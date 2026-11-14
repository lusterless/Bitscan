#!/usr/bin/python3 -I
"""cmax-helper: run the fixed ClusterMAX audit for the Bitscan runner (TS §3.8).

Started by systemd socket activation (cmax-helper.socket). Accepts only peers
with uid `bitscan-runner`, takes a request name and never a command line, runs
exactly `cmax audit -vvv -y`, and keeps the report only in memory. It exits
when it has been idle for IDLE_EXIT_S, which drops the report.

Requests (one line, at most MAX_REQUEST bytes):
  collect            start the audit unless one is running or a fresh report is held
  get <check-id>     wait for the audit, return that check's verdict line
  get header         wait for the audit, return the report's target block
  get status         ok <age-s> <cmax-version> | running | failed <rc> | none
"""

from __future__ import annotations

import os
import pwd
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

CMAX = "/usr/lib/clustermax/bin/cmax"
WORK_DIR = "/run/cmax-work"
ALLOWED_USER = "bitscan-runner"
FRESH_S = 30 * 60
IDLE_EXIT_S = 30 * 60
GET_WAIT_S = 590
MAX_REQUEST = 256
MAX_REPLY = 4000
CHECK_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
VERDICT = re.compile(r"^(PASS|FAIL|WARNING|SKIPPED|INFO)\s+.*\[([A-Za-z0-9_.-]+)\]\s*$")
# A ClusterMAX SKIPPED is "not applicable" (owner decision): printed as n/a.
TOKEN = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "WARNING": "WARNING",
    "SKIPPED": "n/a",
    "INFO": "PASS",
}


def audit_command(cmax: str = CMAX) -> list[str]:
    """The one command this helper ever runs (TS §3.8)."""
    return [cmax, "audit", "-vvv", "-y"]


def audit_environment(work_dir: str = WORK_DIR) -> dict[str, str]:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": work_dir,
        "LANG": "C.UTF-8",
    }


def parse_check(report: str, check_id: str) -> str:
    """Return '<VERDICT> observed=<value>' for one check, or MISSING."""
    lines = report.splitlines()
    for index, line in enumerate(lines):
        match = VERDICT.match(line)
        if match is None or match.group(2) != check_id:
            continue
        observed = ""
        for detail in lines[index + 1 :]:
            if VERDICT.match(detail) or not detail.startswith(" "):
                break
            stripped = detail.strip()
            if stripped.startswith("Observed:"):
                observed = stripped[len("Observed:") :].strip()
                break
        reply = (
            f"{TOKEN[match.group(1)]} observed={observed}"
            if observed
            else TOKEN[match.group(1)]
        )
        return reply[:MAX_REPLY]
    return f"MISSING {check_id} is not in the ClusterMAX report"


def parse_header(report: str) -> str:
    """The target block cmax prints before it starts (command, target, host...)."""
    block: list[str] = []
    started = False
    for line in report.splitlines():
        if line.startswith("# ClusterMAX audit target"):
            started = True
            continue
        if started:
            if not line.startswith("  "):
                break
            block.append(line.strip())
    return ("; ".join(block) or "MISSING no target block in the report")[:MAX_REPLY]


@dataclass
class State:
    """Shared state. All fields are guarded by `lock`."""

    lock: threading.Condition = field(default_factory=threading.Condition)
    running: bool = False
    report: str | None = None
    finished_at: float = 0.0
    exit_code: int | None = None
    last_activity: float = field(default_factory=time.monotonic)


