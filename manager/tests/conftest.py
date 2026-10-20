"""PostgreSQL 16 Testcontainers harness (TASK-003, TP-M1-02; REQ-009, REQ-032).

One container per session, built from ``tests/postgres/Dockerfile`` (``pg_trgm``,
``pgcrypto``, ``debversion``, TLS on, ``hostssl`` only), published on 127.0.0.1
only. The harness then runs, as the container superuser and nothing else, all
before it hands anything to a test:

1. the TS §5.2 Bootstrap block, read verbatim from the spec (``spec_sql``), with
   ``\\c bitscan`` carried out as a reconnect;
2. ``ALTER ROLE ... PASSWORD`` for the three LOGIN roles (test-only, random per run);
3. the database half of the Bootstrap again for the reference database
   ``bitscan_ref`` (question #40), with only the name changed.

The superuser password is never stored where a test can reach it.

Fixtures hand out connections only as ``bitscan_app``, ``bitscan_retention`` and
``bitscan_migrate`` (``owner_conn`` adds ``SET ROLE bitscan_owner``), always with
``sslmode=require``, and each checks that its role is not a superuser.
``migrated_db`` runs the installed ``bitscan-manager db migrate`` CLI.

Without Docker the ``pg`` tests are skipped with "not run: Docker unavailable",
unless ``CI=true``, where the same condition fails the run (PD-15).
"""

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

BUILD_CONTEXT = Path(__file__).resolve().parent / "postgres"


def context_tag(context: Path = BUILD_CONTEXT) -> str:
    """Tag the test image by its build context, so trees never retag each other."""
    digest = hashlib.sha256()
    for path in sorted(p for p in context.rglob("*") if p.is_file()):
        digest.update(path.relative_to(context).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return f"bitscan-test-postgres:16-{digest.hexdigest()[:12]}"


IMAGE_TAG = context_tag()
# The Dockerfile CMD, repeated only when a test adds server options (log test).
SERVER_ARGS = (
    "postgres",
    "-c", "ssl=on",
    "-c", "ssl_cert_file=/etc/postgresql/tls/server.crt",
    "-c", "ssl_key_file=/etc/postgresql/tls/server.key",
    "-c", "hba_file=/etc/postgresql/pg_hba.conf",
)  # fmt: skip
NOT_RUN = "not run: Docker unavailable"
LOGIN_ROLES = ("bitscan_app", "bitscan_retention", "bitscan_migrate")
LOCALHOST = "127.0.0.1"

Conn = psycopg.Connection[Any]


def _docker_problem() -> str | None:
    try:
        from testcontainers.core.docker_client import DockerClient

        DockerClient().client.ping()
    except Exception as exc:  # any failure to reach the daemon means "no Docker"
        return f"{type(exc).__name__}: {exc}"
    return None


@pytest.hookimpl(trylast=True)  # after -m / -k deselection
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    pg_items = [item for item in items if item.get_closest_marker("pg")]
    if not pg_items:
        return
    problem = _docker_problem()
    if problem is None:
        return
    if os.environ.get("CI", "").lower() == "true":
        pytest.exit(f"{NOT_RUN} and CI=true: PostgreSQL tests must run ({problem})", 1)
    for item in pg_items:
        item.add_marker(pytest.mark.skip(reason=NOT_RUN))


@dataclass(frozen=True)
class PgServer:
    """What tests get: the three LOGIN roles' DSNs and the port bindings.

    No superuser credential is reachable from here (testing.md L51): the
    container object (whose environment holds it) is not kept.
    """

    host: str
    port: int
    port_bindings: Mapping[str, Any] = field(repr=False)
    _passwords: Mapping[str, str] = field(repr=False)

    def dsn(self, role: str, dbname: str = "bitscan", sslmode: str = "require") -> str:
        if role not in LOGIN_ROLES:
            raise ValueError(f"tests connect only as {LOGIN_ROLES}, not {role!r}")
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=dbname,
            user=role,
            password=self._passwords[role],
            sslmode=sslmode,
            connect_timeout=10,
        )

    def connect(
        self, role: str, *, sslmode: str = "require", dbname: str = "bitscan", **kw: Any
    ) -> Conn:
        return psycopg.connect(
            self.dsn(role, dbname=dbname, sslmode=sslmode), autocommit=True, **kw
        )


