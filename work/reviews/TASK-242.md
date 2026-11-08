# TASK-242 REVIEW: retention service `run_retention()`

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

- **Scope reviewed:** `manager/bitscan_manager/services/retention/task.py` (new, 255 lines, the only file).
- **Checked against:** TS §5.3 L1049, L1051, L1053, L1054; TS §5.2 L983–L992, L1002–L1006; REQ-274 to REQ-278; #150 (a)–(k), #151; plan `work/plans/TASK-242.md` §4 and the lead's corrections of 2026-11-08.
- **Reports:** `work/reports/TASK-242-impl.md`, `work/reports/TASK-242-test.md` (PASS, 26/26 on PostgreSQL 16 in WSL, 15/15 plants red).

## Checks

- **Audit chain (TS §5.3 L1053, REQ-276).** Each audit chunk is one transaction, in this order:
  1. `PgAuditRepo.lock_chain()`, the M1 chain lock, `pg_advisory_xact_lock(hashtext('audit_log'))`.
  2. `oldest(AUDIT_CHUNK)`.
  3. `audit_prefix(…, shipped_through(), …)`: None stops the step, so nothing is deleted before the first ship.
  4. `append_entry` writes `audit.checkpoint` (actor `system`, target null, detail exactly the #39 keys).
  5. `delete_through(last)`.
  6. If the count deleted differs from the count walked, raise and roll both back.
  7. `on_commit(wake)`.

  The checkpoint is always written before the delete and commits with it, or neither does. App writers wait on the chain lock and append after the commit (CHK-M11-194). The 25,000-entry case gives three chunks and three checkpoints, and M1's `verify_chain()` accepts the chain. The plants -343, -347, -349, the removed count check and the removed wake were all red. M1's `chain.py`, `verify.py` and `repositories/audit_log.py` are unchanged.
- **Clock (#150 (j), REQ-278 (1)):** the cutoffs come from the manager's `now`. A clock doubt returns every step as `clock_doubt` with one warning and no delete at all, audit included. A failing `db_now` propagates, so nothing is deleted. Each dated step probes its future rows first and skips only itself (plant -353 and the probe-removed plant were red).
- **Scans loop and the TASK-237 note:**
  - Skipped (lock-held) ids are carried through the run.
  - Each chunk asks for `SCAN_CHUNK + len(skipped)` rows and leaves them out, so later scans are reached in the same run.
  - Termination: every pass either deletes or adds each fresh id to `skipped`. The loop ends on no fresh id or a short read, so it cannot spin.
  - The lead's stall row CHK-M11-171 (101 locked scans ahead of 50 deletable ones) and its plants -172 and "skipped not carried" were red.
  - The lock is tried in the deleting transaction, on M8's key.
- **Deviations:** both are recorded in the impl report and match the lead's design points:
  - the skipped-ids loop replaces the plan's "stop when a chunk deletes nothing";
  - the chain lock is taken before the prefix read. This is defence in depth: `append_entry` takes the same, re-entrant lock. The tester recorded dropping it as an equivalent mutant, which is correct.
- **Isolation and stop:**
  - Each chunk is its own transaction through `db`, so a fault rolls back one chunk (builder checklist 20, CHK-M11-177, and the one-transaction-per-step plant).
  - A step that raises is logged and the next step runs. This is the REQ-277 boundary, so the broad `except` is at a real boundary.
  - Every transaction goes through `db`, so TASK-245's stoppable wrapper ends a run at its next transaction (checklist 10).
- **Logs and audit (TS §5.3 L1054, checklist 11):** the log lines are `retention step done` {step, deleted, chunks, skipped}, `retention step failed` {step, exc_type} and `retention refused: clock_doubt`. There are no ids, row content, hashes or exception text (plants -357 and "exception text" were red). The only audit INSERTs are checkpoints, and there is no DDL or UPDATE (CHK-M11-190).
- **Inventory (G2):** the `NEVER_DELETED` checksums, `os_info` and `agent_package` included, are unchanged after a full run (CHK-M11-180).
- **Layering:** a service over the retention repositories, M1's `append_entry`/`PgAuditRepo` and TASK-236's rules. There is no SQL in the service.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on `services/retention` and both test files: clean. The PostgreSQL suites are Linux-only, so I relied on the tester's WSL run.

## Findings

None.
