# TASK-202 IMPL: `offline_sweep` compliance steps and the scan state refresh (design note D3)

Implementer: impl-manager-m9. REQ-218, REQ-219, REQ-228, REQ-229. Risk high. Spec: TS §3.3 L218, §4.4 L571–L582. Answers applied: #18, #22, #126, #127. Built on TASK-186 (`states`), 187 (`scan_state`), 189 (`build.retry`), 194 (`repositories/scan_progress.py`) and 196 (`repositories/job_sweep.py`); the repositories are impl-manager-m9b's.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/scheduler/sweep.py` (M3 file, +187 / −7) | `ComplianceRepos`, `Stores.compliance`, `SweepResult` counters, three steps appended to `STEPS` |

No other file changed. **Over the 140 estimate (~180 hand-written lines).** The cause is the `ComplianceRepos` adapter (~50 lines of one-line delegations). The plan asks for the new repositories "as protocols" on `Stores` so unit tests can pass fakes, and an adapter class is the smallest typed form of that. The rest is the three steps (~90 lines) and the docstring.

## Interface

```python
class ComplianceRepos:                       # job_sweep + scan_progress over one conn; subclass to fake
    past_deadline(now) / never_started(now, after) / lock_for_sweep(job_id) /
    unit_result_uuids(job) / end_job(job_id, state, now) /
    insert_retry(original, job_id, payload, eval_spec, now)   # pickup_by = now + 24 h /
    refresh_candidates(now) / lock_scan(scan_id) / unit_facts(scan_ids) /
    set_scan_state(scan_id, state, finished_at)
@dataclass(frozen=True)
class Stores: tx; agents; jobs; settings; audit; compliance: ComplianceRepos | None = None
SweepResult += deadline_ended, never_started_failed, retries, scans_refreshed   (all int = 0)
STEPS += ("compliance_deadline", ...), ("never_started", ...), ("scan_states", ...)
```

`compliance=None` means `ComplianceRepos(s.tx.conn)`. So every M3 `Stores(...)` built with five arguments (`test_sweep_pg.py`, `test_metrics_api_pg.py`) and `dataclasses.replace(pg_stores(tx), ...)` still run the compliance steps on real PostgreSQL. `pg_stores` sets the field explicitly. `runner.py` is unchanged (it calls `run_sweep(db, now, lambda tx: pg_stores(...))`).

## Steps (each in its own transaction, like M3)

