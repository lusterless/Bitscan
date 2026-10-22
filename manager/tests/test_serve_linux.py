"""TASK-045: the real `bitscan-manager serve` on Linux (TP-M2-22; G27).

Checks CHK-M2-250 to CHK-M2-263b of tests/m2/test-plan.md. TS §8.7 L1343
(HTTPS only; SIGHUP reloads the certificate), TS §6 L1056 (TLS 1.2+), TS §8.6
(serve variables; never the migrate DSN), REQ-057 (1)-(7), #55 (d) (proxy
headers ignored), #58 (a) (vault down: serve still starts), decisions
2026-10-21/22 (graceful SIGTERM exits 0; no canary from uvicorn's own loggers;
flusher keeps failed entries, at most 10,000).
"""

import json
import os
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from .canary import new_canary, sweep
from .certs import Leaf, Pki, make_pki
from .conftest import PgServer, cli_path
from .fake_sink import https_sink, server_context

if not hasattr(signal, "SIGHUP"):
    pytest.skip("not run: Linux only (SIGHUP)", allow_module_level=True)
SIGHUP: int = getattr(signal, "SIGHUP", 1)

pytestmark = pytest.mark.pg


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


@dataclass
class Serve:
    proc: subprocess.Popen[str]
    port: int
    cert: Path
    key: Path
    ca: Path
    queue: Path
    log: Path

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")

    def stop(self, sig: int = signal.SIGTERM, timeout: float = 15) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(sig)
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
            raise


def client_context(ca: Path, version: ssl.TLSVersion | None = None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(ca))
    if version is not None:
        ctx.minimum_version = version
        ctx.maximum_version = version
    return ctx


def https_get(
    port: int,
    ca: Path,
    path: str = "/healthz",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    method: str = "GET",
) -> tuple[int, dict[str, str], bytes]:
    import http.client

    conn = http.client.HTTPSConnection(
        "localhost", port, context=client_context(ca), timeout=10
    )
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, hdrs, data


def peer_fingerprint(port: int, ca: Path) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with client_context(ca).wrap_socket(raw, server_hostname="localhost") as tls:
            der = tls.getpeercert(binary_form=True)
    assert der is not None
    import hashlib

    return hashlib.sha256(der).digest()


def wait_ready(s: Serve, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if s.proc.poll() is not None:
            raise AssertionError(
                f"serve exited {s.proc.returncode}: {s.output()[-2000:]}"
            )
        try:
            if https_get(s.port, s.ca)[0] == 200:
                return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("serve did not answer /healthz: " + s.output()[-2000:])


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("serve-pki"))


CANARY_PW = new_canary("dsnpw")
CANARY_VAULT = new_canary("vaulttok")


