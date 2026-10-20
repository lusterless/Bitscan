"""REQ-020: the migration runner and ``bitscan-manager db migrate`` (TP-M1-04).

Checks CHK-M1-050 to CHK-M1-060 of tests/m1/test-plan.md. PostgreSQL cases run
the installed CLI against a Bootstrap-only container of their own.
"""

import ast
import secrets
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from psycopg import sql

import bitscan_manager

from .conftest import Conn, PgServer, run_cli, write_dsn_file

PKG = Path(bitscan_manager.__file__).resolve().parent
VERSIONS = PKG / "db" / "migrations" / "versions"
MIGRATE = "BITSCAN_MIGRATE_DSN_FILE"
REFUSED_DB = [["db", "downgrade"], ["db", "downgrade", "base"], ["db", "stamp", "head"]]


def migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def _assigned(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value  # type: ignore[assignment]
        if name in targets and value is not None:
            return ast.literal_eval(value)
    raise AssertionError(f"{name} not assigned")


def expected_head() -> str:
    """The head from the files alone: the revision nobody names as down_revision."""
    revs, downs = set(), set()
    for path in migration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        revs.add(str(_assigned(tree, "revision")))
        down = _assigned(tree, "down_revision")
        if down is not None:
            downs.add(str(down))
    heads = revs - downs
    assert len(heads) <= 1, f"more than one head: {heads}"
    return heads.pop() if heads else "base"


def owner_session(server: PgServer) -> Conn:
    conn = server.connect("bitscan_migrate")
    conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier("bitscan_owner")))
    return conn


def snapshot(server: PgServer) -> dict[str, object]:
    """Objects in schema public with owners, plus the Alembic version rows."""
    with owner_session(server) as conn:
        rels = conn.execute(
            "SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner)"
            " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' ORDER BY 1"
        ).fetchall()
        types = conn.execute(
            "SELECT t.typname, t.typtype, pg_get_userbyid(t.typowner)"
            " FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
            " WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'r', 'm')"
            " ORDER BY 1"
        ).fetchall()
        procs = conn.execute(
            "SELECT p.proname, pg_get_userbyid(p.proowner)"
            " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public'"
            " AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid"
            " AND d.deptype = 'e') ORDER BY 1"
        ).fetchall()
        version: list[tuple[object, ...]] = []
        if any(r[0] == "alembic_version" for r in rels):
            version = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    return {"rels": rels, "types": types, "procs": procs, "version": version}


def _dsn_env(tmp_path: Path, dsn: str) -> dict[str, str]:
    return {MIGRATE: str(write_dsn_file(tmp_path, f"dsn-{secrets.token_hex(4)}", dsn))}


def _secret_absent(proc: subprocess.CompletedProcess[str], *secrets_: str) -> None:
    for s in secrets_:
        assert s not in proc.stdout and s not in proc.stderr, "secret in CLI output"


# --- PostgreSQL ---------------------------------------------------------------


@pytest.mark.pg
def test_migrate_from_bootstrap_twice_and_ownership(
    fresh_pg_server: PgServer, tmp_path: Path
) -> None:
    server = fresh_pg_server
    assert snapshot(server)["rels"] == []
    dsn = server.dsn("bitscan_migrate")
    password = dsn.split("password=")[1].split()[0]
    env = _dsn_env(tmp_path, dsn)

    first = run_cli(["db", "migrate"], env)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == expected_head()
    _secret_absent(first, password, dsn)
    after_first = snapshot(server)

    second = run_cli(["db", "migrate"], env)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == expected_head()
    assert snapshot(server) == after_first

    rels = after_first["rels"]
    assert isinstance(rels, list)
    assert ("alembic_version", "r", "bitscan_owner") in rels
    for kind in ("rels", "types", "procs"):
        objs = after_first[kind]
        assert isinstance(objs, list)
        assert all(o[-1] == "bitscan_owner" for o in objs), (kind, objs)
    head = expected_head()
    assert after_first["version"] == ([] if head == "base" else [(head,)])
    with owner_session(server) as conn:
        schema = conn.execute(
            "SELECT table_schema FROM information_schema.tables"
            " WHERE table_name = 'alembic_version'"
        ).fetchall()
    assert schema == [("public",)]


@pytest.mark.pg
def test_app_role_dsn_fails_and_creates_nothing(
    fresh_pg_server: PgServer, tmp_path: Path
) -> None:
    before = snapshot(fresh_pg_server)
    dsn = fresh_pg_server.dsn("bitscan_app")
    proc = run_cli(["db", "migrate"], _dsn_env(tmp_path, dsn))
    assert proc.returncode == 1, proc.stderr
    assert proc.stderr.strip()
    _secret_absent(proc, dsn.split("password=")[1].split()[0])
    assert snapshot(fresh_pg_server) == before


@pytest.mark.pg
def test_wrong_password_fails_without_the_canary(
    pg_server: PgServer, tmp_path: Path
) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    dsn = pg_server.dsn("bitscan_migrate").split("password=")[0] + (
        f"password={canary} sslmode=require"
    )
    proc = run_cli(["db", "migrate"], _dsn_env(tmp_path, dsn))
    assert proc.returncode == 1, proc.stderr
    assert "db migrate:" in proc.stderr
    _secret_absent(proc, canary)


