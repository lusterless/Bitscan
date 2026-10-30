# TASK-197 IMPL: schedules repository

Implementer: impl-manager-m9b, 2026-10-30. REQ-224, REQ-225, REQ-230. Open items #122 (h), #128 (d). Plan: `work/plans/TASK-203.md` §3.

## Files

- `manager/bitscan_manager/repositories/schedules.py` (new, 175 lines).

No other file changed.

## Interface (as plan TASK-203 §3)

```python
@dataclass(frozen=True)
class ScheduleRow: schedule_id; name; policy_id; target: dict; cron; timezone; enabled
                   last_run_at | None; next_run_at | None; created_by

def insert(conn, *, name, policy_id, target, cron, timezone, enabled, next_run_at, created_by) -> ScheduleRow
def get(conn, schedule_id, *, lock=False) -> ScheduleRow | None
def page(conn, limit, after_id: int | None) -> list[ScheduleRow]
def update(conn, schedule_id, changes: Mapping[str, object]) -> ScheduleRow | None
def delete(conn, schedule_id) -> bool
def due(conn, now, limit=100) -> list[ScheduleRow]
def previous_unfinished(conn, schedule_id) -> bool
def policy_state(conn, policy_id) -> tuple[str, bool] | None     # (policy_status, deleted)
def mark_run(conn, schedule_id, *, ran_at: datetime | None, next_run_at: datetime) -> None
```

## How it meets the acceptance points

- **CRUD:** `insert … RETURNING` the full row (target as `Jsonb`); `get` (optionally `FOR UPDATE`); `page` ordered by `schedule_id` after the cursor id; `update` sets only columns from the fixed set `name, target, cron, timezone, enabled, next_run_at`, each through `sql.Identifier` (sorted, so the statement text is stable); an empty change or any other key (for example `policy_id`, `created_by`) raises `ValueError` before SQL; `delete` → rowcount 1. The FK `ON DELETE SET NULL` leaves the schedule's scans with `schedule_id` NULL.
- **Due rows:** `enabled AND next_run_at <= now ORDER BY next_run_at, schedule_id LIMIT n FOR UPDATE SKIP LOCKED`: rows another session holds are skipped (#128 (e)); rows with `next_run_at` NULL never match.
- **Previous scan unfinished:** the schedule's latest scan by `created_at DESC, scan_id DESC` has `finished_at IS NULL` (no scan → False).
- **Policy state:** `(policy_status::text, deleted_at IS NOT NULL)`, None for an unknown policy.
- **Run bookkeeping:** `last_run_at = COALESCE(ran_at, last_run_at)` (a skip or a miss keeps the previous run time), `next_run_at = given`.
- Every statement is parameterised; DELETE only on `scan_schedule` (granted).

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour is for the tester (TP-M9-10).

## Plants for the tester (mutation table)

- CHK-M9-373: remove `SKIP LOCKED` (or `FOR UPDATE SKIP LOCKED`) in `due`.
- CHK-M9-376: an f-string query (for example in `update` building the SET list from `changes` keys).

## Revision 1 (2026-10-30, lead's ruling "M9 builder rulings" (5))

- `policy_state(conn, policy_id, *, lock: bool = False)`: with `lock=True` the row is read `FOR SHARE`. A policy delete's `UPDATE policy` then waits for the caller's transaction, and its later `UPDATE scan_schedule SET enabled = false` sees a schedule the caller wrote (TS §4.3 L550). If the delete committed first, the share lock returns the row with `deleted_at` set.
- New `try_share_policy(conn, policy_id) -> bool`: `SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE SKIP LOCKED`, False when another session holds the row. Used by the scheduler tick (TASK-203 r1), which holds its schedule row and must not wait for the policy.

Plants: drop `FOR SHARE` from the `lock=True` query (a racing delete then leaves an enabled schedule of a deleted policy); drop `SKIP LOCKED` from `try_share_policy` (the tick and a policy delete can then deadlock).
