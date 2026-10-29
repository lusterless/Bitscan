"""Shared environment for the M7 catalog write-route suites (tester-m7d;
TASK-162 to TASK-164: upload, delete, rebuild and task routes).

No product code here. The app runs on a database of the module's own
(``own_migrated_server``), with the real ``CatalogService`` over a temporary
bits folder, the real start-up sequence, the real sink gate (a switchable
sink behind the M2 shipper) and the real auth dependencies. The folder
watcher is replaced by one that never opens, so every catalog change comes
from the route under test (the watcher has its own suite, TP-M7-19).
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import SinkRecord
from bitscan_manager.services.importer.service import CatalogService

from .catalog_rows import catalog_checksums, owner
from .conftest import PgServer
from .test_import_pipeline_pg import doc, plug
from .test_totp_enrol import Cipher, Clock
from .test_users_api_pg import Env, SwitchSink

MIB = 1_048_576
PART_CAP = 5 * MIB  # TS §6.3 L1138 (#57: MB means MiB)
BODY_CAP = 5 * MIB + 64 * 1024  # #99 (a)
BOUNDARY = b"bsTesterM7dBoundary"
STARTING = "The catalog is starting; retry shortly."  # #102 (d)
FORM_DETAIL = "The body must be multipart/form-data with one part named file."
MANAGED_DETAIL = "This policy is managed in the server folder; change its file there."
POLICIES = "/api/v1/policies"
IMPORT = "/api/v1/policies/import"
REBUILD = "/api/v1/policies/rebuild"
TASKS = "/api/v1/tasks"


class NoWatcher:
    """The folder watcher, never opened (the watcher has its own suite)."""

    def open(self) -> bool:
        return False

    def run(self, stop: threading.Event, poll: float = 1.0) -> None:
        return None


def until(pred: Callable[[], Any], bound: float = 30.0) -> Any:
    t0 = time.monotonic()
    while time.monotonic() - t0 < bound:
        got = pred()
        if got:
            return got
        time.sleep(0.02)
    pytest.fail(f"not within {bound} s")


@dataclass
class CatEnv(Env):
    db: AppDatabase = field(kw_only=True)
    bits: Path = field(kw_only=True)
    svc: CatalogService = field(kw_only=True)
    services: list[CatalogService] = field(kw_only=True, default_factory=list)

    # --- the catalog service ---------------------------------------------------

    def new_service(self, *, start: bool = True) -> CatalogService:
        s = CatalogService(
            self.db, self.clock, self.bits, wake=self.shipper.wake,
            watcher=NoWatcher(),  # type: ignore[arg-type]
        )  # fmt: skip
        self.services.append(s)
        if start:
            s.start()
            until(lambda: s.ready)
        return s

    def restart(self) -> None:
        """A manager restart: the old service stopped, a new one started (its
        start-up sequence runs again), and the app switched to it."""
        self.svc.stop(wait_s=1)
        self.svc = self.new_service()
        rt = self.client.app.state.runtime  # type: ignore[attr-defined]
        self.client.app.state.runtime = replace(rt, catalog=self.svc)  # type: ignore[attr-defined]

    def app_with(self, catalog: Any) -> TestClient:
        rt = self.client.app.state.runtime  # type: ignore[attr-defined]
        return TestClient(
            create_app(replace(rt, catalog=catalog)), client=("10.2.0.7", 1)
        )

    # --- tokens ----------------------------------------------------------------

    def admin_session(self) -> tuple[int, str]:
        uid = self.user("admin", totp=True)
        return uid, self.token(uid, "session")

    def admin_api(self) -> tuple[int, str]:
        uid = self.user("admin", totp=True)
        return uid, self.token(uid, "api")

    # --- files -----------------------------------------------------------------

    def tree(self) -> dict[str, bytes]:
        """Every file under the bits folder (relative path → bytes)."""
        return {
            p.relative_to(self.bits).as_posix(): p.read_bytes()
            for p in sorted(self.bits.rglob("*"))
            if p.is_file()
        }

    def put_server(self, name: str, data: bytes) -> None:
        (self.bits / name).write_bytes(data)

    # --- database --------------------------------------------------------------

    def q(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return list(c.execute(sql, args).fetchall())

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> tuple[Any, ...]:
        rows = self.q(sql, args)
        assert len(rows) == 1, rows
        return rows[0]

    def policy(self, pid: int) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM policy WHERE policy_id = %s", (pid,))
            cols = [d.name for d in cur.description or []]
            row = cur.fetchone()
        assert row is not None
        return dict(zip(cols, row, strict=True))

    def import_row(self, iid: int) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM bit_import WHERE import_id = %s", (iid,))
            cols = [d.name for d in cur.description or []]
            row = cur.fetchone()
        assert row is not None
        return dict(zip(cols, row, strict=True))

    def last_import(self) -> int:
        (n,) = self.one("SELECT coalesce(max(import_id), 0) FROM bit_import")
        return int(n)

    def last_audit(self) -> int:
        (n,) = self.one("SELECT coalesce(max(audit_id), 0) FROM audit_log")
        return int(n)

    def audit_after(self, mark: int) -> list[dict[str, Any]]:
        rows = self.q(
            "SELECT actor, action, target, detail FROM audit_log WHERE audit_id > %s"
            " ORDER BY audit_id",
            (mark,),
        )
        return [
            {"actor": a, "action": b, "target": t, "detail": d} for a, b, t, d in rows
        ]

    def tasks(self) -> int:
        (n,) = self.one("SELECT count(*) FROM task")
        return int(n)

    def state(self) -> tuple[Any, ...]:
        """Everything a refused catalog write must leave unchanged."""
        with owner(self.server) as c:
            sums = catalog_checksums(c)
            rest = c.execute(
                "SELECT (SELECT count(*) FROM bit_import), (SELECT count(*) FROM task),"
                " (SELECT md5(coalesce(string_agg(j::text, '|' ORDER BY job_id), ''))"
                "  FROM scan_job j),"
                " (SELECT md5(coalesce(string_agg(s::text, '|' ORDER BY schedule_id),"
                "  '')) FROM scan_schedule s)"
            ).fetchone()
        return sums, rest, self.tree()

    # --- calls -----------------------------------------------------------------

    def upload(
        self,
        token: str,
        data: bytes,
        filename: bytes | None = b"p.bit",
        **kw: Any,
    ) -> Any:
        body = multipart([part(data, filename=filename)])
        return self.client.post(
            IMPORT,
            content=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={BOUNDARY.decode()}",
            },
            **kw,
        )

    def uploaded(self, token: str, data: bytes, filename: bytes = b"p.bit") -> int:
        r = self.upload(token, data, filename)
        assert r.status_code == 200, r.text
        assert r.json()["outcome"] == "success", r.json()
        return int(r.json()["policy_id"])

    def sink_outage(self, seconds: int = 900) -> None:
        """The audit sink unreachable for `seconds` (TS §5.3 L1051)."""
        self.sink.up = False
        self.shipper.run_once()  # the first failed delivery starts the outage
        self.clock.at += timedelta(seconds=seconds)

    def sink_back(self) -> None:
        self.sink.up = True
        for _ in range(10):
            self.clock.at += timedelta(seconds=31)
            self.shipper.run_once()
            if not self.shipper.refusing():
                return
        pytest.fail("the queue never drained")


class RecordingSink(SwitchSink):
    """A switchable sink that keeps every record it accepted."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[SinkRecord] = []

    def send(self, records: Sequence[SinkRecord]) -> None:
        super().send(records)
        self.records.extend(records)


