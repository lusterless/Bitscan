#!/usr/bin/python3 -I
"""cmax-trigger: the client that Bitscan plugins call (TS §3.8).

  cmax-trigger collect
  cmax-trigger get <check-id> | header | status

One audit per scan job: under a lock on `cmax-run.lock` in the job's temp
directory (the parent of the plugin's working directory, TS §3.7), the first
plugin of the job sends `collect` and writes the answer (`started <run-id>`
or `running <run-id>`) to `cmax-run` there; every later plugin of the job
reads it. `collect` prints that answer; `get` asks for its item of that run.
The runner deletes the job's temp directory when the job ends, so the next
scan starts a new audit.

It prints one line and always exits 0, so the manager grades the printed
text: a missing helper prints NOHELPER, which fails the plugin's
ExpectedResult.
"""

from __future__ import annotations

import fcntl
import os
import re
import socket
import sys

SOCKET = "/run/clustermax/collect.sock"
# The helper waits up to 590 s for a running audit; the plugin timeout is 600 s.
TIMEOUT_S = 595
STARTED = re.compile(r"(started|running) ([0-9a-f]{32})")
JOB_DIR_PREFIX = "bitscan-j-"


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


def job_dir() -> str | None:
    """The job's temp directory, or None when not run by the Bitscan runner
    (then every call starts or joins an audit on its own)."""
    parent = os.path.dirname(os.getcwd())
    return parent if os.path.basename(parent).startswith(JOB_DIR_PREFIX) else None


def job_run(path: str) -> str:
    """The job's collect answer, sending collect only for the job's first
    plugin. An answer that is not `started|running <run-id>` (no helper, a
    refusal) is printed as is and not saved, so a later plugin retries."""
    folder = job_dir()
    if folder is None:
        return request(["collect"], path)
    with open(os.path.join(folder, "cmax-run.lock"), "a", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = os.path.join(folder, "cmax-run")
        try:
            with open(saved, encoding="ascii") as f:
                answer = f.read().strip()
            if STARTED.fullmatch(answer):
                return answer
        except OSError:
            pass
        answer = request(["collect"], path)
        if STARTED.fullmatch(answer):
            with open(saved, "w", encoding="ascii") as f:
                f.write(answer + "\n")
        return answer


def answer(argv: list[str], path: str) -> str:
    run = job_run(path)
    if argv == ["collect"]:
        return run
    match = STARTED.fullmatch(run)
    if match is None:
        return run or "ERROR empty answer from cmax-helper"
    return request(["get", match.group(2), argv[1]], path)


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
        print(answer(argv, path) or "ERROR empty answer from cmax-helper")
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
