"""Test client for bitscan-runner (TP-M10-19 TASK-228 rows; tester-m10c).

Sends one #130 request (4-byte big-endian length + compact JSON) built from
a plugin list, then records every reply with its receive time, one JSON
line each, until the runner closes. It plays the agent's part only: it is
run as user bitscan and is never shipped.

Usage: python3 -I runner_client_m10.py --sock S --log L --job-id J --agent-id A
       --mpp N --plugins FILE [--patterns FILE] [--close-after-accepted]
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from datetime import UTC, datetime, timedelta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--agent-id", required=True)
    ap.add_argument("--mpp", type=int, required=True)
    ap.add_argument("--plugins", required=True)
    ap.add_argument("--patterns", default="")
    ap.add_argument("--hold-after-accepted", type=float, default=0.0)
    args = ap.parse_args()
    plugins = json.load(open(args.plugins, encoding="utf-8"))
    patterns = [l for l in open(args.patterns, encoding="utf-8").read().split("\n") if l] if args.patterns else []
    pickup = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    req = {"v": 1, "job": {"job_id": args.job_id, "agent_id": args.agent_id, "kind": "compliance", "pickup_by": pickup,
                           "plugins": plugins, "redaction_patterns": patterns}, "max_parallel_plugins": args.mpp}
    body = json.dumps(req, separators=(",", ":")).encode()
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.connect(args.sock)
    t0 = time.time()
    c.sendall(struct.pack(">I", len(body)) + body)
    out = open(args.log, "w", encoding="utf-8")
    buf = b""

    def frame() -> dict | None:
        nonlocal buf
        while True:
            if len(buf) >= 4:
                n = struct.unpack(">I", buf[:4])[0]
                if len(buf) >= 4 + n:
                    f = json.loads(buf[4:4 + n])
                    buf = buf[4 + n:]
                    return f
            chunk = c.recv(1 << 16)
            if not chunk:
                return None
            buf += chunk

    while True:
        f = frame()
        if f is None:
            out.write(json.dumps({"t": time.time() - t0, "type": "EOF"}) + "\n")
            break
        f["t"] = time.time() - t0
        out.write(json.dumps(f) + "\n")
        out.flush()
        if f.get("type") == "accepted" and args.hold_after_accepted:
            time.sleep(args.hold_after_accepted)
            out.write(json.dumps({"t": time.time() - t0, "type": "client-close"}) + "\n")
            break
    c.close()


if __name__ == "__main__":
    main()