def _superuser(host: str, port: int, password: str, dbname: str) -> Conn:
    return psycopg.connect(
        host=host,
        port=port,
        user="postgres",
        password=password,
        dbname=dbname,
        sslmode="require",
        autocommit=True,
    )


def _run_bootstrap(
    host: str, port: int, su_password: str, roles: Mapping[str, str]
) -> None:
    # Imported here so the hook above works when conftest is loaded on its own
    # (tests/test_conftest_hook.py copies it into a pytester directory).
    from .spec_sql import bootstrap

    block = bootstrap()
    # Statements come from the spec file, not from code; bytes keep them verbatim.
    with _superuser(host, port, su_password, "postgres") as conn:
        for statement in block.on_postgres:
            conn.execute(statement.encode())
        for role, password in roles.items():
            conn.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
    with _superuser(host, port, su_password, "bitscan") as conn:
        for statement in block.on_bitscan:
            conn.execute(statement.encode())
    _bootstrap_reference_db(host, port, su_password)


REFERENCE_DB = "bitscan_ref"


def _bootstrap_reference_db(host: str, port: int, su_password: str) -> None:
    """Question #40, Bootstrap phase: the scratch reference database.

    The database half of the TS §5.2 Bootstrap (the roles already exist), with
    only the database name changed, run once before any test or migration. The
    spec DDL is applied later by ``reference_db``, as bitscan_owner only.
    """
    from .spec_sql import bootstrap

    block = bootstrap()
    for_db = []
    for statement in block.on_postgres:
        if statement.startswith("CREATE ROLE"):
            continue
        renamed = statement.replace("DATABASE bitscan ", f"DATABASE {REFERENCE_DB} ")
        assert renamed != statement, statement
        for_db.append(renamed)
    with _superuser(host, port, su_password, "postgres") as conn:
        for statement in for_db:
            conn.execute(statement.encode())
    with _superuser(host, port, su_password, REFERENCE_DB) as conn:
        for statement in block.on_bitscan:
            conn.execute(statement.encode())


@pytest.fixture(scope="session")
def reference_db(pg_server: PgServer) -> PgServer:
    """``pg_server`` with the TS §5.2 DDL and view applied to ``bitscan_ref``.

    Runs as bitscan_migrate with SET ROLE bitscan_owner; never as a superuser,
    and never on the database under test (#40).
    """
    from .schema_diff import reference_sql

    ddl, view = reference_sql()
    with pg_server.connect("bitscan_migrate", dbname=REFERENCE_DB) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier("bitscan_owner")))
        conn.execute(ddl.encode())
        conn.execute(view.encode())
    return pg_server


def redact_passwords(text: str) -> str:
    """Drop everything after ``PASSWORD`` on a line (role passwords in a log)."""
    out = []
    for line in text.split("\n"):
        cut = line.upper().find("PASSWORD")
        out.append(line if cut < 0 else line[: cut + 8] + " <redacted>")
    return "\n".join(out)


@contextmanager
def bootstrapped_server(
    extra_args: Sequence[str] = (), log: list[str] | None = None
) -> Iterator[PgServer]:
    """A new container with only the TS §5.2 Bootstrap applied.

    ``extra_args`` adds server options (``-c name=value``); ``log``, if given,
    receives the container's log at teardown with passwords redacted. Neither
    exposes the container or the superuser password.
    """
    from testcontainers.community.postgres import PostgresContainer
    from testcontainers.core.image import DockerImage

    su_password = secrets.token_hex(16)
    roles = {role: secrets.token_hex(16) for role in LOGIN_ROLES}
    with DockerImage(path=BUILD_CONTEXT, tag=IMAGE_TAG, clean_up=False) as image:
        pg = PostgresContainer(
            image=str(image),
            username="postgres",
            password=su_password,
            dbname="postgres",
            driver=None,
        )
        if extra_args:
            pg.with_command([*SERVER_ARGS, *extra_args])
        # Publish 5432 on 127.0.0.1 only (REQ-032 (4)); docker-py takes (ip, port).
        cast(dict[str, Any], pg.ports)["5432"] = (LOCALHOST, None)
        with pg:
            port = pg.get_exposed_port(5432)
            _run_bootstrap(LOCALHOST, port, su_password, roles)
            attrs = pg.get_wrapped_container().attrs
            bindings = {
                "host_config": attrs["HostConfig"]["PortBindings"],
                "published": attrs["NetworkSettings"]["Ports"],
            }
            try:
                yield PgServer(LOCALHOST, port, bindings, roles)
            finally:
                if log is not None:
                    out, err = pg.get_logs()
                    text = (out or b"").decode(errors="replace")
                    text += (err or b"").decode(errors="replace")
                    log.append(redact_passwords(text.replace(su_password, "<su>")))


