"""M11 nightly end to end (TP-M11-18, REQ-285; #152; CHK-M11-294..303, plants -370, -371).

Runs as root on Linux with Docker, QEMU and /dev/kvm (a hosted ubuntu-24.04
runner, or WSL2 for development), with the system python3 (stdlib only):

  python3 -I e2e/m11/nightly.py --tree TREE --rel RELDIR --deb FILE.deb --images IMGDIR
      --work WORK [--guest-mem 1024] [--expect-red CHK-M11-302] [--keep]
  python3 -I e2e/m11/nightly.py --check-report WORK/report.json

The three machines of TS §8.3 L1283: the manager host (a systemd container
installed by deploy/runbooks/manager-install.md through e2e/m6/manager_walk.py,
with M6's OpenBao and HTTPS-sink doubles, #152 (c)) and two QEMU/KVM guests
from the official Ubuntu 22.04 and 24.04 cloud images (e2e/m11/guests.sh, one
fresh overlay each). The guests reach the manager as bitscan-mgr.test ->
10.0.2.2:18443 (QEMU user networking to the host, where the manager container
publishes 127.0.0.1:18443). A test CA per run (the runbook's §1.1 lab CA); the
agents use CA_FILE, and the 24.04 guest also the SPKI pin (#152 (d)).

The chain, one row per step and host (#152 (f)):
  enrol -> approve (API, admin TOTP session) -> heartbeat -> first inventory ->
  import (the SR §1.1 canonical example, extracted verbatim from the spec) ->
  a scan of both hosts -> results (GET /scans/{id}: completed, score 1.0,
  errors 0; /results: PASS, exit 0; /results.csv parsed; a viewer's results
  and CSV without stdout or stderr), plus the pre-check and a secret sweep.
A row is PASS, FAIL or NOT RUN with its reason; a step whose input is missing
(an earlier step failed) is NOT RUN, never skipped silently. The run writes
WORK/report.json ({"expected": [...], "rows": [...]}) and WORK/report.md;
`--check-report` exits 1 when a row is FAIL or an expected row is missing
(REQ-286; the workflow uses it). `--expect-red CHK` is for the plants: the run
then passes only if that row is FAIL.

Secrets (the admin session and TOTP seed, the viewer's bsk_, the bse_
tokens) stay in memory or 0600 files under WORK/secrets; the bse_ reaches each
guest's root-only install.env through ssh's stdin, never a command line.
Every printed or saved text is masked for bs[uaek]_ and for each secret value.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOSTNAME = "bitscan-mgr.test"
PORT = 18443
CT = "m11n-mgr"
GUESTS = {"u2204": ("bitscan-n2204", "jammy-server-cloudimg-amd64.img", 22204, "22.04"),
          "u2404": ("bitscan-n2404", "noble-server-cloudimg-amd64.img", 22404, "24.04")}
SR_PLUGIN = "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"
SR_POLICY = "CIS Ubuntu 24.04 Level 1 - Server"
TOKEN_RE = re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{8,}")
FULL_TOKEN_RE = re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{43}")
V1 = "/api/v1"

# (chk, host) of every row a complete run has; --check-report and the workflow compare against it
EXPECTED: list[tuple[str, str]] = (
    [("CHK-M11-294", "runner"), ("CHK-M11-295", "manager")]
    + [(c, h) for h in GUESTS for c in ("CHK-M11-296", "CHK-M11-297", "CHK-M11-298", "CHK-M11-299")]
    + [("CHK-M11-300", "manager"), ("CHK-M11-301", "manager")]
    + [("CHK-M11-301", h) for h in GUESTS] + [("CHK-M11-302", h) for h in GUESTS]
    + [("CHK-M11-302", "csv"), ("CHK-M11-302", "viewer"), ("CHK-M11-303", "all")]
)

ROWS: list[dict] = []
SECRETS: list[str] = []
WORK = Path()


def mask(text: str) -> str:
    for s in SECRETS:
        if s and len(s) >= 6:
            text = text.replace(s, "<secret>")
    return TOKEN_RE.sub(lambda m: m.group(0)[:4] + "<masked>", text)


def _masked_excepthook(kind: type[BaseException], value: BaseException, tb: object) -> None:
    """An uncaught exception's traceback goes to stderr (the run log) masked, like every row:
    a value in an exception message or a local repr can never print a token or a secret."""
    import traceback
    sys.stderr.write(mask("".join(traceback.format_exception(kind, value, tb))))  # type: ignore[arg-type]


sys.excepthook = _masked_excepthook


def row(chk: str, host: str, step: str, ok: bool | None, evidence: str, reason: str = "") -> bool:
    status = "NOT RUN" if ok is None else ("PASS" if ok else "FAIL")
    r = {"chk": chk, "host": host, "step": step, "status": status,
         "evidence": mask(evidence)[-1500:], "reason": reason, "t": datetime.now(UTC).strftime("%H:%M:%SZ")}
    ROWS.append(r)
    with (WORK / "rows.jsonl").open("a") as f:
        f.write(json.dumps(r) + "\n")
    print(f"{status} {chk} {host} {step} :: {r['evidence'][-300:]}{' [' + reason + ']' if reason else ''}", flush=True)
    return ok is True


def notrun(chk: str, host: str, step: str, reason: str) -> None:
    row(chk, host, step, None, "", reason)


def wait(fn, timeout: float, every: float = 5.0):  # noqa: ANN001, ANN201
    end = time.time() + timeout
    while True:
        v = fn()
        if v or time.time() > end:
            return v
        time.sleep(every)


def run(argv: list[str], stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
    kw: dict = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, **kw)
    return p.returncode, p.stdout.replace("\r", "")


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)


# ---------------------------------------------------------------- transports

def mgr_sh(cmd: str, timeout: int = 600) -> tuple[int, str]:
    """A root shell in the manager host."""
    return run(["docker", "exec", "-i", CT, "bash", "-o", "pipefail", "-c", cmd], timeout=timeout)


def guest(name: str, *args: str, stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
    return run(["bash", str(HERE / "guests.sh"), *args[:1], name, *args[1:]], stdin=stdin, timeout=timeout)


def on(h: str, cmd: str, stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
    return guest(GUESTS[h][0], "ssh", cmd, stdin=stdin, timeout=timeout)


class Api:
    """HTTPS to the published manager (127.0.0.1:PORT), verified for HOSTNAME with the run's CA."""

    def __init__(self, ca: Path) -> None:
        self.ctx = ssl.create_default_context(cafile=str(ca))
        self.session = ""  # bsu_ of the admin TOTP session

    def raw(self, method: str, path: str, body: bytes | None = None, token: str | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPSConnection(HOSTNAME, PORT, context=self.ctx, timeout=60)
        conn.sock = self.ctx.wrap_socket(socket.create_connection(("127.0.0.1", PORT), 30), server_hostname=HOSTNAME)
        h = dict(headers or {})
        tok = self.session if token is None else token
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        try:
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            conn.close()

    def json(self, method: str, path: str, body: object = None, token: str | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, object]:
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        try:
            st, _, out = self.raw(method, path, data, token, h)
        except OSError as e:
            return 0, f"{type(e).__name__}: {e}"
        try:
            return st, json.loads(out) if out else None
        except ValueError:
            return st, out.decode(errors="replace")


# ---------------------------------------------------------------- steps

def sr_example(tree: Path) -> bytes:
    """The SR §1.1 canonical example, byte for byte from the spec's fenced block."""
    md = (tree / "docs" / "spec" / "bit_Schema_Reference.md").read_text(encoding="utf-8")
    sec = md.split("### 1.1 Canonical example", 1)[1]
    body = sec.split("```xml\n", 1)[1].split("\n```", 1)[0]
    return (body + "\n").encode("utf-8")


def precheck(a: argparse.Namespace) -> bool:
    facts, ok = [], True
    kvm = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)
    facts.append(f"/dev/kvm usable {kvm}")
    ok &= kvm
    q = shutil.which("qemu-system-x86_64") is not None and shutil.which("cloud-localds") is not None
    facts.append(f"qemu and cloud-localds {q}")
    ok &= q
    for _, (_, img, _, _) in GUESTS.items():
        sums = a.images / ("noble" if "noble" in img else "jammy")
        sums = sums.with_suffix(".SHA256SUMS")
        want = next((ln.split()[0] for ln in sums.read_text().split("\n") if ln.endswith(img)), "") if sums.exists() else ""
        got = sha256_file(a.images / img)
        facts.append(f"{img} sha256 {'OK' if want and got == want else 'MISMATCH or missing'}")
        ok &= bool(want) and got == want
    deb_sha = sha256_file(a.deb)
    side = a.deb.with_name(a.deb.name + ".sha256")
    pub = side.read_text().split()[0] if side.exists() else ""
    facts.append(f"{a.deb.name} sha256 {deb_sha[:16]}… published {'match' if pub == deb_sha else 'MISMATCH or missing'}")
    ok &= bool(pub) and pub == deb_sha
    mem = int(next(ln.split()[1] for ln in Path("/proc/meminfo").read_text().split("\n") if ln.startswith("MemAvailable:"))) // 1024
    need = 1200 + 2 * a.guest_mem  # the manager host uses about 0.7 GB (M6), plus the guests
    facts.append(f"MemAvailable {mem} MB (need {need})")
    ok &= mem >= need
    rc, ss = run(["sh", "-c", f"ss -ltnH 'sport = :{PORT}' | wc -l"])
    facts.append(f"port {PORT} free {ss.strip() == '0'}")
    ok &= ss.strip() == "0"
    return row("CHK-M11-294", "runner", "pre-check: KVM, QEMU, verified images and .deb, memory, port", ok, "; ".join(facts))


