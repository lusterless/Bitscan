#!/usr/bin/python3 -I
"""cmax-trigger: the client that Bitscan plugins call (TS §3.8).

  cmax-trigger collect
  cmax-trigger get <check-id> | header | status

It sends one request name to cmax-helper and prints the one-line answer. It
always exits 0, so the manager grades the printed text: a missing helper
prints NOHELPER, which fails the plugin's ExpectedResult.
"""

from __future__ import annotations

import os
import socket
import sys

SOCKET = "/run/clustermax/collect.sock"
# The helper waits up to 590 s for a running audit; the plugin timeout is 600 s.
TIMEOUT_S = 595


def request(words: list[str], path: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(TIMEOUT_S)
        conn.connect(path)
        conn.sendall((" ".join(words) + "\n").encode("ascii"))
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    return data.decode("utf-8", "replace").strip()


def main(argv: list[str]) -> int:
    if not (argv == ["collect"] or (len(argv) == 2 and argv[0] == "get")):
        print(
            "usage: cmax-trigger collect | cmax-trigger get <check-id|header|status>",
            file=sys.stderr,
        )
        return 2
    # The runner gives plugins an empty environment, so production always uses
    # SOCKET; the variable exists only for the collector's own tests.
    path = os.environ.get("CMAX_TRIGGER_SOCKET") or SOCKET
    try:
        print(request(argv, path) or "ERROR empty answer from cmax-helper")
    except FileNotFoundError:
        print("NOHELPER cmax-helper is not installed on this host")
    except ConnectionRefusedError:
        print("NOHELPER cmax-helper is not running")
    except TimeoutError:
        print("TIMEOUT cmax-helper did not answer")
    except OSError as exc:
        print(f"NOHELPER {exc.strerror or 'connection failed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