def make_env(
    server: PgServer,
    tmp_path: Path,
    *,
    start: bool = True,
    sink: SwitchSink | None = None,
) -> Iterator[CatEnv]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=6, connect_timeout_s=3
    )
    db.open()
    bits = tmp_path / "bits"
    (bits / "uploaded").mkdir(parents=True)
    sink = SwitchSink() if sink is None else sink
    shipper = Shipper(
        PgAuditTail(db), DiskQueue(tmp_path / "q"), sink, clock, DbOutageAudit(db)
    )
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=shipper,
        limits=RateLimiter(clock),
    )  # fmt: skip
    services: list[CatalogService] = []
    try:
        with TestClient(create_app(rt), client=("10.2.0.1", 1)) as client:
            env = CatEnv(
                server, clock, sink, shipper, client,
                db=db, bits=bits, svc=None,  # type: ignore[arg-type]
                services=services,
            )  # fmt: skip
            env.svc = env.new_service(start=start)
            client.app.state.runtime = replace(rt, catalog=env.svc)  # type: ignore[attr-defined]
            yield env
    finally:
        for s in services:
            s.stop(wait_s=1)
        db.close()


# --- multipart bodies (built by hand, so every byte is the test's) -----------


def part(
    data: bytes,
    *,
    name: bytes = b"file",
    filename: bytes | None = b"p.bit",
    headers: list[bytes] | None = None,
    disposition: bytes | None = None,
) -> bytes:
    if disposition is None:
        disposition = b'form-data; name="' + name + b'"'
        if filename is not None:
            disposition += b'; filename="' + filename + b'"'
    lines = [b"Content-Disposition: " + disposition] if disposition else []
    lines += headers if headers is not None else [b"Content-Type: application/xml"]
    return b"\r\n".join(lines) + b"\r\n\r\n" + data


