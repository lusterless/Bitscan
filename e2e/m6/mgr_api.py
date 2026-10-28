"""Standard-library API client for the manager-host walk (TP-M6-03/-04/-09).

Runs inside the manager host with the system python3.12 (`python3.12 -I`), so it
needs no Bitscan code. Secrets never go on the command line: passwords and the
session come from 0600 files, and printed output masks every bs?_ token.

  mgr_api.py admin  --url U --ca CA --user NAME --password-file F --state S
      sign in, enrol TOTP (start + confirm), sign in again with a code; the
      TOTP-verified session, the seed and the last used step go to S (0600).
  mgr_api.py call   --url U --ca CA --state S METHOD PATH [--body JSON] [--save-token FILE]
      one call with the session (or --token-file T); prints `<status> <json>`.
  mgr_api.py tls    --host H --port P --ca CA
      one handshake; prints the leaf's SHA-256 fingerprint (CHK-M6-081/-082).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{8,}")


def mask(text: str) -> str:
    return TOKEN.sub(lambda m: m.group(0)[:4] + "<masked>", text)


def code_at(seed: bytes, step: int) -> str:
    mac = hmac.new(seed, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[off : off + 4])[0] & 0x7FFFFFFF) % 10**6).zfill(6)


def write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)


class Client:
    def __init__(self, url: str, ca: str, token: str = "", machine_id: str = "") -> None:
        self.url, self.token, self.machine_id = url.rstrip("/"), token, machine_id
        self.ctx = ssl.create_default_context(cafile=ca)

    def call(self, method: str, path: str, body: object = None, token: str | None = None) -> tuple[int, object]:
        tok = self.token if token is None else token
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        if self.machine_id:
            headers["X-Bitscan-Machine-Id"] = self.machine_id
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw.decode(errors="replace")


def next_code(state: dict) -> str:
    seed = base64.b32decode(state["secret"] + "=" * (-len(state["secret"]) % 8))
    while True:
        step = int(time.time()) // 30
        if step > state.get("used", -1):
            state["used"] = step
            return code_at(seed, step)
        time.sleep(1)


def cmd_admin(a: argparse.Namespace) -> int:
    pw = Path(a.password_file).read_text().rstrip("\n")
    c = Client(a.url, a.ca)
    st, out = c.call("POST", "/api/v1/auth/login", {"username": a.user, "password": pw}, token="")
    print("login (no TOTP yet):", st, mask(json.dumps({k: v for k, v in (out or {}).items() if k != "token"})))
    if st != 200:
        return 1
    c.token = out["token"]
    st, out = c.call("POST", "/api/v1/auth/totp/enrol", {})
    print("totp/enrol start:", st, sorted((out or {}).keys()) if isinstance(out, dict) else out)
    if st != 200:
        return 1
    state = {"secret": out["secret"], "used": -1}
    st, out = c.call("POST", "/api/v1/auth/totp/enrol", {"totp_code": next_code(state)})
    print("totp/enrol confirm:", st, mask(json.dumps({k: v for k, v in (out or {}).items() if k != "token"})))
    if st != 200 or not out.get("totp_verified"):
        return 1
    state["token"] = out["token"]
    write_private(Path(a.state), json.dumps(state))
    st, me = Client(a.url, a.ca, state["token"]).call("GET", "/api/v1/settings")
    print("GET /settings with the confirmed session (TOTP-session route):", st)
    return 0 if st == 200 else 1


def cmd_call(a: argparse.Namespace) -> int:
    tok = Path(a.token_file).read_text().strip() if a.token_file else json.loads(Path(a.state).read_text())["token"]
    st, out = Client(a.url, a.ca, tok, a.machine_id or "").call(a.method, a.path, json.loads(a.body) if a.body else None)
    if a.save_token and isinstance(out, dict):
        for key in ("token", "agent_token"):
            if key in out:
                write_private(Path(a.save_token), out[key])
    text = out if isinstance(out, str) else json.dumps(out, sort_keys=True)
    print(st, mask(text))
    return 0 if 200 <= st < 300 else 1


def cmd_tls(a: argparse.Namespace) -> int:
    ctx = ssl.create_default_context(cafile=a.ca)
    with socket.create_connection((a.host, a.port), timeout=10) as s, ctx.wrap_socket(s, server_hostname=a.host) as t:
        der = t.getpeercert(binary_form=True)
        print("leaf sha256", hashlib.sha256(der).hexdigest(), t.version())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("admin")
    for k in ("--url", "--ca", "--user", "--password-file", "--state"):
        p.add_argument(k, required=True)
    p = sub.add_parser("call")
    p.add_argument("--url", required=True)
    p.add_argument("--ca", required=True)
    p.add_argument("--state")
    p.add_argument("--token-file")
    p.add_argument("--body")
    p.add_argument("--save-token")
    p.add_argument("--machine-id", help="sent as X-Bitscan-Machine-Id (agent routes)")
    p.add_argument("method")
    p.add_argument("path")
    p = sub.add_parser("tls")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--ca", required=True)
    a = ap.parse_args()
    return {"admin": cmd_admin, "call": cmd_call, "tls": cmd_tls}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