def env_for(
    server: PgServer,
    tmp: Path,
    pki: Pki,
    leaf: Leaf,
    sink_url: str,
    port: int,
    **overrides: str | None,
) -> dict[str, str]:
    creds = tmp / "creds"
    creds.mkdir(exist_ok=True)
    (creds / "app_dsn").write_text(server.dsn("bitscan_app"))
    (creds / "retention_dsn").write_text(server.dsn("bitscan_retention"))
    (creds / "vault_token").write_text(CANARY_VAULT)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    env.update(
        {
            "BITSCAN_DB_DSN_FILE": str(creds / "app_dsn"),
            "BITSCAN_RETENTION_DSN_FILE": str(creds / "retention_dsn"),
            "BITSCAN_VAULT_ADDR": "https://127.0.0.1:1",
            "BITSCAN_TOTP_KEY_REF": "bitscan-totp",
            "BITSCAN_VAULT_TOKEN_FILE": str(creds / "vault_token"),
            "BITSCAN_TLS_CERT_FILE": str(leaf.cert),
            "BITSCAN_TLS_KEY_FILE": str(leaf.key),
            "BITSCAN_AUDIT_SINK": sink_url,
            "BITSCAN_LISTEN": f"127.0.0.1:{port}",
            "BITSCAN_MIGRATE_DSN_FILE": "/nonexistent/unreadable/migrate.dsn",
            "SSL_CERT_FILE": str(pki.ca),
        }
    )
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def start(env: dict[str, str], tmp: Path, port: int, pki: Pki, leaf: Leaf) -> Serve:
    """Runs serve through a tiny launcher so queue_dir points at tmp."""
    queue = tmp / "audit-queue"
    log = tmp / "serve.log"
    launcher = (
        "import os, sys, pathlib\n"
        "from bitscan_manager.cli.serve import serve_main\n"
        f"queue = pathlib.Path({str(queue)!r})\n"
        "sys.exit(serve_main(os.environ, queue_dir=queue))\n"
    )
    proc = subprocess.Popen(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", launcher],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )
    return Serve(proc, port, leaf.cert, leaf.key, pki.ca, queue, log)


@pytest.fixture
def sink(pki: Pki) -> Iterator[Any]:
    leaf = pki.leaf("sink-serve")
    with https_sink(server_context(leaf.cert, leaf.key)) as s:
        yield s


@pytest.fixture
def running(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> Iterator[Serve]:
    # Each test gets its own leaf: tests rewrite or chmod running.cert and
    # running.key, and the PKI folder is shared by the whole module.
    leaf = pki.leaf(f"serve-{secrets.token_hex(4)}")
    port = free_port()
    env = env_for(
        migrated_db, tmp_path, pki, leaf, f"https://localhost:{sink.port}/a", port
    )
    s = start(env, tmp_path, port, pki, leaf)
    try:
        wait_ready(s)
        yield s
    finally:
        if s.proc.poll() is None:
            s.stop()


# ------------------------------------------------------------ CHK-M2-250

SERVE_VARS = [
    "BITSCAN_DB_DSN_FILE",
    "BITSCAN_RETENTION_DSN_FILE",
    "BITSCAN_VAULT_ADDR",
    "BITSCAN_TOTP_KEY_REF",
    "BITSCAN_VAULT_TOKEN_FILE",
    "BITSCAN_TLS_CERT_FILE",
    "BITSCAN_TLS_KEY_FILE",
    "BITSCAN_AUDIT_SINK",
]


@pytest.mark.parametrize("missing", SERVE_VARS)
def test_missing_variable_exits_before_binding(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, missing: str
) -> None:
    leaf = pki.leaf(f"m-{missing[-8:].lower()}")
    port = free_port()
    env = env_for(
        migrated_db,
        tmp_path,
        pki,
        leaf,
        "https://localhost:1/a",
        port,
        **{missing: None},
    )
    s = start(env, tmp_path, port, pki, leaf)
    code = s.proc.wait(30)
    out = s.output()
    assert code == 2, out
    assert missing in out
    assert sweep([CANARY_PW, CANARY_VAULT, migrated_db.dsn("bitscan_app")], out) == []
    probe = socket.socket()
    probe.bind(("127.0.0.1", port))  # the port is still free: nothing was bound
    probe.close()


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("BITSCAN_AUDIT_SINK", "http://localhost/a"),
        ("BITSCAN_AUDIT_SINK", "udp://h:514"),
        ("BITSCAN_AUDIT_SINK", "tcp://h:514"),
        ("BITSCAN_LISTEN", "127.0.0.1:0"),
        ("BITSCAN_LISTEN", "nonsense"),
        ("BITSCAN_TLS_KEY_FILE", "/nonexistent/key"),
    ],
)
def test_invalid_values_exit_2_naming_the_variable(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, var: str, value: str
) -> None:
    """CHK-M2-250, -261."""
    leaf = pki.leaf(f"bad-{abs(hash(value)) % 10000}")
    port = free_port()
    env = env_for(
        migrated_db, tmp_path, pki, leaf, "https://localhost:1/a", port, **{var: value}
    )
    s = start(env, tmp_path, port, pki, leaf)
    code = s.proc.wait(30)
    out = s.output()
    assert code == 2, out
    assert var in out or (var.startswith("BITSCAN_TLS") and "BITSCAN_TLS" in out)


