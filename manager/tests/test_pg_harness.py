"""REQ-009, REQ-032: the PostgreSQL 16 harness.

Checks CHK-M0-050/051 and CHK-M1-031, -033 to -035 of the phase test plans.
Unit tests of the spec extraction run without Docker; the rest are ``pg``.
"""

from pathlib import Path

import psycopg
import pytest

from .conftest import LOGIN_ROLES, Conn, PgServer
from .spec_sql import RECONNECT, bootstrap

EXTENSIONS = {"pg_trgm", "pgcrypto", "debversion"}

SYNTHETIC = """
**Bootstrap** (text):

```sql
CREATE ROLE a NOLOGIN;
-- a comment
CREATE ROLE b
  LOGIN;
\\c bitscan
ALTER SCHEMA public OWNER TO a;
```
"""


# --- unit: spec extraction (no Docker) -------------------------------------


def test_bootstrap_is_read_from_the_spec() -> None:
    block = bootstrap()
    assert block.on_postgres[0] == "CREATE ROLE bitscan_owner NOLOGIN;"
    assert "CREATE DATABASE bitscan OWNER bitscan_owner;" in block.on_postgres
    assert block.on_bitscan[0] == "ALTER SCHEMA public OWNER TO bitscan_owner;"
    for ext in sorted(EXTENSIONS):
        assert f"CREATE EXTENSION IF NOT EXISTS {ext};" in block.on_bitscan
    assert not any("\\" in s for s in block.on_postgres + block.on_bitscan)
    assert not any(s.lstrip().startswith("--") for s in block.on_bitscan)


def test_bootstrap_follows_the_spec_text() -> None:
    block = bootstrap(SYNTHETIC)
    assert block.on_postgres == ("CREATE ROLE a NOLOGIN;", "CREATE ROLE b\n  LOGIN;")
    assert block.on_bitscan == ("ALTER SCHEMA public OWNER TO a;",)
    changed = bootstrap(SYNTHETIC.replace("ROLE a NOLOGIN", "ROLE z NOLOGIN"))
    assert changed.on_postgres[0] == "CREATE ROLE z NOLOGIN;"


@pytest.mark.parametrize(
    "text",
    [
        SYNTHETIC.replace(RECONNECT, "\\c other"),
        SYNTHETIC.replace(RECONNECT, RECONNECT + "\n\\set x 1"),
        SYNTHETIC.replace(RECONNECT, ""),
        SYNTHETIC.replace("**Bootstrap**", "**Other**"),
        SYNTHETIC.replace("LOGIN;", "LOGIN"),
    ],
    ids=["other-db", "extra-meta", "no-reconnect", "no-heading", "no-semicolon"],
)
def test_bootstrap_rejects_unexpected_text(text: str) -> None:
    with pytest.raises(ValueError):
        bootstrap(text)


# --- PostgreSQL -------------------------------------------------------------


@pytest.mark.pg
def test_server_is_postgresql_16(app_conn: Conn) -> None:
    row = app_conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    assert 160000 <= int(row[0]) <= 169999


@pytest.mark.pg
def test_bootstrap_installed_the_extensions(app_conn: Conn) -> None:
    rows = app_conn.execute("SELECT extname FROM pg_extension").fetchall()
    assert EXTENSIONS <= {r[0] for r in rows}


@pytest.mark.pg
def test_debversion_orders_like_dpkg(app_conn: Conn) -> None:
    row = app_conn.execute(
        "SELECT '1.0~rc1'::debversion < '1.0'::debversion,"
        " '1.0'::debversion < '1.0~rc1'::debversion,"
        " '1.0~rc1' < '1.0'"
    ).fetchone()
    assert row == (True, False, False)


@pytest.mark.pg
def test_bootstrap_roles_and_ownership(owner_conn: Conn) -> None:
    roles = dict(
        (r[0], r[1:])
        for r in owner_conn.execute(
            "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole"
            " FROM pg_roles WHERE rolname LIKE 'bitscan%'"
        ).fetchall()
    )
    assert roles["bitscan_owner"] == (False, False, False, False)
    for role in LOGIN_ROLES:
        assert roles[role] == (True, False, False, False)
    member = owner_conn.execute(
        "SELECT pg_has_role('bitscan_migrate', 'bitscan_owner', 'MEMBER'),"
        " pg_has_role('bitscan_app', 'bitscan_owner', 'MEMBER')"
    ).fetchone()
    assert member == (True, False)
    owners = owner_conn.execute(
        "SELECT pg_get_userbyid(d.datdba), pg_get_userbyid(n.nspowner)"
        " FROM pg_database d, pg_namespace n"
        " WHERE d.datname = 'bitscan' AND n.nspname = 'public'"
    ).fetchone()
    assert owners == ("bitscan_owner", "bitscan_owner")


