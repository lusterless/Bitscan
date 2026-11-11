# TASK-237 REVIEW: retention repository

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/repositories/retention.py` (new, 180 lines, the only file), against TS §5.3 L1049, L1051, TS §5.2 (the cascades and the L1002–L1006 grants), REQ-275, REQ-278, #150 (a)–(c), (e)–(g), (j), (k), plan `work/plans/TASK-242.md` §3, and the two lead corrections of 2026-11-08 (`work/decisions.md`: the tokens probe on `user_token.created_at`; no row lock in `scan_chunk`). Reports: `work/reports/TASK-237-impl.md`, `work/reports/TASK-237-test.md` (PASS, 41/41 on PostgreSQL 16 in WSL, 29/29 plants red for TASK-237 and TP-M11-22).

## Checks

- **Spec conformance (TS §5.3 L1049, #150):**
  - Whole scans go in one `DELETE FROM scan … = ANY(%s)`, and the cascades remove jobs (original and retry), results in every partition and re-evaluation rows together. A scan whose partitions were already dropped still goes.
  - Inventory jobs: `kind = 'inventory' AND finished_at < cutoff`.
  - Snapshots: `collected_at`.
  - Requests: `decision IS NOT NULL AND decided_at`, so pending ones are never deleted. The tester added an undecided row with an old `decided_at` so the `decision` clause can't be dropped unnoticed.
  - Tokens: `expires_at < cutoff`, revoked or not.
  - Packages: unreferenced only.
  - Every comparison is a strict `<`, and each call removes at most one chunk.
- **What is never touched (security invariant: no path disables or erases inventory, G2):** no statement names `agent`, `os_info`, `agent_package`, `enrollment_token`, the catalog, schedule or setting tables. The grant probes (CHK-M11-150) show `bitscan_retention` can delete from exactly the nine TS §5.2 tables. Plant -341 (deleting `agent_package`) is refused by the grants. No DDL (plant -369 refused; CHK-M11-154).
- **Grants not weakened:** no migration. `bitscan_app` is refused every delete (CHK-M11-142).
- **The no-row-lock correction:** PostgreSQL row-locking clauses need UPDATE privilege, and TS §5.2 gives `bitscan_retention` none, so the plan's `FOR UPDATE SKIP LOCKED` would fail every run (CHK-M11-152 shows all five clauses refused, `42501`). The #150 (k) guard is the advisory lock, so nothing is lost. Code was changed, not grants, as the database rule asks.
- **Re-evaluation lock (#150 (k)):** `try_reeval_lock` uses the same key as M8 `reeval.lock_scan` (`repositories/reeval.py:67`: `hashtext('scan_reeval'), hashtext(CAST(CAST(… AS uuid) AS text))`). It is transaction-level and refuses autocommit. The tester drove the race with M8's own `lock_scan` in a second session, both ways. The wrong-key and session-level plants were red.
- **Future-row probe correction:** `newest("user_token")` reads `created_at`. Probing `expires_at` would skip the tokens step whenever a live API token exists (up to 365 days ahead), so REQ-275 (4) could never hold. The delete cutoff stays on `expires_at`. The probe tables come from a fixed `MappingProxyType` composed with `sql.Identifier`. An unknown key raises before any SQL runs.
- **SQL:** parameterised only. The one composed statement is built from constants (S608 clean; plant -345 red). No logging, and the errors are fixed text.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the module and both test files: clean. The PostgreSQL suites are Linux-only, so I relied on the tester's WSL run.

## Findings

None.

Note for TASK-242 (not a finding here): `scan_chunk` returns the oldest scans first and takes no lock. A scan skipped because its re-evaluation lock is held therefore comes back at the head of every later chunk in the same run. The service loop must end, rather than re-select forever, when a chunk deletes nothing, and must not stop early while deletable scans remain behind skipped ones. A chunk of 100 skipped scans is the edge to test.