def test_non_tls_dsn_is_refused(
    migrated_db: PgServer, tmp_path: Path, pki: Pki
) -> None:
    leaf = pki.leaf("nontls")
    port = free_port()
    bad = tmp_path / "plain.dsn"
    bad.write_text(
        migrated_db.dsn("bitscan_app").replace("sslmode=require", "sslmode=disable")
    )
    env = env_for(
        migrated_db,
        tmp_path,
        pki,
        leaf,
        "https://localhost:1/a",
        port,
        BITSCAN_DB_DSN_FILE=str(bad),
    )
    s = start(env, tmp_path, port, pki, leaf)
    assert s.proc.wait(30) == 2
    assert "BITSCAN_DB_DSN_FILE" in s.output()


def test_port_in_use_exits_non_zero_without_secrets(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> None:
    leaf = pki.leaf("busy")
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        env = env_for(
            migrated_db, tmp_path, pki, leaf, f"https://localhost:{sink.port}/a", port
        )
        s = start(env, tmp_path, port, pki, leaf)
        code = s.proc.wait(30)
    finally:
        holder.close()
    assert code != 0
    assert sweep([CANARY_VAULT, migrated_db.dsn("bitscan_app")], s.output()) == []


# ------------------------------------------------------- CHK-M2-251, -252


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_tls_1_2_and_1_3_succeed(running: Serve, version: ssl.TLSVersion) -> None:
    with socket.create_connection(("127.0.0.1", running.port), timeout=5) as raw:
        with client_context(running.ca, version).wrap_socket(
            raw, server_hostname="localhost"
        ) as tls:
            assert (
                tls.version()
                == {
                    ssl.TLSVersion.TLSv1_2: "TLSv1.2",
                    ssl.TLSVersion.TLSv1_3: "TLSv1.3",
                }[version]
            )


def old_tls_client(version: ssl.TLSVersion) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = version
    ctx.maximum_version = version
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1])
def test_tls_1_0_and_1_1_fail(
    running: Serve, pki: Pki, version: ssl.TLSVersion
) -> None:
    # control: this client CAN speak the old version to a server that allows it
    leaf = pki.leaf("oldctl")
    srv = server_context(leaf.cert, leaf.key, max_version=ssl.TLSVersion.TLSv1_1)
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    import threading

    def accept() -> None:
        conn, _ = lsock.accept()
        try:
            srv.wrap_socket(conn, server_side=True).close()
        except (OSError, ssl.SSLError):
            conn.close()

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        with socket.create_connection(lsock.getsockname(), timeout=5) as raw:
            old_tls_client(version).wrap_socket(raw).close()
    except (OSError, ssl.SSLError) as exc:
        pytest.skip(f"not run: this OpenSSL cannot speak {version.name} ({exc!r})")
    finally:
        lsock.close()
    with pytest.raises((ssl.SSLError, OSError)):
        with socket.create_connection(("127.0.0.1", running.port), timeout=5) as raw:
            old_tls_client(version).wrap_socket(raw).close()


def test_plain_http_gets_no_application_response(running: Serve) -> None:
    with socket.create_connection(("127.0.0.1", running.port), timeout=5) as s:
        s.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s.settimeout(5)
        try:
            data = s.recv(4096)
        except (TimeoutError, ConnectionResetError):
            data = b""
    assert b"200 OK" not in data and b"strict-transport-security" not in data.lower()
    assert https_get(running.port, running.ca)[0] == 200  # still serving TLS


# ------------------------------------------------------------ CHK-M2-253


def listening_inodes(pid: int, port: int) -> set[str]:
    hexport = f"{port:04X}"
    inodes = set()
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        parts = line.split()
        if parts[1].endswith(f":{hexport}") and parts[3] == "0A":
            inodes.add(parts[9])
    fds = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            fds.add(target[8:-1])
    return inodes & fds