@pytest.mark.pg
def test_bootstrap_database_and_schema_privileges(owner_conn: Conn) -> None:
    connect = owner_conn.execute(
        "SELECT has_database_privilege('bitscan_app', 'bitscan', 'CONNECT'),"
        " has_database_privilege('bitscan_retention', 'bitscan', 'CONNECT'),"
        " has_database_privilege('bitscan_migrate', 'bitscan', 'CONNECT'),"
        " has_schema_privilege('bitscan_app', 'public', 'USAGE'),"
        " has_schema_privilege('bitscan_retention', 'public', 'USAGE'),"
        " has_schema_privilege('bitscan_app', 'public', 'CREATE')"
    ).fetchone()
    assert connect == (True, True, True, True, True, False)
    public = owner_conn.execute(
        "SELECT count(*) FROM pg_database d, aclexplode(d.datacl) a"
        " WHERE d.datname = 'bitscan' AND a.grantee = 0"
    ).fetchone()
    assert public == (0,)


@pytest.mark.pg
def test_fixtures_are_the_app_roles_and_not_superusers(
    app_conn: Conn, retention_conn: Conn, owner_conn: Conn
) -> None:
    seen = {}
    for conn in (app_conn, retention_conn, owner_conn):
        row = conn.execute(
            "SELECT session_user::text, current_user::text, r.rolsuper"
            " FROM pg_roles r WHERE r.rolname = session_user"
        ).fetchone()
        assert row is not None
        seen[row[0]] = (row[1], row[2])
    assert seen == {
        "bitscan_app": ("bitscan_app", False),
        "bitscan_retention": ("bitscan_retention", False),
        "bitscan_migrate": ("bitscan_owner", False),
    }


@pytest.mark.pg
def test_superuser_dsn_is_never_handed_out(pg_server: PgServer) -> None:
    with pytest.raises(ValueError):
        pg_server.dsn("postgres")


@pytest.mark.pg
def test_every_fixture_connection_uses_tls(
    pg_server: PgServer, app_conn: Conn, retention_conn: Conn, owner_conn: Conn
) -> None:
    for conn in (app_conn, retention_conn, owner_conn):
        assert conn.execute("SHOW ssl").fetchone() == ("on",)
        assert conn.pgconn.ssl_in_use
        assert conn.info.get_parameters()["sslmode"] == "require"
    # Server side: pg_stat_ssl shows a backend only to its own role, and after
    # SET ROLE bitscan_owner that is no longer the session user, so the migrate
    # role is checked on a plain connection.
    with pg_server.connect("bitscan_migrate") as migrate:
        for conn in (app_conn, retention_conn, migrate):
            row = conn.execute(
                "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
            ).fetchone()
            assert row == (True,)


@pytest.mark.pg
def test_connection_without_tls_is_refused(pg_server: PgServer) -> None:
    with pytest.raises(psycopg.OperationalError) as err:
        pg_server.connect("bitscan_app", sslmode="disable")
    assert "no pg_hba.conf entry" in str(err.value)


@pytest.mark.pg
def test_port_is_published_on_localhost_only(pg_server: PgServer) -> None:
    bindings = pg_server.port_bindings["host_config"]["5432/tcp"]
    assert bindings and all(b["HostIp"] == "127.0.0.1" for b in bindings), bindings
    published = pg_server.port_bindings["published"]["5432/tcp"]
    assert published and all(p["HostIp"] == "127.0.0.1" for p in published), published


@pytest.mark.pg
def test_no_superuser_credential_is_reachable(pg_server: PgServer) -> None:
    """testing.md L51: after the Bootstrap, nothing a test holds can act as one."""
    names = {f.name for f in pg_server.__dataclass_fields__.values()}
    assert names == {"host", "port", "port_bindings", "_passwords"}
    assert set(pg_server._passwords) == set(LOGIN_ROLES)
    assert "Env" not in repr(pg_server.port_bindings)
    with pytest.raises(ValueError):
        pg_server.dsn("postgres")


