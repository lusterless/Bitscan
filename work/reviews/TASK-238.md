# TASK-238 REVIEW: audit retention repository

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/repositories/retention_audit.py` (new, 55 lines, the only file). Checked against TS §5.3 L1049, L1051, L1053, TS §5.2 L983–L992 (`audit_log`) and L1002–L1006 (grants), REQ-276, #39, #150 (d) and plan `work/plans/TASK-242.md` §3. Reports: `work/reports/TASK-238-impl.md` and `work/reports/TASK-238-test.md` (PASS, the audit rows of the 41/41 run on PostgreSQL 16 in WSL, 7/7 plants red).

## Checks

- **Prefix only (TS §5.3 L1053, #150 (d)):**
  - `oldest(n)` reads `(audit_id, at)` in id order. It never orders by `at`; the plant that did was red.
  - `delete_through(N)` deletes exactly `audit_id <= N`. The module offers no delete by `at`, so the hole-in-the-chain plant CHK-M11-348 was red.
  - `N` comes from TASK-236's `audit_prefix`, which always returns a stored id at or below the shipped cursor.
  - `row_hash(N)` returns the stored `row_hash` (the `prev_hash` plant was red) and raises on a missing id, so a checkpoint can never record an empty hash.
- **Checkpoint and delete in one transaction:** `delete_through` refuses an autocommit connection, so the delete cannot commit apart from the checkpoint that TASK-242 appends first through `append_entry` (chain lock). The repository writes no audit entry itself.
- **Grants:** `bitscan_app` is refused the delete and `audit_log` is unchanged (CHK-M11-142). There is no migration and no grant change.
- **SQL and output:** parameterised only, no logging, fixed error texts. No row content leaves the module except ids, times and the hash, which TASK-242 records in the checkpoint as #39 specifies.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the module are clean. The PostgreSQL rows are Linux-only, so I relied on the tester's WSL run.

## Findings

None.