@pytest.fixture(scope="session")
def pg_server() -> Iterator[PgServer]:
    with bootstrapped_server() as server:
        yield server


@pytest.fixture
def fresh_pg_server() -> Iterator[PgServer]:
    """A Bootstrap-only server of its own, for tests that must start from it."""
    with bootstrapped_server() as server:
        yield server


def cli_path() -> str:
    found = shutil.which("bitscan-manager", path=str(Path(sys.executable).parent))
    assert found, "console script bitscan-manager is not installed in this venv"
    return found


def run_cli(
    argv: Sequence[str], env: Mapping[str, str], timeout: float = 300
) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    return subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [cli_path(), *argv],
        capture_output=True,
        text=True,
        env={**base, **env},
        timeout=timeout,
    )


def write_dsn_file(directory: Path, name: str, dsn: str) -> Path:
    path = directory / name
    path.write_text(dsn + "\n", encoding="utf-8")
    return path


def migrate_to(server: PgServer, revision: str) -> None:
    """Upgrade a database to one revision (not head), for states the CLI never
    stops at, such as REQ-026 (7): as bitscan_migrate with SET ROLE bitscan_owner,
    like the runner. The CLI path to head is ``migrated_db``.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from bitscan_manager.db import MIGRATIONS_DIR

    dsn = server.dsn("bitscan_migrate")
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: cast(Any, psycopg.connect(dsn)),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SET ROLE bitscan_owner"))
            conn.commit()
            config = Config()
            config.set_main_option("script_location", str(MIGRATIONS_DIR))
            config.attributes["connection"] = conn
            command.upgrade(config, revision)
            conn.commit()
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def migrated_db(
    pg_server: PgServer, tmp_path_factory: pytest.TempPathFactory
) -> PgServer:
    creds = tmp_path_factory.mktemp("credentials")
    dsn_file = write_dsn_file(creds, "migrate_dsn", pg_server.dsn("bitscan_migrate"))
    proc = run_cli(["db", "migrate"], {"BITSCAN_MIGRATE_DSN_FILE": str(dsn_file)})
    assert proc.returncode == 0, f"db migrate failed: {proc.stderr}"
    return pg_server


def _role_conn(
    server: PgServer, role: str, set_role: str | None = None
) -> Iterator[Conn]:
    with server.connect(role) as conn:
        row = conn.execute(
            "SELECT session_user::text, rolsuper FROM pg_roles"
            " WHERE rolname = session_user"
        ).fetchone()
        assert row == (role, False), row
        if set_role is not None:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(set_role)))
        yield conn


@pytest.fixture
def app_conn(pg_server: PgServer) -> Iterator[Conn]:
    yield from _role_conn(pg_server, "bitscan_app")


@pytest.fixture
def retention_conn(pg_server: PgServer) -> Iterator[Conn]:
    yield from _role_conn(pg_server, "bitscan_retention")


@pytest.fixture
def owner_conn(pg_server: PgServer) -> Iterator[Conn]:
    """``bitscan_migrate`` with ``SET ROLE bitscan_owner`` (TP-M1-05 to -09)."""
    yield from _role_conn(pg_server, "bitscan_migrate", set_role="bitscan_owner")