def manager(a: argparse.Namespace) -> Api | None:
    wk = WORK / "walk"
    log = wk / "walk.log"
    wk.mkdir(parents=True, exist_ok=True)
    rc, _ = run(["sh", "-c", f"cd {shlex.quote(str(a.tree))} && python3 -I e2e/m6/manager_walk.py --tree {shlex.quote(str(a.tree))} "
                 f"--rel {shlex.quote(str(a.rel))} --work {shlex.quote(str(wk))} --name {CT} --publish 127.0.0.1:{PORT}:8443 "
                 f"--log {shlex.quote(str(log))} --keep > {shlex.quote(str(log))} 2>&1"], timeout=3600)
    tail = log.read_text(errors="replace").strip().split("\n")[-1] if log.exists() else ""
    for f in (wk / "secrets").glob("*"):
        SECRETS.append(f.read_text().strip())
    if not row("CHK-M11-295", "manager", "manager host installed by manager-install.md (e2e/m6/manager_walk.py, 0 FAIL)",
               rc == 0 and "0 failed" in tail, f"rc {rc}; {tail}"):
        return None
    rc, ca = mgr_sh("cat /home/admin/rel/manager-ca.pem")
    (WORK / "manager-ca.pem").write_text(ca)
    rc, st = mgr_sh("cat /home/admin/stage/session.json")
    state = json.loads(st) if st.strip().startswith("{") else {}
    SECRETS.extend(str(state.get(k, "")) for k in ("token", "secret"))
    write_private(WORK / "secrets" / "session.json", st)
    api = Api(WORK / "manager-ca.pem")
    api.session = str(state.get("token", ""))
    return api


