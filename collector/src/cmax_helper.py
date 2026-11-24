#!/usr/bin/python3 -I
"""cmax-helper: the ClusterMAX scanner role's root helper (TS §3.8; owner
decisions 2026-11-14, 2026-11-15, 2026-11-23).

Started by systemd socket activation (cmax-helper.socket). Accepts only peers
with uid `bitscan` (the agent). One request per connection: a JSON line
{"job_id", "target", "vars"} of at most MAX_REQUEST bytes, plus at most one
file descriptor (SCM_RIGHTS), a sealed memfd holding the job's kubeconfig.
It runs exactly `cmax audit -vvv -y` (plus --standalone, --slurm or --k8s when
the target is not auto) with the allow-listed variables, one audit at a time,
and answers with a JSON line followed by the files. It never takes a command
line, a path or any other variable, and writes nothing that outlives the run.

Answer: {"exit_code", "started_at", "finished_at", "cmax_version", "files":
[{"name", "size", "truncated"}]} then each file's bytes in that order; the
agent reads the checks from report.txt. A refused request gets
`REFUSED <reason>` and a second request while one runs `BUSY`.
"""

from __future__ import annotations

import array
import fcntl
import json
import os
import pwd
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

CMAX = "/usr/lib/clustermax/bin/cmax"
WORK_DIR = "/run/cmax-work"
ALLOWED_USER = "bitscan"
IDLE_EXIT_S = 30 * 60
AUDIT_LIMIT_S = 4 * 3600
TIMEOUT_EXIT = 124
MAX_REQUEST = 4096
MAX_FILE = 64 * 1024 * 1024
JOB_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
TARGET_FLAGS = {
    "auto": None,
    "standalone": "--standalone",
    "slurm": "--slurm",
    "k8s": "--k8s",
}
_DNS = r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?"
_NAMESPACE = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
# TS §3.8: the same list as the manager's; changing it is a spec change.
ALLOWED_VARS = {
    "CLUSTERMAX_K8S_GPU_DRA": re.compile(r"[01]"),
    "CLUSTERMAX_K8S_GPU_DRA_DEVICE_CLASS": re.compile(_DNS),
    "CLUSTERMAX_K8S_GPU_DRA_DRIVER": re.compile(_DNS),
    "CLUSTERMAX_AUDIT_K8S_NAMESPACE": re.compile(_NAMESPACE),
    "CLUSTERMAX_AUDIT_TENANT_NAMESPACE": re.compile(_NAMESPACE),
}
SEALS = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE


def audit_command(target: str = "auto", cmax: str = CMAX) -> list[str]:
    """The one command this helper ever runs (TS §3.8)."""
    flag = TARGET_FLAGS[target]
    return [cmax, "audit", "-vvv", "-y"] + ([flag] if flag else [])


# Where cluster tools and configs live when they are not on the default PATH
# (RKE2, Slurm built from source, snap), so the audit finds Slurm or
# Kubernetes as a root shell on the host would (owner decision 2026-11-21).
EXTRA_PATH = (
    "/var/lib/rancher/rke2/bin",
    "/opt/slurm/bin",
    "/snap/bin",
    "/usr/local/cuda/bin",
)
# The check scripts run with the system python3, so they find the vendored
# packages (PyYAML) only through PYTHONPATH (owner decision 2026-11-21).
SITE = "/usr/lib/clustermax/site"
KUBECONFIGS = (
    "/root/.kube/config",
    "/etc/rancher/k3s/k3s.yaml",
    "/etc/rancher/rke2/rke2.yaml",
    "/etc/kubernetes/admin.conf",
)
# slurm.conf in a place the Slurm tools do not look by default.
SLURM_CONFS = ("/etc/slurm-llnl/slurm.conf", "/opt/slurm/etc/slurm.conf")


