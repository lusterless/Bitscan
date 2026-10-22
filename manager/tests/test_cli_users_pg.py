"""TASK-046: server CLI `bitscan-manager users …` on PostgreSQL.

Checks CHK-M2-265 to CHK-M2-273 of tests/m2/test-plan.md (TP-M2-23). TS §8.7
L1347 (run as root; DSN from /etc/bitscan/secrets/app.dsn), TS §6.2 L1081
(create-api-token prints a token once), L1089 (create-admin: an admin with no
TOTP, whose first sign-in is restricted), L1090 (reset-totp alerts), REQ-058,
#7 (password never from argv or the environment; TTY prompts twice, else one
stdin line), #47 (e) (--name, --days 1-365, default 90), #50 (actor
cli:root), #51.
"""

import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from bitscan_manager.auth.passwords import hash_password, verify_password
from bitscan_manager.auth.tokens import token_hash

from .canary import new_canary, sweep
from .conftest import PgServer

pytestmark = pytest.mark.pg
PW = "cli admin pass " + "word"
CANARY_DB = new_canary("dsnpw")


@pytest.fixture
def dsn_file(migrated_db: PgServer, tmp_path: Path) -> Path:
    path = tmp_path / "app.dsn"
    path.write_text(migrated_db.dsn("bitscan_app") + "\n", encoding="utf-8")
    return path


