"""CHK-M4-264 (TP-M4-21; REQ-103, TS §3.7): bitscan-agent from the .deb under
the verbatim bitscan-agent.service (user bitscan, ProtectSystem=strict) on a
clean Ubuntu systemd container, against the real M3 manager (`serve` from this
tree, PostgreSQL 16, HTTPS from a private CA in ca_file; fake OpenBao and audit
sink from manager/tests), set up as in e2e/runbook_walk.py.

Checks: enrols (approved), heartbeats, uploads inventory for the inventory job;
a `find / -xdev -newer <marker>` sweep of writable paths shows changes only
under /var/lib/bitscan-agent; `ss -ltnup` shows no socket owned by the agent;
CapEff 0; NoNewPrivs 1; the unit on the host is byte-identical to
deploy/systemd; the journal holds the start line with the build version and no
bse_/bsa_ token.

Run (WSL, root, Docker, the manager venv):
  PYTHONPATH=<copy>/manager python <copy>/e2e/agent_unit_walk.py --deb DIR --out FILE.jsonl [--image m4b-sysd-u24]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import runbook_walk as w  # same folder
from runbook_walk import V1, Host, Manager, row
from tests.certs import make_pki
from tests.conftest import own_migrated_server
from tests.fake_sink import https_sink, server_context
from tests.fake_vault import fake_vault
from tests.test_serve_linux import CANARY_VAULT, env_for, free_port, start, wait_ready

UNIT = Path(__file__).resolve().parents[1] / "deploy" / "systemd" / "bitscan-agent.service"

# Paths the sweep ignores: kernel and systemd runtime state, the journal,
# apt/dpkg's own bookkeeping of the install (the sweep starts after it), and
# the test's own marker.
SWEEP = (
    "find / -xdev \\( -path /proc -o -path /sys -o -path /run/systemd"
    " -o -path /var/log/journal -o -path /run/log -o -path /dev \\) -prune -o -newer /root/m4b.marker -print 2>/dev/null"
    " | grep -v -x -e /root/m4b.marker | sort"
)


def run(deb_dir: Path, image: str, label: str, work: Path) -> None:
    deb = next(deb_dir.glob("bitscan-agent_*_amd64.deb"))
    version = deb.name.split("_")[1]
    pki = make_pki(work / "pki")
    sink_leaf, vault_leaf = pki.leaf("sink"), pki.leaf("vault")
    mgr_leaf = pki.leaf("mgr", sans="DNS:mgr.example,DNS:localhost,IP:127.0.0.1")
    creds = work / "pgcreds"
    creds.mkdir()
    with (
        own_migrated_server(creds) as pg,
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as vault,
    ):
        port = free_port()
        env = env_for(pg, work, pki, mgr_leaf, f"https://localhost:{sink.port}/audit", port,
                      BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{vault.port}", BITSCAN_LISTEN=f"0.0.0.0:{port}")
        serve = start(env, work, port, pki, mgr_leaf)
        try:
            wait_ready(serve)
            m = Manager(port, pki.ca)
            w.admin_session(m, work)
            check(m, pki, deb, version, port, image, label)
        finally:
            if serve.proc.poll() is None:
                serve.stop()


def check(m: Manager, pki: object, deb: Path, version: str, port: int, image: str, label: str) -> None:  # noqa: PLR0915
    url = f"https://mgr.example:{port}"
    h = Host(f"unit-{label}", image)
    try:
        h.put(deb, f"/root/{deb.name}")
        h.put(pki.ca, "/root/manager-ca.pem")  # type: ignore[attr-defined]
        os_line = h.sh(". /etc/os-release; echo $PRETTY_NAME; systemctl --version | head -1")[1].strip().replace("\n", "; ")
        row("264", "host", "-", "a clean Ubuntu systemd container", f"{image}: {os_line}", True)
        # iproute2 (ss, and ip for the agent's ip -j addr source) is on every
        # stock Ubuntu server, but not in the minimal test image
        rc, out = h.sh("command -v ss >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iproute2; } >/dev/null 2>&1;"
                       " command -v ss ip | tr '\\n' ' '")
        row("264", "iproute2 present (ss, ip)", "apt-get install iproute2 (if missing)", "/usr/bin/ss and ip found", out.strip(),
            "/ss" in out and "/ip" in out)
        tok = m.enrol_token()
        rc, out = h.sh(
            "cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem"
            f" && printf 'bitscan-agent bitscan/manager_url string {url}\\nbitscan-agent bitscan/enrol_token password {tok}\\n"
            "bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\\n' | debconf-set-selections"
            f" && apt-get install -y ./{deb.name} </dev/null >/root/install.log 2>&1; echo rc=$?")
        row("264", "installed from the .deb with the CA in ca_file", f"apt-get install ./{deb.name}", "rc=0", out.strip(), out.strip() == "rc=0")
        # the sweep starts after the install, before the agent's own work
        h.sh("systemctl stop bitscan-agent.service; sleep 1; touch /root/m4b.marker; sleep 1.1")
        unit_host = h.sh("cat /lib/systemd/system/bitscan-agent.service")[1]
        row("264", "the unit on the host is byte-identical to deploy/systemd/bitscan-agent.service", "cat; compare",
            "identical", "identical" if unit_host == UNIT.read_text() else "differs", unit_host == UNIT.read_text())
        rc, out = h.sh("systemctl start bitscan-agent.service; sleep 2; systemctl is-active bitscan-agent.service; "
                       "systemctl show -p User -p ProtectSystem -p MainPID --value bitscan-agent.service | tr '\\n' ' '")
        row("264", "the agent runs under the unit as bitscan with ProtectSystem=strict", "systemctl start; show",
            "active; User bitscan; ProtectSystem strict", out.strip().replace("\n", " "),
            out.startswith("active") and "bitscan" in out and "strict" in out)
        req = m.request_for(h.hostname)
        st, _ = m.call("POST", f"{V1}/enrollment-requests/{req['request_id']}/approve") if req else (0, None)
        row("264", "enrols (held, approved)", "GET /enrollment-requests; approve", "kind new; 200",
            json.dumps({"kind": req.get("kind") if req else None, "approve": st}), bool(req) and req.get("kind") == "new" and st == 200)
        w.wait(lambda: "agent_id" in h.sh("ls /var/lib/bitscan-agent")[1], 120, 2)
        agent_id = h.sh("cat /var/lib/bitscan-agent/agent_id")[1].strip()
        detail = w.wait(lambda: (lambda d: d if d.get("last_snapshot") and d.get("last_heartbeat_at") else None)(m.agent(agent_id)), 420, 5) or m.agent(agent_id)
        snap = detail.get("last_snapshot") or {}
        row("264", "heartbeats and uploads inventory for its inventory job", "GET /agents/{id}",
            "status online, last_heartbeat_at, last_snapshot with the host's package count",
            json.dumps({"status": detail.get("status"), "hb": detail.get("last_heartbeat_at"), "packages": snap.get("package_count"),
                        "dpkg": h.sh("dpkg-query -W | wc -l")[1].strip()}),
            detail.get("status") == "online" and bool(snap.get("package_count"))
            and str(snap.get("package_count")) == h.sh("dpkg-query -W | wc -l")[1].strip())
        pid = h.sh("systemctl show -p MainPID --value bitscan-agent.service")[1].strip()
        status = h.sh(f"grep -E '^(Uid|Gid|CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs|Seccomp):' /proc/{pid}/status")[1]
        caps = dict(re.findall(r"^(\w+):\s+(.*)$", status, re.M))
        uid = h.sh("id -u bitscan")[1].strip()
        row("264", "no capabilities; NoNewPrivs; runs as bitscan", f"/proc/{pid}/status",
            "CapEff/CapPrm/CapAmb/CapBnd 0; NoNewPrivs 1; Uid bitscan; Seccomp 2",
            json.dumps(caps), caps.get("CapEff") == "0000000000000000" and caps.get("CapPrm") == "0000000000000000"
            and caps.get("CapAmb") == "0000000000000000" and caps.get("CapBnd") == "0000000000000000"
            and caps.get("NoNewPrivs") == "1" and caps.get("Uid", "").split()[:1] == [uid] and caps.get("Seccomp") == "2")
        rc_ss, ss = h.sh("ss -ltnupH")
        have_ss = h.sh("command -v ss")[0] == 0
        mine = [ln for ln in ss.splitlines() if f"pid={pid}," in ln or "bitscan-agent" in ln]
        row("264", "no listening socket owned by the agent (ss)", "ss -ltnup", "ss present (rc 0); no line for bitscan-agent",
            f"ss rc={rc_ss}; all listening: {[' '.join(ln.split()) for ln in ss.splitlines()]}; agent's: {mine}",
            have_ss and rc_ss == 0 and not mine)
        # independent of ss's process column: LISTEN (TCP state 0A) and bound
        # UDP sockets in the agent's own network view, matched by inode
        # against the agent's open fds
        script = (
            f"fds=$(ls -l /proc/{pid}/fd 2>/dev/null | grep -o 'socket:\\[[0-9]*\\]' | tr -dc '0-9\\n' | sort -u);"
            f" for f in tcp tcp6; do awk 'NR>1 && $4==\"0A\" {{print $10}}' /proc/{pid}/net/$f; done | sort -u > /dev/shm/m4b.l;"
            f" for f in udp udp6; do awk 'NR>1 {{print $10}}' /proc/{pid}/net/$f; done | sort -u >> /dev/shm/m4b.l;"
            " echo \"$fds\" | grep -x -F -f /dev/shm/m4b.l | grep -v '^$' | tr '\\n' ' '; echo; echo \"fds=$(echo $fds | wc -w)\""
        )
        out = h.sh(script)[1].strip().splitlines()
        owned = out[0].split() if out and not out[0].startswith("fds=") else []
        row("264", "no listening TCP or bound UDP socket among the agent's fds (/proc inode match)", f"/proc/{pid}/net/tcp,tcp6,udp,udp6 vs /proc/{pid}/fd",
            "no inode in common", f"inodes owned and listening: {owned}; {out[-1] if out else ''}", not owned)
        conns = h.sh("ss -tnpH")[1]
        row("264", "(observation) the agent's own connections are outbound to the manager", "ss -tnp", "recorded",
            " | ".join(ln.split()[3] + "->" + ln.split()[4] for ln in conns.splitlines() if f"pid={pid}," in ln) or "none open now", True)
        changed = h.sh(SWEEP)[1].split()
        state = [p for p in changed if p == "/var/lib/bitscan-agent" or p.startswith("/var/lib/bitscan-agent/")]
        # PrivateTmp=yes (verbatim unit): systemd (PID 1, root) makes
        # /tmp/systemd-private-<boot>-<unit>-X/tmp and the same under /var/tmp
        # for this unit, and for systemd-hostnamed, which the agent's
        # hostnamectl call (a TS 3.4 source) starts. Allowed only as those
        # roots, root-owned, with an empty inner tmp: the agent wrote nothing.
        priv_re = re.compile(r"^/(var/)?tmp/systemd-private-[0-9a-f]{32}-(bitscan-agent|systemd-hostnamed)\.service-[A-Za-z0-9]+(/tmp)?$")
        priv = [p for p in changed if priv_re.match(p)]
        rest = [p for p in changed if p not in state and p not in priv and p not in ("/tmp", "/var/tmp")]
        inner = sorted({re.sub(r"/tmp$", "", p) + "/tmp" for p in priv})
        detail_priv = h.sh("for d in " + " ".join(inner) + "; do printf '%s %s entries=%s\\n' \"$d\" \"$(stat -c '%U:%G %a' $d)\" \"$(ls -A $d | wc -l)\"; done")[1].strip() if inner else ""
        priv_ok = all(" root:root 1777 entries=0" in ln for ln in detail_priv.splitlines()) if inner else True
        row("264", "files changed only under /var/lib/bitscan-agent (systemd's own PrivateTmp roots aside, which must stay empty)",
            "find / -xdev -newer marker (excluding /proc, /sys, /run/systemd, journal, /dev)",
            "state dir changes only; any systemd-private-* tmp root:root 1777 and empty; nothing else",
            f"state {state}; other {rest}; private tmp: {detail_priv.replace(chr(10), ' | ')}",
            not rest and bool(state) and priv_ok)
        j = h.sh("journalctl -u bitscan-agent --no-pager -o cat")[1]
        start_lines = [ln for ln in j.splitlines() if "bitscan-agent started" in ln]
        row("264", "the start line carries the build version", "journalctl -u bitscan-agent",
            f"'bitscan-agent started' with version={version}", start_lines[-1][:200] if start_lines else "none",
            any(f"version={version}" in ln for ln in start_lines))
        leaked = re.findall(r"bs[ae]_[A-Za-z0-9_-]{20,}", j) + [t for t in w.SECRETS if t in j]
        row("264", "no bse_/bsa_ token in the journal", "journalctl -u bitscan-agent", "none", str(len(leaked)), not leaked)
    finally:
        h.remove()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--image", default="m4b-sysd-u24")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="m4b-unit."))
    label = args.image.rsplit("-", 1)[-1] + str(int(time.time()) % 10000)
    try:
        run(args.deb, args.image, label, work)
    except Exception as exc:  # recorded, then the run fails
        row("harness", "run aborted", "-", "no exception", f"{type(exc).__name__}: {exc}", False)
    finally:
        args.out.write_text("".join(json.dumps(r.__dict__) + "\n" for r in w.ROWS))
        shutil.rmtree(work, ignore_errors=True)
    bad = [r for r in w.ROWS if not r.ok]
    print(f"{'OK' if not bad else 'FAIL'} {len(w.ROWS) - len(bad)}/{len(w.ROWS)} checks", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