@pytest.mark.pg
def test_reference_database_was_bootstrapped_like_bitscan(
    owner_conn: Conn,
) -> None:
    row = owner_conn.execute(
        "SELECT pg_get_userbyid(datdba),"
        " has_database_privilege('bitscan_migrate', 'bitscan_ref', 'CONNECT'),"
        " has_database_privilege('bitscan_app', 'bitscan_ref', 'CONNECT'),"
        " (SELECT count(*) FROM aclexplode(datacl) a WHERE a.grantee = 0)"
        " FROM pg_database WHERE datname = 'bitscan_ref'"
    ).fetchone()
    assert row == ("bitscan_owner", True, True, 0)


# --- harness review follow-ups (TP-M1-02 review, tester-b) -------------------------


def test_server_args_match_the_dockerfile_cmd() -> None:
    from .conftest import BUILD_CONTEXT, SERVER_ARGS

    text = (BUILD_CONTEXT / "Dockerfile").read_text(encoding="utf-8")
    cmd = text.split("CMD [", 1)[1].split("]", 1)[0]
    backslash = chr(92)  # Dockerfile line continuations
    args = tuple(a.replace(backslash, " ").strip().strip('"') for a in cmd.split(","))
    assert args == SERVER_ARGS


def test_image_tag_is_the_build_context_hash(tmp_path: Path) -> None:
    import shutil

    from .conftest import BUILD_CONTEXT, IMAGE_TAG, context_tag

    assert IMAGE_TAG == context_tag(BUILD_CONTEXT)
    assert IMAGE_TAG.startswith("bitscan-test-postgres:16-")
    copy = tmp_path / "ctx"
    shutil.copytree(BUILD_CONTEXT, copy)
    assert context_tag(copy) == IMAGE_TAG  # location does not matter
    dockerfile = copy / "Dockerfile"
    data = bytearray(dockerfile.read_bytes())
    data[-2] = data[-2] ^ 1  # one byte changed
    dockerfile.write_bytes(bytes(data))
    assert context_tag(copy) != IMAGE_TAG


def test_password_redaction() -> None:
    from .conftest import redact_passwords

    text = "a|LOG:  statement: ALTER ROLE \"bitscan_app\" PASSWORD 'abc123'\nok"
    assert redact_passwords(text) == (
        'a|LOG:  statement: ALTER ROLE "bitscan_app" PASSWORD <redacted>\nok'
    )


def test_no_test_module_but_conftest_imports_docker() -> None:
    import ast
    from pathlib import Path

    here = Path(__file__).resolve().parent
    offenders = []
    for path in sorted(here.rglob("*.py")):
        if path == here / "conftest.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in ("docker", "testcontainers"):
                    offenders.append((path.name, name))
    assert offenders == []


@pytest.mark.pg
def test_role_passwords_are_random_per_container(
    pg_server: PgServer, fresh_pg_server: PgServer
) -> None:
    a, b = dict(pg_server._passwords), dict(fresh_pg_server._passwords)
    for pw in [*a.values(), *b.values()]:
        assert len(pw) == 32 and all(c in "0123456789abcdef" for c in pw)
    assert len(set(a.values())) == 3 and len(set(b.values())) == 3
    assert not set(a.values()) & set(b.values())


# The only superuser statements allowed besides the planned ones, exactly as
# logged: the image entrypoint's database check and Testcontainers' probe. They
# must come before the first app-role connection.
ALLOWED_THIRD_PARTY = frozenset(
    {
        "SELECT 1 FROM pg_database WHERE datname = 'postgres' ;",
        "select version();",
    }
)
LOG_MARKERS = ("LOG:  statement: ", "LOG:  execute ")
NL = chr(10)


