"""Fake Bitscan manager for the M10 agent binary walk (TP-M10-19; tester-m10c).

Like e2e/fake_manager.py (M4, unchanged) but it hands out compliance jobs and
accepts result batches. It serves TS §6.5 over TLS on 127.0.0.1 and records
every request as one JSON line (results and inventory bodies gunzipped).

  --jobs FILE      JSON list of jobs for the first pull; each job's
                   "pickup_by" is replaced with now + 1 h; later pulls are empty
  --results MODE   200 (default) | 503-while:<path> (503 for a batch that
                   holds items while the file exists; the start notice is
                   answered 200)
  --mpp N          max_parallel_plugins in heartbeat answers (default 2)

Test-only: it is never shipped.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import secrets
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--jobs", default="")
    ap.add_argument("--results", default="200")
    ap.add_argument("--mpp", type=int, default=2)
    args = ap.parse_args()
    agent_id = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
    jobs = json.load(open(args.jobs, encoding="utf-8")) if args.jobs else []
    state = {"pulls": 0}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a: object) -> None:
            return

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

        def _handle(self) -> None:
            n = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(n) if n else b""
            if self.headers.get("Content-Encoding", "").lower() == "gzip":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    body = b"<not gzip>"
            path, _, query = self.path.partition("?")
            now = datetime.now(UTC)
            op = next((o for o, s in (("enrol", "/enroll"), ("heartbeat", "/heartbeat"), ("rotate", "/token/rotate"),
                                      ("results", "/results"), ("jobs", "/jobs"), ("inventory", "/inventory")) if path.endswith(s)), "unknown")
            status = 200
            if op == "results" and args.results.startswith("503-while:") and os.path.exists(args.results.split(":", 1)[1]):
                # the start notice is answered, so the outage hits batches
                # that hold items (the in-flight case of #140)
                try:
                    status = 503 if json.loads(body)["results"] else 200
                except (ValueError, KeyError):
                    status = 503
            rec = {"t": time.time(), "op": op, "method": self.command, "path": path, "query": query, "status": status,
                   "content_encoding": self.headers.get("Content-Encoding", ""), "body": body.decode("utf-8", "replace")}
            with LOCK, open(args.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            if op == "enrol":
                self._send(200, {"agent_id": agent_id, "agent_token": "bsa_CANARY" + secrets.token_urlsafe(32)[:37],
                                 "issued_at": iso(now), "expires_at": iso(now + timedelta(days=365)), "status": "enrolled"})
            elif op == "heartbeat":
                self._send(200, {"job_pull_seconds": 60, "max_parallel_plugins": args.mpp, "server_time": iso(now)})
            elif op == "jobs":
                with LOCK:
                    state["pulls"] += 1
                    first = state["pulls"] == 1
                out = []
                if first:
                    for j in jobs:
                        j = dict(j)
                        j["pickup_by"] = iso(now + timedelta(hours=1))
                        out.append(j)
                self._send(200, {"jobs": out})
            elif op == "inventory":
                self._send(204)
            elif op == "results":
                if status == 503:
                    self._send(503)
                else:
                    try:
                        k = len(json.loads(body)["results"])
                    except (ValueError, KeyError):
                        k = 0
                    self._send(200, {"accepted": k, "duplicates": 0})
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
    srv.serve_forever()


if __name__ == "__main__":
    main()
