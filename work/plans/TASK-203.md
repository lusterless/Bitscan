# TASK-203 plan: scheduled scans (design note D4), with the TASK-191, 197 and 201 interfaces

Planner: planner-m9, 2026-10-30. REQ-223, REQ-224, REQ-225, REQ-227. Open items: #3, #122 (h), (i), #128, #129 (a).

## 1. Spec quotes

- TS §4.4 L557: "**Scheduled:** a cron expression per `scan_schedule` row, evaluated in the schedule's `timezone` (default UTC). Runs missed while the manager was down are not back-filled. A run is skipped and logged if the previous scan from the same schedule is not yet finished (`finished_at IS NULL`), or if the policy is disabled. Users may enable or disable schedules (unlike inventory)."
- TS §2.1 L103: the scheduler is "APScheduler, inside the manager process (one manager instance in v1)".
- TS §5.2 L846–L857: `scan_schedule (schedule_id, name VARCHAR(128), policy_id, target JSONB, cron VARCHAR(64), timezone VARCHAR(64) DEFAULT 'UTC', enabled, last_run_at, next_run_at, created_by)`.

## 2. Pure interface (TASK-191, `bm/services/scheduler/cron.py`)

```python
class InvalidSchedule(ValueError): field: Literal["cron", "timezone"]     # fixed message
@dataclass(frozen=True)
class Schedule: cron: str; timezone: str; trigger: CronTrigger            # APScheduler 3
def parse_schedule(cron: str, timezone: str) -> Schedule
def next_fire(schedule: Schedule, after: datetime) -> datetime            # strictly after; UTC-aware
```

