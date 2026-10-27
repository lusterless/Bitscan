"""Minimal TLS listener for the M6 Wave 0 network check (TP-M6-01).

Answers every GET with a fixed body that carries a run nonce, so the caller
can prove the reply came from this listener (not from something else that
happens to listen on the port). Standard library only; run with `python3 -I`.

Usage: python3 -I tls_listener.py --bind ADDR --port N --cert PEM --key PEM --body TEXT
"""

from __future__ import annotations

import argparse
import http.server
import ssl
import sys


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--cert", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--body", required=True)
    a = p.parse_args(argv)
    body = (a.body + "\n").encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write("netcheck %s %s\n" % (self.client_address[0], fmt % args))
            sys.stderr.flush()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(a.cert, a.key)
    srv = http.server.ThreadingHTTPServer((a.bind, a.port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    sys.stderr.write("netcheck listening on %s:%d\n" % (a.bind, a.port))
    sys.stderr.flush()
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
