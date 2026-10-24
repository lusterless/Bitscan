# TASK-053 REVIEW: inventory repository

Reviewer: reviewer. Date: 2026-10-23. REQ-075, REQ-081. Spec: TS §5.2 L780–L825 (`os_info`, `package`, `agent_package`, `inventory_snapshot`) and L994–L1013 (grants: INSERT only on `package` and `inventory_snapshot`), §3.4 L241–L243, §7.2 L1219 ("Debian versions … do not sort as text"); `.claude/rules/manager/database.md` ("Never weaken these grants", "Never compare Debian versions as text"); #68 (package page fields and order), #69 (snapshot items, `collected_at`). Plan: `work/plans/TASK-060.md` (ingest, step 5). Inputs:
- `work/reports/TASK-053-impl.md`, including "Revision 1";
- tester's TEST PASS (message 2026-10-23; CHK-M3-070 to -074, `manager/tests/test_inventory_repo_pg.py`, WSL) and the revision 1 re-test PASS (CHK-M3-074-r1 and -r1-probe; 3 undo-plants red). The rows are to be written to `tests/m3/report.md` by `main`.

Files reviewed:
- `manager/bitscan_manager/repositories/inventory.py` (new, 252 lines, 222 code);
- the tester's test file.

Verdict: APPROVED (round 2)

Round 1 was CHANGES_REQUESTED (finding 1 below). Revision 1 fixed it; finding 1 is resolved. Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance and grants.**
  - `insert_packages` uses `INSERT … SELECT FROM unnest(…) ON CONFLICT DO NOTHING RETURNING` followed by a `SELECT … JOIN unnest(…)`, in batches of 1,000. It never issues an UPDATE or DELETE on `package`, as the database rule requires.
  - `new` is exactly the rows this call created, which is the #65 (e) input. Keys are written in sorted order, so overlapping concurrent uploads cannot deadlock (tested with four mixed-order writers).
  - The `agent_package` upsert keeps `first_seen_at`.
  - `delete_not_listed` removes only that agent's rows, using a hashed `NOT IN (SELECT unnest(…))` subplan rather than a quadratic `<> ALL`. `package` rows stay.
  - The `os_info` upsert replaces every column.
  - The snapshot has `added` and `removed` as JSONB.
  - `latest_snapshot` orders by `snapshot_id`, which is insertion order. The test plan row says "by `collected_at`, then id". Since `collected_at` is the receive time (#69), insertion order gives the same answer without depending on the clock. Accepted; the tester asserted the insertion order.
- **Security invariants.** All values are parameters, arrays included. `psycopg.sql` composes identifiers from constants only. ruff S608 is clean. Nothing is logged.
- **Scope.** One file, every function named in the task row. 222 code lines against a 190 estimate. Accepted, because it is one cohesive repository.
- **Tests.** The tests run as `bitscan_app`:
  - 50,000 rows with statement capture show no UPDATE and at least 50 batched inserts;
  - a second call reports no new rows;
  - a deterministic same-package race gives one row;
  - grant probes refuse UPDATE and DELETE on `package` and `inventory_snapshot`;
  - keyset paging returns each row exactly once.

  My run (Windows): ruff, format and `mypy --strict` are clean (143 files, the whole manager tree). The PostgreSQL cases skip locally and ran in WSL (tester).

## Round 2 (revision 1)

- `package_page` (`inventory.py:235-255`) now orders by `p.name, p.architecture, p.version::debversion, p.version`, and the keyset uses the same four-part tuple, with the previous row's version passed as `debversion` and as text. The text tie-break keeps the key total for versions that are equal in Debian order. The change is confined to that function.
- The tester added two paging tests. One pages through `1.0~rc1, 1.0, 1.00, 1.9, 1.10, 2.0, 2.0-1, 1:0.1` (text order differs; `1.0` and `1.00` are equal in Debian order) at page sizes that split the ties. The other mixes architectures. The three undo-plants are red.
- The tester's probe shows `debversion` accepts any string, so the cast cannot fail on stored data. My second note below is therefore answered: no extra decoder rule is needed for it.

## Findings

1. **blocking (resolved in revision 1)**, `manager/bitscan_manager/repositories/inventory.py:246-249` (`package_page`, round 1). The page was ordered, and its keyset compared, on `p.version` as text. That broke `.claude/rules/manager/database.md` "Never compare Debian versions as text" and TS §7.2 L1219. The fix is described in "Round 2".

## Notes (no action in this task)

- **TASK-064 and M6.** `latest_snapshot` has no `agent_id` index (none may be added). For an agent whose list rarely changes, every upload walks the primary key backwards past every other agent's newer snapshots. With 10,000 agents and 180-day retention, that is a growing scan on every ingest. TASK-064 could compare the upload's hash with the hash recomputed from the agent's `agent_package` rows (PK prefix `agent_id`, about 2,000 rows), which hold exactly the last stored list. If it does, the "no snapshot yet" case must still write the first snapshot. This is a design choice for TASK-064 and the lead, not this task's defect.
- **TASK-060 and TASK-064 (answered).** The concern was that odd version strings could fail the `ix_package_name_debver` cast. The tester's probe shows `debversion` accepts any string, so no 500 can come from that cast.
