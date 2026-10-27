# TASK-134 IMPL: manager upgrade and operations runbook

Implementer: impl-deploy. REQ-139. Plan: `work/plans/TASK-133.md` §4 (layout §2). Spec: TS §8.7 L1343, L1346, L1348; §5.3 L1048; §8.2 L1267; README "Starting the app" (OpenBao token, certificate). Answers: #6, #90, #96 (pending its fact check, below).

## Files

| File | Change |
| --- | --- |
| `deploy/runbooks/manager-operations.md` | **New** (147 lines). No other file changed. |

## Sections

1. **Upgrade:**
   - Check the files against `SHA256SUMS`.
   - `systemctl stop bitscan-manager`.
   - `pip --require-hashes --only-binary :all:` for the new lock, then `--no-deps --no-index --force-reinstall` for the wheel (which also covers the degenerate same-wheel upgrade).
   - Install the release's unit files, then `daemon-reload`.
   - `systemctl start bitscan-manager-migrate`, the journal, `systemctl start bitscan-manager`, `/readyz`.
   - Then the agents (`agent-install.md` section 6).
   - The compatibility rule follows #90 and decisions 2026-10-20.
2. **TLS certificate:** `cp` onto the existing 0600 files, then `systemctl restart bitscan-manager`. Also a note on SPKI pins when the key changes: the agent holds a single pin, so a new key cuts pinned agents off until their pin changes.
3. **OpenBao token:** `sudoedit vault.token`, restart, then revoke the old token.
4. **Backups:**
   - A nightly `pg_dump -Fc` encrypted with `gpg --encrypt` to a public key, so no passphrase is typed.
   - WAL archiving in `conf.d/bitscan-archive.conf`, using PostgreSQL's documented `archive_command` form, on encrypted storage.
   - A separate encrypted tar of `manager.env` and `secrets/`.
   - The monthly restore test (detail below).
   - The catalog-rebuild note: 0.1.0 holds no policies, and `bits rebuild` isn't available in 0.1.0.
5. **Removal:**
   - Disable the units, remove them and the link and the venv.
   - Data is kept unless an explicit decision destroys it. Before destroying anything, check that the audit queue is empty, then revoke the OpenBao token.
   - Optional commands to drop the database and roles, the files and the user.
   - `/etc/bitscan` stays when the agent is on the same host (#82).

## Two points for the reviewer and the lead

1. **#96 is pending its fact check.** The certificate step says **restart**. A restart makes fresh `LoadCredential=` copies whatever the answer to #96 is, so the step is correct either way. If TP-M6-04 shows that `systemctl reload` refreshes the credential copies on systemd 255, I'll change section 2 to `systemctl reload bitscan-manager`, with the PID unchanged, as the REQ-139 (2) wording prefers. The runbook makes no claim about reload either way.
2. **Upgrade order detail. Lead ruling 2026-10-26: keep it. The runbook now states that the manager is unavailable from the stop to the start, while agents back off and retry.** Plan §4 installs the new wheel into the venv while the old service runs, then migrates and restarts. I stop the service **before** `pip install`. A running Python process lazily imports modules from disk, so it could load new-version files mid-run. Stop, install, migrate, start still meets TS §8.7 L1346 and L1348: migrate runs before the new version starts, and the manager is upgraded before the agents. The cost is a slightly longer gap, which agents ride out with back-off. If the lead prefers the plan's literal order, steps 2–4 change in one place.

## Monthly restore test (REQ-139 (3))

The `pg_hba.conf` from the install refuses the three roles on any database but `bitscan`. So the test adds one temporary line, `hostssl bitscan_restore bitscan_migrate 127.0.0.1/32 scram-sha-256`, directly above the `hostssl bitscan` line, and removes it at the end. The steps:
- Restore from a **file**, not a pipe. A dump written through a pipe has no data offsets, and `pg_restore` can't seek in stdin.
- Use `createdb -O bitscan_owner`, then `pg_restore --exit-on-error` as `postgres`.
- `sudo env BITSCAN_MIGRATE_DSN_FILE=/root/bitscan-restore.dsn bitscan-manager db migrate`. The variable holds a path, not a secret, and the DSN file is created at 0600 and filled with `sudoedit`.
- It must print the same head as the live migration, and a second run changes nothing.

## Checks run here

- All 11 ```` ```sh ```` blocks pass `bash -n` (dedented where nested in lists). LF only.
- No `PGPASSWORD`, no `password=` and no token on any command line, and no task id, REQ or `#nn` in the runbook.
- Cross-references resolve: `manager-install.md` section 2 (release check), `agent-install.md` section 6 (upgrade) and section 7 (pin change).
- Builder checklist: nothing applies (manager code, SQL and Go items). Item 11 holds in spirit.
- Not run: the walk. TP-M6-04 does it on the TASK-133 host.

## r1 (reviewer should-fix: WAL archive unusable)

Finding: WAL archiving was enabled "for recovery between dumps", but WAL can't be replayed onto a `pg_dump`, no step took a physical base backup, and nothing pruned the archive. Fix, in `deploy/runbooks/manager-operations.md` §4 only (147 → 195 lines). No other file changed.

- **What each part gives:** a new paragraph says the nightly dump is the logical copy (and what the monthly restore test uses), and that base backup + archived WAL is what recovers to a point between dumps.
- **WAL archiving:** settings unchanged (same `conf.d/bitscan-archive.conf`, `/var/lib/postgresql/wal-archive`, `postgres` 0700, encrypted storage, off-host copy).
- **Weekly base backup:** `sudo -u postgres pg_basebackup -D - -Ft -X none -l "base-$(date -u +%F)" | sudo gpg --encrypt … --output /var/backups/bitscan/base-<date>.tar.gpg`, scheduled with the backup system like the dump. It connects over the local socket (Ubuntu's default `local replication all peer` line; the install's Bitscan `pg_hba.conf` lines only cover the three Bitscan roles). `-X none` keeps the tar stream to stdout allowed and makes `pg_basebackup` wait until the archive holds the WAL the backup needs. Same `gpg --encrypt` pattern as the dump.
- **Pruning:** keep at least two base backups; find the oldest kept one's `*.backup` history file in the archive by its label (`grep -rl --include='*.backup' 'LABEL: base-YYYY-MM-DD'`, no shell glob in the 0700 folder), dry-run with `pg_archivecleanup -n`, then prune. Full path `/usr/lib/postgresql/16/bin/pg_archivecleanup` (Ubuntu doesn't put it on `PATH`). Off-host copy pruned the same way.
- **PITR outline (PostgreSQL 16):** stop manager, maintain timer and PostgreSQL; move `/var/lib/postgresql/16/main` aside; restore the base tar into a fresh 0700 `postgres` folder; `conf.d/bitscan-recovery.conf` with `restore_command`, `recovery_target_time`, `recovery_target_action = 'promote'`; `recovery.signal`; start; check the PostgreSQL log; delete the recovery file, start the manager, `/readyz`; take a new base backup (new timeline); delete `main.before-pitr` later. It states plainly that the whole cluster is replaced and later writes are lost. It doesn't claim the PITR path is tested monthly; the monthly test stays the dump restore.
- Paths: only Ubuntu PostgreSQL defaults (`/var/lib/postgresql/16/main`, `/etc/postgresql/16/main/conf.d/`, `/var/log/postgresql/postgresql-16-main.log`) and the existing backup folders. No new Bitscan path, no password on any command line.