def tokens(api: Api) -> dict[str, str]:
    """job_pull_seconds 60, a viewer with a bsk_ (server CLI), one single-use bse_ per guest."""
    out: dict[str, str] = {}
    st, _ = api.json("PATCH", f"{V1}/settings", {"job_pull_seconds": 60})
    out["settings"] = str(st)
    pw = secrets.token_urlsafe(18)
    SECRETS.append(pw)
    st, _ = api.json("POST", f"{V1}/users", {"username": "nightly-viewer", "password": pw, "role": "viewer"})
    out["viewer_user"] = str(st)
    rc, bsk = mgr_sh("bitscan-manager users create-api-token nightly-viewer --name nightly 2>&1")
    m = FULL_TOKEN_RE.search(bsk)
    out["viewer"] = m.group(0) if m else ""
    for h in GUESTS:
        st, body = api.json("POST", f"{V1}/enrollment-tokens", {"max_uses": 1, "expires_in_hours": 24})
        out[h] = str((body or {}).get("token", "")) if isinstance(body, dict) else ""
    SECRETS.extend(v for k, v in out.items() if k in ("viewer", *GUESTS))
    return out


def boot_one(a: argparse.Namespace, h: str) -> bool:
    name, img, port, _ = GUESTS[h]
    rc, out = guest(name, "up", str(a.images / img), str(port), str(a.guest_mem), timeout=900)
    print(f"guest {h}: rc {rc} {out.strip()[-300:]}", flush=True)
    return rc == 0