def audit_environment(
    work_dir: str = WORK_DIR,
    exists: Callable[[str], bool] = os.path.isfile,
    home: str = "/root",
) -> dict[str, str]:
    """HOME is root's, as under `sudo cmax`, so cloud, Docker and enroot
    credentials are found; ClusterMAX writes its report files to work_dir
    (CLUSTERMAX_RUNS_ROOT, tmpfs), which is emptied after each run."""
    env = {
        "PATH": ":".join(
            (
                "/usr/local/sbin",
                "/usr/local/bin",
                "/usr/sbin",
                "/usr/bin",
                "/sbin",
                "/bin",
            )
            + EXTRA_PATH
        ),
        "HOME": home,
        "LANG": "C.UTF-8",
        "CLUSTERMAX_RUNS_ROOT": work_dir,
        "PYTHONPATH": SITE,
    }
    kubeconfig = next((p for p in KUBECONFIGS if exists(p)), None)
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    if not exists("/etc/slurm/slurm.conf"):
        slurm_conf = next((p for p in SLURM_CONFS if exists(p)), None)
        if slurm_conf:
            env["SLURM_CONF"] = slurm_conf
    return env


def clear_dir(path: str) -> None:
    """Remove what the finished audit wrote under path; the report text is
    already held in memory."""
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path, ignore_errors=True)
        else:
            try:
                os.unlink(entry.path)
            except OSError:
                pass


class Refused(Exception):
    """The request is refused; the message is the reason sent to the agent."""


@dataclass(frozen=True)
class Request:
    job_id: str
    target: str
    vars: dict[str, str]


def parse_request(line: bytes) -> Request:
    try:
        doc = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("bad request") from None
    if not isinstance(doc, dict) or set(doc) != {"job_id", "target", "vars"}:
        raise Refused("bad request")
    job_id, target, variables = doc["job_id"], doc["target"], doc["vars"]
    if not isinstance(job_id, str) or JOB_ID.fullmatch(job_id) is None:
        raise Refused("bad job_id")
    if target not in TARGET_FLAGS:
        raise Refused("bad target")
    if not isinstance(variables, dict):
        raise Refused("bad vars")
    for name, value in variables.items():
        pattern = ALLOWED_VARS.get(name)
        if (
            pattern is None
            or not isinstance(value, str)
            or pattern.fullmatch(value) is None
        ):
            raise Refused("variable not allowed")
    return Request(job_id, target, dict(variables))


def check_memfd(fd: int) -> None:
    """The passed descriptor must be a sealed memfd: no file on any disk."""
    try:
        seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        link = os.readlink(f"/proc/self/fd/{fd}")
        mode = os.fstat(fd).st_mode
    except OSError:
        raise Refused("descriptor is not a sealed memfd") from None
    if (
        seals & SEALS != SEALS
        or not link.startswith("/memfd:")
        or not stat.S_ISREG(mode)
    ):
        raise Refused("descriptor is not a sealed memfd")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _find(work_dir: str, name: str) -> str | None:
    for root, _dirs, files in os.walk(work_dir):
        if name in files:
            return os.path.join(root, name)
    return None


def _capped(data: bytes) -> tuple[bytes, bool]:
    return (data[:MAX_FILE], True) if len(data) > MAX_FILE else (data, False)


@dataclass(frozen=True)
class Outcome:
    header: dict[str, object]
    files: list[tuple[str, bytes]]


