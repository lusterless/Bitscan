# TASK-236 IMPL: retention rules (pure)

Implementer: impl-manager-b, 2026-11-08. REQ-274, REQ-276 (the prefix rule), REQ-278 (the clock and future-row decisions). Spec: TS §5.3 L1049 (ages), L1053 (checkpoint before delete, so only a prefix of the chain can go). Open items: #150 (a)–(e), (i), (j). Plan: `work/plans/TASK-242.md` §2. High risk (the user's second look, PD-47).

## Files (+1 package, 2 new files, about 125 lines)

- `manager/bitscan_manager/services/retention/__init__.py` (new): package docstring only. It exports nothing; callers import `retention.rules`, as `services/evaluator/__init__.py` does.
- `manager/bitscan_manager/services/retention/rules.py` (new): pure, with no I/O, clock or logging.
  - Constants exactly as in plan §2: `SCAN_AGE` 400 d, `SNAPSHOT_AGE` 180 d, `REQUEST_AGE` and `TOKEN_AGE` 90 d, `INVENTORY_JOB_AGE` 30 d, `AUDIT_YEARS` 3, `CLOCK_SKEW` 5 min, `FUTURE_SLACK` 1 d; chunks `SCAN_CHUNK` 100, `JOB_CHUNK` 1,000, `ROW_CHUNK` 10,000, `AUDIT_CHUNK` 10,000.
  - `Cutoffs` (frozen): `scans`, `snapshots`, `requests`, `tokens`, `audit`, `inventory_jobs`.
  - `cutoffs(now) -> Cutoffs`: `now − age` for five of them, and `minus_years(now, 3)` for audit.
  - `minus_years(now, years) -> datetime`: calendar years. Feb 29 becomes Feb 28. A negative `years` raises `ValueError`.
  - `audit_prefix(rows, cutoff, shipped, limit) -> int | None`:
    - walks at most `limit` rows in the given (ascending id) order;
    - stops at the first row with `at >= cutoff` or `audit_id > shipped`;
    - returns the last id walked, or None (nothing qualifies, or `shipped` is None).
    - `limit < 1` raises `ValueError`, and so do ids out of ascending order.
  - `clock_doubt(manager_now, db_now) -> bool`: `abs(gap) > 5 min`.
  - `future_rows(newest, now) -> bool`: `newest > now + 1 day`, and False for None.

## Behaviour the tester should know

- **Boundary.** A row is past a cutoff only when it is strictly older (`time < cutoff`). The repositories (TASK-237, 238) use `<`, and `audit_prefix` stops at `at >= cutoff`, so a row exactly at the cutoff is kept and one 1 µs older is selected (REQ-274 (1)).
- **Timezone.** Every input instant must be timezone-aware, or the call raises `ValueError` (REQ-274 (4)). This holds for `now`, `cutoff`, each row's `at`, `manager_now`, `db_now` and `newest`. All cutoffs are returned in UTC.
  - Calendar years are subtracted in UTC: `2028-02-29T05:00+08:00` (= `2028-02-28T21:00Z`) gives `2025-02-28T21:00Z`. Doing the calendar step in UTC means the result doesn't depend on the caller's timezone.
- **Cap at the shipped cursor.** `audit_prefix` always returns an id that is stored in `rows`. With ids 5 and 8 and `shipped = 7`, it returns 5, not 7. So the service's `row_hash(N)` and `delete_through(N)` (TASK-238) always name an existing entry, and the checkpoint records the hash of the entry actually deleted last.
- **`ValueError` texts** are fixed words naming the parameter (for example "now must be timezone-aware"), never a value.

## Deviations

None from plan §2. Additions within the plan's intent, each raising `ValueError`: `limit < 1`, ids out of ascending order, and a negative `years`.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check manager && ruff format --check manager`: all checks passed, 392 files formatted.
- `mypy --strict` on `services/retention` and both TASK-237/238 repositories: no issues in 4 files.
  - `mypy --strict manager` as a whole: 12 errors, all in files this task doesn't touch (`api/user/packages.py`, `agents.py`, `enrolment.py`, `policy_import.py`, `tests/test_policy_import_api_pg.py`).
  - The main checkout at `6efe0fb` gives the same 12. The local venv lacks `python_multipart`, so the venv is stale against `requirements.txt`; CI installs from the hashed lock.
- An ad-hoc `python -I -c` run of the REQ-274 examples (nothing written to the tree):
  - cutoffs: `now` 2029-03-01Z gives audit 2026-03-01Z, and 2028-02-29 gives 2025-02-28;
  - prefix: old, old, new, old gives 2; all new gives None; a cursor of 1 gives 1; no cursor gives None; ids 3 and 7 with the cursor at 5 give 3;
  - `clock_doubt` at exactly 5 min is False and at 5 min 1 s is True;
  - `future_rows` at exactly +1 d is False and at +1 d 1 µs is True;
  - a naive `now` raises `ValueError`.

  Tests are the tester's (`manager/tests/test_retention_rules.py`, TP-M11-05).

## Builder checklist

Items 1–3, 5, 6 and 13 don't apply (no client input, version, route or OpenAPI). 11 and 12: nothing is logged, and the error texts are fixed. 20: per-row isolation is the service's job (TASK-242).
