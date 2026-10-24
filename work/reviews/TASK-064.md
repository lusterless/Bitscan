# TASK-064 REVIEW: inventory ingestion

Reviewer: reviewer. Date: 2026-10-23. REQ-075. Spec: TS §3.4 L241–L243 (every upload replaces `os_info` and sets `last_inventory_at`; on a changed `list_sha256` upsert `agent_package`, delete unlisted rows, write a snapshot), §5.2 L780–L825 and L1007–L1013 (no UPDATE on `package`), §8.1 L1257 (flooding), §8.4 L1291 (more than 1,000 previously unseen packages a day alerts); `.claude/rules/manager/database.md` ("INSERT … ON CONFLICT DO NOTHING and then a SELECT"); #60 (empty `source` → NULL), #65 (e), #69. Rulings (`work/decisions.md`, 2026-10-23):
- W3 (3): keep the spec-faithful comparison with the latest snapshot;
- "Threshold alerts consume their once-per-period slot only on commit" (revision 1, which also touches the approved TASK-056 file).

Plan: `work/plans/TASK-060.md`, step 5. Inputs:
- `work/reports/TASK-064-impl.md`, including "Revision 1";
- `work/reports/TASK-064-test.md` (PASS on revision 1: CHK-M3-170 to -175; 20 unit and 13 PostgreSQL tests; 70 passed in WSL with `test_thresholds.py` and `test_inventory_repo_pg.py`; 16 of 16 plants red).

Files reviewed:
- `manager/bitscan_manager/services/inventory/ingest.py` (new, 185 lines);
- `manager/bitscan_manager/services/audit/thresholds.py` (revision 1: `count_and_check` and `mark_fired`);
- the tester-b test files.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. The M3 owner notes recommend a second look (TS §8.1 flooding).

## What was checked

- **Spec conformance.**
  - The agent row is locked first (`get(lock=True)`). That serialises one agent's uploads and catches a revoke made after the token check: `AgentGone`, nothing written, and TASK-074 answers 401 `token_revoked`.
  - Every upload upserts `os_info` with `collected_at` = receive time (#69) and sets `last_inventory_at`.
  - An unchanged recomputed hash stops there: no `agent_package` change, no snapshot (REQ-075 (2)).
  - On a change, or with no snapshot yet:
    - `insert_packages` (TASK-053: INSERT … ON CONFLICT DO NOTHING plus SELECT in sorted batches, so two agents with one new package give one row) with an empty `source` stored as NULL;
    - the `agent_package` upsert keeps `first_seen_at`;
    - `delete_not_listed` keeps every `package` row;
    - the snapshot diffs on `(name, version, architecture, status)`, so an upgrade or status change is the old line in `removed` and the new line in `added`. The first snapshot lists all packages in `added`, and `package_count` is the uploaded count.
  - Everything runs in the caller's one transaction, and a forced mid-transaction failure leaves no change (REQ-075 (4)).
- **Burst alert (#65 (e), ruling).** The count is the `package` rows this upload created, so "new to the fleet", over a 24 h window and 24 h period, above 1,000.
  - `count_and_check` counts at once. When it is due, the `new_packages_burst` entry is written in the transaction, and `mark_fired` is registered with `on_commit`.
  - A rolled-back upload therefore leaves the slot free and the next qualifying upload alerts. That was round 0's defect, now tested.
  - The detail holds counts only, never package names.
- **`thresholds.py` change (TASK-056 file).** The split is minimal: `add()` is `count_and_check` plus `mark_fired`, so its behaviour and the 19 TASK-056 tests are unchanged. The edit is required by the lead's ruling and is confined to `SlidingCount`.
- **Security invariants and grants.** No UPDATE on `package` (pg tests run as `bitscan_app`). Nothing is logged, and no package name or `raw` value appears outside the tables. All SQL is in the approved repositories.
- **Scope.** `ingest.py` plus the ruled `thresholds.py` change. The package `__init__` is unchanged.
- **Tests (my run, Windows).** `test_inventory_ingest.py`, `test_inventory_ingest_pg.py` and `test_thresholds.py`: 39 passed, 13 skipped (PostgreSQL; run in WSL by tester-b). ruff and format are clean, and `mypy --strict` is clean on the whole tree (166 files). Coverage of both files is 100 % (tester-b).

## Findings

None.

## Notes and carry-overs

- **TASK-074.** Build the burst window once per process as `SlidingCount(clock, 24 h, 24 h, NEW_PACKAGES_PER_DAY)`. Pass `tx.on_commit`. Map `AgentGone` to 401 `token_revoked`. Complete a `dispatched` job in the same transaction as the ingest.
- **TASK-067 (lead ruling).** The approved TASK-063 `agent_auth_failures` window still marks before commit through `add()`. Moving it to `count_and_check` plus an on-commit `mark_fired`, and building it once in `create_app()`, is assigned to TASK-067.
- **M6.** The `latest_snapshot` lookup has no `agent_id` index; its cost is measured in the load test (ruling W3 (3)).
- **Residual (accepted in the impl report).** Two back-to-back uploads from one agent can both see "due" in the gap between the first one's commit and its hook, giving two alerts. That errs toward alerting.
