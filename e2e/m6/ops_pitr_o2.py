"""O2 reproduction (TP-M6-04 CHK-M6-087, user ruling 2026-10-26): after a point-in-time
recovery, do new audit entries get ids at or below the audit queue's cursor
(state.json, outside the database) and so never reach the sink?

Runs in WSL as root on the walked host with WAL archiving on (after ops_backup.py):
  python3 -I e2e/m6/ops_pitr_o2.py --tree TREE --work WORK [--after N]

1. Fresh base backup (operations §4 block as written).
2. Target time T; then N (default 45, above PostgreSQL's 32 pre-logged
   sequence values) `PATCH /settings` changes, each one audit entry, all
   delivered to the sink; WAL switched and archived.
3. PITR to T exactly as operations §4 steps 1-4 say; the manager started.
4. Three new audit entries: their ids, the cursor in state.json, the sequence,
   and whether the sink received them.
Rows go to WORK/out/ops-o2.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manager_walk as mw  # noqa: E402
from ops_backup import psql, sec4_blocks  # noqa: E402

SESS = ["--url", mw.URL, "--ca", f"{mw.REL}/manager-ca.pem", "--state", "/home/admin/stage/session.json"]


def patch(value: int) -> str:
    return mw.sh("python3.12 -I /opt/m6b/mgr_api.py call " + " ".join(SESS) + f" PATCH /api/v1/settings --body '{{\"job_pull_seconds\": {value}}}'", wd="/home/admin")[1]


def cursor() -> int:
    return int(json.loads(mw.root("cat /var/lib/bitscan/audit-queue/state.json")[1])["cursor"])


def sink_ids() -> list[int]:
    out = mw.root("cat /opt/m6b/sink.jsonl")[1]
    ids = []
    for line in out.splitlines():
        try:
            b = json.loads(line)["body"]
        except (ValueError, KeyError):
            continue
        if isinstance(b, dict) and isinstance(b.get("audit_id"), int):
            ids.append(b["audit_id"])
    return ids


def ready() -> bool:
    for _ in range(30):
        if mw.sh("curl -s --cacert manager-ca.pem https://bitscan-mgr.test:8443/readyz")[1] == '{"status":"ok"}':
            return True
        time.sleep(1)
    return False


def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--after", type=int, default=45)
    a = ap.parse_args()
    mw.OUT = a.work / "out"
    (mw.OUT / "walk.jsonl").write_text("")
    B = sec4_blocks((a.tree / "deploy/runbooks/manager-operations.md").read_text())
    day = mw.root("date -u +%F")[1].strip()
    C = "CHK-M6-087"

    arch = mw.root("cat /etc/postgresql/16/main/conf.d/bitscan-archive.conf; ls /var/lib/postgresql/wal-archive | wc -l")[1]
    mw.root(f"cd /var/backups/bitscan && for f in base-{day}*.tar.gpg; do mv \"$f\" \"o2-old-$f\"; done 2>/dev/null; true")
    rc, out = mw.sh(B[2][1], timeout=600)
    mw.row(C, "fresh base backup as written (archiving on)", "rc 0", f"rc {rc}; archive conf: {arch.strip()}; {out[-150:]}", rc == 0)
    psql("select pg_switch_wal()")
    time.sleep(3)
    max0, c0 = psql("select max(audit_id) from audit_log"), cursor()
    target = mw.root("date -u '+%Y-%m-%d %H:%M:%S+00'")[1].strip()
    time.sleep(2)
    t_after = time.time()
    oks = 0
    for i in range(a.after):
        oks += patch(300 + (i % 2)).startswith("200")
    time.sleep(8)
    max1, c1 = int(psql("select max(audit_id) from audit_log")), cursor()
    sk = sink_ids()
    shipped_after = sorted(i for i in sk if i > int(max0))
    mw.row(C, f"{a.after} audited PATCH /settings after the target; all shipped", f"{a.after} x 200; cursor = max id; sink holds them",
           f"target {target}; before: max id {max0}, cursor {c0}; {oks} x 200; after: max id {max1}, cursor {c1}; sink ids > {max0}: {len(shipped_after)} ({shipped_after[:3]}..{shipped_after[-3:]})",
           oks == a.after and c1 == max1 and len(shipped_after) >= a.after)
    psql("select pg_switch_wal()")
    time.sleep(5)

    # PITR to the target, as written
    rc, out = mw.sh(B[4][1].replace("YYYY-MM-DD", day), timeout=600)
    conf = B[5][1].strip().replace("2026-10-25 14:30:00+00", target) + "\n"
    mw.stage("bitscan-recovery.conf", conf)
    rc2, _ = mw.sh("sudoedit /etc/postgresql/16/main/conf.d/bitscan-recovery.conf", env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "bitscan-recovery.conf"})
    rc3, _ = mw.sh(B[6][1], timeout=300)
    time.sleep(6)
    max2 = psql("select max(audit_id) from audit_log")
    seq = psql("select last_value || ' (is_called ' || is_called || ')' from audit_log_audit_id_seq")
    log = mw.root("grep -E 'recovery stopping|archive recovery complete|ready to accept' /var/log/postgresql/postgresql-16-main.log | tail -3")[1]
    mw.row(C, "PITR to the target as written (steps 1-3)", f"rc 0; audit max id back to {max0}", f"rc {rc}/{rc2}/{rc3}; max id {max2}; sequence {seq}; {log}",
           rc == 0 and rc2 == 0 and rc3 == 0 and max2 == max0)
    rc, _ = mw.sh("sudo rm /etc/postgresql/16/main/conf.d/bitscan-recovery.conf && sudo systemctl start bitscan-manager bitscan-manager-maintain.timer")
    up = ready()
    c2 = cursor()

    # three new audit entries after the recovery
    n_sink0 = len(sink_ids())
    for v in (302, 303, 304):
        patch(v)
    time.sleep(10)
    rows = psql(f"select string_agg(audit_id::text, ',' order by audit_id) from audit_log where audit_id > {max0}")
    new_ids = [int(x) for x in rows.split(",") if x]
    sk2 = sink_ids()[n_sink0:]
    c3 = cursor()
    reached = [i for i in new_ids if i in sk2]
    collide = [i for i in new_ids if i <= c2]
    rep = psql("select coalesce(string_agg(action, ',' order by audit_id), '') from audit_log where audit_id > " + str(max0))
    shipper = mw.root("journalctl -u bitscan-manager --since '-2min' --no-pager -o cat | grep -iE 'audit|sink|cursor|queue' | tail -4")[1]
    verdict = "REAL: new entries at or below the cursor never reached the sink" if collide and not all(i in reached for i in collide) else (
        "not reproduced: every new id is above the cursor" if not collide else "collision, but the entries reached the sink")
    mw.row(C, "after PITR + start: new audit ids vs the queue cursor (state.json) and the sink",
           "observation (no fixed expectation): records whether ids <= cursor and whether they reach the sink",
           f"{verdict}. manager ready {up}; cursor at start {c2} (DB max was {max0}); new ids {new_ids} ({rep}); ids <= cursor: {collide}; "
           f"sink got after the restart: {sk2}; cursor now {c3}; shipper log: {shipper}", True)
    rows_out = [json.loads(x) for x in (mw.OUT / "walk.jsonl").read_text().splitlines() if x.strip()]
    (mw.OUT / "ops-o2.jsonl").write_text("\n".join(json.dumps(r) for r in rows_out) + "\n")
    print("O2:", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