def boot(a: argparse.Namespace) -> dict[str, bool]:
    return {h: boot_one(a, h) for h in GUESTS}


def install(h: str, a: argparse.Namespace, bse: str, pin: str) -> tuple[bool, str]:
    name = GUESTS[h][0]
    guest(name, "put", str(a.deb), f"/tmp/{a.deb.name}")
    guest(name, "put", str(WORK / "manager-ca.pem"), "/tmp/manager-ca.pem")
    env = f"MANAGER_URL=https://{HOSTNAME}:{PORT}\nENROL_TOKEN={bse}\nCA_FILE=/etc/bitscan/ca.pem\n"
    if pin:
        env += f"MANAGER_SPKI_SHA256={pin}\n"
    # agent-install.md §3c: root-only install.env; the token comes in on stdin
    rc, out = on(h, "sudo install -d -m 0755 /etc/bitscan && sudo install -m 0644 /tmp/manager-ca.pem /etc/bitscan/ca.pem && "
                    "sudo install -m 0600 /dev/null /etc/bitscan/install.env && sudo tee /etc/bitscan/install.env >/dev/null", stdin=env)
    rc, out = on(h, f"cd /tmp && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./{shlex.quote(a.deb.name)} >/tmp/apt.log 2>&1; echo rc=$?; "
                    "dpkg-query -W -f='${Version} ${Status}\\n' bitscan-agent; systemctl is-active bitscan-agent.service; "
                    "sudo test -e /etc/bitscan/install.env && echo INSTALL-ENV-LEFT; tail -n 2 /tmp/apt.log", timeout=900)
    return ("rc=0" in out and "install ok installed" in out and "INSTALL-ENV-LEFT" not in out), out


CHAIN_IDS = ("CHK-M11-296", "CHK-M11-297", "CHK-M11-298", "CHK-M11-299")


