"""The two test doubles of the manager host (#93), as one long-running process.

  python3.12 -I doubles.py --dir DIR --cert C --key K [--vault-port 18200] [--sink-port 18300]
                           [--transit-key bitscan-totp]

- OpenBao Transit fake on https://127.0.0.1:<vault-port>: the encrypt/decrypt
  semantics of manager/tests/fake_vault.py (FakeVault.answer, copied next to
  this file). The token is read from DIR/vault.token (0600) on every request,
  so replacing that file replaces the accepted token (create new + revoke old)
  without a restart. The key material (pad and ciphertexts) is kept in
  DIR/vault-state.json (0600), so a restart keeps the "Transit key" as a real
  OpenBao would. Every request path and status is appended to DIR/vault.jsonl
  (never the token or a body).
  The token acts as one created from the manager-install.md §1.2 role: POST
  `transit/encrypt|decrypt/<transit-key>` and `auth/token/renew-self` are
  allowed (renew-self answers a 7-day periodic lease with only the
  `bitscan-manager` policy, as a real OpenBao does, CHK-M6-133r2-13); every
  other path or method answers 403, as the policy denies it. This lets the
  runbook's §5 token check and renewal timer run as written (M11 TP-M11-17).
- HTTPS audit sink on https://127.0.0.1:<sink-port>/bitscan: every POST body is
  appended to DIR/sink.jsonl with its arrival time, answered 200.
They stand in for systems outside Bitscan; nothing here is a product file.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import ssl
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_vault import FakeVault  # noqa: E402

LOCK = threading.Lock()


def append(path: Path, entry: dict) -> None:
    with LOCK, path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def serve(port: int, ctx: ssl.SSLContext, handler: type) -> threading.Thread:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--vault-port", type=int, default=18200)
    ap.add_argument("--sink-port", type=int, default=18300)
    ap.add_argument("--transit-key", default="bitscan-totp")
    a = ap.parse_args()
    transit = {f"/v1/transit/encrypt/{a.transit_key}", f"/v1/transit/decrypt/{a.transit_key}"}
    renew = "/v1/auth/token/renew-self"
    denied = 403, b'{"errors":["permission denied"]}'
    d = Path(a.dir)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(a.cert, a.key)
    vault = FakeVault("")
    state = d / "vault-state.json"
    if state.exists():
        saved = json.loads(state.read_text())
        vault._pad = bytes.fromhex(saved["pad"])
        vault.stored = {k: bytes.fromhex(v) for k, v in saved["stored"].items()}

    def save() -> None:
        fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"pad": vault._pad.hex(), "stored": {k: v.hex() for k, v in vault.stored.items()}}, f)

    class Vault(http.server.BaseHTTPRequestHandler):
        def reply(self, status: int, out: bytes) -> None:
            append(d / "vault.jsonl", {"t": time.time(), "method": self.command, "path": self.path, "status": status})
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.headers.get("X-Vault-Token") != (d / "vault.token").read_text().strip():
                self.reply(*denied)
            elif self.path == renew:
                auth = {"lease_duration": 604800, "renewable": True, "policies": ["bitscan-manager"]}
                self.reply(200, json.dumps({"auth": auth}).encode())
            elif self.path not in transit:
                self.reply(*denied)
            else:
                with LOCK:
                    status, out = vault.answer(self.path, json.loads(raw or b"{}"))
                    save()
                self.reply(status, out)

        def do_GET(self) -> None:  # noqa: N802
            self.reply(*denied)  # the role's policy grants no read path

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return None

    class Sink(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                body: object = json.loads(raw)
            except ValueError:
                body = raw.decode(errors="replace")
            append(d / "sink.jsonl", {"t": time.time(), "path": self.path, "body": body})
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return None

    serve(a.vault_port, ctx, Vault)
    serve(a.sink_port, ctx, Sink)
    print(f"doubles up: vault 127.0.0.1:{a.vault_port}, sink 127.0.0.1:{a.sink_port}", flush=True)
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