class Helper:
    def __init__(
        self,
        *,
        cmax: str,
        environment: Mapping[str, str],
        work_dir: str,
        version: str,
        limit_s: float = AUDIT_LIMIT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cmax = cmax
        self.environment = dict(environment)
        self.work_dir = work_dir
        self.version = version
        self.limit_s = limit_s
        self.clock = clock
        self.lock = threading.Lock()
        self.last_activity = clock()

    def run(self, request: Request, kubeconfig_fd: int | None) -> Outcome:
        """Runs one audit; the caller holds self.lock."""
        env = dict(self.environment) | request.vars
        env["KUBECACHEDIR"] = os.path.join(self.work_dir, "kube-cache")
        if kubeconfig_fd is not None:
            env["KUBECONFIG"] = f"/proc/{os.getpid()}/fd/{kubeconfig_fd}"
        started = _now()
        try:
            done = subprocess.run(
                audit_command(request.target, self.cmax),
                cwd=self.work_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.limit_s,
                check=False,
            )
            stdout, stderr, code = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, code = exc.stdout or b"", exc.stderr or b"", TIMEOUT_EXIT
        except OSError as exc:
            stdout, stderr, code = (
                b"",
                f"cmax could not start: {exc.strerror}".encode(),
                127,
            )
        finished = _now()
        files: list[tuple[str, bytes]] = [
            ("report.txt", ANSI.sub("", stdout.decode("utf-8", "replace")).encode()),
            ("run.log", ANSI.sub("", stderr.decode("utf-8", "replace")).encode()),
        ]
        for name in ("audit.out", "audit.values.json"):
            path = _find(self.work_dir, name)
            if path is not None:
                with open(path, "rb") as handle:
                    files.append((name, handle.read(MAX_FILE + 1)))
        clear_dir(self.work_dir)
        capped = [(name, *_capped(data)) for name, data in files]
        header: dict[str, object] = {
            "exit_code": code,
            "started_at": started,
            "finished_at": finished,
            "cmax_version": self.version,
            "files": [
                {"name": n, "size": len(d), "truncated": t} for n, d, t in capped
            ],
        }
        return Outcome(header, [(n, d) for n, d, _ in capped])

    def idle(self) -> bool:
        return (
            not self.lock.locked() and self.clock() - self.last_activity > IDLE_EXIT_S
        )


def peer_uid(conn: socket.socket) -> int:
    data = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    uid: int = struct.unpack("3i", data)[1]
    return uid


def read_request(conn: socket.socket) -> tuple[bytes, list[int]]:
    """The request line and the descriptors sent with it (closed by the
    caller). More than one descriptor, or a line over MAX_REQUEST, is refused."""
    fds = array.array("i")
    data = b""
    received: list[int] = []
    while b"\n" not in data and len(data) <= MAX_REQUEST:
        msg, ancdata, _flags, _addr = conn.recvmsg(
            MAX_REQUEST + 1 - len(data), socket.CMSG_SPACE(2 * fds.itemsize)
        )
        for level, kind, payload in ancdata:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                got = array.array("i")
                got.frombytes(payload[: len(payload) - len(payload) % got.itemsize])
                received.extend(got)
        if not msg:
            break
        data += msg
    if len(data) > MAX_REQUEST or b"\n" not in data:
        raise _Bad(received, "bad request")
    if len(received) > 1:
        raise _Bad(received, "more than one descriptor")
    return data.split(b"\n", 1)[0], received


class _Bad(Exception):
    def __init__(self, fds: list[int], reason: str) -> None:
        super().__init__(reason)
        self.fds = fds
        self.reason = reason


def _drain(conn: socket.socket) -> None:
    """Reads what the peer still sends (at most 64 KiB, 1 s), so closing does
    not reset the connection before it reads the refusal."""
    conn.shutdown(socket.SHUT_WR)
    conn.settimeout(1)
    left = 64 * 1024
    while left > 0 and (chunk := conn.recv(min(left, 4096))):
        left -= len(chunk)


def serve_connection(helper: Helper, conn: socket.socket, allowed_uid: int) -> None:
    fds: list[int] = []
    with conn:
        try:
            conn.settimeout(10)
            try:
                line, fds = read_request(conn)
            except _Bad as bad:
                fds = bad.fds
                conn.sendall(f"REFUSED {bad.reason}\n".encode())
                _drain(conn)
                return
            if peer_uid(conn) != allowed_uid:
                conn.sendall(b"REFUSED peer is not allowed\n")
                return
            try:
                request = parse_request(line)
                if fds:
                    check_memfd(fds[0])
                    if request.target != "k8s":
                        raise Refused("a kubeconfig needs target k8s")
            except Refused as exc:
                conn.sendall(f"REFUSED {exc}\n".encode())
                return
            if not helper.lock.acquire(blocking=False):
                conn.sendall(b"BUSY\n")
                return
            try:
                helper.last_activity = helper.clock()
                outcome = helper.run(request, fds[0] if fds else None)
            finally:
                for fd in fds:
                    os.close(fd)
                fds = []
                helper.last_activity = helper.clock()
                helper.lock.release()
            conn.settimeout(None)
            conn.sendall(json.dumps(outcome.header).encode() + b"\n")
            for _name, data in outcome.files:
                conn.sendall(data)
        except OSError:
            return
        finally:
            for fd in fds:
                os.close(fd)


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
    import ctypes  # Linux only, at start-up

    ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE 0: no core, no ptrace
    allowed_uid = pwd.getpwnam(ALLOWED_USER).pw_uid
    listener = systemd_listener()
    helper = Helper(
        cmax=CMAX,
        environment=audit_environment(),
        work_dir=WORK_DIR,
        version=cmax_version(),
    )
    serve(helper, listener, allowed_uid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