def multipart(
    parts: list[bytes],
    *,
    boundary: bytes = BOUNDARY,
    preamble: bytes = b"",
    epilogue: bytes = b"",
    close: bool = True,
) -> bytes:
    out = preamble
    for p in parts:
        out += b"--" + boundary + b"\r\n" + p + b"\r\n"
    if close:
        out += b"--" + boundary + b"--\r\n" + epilogue
    return out


def envelope_len(filename: bytes = b"p.bit") -> int:
    return len(multipart([part(b"", filename=filename)]))


# --- documents ---------------------------------------------------------------


def policy_doc(name: str, plugins: int = 1, **kw: Any) -> bytes:
    """A valid `.bit` with fresh plugin ids (no other policy owns them)."""
    return doc(name, [plug() for _ in range(plugins)], **kw)


def padded(data: bytes, size: int) -> bytes:
    """`data` padded to exactly `size` bytes with one comment after the XML
    declaration (still a valid file)."""
    decl, rest = data.split(b"\n", 1)
    fill = size - len(data) - len(b"<!---->\n")
    assert fill >= 0, "target smaller than the file"
    out = decl + b"\n<!--" + b"a" * fill + b"-->\n" + rest
    assert len(out) == size
    return out


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def alerts(kind: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind})
    return 0.0 if v is None else v


# --- tokens of the wrong route group ------------------------------------------


def wrong_group_headers() -> dict[str, dict[str, str]]:
    return {
        "bsa": {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        "bse": {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.ENROLMENT)}"},
        "none": {},
        "garbage_bsk": {"Authorization": "Bearer bsk_" + "x" * 43},
        "basic": {"Authorization": "Basic YWRtaW46YWRtaW4="},
    }


# --- a raw ASGI request that counts the body bytes pulled ----------------------


@dataclass
class Feed:
    chunks: list[bytes]
    pulled: int = 0

    async def receive(self) -> dict[str, Any]:
        if not self.chunks:
            return {"type": "http.disconnect"}
        chunk = self.chunks.pop(0)
        self.pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self.chunks)}


def drive(
    app: Any, method: str, path: str, headers: list[tuple[bytes, bytes]], feed: Feed
) -> tuple[int, dict[str, str], bytes]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("10.74.252.9", 1),
        "server": ("t", 443),
    }
    status: list[int] = []
    resp_headers: dict[str, str] = {}
    body: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
            resp_headers.update(
                {k.decode(): v.decode() for k, v in message.get("headers", [])}
            )
        elif message["type"] == "http.response.body":
            body.append(message.get("body", b""))

    asyncio.run(app(scope, feed.receive, send))
    return status[0], resp_headers, b"".join(body)


def conn_of(server: PgServer) -> psycopg.Connection[Any]:
    return psycopg.connect(server.dsn("bitscan_app"), autocommit=True)