- **`compliance_deadline`:**
  - For each `past_deadline(now)` id, `lock_for_sweep` locks the root, then the job, with `SKIP LOCKED` (None means skip).
  - Re-checked under the lock: state `dispatched`/`running`, `deadline_at` set and `deadline_at < now` (strict, #127 (b)).
  - `have = unit_result_uuids(job) ∩ payload plugins`, then `state = after_deadline(any_result, all_have_results)`. If `states.allowed(job.state, state)` holds, `_end`.
- **`never_started`:**
  - For each `never_started(now, NEVER_STARTED_AFTER)` id, `lock_for_sweep`.
  - Re-checked: state `dispatched`, `started_at` NULL, `dispatched_at < now − 24 h` (strict).
  - Then `_end(..., "failed")`. No batch was ever accepted, so `failed` (`dispatched → failed` is the only allowed ending). The unit's results still decide the retry's plugins.
- **`_end`:**
  - `end_job` (conditional on `dispatched`/`running`). If it changed no row, nothing more happens, so two sweeps give one retry (#126 (c)).
  - Then, only when the state is `failed`/`partial`, the job is an original (`retry_of` NULL), the policy is not deleted and the agent is not decommissioned (#126 (d)): `build.retry(job.payload, job.eval_spec, missing in payload order, job_id=uuid4(), created_at=now, original_is_retry=False)` and `insert_retry` in **the same transaction**.
  - A disabled policy still gets its retry (#18).
  - The commands are the original's, never the catalog's (#126 (a)).
- **`scan_states`:**
  - `refresh_candidates(now)` (8-day window, #127 (f)), each scan row locked `FOR UPDATE` in `scan_id` order.
  - Then **one** `unit_facts` read of `scan_job` for all of them, `derive()` per scan, and `set_scan_state` **only** when the derived state differs, or the scan has just finished and has no `finished_at` yet (REQ-219 (4)).
  - **Addition: the scan row lock.** Without it, a cancel committing between our read and our write could be overwritten by a stale derivation for up to one sweep (checklist 9). Cancel locks the scan row too.
- `max_parallel_plugins` is not read: the deadline was fixed at the start (REQ-217 (1)). No new query touches `kind = 'inventory'`, and the M3 four steps are unchanged.

## For the tester (tester-m9b): M3 unit tests affected

`manager/tests/test_sweep.py` uses a `FakeDb` whose tx has no `.conn` and builds `Stores(tx, self, self, self, self)`. The three new steps therefore fail there (`AttributeError`), so `(db.commits, db.rollbacks) == (4, 0)`, `failed_steps == []` and `len(w.calls) == 4` no longer hold. Pass a `ComplianceRepos` subclass fake as the sixth `Stores` argument and expect seven steps. This follows from REQ-218 adding steps, not from lowering a gate. Please list it in `tests/m9/report.md` (the M3 sweep regression item in TP-M9-15). The PostgreSQL M3 sweep suites need no change.

## Plants

- CHK-M9-339: `<=` in the deadline re-check (and in TASK-196's query).
- CHK-M9-340: `dispatched_at` replaced by `created_at`.
- CHK-M9-341: drop `job.retry_of is not None`.
- CHK-M9-342: not reachable here (a `partial` from a final batch is not `dispatched`/`running`); the guard is the state re-check.
- CHK-M9-344: the retry is built from `job.payload` only.
- CHK-M9-345: move `insert_retry` into its own `db.transaction()`.
- CHK-M9-346: ignore `end_job`'s result.
- CHK-M9-363: TASK-194's candidates.
- REQ-219 (4): drop the unchanged check (an UPDATE per candidate).

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`) on `manager/bitscan_manager`: pass. `import bitscan_manager.services.scheduler.runner` works.

## Revision 1 (2026-10-30): one savepoint per job (REVIEW should-fix)

reviewer-m9 found that `compliance_deadline` and `never_started` handled every candidate in the step's one transaction. One poison job then rolled back the whole step, and since `past_deadline` orders by `deadline_at`, the same job came first on every sweep. A poison job here means one of:
- an `eval_spec` that `parse_eval_spec`/`build.retry` rejects;
- a payload where `_planned()` raises;
- a failing `insert_retry`.

No compliance job anywhere would then ever end or retry.

The fix:
- **Per-job savepoint:** `_each_job()` runs each candidate's lock, end and retry inside `with c.savepoint():` (a new `ComplianceRepos.savepoint()`, which is `conn.transaction()`, so a savepoint inside the step's transaction). End and retry stay atomic per job (CHK-M9-345 still holds).
- **On an exception:** that job's savepoint rolls back. It is logged as `"sweep job failed"` with `{step, job_id, exc_type}` only (never the message or any job content), and the loop continues. The job is retried by the next sweep, and the other jobs still end. This fails closed per job, as intake does (#124 (h)).
- **Restructure:** the per-job logic moved into `_deadline_job()` and `_never_started_job()`. `_end()` now returns `(ended, retries)`.
- **Review nit:** `deadline_ended` and `never_started_failed` now count only jobs whose `end_job` changed the row.
- **Fakes:** a fake `ComplianceRepos` that returns candidates must override `savepoint()`, for example with `contextlib.nullcontext()`. Otherwise every job fails (and is logged) on the missing connection. tester-m9b's `FakeCompliance` returns no candidates, so it is unaffected.

`sweep.py` is now +238/−7 against `d09c537`; the revision adds about 50 lines. Gates on `manager/bitscan_manager`: ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass. The `--platform linux` run also reports errors in tester files only (`test_readme_m9_walk_linux.py`).

Suggested plants: remove the savepoint (one poison job then leaves the healthy one un-ended); log `str(exc)`; count `deadline_ended` without `done`.