class Helper:
    def __init__(
        self,
        *,
        command: list[str],
        environment: dict[str, str],
        work_dir: str,
        version: str,
        clock: Callable[[], float] = time.monotonic,
        get_wait_s: float = GET_WAIT_S,
    ) -> None:
        self.command = command
        self.environment = environment
        self.work_dir = work_dir
        self.version = version
        self.clock = clock
        self.get_wait_s = get_wait_s
        self.state = State(last_activity=clock())

    # -- audit -----------------------------------------------------------
    def _fresh(self) -> bool:
        s = self.state
        return (
            s.report is not None
            and s.exit_code == 0
            and self.clock() - s.finished_at < FRESH_S
        )

    def collect(self) -> str:
        s = self.state
        with s.lock:
            s.last_activity = self.clock()
            if s.running:
                return "running"
            if self._fresh():
                return "ready"
            s.running = True
            s.report = None
            s.exit_code = None
        threading.Thread(target=self._run, daemon=True).start()
        return "started"

    def _run(self) -> None:
        try:
            done = subprocess.run(
                self.command,
                cwd=self.work_dir,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            text, code = (
                ANSI.sub("", done.stdout.decode("utf-8", "replace")),
                done.returncode,
            )
        except OSError as exc:
            text, code = f"cmax could not start: {exc.strerror}", 127
        s = self.state
        with s.lock:
            s.report, s.exit_code = text, code
            s.running = False
            s.finished_at = s.last_activity = self.clock()
            s.lock.notify_all()

    def _wait(self) -> str | None:
        """Wait for a running audit; return the report, or None."""
        s = self.state
        deadline = self.clock() + self.get_wait_s
        with s.lock:
            while s.running:
                left = deadline - self.clock()
                if left <= 0:
                    return None
                s.lock.wait(timeout=min(left, 5.0))
            return s.report

    def get(self, what: str) -> str:
        s = self.state
        with s.lock:
            s.last_activity = self.clock()
            if what == "status":
                if s.running:
                    return "running"
                if s.report is None:
                    return "none"
                if s.exit_code != 0:
                    return f"failed {s.exit_code}"
                return f"ok {int(self.clock() - s.finished_at)} {self.version}"
        report = self._wait()
        if report is None:
            with s.lock:
                return (
                    "TIMEOUT the audit is still running"
                    if s.running
                    else "MISSING no report; send collect first"
                )
        if s.exit_code != 0:
            return f"ERROR cmax exited {s.exit_code}"
        return parse_header(report) if what == "header" else parse_check(report, what)

    def handle(self, request: str) -> str:
        words = request.split()
        if words == ["collect"]:
            return self.collect()
        if (
            len(words) == 2
            and words[0] == "get"
            and (words[1] in {"header", "status"} or CHECK_ID.fullmatch(words[1]))
        ):
            return self.get(words[1])
        return "REFUSED unknown request"

    def idle(self) -> bool:
        s = self.state
        with s.lock:
            return not s.running and self.clock() - s.last_activity >= IDLE_EXIT_S


def peer_uid(conn: socket.socket) -> int:
    data = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    uid: int = struct.unpack("3i", data)[1]
    return uid


def read_request(conn: socket.socket) -> str | None:
    data = b""
    while b"\n" not in data and len(data) <= MAX_REQUEST:
        chunk = conn.recv(MAX_REQUEST + 1 - len(data))
        if not chunk:
            break
        data += chunk
    if len(data) > MAX_REQUEST or b"\n" not in data:
        return None
    try:
        return data.split(b"\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None


def serve_connection(helper: Helper, conn: socket.socket, allowed_uid: int) -> None:
    with conn:
        conn.settimeout(10)
        try:
            request = read_request(conn)
            if peer_uid(conn) != allowed_uid:
                # The request is read (bounded) and ignored, so the client gets
                # this answer instead of a reset connection.
                conn.sendall(b"REFUSED peer is not allowed\n")
                return
            reply = "REFUSED bad request" if request is None else helper.handle(request)
            conn.settimeout(None)
            conn.sendall(reply.encode("utf-8", "replace") + b"\n")
        except OSError:
            return


def serve(helper: Helper, listener: socket.socket, allowed_uid: int) -> None:
    listener.settimeout(5)
    while True:
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            if helper.idle():
                return
            continue
        threading.Thread(
            target=serve_connection, args=(helper, conn, allowed_uid), daemon=True
        ).start()


def cmax_version(cmax: str = CMAX) -> str:
    try:
        out = subprocess.run(
            [cmax, "-v"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    words = out.stdout.split()
    return words[-1] if out.returncode == 0 and words else "unknown"


def systemd_listener() -> socket.socket:
    """The socket systemd passed (LISTEN_FDS, fd 3)."""
    if (
        os.environ.get("LISTEN_PID") != str(os.getpid())
        or os.environ.get("LISTEN_FDS") != "1"
    ):
        raise SystemExit("cmax-helper: start it through cmax-helper.socket")
    return socket.socket(fileno=3)


def main(argv: list[str]) -> int:
    if argv != ["--serve"]:
        print("usage: cmax-helper --serve", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("cmax-helper: must run as root", file=sys.stderr)
        return 1
    allowed_uid = pwd.getpwnam(ALLOWED_USER).pw_uid
    listener = systemd_listener()
    helper = Helper(
        command=audit_command(),
        environment=audit_environment(),
        work_dir=WORK_DIR,
        version=cmax_version(),
    )
    serve(helper, listener, allowed_uid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