Checks run here (r1):
- All 15 ```` ```sh ```` blocks (the 11 from r0 plus 4 new) pass `bash -n`, dedented where nested in lists. LF only. No `PGPASSWORD` or `password=`.
- Not run: the backup, prune and PITR walk itself. TP-M6-04 (tester) would need a PostgreSQL 16 host with archiving on to run it.

## r2 (TEST FAIL from tester-m6b: TP-M6-04, F3 and F4)

Only `deploy/runbooks/manager-operations.md` changed (195 → 200 lines).

- **F3 (§1 Upgrade, step 4):** the single `curl` after `systemctl start bitscan-manager` is now the same 10-try `/readyz` loop as `manager-install.md` §9. The six loop lines are byte-identical (`diff` of install L231–L236 against the tail of the step-4 block, after dedent). One sentence explains the loop ("a moment after `systemctl start` returns"). PITR step 4 still says "check `/readyz` as in section 1", so it now points to the loop. I left the PITR wording unchanged, as instructed.
- **F4 (§5 Removal):** the drain check is now `sudo find /var/lib/bitscan/audit-queue -name 'segment-*.jsonl'` must print nothing. The text says why: queued entries live in segment files, a segment is deleted once the sink has every entry in it, so no segment file means every entry reached the sink. `state.json` and `acked.json` stay, and that is expected. I checked this against `services/audit/disk_queue.py`: L104 globs `segment-*.jsonl`, and L194–L195 unlink every leading segment whose ids are all acked, including the newest.

Checks run here (r2):
- All 15 ```` ```sh ```` blocks pass `bash -n` (dedented where nested). LF only.
- No PITR line changed apart from what r1 wrote.

## r3 (user ruling 2026-10-26 on O2; tester-m6b CHK-M6-087)

Problem: point-in-time recovery rolls `audit_log` and `audit_log_audit_id_seq` back, but the shipper cursor in `/var/lib/bitscan/audit-queue/state.json` is outside the database and stays ahead. New entries with ids at or below the cursor are skipped by the shipper and never reach the sink, which breaks TS §5.3 L1051.