def chain_host(api: Api, h: str, a: argparse.Namespace, bse: str, pin: str, deb_version: str,
               ids: tuple[str, str, str, str] = CHAIN_IDS, label: str = "") -> str:
    """install -> enrol -> approve -> heartbeat -> inventory for one guest; returns the agent_id ('' on a break).
    compat.py passes its own check ids and a row label per step (`label:enrol` ...)."""
    lab = (lambda s: f"{label}:{s}") if label else (lambda s: h)
    ok, out = install(h, a, bse, pin)
    rc, mid = on(h, "cat /etc/machine-id")
    rc, hn = on(h, "hostname")
    mid, hn = mid.strip(), hn.strip()

    def pending() -> dict | None:
        st, body = api.json("GET", f"{V1}/enrollment-requests?state=pending&limit=100")
        items = body.get("items", []) if st == 200 and isinstance(body, dict) else []
        return next((q for q in items if q.get("machine_id") == mid), None)

    q = wait(pending, 180, 5) if ok else None
    row(ids[0], lab("enrol"), "enrol: the .deb installs with install.env and the enrolment is held (kind new, this host)",
        bool(ok and q and q.get("hostname") == hn and q.get("kind") == "new" and q.get("agent_version") == deb_version),
        f"install: {out.strip()[-250:]}; request {json.dumps({k: (q or {}).get(k) for k in ('request_id', 'kind', 'hostname', 'agent_version')})}")
    if not q:
        for c, s in ((ids[1], "approve"), (ids[2], "heartbeat"), (ids[3], "inventory")):
            notrun(c, lab(s), s, f"no held enrolment ({ids[0]})")
        return ""
    aid = str(q.get("agent_id", ""))
    st, _ = api.json("POST", f"{V1}/enrollment-requests/{q['request_id']}/approve")
    row(ids[1], lab("approve"), "approve with the admin TOTP session (API)", st == 200, f"POST approve {st}")

    def agent() -> dict:
        st, body = api.json("GET", f"{V1}/agents/{aid}")
        return body if st == 200 and isinstance(body, dict) else {}

    t0 = time.time()
    on_ = wait(lambda: agent().get("status") == "online" and agent().get("last_heartbeat_at"), 420, 10)
    d = agent()
    row(ids[2], lab("heartbeat"), "heartbeat: online after approval, with the package version", bool(on_) and d.get("agent_version") == deb_version,
        f"{time.time() - t0:.0f} s; {json.dumps({k: d.get(k) for k in ('status', 'last_heartbeat_at', 'agent_version')})}")
    d = wait(lambda: (lambda x: x if x.get("os_info") and x.get("last_snapshot") else None)(agent()), 600, 10) or agent()
    oi, snap = d.get("os_info") or {}, d.get("last_snapshot") or {}
    rc, n = on(h, "dpkg-query -W | wc -l")
    row(ids[3], lab("inventory"), "first inventory: os_info of this host and a snapshot with every dpkg package",
        oi.get("os_id") == "ubuntu" and oi.get("os_version_id") == GUESTS[h][3] and oi.get("architecture") == "x86_64"
        and str(snap.get("package_count")) == n.strip(),
        f"os {[oi.get('os_id'), oi.get('os_version_id'), oi.get('architecture')]}; package_count {snap.get('package_count')} vs dpkg-query {n.strip()}")
    return aid


def import_sr(api: Api, tree: Path) -> int:
    data = sr_example(tree)
    boundary = "m11n-" + secrets.token_hex(12)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sr-1.1-canonical.bit\"\r\n"
            "Content-Type: application/xml\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    st, _, out = api.raw("POST", f"{V1}/policies/import", body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        res = json.loads(out)
    except ValueError:
        res = {}
    pid = int(res.get("policy_id") or 0) if isinstance(res, dict) else 0
    st2, pol = api.json("GET", f"{V1}/policies/{pid}") if pid else (0, {})
    plugins = (pol or {}).get("plugins", []) if isinstance(pol, dict) else []
    ok = (st == 200 and res.get("outcome") == "success" and res.get("policy_name") == SR_POLICY and st2 == 200
          and res.get("plugins_added") == 1 and [p.get("plugin_uuid") for p in plugins] == [SR_PLUGIN])
    row("CHK-M11-300", "manager", "import the SR §1.1 canonical example (verbatim from the spec) by upload",
        ok, f"sha256 {hashlib.sha256(data).hexdigest()[:16]}…; {st} {json.dumps({k: res.get(k) for k in ('outcome', 'policy_id', 'policy_name', 'plugins_added', 'errors')})}; "
            f"GET /policies/{pid} {st2}, plugins {[(p.get('plugin_uuid'), p.get('display_name') or p.get('plugin_name')) for p in plugins]}")
    return pid if ok else 0


def scan(api: Api, pid: int, aids: dict[str, str]) -> str:
    target = {"agents": sorted(aids.values())}
    st, body = api.json("POST", f"{V1}/scans", {"policy_id": pid, "target": target}, headers={"Idempotency-Key": str(uuid.uuid4())})
    sid = str((body or {}).get("scan_id", "")) if isinstance(body, dict) else ""
    row("CHK-M11-301", "manager", "a scan of both hosts queued (operator route, admin session)", st == 202 and bool(sid),
        f"POST /scans {st} {json.dumps(body)[:300] if isinstance(body, dict) else body}")
    return sid


