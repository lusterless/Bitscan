"""Operations walk, upgrade (TP-M6-04 CHK-M6-080, TASK-134; REQ-139 (1)), on the walked host.

Runs in WSL as root after manager_walk.py --keep:
  python3 -I e2e/m6/ops_upgrade.py --tree TREE --work WORK --deb DEB

An agent container (`m6b-agent`, image m4b-sysd-u24, on the host's network
m6b-net, no published port) installs the release .deb with a preseed (manager
URL https://bitscan-mgr.test:8443, ca_file the test CA, a single-use bse_ made
with the TOTP session), is approved and heartbeats. Then the upgrade section of
deploy/runbooks/manager-operations.md runs verbatim as `admin`, with the same
release files as the degenerate upgrade (the example `0.1.1` -> `0.1.0`; the
§1 step 1 check is install §2's block). Afterwards: migrate head unchanged,
a new manager PID, /readyz ok, and the agent heartbeats again with the same
agent_id and token, with no new enrolment request. Rows go to
WORK/out/ops-upgrade.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manager_walk as mw  # noqa: E402

AG = "m6b-agent"
CA = f"{mw.REL}/manager-ca.pem"
SESS = ["--url", mw.URL, "--ca", CA, "--state", "/home/admin/stage/session.json"]


def ag(cmd: str, stdin: str | None = None, timeout: int = 600) -> tuple[int, str]:
    return mw.run(["docker", "exec", "-i", AG, "bash", "-c", cmd], stdin, timeout)


def api_json(*args: str) -> tuple[int, object]:
    rc, out = mw.sh("python3.12 -I /opt/m6b/mgr_api.py call " + " ".join(SESS) + " " + " ".join(args), wd="/home/admin")
    m = re.match(r"(\d{3}) (.*)", out.strip(), re.S)
    if not m:
        return 0, out
    try:
        return int(m.group(1)), json.loads(m.group(2))
    except ValueError:
        return int(m.group(1)), m.group(2)


def agent(aid: str) -> dict:
    st, out = api_json("GET", f"/api/v1/agents/{aid}")
    return out if st == 200 and isinstance(out, dict) else {}


def wait(pred, timeout: float, every: float = 5):  # type: ignore[no-untyped-def]
    end = time.time() + timeout
    while True:
        v = pred()
        if v or time.time() > end:
            return v
        time.sleep(every)


def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--deb", required=True, type=Path)
    a = ap.parse_args()
    mw.OUT = a.work / "out"
    (mw.OUT / "walk.jsonl").write_text("")

    # enrolment token and the agent host
    rc, out = mw.sh("python3.12 -I /opt/m6b/mgr_api.py call " + " ".join(SESS) + " --save-token /home/admin/stage/bse-ag POST /api/v1/enrollment-tokens --body '{\"max_uses\": 1, \"expires_in_hours\": 24}'", wd="/home/admin")
    bse = mw.root("cat /home/admin/stage/bse-ag")[1].strip()
    mw.SECRET_VALUES.append(bse)
    mw.row("CHK-M6-080", "single-use bse_ created with the TOTP session", "201", out, out.startswith("201") and bse.startswith("bse_"))
    mw.run(["docker", "rm", "-f", AG])
    rc, out = mw.run(["docker", "create", "--name", AG, "--hostname", AG, "--privileged", "--cgroupns=private", "--tmpfs", "/run", "--tmpfs", "/run/lock",
                      "--network", mw.NET, "--memory", "512m", "m4b-sysd-u24"])
    d = a.work / "agent-mid"
    d.mkdir(exist_ok=True)
    (d / "machine-id").write_text(secrets.token_hex(16) + "\n")
    mw.run(["docker", "cp", str(d / "machine-id"), f"{AG}:/etc/machine-id"])
    mw.run(["docker", "start", AG])
    wait(lambda: ag("systemctl is-system-running")[1].strip() in ("running", "degraded"), 60, 1)
    mw.run(["docker", "cp", str(a.deb), f"{AG}:/root/{a.deb.name}"])
    mw.run(["docker", "cp", str(a.work / "pki" / "ca.pem"), f"{AG}:/root/manager-ca.pem"])
    preseed = (f"bitscan-agent bitscan/manager_url string {mw.URL}\n"
               f"bitscan-agent bitscan/enrol_token password {bse}\n"
               "bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\n")
    rc, out = ag("install -d -m 0755 /etc/bitscan && install -m 0644 /root/manager-ca.pem /etc/bitscan/ca.pem && debconf-set-selections && cd /root && "
                 f"apt-get install -y ./{a.deb.name} </dev/null >/root/apt.log 2>&1; echo rc=$?; dpkg-query -W -f='${{Version}} ${{Status}}' bitscan-agent; echo; systemctl is-active bitscan-agent", stdin=preseed)
    mw.row("CHK-M6-080", "agent 0.1.0-1 installed with a preseed on the agent host", "rc=0, install ok installed, active", out, out.startswith("rc=0") and "install ok installed" in out and out.strip().endswith("active"))

    def pending():  # type: ignore[no-untyped-def]
        st, out = api_json("GET", "'/api/v1/enrollment-requests?state=pending&limit=50'")
        items = out.get("items", []) if isinstance(out, dict) else []
        return next((r for r in items if r.get("hostname") == AG), None)

    req = wait(pending, 180)
    st, out = api_json("POST", f"/api/v1/enrollment-requests/{req['request_id'] if req else 0}/approve")
    aid = ag("cat /var/lib/bitscan-agent/agent_id")[1].strip()
    mw.row("CHK-M6-080", "held enrolment approved with the TOTP session", "200", f"{st} request {req and req.get('request_id')} agent {aid}", st == 200 and bool(aid))
    hb0 = wait(lambda: (lambda d: d if d.get("status") == "online" and d.get("last_heartbeat_at") else None)(agent(aid)), 420)
    mw.row("CHK-M6-080", "agent online and heartbeating before the upgrade", "online, last_heartbeat_at set", json.dumps({k: (hb0 or {}).get(k) for k in ("status", "last_heartbeat_at", "agent_version")}), bool(hb0))
    tok0 = ag("sha256sum /var/lib/bitscan-agent/token /var/lib/bitscan-agent/agent_id /etc/bitscan/agent.yaml")[1]
    st, reqs0 = api_json("GET", "'/api/v1/enrollment-requests?limit=100'")
    n_req0 = len(reqs0.get("items", [])) if isinstance(reqs0, dict) else -1
    pid0 = mw.root("systemctl show -p MainPID --value bitscan-manager")[1].strip()
    head0 = mw.root("sudo -u postgres psql -X -At -d bitscan -c 'select version_num from alembic_version'")[1].strip()

    # the upgrade section, verbatim (degenerate upgrade: the same 0.1.0 files)
    md = (a.tree / "deploy/runbooks/manager-operations.md").read_text()
    b1 = [textwrap.dedent(body) for sec, lang, body in mw.blocks(md) if sec == "1" and lang == "sh"]
    inst = [body for sec, lang, body in mw.blocks((a.tree / "deploy/runbooks/manager-install.md").read_text()) if sec == "2" and lang == "sh"][0]
    rc, out = mw.sh(inst)
    mw.row("CHK-M6-080", "upgrade step 1: release files checked as in install §2", "OK x6", out, rc == 0 and out.count(": OK") == 6)
    t_stop = time.time()
    rc, out = mw.sh(b1[0].replace("0.1.1", "0.1.0"), timeout=900)
    mw.row("CHK-M6-080", "upgrade step 2 as written: stop, hashed lock, wheel --force-reinstall", "rc 0; the wheel reinstalled", f"rc {rc}; {out[-400:]}",
           rc == 0 and "Successfully installed bitscan-manager-0.1.0" in out)
    rc, out = mw.sh(b1[1])
    mw.row("CHK-M6-080", "upgrade step 3 as written: units installed, daemon-reload", "rc 0", f"rc {rc}; {out}", rc == 0)
    rc, out = mw.sh(mw.sub(b1[2]))
    mw.row("CHK-M6-080", "upgrade step 4 block run as written (migrate, journal, start, curl /readyz)", "rc 0; head in the journal; {\"status\":\"ok\"}", f"rc {rc}; {out[-700:]}",
           rc == 0 and out.strip().endswith('{"status":"ok"}'))
    ready = wait(lambda: mw.sh("curl -s --cacert manager-ca.pem https://bitscan-mgr.test:8443/readyz")[1] == '{"status":"ok"}', 30, 1)
    t_up = time.time()
    pid1 = mw.root("systemctl show -p MainPID --value bitscan-manager")[1].strip()
    head1 = mw.root("sudo -u postgres psql -X -At -d bitscan -c 'select version_num from alembic_version'")[1].strip()
    mj = mw.root("journalctl -u bitscan-manager-migrate --no-pager -o cat | grep -vE '^(Starting |Finished |bitscan-manager-migrate.service: )' | tail -1")[1].strip()
    mw.row("CHK-M6-080", "after the upgrade: head unchanged, new PID, /readyz ok", f"head {head0} = {head1} = migrate log; PID changed; ready",
           f"head {head0} -> {head1}, migrate log {mj}; PID {pid0} -> {pid1}; ready {bool(ready)}; down {t_up - t_stop:.0f} s",
           head0 == head1 == mj and pid0 != pid1 and bool(ready))

    hb_before = (hb0 or {}).get("last_heartbeat_at")
    hb1 = wait(lambda: (lambda d: d if d.get("last_heartbeat_at") and d.get("last_heartbeat_at") > hb_before and d.get("status") == "online" else None)(agent(aid)), 420)
    tok1 = ag("sha256sum /var/lib/bitscan-agent/token /var/lib/bitscan-agent/agent_id /etc/bitscan/agent.yaml")[1]
    st, reqs1 = api_json("GET", "'/api/v1/enrollment-requests?limit=100'")
    n_req1 = len(reqs1.get("items", [])) if isinstance(reqs1, dict) else -1
    jr = ag("journalctl -u bitscan-agent --no-pager -o cat | grep -ci 're-enrol'; systemctl show -p NRestarts --value bitscan-agent")[1].split()
    mw.row("CHK-M6-080", "the enrolled agent keeps heartbeating without re-enrolment", "a later heartbeat, same agent_id/token/agent.yaml, no new enrolment request, no re-enrol line, NRestarts 0",
           json.dumps({"hb": [hb_before, (hb1 or {}).get("last_heartbeat_at")], "same_files": tok0 == tok1, "requests": [n_req0, n_req1], "journal_reenrol_lines_and_nrestarts": jr,
                       "after_upgrade_s": round(time.time() - t_up)}),
           bool(hb1) and tok0 == tok1 and n_req0 == n_req1 and jr[:2] == ["0", "0"])
    leaks = ag("journalctl --no-pager -o cat | grep -Eo 'bs[ae]_[A-Za-z0-9_-]{20,}' | head -2")[1].strip()
    mw.row("CHK-M6-080", "no bsa_/bse_ in the agent host's journal", "none", leaks or "none", not leaks)

    rows = [json.loads(x) for x in (mw.OUT / "walk.jsonl").read_text().splitlines() if x.strip()]
    (mw.OUT / "ops-upgrade.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    bad = [r for r in rows if not r["ok"]]
    print(f"ops_upgrade rows: {len(rows) - len(bad)}/{len(rows)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
