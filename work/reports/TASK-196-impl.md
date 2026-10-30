# TASK-196 IMPL: compliance sweep repository

Implementer: impl-manager-m9b, 2026-10-30. REQ-218, REQ-230. Open items #126, #127 (b). Plan: `work/plans/TASK-202.md` §3.

## Files

- `manager/bitscan_manager/repositories/job_sweep.py` (new, 186 lines).

No other file changed.

## Interface

```python
@dataclass(frozen=True)
class SweepJob: job_id; root_id; retry_of | None; scan_id; agent_id; state; payload: dict; eval_spec: Any
                created_at; dispatched_at | None; started_at | None; deadline_at | None
                policy_deleted: bool; agent_decommissioned: bool

def past_deadline(conn, now, limit=1000) -> list[UUID]
def never_started(conn, now, after: timedelta, limit=1000) -> list[UUID]
def lock_for_sweep(conn, job_id) -> SweepJob | None
def unit_result_uuids(conn, job: SweepJob) -> set[UUID]
def end_job(conn, job_id, state, now) -> bool
def insert_retry(conn, *, original: SweepJob, job_id, payload, eval_spec, created_at, pickup_by) -> None
```

**Differences from plan §3:** `SweepJob` also carries `dispatched_at`, `started_at` and `deadline_at`, so TASK-202 can re-check the deadline or the 24 h rule on the row read under the lock (builder checklist 9). `end_job` also filters `kind = 'compliance'` and raises `ValueError` for a state other than `completed`, `partial`, `failed`. `insert_retry` raises `ValueError` when the original is itself a retry or the payload's `job_id` is not the row's id.

## How it meets the acceptance points

- **Strict boundaries (#127 (b)):** `deadline_at < now`; `dispatched_at < now - after` with `started_at IS NULL` and `state = 'dispatched'`. Both `kind = 'compliance'` only, ordered, limited, unlocked (the caller locks each).
- **Root-first SKIP LOCKED:** `lock_for_sweep` reads the root without a lock, then (for a retry) `SELECT 1 … WHERE job_id = <root> FOR UPDATE SKIP LOCKED` (None if held), then the job joined to `scan → policy` (`deleted_at`) and `agent` (`status`) with `FOR UPDATE OF j SKIP LOCKED` (only the job row is locked). Same order as intake; never waits, so no deadlock.
- **Unit results:** distinct result plugins of the job and, for a retry, its original, both by primary key, joined on `job_created_at`. For an original in `dispatched`/`running` no retry can exist yet (a retry is made only when the original leaves those states), so no full `retry_of` read is needed.
- **State guard:** `end_job` updates only `WHERE state IN ('dispatched','running')`; rowcount 1 means this sweep ended it, so two sweeps make one retry.
- **Retry row:** a new `queued` compliance job with the given payload and `eval_spec`, the original's `scan_id` and `agent_id`, `retry_of` = the original. Only progress columns of the original change (`end_job`); the original's payload, `eval_spec`, `agent_id`, `scan_id`, `retry_of` are never written.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour is for the tester (TP-M9-10).

## Plants for the tester (mutation table)

- CHK-M9-339: `deadline_at <= %s` in `past_deadline`.
- CHK-M9-340: `created_at < %s` instead of `dispatched_at < %s` in `never_started`.
- CHK-M9-346: drop `AND state IN ('dispatched', 'running')` in `end_job`.
- CHK-M9-377: an `UPDATE scan_job SET payload = …` in `end_job` (the grant refusal must surface).
- CHK-M9-376: an f-string query.
