"""Operations walk, backups (TP-M6-04 CHK-M6-084, TASK-134 r1; REQ-139 (3)), on the walked host.

Runs in WSL as root after manager_walk.py --keep:
  python3 -I e2e/m6/ops_backup.py --tree TREE --work WORK

Every ```sh block of deploy/runbooks/manager-operations.md §4 runs verbatim as
`admin` with sudo; placeholders are filled the way an operator would
(`backup@example.org` stays: a test key pair with that address is made in root's
keyring; `YYYY-MM-DD`, the example `.backup` file name and the example target
time are replaced by the real values). Text blocks go into their files with
sudoedit. Order: nightly dump -> monthly restore test -> WAL archiving -> two
weekly base backups -> pruning -> point-in-time recovery -> config backup.
Same-day runs: the base-backup block names its output by date, so an earlier
output is moved aside first (as a week passing would). Rows go to
WORK/out/ops-backup.jsonl.
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


def sec4_blocks(md: str) -> list[tuple[str, str]]:
    return [(lang, textwrap.dedent(body)) for sec, lang, body in mw.blocks(md) if sec == "4"]


def adm(cmd: str, **kw: object) -> tuple[int, str]:
    return mw.sh(cmd, **kw)  # type: ignore[arg-type]


def psql(sql: str, db: str = "bitscan") -> str:
    return mw.root(f"sudo -u postgres psql -X -At -d {db} -c \"{sql}\"")[1].strip()


def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    a = ap.parse_args()
    mw.OUT = a.work / "out"
    (mw.OUT / "walk.jsonl").write_text("")  # mw.row appends here; copied at the end
    vals = {k: (a.work / "secrets" / k).read_text().strip() for k in ("pg_migrate", "admin_pw")}
    mw.SECRET_VALUES.extend(vals.values())
    B = sec4_blocks((a.tree / "deploy/runbooks/manager-operations.md").read_text())
    langs = [lang for lang, _ in B]
    mw.row("CHK-M6-084", "operations §4 block layout", "11 blocks (8 sh, 3 text)", f"{len(B)}: {langs}", len(B) == 11 and langs.count("sh") == 8)
    day = mw.root("date -u +%F")[1].strip()

    # test key pair for backup@example.org (root's keyring; the runbook's sudo gpg)
    rc, out = mw.root("gpg --batch --pinentry-mode loopback --passphrase '' --quick-gen-key backup@example.org default default never 2>&1 | tail -1; gpg --list-keys backup@example.org | head -2")
    mw.row("CHK-M6-084", "test backup key pair (root keyring)", "key listed", out, "backup@example.org" in out or "pub" in out)

    # nightly dump
    mw.root("for u in carol-dump; do true; done")
    rc, out = adm(B[0][1])
    f = f"/var/backups/bitscan/bitscan-{day}.dump.gpg"
    rc2, info = mw.root(f"stat -c '%U:%G %a %s' /var/backups/bitscan {f}; head -c 5 {f} | od -An -c; gpg --list-packets {f} 2>/dev/null | head -2")
    mw.row("CHK-M6-084", "§4 nightly dump block as written", "rc 0; /var/backups/bitscan root 700; dump encrypted (OpenPGP, not a PGDMP header)", f"rc {rc}; {out} || {info}",
           rc == 0 and "root:root 700" in info and "PGDMP" not in info and "pubkey enc packet" in info)

    # monthly restore test (steps 1-4)
    hba_line = B[8][1].strip() + "\n"
    mw.stage("restore.hba", hba_line)
    mw.sh("cat > /home/admin/bin/m6b-above && chmod 0700 /home/admin/bin/m6b-above", wd="/home/admin", stdin=(
        '#!/bin/sh\n# SUDO_EDITOR: insert the staged lines directly above the first `hostssl    bitscan ` line\nset -e\n'
        'awk -v f="/home/admin/stage/$M6B_STAGE" \'BEGIN{while((getline l < f)>0) s=s l "\\n"} /^hostssl +bitscan +/ && !d {printf "%s", s; d=1} {print}\' "$1" > "$1.m6b"\n'
        'cat "$1.m6b" > "$1"; rm -f "$1.m6b"\n'))
    rc, out = adm("sudoedit /etc/postgresql/16/main/pg_hba.conf && sudo systemctl reload postgresql",
                  env={"SUDO_EDITOR": "/home/admin/bin/m6b-above", "M6B_STAGE": "restore.hba"})
    rc2, hba = mw.root("grep -n -E '^(hostssl|hostnossl|host|local) ' /etc/postgresql/16/main/pg_hba.conf | head -6")
    mw.row("CHK-M6-084", "restore step 1: the bitscan_restore line directly above the hostssl bitscan line, reload", "rc 0; line order", f"rc {rc}; {hba}",
           rc == 0 and re.search(r"bitscan_restore.*\n\d+:hostssl +bitscan ", hba) is not None)
    rc, out = adm(B[9][1].replace("YYYY-MM-DD", day))
    tables = psql("select count(*) from pg_tables where schemaname='public'", "bitscan_restore")
    live_tables = psql("select count(*) from pg_tables where schemaname='public'")
    users = psql("select string_agg(username, ',' order by username) from app_user", "bitscan_restore")
    owner = psql("select pg_get_userbyid(datdba) from pg_database where datname='bitscan_restore'", "postgres")
    mw.row("CHK-M6-084", "restore step 2 as written (decrypt to a file, createdb -O bitscan_owner, pg_restore --exit-on-error)", "rc 0; same public tables as live; app users restored; owner bitscan_owner",
           f"rc {rc}; {out[-300:]} || tables {tables} vs live {live_tables}; users {users}; owner {owner}", rc == 0 and tables == live_tables and "alice" in users and owner == "bitscan_owner")
    mw.stage("bitscan-restore.dsn", f"host=127.0.0.1 port=5432 dbname=bitscan_restore user=bitscan_migrate password={vals['pg_migrate']} sslmode=require\n")
    body = B[10][1]
    rc, out = adm(body, env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "bitscan-restore.dsn"})
    live = mw.root("journalctl -u bitscan-manager-migrate --no-pager -o cat | grep -vE '^(Starting |Finished |bitscan-manager-migrate.service: )' | tail -1")[1].strip()
    mode = mw.root("stat -c '%U:%G %a' /root/bitscan-restore.dsn")[1].strip()
    mw.row("CHK-M6-084", "restore step 3 as written: db migrate with the scratch DSN", f"rc 0; prints the live head ({live})", f"rc {rc}; [{out.strip()}]; dsn file {mode}",
           rc == 0 and out.strip().split("\n")[-1] == live and mode == "root:root 600")
    rc, out2 = adm("sudo env BITSCAN_MIGRATE_DSN_FILE=/root/bitscan-restore.dsn bitscan-manager db migrate")
    ver = psql("select version_num from alembic_version", "bitscan_restore")
    mw.row("CHK-M6-084", "restore step 3: a second run changes nothing", f"rc 0; same head; alembic_version {live}", f"rc {rc}; [{out2.strip()}]; alembic_version {ver}",
           rc == 0 and out2.strip() == out.strip() and ver == live)
    rc, out = adm("sudo -u postgres dropdb bitscan_restore && sudo rm -rf /var/lib/postgresql/restore-test /root/bitscan-restore.dsn")
    mw.stage("restore.hba", hba_line)
    mw.sh("cat > /home/admin/bin/m6b-dropline && chmod 0700 /home/admin/bin/m6b-dropline", wd="/home/admin", stdin=(
        '#!/bin/sh\n# SUDO_EDITOR: remove the staged line\nset -e\ngrep -vxF -f "/home/admin/stage/$M6B_STAGE" "$1" > "$1.m6b" || true\ncat "$1.m6b" > "$1"; rm -f "$1.m6b"\n'))
    rc2, out2 = adm("sudoedit /etc/postgresql/16/main/pg_hba.conf && sudo systemctl reload postgresql",
                    env={"SUDO_EDITOR": "/home/admin/bin/m6b-dropline", "M6B_STAGE": "restore.hba"})
    rc3, left = mw.root("grep -c bitscan_restore /etc/postgresql/16/main/pg_hba.conf || true; sudo -u postgres psql -X -Atc \"select count(*) from pg_database where datname='bitscan_restore'\"; ls /var/lib/postgresql/restore-test /root/bitscan-restore.dsn 2>&1 | head -2")
    mw.row("CHK-M6-084", "restore step 4 clean-up as written", "scratch db, files and the pg_hba line gone", f"rc {rc}/{rc2}; {left}",
           rc == 0 and rc2 == 0 and left.split("\n")[0] == "0" and left.split("\n")[1] == "0")

    # WAL archiving
    assert B[1][0] == "text" and B[1][1].startswith("wal_level")
    mw.stage("bitscan-archive.conf", B[1][1].strip() + "\n")
    rc, out = adm("sudoedit /etc/postgresql/16/main/conf.d/bitscan-archive.conf && sudo install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/wal-archive && sudo systemctl restart postgresql",
                  env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "bitscan-archive.conf"})
    time.sleep(2)
    psql("select pg_switch_wal()")
    time.sleep(3)
    arch = psql("select archived_count || ' archived, ' || failed_count || ' failed' from pg_stat_archiver", "postgres")
    ready = ""
    for _ in range(30):
        ready = adm("curl -s --cacert manager-ca.pem https://bitscan-mgr.test:8443/readyz")[1]
        if ready == '{"status":"ok"}':
            break
        time.sleep(1)
    mw.row("CHK-M6-084", "WAL archiving as written (conf.d file, wal-archive postgres 0700, restart PostgreSQL)", "archiving works (archived > 0, failed 0); the manager recovers (/readyz ok)",
           f"rc {rc}; {arch}; readyz {ready}", rc == 0 and arch.endswith("0 failed") and not arch.startswith("0 ") and ready == '{"status":"ok"}')

    # two weekly base backups
    labels = []
    for n in (1, 2):
        if n == 2:
            mw.root(f"mv /var/backups/bitscan/base-{day}.tar.gpg /var/backups/bitscan/base-{day}.week1.tar.gpg")
            mw.sh("sudo bitscan-manager users create-admin bob-week2 </dev/null >/dev/null 2>&1; true")
        rc, out = adm(B[2][1], timeout=600)
        info = mw.root(f"ls -la /var/backups/bitscan/; gpg --list-packets /var/backups/bitscan/base-{day}.tar.gpg 2>/dev/null | head -2")[1]
        labels.append(rc)
        mw.row("CHK-M6-084", f"weekly base backup {n} as written (pg_basebackup -X none | gpg)", "rc 0; encrypted file", f"rc {rc}; {out[-200:]} || {info}", rc == 0 and "pubkey enc packet" in info)
    rc, bk = mw.root("ls /var/lib/postgresql/wal-archive/*.backup | xargs -n1 basename")
    backups = sorted(bk.split())
    mw.row("CHK-M6-084", "each base backup left a .backup history file in the archive", "two", " ".join(backups), len(backups) == 2)

    # pruning: drop the first base backup; keep the second
    mw.root(f"rm /var/backups/bitscan/base-{day}.week1.tar.gpg")
    grep_line, dry, prune = (B[3][1].strip().split("\n") + ["", "", ""])[:3]
    rc, found = adm(grep_line.replace("YYYY-MM-DD", day))
    found_names = sorted(Path(p).name for p in found.split())
    keep = backups[-1]
    mw.row("CHK-M6-084", "pruning: the grep as written finds the .backup file of the base backups by label", f"lists the .backup files labelled base-{day}",
           f"rc {rc}; {found_names} (same-day labels: both backups carry base-{day})", rc == 0 and keep in found_names)
    before = sorted(mw.root("ls /var/lib/postgresql/wal-archive")[1].split())
    rc, dryout = adm(dry.replace("000000010000000000000042.00000028.backup", keep))
    after_dry = sorted(mw.root("ls /var/lib/postgresql/wal-archive")[1].split())
    rc2, pout = adm(prune.replace("000000010000000000000042.00000028.backup", keep))
    after = sorted(mw.root("ls /var/lib/postgresql/wal-archive")[1].split())
    removed = sorted(set(before) - set(after))
    keep_seg = keep.split(".")[0]
    dry_names = sorted(Path(x).name for x in re.findall(r"\S*[0-9A-F]{24}\S*", dryout))
    mw.row("CHK-M6-084", "pruning: -n dry run changes nothing and lists what goes; the prune removes exactly that",
           f"segments before {keep_seg} removed, {keep_seg} and later kept",
           f"rc {rc}/{rc2}; dry run listed {len(dry_names)}; removed {removed}; kept {[x for x in after if x[:24] >= keep_seg][:4]}",
           rc == 0 and rc2 == 0 and before == after_dry and bool(removed) and all(r[:24] < keep_seg for r in removed)
           and all(x in after for x in before if x[:24] >= keep_seg) and set(dry_names) == set(removed))

    # point-in-time recovery
    mw.sh("sudo bitscan-manager users create-admin carol-before </dev/null >/dev/null 2>&1; true")
    pw = vals["admin_pw"]
    for name in ("carol-before",):
        rc, o, done = mw.pty_run(f"sudo bitscan-manager users create-admin {name}", [(r"New password: $", pw), (r"Repeat the password: $", pw)], timeout=60)
    psql("select pg_switch_wal()")
    time.sleep(2)
    target = mw.root("date -u '+%Y-%m-%d %H:%M:%S+00'")[1].strip()
    time.sleep(2)
    rc, o, done = mw.pty_run("sudo bitscan-manager users create-admin dave-after", [(r"New password: $", pw), (r"Repeat the password: $", pw)], timeout=60)
    psql("select pg_switch_wal()")
    time.sleep(4)
    pre = psql("select string_agg(username, ',' order by username) from app_user")
    mw.row("CHK-M6-084", "PITR set-up: carol-before, target time, dave-after, WAL switched and archived", "both users present before recovery", f"target {target}; users {pre}",
           "carol-before" in pre and "dave-after" in pre)
    rc, out = adm(B[4][1].replace("YYYY-MM-DD", day), timeout=600)
    mw.row("CHK-M6-084", "PITR step 1 as written (stop, move main aside, restore the base backup)", "rc 0", f"rc {rc}; {out[-300:]}", rc == 0)
    conf = B[5][1].strip().replace("2026-10-25 14:30:00+00", target) + "\n"
    mw.stage("bitscan-recovery.conf", conf)
    rc, out = adm("sudoedit /etc/postgresql/16/main/conf.d/bitscan-recovery.conf", env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "bitscan-recovery.conf"})
    mw.row("CHK-M6-084", "PITR step 2: bitscan-recovery.conf with the target time (sudoedit)", "rc 0", f"rc {rc}; {conf}", rc == 0)
    rc, out = adm(B[6][1], timeout=300)
    time.sleep(5)
    log = mw.root("grep -E 'recovery stopping|starting point-in-time|archive recovery complete|ready to accept|selected new timeline|FATAL|PANIC' /var/log/postgresql/postgresql-16-main.log | tail -8")[1]
    sig = mw.root("ls /var/lib/postgresql/16/main/recovery.signal 2>&1 | tail -1")[1]
    post = psql("select string_agg(username, ',' order by username) from app_user")
    mw.row("CHK-M6-084", "PITR step 3 as written: recovery stops at the target, promotes, accepts connections; recovery.signal removed",
           "carol-before present, dave-after absent; log names the stop and readiness", f"rc {rc}; users {post}; {log}; signal: {sig}",
           rc == 0 and "carol-before" in post and "dave-after" not in post and "recovery stopping before" in log and "ready to accept" in log and "No such file" in sig)
    rc, out = adm("sudo rm /etc/postgresql/16/main/conf.d/bitscan-recovery.conf && sudo systemctl start bitscan-manager bitscan-manager-maintain.timer")
    ready = ""
    for _ in range(30):
        ready = adm("curl -s --cacert manager-ca.pem https://bitscan-mgr.test:8443/readyz")[1]
        if ready == '{"status":"ok"}':
            break
        time.sleep(1)
    mw.root(f"mv /var/backups/bitscan/base-{day}.tar.gpg /var/backups/bitscan/base-{day}.pre-pitr.tar.gpg")
    rc2, out2 = adm(B[2][1], timeout=600)
    tl = psql("select timeline_id from pg_control_checkpoint()", "postgres")
    mw.row("CHK-M6-084", "PITR step 4: recovery file deleted, manager and timer started, /readyz, a new base backup on the new timeline",
           "/readyz ok; base backup rc 0; timeline 2", f"rc {rc}; readyz {ready}; base backup rc {rc2}; timeline {tl}", rc == 0 and ready == '{"status":"ok"}' and rc2 == 0 and tl == "2")
    mw.root("rm -rf /var/lib/postgresql/16/main.before-pitr")

    # config and secrets backup
    rc, out = adm(B[7][1])
    f = f"/var/backups/bitscan/etc-{day}.tar.gpg"
    rc2, lst = mw.root(f"gpg --list-packets {f} 2>/dev/null | head -2; gpg --batch -q --decrypt {f} 2>/dev/null | tar -tvf - | awk '{{print $1, $2, $6}}'; grep -c BITSCAN {f} || true")
    mw.row("CHK-M6-084", "§4 configuration and secrets backup as written", "encrypted; holds manager.env and secrets/ (six files) with their modes; no plain text in the file",
           f"rc {rc}; {lst}", rc == 0 and "pubkey enc packet" in lst and "manager.env" in lst and lst.count("secrets/") >= 7 and lst.strip().endswith("0"))

    rows = [json.loads(x) for x in (mw.OUT / "walk.jsonl").read_text().splitlines() if x.strip()]
    (mw.OUT / "ops-backup.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    bad = [r for r in rows if not r["ok"]]
    print(f"ops_backup rows: {len(rows) - len(bad)}/{len(rows)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