def runner_done(h: str) -> int:
    """The runner's own count of finished plugins on the guest (its line holds ids, exit code and
    duration, never output)."""
    _, n = on(h, "sudo journalctl -u bitscan-runner -o cat --no-pager | grep -c 'runner: plugin done' || true")
    return int(n.strip()) if n.strip().isdigit() else -1


def results(api: Api, sid: str, aids: dict[str, str], viewer: str) -> None:
    final = {"completed", "partial", "failed", "cancelled"}

    def detail() -> dict | None:
        st, body = api.json("GET", f"{V1}/scans/{sid}")
        if st in (404, 501):  # the scan was just created, so the read route itself is missing or unfilled (before TASK-244)
            return {"state": "read route missing (404 or 501)"}
        return body if st == 200 and isinstance(body, dict) and body.get("state") in final else None

    det = wait(detail, 900, 10)
    if isinstance(det, dict) and det.get("state") == "read route missing (404 or 501)":  # still show whether the guests ran it
        wait(lambda: all(runner_done(h) >= 1 for h in aids), 600, 15)
    st, last = api.json("GET", f"{V1}/scans/{sid}")
    det = det or (last if isinstance(last, dict) else {})
    hosts = {x.get("agent_id"): x for x in det.get("hosts", [])} if isinstance(det, dict) else {}
    items: list[dict] = []
    cur, pst = None, 0
    while True:
        pst, page = api.json("GET", f"{V1}/scans/{sid}/results?limit=500" + (f"&cursor={cur}" if cur else ""))
        if pst != 200 or not isinstance(page, dict):
            break
        items += page.get("items", [])
        cur = page.get("next_cursor")
        if not cur:
            break
    for h, aid in aids.items():
        x = hosts.get(aid, {})
        mine = [i for i in items if i.get("agent_id") == aid]
        jobs = [j.get("state") for j in x.get("jobs", [])]
        row("CHK-M11-301", h, "the host's compliance job completed", jobs[:1] == ["completed"],
            f"GET /scans/{{id}} {st}; jobs {jobs}; runner journal 'plugin done' lines {runner_done(h)}")
        ok = (det.get("state") == "completed" and x.get("score") == 1.0 and x.get("errors") == 0 and x.get("passed") == 1
              and x.get("failed") == 0 and x.get("not_run") == 0 and len(mine) == 1 and mine[0].get("plugin_uuid") == SR_PLUGIN
              and mine[0].get("result") == "PASS" and mine[0].get("exit_code") == 0 and mine[0].get("original_result") == "PASS"
              and "install ok installed" in str(mine[0].get("stdout")))
        row("CHK-M11-302", h, "results: scan completed, score 1.0, errors 0; the plugin PASS with exit 0 and its stdout (admin)", ok,
            f"scan {det.get('state')}; host {json.dumps({k: x.get(k) for k in ('passed', 'failed', 'errors', 'not_run', 'score')})}; results {pst}, "
            + json.dumps([{k: i.get(k) for k in ('plugin_uuid', 'result', 'exit_code', 'original_result')} | {"stdout": str(i.get('stdout'))[:40]} for i in mine]))
    st, hd, raw = api.raw("GET", f"{V1}/scans/{sid}/results.csv")
    rows_ = list(csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))) if st == 200 else []
    by = {r.get("agent_id"): r for r in rows_}
    ok = (st == 200 and hd.get("content-disposition", "") == f'attachment; filename="scan-{sid}-results.csv"' and len(rows_) == 2
          and all(by.get(aid, {}).get("result") == "PASS" and by.get(aid, {}).get("exit_code") == "0" for aid in aids.values())
          and "stdout" in (rows_[0].keys() if rows_ else []))
    row("CHK-M11-302", "csv", "results.csv parsed: one PASS row per host with exit 0; admin header has stdout", ok,
        f"{st} {hd.get('content-disposition')}; header {list(rows_[0].keys()) if rows_ else []}; rows {[(r.get('hostname'), r.get('result'), r.get('exit_code')) for r in rows_]}")
    vst, vpage = api.json("GET", f"{V1}/scans/{sid}/results?limit=500", token=viewer)
    vitems = vpage.get("items", []) if isinstance(vpage, dict) else []
    cst, _, craw = api.raw("GET", f"{V1}/scans/{sid}/results.csv", token=viewer)
    vhead = next(csv.reader(io.StringIO(craw.decode("utf-8", errors="replace"))), []) if cst == 200 else []
    leaked = [k for i in vitems for k in ("stdout", "stderr") if k in i]
    ok = (bool(viewer) and vst == 200 and len(vitems) == 2 and not leaked and cst == 200 and vhead
          and "stdout" not in vhead and "stderr" not in vhead and "install ok installed" not in craw.decode(errors="replace"))
    row("CHK-M11-302", "viewer", "a viewer's results (JSON and CSV) hold no stdout or stderr", ok,
        f"JSON {vst}: {len(vitems)} items, keys with output {leaked}; CSV {cst}: header {vhead}")