@pytest.mark.pg
@pytest.mark.parametrize("argv", REFUSED_DB, ids=lambda a: " ".join(a))
def test_downgrade_like_commands_change_nothing(
    fresh_pg_server: PgServer, tmp_path: Path, argv: list[str]
) -> None:
    env = _dsn_env(tmp_path, fresh_pg_server.dsn("bitscan_migrate"))
    assert run_cli(["db", "migrate"], env).returncode == 0
    before = snapshot(fresh_pg_server)
    proc = run_cli(argv, env)
    assert proc.returncode == 2
    assert snapshot(fresh_pg_server) == before


# --- local (no Docker) --------------------------------------------------------


def test_unreachable_host_fails_without_the_canary(tmp_path: Path) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    dsn = (
        f"host=127.0.0.1 port=1 dbname=bitscan user=bitscan_migrate"
        f" password={canary} sslmode=require connect_timeout=3"
    )
    proc = run_cli(["db", "migrate"], _dsn_env(tmp_path, dsn), timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.startswith("db migrate:")
    _secret_absent(proc, canary)


@pytest.mark.parametrize(
    "dsn_tail",
    ["", " sslmode=prefer", " sslmode=disable"],
    ids=["none", "prefer", "disable"],
)
def test_dsn_without_tls_is_a_configuration_error(
    tmp_path: Path, dsn_tail: str
) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    dsn = f"host=127.0.0.1 port=1 dbname=bitscan user=m password={canary}{dsn_tail}"
    proc = run_cli(["db", "migrate"], _dsn_env(tmp_path, dsn), timeout=60)
    assert proc.returncode == 2
    assert MIGRATE in proc.stderr
    _secret_absent(proc, canary)


def test_unset_variable_is_named(tmp_path: Path) -> None:
    proc = run_cli(["db", "migrate"], {}, timeout=60)
    assert proc.returncode == 2
    assert MIGRATE in proc.stderr
    assert proc.stdout == ""


def test_migration_files_are_forward_only() -> None:
    names = sorted(p.name for p in VERSIONS.iterdir() if p.suffix == ".py")
    assert "__init__.py" in names
    for path in migration_files():
        assert path.name.startswith("m") and path.stem[1:5].isdigit(), path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert "upgrade" in funcs, path.name
        down = funcs.get("downgrade")
        if down is not None:
            body = [s for s in down.body if not isinstance(s, ast.Expr)]
            assert len(body) == 1 and isinstance(body[0], ast.Raise), path.name


def bind_traps(text: str) -> list[str]:
    """``:word`` that SQLAlchemy ``text()`` would read as a bind parameter.

    A colon after another colon (``::type``) or after a word character is safe.
    """
    found = []
    for i, ch in enumerate(text):
        if ch != ":" or i + 1 >= len(text):
            continue
        nxt, prev = text[i + 1], text[i - 1] if i else ""
        if (
            (nxt.isalpha() or nxt == "_")
            and prev != ":"
            and not (prev.isalnum() or prev == "_")
        ):
            found.append(text[max(0, i - 15) : i + 15].replace("\n", " "))
    return found


def test_bind_trap_scanner() -> None:
    assert bind_traps("SELECT '1'::debversion, now()") == []
    assert bind_traps("ab:cd") == []
    assert bind_traps("-- note: x\nSELECT :name") != []
    assert len(bind_traps('{"all":true} and :x')) == 2


def test_migrations_have_no_bind_parameter_traps() -> None:
    for path in migration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == doc:
                    continue
                assert bind_traps(node.value) == [], (path.name, bind_traps(node.value))


def test_downgrade_functions_raise() -> None:
    import importlib

    for path in migration_files():
        mod = importlib.import_module(
            f"bitscan_manager.db.migrations.versions.{path.stem}"
        )
        if hasattr(mod, "downgrade"):
            with pytest.raises(Exception):  # noqa: B017  # any error is refusal
                mod.downgrade()


def test_offline_sql_mode_is_refused() -> None:
    from alembic import command
    from alembic.config import Config

    from bitscan_manager.db import MIGRATIONS_DIR

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with pytest.raises(RuntimeError, match="offline"):
        command.upgrade(config, "head", sql=True)


def test_wheel_ships_the_migrations(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [
            sys.executable,
            "-m",
            "hatchling",
            "build",
            "-t",
            "wheel",
            "-d",
            str(tmp_path),
        ],
        cwd=PKG.parent,
        check=True,
        capture_output=True,
        timeout=300,
    )
    wheels = list(tmp_path.glob("bitscan_manager-*.whl"))
    assert len(wheels) == 1
    names = set(zipfile.ZipFile(wheels[0]).namelist())
    for rel in (
        "bitscan_manager/db/__init__.py",
        "bitscan_manager/db/migrations/env.py",
        "bitscan_manager/db/migrations/versions/__init__.py",
        *[
            f"bitscan_manager/db/migrations/versions/{p.name}"
            for p in migration_files()
        ],
    ):
        assert rel in names, rel
