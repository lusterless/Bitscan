"""G41 (tests/m4/test-plan.md CHK-M4-311, TP-M4-23): the installed .deb against the
real M3 manager. A real `bitscan-manager serve` from this tree (PostgreSQL 16 through
Testcontainers, HTTPS with a private CA, the fake vault and audit sink of
manager/tests), and one clean Ubuntu systemd container (m4b-sysd-u24 or -u22) that
installs the package by preseed as an operator would.

The chain, each link one row, and the run stops at the first broken link:
  admin with a TOTP session creates a bse_ token -> install with preseed -> the
  enrolment is held -> approve -> heartbeat -> the first inventory job -> upload ->
  GET /agents/{id} shows os_info and the snapshot (package count = dpkg-query on the
  host) -> a dpkg change on the host -> an unscheduled upload, at least 10 min 30 s
  after the previous one (#80; real time, no manager-side shortcut exists) -> revoke
  -> 401 stops the loops: the journal line, and no agent call in the manager access
  log after the 401.
Plus: no bse_/bsa_ token in serve.log or the agent journal.

The planted violation (an agent that sends list_sha256 over unsorted lines) is the
same run with --deb pointing at a package built from the planted tree: the manager
answers 422 hash_mismatch and the chain stops at the snapshot row.

Run (WSL, root, Docker, the manager venv):
  PYTHONPATH=<copy>/manager PATH=<venv>/bin:$PATH \
    python <copy>/e2e/agent_manager.py --deb DIR --out FILE.jsonl [--image m4b-sysd-u22]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bitscan_manager.auth.totp import code_at, step_at
from tests.certs import make_pki
from tests.conftest import own_migrated_server
from tests.fake_sink import https_sink, server_context
from tests.fake_vault import fake_vault
from tests.test_cli_users_pg import run as run_users
from tests.test_serve_linux import CANARY_VAULT, env_for, free_port, https_get, start, wait_ready

V1 = "/api/v1"
TOKEN_RE = re.compile(r"bs[ae]_[A-Za-z0-9_-]{43}")
HOLD_OFF = 10 * 60 + 30  # #80: unscheduled uploads at least 10 min 30 s apart


@dataclass
class Row:
    step: str
    expected: str
    actual: str
    ok: bool


ROWS: list[Row] = []
SECRETS: dict[str, str] = {}


class Broken(Exception):
    """A link of the chain failed; the run stops there."""


def hide(text: str) -> str:
    for value, name in SECRETS.items():
        text = text.replace(value, name)
    return text


def row(step: str, expected: str, actual: str, ok: bool, stop: bool = True) -> None:
    r = Row(step, expected, hide(actual)[:700], ok)
    ROWS.append(r)
    print(("PASS " if ok else "FAIL ") + f"{step}: {r.actual[:240]}", flush=True)
    if not ok and stop:
        raise Broken(step)


def wait(pred: Callable[[], Any], timeout: float, every: float = 2.0) -> Any:
    end = time.time() + timeout
    while True:
        v = pred()
        if v or time.time() > end:
            return v
        time.sleep(every)


class Host:
    def __init__(self, name: str, image: str) -> None:
        self.name = f"m4a-g41-{name}"
        self.hostname = f"g41-{name}"
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(
            ["docker", "create", "--name", self.name, "--hostname", self.hostname,
             "--privileged", "--cgroupns=private", "--tmpfs", "/run", "--tmpfs", "/run/lock",
             "--add-host", "mgr.example:host-gateway", image],
            check=True, capture_output=True,
        )
        d = Path(tempfile.mkdtemp(prefix="m4a-g41-mid."))
        (d / "machine-id").write_text(secrets.token_hex(16) + "\n")
        subprocess.run(["docker", "cp", str(d / "machine-id"), f"{self.name}:/etc/machine-id"], check=True, capture_output=True)
        shutil.rmtree(d, ignore_errors=True)
        subprocess.run(["docker", "start", self.name], check=True, capture_output=True)
        wait(lambda: self.sh("systemctl is-system-running")[1].strip() in ("running", "degraded"), 60, 1)

    def sh(self, cmd: str, stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
        p = subprocess.run(["docker", "exec", "-i", self.name, "bash", "-c", cmd], input=stdin,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return p.returncode, p.stdout.replace("\r", "")

    def put(self, src: Path, dst: str) -> None:
        subprocess.run(["docker", "cp", str(src), f"{self.name}:{dst}"], check=True, capture_output=True)

    def journal(self) -> str:
        return self.sh("journalctl -u bitscan-agent --no-pager -o cat")[1]

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


class Manager:
    def __init__(self, port: int, ca: Path) -> None:
        self.port, self.ca, self.session, self.used, self.seed = port, ca, "", -1, b""

    def call(self, method: str, path: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
        h = {} if token == "" else {"Authorization": f"Bearer {token or self.session}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        status, _, out = https_get(self.port, self.ca, path, h, data, method)
        try:
            return status, json.loads(out) if out else None
        except ValueError:
            return status, out.decode(errors="replace")

    def code(self) -> str:
        while True:
            now = step_at(datetime.now(UTC))
            for step in (now, now + 1):
                if step > self.used:
                    self.used = step
                    return code_at(self.seed, step)
            time.sleep(0.5)

    def agent(self, agent_id: str) -> dict[str, Any]:
        status, out = self.call("GET", f"{V1}/agents/{agent_id}")
        return out if status == 200 and isinstance(out, dict) else {}

    def audit(self, action: str) -> list[dict[str, Any]]:
        status, out = self.call("GET", f"{V1}/audit-log?limit=500")
        items = out.get("items", []) if status == 200 and isinstance(out, dict) else []
        return [i for i in items if i.get("action") == action]


def access_log(log: Path) -> list[dict[str, Any]]:
    """serve.log JSON lines of the access logger (bitscan_manager.access, one per
    response: method, path, status; never a header, query or body)."""
    out = []
    for line in log.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("logger") == "bitscan_manager.access" and "path" in e:
            out.append(e)
    return out


def chain(m: Manager, h: Host, deb: Path, url: str, serve_log: Path) -> None:  # noqa: PLR0915
    # admin with TOTP; bse_ created with the TOTP session
    admin, pw = "g41-admin", "g41 pass " + secrets.token_hex(8)
    made = run_users(["create-admin", admin], WORK / "creds" / "app_dsn", stdin=pw + "\n")
    row("admin created by the server CLI", "rc 0", str(made.returncode), made.returncode == 0)
    _, out = m.call("POST", f"{V1}/auth/login", {"username": admin, "password": pw}, token="")
    m.session = out["token"]
    _, out = m.call("POST", f"{V1}/auth/totp/enrol", {})
    secret = out["secret"]
    m.seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    m.call("POST", f"{V1}/auth/totp/enrol", {"totp_code": m.code()})
    st, out = m.call("POST", f"{V1}/auth/login", {"username": admin, "password": pw, "totp_code": m.code()}, token="")
    m.session = out["token"] if st == 200 else ""
    SECRETS[m.session] = "<bsu_admin>"
    st, _ = m.call("PATCH", f"{V1}/settings", {"job_pull_seconds": 60})
    row("TOTP-verified admin session; job_pull_seconds 60", "200", str(st), st == 200)
    st, out = m.call("POST", f"{V1}/enrollment-tokens", {"max_uses": 1, "expires_in_hours": 24})
    bse = out.get("token", "") if isinstance(out, dict) else ""
    SECRETS[bse] = "<bse_>"
    row("bse_ enrolment token created with the TOTP session", "201, a bse_ token", f"{st} {bse[:4]}", st == 201 and bse.startswith("bse_"))

    # install with preseed
    h.put(deb, f"/root/{deb.name}")
    h.put(PKI_CA, "/root/manager-ca.pem")
    preseed = (f"bitscan-agent bitscan/manager_url string {url}\n"
               f"bitscan-agent bitscan/enrol_token password {bse}\n"
               "bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\n")
    rc, out = h.sh("install -d -m 0755 /etc/bitscan && install -m 0644 /root/manager-ca.pem /etc/bitscan/ca.pem"
                   f" && debconf-set-selections && cd /root && apt-get install -y ./{deb.name} </dev/null >/root/apt.log 2>&1; echo rc=$?;"
                   " dpkg-query -W -f='${Version} ${Status}' bitscan-agent; echo; systemctl is-active bitscan-agent.service", stdin=preseed)
    row("install with preseed", "rc=0; install ok installed; agent active", out.strip().replace("\n", " "),
        out.startswith("rc=0") and "install ok installed" in out and out.strip().endswith("active"))
    rc, out = h.sh(f"grep -rlF {bse} /var/cache/debconf /etc /var/log 2>/dev/null; true")
    row("the bse_ token is in no debconf file, /etc or log after install", "nothing", out.strip() or "nothing", out.strip() == "")

    # enrolment held, then approve
    def pending() -> dict[str, Any] | None:
        st, out = m.call("GET", f"{V1}/enrollment-requests?state=pending&limit=100")
        items = out.get("items", []) if st == 200 and isinstance(out, dict) else []
        return next((r for r in items if r.get("hostname") == h.hostname), None)

    req = wait(pending, 180)
    row("the enrolment is held (pending request, kind new)", "pending, new", json.dumps({k: (req or {}).get(k) for k in ("kind", "hostname", "agent_version")}),
        bool(req) and req.get("kind") == "new")
    agent_id = h.sh("cat /var/lib/bitscan-agent/agent_id 2>/dev/null")[1].strip()
    det = m.agent(agent_id) if agent_id else {}
    row("while held the agent waits (status awaiting_approval, no inventory)", "awaiting_approval, no snapshot",
        json.dumps({"status": det.get("status"), "snapshot": bool(det.get("last_snapshot"))}),
        det.get("status") == "awaiting_approval" and not det.get("last_snapshot"))
    st, _ = m.call("POST", f"{V1}/enrollment-requests/{req['request_id']}/approve")
    row("admin approves (TOTP session)", "200", str(st), st == 200)

    # heartbeat
    hb = wait(lambda: m.agent(agent_id).get("last_heartbeat_at") and m.agent(agent_id).get("status") == "online", 420, 5)
    det = m.agent(agent_id)
    row("heartbeat after approval: status online", "online, last_heartbeat_at set",
        json.dumps({"status": det.get("status"), "hb": det.get("last_heartbeat_at"), "version": det.get("agent_version")}), bool(hb))

    # inventory job -> upload -> os_info and snapshot
    det = wait(lambda: (lambda d: d if d.get("os_info") and d.get("last_snapshot") else None)(m.agent(agent_id)), 600, 5) or m.agent(agent_id)
    snap = det.get("last_snapshot") or {}
    oi = det.get("os_info") or {}
    n_host = h.sh("dpkg-query -W | wc -l")[1].strip()
    os_host = h.sh(". /etc/os-release; echo $ID $VERSION_ID")[1].split()
    refused = m.audit("agent.inventory_refused")
    row("the first inventory job is uploaded: GET /agents/{id} shows os_info and the snapshot",
        f"os_info {os_host}, x86_64; snapshot package_count {n_host}; no inventory_refused entry",
        json.dumps({"os": [oi.get("os_id"), oi.get("os_version_id"), oi.get("architecture")], "package_count": snap.get("package_count"),
                    "refused": [r.get("detail") for r in refused]}),
        [oi.get("os_id"), oi.get("os_version_id")] == os_host[:2] and oi.get("architecture") == "x86_64"
        and str(snap.get("package_count")) == n_host and not refused)
    st, pk = m.call("GET", f"{V1}/agents/{agent_id}/packages?limit=500")
    names = {p["name"] for p in (pk or {}).get("items", [])} if st == 200 else set()
    row("the package list is searchable for the host (bash, dpkg, libc6 listed)", "200 and the three names", f"{st} {sorted(names & {'bash', 'dpkg', 'libc6'})}",
        st == 200 and {"bash", "dpkg", "libc6"} <= names)
    first_upload = det.get("last_inventory_at")
    t_first = time.time()

    # a dpkg change on the host -> one unscheduled upload, >= 10 min 30 s after the previous one
    acc0 = len(access_log(serve_log))
    rc, out = h.sh("dpkg -i /root/zz.deb 2>&1 | tail -1; dpkg-query -W -f='${Status}' bitscan-g41-probe")
    row("a dpkg change on the host (a probe package installed)", "install ok installed", out.strip().replace("\n", " "), "install ok installed" in out)
    t_change = time.time()

    def puts_since(n0: int) -> list[dict[str, Any]]:
        return [a for a in access_log(serve_log)[n0:] if a.get("method") == "PUT" and a.get("path", "").endswith("/inventory")]

    def listed() -> set[str]:
        st, pk = m.call("GET", f"{V1}/agents/{agent_id}/packages?limit=500")
        return {p["name"] for p in (pk or {}).get("items", [])} if st == 200 else set()

    # #80: 60 s quiet, then upload if 10 min 30 s have passed since the previous
    # *unscheduled* upload (none yet), so this one follows the quiet time.
    got = wait(lambda: puts_since(acc0), 300, 5)
    t_up1 = time.time()
    det = m.agent(agent_id)
    row("the dpkg change leads to one unscheduled upload after the 60 s quiet time; the snapshot lists the probe",
        "one PUT /inventory answered 2xx, 60..180 s after the change; last_inventory_at moves; bitscan-g41-probe listed",
        json.dumps({"puts": [a.get("status") for a in got or []], "after_change_s": round(t_up1 - t_change), "after_job_upload_s": round(t_up1 - t_first),
                    "last_inventory_at": [first_upload, det.get("last_inventory_at")]}),
        bool(got) and len(got) == 1 and 200 <= int(got[0].get("status") or 0) < 300 and 55 <= t_up1 - t_change <= 180
        and det.get("last_inventory_at") != first_upload and "bitscan-g41-probe" in listed())
    # a second change during the hold-off: not sent before 10 min 30 s after the
    # first unscheduled upload, never lost, never refused by the manager (429)
    acc1 = len(access_log(serve_log))
    rc, out = h.sh("dpkg -r bitscan-g41-probe 2>&1 | tail -1; dpkg-query -W -f='${Status}' bitscan-g41-probe 2>&1")
    t_change2 = time.time()
    row("a second dpkg change during the hold-off (the probe removed)", "deinstall ok config-files or not installed", out.strip().replace("\n", " "),
        "installed" not in out.replace("not-installed", "").replace("config-files", "") or "deinstall" in out)
    early = wait(lambda: puts_since(acc1), HOLD_OFF - 60 - (time.time() - t_up1), 10)
    row("no unscheduled upload during the hold-off (#80, the manager's 10 minutes)", f"no PUT /inventory until {HOLD_OFF - 60} s after the first unscheduled upload",
        json.dumps({"puts": [a.get("status") for a in early or []], "watched_s": round(time.time() - t_up1)}), not early)
    got2 = wait(lambda: puts_since(acc1), 420, 5)
    t_up2 = time.time()
    names = listed()
    row("the change made during the hold-off is sent once it ends, never lost or refused",
        f"one PUT /inventory, 2xx, >= {HOLD_OFF} s after the first unscheduled upload; bitscan-g41-probe no longer listed; no 429",
        json.dumps({"puts": [a.get("status") for a in got2 or []], "after_first_unscheduled_s": round(t_up2 - t_up1), "after_change_s": round(t_up2 - t_change2),
                    "probe_listed": "bitscan-g41-probe" in names}),
        bool(got2) and len(got2) == 1 and 200 <= int(got2[0].get("status") or 0) < 300 and t_up2 - t_up1 >= HOLD_OFF - 15
        and "bitscan-g41-probe" not in names)

    # revoke -> 401 stops the loops
    st, _ = m.call("POST", f"{V1}/agents/{agent_id}/revoke")
    row("admin revokes the agent (TOTP session)", "204", str(st), st == 204)
    n_rev = len(access_log(serve_log))
    ok = wait(lambda: "the host must be re-enrolled with a new enrolment token" in h.journal(), 420, 5)
    row("the 401 stops the loops: the journal says the host must be re-enrolled with a new enrolment token", "the line, once",
        f"found={bool(ok)} count={h.journal().count('re-enrolled')}", bool(ok) and h.journal().count("re-enrolled") == 1)
    agent_calls = [a for a in access_log(serve_log)[n_rev:] if f"/agent/{agent_id}/" in a.get("path", "")]
    first401 = next((i for i, a in enumerate(agent_calls) if a.get("status") == 401), None)
    time.sleep(400)  # longer than one heartbeat interval (330 s) and several pull intervals
    agent_calls = [a for a in access_log(serve_log)[n_rev:] if f"/agent/{agent_id}/" in a.get("path", "")]
    after = agent_calls[first401 + 1:] if first401 is not None else agent_calls
    alive = h.sh("systemctl is-active bitscan-agent.service; systemctl show -p NRestarts --value bitscan-agent.service")[1].split()
    row("no agent call in the manager access log after the 401 (400 s watched); the process stays up idle (#81 (a))",
        "a 401, then nothing; active, NRestarts 0",
        json.dumps({"calls_after_revoke": [(a.get("method"), a.get("path", "").rsplit("/", 1)[-1], a.get("status")) for a in agent_calls],
                    "after_401": len(after), "unit": alive}),
        first401 is not None and not after and alive[:1] == ["active"] and alive[1:] == ["0"])

    # secrets
    leaks = [k for k in TOKEN_RE.findall(h.journal())]
    row("no bse_/bsa_ token in the agent journal", "none", str(len(leaks)), not leaks, stop=False)


def probe_deb(work: Path) -> Path:
    """A tiny local package for the dpkg change (no network inside the host)."""
    root = work / "probe"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text("Package: bitscan-g41-probe\nVersion: 1.0\nArchitecture: all\nMaintainer: test <t@example.invalid>\nDescription: G41 dpkg change probe\n")
    out = work / "zz.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(root), str(out)], check=True, capture_output=True)
    return out


WORK = Path()
PKI_CA = Path()


def main() -> int:
    global WORK, PKI_CA  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--deb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--image", default="m4b-sysd-u24")
    args = ap.parse_args()
    deb = next(args.deb.glob("bitscan-agent_*_amd64.deb"))
    WORK = Path(tempfile.mkdtemp(prefix="m4a-g41."))
    h: Host | None = None
    try:
        pki = make_pki(WORK / "pki")
        PKI_CA = pki.ca
        sink_leaf, vault_leaf = pki.leaf("sink"), pki.leaf("vault")
        mgr_leaf = pki.leaf("mgr", sans="DNS:mgr.example,DNS:localhost,IP:127.0.0.1")
        (WORK / "pgcreds").mkdir()
        with (
            own_migrated_server(WORK / "pgcreds") as pg,
            https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
            fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as vault,
        ):
            port = free_port()
            env = env_for(pg, WORK, pki, mgr_leaf, f"https://localhost:{sink.port}/audit", port,
                          BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{vault.port}", BITSCAN_LISTEN=f"0.0.0.0:{port}")
            serve = start(env, WORK, port, pki, mgr_leaf)
            try:
                wait_ready(serve)
                row("real M3 serve ready (PostgreSQL 16, HTTPS, private CA)", "ready", f"port {port}; deb {deb.name}", True)
                h = Host("a", args.image)
                rc, osr = h.sh(". /etc/os-release; echo $PRETTY_NAME")
                row("clean systemd host", args.image, osr.strip(), rc == 0)
                h.put(probe_deb(WORK), "/root/zz.deb")
                chain(Manager(port, pki.ca), h, deb, f"https://mgr.example:{port}", WORK / "serve.log")
            except Broken:
                pass
            finally:
                if serve.proc.poll() is None:
                    serve.stop()
                log = (WORK / "serve.log").read_text(errors="replace")
                row("serve.log holds no bse_/bsa_ token", "none", str(len(TOKEN_RE.findall(log))), not TOKEN_RE.findall(log), stop=False)
                shutil.copy(WORK / "serve.log", args.out.with_suffix(".serve.log"))
    except Exception as exc:  # recorded, then the run fails
        ROWS.append(Row("harness", "no exception", f"{type(exc).__name__}: {exc}", False))
        print(f"FAIL harness: {type(exc).__name__}: {exc}", flush=True)
    finally:
        if h is not None:
            h.remove()
        args.out.write_text("".join(json.dumps(asdict(r)) + "\n" for r in ROWS))
        shutil.rmtree(WORK, ignore_errors=True)
    bad = [r for r in ROWS if not r.ok]
    print(f"{'OK' if not bad else 'FAIL'} {len(ROWS) - len(bad)}/{len(ROWS)} rows", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
