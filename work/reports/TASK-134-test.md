# TASK-134 TEST: manager upgrade and operations runbook (TP-M6-04)

Verdict: **PASS at r5** (see "Revision 5" below; round 1 was FAIL, open on O2 → TASK-134 r3). Tester: tester-m6b. REQ-139. Runbook versions:
- r1 (WAL archive fix, sha256 at walk time): walked §2/§3 on the round-1 install host, and §1, §4, §5 on the TASK-133 r1 host.
- r2 (sha256 df706a30…cfac): re-tested F3 and F4.
OpenBao and the sink are the test doubles (#93). The agent is the real 0.1.0-1 `.deb` from the local release run (sha256 3b5c98a0…033db) in an `m4b-sysd-u24` container on the host's Docker network, with no published port.

Written by `main` from the tester's text (the harness blocks the tester on report files).

Commands and totals:
- `check_runbook_text.py manager-operations.md`: OK, 15 sh blocks, 0 findings. `check_md_links.py`: OK (CHK-M6-086).
- `ops_walk.sh m6b-host /root/m6tb cert96 cert vault`: #96 FACT row + 3/3 PASS. The first vault run failed on a test-double bug: the fake lost its key on restart. After the fix (persisted key, token read per request): 1/1.
- `ops_backup.py` (r1 §4): 16/20 rows. The 4 failures were check bugs (gpg packet line offset ×3, grep rc ×1). Re-checked on the artifacts: 4/4 PASS.
- `ops_upgrade.py` (r1 §1, real agent): 10/11. Failed: step 4 as written (F3).
- `ops_walk.sh … removal` (r1 §5, on a snapshot copy): 1/3. F4, plus a check bug in the process count, which a re-check showed 0.
- r2: `ops_walk.sh … upgrade`: 1/1 PASS (after a check-parse fix). `ops_walk.sh … removal`: 4/4 PASS, including a control (a queued segment file is printed).
- `ops_pitr_o2.py` (O2 reproduction, user ruling): REAL (CHK-M6-087).

Acceptance criteria:
- REQ-139 (1) upgrade: PASS at r2. Head m0005 unchanged, new PID, /readyz ok. The agent heartbeated again 310 s later (03:53:52 → 03:59:02) with the same agent_id, token and agent.yaml, no new enrolment request, no re-enrol journal line and NRestarts 0. r1 failed only on F3.
- (2) #96 fact, then the certificate step: FACT recorded. `systemctl reload` sends SIGHUP: the manager logs "tls certificate reloaded", but the PID, the credential copy's hash and the leaf presented to new connections are all unchanged, so reload does **not** refresh LoadCredential= copies on systemd 255. §2's restart, as written, presents the new leaf: PASS. The runbook says restart, which is the right step.
- (3) backup restores into a scratch DB at head: PASS. That covers the monthly restore test, the r1 WAL/base-backup/prune/PITR steps, and the config backup.
- (4) no secret or process note: PASS.
- O2 (PITR and the audit queue cursor): **FAIL**, see below.

Failures:
1. F3 (r1 §1 step 4). Expected `{"status":"ok"}`; got `curl: (7) Failed to connect … Couldn't connect to server`, rc 7: curl runs straight after `systemctl start`. Fixed in r2 (the 10-try loop): PASS.
2. F4 (r1 §5). Expected the drain check to pass on a drained queue. `find … -type f` always prints state.json and acked.json. Fixed in r2 (`-name 'segment-*.jsonl'`): PASS, with a control.
3. O2 (CHK-M6-087). Setup: 45 audited changes after the PITR target, then a PITR as written. The sequence was restored to 42, but state.json kept cursor 87. The new entries got ids 43, 44, 45, all ≤ the cursor, and the sink received none of them. Diagnosis: the queue cursor lives outside the database, and nothing in the PITR outline moves the id sequence past it. Fix (r3): before the manager starts, setval the sequence to GREATEST(cursor, max(audit_id)).

Notes (low, not blocking):
- N3: the r2 drain check sees only segment files. Entries the shipper hasn't read from the database yet (id > cursor) have no segment, so "no segment file" isn't strictly "everything shipped". Comparing the cursor with `max(audit_id)` would close that gap.
- N4: the base-backup block names its output by date, so a second run on the same day hits gpg's "File exists" prompt. Same-day backups also carry the same label, and §4's grep then lists two `.backup` files. Weekly scheduling avoids both.
- O2's product guard (refuse to start or alert when the cursor is ahead of the database) is the user's later-milestone question.

## Revision 3: FAIL (F5); Revision 4: PASS for O2 (the N3 re-test is still open)
r3 (sha256 5679ffbc…64eb5): `ops_pitr_r3.py` gave 8/10.
- The new PITR step 4 block, run as written, failed. Its `sudo python3` doesn't exist on the walked host: install §3 installs only python3.12. That left the cursor empty and psql errored (`invalid input syntax for type bigint: ""`, rc 3, sequence untouched). This is F5.
- With `python3` → `python3.12` substituted (recorded), the logic passed on every point:
  - (1)/(2): 87 > 46 → `setval 87`. The next entry shipped above the old cursor, and the cursor advanced.
  - (4): cursor 10 below max 89 → the sequence stayed at 89.
  - (3): verify_chain gave ok, 22 rows checked, across the gaps.
  - C (the PITR scenario): max id back to 91, setval 136, new ids 137–140 all above 136, all in the sink.
- The second failed row was a test bug: a start-up alert (137) was shipped before my sink count. The sink held it.
r4 (sha256 d6e935cc…586e): `python3.12` plus an `if sudo test -f …/state.json` guard. `ops_pitr_r3.py --parts A,E,C --label CHK-M6-087-r4`: **8/8 PASS**.
- A: cursor 160 > max 140 (state.json set by hand, as a PITR leaves it). `setval 160`; the next entry, 162, reached the sink; cursor 162.
- E: state.json missing → the block printed `no state.json: the shipper starts again from the beginning; nothing to do`, rc 0, psql was not run, sequence 162 → 162.
- C: base backup; target 04:23:38; 45 changes (cursor 208). PITR steps 1–3 as written, then step 4: `setval 208` (sequence 196 → 208). The sink count was taken before step 5. After the start: new ids 209 (`alert.agents_offline` at start-up), then 210–212 (`settings.change`). All above 208, all in the sink, cursor 212.
- B and D were not repeated: the SQL is unchanged. In r3, B held the sequence at 89 and D gave verify_chain ok.
Result: O2 is fixed. `check_runbook_text.py manager-operations.md`: OK, 16 sh blocks, 0 findings.

## Revision 5: PASS
Runbook sha256 52fce86f…a45b. `check_runbook_text.py`: OK, 17 sh blocks, 0 findings.
- N4 (§4, `ops_walk.sh m6b-host /root/m6tb n4`): 3/3.
  - Two base backups as written on the same day: `base-20261026T042852Z.tar.gpg` and `base-20261026T042857Z.tar.gpg`, distinct, no overwrite prompt.
  - The pruning grep with the newer label prints exactly one file, `000000050000000000000017.00000028.backup` (`LABEL: base-20261026T042857Z`).
  - The dry run changes nothing. The prune removes only segments before 000000050000000000000017, and the kept `.backup` stays.
- One PITR pass with the timestamped name (`ops_pitr_r3.py --parts C --label CHK-M6-087-r5`): the three C rows PASS.
  - Restore from `base-20261026T042918Z.tar.gpg`. Max id back to 215; step 4 `setval 260`.
  - New ids 261–264, all above the old cursor 260, all in the sink (counted before the start); cursor 264.
  - The script's unselected A row printed FAIL with the block not run (`cursor 212 > max id 212 :: rc 0; []`). That's a script artifact, not counted.
- N3 (§5, on a snapshot copy, `ops_walk.sh m6b-rm /root/m6tb removal5`): 7/7.
  - Sink double stopped, 3 audited changes queued, then the drain block as written: `segment files: 1, newest audit_id: 300, shipper cursor: 300` → `not drained`.
  - Sink back, "start the manager, wait a minute, run the block again": `segment files: 0, newest 302, cursor 302` → `OK`.
  - Cursor set one behind the newest, no segment: `… newest 302, cursor 301` → `not drained`. After restoring state.json: `OK`.
  - A segment file left with cursor = newest: `segment files: 1 …` → `not drained`.
  - The disable/remove block keeps the data. The destroy block removes the DB, 4 roles, files and user.
TASK-134 acceptance:
- REQ-139 (1)–(4) all PASS: upgrade at r2; #96 fact and the certificate step; backups, restore test, PITR with O2 fixed at r4; text.
- F3, F4, F5, O2, N3 and N4 are all fixed and re-tested.
- Verdict **PASS**.
