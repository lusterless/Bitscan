"""Fake bitscan-runner for the M10 agent binary walk (tests/m10/test-plan.md
TP-M10-19, CHK-M10-182 to -185; tester-m10c).

Listens on a Unix socket and speaks the #130 protocol: one 4-byte
big-endian length + one compact JSON object per frame. It reads one request,
records it, and answers by --mode:
  normal         accepted, one result per plugin, done
  hold:N         accepted, N results, then waits until the agent closes
  refuse:WORD    refused WORD
  eof:N          accepted, N results, then closes without done
  slow:N:S       accepted, N results, S seconds pause, the rest, done
Every result's stdout carries --canary. Test-only: never shipped.

Usage: python3 -I fake_runner_m10.py --sock S --log L --mode M [--canary C]
       [--stdout-bytes N]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import threading
import time
from datetime import UTC, datetime


def iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--mode", default="normal")
    ap.add_argument("--canary", default="M10RUNNERCANARY")
    ap.add_argument("--stdout-bytes", type=int, default=0)
    args = ap.parse_args()
    lock = threading.Lock()

    def log(rec: dict[str, object]) -> None:
        rec["t"] = time.time()
        with lock, open(args.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def send(c: socket.socket, obj: dict[str, object]) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        c.sendall(struct.pack(">I", len(body)) + body)

    def read_exact(c: socket.socket, n: int) -> bytes:
        b = b""
        while len(b) < n:
            chunk = c.recv(n - len(b))
            if not chunk:
                raise EOFError
            b += chunk
        return b

    def serve(c: socket.socket) -> None:
        try:
            n = struct.unpack(">I", read_exact(c, 4))[0]
            req = json.loads(read_exact(c, n))
        except (EOFError, ValueError) as e:
            log({"event": "bad request", "error": str(e)})
            c.close()
            return
        log({"event": "request", "request": req})
        mode, _, arg = args.mode.partition(":")
        if mode == "refuse":
            send(c, {"type": "refused", "reason": arg})
            c.close()
            return
        send(c, {"type": "accepted"})
        plugins = req["job"]["plugins"]
        pause_at, pause = -1, 0.0
        if mode == "slow":
            n_, _, s_ = arg.partition(":")
            pause_at, pause = int(n_), float(s_)
        count = len(plugins) if mode in ("normal", "slow") else int(arg)
        for i, p in enumerate(plugins[:count]):
            if i == pause_at:
                log({"event": "pause", "after": i})
                time.sleep(pause)
            out = "out " + args.canary
            if args.stdout_bytes:
                out = (out + " " + "x" * args.stdout_bytes)[: args.stdout_bytes]
            t = iso()
            send(c, {"type": "result", "result": {"plugin_uuid": p["plugin_uuid"], "exit_code": 0, "stdout": out, "stderr": "",
                                                  "started_at": t, "finished_at": t, "timed_out": False, "truncated": False, "error": None}})
        log({"event": "sent", "results": count})
        if mode in ("normal", "slow"):
            send(c, {"type": "done"})
            log({"event": "done"})
        elif mode == "hold":
            c.settimeout(None)
            try:
                while c.recv(1):
                    pass
            except OSError:
                pass
            log({"event": "agent closed"})
        c.close()

    if os.path.exists(args.sock):
        os.unlink(args.sock)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(args.sock)
    os.chmod(args.sock, 0o666)
    srv.listen(8)
    log({"event": "listening"})
    while True:
        c, _ = srv.accept()
        log({"event": "connection"})
        threading.Thread(target=serve, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
