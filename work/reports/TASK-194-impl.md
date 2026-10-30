# TASK-194 IMPL: scan progress repository

Implementer: impl-manager-m9b, 2026-10-30. REQ-219, REQ-220, REQ-230. Open items #127 (d)–(f). Plan: `work/plans/TASK-202.md` §3.

## Files

- `manager/bitscan_manager/repositories/scan_progress.py` (new, 134 lines).

No other file changed.

## Interface (as plan TASK-202 §3)

```python
REFRESH_WINDOW: Final = timedelta(days=8)
def refresh_candidates(conn, now: datetime, window: timedelta = REFRESH_WINDOW) -> list[UUID]
def unit_facts(conn, scan_ids: Sequence[UUID]) -> dict[UUID, list[Unit]]     # Unit from services/jobs/scan_state.py
def scan_row(conn, scan_id: UUID, *, lock: bool = False) -> tuple[str, datetime | None] | None
def set_scan_state(conn, scan_id: UUID, state: str, finished_at: datetime | None) -> bool
def cancel_open_jobs(conn, scan_id: UUID, now: datetime) -> list[UUID]       # sorted
```

`Unit` is imported from the pure `services/jobs/scan_state.py` (TASK-187) so the facts and `derive()` share one shape.

## How it meets the acceptance points

- **Unit facts in one statement:** `jobs` (MATERIALIZED: compliance jobs with `scan_id = ANY(%s)`, each with `root = COALESCE(retry_of, job_id)`) is the only read of `scan_job`; `got` = distinct (root, plugin) with a result (joined on `job_id` and `job_created_at`); `planned` = the original's payload plugins (`jsonb_array_elements(payload -> 'plugins')`, `retry_of IS NULL`); `missing` = roots with a planned plugin not in `got`. Per (scan, root): `open` = any job queued/dispatched/running; `complete` = root not in `missing`; `has_results` = root in `got`; `any_cancelled`; `all_queued` = every job queued. An empty id list returns `{}` without SQL. A unit's retry filling the original's missing plugins makes the unit complete (REQ-207 (1)).
- **Candidates (#127 (f)):** `finished_at IS NULL OR (state <> 'completed' AND created_at > now - 8 days)`: excludes `completed` scans and finished scans older than 8 days, keeps finished non-completed scans (late results).
- **Scan update:** `set_scan_state` sets `state` and `finished_at = COALESCE(finished_at, given)` only `WHERE state <> new OR (finished_at IS NULL AND given IS NOT NULL)`; so `finished_at` is set once, never moved or cleared (#127 (e)), and an unchanged scan is not written (rowcount 0 → False). `dispatched`/`expired` or any non-scan state raises `ValueError` before SQL. Only `scan.state` and `scan.finished_at` are written.
- **Cancel:** `UPDATE scan_job SET state = 'cancelled', finished_at = now WHERE scan_id = %s AND kind = 'compliance' AND state IN ('queued','dispatched','running') RETURNING job_id`. Completed, partial, failed, expired and already-cancelled jobs are untouched. Lock note in the docstring: it locks only open jobs and a unit has at most one open job (a retry exists only after its original ended), so it cannot form a cycle with intake's root-then-job order.
- `scan_row(lock=True)` reads `FOR UPDATE` (UPDATE grant on `scan.state` suffices) for TASK-200.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour is for the tester (TP-M9-10).

## Plants for the tester (mutation table)

- CHK-M9-359: `state IN ('queued')` only in `cancel_open_jobs` (dispatched left).
- CHK-M9-363: candidates `WHERE finished_at IS NULL` only (finished non-completed scans skipped).
- CHK-M9-361 (repository side): group by `job_id` instead of `root` in `_FACTS`.
- CHK-M9-376: an f-string query.