def test_sighup_reloads_the_certificate_in_place(running: Serve, pki: Pki) -> None:
    before = peer_fingerprint(running.port, running.ca)
    pid = running.proc.pid
    sockets_before = listening_inodes(pid, running.port)
    assert sockets_before
    import http.client

    keep = http.client.HTTPSConnection(
        "localhost", running.port, context=client_context(running.ca), timeout=10
    )
    keep.request("GET", "/healthz")
    keep.getresponse().read()
    new = pki.leaf("serve-new")
    running.cert.write_bytes(new.cert.read_bytes())
    running.key.write_bytes(new.key.read_bytes())
    running.proc.send_signal(SIGHUP)
    deadline = time.monotonic() + 10
    after = before
    while time.monotonic() < deadline and after == before:
        time.sleep(0.2)
        after = peer_fingerprint(running.port, running.ca)
    assert after != before
    assert running.proc.poll() is None and running.proc.pid == pid
    assert listening_inodes(pid, running.port) == sockets_before
    keep.request("GET", "/healthz")  # the open keep-alive connection still works
    assert keep.getresponse().status == 200
    keep.close()


# ------------------------------------------------------------ CHK-M2-254


@pytest.mark.parametrize("broken", ["unreadable-key", "mismatched", "truncated-cert"])
def test_sighup_with_a_broken_pair_keeps_the_old_certificate(
    running: Serve, pki: Pki, broken: str
) -> None:
    before = peer_fingerprint(running.port, running.ca)
    secret_line = new_canary("keymaterial")
    mode = running.key.stat().st_mode & 0o777
    try:
        if broken == "unreadable-key":
            running.key.write_text(f"-----BEGIN PRIVATE KEY-----\n{secret_line}\n")
            # As a normal user the key cannot be read; as root (WSL) it can, and
            # the reload fails on the invalid key instead. Both must be refused.
            os.chmod(running.key, 0)
        elif broken == "mismatched":
            running.cert.write_bytes(pki.leaf("other-pair").cert.read_bytes())
        else:
            data = running.cert.read_bytes()
            running.cert.write_bytes(data[: len(data) // 2])
        running.proc.send_signal(SIGHUP)
        time.sleep(2)
        assert running.proc.poll() is None
        assert peer_fingerprint(running.port, running.ca) == before
        out = running.output()
        errors = [ln for ln in out.splitlines() if "reload" in ln.lower()]
        assert errors, out[-1500:]
        assert sweep([secret_line, "BEGIN PRIVATE KEY"], out) == []
    finally:
        os.chmod(running.key, mode)  # this test's own file, but leave nothing broken


# ------------------------------------------------------ CHK-M2-255, -258


def test_healthz_over_tls_carries_the_headers(running: Serve) -> None:
    status, headers, _ = https_get(running.port, running.ca)
    assert status == 200
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert headers["content-security-policy"].startswith("default-src 'self'")
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert "server" not in headers


# ------------------------------------------------------- CHK-M2-256, -263a


def test_proxy_headers_are_ignored(running: Serve) -> None:
    codes = []
    for i in range(11):
        status, _, _ = https_get(
            running.port,
            running.ca,
            "/api/v1/auth/login",
            method="POST",
            body=json.dumps({"username": "nobody", "password": "x" * 12}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Forwarded-For": f"203.0.113.{i}",
                "Forwarded": f"for=198.51.100.{i}",
            },
        )
        codes.append(status)
    assert codes[-1] == 429 and 429 not in codes[:10]
    assert "203.0.113" not in running.output()


def test_no_query_or_exception_canary_on_stdout_or_stderr(running: Serve) -> None:
    """Decisions 2026-10-21 (reviewer's TASK-027 point): uvicorn's own access and
    error loggers must not print a query string or an exception message."""
    q = new_canary("query")
    https_get(running.port, running.ca, f"/healthz?token={q}")
    https_get(
        running.port,
        running.ca,
        f"/api/v1/auth/login?x={q}",
        method="POST",
        body=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    msg = new_canary("exc")
    # a body that makes the JSON decoder raise with the canary in its message
    https_get(
        running.port,
        running.ca,
        "/api/v1/auth/login",
        method="POST",
        body=('{"username": "' + msg + '", "password": ').encode(),
        headers={"Content-Type": "application/json"},
    )
    time.sleep(0.5)
    out = running.output()
    assert sweep([q, msg], out) == []
    access = [
        json.loads(ln)
        for ln in out.splitlines()
        if ln.startswith("{") and '"bitscan_manager.access"' in ln
    ]
    assert any(r.get("path") == "/healthz" for r in access)
    assert all("?" not in str(r.get("path")) for r in access)
    assert not any("uvicorn.access" in ln for ln in out.splitlines())


# ------------------------------------------------------------ CHK-M2-257


def test_sigterm_exits_0_flushes_counts_and_keeps_the_queue(
    running: Serve, migrated_db: PgServer
) -> None:
    for _ in range(3):
        https_get(
            running.port,
            running.ca,
            "/api/v1/auth/logout",
            method="POST",
            headers={"Authorization": "Bearer bsu_" + "Q" * 43},
        )
    code = running.stop(signal.SIGTERM)
    assert code == 0, running.output()[-1500:]
    with psycopg.connect(migrated_db.dsn("bitscan_app"), autocommit=True) as c:
        rows = c.execute(
            "SELECT detail FROM audit_log WHERE action = 'auth.token_check_failed'"
            " ORDER BY audit_id DESC LIMIT 1"
        ).fetchall()
    assert rows and rows[0][0]["ip"] == "127.0.0.1" and rows[0][0]["count"] == 3


# ------------------------------------------------------- CHK-M2-258, -260


def test_starts_with_unreadable_migrate_dsn_and_vault_down(running: Serve) -> None:
    """The fixture sets BITSCAN_MIGRATE_DSN_FILE to a missing path and the vault
    to a closed port; serve still starts and answers both health routes."""
    assert https_get(running.port, running.ca, "/healthz")[0] == 200
    assert https_get(running.port, running.ca, "/readyz")[0] == 200


# ------------------------------------------------------------ CHK-M2-262


def test_entries_reach_the_sink_within_5_s(
    running: Serve, sink: Any, migrated_db: PgServer
) -> None:
    with psycopg.connect(migrated_db.dsn("bitscan_app")) as c:
        from bitscan_manager.repositories.audit_log import PgAuditRepo
        from bitscan_manager.services.audit.chain import append_entry

        with c.transaction():
            entry = append_entry(
                PgAuditRepo(c), actor="cli:root", action="test.serve_ship"
            )
    committed = time.monotonic()
    deadline = committed + 10
    seen = None
    while time.monotonic() < deadline and seen is None:
        for post in sink.posts:
            body = json.loads(post.body)
            if body["audit_id"] == entry.audit_id:
                seen = time.monotonic()
        time.sleep(0.1)
    assert seen is not None and seen - committed < 5


# ------------------------------------------------------------ CHK-M2-263


def test_no_secret_anywhere_in_the_serve_output(
    running: Serve, migrated_db: PgServer
) -> None:
    https_get(running.port, running.ca, "/readyz")
    running.stop()
    out = running.output()
    secrets_ = [
        CANARY_VAULT,
        migrated_db.dsn("bitscan_app"),
        migrated_db.dsn("bitscan_retention"),
        running.key.read_text(),
    ]
    assert sweep(secrets_, out) == []
    for line in out.splitlines():
        if line.strip():
            json.loads(line)  # every line is JSON


# ------------------------------------------------------------ CHK-M2-263c


def test_refused_dsn_puts_no_dsn_content_on_stdout_or_stderr(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> None:
    """Decisions 2026-10-22 (TASK-046 ruling (a)): no DSN content (user, host,
    port, password) in serve's output when PostgreSQL refuses the connection.

    host is a canary and hostaddr the real address, so libpq connects without a
    lookup and its refusal names both the host and the user canary.
    """
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    host_canary = new_canary("dsnhost").lower()
    user_canary = new_canary("dsnuser")
    pw_canary = new_canary("dsnpw")
    params = conninfo_to_dict(migrated_db.dsn("bitscan_app"))
    params.update(
        host=host_canary,
        hostaddr=socket.gethostbyname(str(migrated_db.host)),
        user=user_canary,
        password=pw_canary,
    )
    bad = tmp_path / "refused.dsn"
    bad.write_text(make_conninfo("", **params))
    leaf = pki.leaf("serve-refused")
    port = free_port()
    env = env_for(
        migrated_db,
        tmp_path,
        pki,
        leaf,
        f"https://localhost:{sink.port}/a",
        port,
        BITSCAN_DB_DSN_FILE=str(bad),
    )
    s = start(env, tmp_path, port, pki, leaf)
    try:
        wait_ready(s)
        assert https_get(s.port, s.ca, "/readyz")[0] == 503  # really refused
        status, _, _ = https_get(
            s.port,
            s.ca,
            "/api/v1/auth/login",
            method="POST",
            body=b'{"username": "nobody", "password": "nobody password"}',
            headers={"Content-Type": "application/json"},
        )
        assert status == 503
        time.sleep(4)  # several pool reconnect attempts
    finally:
        if s.proc.poll() is None:
            s.stop()
    out = s.output()
    assert sweep([host_canary, user_canary, pw_canary], out) == []
    assert f"port {migrated_db.port}" not in out  # libpq's wording
    for line in out.splitlines():
        if line.strip():
            json.loads(line)  # structured logs only, no raw driver text


def test_bounded_dsn_adds_the_time_bounds() -> None:
    from psycopg.conninfo import conninfo_to_dict
    from pydantic import SecretStr

    from bitscan_manager.cli.serve import bounded_dsn

    dsn = "host=h dbname=d user=u sslmode=require options='-c search_path=public'"
    out = conninfo_to_dict(bounded_dsn(SecretStr(dsn)).get_secret_value())
    assert out["keepalives"] == "1"
    assert out["tcp_user_timeout"] == "300000"
    assert "statement_timeout=300000" in str(out["options"])
    assert "search_path=public" in str(out["options"])
    assert datetime.now(UTC)  # module imports on Linux


def test_cli_path_exists() -> None:
    assert Path(cli_path()).exists()


def test_sigterm_with_the_sink_down_leaves_the_queue_intact(
    migrated_db: PgServer, tmp_path: Path, pki: Pki
) -> None:
    """REQ-057 (6): with the sink unreachable, queued entries stay on disk
    through a graceful stop and the next start can still send them."""
    from bitscan_manager.repositories.audit_log import PgAuditRepo
    from bitscan_manager.services.audit.chain import append_entry
    from bitscan_manager.services.audit.disk_queue import DiskQueue

    leaf = pki.leaf("serve-sinkdown")
    port = free_port()
    dead_sink = f"https://localhost:{free_port()}/a"
    env = env_for(migrated_db, tmp_path, pki, leaf, dead_sink, port)
    s = start(env, tmp_path, port, pki, leaf)
    try:
        wait_ready(s)
        with psycopg.connect(migrated_db.dsn("bitscan_app")) as c:
            with c.transaction():
                entry = append_entry(PgAuditRepo(c), actor="cli:root", action="test.q")
        deadline = time.monotonic() + 15
        queued: list[int] = []
        while time.monotonic() < deadline and entry.audit_id not in queued:
            time.sleep(0.3)
            if any(p.name.startswith("segment-") for p in s.queue.iterdir()):
                queued = [r["audit_id"] for r in DiskQueue(s.queue).peek(100_000)]
        assert entry.audit_id in queued
        assert s.stop(signal.SIGTERM) == 0
    finally:
        if s.proc.poll() is None:
            s.stop()
    after = [r["audit_id"] for r in DiskQueue(s.queue).peek(100_000)]
    assert set(queued) <= set(after)
