"""Fake Bitscan manager for the agent binary tests (tests/m4/test-plan.md TP-M4-21).

Serves the frozen agent contract (TS §6.5) over TLS on 127.0.0.1 and records
every request as one JSON line (method, path, query, the headers that matter,
the body; inventory bodies are gunzipped). Test-only: it is never shipped.

Usage: python3 -I fake_manager.py --cert C --key K --port-file F --log L
       [--enrol enrolled|awaiting|401|403] [--hold OP] [--inventory-job]
       [--rotate-open] [--jobs-401]
"""

from __future__ import annotations

import argparse
import gzip
import json
import secrets
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
STATE: dict[str, object] = {"pulls": 0}


def token(prefix: str) -> str:
    """A canary token: prefix + 43 base64url characters with CANARY inside."""
    body = "CANARY" + secrets.token_urlsafe(32)[:37]
    return prefix + body


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--enrol", default="enrolled")
    ap.add_argument("--hold", default="")
    ap.add_argument("--inventory-job", action="store_true")
    ap.add_argument("--rotate-open", action="store_true")
    ap.add_argument("--jobs-401", action="store_true")
    args = ap.parse_args()
    agent_id = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
    job_id = "c1a4e5f6-0718-4293-a4b5-c6d7e8f9a0b1"
    tokens: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a: object) -> None:  # quiet
            return

        def _record(self, body: bytes) -> dict[str, object]:
            path, _, query = self.path.partition("?")
            if self.headers.get("Content-Encoding", "").lower() == "gzip":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    body = b"<not gzip>"
            rec = {
                "t": time.time(),
                "method": self.command,
                "path": path,
                "query": query,
                "authorization": self.headers.get("Authorization", ""),
                "machine_id": self.headers.get_all("X-Bitscan-Machine-Id") or [],
                "content_type": self.headers.get("Content-Type", ""),
                "content_encoding": self.headers.get("Content-Encoding", ""),
                "body": body.decode("utf-8", "replace"),
            }
            with LOCK, open(args.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            return rec

        def _send(self, status: int, obj: object | None = None, ptype: str = "") -> None:
            if status == 204:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if status >= 400:
                data = json.dumps({"type": ptype or "about:blank", "title": "t", "status": status, "detail": "d", "instance": self.path}).encode()
                ctype = "application/problem+json"
            else:
                data = json.dumps(obj).encode()
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self) -> str:
            p = self.path.partition("?")[0]
            for op, suffix in (("enrol", "/api/v1/agent/enroll"), ("heartbeat", "/heartbeat"), ("rotate", "/token/rotate"), ("results", "/results"), ("jobs", "/jobs"), ("inventory", "/inventory")):
                if p.endswith(suffix):
                    return op
            return "unknown"

        def _handle(self) -> None:
            n = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(n) if n else b""
            self._record(body)
            op = self._route()
            if args.hold and op == args.hold:
                time.sleep(30)
            now = datetime.now(UTC)
            if op == "enrol":
                if args.enrol in ("401", "403"):
                    self._send(int(args.enrol), ptype="enrollment_rejected" if args.enrol == "401" else "forbidden")
                    return
                tok = token("bsa_")
                tokens.append(tok)
                issued = now - timedelta(days=400) if args.rotate_open else now
                self._send(200, {"agent_id": agent_id, "agent_token": tok, "issued_at": iso(issued), "expires_at": iso(now + timedelta(days=30 if args.rotate_open else 365)), "status": "awaiting_approval" if args.enrol == "awaiting" else "enrolled"})
            elif op == "heartbeat":
                self._send(200, {"job_pull_seconds": 60, "max_parallel_plugins": 2, "server_time": iso(now)})
            elif op == "rotate":
                tok = token("bsa_")
                tokens.append(tok)
                self._send(200, {"agent_token": tok, "issued_at": iso(now), "expires_at": iso(now + timedelta(days=365))})
            elif op == "jobs":
                if args.jobs_401:
                    self._send(401, ptype="token_revoked")
                    return
                with LOCK:
                    STATE["pulls"] = int(str(STATE["pulls"])) + 1
                    first = STATE["pulls"] == 1
                jobs = []
                if args.inventory_job and first:
                    jobs.append({"job_id": job_id, "agent_id": agent_id, "kind": "inventory", "pickup_by": iso(now + timedelta(hours=1))})
                self._send(200, {"jobs": jobs})
            elif op == "inventory":
                self._send(204)
            elif op == "results":
                self._send(409, ptype="job_not_acceptable")
            else:
                self._send(404)

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(args.cert, args.key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    with open(args.port_file, "w", encoding="utf-8") as f:
        f.write(str(srv.server_address[1]))
    with open(args.log + ".tokens", "w", encoding="utf-8") as f:
        f.write("")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(0.2)
            with LOCK, open(args.log + ".tokens", "w", encoding="utf-8") as f:
                f.write("\n".join(tokens))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
