# TASK-203 IMPL: scheduled runs and the scheduler tick

Implementer: impl-manager-m9b, 2026-10-30. REQ-225, REQ-227. Open items #3, #128 (d)–(g). Plan: `work/plans/TASK-203.md` §5 (design note D4).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/scheduler/scan_schedules.py` | new, 144 lines: `TICK_S`, `MISSED_AFTER`, `INVALID_RETRY`, `TickResult`, `run_due_schedules()` |
| `manager/bitscan_manager/services/scheduler/runner.py` | +30 / −9: third job `scan_schedules` every `TICK_S` (30 s), `run_scan_schedules()` through `_guarded` and the stoppable database; worker threads 2 → 3; docstring |

Builds on TASK-191 (`cron`), TASK-197 (`repositories/schedules`), TASK-198 (`queue.queue_scan` and its refusals), TASK-188 (`parse_target`).

## Interface

```python
TICK_S: Final = 30
MISSED_AFTER: Final = timedelta(minutes=2)
INVALID_RETRY: Final = timedelta(days=1)
@dataclass
class TickResult: queued: int = 0; skipped: Counter[str]; failed: int = 0
def run_due_schedules(db: Database, now: datetime, wake: Callable[[], None]) -> TickResult
SchedulerRunner.run_scan_schedules() -> None      # job id "scan_schedules"
```

## Behaviour (plan §5)

Loop, one transaction per due row (`tx.on_commit(wake)`): `schedules.due(conn, now, limit=len(failed) + 1)` (enabled, `next_run_at <= now`, `FOR UPDATE SKIP LOCKED`), first row not already failed in this tick, then:

1. `nxt = next_fire(parse_schedule(cron, timezone), now)` and `parse_target(row.target)`. If either fails (only an owner write can cause it): `next_run_at = now + 1 day`, `last_run_at` kept, log `invalid`; the schedule is not disabled.
2. `next_run_at < now - 2 min` → `missed` (no back-fill, #128 (e)).
3. `previous_unfinished` → `previous_unfinished`.
4. `policy_state` disabled or deleted → `policy_disabled` (deleted is not expected: M7 disables those schedules).
5. Else `queue_scan(tx, trigger="scheduled", schedule_id, requested_by=None, actor="system", via_api_token=False, now=now)` inside a savepoint (`conn.transaction()`); its refusals become skips: `PolicyDisabled`/`PolicyDeleted` → `policy_disabled`, `NoTargetAgents` → `no_target_agents` (#3), `PolicyHasNoPlugins` → `policy_has_no_plugins`.
6. `mark_run(ran_at = now if queued else None, next_run_at = nxt)`.

Every skip and miss writes no scan and no audit entry, and logs `scheduled run skipped` with `{"schedule_id", "reason"}` only. A queued scan's single `scan.create` entry (actor `system`) comes from `queue_scan`; it never raises the API-token alert.

**Termination and failure handling:** every handled row gets `next_run_at > now` (`next_fire` is strictly after `now`), so the loop ends within the tick. A row whose transaction raises (anything else) is rolled back, logged `scheduled run failed` with `{"schedule_id", "exc_type"}`, and not tried again in this tick (next tick retries it), so one bad row cannot block the others. A failure before a row is chosen (database down, `SchedulerStopping` on stop) ends the tick and reaches the runner's `_guarded` (job name and exception type only), so `stop()` still waits for a running tick and the tick gives up at its next row (builder checklist 10).

**Runner:** `add_job(self.run_scan_schedules, "interval", seconds=30, id="scan_schedules", max_instances=1, coalesce=True, misfire_grace_time=30, next_run_time=<start>)`. No `system_schedule` row (no migration; the tick is not a runtime setting). Three worker threads, so a long sweep and an inventory run cannot starve the tick.

## M3 checks this changes (for the tester, by requirement REQ-225)

- `manager/tests/test_scheduler_runner.py::test_start_adds_both_jobs_from_system_schedule_running_now` and `test_start_uses_the_seeded_intervals_when_the_database_is_unreadable` assert the job set is exactly `{inventory, offline_sweep}`; it is now `{inventory, offline_sweep, scan_schedules}` (30 s).
- `manager/tests/test_serve_scheduler_linux.py` (around line 423) accepts `SchedulerStopping` failures only for `offline_sweep` and `inventory`; a tick running at stop may log one for `scan_schedules`.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager/bitscan_manager`: green (176 files). The runner and the app import cleanly in a fresh interpreter. PostgreSQL behaviour is for the tester (TP-M9-14).

## Plants (mutation table)

- CHK-M9-370: `parse_schedule(row.cron, "UTC")`.
- CHK-M9-371: drop the `missed` branch (back-fill after a clock jump).
- CHK-M9-372: drop the `previous_unfinished` branch.
- CHK-M9-373: in `repositories/schedules.due` (TASK-197).
- REQ-225 (3): drop the `policy_state` pre-check and the `PolicyDisabled` mapping together.
- REQ-225 (8): remove `_guarded` from `run_scan_schedules`, or re-raise per-row failures.

## Revision 1 (2026-10-30, a deadlock found while doing TASK-197/201 r1)

**Cause:** the tick holds its schedule row (`due()`, `FOR UPDATE`), and `queue_scan` then takes the policy row `FOR SHARE`. M7's policy delete locks the policy row (`UPDATE policy`) and then updates that schedule row (`UPDATE scan_schedule SET enabled = false`). A delete during a tick of one of that policy's schedules could deadlock, and PostgreSQL would abort one side, possibly the admin's delete.

**Fix:** before `queue_scan`, `_run` calls `schedules.try_share_policy()` (`FOR SHARE SKIP LOCKED`). When another session holds the policy row (a delete, import or status change), it returns `BUSY` and writes nothing. The loop leaves that row due, excludes it for the rest of this tick and counts `TickResult.busy`; the next tick (30 s) tries again. A row busy for more than 2 minutes becomes `missed`, as any late run does. With the share already held, `queue_scan`'s own `FOR SHARE` is granted at once. The tick never waits for the policy while holding the schedule row.

Files: `services/scheduler/scan_schedules.py` (+ `BUSY`, `TickResult.busy`) and `repositories/schedules.py` (`try_share_policy`, TASK-197 r1). Gates green.

Plant: replace `try_share_policy` by a plain `FOR SHARE` (or remove the check). A policy delete held at a barrier during a tick then deadlocks (`DeadlockDetected` on one side).
