"""Bitscan M10 sandbox and runner-security suite (G76, G77 and the host part of G78).

TS §8.3 Sandbox and Security; REQ-235 to REQ-241, REQ-252 to REQ-255, REQ-259,
REQ-261, REQ-262; tests/m10/test-plan.md TP-M10-20 (CHK-M10-200 to -223) and
TP-M10-21 (CHK-M10-280 to -289).

Run as root on a sandbox host (a throwaway VM restored from `clean`, a GitHub
hosted runner, or a systemd test container) where the `.deb` under test was
just installed by run_vm.sh. It plays the agent's part only: every job is sent
straight to /run/bitscan/runner.sock as uid `bitscan`, built from the probe
plugins below. It never connects to a manager and is never shipped.

Each row is PASS, FAIL or NOT RUN (with a reason); nothing is skipped silently.
No token, canary or plugin output beyond the probe fields is written to the
report, and every excerpt is masked for `bs[uaek]_`.

Usage (root): python3 -I sandbox.py --out DIR [--rows ID,ID] [--samples DIR]
                [--expect-red ID] [--label TEXT]
Client mode (internal; run as bitscan or another user by the suite):
              python3 -I sandbox.py --client REQ OUT TIMEOUT HOLD
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pwd
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
import xml.etree.ElementTree as ET  # noqa: S405 - repo-owned sample files only
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOCK = "/run/bitscan/runner.sock"
CAPSOCK = "/run/bitscan/capread.sock"
AGENT_ID_FILE = "/var/lib/bitscan-agent/agent_id"
MARK_SOCK = "/run/bs-sbx-open.sock"
PATH_ENV = "PATH=/usr/sbin:/usr/bin:/sbin:/bin"
RUNNER_UNIT = "bitscan-runner.service"
DROPIN_DIR = "/run/systemd/system/bitscan-runner.service.d"
BLOCKED = [
    "/run/docker.sock",
    "/var/run/docker.sock",
    "/run/containerd/containerd.sock",
    "/run/snapd.socket",
    "/run/snapd-snap.socket",
    "/run/systemd/journal/socket",
    "/run/systemd/journal/stdout",
    "/run/systemd/journal/syslog",
    "/run/systemd/journal/dev-log",
]
UTC = timezone.utc
TOKEN_RE = re.compile(r"bs[uaek]_[A-Za-z0-9_-]{4,}")


def mask(s: str) -> str:
    return TOKEN_RE.sub("bs?_[MASKED]", s)


# --------------------------------------------------------------------------
# client mode: one connection, run as the requested user by the suite
# --------------------------------------------------------------------------


def client_main(req_path: str, out_path: str, timeout: float, hold: float) -> int:
    frames: list[dict] = []
    status = "eof"
    raw = Path(req_path).read_bytes()
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(timeout)
    t0 = time.time()
    try:
        c.connect(SOCK)
    except OSError as e:
        Path(out_path).write_text(json.dumps({"connect_errno": e.errno, "frames": [], "status": "connect"}))
        return 0
    buf = b""
    try:
        c.sendall(raw)
        while True:
            while len(buf) < 4 or len(buf) < 4 + struct.unpack(">I", buf[:4])[0]:
                chunk = c.recv(1 << 16)
                if not chunk:
                    raise EOFError
                buf += chunk
            n = struct.unpack(">I", buf[:4])[0]
            f = json.loads(buf[4 : 4 + n])
            buf = buf[4 + n :]
            f["t"] = round(time.time() - t0, 3)
            frames.append(f)
            if f.get("type") == "accepted" and hold > 0:
                time.sleep(hold)
                status = "client-close"
                break
            if f.get("type") in ("done", "refused"):
                # read on: anything after done or refused is a defect
                c.settimeout(2)
    except EOFError:
        status = "eof"
    except TimeoutError:
        status = "timeout"
    except ConnectionResetError:
        status = "reset"
    except OSError as e:
        status = "oserror-%d" % (e.errno or 0)
    c.close()
    Path(out_path).write_text(json.dumps({"connect_errno": 0, "frames": frames, "status": status}))
    return 0


# --------------------------------------------------------------------------
# suite helpers
# --------------------------------------------------------------------------


class Ctx:
    def __init__(self, out: Path, work: Path) -> None:
        self.out = out
        self.work = work
        self.aid = Path(AGENT_ID_FILE).read_text().strip()
        self.runner_uid = pwd.getpwnam("bitscan-runner").pw_uid
        self.marks: list[str] = []
        self.canary_exec = "BSSBXEXEC" + secrets.token_hex(6).upper()
        self.canary_out = "BSSBXOUT" + secrets.token_hex(6).upper()
        self.canary_err = "BSSBXERR" + secrets.token_hex(6).upper()
        self.canary_pat = "BSSBXPAT" + secrets.token_hex(6).upper()
        self.canary_tok = "bsa_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        self.started = datetime.now(UTC)
        self.journal_since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 2))
        self.n = 0
        self.patterns = default_patterns()


def default_patterns() -> list[str]:
    # The TS §8.6 default list (sandbox hosts have no spec copy; kept in step
    # with docs/spec/Technical_Specification.md "Default redaction patterns").
    return [
        r"\$(?:1|2[abxy]?|5|6|7|y|gy|sha1|md5)\$[^:\s]+",
        r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\z)",
        r"\bbs[aeku]_[A-Za-z0-9_-]{20,}",
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        r"(?i)(?:password|secret|api[_-]?key|token)\s*[=:]\s*\S+",
    ]


def sh(cmd: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=timeout, check=False
    )


def frame(obj: object) -> bytes:
    body = json.dumps(obj, separators=(",", ":")).encode()
    return struct.pack(">I", len(body)) + body


def plugin(execute: str, timeout_s: int = 30) -> dict:
    return {"plugin_uuid": str(uuid.uuid4()), "execute": execute, "timeout_s": timeout_s}


def request(ctx: Ctx, plugins: list[dict], **kw: object) -> dict:
    pickup = kw.get("pickup", datetime.now(UTC) + timedelta(hours=1))
    assert isinstance(pickup, datetime)
    job = {
        "job_id": kw.get("job_id", str(uuid.uuid4())),
        "agent_id": kw.get("agent_id", ctx.aid),
        "kind": kw.get("kind", "compliance"),
        "pickup_by": pickup.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": plugins,
        "redaction_patterns": kw.get("patterns", ctx.patterns),
    }
    return {"v": 1, "job": job, "max_parallel_plugins": kw.get("mpp", 1)}


def send_raw(ctx: Ctx, raw: bytes, user: str = "bitscan", timeout: float = 120, hold: float = 0) -> dict:
    ctx.n += 1
    req = ctx.work / ("req-%03d.bin" % ctx.n)
    out = ctx.work / ("out-%03d.json" % ctx.n)
    req.write_bytes(raw)
    req.chmod(0o644)
    if out.exists():
        out.unlink()
    me = str(ctx.work / "sandbox.py")
    args = ["/usr/bin/python3", "-I", me, "--client", str(req), str(out), str(timeout), str(hold)]
    kw: dict = {}
    if user != "root":
        pw = pwd.getpwnam(user)
        groups = [g for g in os.getgrouplist(user, pw.pw_gid)]
        kw = {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": groups}
    os.chmod(out.parent, 0o777)
    subprocess.run(args, check=True, timeout=timeout + 30, **kw, env={"PATH": "/usr/bin:/bin"})
    os.chmod(out.parent, 0o755)
    res = json.loads(out.read_text())
    out.unlink()
    req.unlink()
    return res


def run_job(ctx: Ctx, plugins: list[dict], user: str = "bitscan", timeout: float = 180, hold: float = 0, **kw: object) -> dict:
    req = request(ctx, plugins, **kw)
    res = send_raw(ctx, frame(req), user=user, timeout=timeout, hold=hold)
    res["job_id"] = req["job"]["job_id"]
    res["kinds"] = [f.get("type") for f in res["frames"]]
    by = {}
    for f in res["frames"]:
        if f.get("type") == "result":
            by[f["result"]["plugin_uuid"]] = f["result"]
    res["results"] = [by.get(p["plugin_uuid"]) for p in plugins]
    return res


def rfc3339(s: str) -> datetime:
    """RFC 3339 UTC with up to nanoseconds (Python 3.10 takes 6 digits)."""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]00:00)$", s)
    if not m:
        raise ValueError("not RFC 3339 UTC: %r" % s)
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    return datetime.strptime(m.group(1) + "." + frac, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)


def kv(item: dict | None) -> dict[str, str]:
    d: dict[str, str] = {}
    if not item:
        return d
    for line in (item.get("stdout") or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def ok_job(res: dict, n: int) -> bool:
    return res["kinds"][:1] == ["accepted"] and res["kinds"].count("result") == n and "done" in res["kinds"]


def runner_pid() -> int:
    p = sh("systemctl show -p MainPID --value " + RUNNER_UNIT).stdout.strip()
    return int(p or 0)


def proc_status(pid: int) -> dict[str, str]:
    d = {}
    try:
        for line in Path("/proc/%d/status" % pid).read_text().splitlines():
            k, _, v = line.partition(":")
            d[k] = v.strip()
    except OSError:
        pass
    return d


def service_cgroup() -> Path | None:
    pid = runner_pid()
    if not pid:
        return None
    try:
        line = Path("/proc/%d/cgroup" % pid).read_text().strip().splitlines()[-1]
    except OSError:
        return None
    rel = line.split(":", 2)[2]
    if rel.endswith("/supervisor"):
        rel = rel[: -len("/supervisor")]
    return Path("/sys/fs/cgroup" + rel)


def subtree_pids(cg: Path) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for d, _dirs, files in os.walk(cg):
        if "cgroup.procs" in files:
            try:
                pids = [int(x) for x in Path(d, "cgroup.procs").read_text().split()]
            except OSError:
                continue
            out[os.path.relpath(d, cg)] = pids
    return out


def survivors(tag: str) -> list[str]:
    r = sh("pgrep -a -f %s" % shlex_quote(tag))
    return [l for l in r.stdout.splitlines() if "pgrep" not in l]


def shlex_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def journal(ctx: Ctx, unit: str | None = None) -> str:
    cmd = "journalctl --no-pager -o cat --since %s" % shlex_quote(ctx.journal_since)
    if unit:
        cmd += " -u " + unit
    return sh(cmd, timeout=120).stdout


def mark_cmd(token: str) -> str:
    return (
        "python3 -I -c \"import socket;s=socket.socket(socket.AF_UNIX);"
        "s.connect('%s');s.sendall(b'%s')\" 2>/dev/null" % (MARK_SOCK, token)
    )


def py(code: str) -> str:
    """A plugin line running Python code (the code is base64 so no quoting)."""
    b = base64.b64encode(code.encode()).decode()
    return "python3 -I -c \"import base64;exec(base64.b64decode('%s'))\"" % b


# --------------------------------------------------------------------------
# listeners planted by the suite (root-owned, 0666)
# --------------------------------------------------------------------------


class Listener(threading.Thread):
    def __init__(self, path: str, sink: list[str] | None) -> None:
        super().__init__(daemon=True)
        self.path = path
        self.sink = sink
        self.hits = 0
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path):
            os.unlink(path)
        self.s.bind(path)
        os.chmod(path, 0o666)
        self.s.listen(64)

    def run(self) -> None:
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            self.hits += 1
            c.settimeout(2)
            data = b""
            try:
                while len(data) < 256:
                    b = c.recv(256)
                    if not b:
                        break
                    data += b
            except OSError:
                pass
            c.close()
            if self.sink is not None:
                self.sink.append(data.decode(errors="replace"))


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

Row = Callable[[Ctx], tuple[str, str]]
ROWS: list[tuple[str, str, Row]] = []


def row(rid: str, title: str) -> Callable[[Row], Row]:
    def deco(fn: Row) -> Row:
        ROWS.append((rid, title, fn))
        return fn

    return deco


def verdict(checks: list[tuple[str, bool]], extra: str = "") -> tuple[str, str]:
    bad = [n for n, v in checks if not v]
    ev = "; ".join("%s %s" % (n, "ok" if v else "FAILED") for n, v in checks)
    if extra:
        ev += " | " + extra
    return ("PASS" if not bad else "FAIL", ev)


@row("CHK-M10-221", "bitscan-runner.service inactive until the first job, active after it (REQ-255 (4))")
def r221(ctx: Ctx) -> tuple[str, str]:
    before = sh("systemctl is-active " + RUNNER_UNIT).stdout.strip()
    sock = sh("systemctl is-active bitscan-runner.socket").stdout.strip()
    if getattr(ctx, "runner_was_active", False):
        return ("NOT RUN", "the runner was already active when the suite started (not a fresh install)")
    res = run_job(ctx, [plugin("echo first=1")])
    after = sh("systemctl is-active " + RUNNER_UNIT).stdout.strip()
    return verdict(
        [("before first job: service %s" % before, before == "inactive"), ("socket %s" % sock, sock == "active"),
         ("first job done", ok_job(res, 1)), ("after: service %s" % after, after == "active")]
    )


@row("CHK-M10-200", "systemd-analyze verify of the installed units as written, with the real binaries")
def r200(ctx: Ctx) -> tuple[str, str]:
    units = ["bitscan-agent.service", "bitscan-runner.socket", "bitscan-runner.service",
             "bitscan-capread.socket", "bitscan-capread.service"]
    base = "/usr/lib/systemd/system" if os.path.exists("/usr/lib/systemd/system/bitscan-runner.service") else "/lib/systemd/system"
    r = sh("systemd-analyze verify " + " ".join(base + "/" + u for u in units), timeout=120)
    text = (r.stdout + r.stderr).strip()
    lines = [l for l in text.splitlines() if "bitscan" in l]
    return ("PASS" if r.returncode == 0 and not lines else "FAIL",
            "rc %d; bitscan lines: %s; all output: %s" % (r.returncode, lines[:5], mask(text)[:400]))


@row("CHK-M10-201", "a plugin cannot write outside its private /tmp and /var/tmp")
def r201(ctx: Ctx) -> tuple[str, str]:
    dirs = ["/etc", "/var/lib", "/home", "/root", "/run", "/usr/local", "/dev/shm", "/tmp", "/var/tmp"]
    lines = []
    for d in dirs:
        lines.append('if (echo x > %s/.bs-sbx-w) 2>/dev/null; then echo "W%s=yes"; else echo "W%s=no"; fi' % (d, d, d))
    # /sys and /proc/sys: write back the value already there (harmless if it worked)
    lines.append('f=/proc/sys/kernel/hostname; if (cat $f > $f.tmp) 2>/dev/null; then :; fi; '
                 'if (printf "%s\\n" "$(cat $f)" > $f) 2>/dev/null; then echo "W/proc/sys=yes"; else echo "W/proc/sys=no"; fi')
    lines.append('f=/sys/kernel/mm/transparent_hugepage/enabled; v=$(sed "s/.*\\[\\(.*\\)\\].*/\\1/" $f); '
                 'if (printf "%s" "$v" > $f) 2>/dev/null; then echo "W/sys=yes"; else echo "W/sys=no"; fi')
    res = run_job(ctx, [plugin("; ".join(lines))])
    d = kv(res["results"][0])
    checks = [("job done", ok_job(res, 1))]
    for x in ["/etc", "/var/lib", "/home", "/root", "/run", "/usr/local", "/dev/shm", "/sys", "/proc/sys"]:
        checks.append(("%s refused" % x, d.get("W" + x) == "no"))
    for x in ["/tmp", "/var/tmp"]:
        checks.append(("%s writable" % x, d.get("W" + x) == "yes"))
    leaked = [x for x in dirs if os.path.exists(x + "/.bs-sbx-w")]
    checks.append(("no probe file on the host (private /tmp, /var/tmp)", not leaked))
    for x in leaked:
        os.unlink(x + "/.bs-sbx-w")
    return verdict(checks, "host files: %s" % leaked)


@row("CHK-M10-202", "no AF_INET, AF_INET6 or AF_PACKET socket; no IP reachable")
def r202(ctx: Ctx) -> tuple[str, str]:
    code = (
        "import socket,errno\n"
        "for n,f,t in (('INET',socket.AF_INET,socket.SOCK_STREAM),('INET6',socket.AF_INET6,socket.SOCK_STREAM),"
        "('UDP',socket.AF_INET,socket.SOCK_DGRAM),('PACKET',17,socket.SOCK_RAW),('NETLINK',socket.AF_NETLINK,socket.SOCK_RAW)):\n"
        "  try:\n    s=socket.socket(f,t);s.close();print(n+'=open')\n"
        "  except OSError as e:\n    print(n+'='+errno.errorcode.get(e.errno,str(e.errno)))\n"
        "for host in ('127.0.0.1','1.1.1.1'):\n"
        "  try:\n    s=socket.create_connection((host,53),timeout=3);print('CONN'+host+'=open')\n"
        "  except OSError as e:\n    print('CONN'+host+'='+errno.errorcode.get(e.errno or 0,'timeout'))\n"
    )
    res = run_job(ctx, [plugin(py(code))])
    d = kv(res["results"][0])
    checks = [("job done", ok_job(res, 1))]
    for n in ("INET", "INET6", "UDP", "PACKET"):
        checks.append(("%s %s" % (n, d.get(n)), d.get(n) not in (None, "open")))
    for h in ("127.0.0.1", "1.1.1.1"):
        checks.append(("connect %s %s" % (h, d.get("CONN" + h)), d.get("CONN" + h) not in (None, "open")))
    return verdict(checks, "AF_NETLINK (allowed by the unit) %s" % d.get("NETLINK"))


@row("CHK-M10-203", "no exec of a copy of true in /tmp, /var/tmp or /home; /usr/bin/true runs")
def r203(ctx: Ctx) -> tuple[str, str]:
    os.makedirs("/home/bs-sbx", exist_ok=True)
    shutil.copy2("/usr/bin/true", "/home/bs-sbx/true")
    os.chmod("/home/bs-sbx/true", 0o755)
    os.chmod("/home/bs-sbx", 0o755)
    ex = ("cp /usr/bin/true /tmp/t; chmod 755 /tmp/t; /tmp/t 2>/dev/null; echo TMP=$?; "
          "cp /usr/bin/true /var/tmp/t; chmod 755 /var/tmp/t; /var/tmp/t 2>/dev/null; echo VARTMP=$?; "
          "/home/bs-sbx/true 2>/dev/null; echo HOME=$?; /usr/bin/true; echo USR=$?")
    try:
        res = run_job(ctx, [plugin(ex)])
    finally:
        shutil.rmtree("/home/bs-sbx", ignore_errors=True)
    d = kv(res["results"][0])
    return verdict([("job done", ok_job(res, 1)), ("/tmp copy %s" % d.get("TMP"), d.get("TMP") == "126"),
                    ("/var/tmp copy %s" % d.get("VARTMP"), d.get("VARTMP") == "126"),
                    ("/home copy %s" % d.get("HOME"), d.get("HOME") == "126"),
                    ("/usr/bin/true %s" % d.get("USR"), d.get("USR") == "0")])


@row("CHK-M10-204", "blocked sockets (Docker, containerd, snapd, journald) unreachable; an open test socket is reachable")
def r204(ctx: Ctx) -> tuple[str, str]:
    code = (
        "import socket,errno,os,stat\n"
        "for p in %r:\n"
        "  try:\n    st=os.stat(p);m='%%o'%%stat.S_IMODE(st.st_mode)\n"
        "  except OSError as e:\n    m=errno.errorcode.get(e.errno,'?')\n"
        "  try:\n    s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(3);s.connect(p);print('C'+p+'=open mode='+m)\n"
        "  except OSError as e:\n    print('C'+p+'='+errno.errorcode.get(e.errno or 0,'timeout')+' mode='+m)\n"
        "  try:\n    d=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);d.connect(p);print('D'+p+'=open')\n"
        "  except OSError as e:\n    print('D'+p+'='+errno.errorcode.get(e.errno or 0,'?'))\n"
    ) % (BLOCKED + [MARK_SOCK],)
    res = run_job(ctx, [plugin(py(code))])
    d = kv(res["results"][0])
    checks = [("job done", ok_job(res, 1))]
    for p in BLOCKED:
        c, g = d.get("C" + p, "missing"), d.get("D" + p, "missing")
        checks.append(("%s stream %s dgram %s" % (p, c, g), not c.startswith("open") and g != "open"))
    checks.append(("control %s %s" % (MARK_SOCK, d.get("C" + MARK_SOCK)), (d.get("C" + MARK_SOCK) or "").startswith("open")))
    planted = getattr(ctx, "planted", [])
    return verdict(checks, "planted 0666 listeners: %s" % planted)


@row("CHK-M10-205", "no ptrace or process_vm_readv of the runner; its mem and environ give EACCES")
def r205(ctx: Ctx) -> tuple[str, str]:
    code = (
        "import ctypes,errno,os,sys\n"
        "pid=int(sys.argv[1]) if len(sys.argv)>1 else int(os.environ.get('R','0'))\n"
        "libc=ctypes.CDLL(None,use_errno=True)\n"
        "libc.ptrace.argtypes=[ctypes.c_long,ctypes.c_long,ctypes.c_void_p,ctypes.c_void_p]\n"
        "r=libc.ptrace(16,pid,None,None);print('PTRACE=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n"
        "r=libc.ptrace(0x4206,pid,None,None);print('SEIZE=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n"
        "class iov(ctypes.Structure):\n  _fields_=[('b',ctypes.c_void_p),('n',ctypes.c_size_t)]\n"
        "buf=ctypes.create_string_buffer(8);l=iov(ctypes.addressof(buf),8);rm=iov(0x400000,8)\n"
        "libc.syscall.restype=ctypes.c_long\n"
        "r=libc.syscall(310,ctypes.c_long(pid),ctypes.byref(l),ctypes.c_ulong(1),ctypes.byref(rm),ctypes.c_ulong(1),ctypes.c_ulong(0))\n"
        "print('VMREAD=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n"
        "for f in ('mem','environ'):\n"
        "  try:\n    open('/proc/%d/%s'%(pid,f),'rb').read(1);print(f.upper()+'=read')\n"
        "  except OSError as e:\n    print(f.upper()+'='+errno.errorcode.get(e.errno,'?'))\n"
    )
    ex = 'echo COMM=$(cat /proc/$PPID/comm); R=$PPID; export R; ' + py(code)
    res = run_job(ctx, [plugin(ex)])
    d = kv(res["results"][0])
    st = proc_status(runner_pid())
    return verdict([("job done", ok_job(res, 1)), ("parent is the runner (%s)" % d.get("COMM"), d.get("COMM") == "bitscan-runner"),
                    ("ptrace attach %s" % d.get("PTRACE"), (d.get("PTRACE") or "").startswith("-1:")),
                    ("ptrace seize %s" % d.get("SEIZE"), (d.get("SEIZE") or "").startswith("-1:")),
                    ("process_vm_readv %s" % d.get("VMREAD"), (d.get("VMREAD") or "").startswith("-1:EPERM")),
                    ("mem %s" % d.get("MEM"), d.get("MEM") == "EACCES"),
                    ("environ %s" % d.get("ENVIRON"), d.get("ENVIRON") == "EACCES")],
                   "runner CapEff %s CapBnd %s" % (st.get("CapEff"), st.get("CapBnd")))


# The plugin's own descriptors, as the runner handed them over: the shell is
# replaced by Python (no redirection, no $(...) pipe, no saved copy), and the
# directory descriptor of the listing itself is left out (closed by then).
FD_PROBE = "exec " + "python3 -I -c \"import os\nfor n in sorted(os.listdir('/proc/self/fd'),key=int):\n  try:\n    print('FDL%s=%s'%(n,os.readlink('/proc/self/fd/'+n)))\n  except OSError:\n    pass\n\""


def fd_list(item: dict | None) -> dict[str, str]:
    return {k[3:]: v for k, v in kv(item).items() if k.startswith("FDL")}


@row("CHK-M10-206", "the runner's socket is not among a plugin's fds; runner.sock can't be replaced, renamed or unlinked; nothing can be created in /run/bitscan")
def r206(ctx: Ctx) -> tuple[str, str]:
    ino = os.stat(SOCK).st_ino
    before = sorted(os.listdir("/run/bitscan"))
    ex = (''
          'mv /run/bitscan/runner.sock /run/bitscan/x 2>/dev/null; echo MV=$?; rm -f /run/bitscan/runner.sock 2>/dev/null; echo RM=$?; '
          'ln -sf /dev/null /run/bitscan/runner.sock 2>/dev/null; echo LN=$?; touch /run/bitscan/new 2>/dev/null; echo TOUCH=$?; '
          'mkdir /run/bitscan/d 2>/dev/null; echo MKDIR=$?')
    res = run_job(ctx, [plugin(FD_PROBE), plugin(ex)])
    d = kv(res["results"][1])
    links = fd_list(res["results"][0])
    fds = list(links)
    after = sorted(os.listdir("/run/bitscan"))
    return verdict([("job done", ok_job(res, 2)), ("fds %s" % fds, fds == ["0", "1", "2"]),
                    ("no socket fd", not any("socket:" in v for v in links.values())),
                    ("mv %s" % d.get("MV"), d.get("MV") not in (None, "0")), ("rm %s" % d.get("RM"), d.get("RM") not in (None, "0")),
                    ("ln %s" % d.get("LN"), d.get("LN") not in (None, "0")), ("touch %s" % d.get("TOUCH"), d.get("TOUCH") not in (None, "0")),
                    ("mkdir %s" % d.get("MKDIR"), d.get("MKDIR") not in (None, "0")),
                    ("runner.sock same inode", os.path.exists(SOCK) and os.stat(SOCK).st_ino == ino),
                    ("/run/bitscan unchanged %s" % after, after == before)], "fd links %s" % links)


def _dbus_units() -> None:
    for name, extra in (("bs-sbx-dummy", ""), ("bs-sbx-dummy2", "")):
        Path("/run/systemd/system/%s.service" % name).write_text(
            "[Unit]\nDescription=Bitscan sandbox suite dummy\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/bin/true\n"
            "[Install]\nWantedBy=multi-user.target\n" + extra
        )
    sh("systemctl daemon-reload && systemctl start bs-sbx-dummy.service")


@row("CHK-M10-207", "D-Bus: state-changing calls refused by the bus policy; read-only calls work")
def r207(ctx: Ctx) -> tuple[str, str]:
    _dbus_units()
    host_before = sh("hostname").stdout.strip()
    calls = {
        "stop": "systemctl --no-ask-password stop bs-sbx-dummy.service",
        "start": "systemctl --no-ask-password start bs-sbx-dummy2.service",
        "restart": "systemctl --no-ask-password restart bs-sbx-dummy.service",
        "enable": "systemctl --no-ask-password enable bs-sbx-dummy2.service",
        "mask": "systemctl --no-ask-password mask bs-sbx-dummy2.service",
        "busctl": "busctl call --allow-interactive-authorization=no org.freedesktop.systemd1 /org/freedesktop/systemd1 "
                  "org.freedesktop.systemd1.Manager StartUnit ss bs-sbx-dummy2.service replace",
        "loginctl": "loginctl --no-ask-password terminate-session bs-sbx-none",
        "hostnamectl": 'hostnamectl --no-ask-password set-hostname "$(hostname)"',
        "timedatectl": "timedatectl --no-ask-password set-time \"$(date '+%Y-%m-%d %H:%M:%S')\"",
    }
    lines = []
    for k, c in calls.items():
        lines.append('%s >/dev/null 2>./e; echo "SC_%s=$?:$(head -c 300 ./e | tr "\\n" " ")"' % (c, k))
    ro = {
        "isactive": "systemctl is-active bitscan-runner.socket",
        "isenabled": "systemctl is-enabled bitscan-runner.socket",
        "listunits": "systemctl list-units --no-pager --no-legend | wc -l",
        "listfiles": "systemctl list-unit-files --no-pager --no-legend | wc -l",
    }
    for k, c in ro.items():
        lines.append('o=$(%s 2>./e); echo "RO_%s=$?:$o:$(head -c 200 ./e | tr "\\n" " ")"' % (c, k))
    res = run_job(ctx, [plugin("; ".join(lines), timeout_s=120)], timeout=240)
    d = kv(res["results"][0])
    checks = [("job done", ok_job(res, 1))]
    for k in calls:
        v = d.get("SC_" + k, "missing")
        rc, _, err = v.partition(":")
        checks.append(("%s rc %s" % (k, rc), rc not in ("0", "missing") and "access denied" in err.lower()))
    for k in ro:
        v = d.get("RO_" + k, "missing")
        rc, _, rest = v.partition(":")
        out = rest.split(":", 1)[0]
        good = rc == "0" and (out in ("active", "enabled") if k in ("isactive", "isenabled") else out.isdigit() and int(out) > 0)
        checks.append(("%s rc %s out %s" % (k, rc, out), good))
    st1 = sh("systemctl is-active bs-sbx-dummy.service").stdout.strip()
    st2 = sh("systemctl is-active bs-sbx-dummy2.service").stdout.strip()
    en2 = sh("systemctl is-enabled bs-sbx-dummy2.service").stdout.strip()
    checks += [("dummy still %s" % st1, st1 == "active"), ("dummy2 still %s" % st2, st2 == "inactive"),
               ("dummy2 %s (not enabled or masked)" % en2, en2 == "disabled"),
               ("hostname unchanged", sh("hostname").stdout.strip() == host_before)]
    errs = {k: mask(d.get("SC_" + k, ""))[:120] for k in calls}
    sh("systemctl stop bs-sbx-dummy.service bs-sbx-dummy2.service; rm -f /run/systemd/system/bs-sbx-dummy*.service; systemctl daemon-reload")
    return verdict(checks, "errors %s" % errs)


@row("CHK-M10-208", "no privilege gain, module load, clock or hostname change, or block device open")
def r208(ctx: Ctx) -> tuple[str, str]:
    code = (
        "import ctypes,errno,os,glob\n"
        "libc=ctypes.CDLL(None,use_errno=True)\n"
        "try:\n  os.setuid(0);print('SETUID=ok')\nexcept OSError as e:\n  print('SETUID='+errno.errorcode.get(e.errno,'?'))\n"
        "libc.syscall.restype=ctypes.c_long\n"
        "r=libc.syscall(175,None,ctypes.c_ulong(0),b'');print('INITMOD=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n"
        "r=libc.syscall(313,ctypes.c_int(-1),b'',ctypes.c_int(0));print('FINITMOD=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n"
        "blk=[p for p in glob.glob('/dev/**',recursive=True) if os.path.exists(p) and __import__('stat').S_ISBLK(os.stat(p).st_mode)]\n"
        "print('BLOCKDEVS=%d'%len(blk))\n"
        "for p in ('/dev/sda','/dev/vda','/dev/nvme0n1','/dev/loop0','/dev/dm-0','/dev/mem','/dev/kmsg'):\n"
        "  try:\n    os.close(os.open(p,os.O_RDONLY));print('OPEN'+p+'=ok')\n"
        "  except OSError as e:\n    print('OPEN'+p+'='+errno.errorcode.get(e.errno,'?'))\n"
    )
    ex = ('sudo -n true >/dev/null 2>&1; echo SUDO=$?; su root -c true </dev/null >/dev/null 2>&1; echo SU=$?; '
          'newgrp bitscan </dev/null >/dev/null 2>&1; echo NEWGRP=$?; echo NNP=$(grep NoNewPrivs /proc/$$/status | cut -f2); '
          'date -s "@$(date +%s)" >/dev/null 2>&1; echo DATE=$?; hostname "$(hostname)" >/dev/null 2>&1; echo HOSTNAME=$?; '
          'modprobe -q dummy >/dev/null 2>&1; echo MODPROBE=$?; ' + py(code))
    res = run_job(ctx, [plugin(ex)])
    d = kv(res["results"][0])
    checks = [("job done", ok_job(res, 1))]
    for k in ("SUDO", "SU", "NEWGRP", "DATE", "HOSTNAME", "MODPROBE"):
        checks.append(("%s rc %s" % (k.lower(), d.get(k)), d.get(k) not in (None, "0")))
    checks += [("NoNewPrivs %s" % d.get("NNP"), d.get("NNP") == "1"), ("setuid(0) %s" % d.get("SETUID"), d.get("SETUID") == "EPERM"),
               ("init_module %s" % d.get("INITMOD"), (d.get("INITMOD") or "").startswith("-1:EPERM")),
               ("finit_module %s" % d.get("FINITMOD"), (d.get("FINITMOD") or "").startswith("-1:EPERM")),
               ("block devices visible %s" % d.get("BLOCKDEVS"), d.get("BLOCKDEVS") == "0")]
    for p in ("/dev/sda", "/dev/vda", "/dev/nvme0n1", "/dev/loop0", "/dev/dm-0", "/dev/mem", "/dev/kmsg"):
        checks.append(("open %s %s" % (p, d.get("OPEN" + p)), d.get("OPEN" + p) not in (None, "ok")))
    return verdict(checks)


@row("CHK-M10-209", "a plugin can read /etc/shadow (CAP_DAC_READ_SEARCH); its CapEff and CapBnd are 0x4")
def r209(ctx: Ctx) -> tuple[str, str]:
    ex = ("echo SHADOWLINES=$(wc -l < /etc/shadow); echo EFF=$(grep CapEff /proc/$$/status | cut -f2); "
          "echo BND=$(grep CapBnd /proc/$$/status | cut -f2); echo AMB=$(grep CapAmb /proc/$$/status | cut -f2)")
    res = run_job(ctx, [plugin(ex)])
    d = kv(res["results"][0])
    st = proc_status(runner_pid())
    return verdict([("job done", ok_job(res, 1)), ("shadow lines %s" % d.get("SHADOWLINES"), (d.get("SHADOWLINES") or "0").isdigit() and int(d.get("SHADOWLINES") or 0) > 0),
                    ("plugin CapEff %s" % d.get("EFF"), d.get("EFF") == "0000000000000004"),
                    ("plugin CapBnd %s" % d.get("BND"), d.get("BND") == "0000000000000004"),
                    ("runner CapEff %s" % st.get("CapEff"), st.get("CapEff") == "0000000000000004"),
                    ("runner CapBnd %s" % st.get("CapBnd"), st.get("CapBnd") == "0000000000000004")])


@row("CHK-M10-210", "cgroup layout: each plugin in its own p-<n>, the runner in supervisor, only supervisor left (REQ-238 (2)-(4))")
def r210(ctx: Ctx) -> tuple[str, str]:
    # The runner hops through each new p-<n> while it starts a plugin (#136
    # (a)), so its cgroup is read after the other starts are over.
    ex = ("echo CG=$(cut -d: -f3 /proc/self/cgroup); sleep 30.210 & echo CH=$(cut -d: -f3 /proc/$!/cgroup); "
          "sleep 1.5; echo RCG=$(cut -d: -f3 /proc/$PPID/cgroup)")
    res = run_job(ctx, [plugin(ex) for _ in range(3)], mpp=3)
    ds = [kv(r) for r in res["results"]]
    cgs = [d.get("CG", "") for d in ds]
    cg = service_cgroup()
    time.sleep(0.5)
    left = sorted(p.name for p in cg.iterdir() if p.is_dir()) if cg else []
    pids = subtree_pids(cg) if cg else {}
    rp = runner_pid()
    others = {k: [p for p in v if p != rp] for k, v in pids.items() if [p for p in v if p != rp]}
    return verdict([("job done", ok_job(res, 3)),
                    ("plugin cgroups %s" % cgs, len(set(cgs)) == 3 and all(re.search(r"/bitscan-runner\.service/p-\d+$", c) for c in cgs)),
                    ("runner in supervisor", all(d.get("RCG", "").endswith("/bitscan-runner.service/supervisor") for d in ds)),
                    ("forked child in the plugin's own cgroup", all(d.get("CH") == d.get("CG") for d in ds)),
                    ("after the job the service holds only %s" % left, left == ["supervisor"]),
                    ("no process but the runner in the subtree", not others)], "subtree pids %s" % others)


@row("CHK-M10-211", "plugin environment, fds, niceness 10, I/O class idle, temp dir, uid, parallel cap (REQ-239)")
def r211(ctx: Ctx) -> tuple[str, str]:
    ex = ("echo LS=$(ls -A | wc -l); echo PWD=$PWD; echo ENVN=$(tr '\\0' '\\n' < /proc/$$/environ | wc -l); "
          "echo ENV=$(tr '\\0' '\\n' < /proc/$$/environ | head -n 3 | tr '\\n' '|'); echo FD0=$(readlink /proc/$$/fd/0); "
          "echo NICE=$(cut -d' ' -f19 /proc/$$/stat); "
          "echo IONICE=$(ionice -p $$); echo UID=$(id -u); echo MODE=$(stat -c %a .)")
    res = run_job(ctx, [plugin(ex), plugin(FD_PROBE)])
    d = kv(res["results"][0])
    fdl = fd_list(res["results"][1])
    pwdir = d.get("PWD", "")
    rp = runner_pid()
    time.sleep(0.5)
    gone = sh("nsenter -t %d -m test -e %s; echo $?" % (rp, shlex_quote(pwdir or "/nonexistent"))).stdout.strip()
    par = [plugin("S=$(date +%s.%N); sleep 2; echo S=$S; echo E=$(date +%s.%N)", 30) for _ in range(8)]
    t0 = time.time()
    res2 = run_job(ctx, par, mpp=3)
    dur = time.time() - t0
    ev = []
    for r in res2["results"]:
        k = kv(r)
        if "S" in k and "E" in k:
            ev += [(float(k["S"]), 1), (float(k["E"]), -1)]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = top = 0
    for _, x in ev:
        cur += x
        top = max(top, cur)
    return verdict([("job done", ok_job(res, 2)), ("environ %s (%s lines)" % (d.get("ENV"), d.get("ENVN")), d.get("ENVN") == "1" and d.get("ENV") == PATH_ENV + "|"),
                    ("stdin %s" % d.get("FD0"), d.get("FD0") == "/dev/null"), ("fds %s" % fdl, list(fdl) == ["0", "1", "2"] and fdl["0"] == "/dev/null" and all(fdl[k].startswith("pipe:") for k in ("1", "2"))),
                    ("niceness %s" % d.get("NICE"), d.get("NICE") == "10"), ("ionice %s" % d.get("IONICE"), d.get("IONICE") == "idle"),
                    ("cwd %s, empty at start (%s), mode %s" % (pwdir, d.get("LS"), d.get("MODE")), pwdir.startswith("/tmp/") and d.get("LS") == "0" and d.get("MODE") == "700"),
                    ("cwd gone after the job (test -e rc %s)" % gone, gone == "1"),
                    ("uid %s is bitscan-runner" % d.get("UID"), d.get("UID") == str(ctx.runner_uid) and d.get("UID") != "0"),
                    ("8 x sleep 2 at max_parallel 3 done", ok_job(res2, 8)), ("at most 3 at once (%d)" % top, top == 3),
                    ("three rounds (%.1f s)" % dur, 5.5 <= dur < 12)])


@row("CHK-M10-212", "no plugin outlives its job (REQ-240 (1)-(10))")
def r212(ctx: Ctx) -> tuple[str, str]:
    S = 'S=$(cut -d: -f3 /proc/$PPID/cgroup); S=/sys/fs/cgroup${S%/supervisor}; M=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); '
    pl = [
        plugin("sleep 300.2121 & echo ok=1"),
        plugin("setsid nohup sleep 300.2122 >/dev/null 2>&1 & echo ok=1"),
        plugin("(sleep 300.2123 &) & echo ok=1"),
        plugin(S + "sh -c 'echo $$ > '$S'/supervisor/cgroup.procs && exec sleep 300.2124' >/dev/null 2>&1 & sleep 0.5; echo ok=1"),
        plugin(S + "mkdir $S/supervisor/bs-x 2>/dev/null; sh -c 'echo $$ > '$S'/supervisor/bs-x/cgroup.procs && exec sleep 300.2125' >/dev/null 2>&1 & "
               "mkdir $M/bs-y 2>/dev/null; sh -c 'echo $$ > '$M'/bs-y/cgroup.procs && exec sleep 300.2126' >/dev/null 2>&1 & sleep 0.5; echo ok=1"),
        plugin("sh -c 'trap \"\" TERM; exec sleep 300.2127' >/dev/null 2>&1 & echo ok=1"),
        # (1b) per-plugin kill: the background child of the plugin before this one is gone
        plugin("sleep 300.2130 & echo ok=1"),
        plugin("sleep 1; if pgrep -f 'sleep 300[.]2130' >/dev/null; then echo ALIVE=1; else echo ALIVE=0; fi"),
    ]
    res = run_job(ctx, pl, mpp=1)
    time.sleep(1)
    surv = survivors("sleep 300.21")
    cg = service_cgroup()
    rp = runner_pid()
    pids = subtree_pids(cg) if cg else {}
    others = {k: [p for p in v if p != rp] for k, v in pids.items() if [p for p in v if p != rp]}
    alive = kv(res["results"][7]).get("ALIVE")
    # (7) timeout
    r7 = run_job(ctx, [plugin("sleep 100.2128", 2)])
    it = r7["results"][0] or {}
    el = 99.0
    if it.get("started_at") and it.get("finished_at"):
        el = (rfc3339(it["finished_at"]) - rfc3339(it["started_at"])).total_seconds()
    # (8) the runner's pid written into the plugin's own cgroup.procs
    r8 = run_job(ctx, [plugin("M=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); echo $PPID > $M/cgroup.procs 2>/dev/null; echo W=$?; sleep 300.2131 & sleep 0.5")])
    rp8 = runner_pid()
    r8b = run_job(ctx, [plugin("echo RCG=$(cut -d: -f3 /proc/$PPID/cgroup)")], timeout=60)
    rcg = kv(r8b["results"][0]).get("RCG", "")
    surv8 = survivors("sleep 300.2131")
    # (9) files under /tmp and /var/tmp are gone before the next job
    run_job(ctx, [plugin("echo a > /tmp/bs-sbx-9; echo b > /var/tmp/bs-sbx-9; echo ok=1")])
    r9 = run_job(ctx, [plugin("test -e /tmp/bs-sbx-9; echo T=$?; test -e /var/tmp/bs-sbx-9; echo V=$?")])
    d9 = kv(r9["results"][0])
    # (10) the driver closes its connection mid-job
    r10 = run_job(ctx, [plugin("sleep 300.2129", 600)], hold=0.5)
    time.sleep(1.0)
    surv10 = survivors("sleep 300.2129")
    return verdict([("job of 8 done", ok_job(res, 8)), ("(1)-(6) no survivor %s" % surv, not surv),
                    ("(1)-(6) subtree holds only the runner", not others),
                    ("(1b) background child killed when its plugin exits (ALIVE=%s)" % alive, alive == "0"),
                    ("(7) timed_out %s exit %s in %.2f s" % (it.get("timed_out"), it.get("exit_code"), el), it.get("timed_out") is True and it.get("exit_code") == 137 and el <= 3.0),
                    ("(8) next job ran (%s), runner back in supervisor or restarted (%s, pid %d -> %d)" % (r8b["kinds"], rcg, rp8, runner_pid()),
                     ok_job(r8b, 1) and (rcg.endswith("/supervisor"))),
                    ("(8) the move was tried (write rc %s), no survivor %s" % (kv(r8["results"][0]).get("W"), surv8), not surv8),
                    ("(9) /tmp %s /var/tmp %s gone" % (d9.get("T"), d9.get("V")), d9.get("T") == "1" and d9.get("V") == "1"),
                    ("(10) client closed after accepted (%s)" % r10["status"], r10["status"] == "client-close"),
                    ("(10) no plugin 1 s later %s" % surv10, not surv10)], "subtree %s" % others)


@row("CHK-M10-213", "exit codes on the host: exit 3 -> 3, kill -9 $$ -> 137, unknown command -> 127")
def r213(ctx: Ctx) -> tuple[str, str]:
    res = run_job(ctx, [plugin("exit 3"), plugin("kill -9 $$"), plugin("bs-sbx-no-such-command")], mpp=3)
    codes = [(r or {}).get("exit_code") for r in res["results"]]
    return verdict([("job done", ok_job(res, 3)), ("exit codes %s" % codes, codes == [3, 137, 127])])


@row("CHK-M10-214", "cgroup v1 host: the runner refuses to start (REQ-237 (3))")
def r214(ctx: Ctx) -> tuple[str, str]:
    return ("NOT RUN", "this host boots unified cgroup v2; the row needs bitscan-u2204 booted with "
            "systemd.unified_cgroup_hierarchy=0 (run_vm.sh runs it there in v1 mode). Cover: CHK-M10-110, -074")


def _restart_runner() -> None:
    sh("systemctl stop %s; systemctl reset-failed %s bitscan-runner.socket; systemctl restart bitscan-runner.socket" % (RUNNER_UNIT, RUNNER_UNIT))
    for _ in range(50):
        if os.path.exists(SOCK):
            break
        time.sleep(0.1)


@row("CHK-M10-215", "planted unit with CAP_SYS_ADMIN: the runner refuses to start (REQ-237 (4))")
def r215(ctx: Ctx) -> tuple[str, str]:
    os.makedirs(DROPIN_DIR, exist_ok=True)
    Path(DROPIN_DIR, "zz-bs-sbx-cap.conf").write_text(
        "[Service]\nAmbientCapabilities=CAP_SYS_ADMIN\nCapabilityBoundingSet=CAP_SYS_ADMIN\n")
    sh("systemctl daemon-reload")
    _restart_runner()
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        res = run_job(ctx, [plugin(mark_cmd("M215"))], timeout=8)
        time.sleep(1)
        bnd = sh("systemctl show -p CapabilityBoundingSet --value " + RUNNER_UNIT).stdout.strip()
        j = sh("journalctl --no-pager -o cat -u %s --since %s" % (RUNNER_UNIT, shlex_quote(since))).stdout
    finally:
        os.unlink(Path(DROPIN_DIR, "zz-bs-sbx-cap.conf"))
        sh("systemctl daemon-reload")
        _restart_runner()
    after = run_job(ctx, [plugin("echo back=1")])
    refused = [l for l in j.splitlines() if "start-up refused" in l]
    return verdict([("unit bounding set %s holds cap_sys_admin" % bnd, "cap_sys_admin" in bnd),
                    ("no accepted frame (%s, %s)" % (res["kinds"], res["status"]), "accepted" not in res["kinds"]),
                    ("nothing executed", "M215" not in "".join(ctx.marks)),
                    ("journal start-up refused %d" % len(refused), len(refused) >= 1),
                    ("drop-in removed: the next job runs", ok_job(after, 1))], "journal: %s" % mask(" | ".join(refused[:2]))[:300])


@row("CHK-M10-216", "peer check: root and a member of group bitscan closed without a reply; a non-member gets EACCES")
def r216(ctx: Ctx) -> tuple[str, str]:
    a = run_job(ctx, [plugin(mark_cmd("M216root"))], user="root", timeout=10)
    b = run_job(ctx, [plugin(mark_cmd("M216member"))], user="bs-sbx-member", timeout=10)
    c = run_job(ctx, [plugin(mark_cmd("M216out"))], user="bs-sbx-outsider", timeout=10)
    time.sleep(0.5)
    m = "".join(ctx.marks)
    return verdict([("root: no frame (%s)" % a["status"], not a["frames"] and a.get("connect_errno") == 0),
                    ("member of bitscan: no frame (%s)" % b["status"], not b["frames"] and b.get("connect_errno") == 0),
                    ("outsider: connect errno %s" % c.get("connect_errno"), c.get("connect_errno") == 13),
                    ("nothing executed", not any(x in m for x in ("M216root", "M216member", "M216out")))])



NFT_NORM = (
    "import json,sys,hashlib\n"
    "def z(o):\n"
    "  if isinstance(o,dict):\n"
    "    return {k:(0 if k in ('packets','bytes') else z(v)) for k,v in o.items()}\n"
    "  if isinstance(o,list):\n"
    "    return [z(v) for v in o]\n"
    "  return o\n"
    "d=sys.stdin.buffer.read()\n"
    "try:\n  d=json.dumps(z(json.loads(d)),sort_keys=True).encode()\nexcept ValueError:\n  pass\n"
    "print(hashlib.sha256(d).hexdigest())\n"
)


def nft_sha(raw: bytes) -> str:
    r = subprocess.run(["/usr/bin/python3", "-I", "-c", NFT_NORM], input=raw, capture_output=True, check=False)
    return r.stdout.decode().strip()


def _capread(enable: bool) -> None:
    if enable:
        sh("systemctl enable --now bitscan-capread.socket")
    else:
        sh("systemctl disable --now bitscan-capread.socket bitscan-capread.service")


@row("CHK-M10-217", "capread with the real nft and auditctl; helper CapEff 0x40001000 under a dynamic uid; runner and plugins 0x4")
def r217(ctx: Ctx) -> tuple[str, str]:
    if not os.path.exists("/usr/sbin/nft"):
        return ("NOT RUN", "nft is not installed on this host (run_vm.sh installs nftables); cover CHK-M10-137 to -141")
    _capread(True)
    try:
        ex = ("bitscan-capread nft_ruleset > ./n 2>./ne; echo NRC=$?; echo NSHA=$(" + py(NFT_NORM) + " < ./n); echo NERR=$(cat ./ne); "
              "bitscan-capread audit_rules > ./a 2>./ae; echo ARC=$?; echo ASHA=$(sha256sum < ./a | cut -c1-64); echo AERR=$(cat ./ae); "
              "echo EFF=$(grep CapEff /proc/$$/status | cut -f2)")
        res = run_job(ctx, [plugin(ex)])
        d = kv(res["results"][0])
        hp = int(sh("systemctl show -p MainPID --value bitscan-capread.service").stdout.strip() or 0)
        hst = proc_status(hp)
        nft = subprocess.run(["/usr/sbin/nft", "-j", "list", "ruleset"], capture_output=True, check=False).stdout
        import hashlib

        nsha = nft_sha(nft)
        has_audit = os.path.exists("/usr/sbin/auditctl")
        checks = [("job done", ok_job(res, 1)), ("nft_ruleset rc %s" % d.get("NRC"), d.get("NRC") == "0"),
                  ("nft output equals root's, rule counters zeroed (%d bytes)" % len(nft), d.get("NSHA") == nsha)]
        if has_audit:
            au = subprocess.run(["/usr/sbin/auditctl", "-l"], capture_output=True, check=False).stdout
            checks += [("audit_rules rc %s" % d.get("ARC"), d.get("ARC") == "0"),
                       ("audit_rules equals root's auditctl -l", d.get("ASHA") == hashlib.sha256(au).hexdigest())]
        else:
            checks += [("audit_rules without auditd: rc %s, %s" % (d.get("ARC"), d.get("AERR")), d.get("ARC") == "1" and d.get("AERR") == "bitscan-capread: not_installed")]
        uid = int((hst.get("Uid") or "0").split()[0])
        checks += [("helper CapEff %s" % hst.get("CapEff"), hst.get("CapEff") == "0000000040001000"),
                   ("helper uid %d is dynamic (61184-65519)" % uid, 61184 <= uid <= 65519),
                   ("plugin CapEff %s" % d.get("EFF"), d.get("EFF") == "0000000000000004"),
                   ("runner CapEff %s" % proc_status(runner_pid()).get("CapEff"), proc_status(runner_pid()).get("CapEff") == "0000000000000004")]
        # The helper's command gets an empty environment: an env probe bound
        # over /usr/sbin/auditctl on this throwaway host for one request.
        envd = _capread_env_probe(ctx)
        checks.append(("helper command environment %s" % envd, envd == "EMPTY"))
        return verdict(checks, "auditd installed: %s" % has_audit)
    finally:
        _capread(False)


def _capread_env_probe(ctx: Ctx) -> str:
    probe = ctx.work / "envprobe"
    probe.write_text("#!/usr/bin/python3 -I\nimport sys\ne=open('/proc/self/environ','rb').read()\n"
                     "sys.stdout.write('ENVPROBE=' + ('EMPTY' if not e else e.replace(b'\\0', b'|').decode(errors='replace')) + '\\n')\n")
    probe.chmod(0o755)
    made = not os.path.exists("/usr/sbin/auditctl")
    if made:
        Path("/usr/sbin/auditctl").touch()
    sh("systemctl stop bitscan-capread.service")
    r = sh("mount --bind %s /usr/sbin/auditctl" % probe)
    if r.returncode != 0:
        if made:
            os.unlink("/usr/sbin/auditctl")
        return "probe not mounted: " + r.stderr.strip()[:100]
    try:
        res = run_job(ctx, [plugin("bitscan-capread audit_rules 2>&1 | head -c 600")])
        out = (res["results"][0] or {}).get("stdout", "")
    finally:
        sh("systemctl stop bitscan-capread.service; umount /usr/sbin/auditctl")
        if made:
            os.unlink("/usr/sbin/auditctl")
    m = re.search(r"ENVPROBE=(.*)", out)
    return m.group(1).strip() if m else "no probe line: " + mask(out)[:100]


@row("CHK-M10-218", "helper disabled: exit 1 and the fixed line; file-based checks still work")
def r218(ctx: Ctx) -> tuple[str, str]:
    _capread(False)
    ex = "bitscan-capread nft_ruleset 2>./e >/dev/null; echo RC=$?; echo ERR=$(cat ./e); echo PASSWD=$(grep -c . /etc/passwd)"
    res = run_job(ctx, [plugin(ex)])
    d = kv(res["results"][0])
    return verdict([("job done", ok_job(res, 1)), ("rc %s" % d.get("RC"), d.get("RC") == "1"),
                    ("line %s" % d.get("ERR"), d.get("ERR") == "bitscan-capread: not enabled"),
                    ("file read works (%s lines)" % d.get("PASSWD"), int(d.get("PASSWD") or 0) > 0)])


@row("CHK-M10-219a", "capread units disabled and inactive after install (REQ-254 (1), first part)")
def r219a(ctx: Ctx) -> tuple[str, str]:
    st = getattr(ctx, "capread_at_start", {})
    return verdict([("socket %s" % st.get("socket"), st.get("socket") == "disabled inactive"),
                    ("service %s" % st.get("service"), st.get("service") in ("static inactive", "disabled inactive"))])


@row("CHK-M10-219b", "runner_helpers [] -> [\"capread\"] -> [] in the heartbeat")
def r219b(ctx: Ctx) -> tuple[str, str]:
    return ("NOT RUN", "needs an enrolled agent and a manager; done in the TASK-231 runbook walk §10 on bitscan-u2404 and "
            "bitscan-u2204 (PASS 2026-11-02, work/reports/M10-vm-test.md). Cover: M4 heartbeat suite (#30)")


@row("CHK-M10-223", "clone3 under the verbatim unit: ENOSYS or not (fact for the owner)")
def r223(ctx: Ctx) -> tuple[str, str]:
    code = ("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nlibc.syscall.restype=ctypes.c_long\n"
            "r=libc.syscall(435,None,ctypes.c_size_t(0));print('CLONE3=%d:%s'%(r,errno.errorcode.get(ctypes.get_errno(),'0')))\n")
    res = run_job(ctx, [plugin(py(code))])
    d = kv(res["results"][0])
    return ("PASS" if ok_job(res, 1) and d.get("CLONE3") else "FAIL",
            "recorded: clone3(NULL, 0) -> %s (EINVAL means the call reached the kernel; ENOSYS or EPERM means the filter answered)" % d.get("CLONE3"))


@row("CHK-M10-344v", "redaction before truncation at the 64 KiB boundary, at the runner reply (the agent forwards it as is)")
def r344(ctx: Ctx) -> tuple[str, str]:
    tok = "bsa_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    ex = "head -c 65529 /dev/zero | tr '\\0' a; printf '\\n%s' " + tok
    res = run_job(ctx, [plugin(ex)])
    it = res["results"][0] or {}
    so = it.get("stdout", "")
    return verdict([("job done", ok_job(res, 1)), ("truncated %s" % it.get("truncated"), it.get("truncated") is True),
                    ("stdout %d bytes" % len(so), len(so) <= 65536),
                    ("no part of the token (bsa_ prefix) returned", "bsa_" not in so and tok[4:12] not in so),
                    ("tail %r" % so[-12:], so.endswith("[REDAC") or "[REDACTED]" in so[-16:] or so.rstrip("a") == "")])


@row("CHK-M10-222", "every bits/samples plugin under the sandbox: no error, timeout or 126/127; stdout equal to root's outside (#143)")
def r222(ctx: Ctx) -> tuple[str, str]:
    sdir = getattr(ctx, "samples", None)
    if not sdir or not os.path.isdir(sdir):
        return ("NOT RUN", "no samples directory given (--samples)")
    plugins: list[tuple[str, str, int]] = []
    for f in sorted(Path(sdir).glob("*.bit")):
        root = ET.parse(f).getroot()  # noqa: S314 - repo-owned samples
        for p in root.iter():
            if p.tag.split("}")[-1] != "Plugin":
                continue
            name = ex = None
            to = 30
            for c in p:
                t = c.tag.split("}")[-1]
                if t == "PluginName":
                    name = (c.text or "").strip()
                elif t == "Execute":
                    ex = c.text or ""
                    to = int(c.get("timeout", "30"))
            if name and ex:
                plugins.append(("%s: %s" % (f.stem, name), ex.strip(), to))
    specs = [plugin(e, t) for _, e, t in plugins]
    res = run_job(ctx, specs, mpp=4, timeout=1800)
    bad, diff = [], []
    for (name, ex, to), it in zip(plugins, res["results"]):
        it = it or {}
        if it.get("error") or it.get("timed_out") or it.get("exit_code") in (126, 127, None):
            bad.append("%s: exit %s timed_out %s error %s" % (name, it.get("exit_code"), it.get("timed_out"), it.get("error")))
            continue
        d = Path(ctx.work, "root-cwd")
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(mode=0o700)
        r = subprocess.run(["/bin/sh", "-c", ex], capture_output=True, timeout=to + 5, cwd=d,
                           env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, check=False, stdin=subprocess.DEVNULL)
        n1 = norm(it.get("stdout", ""))
        n2 = norm(redact_like(r.stdout.decode(errors="replace"), ctx.patterns))
        if n1 != n2 or it.get("exit_code") != r.returncode:
            diff.append("%s: sandbox exit %s vs root %s; sandbox %r vs root %r" % (name, it.get("exit_code"), r.returncode, mask(n1)[:160], mask(n2)[:160]))
    st = "PASS" if ok_job(res, len(specs)) and not bad and not diff else "FAIL"
    return (st, "%d plugins from %d files; job %s; failing %s; differing from root %s" % (
        len(specs), len(list(Path(sdir).glob("*.bit"))), "done" if ok_job(res, len(specs)) else res["kinds"][-3:], bad, diff))


def norm(s: str) -> str:
    return "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").strip().split("\n"))


def redact_like(s: str, pats: list[str]) -> str:
    # Python re approximates the RE2 default list well enough for a compare of
    # sample output (no capture expansion; same order as the runner).
    for p in pats:
        try:
            s = re.sub(p.replace(r"\z", r"\Z"), lambda _m: "[REDACTED]", s)
        except re.error:
            pass
    return s


# ---- G78 host part: runner security through the driver (REQ-236 (5), REQ-261 (1)) ----


def _refusal_row(ctx: Ctx, rid: str, raw: bytes, job_id: str | None, word: str) -> tuple[str, str]:
    res = send_raw(ctx, raw, timeout=15)
    kinds = [f.get("type") for f in res["frames"]]
    reasons = [f.get("reason") for f in res["frames"] if f.get("type") == "refused"]
    time.sleep(0.5)
    tag = rid.replace("CHK-M10-", "M")
    j = journal(ctx, RUNNER_UNIT)
    lines = [l for l in j.splitlines() if job_id and job_id in l]
    checks = [("one refused frame %s %s" % (kinds, reasons), kinds == ["refused"] and reasons == [word]),
              ("nothing executed", tag not in "".join(ctx.marks))]
    if job_id:
        checks.append(("one log line with the job id (%d)" % len(lines), len(lines) == 1 and word in lines[0]))
        checks.append(("the line holds no payload", all(ctx.canary_exec not in l and "execute" not in l for l in lines)))
    else:
        refl = [l for l in j.splitlines() if word in l]
        checks.append(("a refusal line with the word (%d)" % len(refl), len(refl) >= 1))
    return verdict(checks, "journal: %s" % mask(" | ".join(lines))[:300])


def _marked(ctx: Ctx, tag: str) -> list[dict]:
    return [plugin(": %s; %s" % (ctx.canary_exec, mark_cmd(tag)))]


@row("CHK-M10-280", "an expired job (pickup_by passed) sent straight to the socket is refused and runs nothing")
def r280(ctx: Ctx) -> tuple[str, str]:
    req = request(ctx, _marked(ctx, "M280"), pickup=datetime.now(UTC) - timedelta(seconds=60))
    return _refusal_row(ctx, "CHK-M10-280", frame(req), req["job"]["job_id"], "pickup_passed")


@row("CHK-M10-281", "a foreign job (another agent_id) is refused and runs nothing")
def r281(ctx: Ctx) -> tuple[str, str]:
    req = request(ctx, _marked(ctx, "M281"), agent_id=str(uuid.uuid4()))
    return _refusal_row(ctx, "CHK-M10-281", frame(req), req["job"]["job_id"], "foreign_agent")


@row("CHK-M10-282", "a replayed job (same job_id) is refused and runs nothing the second time")
def r282(ctx: Ctx) -> tuple[str, str]:
    req = request(ctx, _marked(ctx, "M282a"))
    first = send_raw(ctx, frame(req), timeout=30)
    time.sleep(0.3)
    req["job"]["plugins"] = _marked(ctx, "M282b")
    st, ev = _refusal_row(ctx, "CHK-M10-282b", frame(req), None, "replayed")
    ok1 = [f.get("type") for f in first["frames"]][:1] == ["accepted"] and "M282a" in "".join(ctx.marks)
    j = [l for l in journal(ctx, RUNNER_UNIT).splitlines() if req["job"]["job_id"] in l and "replayed" in l]
    if not ok1 or len(j) != 1:
        st = "FAIL"
    return st, "first run executed %s; replay line %d | %s" % (ok1, len(j), ev)


@row("CHK-M10-283", "a wrong peer (root, a member of group bitscan) is closed without a reply and runs nothing")
def r283(ctx: Ctx) -> tuple[str, str]:
    out = []
    for user in ("root", "bs-sbx-member"):
        r = run_job(ctx, _marked(ctx, "M283" + user), user=user, timeout=10)
        out.append(("%s: no frame (%s)" % (user, r["status"]), not r["frames"] and r.get("connect_errno") == 0))
    time.sleep(0.5)
    j = journal(ctx, RUNNER_UNIT)
    peer = [l for l in j.splitlines() if "peer refused" in l]
    uids = sorted(set(re.findall(r"uid=(\d+)", " ".join(peer))))
    out += [("nothing executed", "M283" not in "".join(ctx.marks)), ("peer refused lines name the uids %s" % uids, "0" in uids)]
    return verdict(out, "lines: %s" % " | ".join(peer[-2:])[:200])


@row("CHK-M10-284", "a bare string request is refused malformed and runs nothing")
def r284(ctx: Ctx) -> tuple[str, str]:
    return _refusal_row(ctx, "CHK-M10-284", frame("echo M284; " + mark_cmd("M284")), None, "malformed")


@row("CHK-M10-285", "a plugins list without a job is refused malformed and runs nothing")
def r285(ctx: Ctx) -> tuple[str, str]:
    return _refusal_row(ctx, "CHK-M10-285", frame({"v": 1, "plugins": _marked(ctx, "M285"), "max_parallel_plugins": 1}), None, "malformed")


@row("CHK-M10-286", "a second request frame on one connection is never run")
def r286(ctx: Ctx) -> tuple[str, str]:
    a = request(ctx, [plugin("echo one=1")])
    b = request(ctx, _marked(ctx, "M286"))
    res = send_raw(ctx, frame(a) + frame(b), timeout=30)
    kinds = [f.get("type") for f in res["frames"]]
    time.sleep(0.5)
    j = journal(ctx, RUNNER_UNIT)
    # Any byte after the request ends the connection's job (serve.go: the
    # reader cancels it), so the first job may be cancelled; the second
    # frame is never decoded.
    return verdict([("frames %s: no second accepted, no refused for frame 2" % kinds, kinds.count("accepted") <= 1 and "refused" not in kinds),
                    ("second never executed", "M286" not in "".join(ctx.marks)),
                    ("second job id not logged", b["job"]["job_id"] not in j)])


@row("CHK-M10-287", "an inventory job is refused not_compliance and runs nothing")
def r287(ctx: Ctx) -> tuple[str, str]:
    req = request(ctx, _marked(ctx, "M287"), kind="inventory")
    del req["job"]["plugins"], req["job"]["redaction_patterns"]
    return _refusal_row(ctx, "CHK-M10-287", frame(req), None, "not_compliance")


@row("CHK-M10-288", "an unknown key (\"command\") beside the job is refused and runs nothing")
def r288(ctx: Ctx) -> tuple[str, str]:
    req = request(ctx, _marked(ctx, "M288"))
    req["command"] = "echo M288; " + mark_cmd("M288")
    return _refusal_row(ctx, "CHK-M10-288", frame(req), None, "malformed")


def _capread_raw(user: str, data: bytes) -> tuple[int, bytes]:
    code = ("import socket,sys\ns=socket.socket(socket.AF_UNIX);s.settimeout(15)\n"
            "try:\n  s.connect(%r)\nexcept OSError as e:\n  sys.stdout.write('CONNERR %%d'%%e.errno);sys.exit(0)\n"
            "s.sendall(sys.stdin.buffer.read())\nb=b''\n"
            "try:\n  while True:\n    c=s.recv(65536)\n    if not c: break\n    b+=c\nexcept OSError:\n  pass\n"
            "sys.stdout.buffer.write(b'OK ' + b)\n") % CAPSOCK
    kw: dict = {}
    if user != "root":
        pw = pwd.getpwnam(user)
        kw = {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": os.getgrouplist(user, pw.pw_gid)}
    r = subprocess.run(["/usr/bin/python3", "-I", "-c", code], input=data, capture_output=True, timeout=40, check=False,
                       env={"PATH": "/usr/bin:/bin"}, **kw)
    return r.returncode, r.stdout


@row("CHK-M10-289", "capread refuses every name but its two, runs nothing for them, and serves only bitscan-runner")
def r289(ctx: Ctx) -> tuple[str, str]:
    _capread(True)
    try:
        names = [b"nft_ruleset x\n", b"NFT_RULESET\n", b"../nft\n", b"/usr/sbin/nft\n", b"\n", b"a" * 33 + b"\n",
                 b"id\n", b"shutdown\n", b"nft_ruleset;id\n", b"audit_rules -D\n"]
        checks = []
        for n in names:
            _rc, out = _capread_raw("bitscan-runner", n)
            checks.append(("%r -> %r" % (n[:20], out[:40]), out == b"OK error unknown_request\n"))
        _rc, good = _capread_raw("bitscan-runner", b"nft_ruleset\n")
        checks.append(("control nft_ruleset answered ok", good.startswith(b"OK ok\n") or not os.path.exists("/usr/sbin/nft")))
        for user in ("root", "bitscan"):
            _rc, out = _capread_raw(user, b"nft_ruleset\n")
            checks.append(("peer %s: %r" % (user, out[:30]), out in (b"OK ", b"CONNERR 13")))
        r = sh("runuser -u bitscan-runner -- bitscan-capread /bin/sh; echo RC=$?")
        checks.append(("client with a path: %s" % r.stdout.strip()[-6:], r.stdout.strip().endswith("RC=2")))
        hp = int(sh("systemctl show -p MainPID --value bitscan-capread.service").stdout.strip() or 0)
        kids = sh("ps -o pid=,comm= --ppid %d" % hp).stdout.strip() if hp else ""
        checks.append(("helper has no child left (%s)" % kids, kids == ""))
        return verdict(checks)
    finally:
        _capread(False)


@row("CHK-M10-220", "canary sweep: no execute, stdout, stderr, pattern or token canary in any journal; no TCP/UDP listener of theirs")
def r220(ctx: Ctx) -> tuple[str, str]:
    ex = (": %s; echo %s; echo %s >&2; echo token=%s; echo %s" % (ctx.canary_exec, ctx.canary_out, ctx.canary_err, ctx.canary_tok, ctx.canary_tok))
    pats = ctx.patterns + [ctx.canary_pat + "[0-9]{40}"]
    res = run_job(ctx, [plugin(ex)], patterns=pats)
    it = res["results"][0] or {}
    time.sleep(1)
    j = journal(ctx)
    found = [n for n, c in (("execute", ctx.canary_exec), ("stdout", ctx.canary_out), ("stderr", ctx.canary_err),
                            ("pattern", ctx.canary_pat), ("token", ctx.canary_tok), ("token body", ctx.canary_tok[4:24])) if c in j]
    ss = sh("ss -ltnupH").stdout
    theirs = [l for l in ss.splitlines() if "bitscan" in l]
    lines = len(j.splitlines())
    return verdict([("job done", ok_job(res, 1)), ("token redacted in the reply", ctx.canary_tok not in it.get("stdout", "") and "[REDACTED]" in it.get("stdout", "")),
                    ("stdout canary reached the reply", ctx.canary_out in it.get("stdout", "")),
                    ("no canary in %d journal lines since the suite started: %s" % (lines, found), not found),
                    ("no TCP/UDP listener of bitscan processes", not theirs)], "ss lines of theirs: %s" % theirs)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def setup(ctx: Ctx, args: argparse.Namespace) -> None:
    ctx.runner_was_active = sh("systemctl is-active " + RUNNER_UNIT).stdout.strip() == "active"
    ctx.capread_at_start = {
        "socket": "%s %s" % (sh("systemctl is-enabled bitscan-capread.socket").stdout.strip(), sh("systemctl is-active bitscan-capread.socket").stdout.strip()),
        "service": "%s %s" % (sh("systemctl is-enabled bitscan-capread.service").stdout.strip(), sh("systemctl is-active bitscan-capread.service").stdout.strip()),
    }
    ctx.samples = args.samples
    # test users
    for u, g in (("bs-sbx-member", "bitscan"), ("bs-sbx-outsider", None)):
        if sh("id -u " + u).returncode != 0:
            sh("useradd --system --no-create-home --shell /usr/sbin/nologin %s%s" % (u, " -G " + g if g else ""))
    # planted 0666 listeners where the host has none, and the open control socket
    ctx.planted = []
    ctx.listeners = [Listener(MARK_SOCK, ctx.marks)]
    for p in BLOCKED:
        if p.startswith("/run/systemd/journal") or p == "/var/run/docker.sock":
            continue
        if not os.path.exists(p):
            ctx.listeners.append(Listener(p, None))
            ctx.planted.append(p)
    for lst in ctx.listeners:
        lst.start()
    if ctx.runner_was_active:
        # InaccessiblePaths= is applied at start: restart so the planted paths count
        _restart_runner()


def cleanup(ctx: Ctx) -> None:
    for p in getattr(ctx, "planted", []):
        try:
            os.unlink(p)
        except OSError:
            pass
    if os.path.exists("/run/containerd") and "/run/containerd/containerd.sock" in getattr(ctx, "planted", []):
        try:
            os.rmdir("/run/containerd")
        except OSError:
            pass
    try:
        os.unlink(MARK_SOCK)
    except OSError:
        pass
    sh("userdel bs-sbx-member; userdel bs-sbx-outsider")


def cgroup_v1_mode(ctx: Ctx, out: Path) -> int:
    """VM row CHK-M10-214 on a host booted with cgroup v1 (u2204)."""
    res = run_job(ctx, [plugin(mark_cmd("M214"))], timeout=8)
    time.sleep(1)
    j = journal(ctx, RUNNER_UNIT)
    ref = [l for l in j.splitlines() if "start-up refused" in l]
    st, ev = verdict([("no accepted frame (%s %s)" % (res["kinds"], res["status"]), "accepted" not in res["kinds"]),
                      ("nothing executed", "M214" not in "".join(ctx.marks)),
                      ("journal start-up refused (%d)" % len(ref), bool(ref))], " | ".join(ref[:2])[:300])
    rows = [{"id": "CHK-M10-214", "title": "cgroup v1 host: the runner refuses to start", "status": st, "evidence": ev}]
    for rid, title, _fn in ROWS:
        if rid != "CHK-M10-214":
            rows.append({"id": rid, "title": title, "status": "NOT RUN", "evidence": "host booted with cgroup v1: only CHK-M10-214 runs here"})
    return write_report(out, rows, None, "cgroup v1")


def write_report(out: Path, rows: list[dict], expect_red: str | None, label: str) -> int:
    with open(out / "rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    p = sum(r["status"] == "PASS" for r in rows)
    fl = sum(r["status"] == "FAIL" for r in rows)
    nr = sum(r["status"] == "NOT RUN" for r in rows)
    osr = sh(". /etc/os-release; echo $PRETTY_NAME").stdout.strip()
    md = ["# Bitscan sandbox suite: %s" % label, "",
          "Host %s, kernel %s, systemd %s, cgroup %s, package %s. %s UTC." % (
              osr, os.uname().release, sh("systemctl --version | head -n1").stdout.split()[1] if sh("systemctl --version").returncode == 0 else "?",
              sh("stat -fc %T /sys/fs/cgroup").stdout.strip(), sh("dpkg-query -W -f '${Version}' bitscan-agent").stdout.strip(),
              datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")), "",
          "**%d PASS, %d FAIL, %d NOT RUN** of %d rows." % (p, fl, nr, len(rows)), "",
          "| Row | Check | Result | Evidence |", "| --- | --- | --- | --- |"]
    for r in rows:
        md.append("| %s | %s | %s | %s |" % (r["id"], r["title"].replace("|", "/"), r["status"], mask(r["evidence"]).replace("|", "/").replace("\n", " ")))
    (out / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    if expect_red:
        # ROW, or ROW@part: then the failed check must be that part, so a
        # row already red on a clean build cannot hide a missed plant.
        rid, _, part = expect_red.partition("@")
        hit = [r for r in rows if r["id"] == rid]
        red = bool(hit) and hit[0]["status"] == "FAIL"
        if red and part:
            red = any(part in c and c.endswith("FAILED") for c in hit[0]["evidence"].split(" | ")[0].split("; "))
        print("EXPECT-RED %s: %s" % (expect_red, "RED (plant caught)" if red else "NOT RED (plant missed)"))
        return 0 if red else 1
    return 0 if fl == 0 else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--client":
        return client_main(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rows", default="")
    ap.add_argument("--samples", default="")
    ap.add_argument("--expect-red", default="")
    ap.add_argument("--label", default="sandbox host")
    args = ap.parse_args()
    if os.geteuid() != 0:
        print("run as root", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path("/opt/bs-sbx-work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(mode=0o755, parents=True)
    shutil.copy2(__file__, work / "sandbox.py")
    os.chmod(work / "sandbox.py", 0o644)
    ctx = Ctx(out, work)
    setup(ctx, args)
    try:
        if sh("stat -fc %T /sys/fs/cgroup").stdout.strip() != "cgroup2fs":
            return cgroup_v1_mode(ctx, out)
        want = [x for x in args.rows.split(",") if x]
        rows = []
        for rid, title, fn in ROWS:
            if want and rid not in [w.partition("@")[0] for w in want]:
                continue
            t0 = time.time()
            try:
                st, ev = fn(ctx)
            except Exception as e:  # noqa: BLE001 - a crashed row is a FAIL with its error
                st, ev = "FAIL", "suite error: %s: %s" % (type(e).__name__, mask(str(e))[:300])
                traceback.print_exc()
            rows.append({"id": rid, "title": title, "status": st, "evidence": mask(ev), "seconds": round(time.time() - t0, 1)})
            print("%-14s %-8s %s" % (rid, st, mask(ev)[:220]), flush=True)
        return write_report(out, rows, args.expect_red or None, args.label)
    finally:
        cleanup(ctx)


if __name__ == "__main__":
    sys.exit(main())
