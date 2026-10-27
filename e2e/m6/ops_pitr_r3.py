"""TASK-134 r3 re-test of O2 (TP-M6-04 CHK-M6-087-r3) on the walked host.

Runs in WSL as root after ops_pitr_o2.py (the host is left with cursor > max(audit_id)):
  python3 -I e2e/m6/ops_pitr_r3.py --tree TREE --work WORK [--after N]

A. The r3 PITR step 4 block as written, manager stopped, on the O2-damaged host;
   then the manager starts and a new entry must ship above the old cursor.
B. GREATEST never moves the sequence back: with the manager stopped, state.json
   is set to a cursor below max(audit_id), the block runs, the sequence must
   stay at max(audit_id); state.json is restored.
C. The CHK-M6-087 scenario again with r3 as written: base backup, target, N
   audited changes after it, PITR steps 1-5; the first new ids must be above
   the old cursor, reach the sink, and move the cursor.
D. The audit chain verifier (services.audit.verify.verify_chain) passes over the
   whole log, across the id gap.
If the block fails only because `python3` is missing on the host (the runbook
installs python3.12), that is recorded as its own row and the rest runs with
`python3` -> `python3.12`, recorded as a substitution.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manager_walk as mw  # noqa: E402
from ops_backup import psql  # noqa: E402
from ops_pitr_o2 import cursor, patch, ready, sink_ids  # noqa: E402

C = "CHK-M6-087-r3"


def seq() -> int:
    return int(psql("select last_value from audit_log_audit_id_seq"))


def maxid() -> int:
    return int(psql("select max(audit_id) from audit_log"))


def verify() -> str:
    code = ("import psycopg; from bitscan_manager.services.audit.verify import verify_chain; "
            "c = psycopg.connect(open('/etc/bitscan/secrets/app.dsn').read().strip(), autocommit=True); "
            "r = verify_chain(c); print(r.ok, r.checked, r.first_bad_id, r.reason)")
    return mw.root(f"/opt/bitscan-manager/bin/python -I -c \"{code}\"")[1].strip()


def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--after", type=int, default=45)
    ap.add_argument("--parts", default="A,B,E,C,D")
    ap.add_argument("--label", default="CHK-M6-087-r3")
    a = ap.parse_args()
    global C  # noqa: PLW0603
    C = a.label
    parts = set(a.parts.split(","))
    mw.OUT = a.work / "out"
    (mw.OUT / "walk.jsonl").write_text("")
    md = (a.tree / "deploy/runbooks/manager-operations.md").read_text()
    sec4 = [(lang, textwrap.dedent(body)) for sec, lang, body in mw.blocks(md) if sec == "4"]
    step4 = [b for lang, b in sec4 if lang == "sh" and "audit_log_audit_id_seq" in b]
    mw.row(C, "r3: the PITR step 4 block (sequence past the cursor) exists", "one sh block", f"{len(step4)} block(s)", len(step4) == 1)
    block = step4[0]
    day = mw.root("date -u +%F")[1].strip()
    B = sec4

    # A. cursor ahead of the database (the O2 state; made by hand if the host is not in it)
    mw.root("systemctl stop bitscan-manager")
    made = ""
    if "A" in parts and cursor() <= maxid():
        ahead = maxid() + 20
        mw.root("python3.12 -I -c \"import json; p='/var/lib/bitscan/audit-queue/state.json'; d=json.load(open(p)); d['cursor']=%d; json.dump(d, open(p,'w'))\"" % ahead)
        made = f" (cursor set to {ahead} by hand, as a PITR leaves it)"
    c0, m0, s0 = cursor(), maxid(), seq()
    rc, out = mw.sh(block) if "A" in parts else (0, "")
    subst = ""
    if rc != 0 and "python3: command not found" in out:
        mw.row(C, "A. step 4 block as written on the walked host", "rc 0", f"rc {rc}; {out}  (the host has python3.12 from install §3 but no python3)", False)
        block = block.replace("sudo python3 -I", "sudo python3.12 -I")
        subst = " [python3 -> python3.12]"
        rc, out = mw.sh(block)
    s1 = seq()
    mw.row(C, f"A. step 4 block{subst}, manager stopped, cursor {c0} > max id {m0}{made}", f"rc 0; sequence {c0} (psql prints the value)", f"rc {rc}; [{out.strip()}]; sequence {s0} -> {s1}",
           rc == 0 and s1 == max(c0, m0) and str(max(c0, m0)) in out)
    mw.root("systemctl start bitscan-manager")
    up = ready()
    n0 = len(sink_ids())
    patch(305)
    time.sleep(8)
    new = maxid()
    got = sink_ids()[n0:]
    mw.row(C, "A. the next audit entry ships above the old cursor", f"id > {c0}; in the sink; cursor = id", f"ready {up}; new id {new}; sink got {got}; cursor {cursor()}",
           up and new > c0 and new in got and cursor() == new)

    # B. GREATEST never moves the sequence back
    if "B" in parts:
      mw.root("systemctl stop bitscan-manager && cp -a /var/lib/bitscan/audit-queue/state.json /root/state.json.m6b && "
            "python3.12 -I -c \"import json; p='/var/lib/bitscan/audit-queue/state.json'; d=json.load(open(p)); d['cursor']=10; json.dump(d, open(p,'w'))\"")
      m1, s2 = maxid(), seq()
      rc, out = mw.sh(block)
      s3 = seq()
      mw.root("cp -a /root/state.json.m6b /var/lib/bitscan/audit-queue/state.json && rm -f /root/state.json.m6b && systemctl start bitscan-manager")
      up = ready()
      mw.row(C, "B. cursor (10) below max(audit_id): the block leaves the sequence at max(audit_id), never lower", f"sequence stays {s2} (>= max id {m1})",
             f"rc {rc}; [{out.strip()}]; sequence {s2} -> {s3}; state.json restored, cursor {cursor()}; ready {up}", rc == 0 and s3 == s2 and s3 >= m1 and up)

    # E. state.json missing: the text says skip the step; what does the block do if run anyway?
    mw.root("systemctl stop bitscan-manager && mv /var/lib/bitscan/audit-queue/state.json /root/state.json.m6b")
    s5 = seq()
    rc, out = mw.sh(block)
    s6 = seq()
    mw.root("mv /root/state.json.m6b /var/lib/bitscan/audit-queue/state.json && systemctl start bitscan-manager")
    up = ready()
    reached = "invalid input syntax" in out or "setval" in out.lower()
    mw.row(C, "E. state.json missing, the block run as written", "rc 0; the block skips: psql not reached, sequence unchanged",
           f"rc {rc}; psql reached with an empty cursor: {reached}; output [{out.strip()[-400:]}]; sequence {s5} -> {s6}; ready {up}", rc == 0 and not reached and s6 == s5 and up)

    # C. the CHK-M6-087 scenario with r3 as written
    mw.root(f"cd /var/backups/bitscan && for f in base-{day}*.tar.gpg; do mv \"$f\" \"r3-old-$f\"; done 2>/dev/null; true")
    rc, out = mw.sh(B[2][1], timeout=600)
    psql("select pg_switch_wal()")
    time.sleep(3)
    max0 = maxid()
    target = mw.root("date -u '+%Y-%m-%d %H:%M:%S+00'")[1].strip()
    time.sleep(2)
    oks = sum(patch(300 + (i % 2)).startswith("200") for i in range(a.after))
    time.sleep(8)
    c_before = cursor()
    mw.row(C, f"C. base backup, target, {a.after} audited changes after it", "all 200, cursor = max id", f"base backup rc {rc}; target {target}; max id {max0} -> {maxid()}; {oks} x 200; cursor {c_before}",
           rc == 0 and oks == a.after and c_before == maxid())
    psql("select pg_switch_wal()")
    time.sleep(5)
    pitr = [b for lang, b in B if lang == "sh"]
    s1b = [b for b in pitr if "main.before-pitr" in b and "systemctl stop" in b][0]
    s3b = [b for b in pitr if "recovery.signal" in b][0]
    newest_base = mw.root("ls -t /var/backups/bitscan/base-*.tar.gpg | head -1 | xargs -n1 basename")[1].strip()
    s1b = re.sub(r"base-YYYY[-MDTHSZ0-9]*\.tar\.gpg", newest_base, s1b)
    rc1, o1 = mw.sh(s1b, timeout=600)
    conf = [b for lang, b in B if lang == "text" and "recovery_target_time" in b][0].strip().replace("2026-10-25 14:30:00+00", target) + "\n"
    mw.stage("bitscan-recovery.conf", conf)
    rc2, _ = mw.sh("sudoedit /etc/postgresql/16/main/conf.d/bitscan-recovery.conf", env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "bitscan-recovery.conf"})
    rc3, _ = mw.sh(s3b, timeout=300)
    time.sleep(6)
    mrec, srec = maxid(), seq()
    rc4, o4 = mw.sh(block)
    s4 = seq()
    mw.row(C, f"C. PITR steps 1-3 as written (base backup {newest_base}), then step 4{subst}", f"max id back to {max0}; sequence set to the cursor {c_before}",
           f"rc {rc1}/{rc2}/{rc3}/{rc4}; max id {mrec}, sequence {srec} -> {s4}; psql [{o4.strip()}]", rc1 == rc2 == rc3 == rc4 == 0 and mrec == max0 and s4 == c_before)
    n1 = len(sink_ids())
    rc5, o5 = mw.sh("sudo rm /etc/postgresql/16/main/conf.d/bitscan-recovery.conf && sudo systemctl start bitscan-manager bitscan-manager-maintain.timer")
    up = ready()
    for v in (302, 303, 304):
        patch(v)
    time.sleep(10)
    ids = [int(x) for x in psql(f"select string_agg(audit_id::text, ',' order by audit_id) from audit_log where audit_id > {max0}").split(",") if x]
    got = sink_ids()[n1:]
    allsink = set(sink_ids())
    acts = psql(f"select string_agg(action, ',' order by audit_id) from audit_log where audit_id > {max0}")
    mw.row(C, "C. step 5 (start), three new audit entries (plus any system entry written at start-up)",
           f"every new id above the old cursor {c_before} and in the sink; the cursor advances to the last",
           f"ready {up}; new ids {ids} ({acts}); sink got after the count {got}; all new ids in the sink: {all(i in allsink for i in ids)}; cursor {cursor()}",
           up and len(ids) >= 3 and all(i > c_before for i in ids) and all(i in allsink for i in ids) and cursor() == ids[-1])

    # D. chain verification across the gap
    v = verify() if "D" in parts else "True (not repeated)"
    gaps = psql("select string_agg(a || '->' || b, ' ') from (select audit_id a, lead(audit_id) over (order by audit_id) b from audit_log) t where b - a > 1")
    mw.row(C, "D. verify_chain over the whole audit_log after r3", "ok True, every row checked", f"{v}; id gaps: {gaps}", v.startswith("True"))
    mw.root("rm -rf /var/lib/postgresql/16/main.before-pitr")

    rows = [json.loads(x) for x in (mw.OUT / "walk.jsonl").read_text().splitlines() if x.strip()]
    (mw.OUT / "ops-r3.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    bad = [r for r in rows if not r["ok"]]
    print(f"ops_pitr_r3 rows: {len(rows) - len(bad)}/{len(rows)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