- Cron: ASCII, ≤ 64 characters, exactly five whitespace-separated fields; no `@`; no `?`, `L`, `W`, `#`. Day-of-week field: each numeric token (in lists, ranges and steps) is mapped `0→sun, 1→mon, …, 6→sat, 7→sun` before calling `CronTrigger(minute=…, hour=…, day=…, month=…, day_of_week=…, timezone=zone)` (not `from_crontab`, so the translation is explicit). A range that wraps after translation (`5-7` → `fri-sun`) must stay valid; the test pins it. Both day of month and day of week not `*` → `InvalidSchedule("cron")` (#128 (a)).
- APScheduler parse errors (`ValueError`) become `InvalidSchedule("cron")`.
- Time zone: `zoneinfo.ZoneInfo(name)` after refusing `localtime`, any name with `/` at the start, `..`, a backslash, or over 64 characters; `ZoneInfoNotFoundError` and `ValueError` → `InvalidSchedule("timezone")`. `UTC` always valid (on Windows through the locked `tzdata`).
- Never-firing cron: `trigger.get_next_fire_time(None, <fixed reference>)` is None, or none within 5 years → refused.
- `next_fire(after)`: `trigger.get_next_fire_time(None, after + 1 µs)` then confirm `> after` (APScheduler returns a time ≥ now). DST follows the user's decision (decisions 2026-10-30, "DST behaviour for scheduled scans", superseding #128 (b)): APScheduler 3.11.3 already shifts a run in the spring gap to just after the missing hour, which is kept; it fires twice in the autumn repeat, so `next_fire()` drops a second occurrence of the same local wall time and the repeat runs once (TASK-191 r1). Pinned by TP-M9-07: Europe/London `30 1 * * *` fires at 01:30Z (02:30 BST) on 2026-03-29 and once, at 00:30Z, on 2026-10-25.

## 3. Repository interface (TASK-197, `bm/repositories/schedules.py`)

```python
@dataclass(frozen=True)
class ScheduleRow:
    schedule_id: int; name: str; policy_id: int; target: dict[str, Any]; cron: str
    timezone: str; enabled: bool; last_run_at: datetime | None; next_run_at: datetime | None
    created_by: int

def insert(conn, *, name, policy_id, target, cron, timezone, enabled, next_run_at, created_by) -> ScheduleRow
def get(conn, schedule_id: int, *, lock: bool = False) -> ScheduleRow | None
def page(conn, limit: int, after_id: int | None) -> list[ScheduleRow]
def update(conn, schedule_id: int, changes: Mapping[str, object]) -> ScheduleRow | None
    # only name, target, cron, timezone, enabled, next_run_at; column names from a fixed map (sql.Identifier)
def delete(conn, schedule_id: int) -> bool
def due(conn, now: datetime, limit: int = 100) -> list[ScheduleRow]
    # enabled AND next_run_at <= now ORDER BY next_run_at FOR UPDATE SKIP LOCKED LIMIT n
def previous_unfinished(conn, schedule_id: int) -> bool
    # the latest scan by created_at for this schedule_id has finished_at IS NULL (no index; scan is small)
def policy_state(conn, policy_id: int, *, share: bool = False) -> tuple[str, bool] | None   # (status, deleted)
    # share=True adds FOR SHARE on the policy row (create and enable, r1; decisions 2026-10-30
    # "M9 builder rulings" (5)), so a racing policy delete waits for the commit and then disables it
def mark_run(conn, schedule_id: int, *, ran_at: datetime | None, next_run_at: datetime) -> None
```

## 4. Admin service (TASK-201, `bm/services/scheduler/schedules_admin.py`)

`create`, `update`, `delete`, `get`, `list_page`, each taking `Tx`, the actor and `now`. Validation: `name` stored as given (not trimmed), 1–128 characters, no U+0000, no lone surrogate; `parse_target` (REQ-208); `parse_schedule`. Create and enable read `policy_state(..., share=True)`, taking the policy row `FOR SHARE` first (r1, decisions 2026-10-30 "M9 builder rulings" (5)): either a racing delete committed before (seen as deleted) or it waits and then disables the new or re-enabled schedule, so no enabled schedule of a deleted policy remains. Deleted → `ScheduleConflict` (409); unknown policy → `PolicyNotFound` (404). `next_run_at` = `next_fire(now)` on create, on a `cron`/`timezone` change and on `enabled: true`; `enabled: false` leaves it (ignored while disabled). Audit `scan_schedule.create|update|delete`, target `scan_schedule:<id>`, detail the changed field names and new values (the target and cron are not secret; no command text exists here).

## 5. Runner (TASK-203, `bm/services/scheduler/scan_schedules.py` and `runner.py`)

```python
TICK_S: Final = 30
MISSED_AFTER: Final = timedelta(minutes=2)
def run_due_schedules(db: Database, now: datetime, wake: Callable[[], None]) -> TickResult
```

Per due row, in its own transaction (`tx.on_commit(wake)`), the row locked by `due()`:
1. `nxt = next_fire(parse_schedule(row.cron, row.timezone), now)`.
2. `row.next_run_at < now - MISSED_AFTER` → log `missed` (fixed words, `schedule_id` only), `mark_run(ran_at=None, next_run_at=nxt)`.
3. The tick takes the schedule's policy row `FOR SHARE SKIP LOCKED` (TASK-203 r1; decisions 2026-10-30, "First result wins includes `completed` originals", which also accepts this change). If another session holds it (for example M7's policy delete), the schedule is **busy**: log `busy`, change nothing (no `mark_run`), and leave it due for the next 30 s tick. This removes a lock-order deadlock with the policy delete; it defers by one tick and is not a back-fill. Then: `previous_unfinished` → `previous_unfinished`; policy disabled → `policy_disabled`; (deleted: the schedule is already disabled by M7, but if seen, treat as `policy_disabled`).
4. Else `queue_scan(tx, policy_id=…, target=parse_target(row.target), trigger="scheduled", schedule_id=row.schedule_id, requested_by=None, actor="system", via_api_token=False, now=now)`; `NoTargetAgents` → skip `no_target_agents` in a savepoint so the bookkeeping still commits; other refusals → skip with the matching word: `PolicyDisabled` and `PolicyDeleted` → `policy_disabled`, `PolicyHasNoPlugins` → `policy_has_no_plugins` (decisions 2026-10-30, "M9 builder rulings" (4)).
5. `mark_run(ran_at=now if queued else None, next_run_at=nxt)` (not for a busy schedule).

A stored row whose cron or timezone no longer parses (only an owner write can cause it) is not disabled, since that would silently change user state: the tick logs `invalid` and moves `next_run_at` one day on. The tester pins this row.

`SchedulerRunner` (runner.py): a third `add_job(self.run_scan_schedules, "interval", seconds=TICK_S, id="scan_schedules", max_instances=1, coalesce=True, misfire_grace_time=TICK_S, next_run_time=first)`, wrapped by `_guarded` and the stoppable database like the other two jobs. No `system_schedule` row is added (no migration; the tick is not a runtime setting).

## 6. Edge cases (tests: TP-M9-07, TP-M9-14)

- Restart: nothing special at start-up; the first tick sees overdue rows and treats those older than 2 minutes as missed (no back-fill).
- Two ticks (a stalled one and the next): `max_instances=1` in-process, `SKIP LOCKED` across sessions; the barrier test uses two sessions.
- `finished_at` lags up to one sweep (#127 (f)), so a schedule firing every minute may skip runs while the previous scan's state settles; accepted and documented in the README.
