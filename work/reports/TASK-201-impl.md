# TASK-201 IMPL: schedule management service

Implementer: impl-manager-m9b, 2026-10-30. REQ-224, REQ-227. Open items #122 (h), (i), #128 (d), (h), (i), #129 (a). Plan: `work/plans/TASK-203.md` §4.

## Files

- `manager/bitscan_manager/services/scheduler/schedules_admin.py` (new, 203 lines with docstrings; about 150 code lines).

No other file changed. Uses TASK-188 `parse_target`, TASK-191 `parse_schedule`/`next_fire`, TASK-197 `repositories/schedules`, TASK-198 `queue.PolicyNotFound` (one 404 class for "unknown policy"), M3 `TxAudit`.

## Interface

```python
NAME_MAX = 128; PATCHABLE = {"name", "target", "cron", "timezone", "enabled"}
class ScheduleNotFound(Exception)      # 404
class ScheduleConflict(Exception)      # 409: the policy is deleted
class InvalidField(ValueError)         # .field in {"name", "enabled", "body"}; message "Invalid request: <field>"
# InvalidTarget (.field "target…") and InvalidSchedule (.field "cron" | "timezone") propagate unchanged.

def create(tx, *, name: object, policy_id: int, target: object, cron: object,
           timezone: object = "UTC", enabled: object = True, user_id: int, now: datetime) -> ScheduleRow
def update(tx, schedule_id: int, *, changes: Mapping[str, object], user_id: int, now: datetime) -> ScheduleRow
def delete(tx, schedule_id: int, *, user_id: int) -> None
def get(tx, schedule_id: int) -> ScheduleRow
def list_page(tx, *, limit: int, after_id: int | None) -> list[ScheduleRow]
```

Values arrive as decoded JSON (`object`), so the service checks each type again (defence behind the route's strict model). Every message is a fixed word naming the field.

## Behaviour

- **Validation before any write:** `name` stored as given, 1–128 characters, no U+0000, no lone surrogate (UTF-8 encode check); `target` through `parse_target` and stored as the request form (agent ids lowercase, no `resolved_agents`; resolved at each run, #122 (h)); `cron` + `timezone` through `parse_schedule`; `enabled` must be a bool.
- **Policy (#122 (h)):** unknown → `PolicyNotFound` (404); deleted → `ScheduleConflict` (409) on create, and on a patch with `enabled: true`; a disabled policy is accepted.
- **`next_run_at` (#128 (d)):** `next_fire(schedule, now)` on create (also when created disabled), on a `cron` or `timezone` change, and on `enabled: true`; `enabled: false` leaves it. A patch of `cron` alone is checked with the stored `timezone` (and the reverse). A patch that only renames, retargets or disables does not re-parse the stored cron.
- **Patch:** a non-empty subset of `PATCHABLE`; empty or any other key (`policy_id`, `created_by`, …) → `InvalidField("body")`. The row is locked (`get(lock=True)`) before deciding; `ScheduleNotFound` if absent.
- **Delete:** row locked, then deleted; `ScheduleNotFound` if absent. Its scans keep their rows (FK `ON DELETE SET NULL`).
- **Audit (#129 (a)):** one entry per change, actor `user:<id>`, target `scan_schedule:<id>`; `scan_schedule.create` detail = name, policy_id, target, cron, timezone, enabled, next_run_at (ISO text); `scan_schedule.update` detail = the changed fields with their new values (plus `next_run_at` when recomputed); `scan_schedule.delete` detail = name, policy_id. No command text exists in a schedule. A rolled-back change leaves no entry (same transaction).
- **RBAC (#128 (i), #122 (i)):** none here; the route requires operator. Any operator may change any schedule; `created_by` is set once.

## Known benign race (for the reviewer)

`create` reads the policy's deleted flag without a lock. A policy delete committing between that read and this commit could leave one enabled schedule of a deleted policy. Its runs are still refused: `queue_scan` raises `PolicyDeleted` and TASK-203 skips it as `policy_disabled` (plan §5 step 3). I did not add a `FOR SHARE` because it would change the TASK-197 repository under test; say if you want it.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour is for the tester (TP-M9-14).

## Plants for the tester

- REQ-224 (2): drop the `enabled is True` recompute (enable keeps a stale `next_run_at`).
- REQ-224 (3): drop `if _deleted(...)` in `create`.
- REQ-224 (7): accept a 129-character name (`NAME_MAX = 129`) or drop the NUL check.
- CHK-M9-370 (service side): call `parse_schedule(cron, "UTC")`.

## Revision 1 (2026-10-30, lead's ruling "M9 builder rulings" (5))

The "known benign race" above is closed. `_deleted()` reads the policy with `policy_state(..., lock=True)` (`FOR SHARE`, TASK-197 r1) in the change's own transaction:
- `create`: a delete that commits first is seen (409); a delete that starts later waits on the share lock, then disables the new schedule (TS §4.3 L550). So no enabled schedule of a deleted policy is left behind.
- `update` with `enabled: true`: the same check, now taken **before** the schedule row lock. The row is read without a lock first for its `policy_id`, which never changes. Lock order is policy, then schedule, the same as M7's delete (which updates the policy, then its schedules), so the two cannot deadlock. As a result, an enabling PATCH of a deleted policy's schedule now answers 409 before any cron, time-zone or target 400.

Plant: drop the `FOR SHARE` (call `policy_state` without `lock=True`). A delete held at a barrier between the check and the commit then leaves an enabled schedule of a deleted policy.