def sweep(a: argparse.Namespace, label: str = "all", chk: str = "CHK-M11-303", hosts: list[str] | None = None) -> None:
    texts: dict[str, str] = {"rows": (WORK / "rows.jsonl").read_text()}
    if a.log and a.log.exists():
        texts["harness log"] = a.log.read_text(errors="replace")
    wl = WORK / "walk" / "walk.log"
    if wl.exists():
        texts["walk log"] = wl.read_text(errors="replace")
    rc, j = mgr_sh("journalctl --no-pager -o cat")
    texts["manager host journal"] = j
    for h in hosts if hosts is not None else list(GUESTS):
        rc, j = on(h, "sudo journalctl --no-pager -o cat")
        texts[f"{h} journal"] = j
    hits = []
    vals = [v for v in SECRETS if len(v) >= 8]
    for name, text in texts.items():
        n = sum(text.count(v) for v in vals) + len(FULL_TOKEN_RE.findall(text))
        if n:
            hits.append(f"{name}: {n}")
    row(chk, label, "token and password sweep over the report, the logs and every journal", not hits,
        f"{len(vals)} secret values and the bs?_ token pattern over {sorted(texts)}; hits {hits or 0}")


def report(expect_red: str | None) -> int:
    data = {"expected": [list(e) for e in EXPECTED], "rows": ROWS}
    (WORK / "report.json").write_text(json.dumps(data, indent=1))
    lines = ["| Check | Host | Step | Result | Evidence |", "| --- | --- | --- | --- | --- |"]
    for r in ROWS:
        ev = (r["evidence"] or r["reason"]).replace("|", "/").replace("\n", " ")[:400]
        lines.append(f"| {r['chk']} | {r['host']} | {r['step']} | {r['status']}{' (' + r['reason'] + ')' if r['reason'] else ''} | {ev} |")
    (WORK / "report.md").write_text("\n".join(lines) + "\n")
    bad = check(data)
    if expect_red:
        red = [r for r in ROWS if r["chk"] == expect_red and r["status"] == "FAIL"]
        print(f"plant: {expect_red} {'red as required' if red else 'NOT red'}", flush=True)
        return 0 if red else 1
    return 1 if bad else 0


def check(data: dict) -> list[str]:
    have = {(r["chk"], r["host"]) for r in data.get("rows", [])}
    bad = [f"missing {c} {h}" for c, h in (tuple(e) for e in data.get("expected", [])) if (c, h) not in have]
    bad += [f"FAIL {r['chk']} {r['host']}" for r in data.get("rows", []) if r.get("status") == "FAIL"]
    n = len(data.get("rows", []))
    p = sum(1 for r in data.get("rows", []) if r.get("status") == "PASS")
    print(f"report: {p}/{n} rows PASS, {sum(1 for r in data.get('rows', []) if r.get('status') == 'FAIL')} FAIL, "
          f"{sum(1 for r in data.get('rows', []) if r.get('status') == 'NOT RUN')} NOT RUN; problems {bad or 0}", flush=True)
    return bad


