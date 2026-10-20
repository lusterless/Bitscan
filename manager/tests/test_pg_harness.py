"""REQ-009, REQ-032: the PostgreSQL 16 harness.

Checks CHK-M0-050/051 and CHK-M1-031, -033 to -035 of the phase test plans.
Unit tests of the spec extraction run without Docker; the rest are ``pg``.
"""

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