Only `deploy/runbooks/manager-operations.md` §4, the PITR outline, changed (200 → 209 lines):
- **Intro sentence:** "Anything written after the target is lost from the database. Audit entries the sink received after the target stay in the sink as history, by design."
- **New step 4,** between recovery and starting the manager, which is now step 5. It is marked in bold: don't start the manager until it's done.
  - `sudo python3 -I -c '…'` reads `cursor` from `state.json` and prints it as an `int`. The key and file name come from `services/audit/disk_queue.py` L26, L38 and L212–L217. `python3` is in Ubuntu 24.04 by default and the install adds `python3.12`. `jq` isn't installed by default, so it isn't used.
  - SQL `SELECT setval('audit_log_audit_id_seq', GREATEST(:'cursor'::bigint, (SELECT max(audit_id) FROM audit_log), 1))`, run as `postgres` on `bitscan` with `ON_ERROR_STOP=1`. The sequence name is the one in TS §5.2 L1004.
  - The cursor goes in as a psql variable (`-v cursor="$cursor"`, used as `:'cursor'::bigint`), so it is a quoted literal cast to `bigint`, never pasted into SQL. The SQL arrives on stdin through `printf … |`, because psql doesn't interpolate variables in `-c` strings. If the read failed and `$cursor` is empty, the cast fails and `ON_ERROR_STOP` stops before anything changes.
  - `GREATEST` never moves the sequence backwards, and it ignores a NULL `max` on an empty table. The extra `1` keeps `setval` from being called with 0, which is below the sequence's minimum, when both the cursor and the table are empty.
  - If `state.json` doesn't exist, the queue starts at cursor 0 (`disk_queue.py` L207–L209) and re-sends from the start, so nothing is skipped and the step isn't needed. The runbook says to skip it then.
- Nothing else changed. Step 5 still points at the `/readyz` loop in section 1. No product code, units or other sections were touched.

Checks run here (r3):
- All 16 ```` ```sh ```` blocks pass `bash -n` (15 plus the new one; dedented where nested). LF only.
- Not run: the SQL against a live PostgreSQL, and the full PITR walk (tester-m6b, CHK-M6-087).

## r4 (tester-m6b CHK-M6-087-r3 FAIL F5)

Problem: the install puts only `python3.12` and `python3.12-venv` on the host, and a fresh ubuntu:24.04 has no `python3`. So `sudo python3` failed, and psql then got an empty cursor (rc 3, nothing changed).

Only the PITR step 4 block in `deploy/runbooks/manager-operations.md` changed (209 → 213 lines):
- `sudo python3.12 -I -c …` instead of `sudo python3`. That is the interpreter `manager-install.md` §3 installs.
- The block now wraps the read and the `setval` in `if sudo test -f /var/lib/bitscan/audit-queue/state.json; then … else echo "no state.json: …; nothing to do"; fi`. `test` runs under `sudo` because the folder is 0700 `bitscan-manager`. psql is never reached when `state.json` is missing.
- The sentence after the block keeps the reason: the shipper starts again from the beginning, so the block skips the change.
- The SQL, the psql variable and `GREATEST` are unchanged. Nothing else changed.

Checks run here (r4):
- All 16 ```` ```sh ```` blocks pass `bash -n`. LF only. No bare `python3 ` left in the file.

## r5 (reviewer N3 should-fix, N4 nit; work/reviews/TASK-133-134-135.md)

Only `deploy/runbooks/manager-operations.md` changed (213 → 229 lines). PITR step 4 is untouched.

- **N3 (§5 Removal):** a new first step runs before anything is disabled or removed.
  - It runs `sudo systemctl stop bitscan-manager bitscan-manager-maintain.timer`. I also stop the timer, so no maintenance run starts during the check. The following `disable --now` disables it anyway.
  - Then one block prints `segment files: N, newest audit_id: M, shipper cursor: C`, followed by `OK` or `not drained`. `OK` needs 0 segment files and `max(audit_id)` equal to `cursor`.
    - `max` is read as `postgres` with `-Atc 'SELECT coalesce(max(audit_id),0) FROM audit_log'`.
    - `cursor` is read with `sudo python3.12 -I`, as in PITR step 4. A missing `state.json` counts as cursor 0, which matches the queue's own default (`disk_queue.py` L207–L209).
  - The text explains why: stopping can still write rows, for example the failed-check flush on `SIGTERM`. If the block says `not drained`, start the manager, wait a minute, and run it again until it prints `OK`. If it never does, check the journal.
  - The old segment-only sentence is replaced with: "Destroy the data only after the drain check above printed `OK`." The existing disable/remove block follows, under "Then disable and remove the service".
- **N4 (§4 base backup):** `ts="$(date -u +%Y%m%dT%H%M%SZ)"` is computed once, so the label `base-$ts` and the file `base-$ts.tar.gpg` always share the same timestamp, to the second. The pruning `grep` example is now `'LABEL: base-YYYYMMDDTHHMMSSZ'`. The PITR step 1 decrypt example is now `base-YYYYMMDDTHHMMSSZ.tar.gpg`. That is the step-1 file name only, so it matches the backup's output name; step 4 is untouched. The nightly dump and the `/etc` tar keep `+%F`, outside N4's scope.

Checks run here (r5):
- All 17 ```` ```sh ```` blocks pass `bash -n` (16 plus the drain check). LF only. No secret on any command line.
- I ran the cursor one-liner locally against a sample `state.json` (prints 87) and against a missing file (prints 0).