def superuser_log_problems(text: str, planned: list[str]) -> list[str]:
    """Problems in a log written with log_statement=all and log_line_prefix=%u|.

    Simple-protocol statements ("statement:") and extended-protocol ones
    ("execute <name>:") are both collected. Allowed third-party statements match
    by exact equality, and nothing may run as the superuser after the first
    connection of an app role.
    """
    entries: list[tuple[int, str]] = []
    first_app: int | None = None
    for no, line in enumerate(text.split(NL)):
        user, sep, rest = line.partition("|")
        if not sep:
            continue
        if first_app is None and "connection authorized: user=bitscan_" in rest:
            first_app = no
        if user != "postgres":
            continue
        for marker in LOG_MARKERS:
            if marker in rest:
                body = rest.split(marker, 1)[1]
                if marker.endswith("execute "):
                    body = body.split(": ", 1)[1] if ": " in body else body
                entries.append((no, body.strip()))
    problems = []
    if first_app is None:
        problems.append("no app-role connection in the log")
    harness = []
    for no, body in entries:
        if first_app is not None and no > first_app:
            problems.append(f"superuser statement after the bootstrap: {body}")
        if body not in ALLOWED_THIRD_PARTY:
            harness.append(body)
    if harness != planned:
        problems.append(
            "superuser statements differ from the plan: " + " | ".join(harness)
        )
    return problems


SYNTHETIC_PLAN = ["CREATE ROLE a NOLOGIN;", 'ALTER ROLE "a" PASSWORD <redacted>']
SYNTHETIC_LOG = NL.join(
    [
        "postgres|LOG:  statement: "
        "SELECT 1 FROM pg_database WHERE datname = 'postgres' ;",
        "postgres|LOG:  statement: select version();",
        "postgres|LOG:  statement: CREATE ROLE a NOLOGIN;",
        'postgres|LOG:  statement: ALTER ROLE "a" PASSWORD <redacted>',
        "bitscan_app|LOG:  connection authorized: user=bitscan_app database=bitscan",
        "bitscan_app|LOG:  execute <unnamed>: SELECT $1::int",
    ]
)
APP_CONNECT = "bitscan_app|LOG:  connection"


@pytest.mark.parametrize(
    ("label", "log", "red"),
    [
        ("clean", SYNTHETIC_LOG, False),
        (
            "parameterised superuser query after the bootstrap",
            SYNTHETIC_LOG + NL + "postgres|LOG:  execute <unnamed>: SELECT $1",
            True,
        ),
        (
            "simple superuser query after the bootstrap",
            SYNTHETIC_LOG + NL + "postgres|LOG:  statement: SELECT 2",
            True,
        ),
        (
            "allowed statement smuggling a GRANT",
            SYNTHETIC_LOG.replace(
                "select version();", "select version(); GRANT ALL ON DATABASE x TO y"
            ),
            True,
        ),
        (
            "allowed statement after the bootstrap",
            SYNTHETIC_LOG + NL + "postgres|LOG:  statement: select version();",
            True,
        ),
        (
            "extra superuser statement inside the bootstrap",
            SYNTHETIC_LOG.replace(
                APP_CONNECT, "postgres|LOG:  statement: SELECT 42" + NL + APP_CONNECT
            ),
            True,
        ),
        ("no app connection", SYNTHETIC_LOG.split(NL + "bitscan_app")[0], True),
    ],
)
def test_superuser_log_checker(label: str, log: str, red: bool) -> None:
    assert bool(superuser_log_problems(log, SYNTHETIC_PLAN)) is red, label


@pytest.mark.pg
def test_superuser_statements_are_only_the_planned_ones() -> None:
    from .conftest import REFERENCE_DB, bootstrapped_server
    from .spec_sql import bootstrap

    log: list[str] = []
    args = (
        "-c",
        "log_statement=all",
        "-c",
        "log_connections=on",
        "-c",
        "log_line_prefix=%u|",
    )
    with bootstrapped_server(extra_args=args, log=log) as server:
        with server.connect("bitscan_app") as conn:
            conn.execute("SELECT %s::int", (1,))
    assert "PASSWORD '" not in log[0]
    block = bootstrap()
    ref_db = [
        s.replace("DATABASE bitscan ", f"DATABASE {REFERENCE_DB} ")
        for s in block.on_postgres
        if not s.startswith("CREATE ROLE")
    ]
    planned = [
        *block.on_postgres,
        *[f'ALTER ROLE "{r}" PASSWORD <redacted>' for r in LOGIN_ROLES],
        *block.on_bitscan,
        *ref_db,
        *block.on_bitscan,
    ]
    problems = superuser_log_problems(log[0], planned)
    assert problems == [], " | ".join(problems)
