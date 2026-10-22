"""Local fake audit sinks for TP-M2-10 and TP-M2-12 (tester-owned).

SyslogTlsSink: a TLS listener that reads RFC 5425 octet-counted frames.
HttpsSink: an HTTPS listener that records each POST and answers with a
scripted status. Both run on 127.0.0.1 in daemon threads.
"""

import http.server
import socket
import ssl
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


def server_context(
    cert: Path, key: Path, max_version: ssl.TLSVersion | None = None
) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    if max_version is not None:
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.maximum_version = max_version
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx


def split_frames(data: bytes) -> list[bytes]:
    """RFC 5425 §4.3: MSG-LEN SP SYSLOG-MSG, repeated. Raises on bad framing."""
    frames: list[bytes] = []
    pos = 0
    while pos < len(data):
        space = data.index(b" ", pos)
        length_text = data[pos:space]
        assert length_text.isdigit() and not length_text.startswith(b"0"), length_text
        length = int(length_text)
        start = space + 1
        frame = data[start : start + length]
        assert len(frame) == length, "frame shorter than its MSG-LEN"
        frames.append(frame)
        pos = start + length
    return frames


@dataclass
class SyslogTlsSink:
    context: ssl.SSLContext | None  # None: accept TCP and never answer
    port: int = 0
    raw: list[bytes] = field(default_factory=list)
    connections: int = 0
    handshakes_failed: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)

    def frames(self) -> list[bytes]:
        return [f for chunk in self.raw for f in split_frames(chunk)]

    def run(self, sock: socket.socket) -> None:
        sock.settimeout(0.2)
        held: list[socket.socket] = []
        while not self._stop.is_set():
            try:
                conn, _ = sock.accept()
            except OSError:
                continue
            self.connections += 1
            if self.context is None:
                held.append(conn)
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
        for c in held:
            c.close()

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        assert self.context is not None
        try:
            tls = self.context.wrap_socket(conn, server_side=True)
        except (OSError, ssl.SSLError):
            self.handshakes_failed += 1
            conn.close()
            return
        data = b""
        try:
            while True:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                data += chunk
        except (OSError, ssl.SSLError):
            pass
        finally:
            self.raw.append(data)
            try:
                tls.unwrap().close()
            except (OSError, ssl.SSLError, ValueError):
                tls.close()


@contextmanager
def syslog_sink(context: ssl.SSLContext | None) -> Iterator[SyslogTlsSink]:
    sink = SyslogTlsSink(context)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    sink.port = sock.getsockname()[1]
    thread = threading.Thread(target=sink.run, args=(sock,), daemon=True)
    thread.start()
    try:
        yield sink
    finally:
        sink._stop.set()
        thread.join(3)
        sock.close()


def wait_for(predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return True
        time.sleep(0.02)
    return bool(callable(predicate) and predicate())


@dataclass
class Post:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class HttpsSink:
    statuses: Sequence[int] = (200,)
    delay_s: float = 0.0
    response_body: bytes = b""
    posts: list[Post] = field(default_factory=list)
    port: int = 0


@contextmanager
def https_sink(
    context: ssl.SSLContext,
    statuses: Sequence[int] = (200,),
    delay_s: float = 0.0,
    response_body: bytes = b"",
) -> Iterator[HttpsSink]:
    sink = HttpsSink(statuses, delay_s, response_body)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            sink.posts.append(
                Post(self.path, {k.lower(): v for k, v in self.headers.items()}, body)
            )
            if sink.delay_s:
                time.sleep(sink.delay_s)
            index = min(len(sink.posts) - 1, len(sink.statuses) - 1)
            status = sink.statuses[index]
            self.send_response(status)
            if 300 <= status < 400:
                self.send_header("Location", f"https://127.0.0.1:{sink.port}/elsewhere")
            self.send_header("Content-Length", str(len(sink.response_body)))
            self.end_headers()
            self.wfile.write(sink.response_body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    sink.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield sink
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
