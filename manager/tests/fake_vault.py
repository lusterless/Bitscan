"""A local fake OpenBao Transit server (TP-M2-08, tester-owned).

Implements POST /v1/transit/encrypt/<key> and /v1/transit/decrypt/<key> over
HTTPS on 127.0.0.1 with its own encryption (a random XOR pad, so the
ciphertext shares nothing with the seed), records every request, and can be
switched into failure modes.
"""

import base64
import http.server
import json
import secrets
import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Seen:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class FakeVault:
    token: str
    mode: str = "good"  # good, status, raw, delay, redirect
    status: int = 200
    raw: bytes = b""
    delay_s: float = 0.0
    redirect_to: str = ""
    requests: list[Seen] = field(default_factory=list)
    stored: dict[str, bytes] = field(default_factory=dict)  # ciphertext -> plaintext
    port: int = 0
    _pad: bytes = field(default_factory=lambda: secrets.token_bytes(64))

    def _encrypt(self, plaintext: bytes) -> str:
        nonce = secrets.token_bytes(8)
        mixed = bytes(
            b ^ self._pad[i % 64] ^ nonce[i % 8] for i, b in enumerate(plaintext)
        )
        text = "vault:v1:" + base64.b64encode(nonce + mixed).decode()
        self.stored[text] = plaintext
        return text

    def answer(self, path: str, body: dict[str, Any]) -> tuple[int, bytes]:
        if self.mode == "status":
            return self.status, self.raw
        if self.mode == "raw":
            return 200, self.raw
        if self.mode == "delay":
            time.sleep(self.delay_s)
        key_path = path.split("/")
        if len(key_path) != 5 or key_path[:3] != ["", "v1", "transit"]:
            return 404, b'{"errors":["no handler"]}'
        op = key_path[3]
        if op == "encrypt":
            plaintext = base64.b64decode(body["plaintext"], validate=True)
            data = {"ciphertext": self._encrypt(plaintext), "key_version": 1}
        elif op == "decrypt":
            stored = self.stored.get(body["ciphertext"])
            if stored is None:
                return 400, b'{"errors":["invalid ciphertext"]}'
            data = {"plaintext": base64.b64encode(stored).decode()}
        else:
            return 404, b'{"errors":["no handler"]}'
        return 200, json.dumps({"data": data}).encode()


@contextmanager
def fake_vault(context: ssl.SSLContext, token: str) -> Iterator[FakeVault]:
    vault = FakeVault(token)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {k.lower(): v for k, v in self.headers.items()}
            vault.requests.append(Seen(self.path, headers, raw))
            if vault.mode == "redirect":
                self.send_response(307)
                self.send_header("Location", vault.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if headers.get("x-vault-token") != vault.token:
                status, out = 403, b'{"errors":["permission denied"]}'
            else:
                status, out = vault.answer(self.path, json.loads(raw or b"{}"))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    vault.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield vault
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