def run(
    argv: list[str],
    dsn: Path,
    stdin: str = "",
    env_extra: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    """The CLI in a subprocess with stdin not a TTY, pointed at our DSN file."""
    code = (
        "import sys, pathlib\n"
        "from bitscan_manager.cli.users import users_main\n"
        f"sys.exit(users_main(sys.argv[1:], dsn_file=pathlib.Path({str(dsn)!r})))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    env.update(env_extra or {})
    return subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code, *argv],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def conn(server: PgServer) -> psycopg.Connection[Any]:
    return psycopg.connect(server.dsn("bitscan_app"), autocommit=True)


def user_row(server: PgServer, name: str) -> dict[str, Any] | None:
    with conn(server) as c:
        cur = c.execute("SELECT * FROM app_user WHERE username = %s", (name,))
        cols = [d.name for d in cur.description or []]
        values = cur.fetchone()
    return None if values is None else dict(zip(cols, values, strict=True))


def new_name(prefix: str = "cli") -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def entries(server: PgServer, target: str) -> list[tuple[str, str, Any]]:
    with conn(server) as c:
        rows = c.execute(
            "SELECT actor, action, detail FROM audit_log WHERE target = %s"
            " ORDER BY audit_id",
            (target,),
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ------------------------------------------------------------ CHK-M2-265


def test_create_admin_creates_an_admin_without_totp(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = new_name("adm")
    proc = run(["create-admin", name], dsn_file, stdin=PW + "\n")
    assert proc.returncode == 0, proc.stderr
    row = user_row(migrated_db, name)
    assert row is not None
    assert row["role"] == "admin" and row["totp_secret_enc"] is None
    assert row["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(row["password_hash"], PW)
    assert PW not in proc.stdout + proc.stderr
    log = entries(migrated_db, f"user:{row['user_id']}")
    assert [(a, act) for a, act, _ in log] == [("cli:root", "user.create")]
    assert log[0][2]["alert_kind"] == "admin_created"


def test_existing_username_exits_non_zero_with_no_change(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = new_name("dup")
    assert run(["create-admin", name], dsn_file, stdin=PW + "\n").returncode == 0
    before = user_row(migrated_db, name)
    proc = run(["create-admin", name], dsn_file, stdin="another pass " + "word\n")
    assert proc.returncode == 1 and "already taken" in proc.stderr
    assert user_row(migrated_db, name) == before


@contextmanager
def app_client(server: PgServer) -> Iterator[Any]:
    """The real app on the migrated database (fake vault cipher and sink gate)."""
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from bitscan_manager.api.ratelimit import RateLimiter
    from bitscan_manager.app import create_app
    from bitscan_manager.db.pool import AppDatabase
    from bitscan_manager.runtime import Runtime, SystemClock

    from .test_totp_enrol import Cipher, Gate

    db = AppDatabase(SecretStr(server.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    clock = SystemClock()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    try:
        with TestClient(create_app(rt), client=("10.1.0.9", 1)) as c:
            yield c
    finally:
        db.close()


def test_first_sign_in_of_a_cli_admin_is_restricted(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = new_name("first")
    assert run(["create-admin", name], dsn_file, stdin=PW + "\n").returncode == 0
    with app_client(migrated_db) as c:
        resp = c.post("/api/v1/auth/login", json={"username": name, "password": PW})
        assert resp.status_code == 200 and resp.json()["totp_verified"] is False
        tok = resp.json()["token"]
        refused = c.get(
            "/api/v1/api-tokens", headers={"Authorization": f"Bearer {tok}"}
        )
        assert refused.status_code == 403
        assert refused.json()["type"] == "totp_enrolment_required"


# ------------------------------------------------------------ CHK-M2-266


@pytest.mark.parametrize("pw", ["a" * 11, "x" * 1025, ""])
def test_create_admin_password_rules(
    migrated_db: PgServer, dsn_file: Path, pw: str
) -> None:
    name = new_name("rule")
    proc = run(["create-admin", name], dsn_file, stdin=pw + "\n")
    assert proc.returncode == 1
    assert user_row(migrated_db, name) is None


def test_password_is_never_taken_from_argv_or_the_environment(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = new_name("argv")
    proc = run(["create-admin", name, "--password", PW], dsn_file, stdin="")
    assert proc.returncode == 2  # unknown option
    assert user_row(migrated_db, name) is None
    env = {
        k: PW
        for k in (
            "BITSCAN_ADMIN_PASSWORD",
            "PASSWORD",
            "BITSCAN_PASSWORD",
            "ADMIN_PASSWORD",
        )
    }
    proc = run(["create-admin", name], dsn_file, stdin="", env_extra=env)
    assert proc.returncode == 1  # empty stdin: no password, the environment is ignored
    assert user_row(migrated_db, name) is None


# ------------------------------------------------------------ CHK-M2-267


def make_user(server: PgServer, role: str = "operator", disabled: bool = False) -> str:
    name = new_name("u")
    with conn(server) as c:
        c.execute(
            "INSERT INTO app_user (username, password_hash, role, disabled)"
            " VALUES (%s, %s, %s::user_role, %s)",
            (name, hash_password(PW), role, disabled),
        )
    return name


def test_create_api_token_prints_one_token_and_stores_only_its_hash(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = make_user(migrated_db)
    before = datetime.now(UTC)
    proc = run(["create-api-token", name, "--name", "ci"], dsn_file)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    tok = lines[0]
    assert tok.startswith("bsk_") and len(tok) == 47
    assert tok not in proc.stderr
    with conn(migrated_db) as c:
        row = c.execute(
            "SELECT t.token_hash, t.name, t.expires_at, t.totp_verified, t.kind"
            " FROM user_token t JOIN app_user u USING (user_id) WHERE u.username = %s",
            (name,),
        ).fetchone()
        dump = repr(c.execute("SELECT * FROM user_token").fetchall())
        dump += repr(c.execute("SELECT * FROM audit_log").fetchall())
    assert row is not None
    assert row[0] == token_hash(tok) and row[1] == "ci" and row[3] is False
    assert row[4] == "api"
    assert abs((row[2] - before) - timedelta(days=90)) < timedelta(minutes=5)
    assert tok not in dump and tok[4:] not in dump
    with app_client(migrated_db) as c:  # the printed token works on the API
        listed = c.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {tok}"})
        assert listed.status_code == 200, listed.text
        assert [i["name"] for i in listed.json()["items"]] == ["ci"]
        bad = tok[:-1] + ("B" if tok.endswith("A") else "A")
        wrong = c.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"})
        assert wrong.status_code == 401


@pytest.mark.parametrize(
    ("args", "ok"),
    [
        (["--days", "365"], True),
        (["--days", "1"], True),
        (["--days", "366"], False),
        (["--days", "0"], False),
        (["--name", "x" * 65], False),
        (["--days", "abc"], False),
    ],
)
def test_create_api_token_options(
    migrated_db: PgServer, dsn_file: Path, args: list[str], ok: bool
) -> None:
    name = make_user(migrated_db)
    proc = run(["create-api-token", name, *args], dsn_file)
    with conn(migrated_db) as c:
        n = c.execute(
            "SELECT count(*) FROM user_token t JOIN app_user u USING (user_id)"
            " WHERE u.username = %s",
            (name,),
        ).fetchone()
    if ok:
        assert proc.returncode == 0 and n == (1,)
    else:
        assert proc.returncode != 0 and n == (0,) and proc.stdout == ""


@pytest.mark.parametrize("who", ["unknown", "disabled"])
def test_create_api_token_for_unknown_or_disabled_user(
    migrated_db: PgServer, dsn_file: Path, who: str
) -> None:
    name = (
        new_name("ghost") if who == "unknown" else make_user(migrated_db, disabled=True)
    )
    proc = run(["create-api-token", name], dsn_file)
    assert proc.returncode == 1 and proc.stdout == ""
    with conn(migrated_db) as c:
        n = c.execute(
            "SELECT count(*) FROM user_token t JOIN app_user u USING (user_id)"
            " WHERE u.username = %s",
            (name,),
        ).fetchone()
    assert n in ((0,), None)


# ------------------------------------------------------------ CHK-M2-268


def test_reset_totp_clears_it_ends_sessions_and_alerts(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    name = make_user(migrated_db, role="admin")
    with conn(migrated_db) as c:
        uid = c.execute(
            "UPDATE app_user SET totp_secret_enc = 'enc:00', totp_last_step = 9"
            " WHERE username = %s RETURNING user_id",
            (name,),
        ).fetchone()
        assert uid is not None
        c.execute(
            "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
            " expires_at) VALUES (%s, 'session', %s, true, now() + interval '1 day')",
            (uid[0], "a" * 64),
        )
        c.execute(
            "INSERT INTO user_token (user_id, kind, token_hash, expires_at)"
            " VALUES (%s, 'api', %s, now() + interval '9 day')",
            (uid[0], "b" * 64),
        )
    proc = run(["reset-totp", name], dsn_file)
    assert proc.returncode == 0, proc.stderr
    row = user_row(migrated_db, name)
    assert row is not None and (row["totp_secret_enc"], row["totp_last_step"]) == (
        None,
        None,
    )
    with conn(migrated_db) as c:
        states = dict(
            c.execute(
                "SELECT kind, revoked_at IS NOT NULL FROM user_token"
                " WHERE user_id = %s",
                (uid[0],),
            ).fetchall()
        )
    assert states == {"session": True, "api": False}
    log = entries(migrated_db, f"user:{uid[0]}")
    assert log[-1][0] == "cli:root" and log[-1][1] == "user.totp_reset"
    assert log[-1][2]["alert_kind"] == "totp_reset"


# ------------------------------------------------------------ CHK-M2-269


@pytest.mark.parametrize(
    "case", ["missing", "unreadable", "empty", "disable", "no-sslmode", "garbage"]
)
def test_bad_dsn_files_exit_2_naming_the_path_without_secrets(
    migrated_db: PgServer, tmp_path: Path, case: str
) -> None:
    path = tmp_path / f"{case}.dsn"
    good = migrated_db.dsn("bitscan_app")
    pw = good.split("password=")[1].split(" ")[0]
    dsn_canary = good.replace(pw, CANARY_DB)
    if case == "empty":
        path.write_text("")
    elif case == "disable":
        path.write_text(dsn_canary.replace("sslmode=require", "sslmode=disable"))
    elif case == "no-sslmode":
        path.write_text(dsn_canary.replace(" sslmode=require", ""))
    elif case == "garbage":
        path.write_text(f"host='unterminated password={CANARY_DB}")
    elif case == "unreadable":
        # A folder cannot be read as a file, even by root (the CLI runs as root,
        # where chmod 0 does not stop a read).
        path.mkdir()
        (path / "inner.dsn").write_text(dsn_canary)
    proc = run(["create-api-token", "anyone"], path)
    assert proc.returncode == 2, proc.stderr
    assert str(path) in proc.stderr
    assert sweep([CANARY_DB, pw], proc.stdout, proc.stderr) == []


# ------------------------------------------------------- CHK-M2-270, -271


PROBE_PORT = 9  # discard; nothing listens there in the test environment


def test_only_postgresql_is_contacted(migrated_db: PgServer, dsn_file: Path) -> None:
    """A sys.addaudithook recorder (socket.connect, socket.getaddrinfo).

    psycopg reaches PostgreSQL through libpq in C, which raises no Python audit
    event, so a correct CLI records nothing of its own; any Python-level
    connect or lookup (vault, sink, HTTP) must name the PostgreSQL port. After
    the command the subprocess makes one probe connect to PROBE_PORT, which the
    recorder must see: that proves the recorder would catch a connect.
    """
    name = make_user(migrated_db)
    code = (
        "import sys, json, pathlib, socket\n"
        "seen = []\n"
        "def hook(event, args):\n"
        "    if event == 'socket.connect':\n"
        "        seen.append(['connect', repr(args[1])])\n"
        "    elif event == 'socket.getaddrinfo':\n"
        "        seen.append(['getaddrinfo', repr(args[:2])])\n"
        "sys.addaudithook(hook)\n"
        "from bitscan_manager.cli.users import users_main\n"
        f"dsn = pathlib.Path({str(dsn_file)!r})\n"
        f"rc = users_main(['create-api-token', {name!r}], dsn_file=dsn)\n"
        "cli_seen = list(seen)\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(2)\n"
        "try:\n"
        f"    s.connect(('127.0.0.1', {PROBE_PORT}))\n"
        "except OSError:\n"
        "    pass\n"
        "finally:\n"
        "    s.close()\n"
        "probe = seen[len(cli_seen):]\n"
        "print(json.dumps({'rc': rc, 'cli': cli_seen, 'probe': probe}),"
        " file=sys.stderr)\n"
    )
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    out = json.loads(proc.stderr.strip().splitlines()[-1])
    assert out["rc"] == 0, proc.stderr
    assert out["probe"] == [["connect", f"('127.0.0.1', {PROBE_PORT})"]]
    for kind, target in out["cli"]:
        assert str(migrated_db.port) in target, (kind, target)
    with conn(migrated_db) as c:  # PostgreSQL was reached: the token row exists
        n = c.execute(
            "SELECT count(*) FROM user_token t JOIN app_user u USING (user_id)"
            " WHERE u.username = %s",
            (name,),
        ).fetchone()
    assert n == (1,)


def test_database_errors_name_only_the_error_type(
    migrated_db: PgServer, tmp_path: Path
) -> None:
    """A well-formed TLS DSN that the server refuses: exit 1, no DSN content.

    The user name and password are canaries; PostgreSQL's refusal names the user,
    so a CLI that printed the exception text would leak file content.
    """
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    user_canary = new_canary("dsnuser")
    params = conninfo_to_dict(migrated_db.dsn("bitscan_app"))
    params.update(user=user_canary, password=CANARY_DB)
    path = tmp_path / "refused.dsn"
    path.write_text(make_conninfo("", **params) + "\n", encoding="utf-8")
    proc = run(["create-api-token", "anyone"], path)
    assert proc.returncode == 1, proc.stderr
    assert proc.stdout == ""
    assert "database error (" in proc.stderr
    assert sweep([CANARY_DB, user_canary], proc.stdout, proc.stderr) == []


def test_each_command_audits_with_actor_cli_root(
    migrated_db: PgServer, dsn_file: Path
) -> None:
    admin = new_name("audit")
    run(["create-admin", admin], dsn_file, stdin=PW + "\n")
    other = make_user(migrated_db)
    run(["create-api-token", other], dsn_file)
    with conn(migrated_db) as c:
        rows = c.execute(
            "SELECT actor, action, detail FROM audit_log"
            " WHERE actor = 'cli:root' ORDER BY audit_id DESC LIMIT 2"
        ).fetchall()
    kinds = {r[1]: r[2]["alert_kind"] for r in rows}
    assert kinds == {
        "user.create": "admin_created",
        "api_token.create": "api_token_created",
    }


ALERT_OF = {
    "user.create": "admin_created",
    "api_token.create": "api_token_created",
    "user.totp_reset": "totp_reset",
}


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def send(self, records: Any) -> None:
        self.records.extend(records)

    def close(self) -> None:
        return None


def test_cli_entries_reach_the_sink_through_the_serve_shipper(
    migrated_db: PgServer, dsn_file: Path, tmp_path: Path
) -> None:
    """#51: the CLI writes audit_log only; serve's Shipper (the one serve runs)
    reads the committed rows and delivers them, alert marker included."""
    from pydantic import SecretStr

    from bitscan_manager.db.pool import AppDatabase
    from bitscan_manager.runtime import SystemClock
    from bitscan_manager.services.audit.disk_queue import DiskQueue
    from bitscan_manager.services.audit.shipper import (
        DbOutageAudit,
        PgAuditTail,
        Shipper,
    )

    admin = new_name("ship")
    assert run(["create-admin", admin], dsn_file, stdin=PW + "\n").returncode == 0
    other = make_user(migrated_db, role="admin")
    assert run(["create-api-token", other], dsn_file).returncode == 0
    assert run(["reset-totp", other], dsn_file).returncode == 0
    with conn(migrated_db) as c:
        ids = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT audit_id, action FROM audit_log WHERE actor = 'cli:root'"
                " ORDER BY audit_id DESC LIMIT 3"
            ).fetchall()
        }
    assert sorted(ids.values()) == [
        "api_token.create",
        "user.create",
        "user.totp_reset",
    ]
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    sink = RecordingSink()
    shipper = Shipper(
        PgAuditTail(db),
        DiskQueue(tmp_path / "q"),
        sink,
        SystemClock(),
        DbOutageAudit(db),
    )
    try:
        for _ in range(50):  # a shared database: other tests' entries come first
            shipper.run_once()
            if set(ids) <= {r.audit_id for r in sink.records}:
                break
    finally:
        db.close()
    got = {r.audit_id: r for r in sink.records if r.audit_id in ids}
    assert set(got) == set(ids)
    for audit_id, record in got.items():
        assert (record.actor, record.action) == ("cli:root", ids[audit_id])
        detail = json.loads(record.detail_text)
        assert detail["alert"] is True
        assert detail["alert_kind"] == ALERT_OF[ids[audit_id]]


# ------------------------------------------------------------ CHK-M2-272


@pytest.mark.parametrize("argv", [["bogus"], [], ["create-admin"], ["reset-totp"]])
def test_unknown_or_incomplete_users_commands_touch_no_database(
    tmp_path: Path, argv: list[str]
) -> None:
    code = (
        "import sys, json\n"
        "from bitscan_manager.cli.users import users_main\n"
        "dsn = __import__('pathlib').Path('/nonexistent')\n"
        "rc = users_main(sys.argv[1:], dsn_file=dsn)\n"
        "roots = ('psycopg', 'sqlalchemy', 'alembic')\n"
        "db = [m for m in sys.modules if m.split('.')[0] in roots]\n"
        "print(json.dumps({'rc': rc, 'db': db}))\n"
    )
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code, *argv], capture_output=True, text=True, timeout=60
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["rc"] == 2 and out["db"] == []