def main() -> int:
    global WORK  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-report", type=Path)
    ap.add_argument("--tree", type=Path)
    ap.add_argument("--rel", type=Path)
    ap.add_argument("--deb", type=Path)
    ap.add_argument("--images", type=Path)
    ap.add_argument("--work", type=Path)
    ap.add_argument("--log", type=Path, help="the file this run's stdout goes to (for the sweep)")
    ap.add_argument("--guest-mem", type=int, default=1024)
    ap.add_argument("--expect-red")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if a.check_report:
        return 1 if check(json.loads(a.check_report.read_text())) else 0
    for k in ("tree", "rel", "deb", "images", "work"):
        if getattr(a, k) is None:
            ap.error(f"--{k} is required")
    a.tree, a.rel, a.deb, a.images = (p.resolve() for p in (a.tree, a.rel, a.deb, a.images))
    WORK = a.work
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o700)
    (WORK / "secrets").mkdir(mode=0o700, exist_ok=True)
    (WORK / "rows.jsonl").write_text("")
    os.environ.setdefault("GUESTS_DIR", str(WORK / "guests"))
    deb_version = a.deb.name.split("_")[1] if a.deb.name.count("_") == 2 else "?"
    up: dict[str, bool] = {}
    try:
        if not precheck(a):
            for c, h in EXPECTED[1:]:
                notrun(c, h, "chain", "the pre-check failed (CHK-M11-294); never a silent skip (#152 (a))")
            return report(a.expect_red)
        api = manager(a)
        if api is None:
            for c, h in EXPECTED[2:]:
                notrun(c, h, "chain", "no manager host (CHK-M11-295)")
            return report(a.expect_red)
        tok = tokens(api)
        print(f"set-up: settings {tok.get('settings')}, viewer user {tok.get('viewer_user')}, viewer bsk_ {bool(tok.get('viewer'))}, "
              f"bse_ {[bool(tok.get(h)) for h in GUESTS]}", flush=True)
        rc, pin = mgr_sh("openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1")
        up = boot(a)
        aids: dict[str, str] = {}
        for h in GUESTS:
            if not up[h]:
                for c in ("CHK-M11-296", "CHK-M11-297", "CHK-M11-298", "CHK-M11-299"):
                    row(c, h, "chain", False, f"guest {h} did not boot (guests.sh up)")
                continue
            aid = chain_host(api, h, a, tok.get(h, ""), pin.strip() if h == "u2404" else "", deb_version)
            if aid:
                aids[h] = aid
        pid = import_sr(api, a.tree)
        sid = scan(api, pid, aids) if pid and len(aids) == len(GUESTS) else ""
        if not sid:
            if not pid or len(aids) != len(GUESTS):
                notrun("CHK-M11-301", "manager", "scan", "no policy or not both hosts enrolled (CHK-M11-296..300)")
            for h in GUESTS:
                notrun("CHK-M11-301", h, "job", "no scan")
                notrun("CHK-M11-302", h, "results", "no scan")
            notrun("CHK-M11-302", "csv", "results.csv", "no scan")
            notrun("CHK-M11-302", "viewer", "viewer results", "no scan")
        else:
            results(api, sid, aids, tok.get("viewer", ""))
        sweep(a)
    except Exception as exc:  # recorded, then the run fails
        row("CHK-M11-294", "harness", "no harness exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        if not a.keep:
            for h, (name, *_r) in GUESTS.items():
                guest(name, "down")
            run(["docker", "rm", "-f", CT])
            shutil.rmtree(WORK / "walk" / "secrets", ignore_errors=True)  # the walk's test passwords, host gone
        shutil.rmtree(WORK / "secrets", ignore_errors=True)
    return report(a.expect_red)


if __name__ == "__main__":
    sys.exit(main())
