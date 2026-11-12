"""M11 N / N−1 rows (TP-M11-19, REQ-287, REQ-288; #153; CHK-M11-304..309, plant -372).

N = the tree under test (manager wheel and agent .deb built from it); N−1 = the
previous release (`--prev`: since 0.3.0 the v0.2.0 release,
`bitscan-agent_0.2.0-1_amd64.deb` and the manager files), each file checked
against the SHA256SUMS text of the release page (#153 (a)). Same machines and
helpers as nightly.py (the manager host by the install walk, QEMU/KVM guests);
one phase per run, so at most one manager and one or two guests are up at a time:

  python3 -I e2e/m11/compat.py --phase a|b|upgrade --tree TREE --rel REL_N --deb-n FILE.deb
      --prev DIR --prev-sums FILE --images IMGDIR --work WORK [--guest-mem 1024] [--keep]
      [--plant-rel REL_PLANT --expect-red CHK]

A plant of a manager tree (CHK-M11-372) is not installed by the walk: the
walk's own simulated agent would meet it first. The walk installs manager N
from --rel, then --plant-rel is deployed onto it by manager-operations.md §1
(rows `plant:*`), and the phase runs against the planted manager.
  python3 -I e2e/m11/nightly.py --check-report WORK/report.json

  a        manager N, agent N−1 (u2204): enrol, approve, heartbeat, inventory
           (CHK-M11-305); a scan of the SR §1.1 example completes: PASS, exit 0,
           score 1.0, no errors (CHK-M11-306)
  b        manager N−1, agent N (u2404): enrol, approve, heartbeat, inventory
           (CHK-M11-308); a scan completes the same way (CHK-M11-309)
  upgrade  once at the gate (#153 (d)), CHK-M11-307: manager N−1 with agent
           N−1 enrolled -> manager-operations.md §1 to N (files checked, stop,
           pip, units, migrate, start) -> heartbeats and inventory go on -> the
           agent upgraded to N (agent-install.md §6) -> a scan completes (PASS)

Until 0.3.0, N−1 was v0.1.0, whose agent answered every check with
runner_unavailable and whose manager had no scans; those expectations went
with it (decisions 2026-11-12, release 0.3.0).

Every phase starts with CHK-M11-304 (pre-check: the release files against the
published sums, the N .deb against its .sha256, KVM, images, memory) and ends
with a CHK-M11-309 token sweep (host `sweep:<phase>`). Rows, report and secret
handling as in nightly.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nightly as n  # noqa: E402

SUMS_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)$")
MANAGER_FILES = ("bitscan-manager.service", "bitscan-manager-migrate.service", "bitscan-manager-maintain.service",
                 "bitscan-manager-maintain.timer")
PREV_DEB = "bitscan-agent_0.2.0-1_amd64.deb"
PREV_VERSION = "0.2.0-1"

EXPECTED = {
    "a": [("CHK-M11-304", "runner")] + [("CHK-M11-305", f"agentPrev:{s}") for s in ("enrol", "approve", "heartbeat", "inventory")]
         + [("CHK-M11-306", "agentPrev:scan"), ("CHK-M11-306", "agentPrev:results"), ("CHK-M11-309", "sweep:a")],
    "b": [("CHK-M11-304", "runner")] + [("CHK-M11-308", f"agentN:{s}") for s in ("enrol", "approve", "heartbeat", "inventory")]
         + [("CHK-M11-309", "agentN:scan"), ("CHK-M11-309", "sweep:b")],
    "upgrade": [("CHK-M11-304", "runner")] + [("CHK-M11-307", f"base:{s}") for s in ("enrol", "approve", "heartbeat", "inventory")]
               + [("CHK-M11-307", s) for s in ("manager:files", "manager:stop-install", "manager:units", "manager:migrate-start",
                                               "agentPrev:heartbeat-after", "agentPrev:inventory-after", "agent:upgrade-to-N", "scan:after")]
               + [("CHK-M11-309", "sweep:upgrade")],
}


def published_sums(path: Path) -> dict[str, str]:
    """name -> sha256 from the release page's SHA256SUMS text (a different origin than the files)."""
    out = {}
    for ln in path.read_text(encoding="utf-8", errors="replace").replace("\r", "").split("\n"):
        m = SUMS_LINE.match(ln.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def precheck(a: argparse.Namespace, sums: dict[str, str]) -> bool:
    facts, ok = [], True
    need = [PREV_DEB] if a.phase in ("a", "upgrade") else []
    if a.phase in ("b", "upgrade"):
        need += [f for f in sums if f.startswith("bitscan_manager-") or f.endswith("-requirements.txt")] + list(MANAGER_FILES)
    for f in need:
        got = n.sha256_file(a.prev / f)
        good = bool(sums.get(f)) and got == sums.get(f)
        facts.append(f"{f} {'OK' if good else 'MISMATCH or missing'}")
        ok &= good
    deb_sha = n.sha256_file(a.deb_n)
    side = a.deb_n.with_name(a.deb_n.name + ".sha256")
    pub = side.read_text().split()[0] if side.exists() else ""
    facts.append(f"N {a.deb_n.name} {'OK' if pub and pub == deb_sha else 'MISMATCH or missing'}")
    ok &= bool(pub) and pub == deb_sha
    kvm = Path("/dev/kvm").exists()
    facts.append(f"/dev/kvm {kvm}")
    ok &= kvm
    for rel, img in (("jammy", "jammy-server-cloudimg-amd64.img"), ("noble", "noble-server-cloudimg-amd64.img")):
        sums_file = a.images / f"{rel}.SHA256SUMS"
        lines = sums_file.read_text().split("\n") if sums_file.exists() else []
        want = next((ln.split()[0] for ln in lines if ln.endswith(img)), "")
        good = bool(want) and n.sha256_file(a.images / img) == want
        facts.append(f"{img} {'OK' if good else 'MISMATCH or missing'}")
        ok &= good
    mem = int(next(ln.split()[1] for ln in Path("/proc/meminfo").read_text().split("\n") if ln.startswith("MemAvailable:"))) // 1024
    facts.append(f"MemAvailable {mem} MB (need {1200 + a.guest_mem})")
    ok &= mem >= 1200 + a.guest_mem
    return n.row("CHK-M11-304", "runner", f"pre-check ({a.phase}): N−1 release files against the release page's sums, the N .deb, KVM, images, memory",
                 ok, "; ".join(facts))


def rel_prev(a: argparse.Namespace, sums: dict[str, str]) -> Path:
    """The release folder of manager N−1 as manager-install.md §2 has it: the six files and the
    SHA256SUMS text copied from the release page."""
    d = n.WORK / "relprev"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    for f in [f for f in sums if f.startswith("bitscan_manager-") or f.endswith("-requirements.txt")] + list(MANAGER_FILES):
        shutil.copy(a.prev / f, d / f)
    (d / "SHA256SUMS").write_text("".join(f"{h}  {f}\n" for f, h in sums.items()))
    return d


def with_deb(a: argparse.Namespace, deb: Path) -> argparse.Namespace:
    b = argparse.Namespace(**vars(a))
    b.deb = deb
    return b


def manager_up(a: argparse.Namespace, rel: Path) -> n.Api | None:
    b = argparse.Namespace(**vars(a))
    b.rel = rel
    return n.manager(b)


def ids(c: str) -> tuple[str, str, str, str]:
    return (c, c, c, c)


def agent_of(api: n.Api, aid: str) -> dict:
    st, body = api.json("GET", f"{n.V1}/agents/{aid}")
    return body if st == 200 and isinstance(body, dict) else {}


def scan_and_wait(api: n.Api, pid: int, aid: str, timeout: int = 900) -> tuple[str, dict, list]:
    st, body = api.json("POST", f"{n.V1}/scans", {"policy_id": pid, "target": {"agents": [aid]}},
                        headers={"Idempotency-Key": str(uuid.uuid4())})
    sid = str((body or {}).get("scan_id", "")) if isinstance(body, dict) else ""
    if not sid:
        return "", {"post": st, "body": body}, []

    def final() -> dict | None:
        s, d = api.json("GET", f"{n.V1}/scans/{sid}")
        if s in (404, 501):  # the scan was just created: the read route itself is missing (before TASK-244)
            return {"state": f"GET /scans/{{id}} answers {s}"}
        return d if s == 200 and isinstance(d, dict) and d.get("state") in ("completed", "partial", "failed", "cancelled") else None

    det = n.wait(final, timeout, 10) or {}
    _, page = api.json("GET", f"{n.V1}/scans/{sid}/results?limit=500")
    return sid, det, page.get("items", []) if isinstance(page, dict) else []


def scan_passes(api: n.Api, tree: Path, aid: str, chk: str, label: str, what: str) -> None:
    """Import the SR §1.1 example, scan the host and check the nightly pass condition: the scan
    completes, its one result is PASS with exit code 0, and the host scores 1.0 with no errors."""
    pid = n.import_sr(api, tree)
    if not pid:
        n.notrun(chk, f"{label}:scan", "scan", "the SR §1.1 example did not import")
        return
    sid, det, items = scan_and_wait(api, pid, aid)
    host = next((x for x in det.get("hosts", []) if x.get("agent_id") == aid), {})
    mine = [i for i in items if i.get("agent_id") == aid]
    ok = (det.get("state") == "completed" and len(mine) == 1 and mine[0].get("result") == "PASS" and mine[0].get("exit_code") == 0
          and host.get("errors") == 0 and host.get("score") == 1.0)
    n.row(chk, f"{label}:scan", what, ok,
          f"scan {sid or det}; state {det.get('state')}; host {json.dumps({k: host.get(k) for k in ('passed', 'failed', 'errors', 'not_run', 'score')})}; "
          f"results {json.dumps([{k: i.get(k) for k in ('plugin_uuid', 'result', 'eval_detail', 'exit_code')} for i in mine])}")


def phase_a(a: argparse.Namespace, api: n.Api, tok: dict[str, str]) -> None:
    up = n.boot_one(a, "u2204")
    if not up:
        for c, h in EXPECTED["a"][1:-1]:
            n.row(c, h, "chain", False, "guest u2204 did not boot")
        return
    aid = n.chain_host(api, "u2204", with_deb(a, a.prev / PREV_DEB), tok["u2204"], "", PREV_VERSION, ids("CHK-M11-305"), "agentPrev")
    if not aid:
        n.notrun("CHK-M11-306", "agentPrev:scan", "scan", "no agent (CHK-M11-305)")
        n.notrun("CHK-M11-306", "agentPrev:results", "results", "no agent (CHK-M11-305)")
        return
    pid = n.import_sr(api, a.tree)
    if not pid:
        n.notrun("CHK-M11-306", "agentPrev:scan", "scan", "the SR §1.1 example did not import")
        n.notrun("CHK-M11-306", "agentPrev:results", "results", "the SR §1.1 example did not import")
        return
    sid, det, items = scan_and_wait(api, pid, aid)
    n.row("CHK-M11-306", "agentPrev:scan", f"a scan of the {PREV_VERSION} host under manager N completes", bool(sid) and det.get("state") == "completed",
          f"scan {sid or det}; state {det.get('state')}")
    host = next((x for x in det.get("hosts", []) if x.get("agent_id") == aid), {})
    mine = [i for i in items if i.get("agent_id") == aid]
    ok = (len(mine) == 1 and mine[0].get("result") == "PASS" and mine[0].get("exit_code") == 0
          and host.get("errors") == 0 and host.get("score") == 1.0)
    n.row("CHK-M11-306", "agentPrev:results", "the check is PASS with exit code 0; score 1.0, no errors", ok,
          f"host {json.dumps({k: host.get(k) for k in ('passed', 'failed', 'errors', 'not_run', 'score')})}; "
          f"results {json.dumps([{k: i.get(k) for k in ('plugin_uuid', 'result', 'eval_detail', 'exit_code')} for i in mine])}")


def phase_b(a: argparse.Namespace, api: n.Api, tok: dict[str, str], n_version: str) -> None:
    up = n.boot_one(a, "u2404")
    if not up:
        for c, h in EXPECTED["b"][1:-1]:
            n.row(c, h, "chain", False, "guest u2404 did not boot")
        return
    rc, pin = n.mgr_sh("openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1")
    aid = n.chain_host(api, "u2404", with_deb(a, a.deb_n), tok["u2404"], pin.strip(), n_version, ids("CHK-M11-308"), "agentN")
    if not aid:
        n.notrun("CHK-M11-309", "agentN:scan", "scan", "no agent (CHK-M11-308)")
        return
    scan_passes(api, a.tree, aid, "CHK-M11-309", "agentN",
                "manager N−1 scans agent N: the scan completes, PASS with exit code 0, score 1.0, no errors")


def ops_blocks(tree: Path) -> dict[str, str]:
    """manager-operations.md §1 blocks, found by anchor (TASK-253 may rewrite the section)."""
    md = (tree / "deploy" / "runbooks" / "manager-operations.md").read_text(encoding="utf-8")
    sec = md.split("## 1. Upgrade", 1)[1].split("\n## 2.", 1)[0]
    bl = _blocks(sec)
    want = {"stop": "systemctl stop bitscan-manager", "units": "bitscan-manager-maintain.timer /etc/systemd/system/",
            "start": "systemctl start bitscan-manager-migrate"}
    out = {}
    for k, anchor in want.items():
        hits = [b for b in bl if anchor in b]
        out[k] = hits[0] if len(hits) == 1 else ""
    return out


def _blocks(md: str) -> list[str]:
    out: list[str] = []
    cur: list[str] | None = None
    for line in md.split("\n"):
        s = line.strip()
        if cur is None and re.fullmatch(r"```[a-z]*", s):
            cur = []
        elif cur is not None and s == "```":
            out.append(textwrap.dedent("\n".join(cur)))
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


def admin_sh(cmd: str, wd: str, timeout: int = 1500) -> tuple[int, str]:
    trap = "trap 'echo \"!! rc=$? at: $BASH_COMMAND\"' ERR\n"
    return n.run(["docker", "exec", "-i", "-u", "admin", "-w", wd, n.CT, "bash", "-o", "pipefail", "-c", trap + cmd], timeout=timeout)


RECORD_CHECK = """import base64, hashlib, os, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
rec = next(x for x in z.namelist() if x.endswith(".dist-info/RECORD"))
n = bad = 0
for line in z.read(rec).decode().splitlines():
    path, digest, _size = line.rsplit(",", 2)
    if not digest:
        continue
    algo, want = digest.split("=", 1)
    try:
        with open(os.path.join(sys.argv[2], path), "rb") as f:
            got = base64.urlsafe_b64encode(hashlib.new(algo, f.read()).digest()).rstrip(b"=").decode()
    except OSError:
        got = ""
    n += 1
    bad += got != want
print(f"checked {n} bad {bad}")
"""


def upgrade_manager(a: argparse.Namespace, rel: Path, wheel_version: str, chk: str, prefix: str, what: str) -> bool:
    """manager-operations.md §1 on the manager host with the files in `rel`: step 1 the files against
    SHA256SUMS, steps 2-4 its blocks (found by anchor; the example version and host name substituted).
    Rows `<prefix>:files`, `:stop-install`, `:units`, `:migrate-start`. True when all four pass."""
    d = f"/home/admin/rel-{prefix}"
    n.run(["docker", "exec", n.CT, "install", "-d", "-o", "admin", "-g", "admin", d])
    for f in rel.iterdir():
        n.run(["docker", "cp", str(f), f"{n.CT}:{d}/{f.name}"])
    n.run(["docker", "cp", str(n.WORK / "manager-ca.pem"), f"{n.CT}:{d}/manager-ca.pem"])
    n.run(["docker", "exec", n.CT, "chown", "-R", "admin:admin", d])
    rc, out = admin_sh("sha256sum -c --ignore-missing SHA256SUMS", d)
    oks = [n.row(chk, f"{prefix}:files", f"§1 step 1: {what} release files against SHA256SUMS", rc == 0 and out.count(": OK") == 6, out)]
    ob = ops_blocks(a.tree)

    def sub(b: str) -> str:
        return re.sub(r"0\.1\.1", wheel_version, b).replace("mgr.example", n.HOSTNAME)

    if not all(ob.values()):
        for h in ("stop-install", "units", "migrate-start"):
            n.row(chk, f"{prefix}:{h}", "manager-operations.md §1 block", False, f"block not found once: {[k for k, v in ob.items() if not v]}")
        return False
    rc, out = admin_sh(sub(ob["stop"]), d)
    oks.append(n.row(chk, f"{prefix}:stop-install", f"§1 step 2: stop, requirements, {what} wheel (--force-reinstall)",
                     rc == 0 and "!! rc=" not in out and "Successfully installed bitscan-manager" in out, out[-600:]))
    rc, out = admin_sh(sub(ob["units"]), d)
    oks.append(n.row(chk, f"{prefix}:units", "§1 step 3: the release's units, daemon-reload", rc == 0 and "!! rc=" not in out, out[-300:] or "(no output)"))
    rc, out = admin_sh(sub(ob["start"]), d)
    if not out.strip().endswith('{"status":"ok"}'):
        # evidence only (the row stays FAIL: the block's own loop decides): when did it become ready, if at all?
        _, late = n.mgr_sh("for i in $(seq 1 60); do curl -s --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/readyz "
                           "| grep -q '\"ok\"' && { echo \"ready after $i more s\"; break; }; sleep 1; done; systemctl is-active bitscan-manager; "
                           "journalctl -u bitscan-manager --no-pager -o cat | tail -n 15")
        out += "\n[after the block] " + late[-900:]
    # the installed code is told apart by its files (two wheels can share a version, PD-50): every file the
    # wheel's RECORD lists must be installed with that hash (pip rewrites the installed RECORD, so it is not compared)
    n.run(["docker", "exec", "-i", n.CT, "bash", "-c", "cat > /root/m11c-record.py"], stdin=RECORD_CHECK)
    _, rec = n.mgr_sh(f"python3.12 -I /root/m11c-record.py {d}/bitscan_manager-{wheel_version}-py3-none-any.whl "
                      "/opt/bitscan-manager/lib/python3.12/site-packages")
    m = re.search(r"checked (\d+) bad (\d+)", rec)
    same = bool(m) and int(m.group(1)) > 50 and m.group(2) == "0"
    oks.append(n.row(chk, f"{prefix}:migrate-start", f"§1 step 4: migrate, start, /readyz; the installed files are {what} wheel's",
                     rc == 0 and out.strip().endswith('{"status":"ok"}') and same,
                     f"{out[-1000:]} || wheel files installed with the wheel's hashes: {rec.strip()[-200:]}"))
    return all(oks)


def phase_upgrade(a: argparse.Namespace, api: n.Api, tok: dict[str, str], n_version: str, n_wheel_version: str) -> None:
    if not n.boot_one(a, "u2204"):
        for c, h in EXPECTED["upgrade"][1:-1]:
            n.row(c, h, "chain", False, "guest u2204 did not boot")
        return
    aid = n.chain_host(api, "u2204", with_deb(a, a.prev / PREV_DEB), tok["u2204"], "", PREV_VERSION, ids("CHK-M11-307"), "base")
    if not aid:
        for c, h in EXPECTED["upgrade"][5:-1]:
            n.notrun(c, h, "upgrade", f"no enrolled {PREV_VERSION} agent (base rows)")
        return
    before = agent_of(api, aid)
    upgrade_manager(a, a.rel, n_wheel_version, "CHK-M11-307", "manager", "the N")
    t_up = time.time()
    hb0 = before.get("last_heartbeat_at")
    got = n.wait(lambda: (lambda d: d if d.get("last_heartbeat_at") and d.get("last_heartbeat_at") != hb0 and d.get("status") == "online" else None)(agent_of(api, aid)), 420, 10)
    d = got or agent_of(api, aid)
    n.row("CHK-M11-307", "agentPrev:heartbeat-after", f"the {PREV_VERSION} agent keeps heartbeating to manager N (no re-enrolment)", bool(got) and d.get("agent_version") == PREV_VERSION,
          f"{time.time() - t_up:.0f} s after the start; last_heartbeat_at {hb0} -> {d.get('last_heartbeat_at')}; {d.get('status')} {d.get('agent_version')}")
    inv0 = d.get("last_inventory_at")
    probe = n.WORK / "probe"
    (probe / "DEBIAN").mkdir(parents=True, exist_ok=True)
    (probe / "DEBIAN" / "control").write_text("Package: bitscan-m11-probe\nVersion: 1.0\nArchitecture: all\nMaintainer: test <t@example.invalid>\n"
                                              "Description: M11 dpkg change probe\n")
    subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(probe), str(n.WORK / "probe.deb")], check=True, capture_output=True)
    n.guest(n.GUESTS["u2204"][0], "put", str(n.WORK / "probe.deb"), "/tmp/probe.deb")
    n.on("u2204", "sudo dpkg -i /tmp/probe.deb >/dev/null")
    got = n.wait(lambda: (lambda x: x if x.get("last_inventory_at") != inv0 else None)(agent_of(api, aid)), 420, 10)
    st, pk = api.json("GET", f"{n.V1}/agents/{aid}/packages?limit=500")
    names = {p.get("name") for p in (pk or {}).get("items", [])} if isinstance(pk, dict) else set()
    n.row("CHK-M11-307", "agentPrev:inventory-after", "inventory goes on: a dpkg change reaches manager N", bool(got) and "bitscan-m11-probe" in names,
          f"last_inventory_at {inv0} -> {(got or {}).get('last_inventory_at')}; probe listed {'bitscan-m11-probe' in names}")
    n.guest(n.GUESTS["u2204"][0], "put", str(a.deb_n), f"/tmp/{a.deb_n.name}")
    rc, out = n.on("u2204", f"cd /tmp && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./{shlex.quote(a.deb_n.name)} >/tmp/up.log 2>&1; echo rc=$?; "
                            "dpkg-query -W -f='${Version}\\n' bitscan-agent; sudo journalctl -u bitscan-agent -o cat --no-pager | grep 'bitscan-agent started' | tail -1")
    got = n.wait(lambda: agent_of(api, aid).get("agent_version") == n_version, 420, 10)
    n.row("CHK-M11-307", "agent:upgrade-to-N", "agent-install.md §6: apt install the N package; same agent id, version N on the manager",
          "rc=0" in out and n_version in out and bool(got), f"{out.strip()[-300:]}; manager agent_version {agent_of(api, aid).get('agent_version')}")
    pid = n.import_sr(api, a.tree)
    sid, det, items = scan_and_wait(api, pid, aid) if pid else ("", {}, [])
    mine = [i for i in items if i.get("agent_id") == aid]
    n.row("CHK-M11-307", "scan:after", "a scan completes after the upgrades: PASS, exit 0", det.get("state") == "completed"
          and len(mine) == 1 and mine[0].get("result") == "PASS" and mine[0].get("exit_code") == 0,
          f"scan {sid}; state {det.get('state')}; results {json.dumps([{k: i.get(k) for k in ('result', 'exit_code', 'eval_detail')} for i in mine])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=sorted(EXPECTED))
    for k in ("--tree", "--rel", "--deb-n", "--prev", "--prev-sums", "--images", "--work"):
        ap.add_argument(k, required=True, type=Path)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--guest-mem", type=int, default=1024)
    ap.add_argument("--expect-red")
    ap.add_argument("--plant-rel", type=Path, help="plants: a release folder of a planted manager tree, installed by "
                                                   "manager-operations.md §1 onto the walked manager N before the guests")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    a.tree, a.rel, a.deb_n, a.prev, a.images = (p.resolve() for p in (a.tree, a.rel, a.deb_n, a.prev, a.images))
    n.WORK = a.work
    n.CT = f"m11c-{a.phase}"
    n.EXPECTED[:] = EXPECTED[a.phase]
    a.work.mkdir(parents=True, exist_ok=True)
    a.work.chmod(0o700)
    (a.work / "secrets").mkdir(mode=0o700, exist_ok=True)
    (a.work / "rows.jsonl").write_text("")
    os.environ.setdefault("GUESTS_DIR", str(a.work / "guests"))
    sums = published_sums(a.prev_sums)
    n_version = a.deb_n.name.split("_")[1]
    wheel = next(a.rel.glob("bitscan_manager-*-py3-none-any.whl"), None)
    n_wheel_version = wheel.name.split("-")[1] if wheel else "?"
    try:
        if not precheck(a, sums):
            for c, h in EXPECTED[a.phase][1:]:
                n.notrun(c, h, "chain", "the pre-check failed (CHK-M11-304)")
            return n.report(a.expect_red)
        rel = rel_prev(a, sums) if a.phase in ("b", "upgrade") else a.rel
        api = manager_up(a, rel)
        if api is None:
            for c, h in EXPECTED[a.phase][1:]:
                n.notrun(c, h, "chain", f"no manager host ({'N−1' if a.phase != 'a' else 'N'})")
            return n.report(a.expect_red)
        if a.plant_rel:  # a planted manager tree, deployed onto the walked host the way an upgrade is
            if not upgrade_manager(a, a.plant_rel.resolve(), n_wheel_version, "CHK-M11-372", "plant", "the planted"):
                for c, h in EXPECTED[a.phase][1:]:
                    n.notrun(c, h, "chain", "the planted manager tree did not install (CHK-M11-372 plant rows)")
                return n.report(a.expect_red)
        tok = n.tokens(api)
        {"a": lambda: phase_a(a, api, tok), "b": lambda: phase_b(a, api, tok, n_version),
         "upgrade": lambda: phase_upgrade(a, api, tok, n_version, n_wheel_version)}[a.phase]()
        n.sweep(a, label=f"sweep:{a.phase}", chk="CHK-M11-309", hosts=["u2204"] if a.phase in ("a", "upgrade") else ["u2404"])
    except Exception as exc:  # recorded, then the run fails
        n.row("CHK-M11-304", "harness", "no harness exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        if not a.keep:
            for name, *_r in n.GUESTS.values():
                n.guest(name, "down")
            n.run(["docker", "rm", "-f", n.CT])
            shutil.rmtree(a.work / "walk" / "secrets", ignore_errors=True)  # the walk's test passwords, host gone
        shutil.rmtree(a.work / "secrets", ignore_errors=True)
    return n.report(a.expect_red)


if __name__ == "__main__":
    sys.exit(main())
