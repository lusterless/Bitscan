# TASK-202 plan: `offline_sweep` compliance steps and scan refresh (design note D3), with the TASK-187, 194 and 196 interfaces

Planner: planner-m9, 2026-10-30. REQ-207, REQ-218, REQ-219, REQ-228, REQ-229. Open items: #18, #22, #126, #127.

## 1. Spec quotes

- TS §3.3 L218: "The `offline_sweep` task (every 60 s) updates status, and also applies job timeouts and creates retries (§4.4)."
- TS §4.4 L575: "The deadline is the start time + ceil(Σ `timeout_s` ÷ `max_parallel_plugins`) + 10 min … A dispatched job that never starts fails 24 h after dispatch and gets the same single retry as any failed job … dispatched or running jobs past their deadline become `failed` or `partial`."
- TS §4.4 L577: "When a job ends `failed` or `partial` because its deadline passed … the manager creates one retry … holding only the plugins with no result. A retry is never retried."
- TS §4.4 L579–L580: scan finished and scan state rules.

## 2. Pure interface (TASK-187, `bm/services/jobs/scan_state.py`)

```python
@dataclass(frozen=True, slots=True)
class Unit:
    open: bool            # a job of the unit is queued, dispatched or running
    complete: bool        # every plugin of the original's payload has a result in the unit
    has_results: bool
    any_cancelled: bool
    all_queued: bool      # every job of the unit is still queued

ScanState = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
def derive(units: Sequence[Unit]) -> tuple[ScanState, bool]   # (state, finished); ValueError on empty
```

Rule (#127 (d)): any open → (`queued` if all units `all_queued` else `running`, False); else all complete → `completed`; else any has_results → `partial`; else any cancelled → `cancelled`; else `failed`; finished True.

## 3. Repository interfaces

`bm/repositories/scan_progress.py` (TASK-194):

```python
def refresh_candidates(conn, now: datetime, window: timedelta = timedelta(days=8)) -> list[UUID]
    # SELECT scan_id FROM scan WHERE finished_at IS NULL
    #    OR (state <> 'completed' AND created_at > %(now)s - %(window)s)
def unit_facts(conn, scan_ids: Sequence[UUID]) -> dict[UUID, list[Unit]]
    # ONE statement: jobs of those scans (kind='compliance', scan_id = ANY), grouped by
    # COALESCE(retry_of, job_id); results counted by EXISTS / count(DISTINCT plugin_uuid)
    # over the unit's jobs (joined on job_id and job_created_at); complete compares with
    # jsonb_array_length(root.payload->'plugins')
def scan_row(conn, scan_id: UUID, *, lock: bool = False) -> tuple[str, datetime | None] | None
def set_scan_state(conn, scan_id: UUID, state: str, finished_at: datetime | None) -> bool
    # UPDATE scan SET state = CAST(%s AS scan_state), finished_at = COALESCE(finished_at, %s)
    # WHERE scan_id = %s AND (state, finished_at) IS DISTINCT FROM (…)
def cancel_open_jobs(conn, scan_id: UUID, now: datetime) -> list[UUID]
    # state IN ('queued','dispatched','running') -> 'cancelled', finished_at = now
```

`unit_facts` reads `scan_job` once per call (no `scan_id` index; #127 (f)). The sweep calls it once per run with every candidate.

`bm/repositories/job_sweep.py` (TASK-196):

```python
@dataclass(frozen=True)
class SweepJob:
    job_id: UUID; root_id: UUID; retry_of: UUID | None; scan_id: UUID; agent_id: UUID
    state: str; payload: dict[str, Any]; eval_spec: Any; created_at: datetime
    policy_deleted: bool; agent_decommissioned: bool

def past_deadline(conn, now: datetime, limit: int = 1000) -> list[UUID]
    # kind='compliance' AND state IN ('dispatched','running') AND deadline_at < now
def never_started(conn, now: datetime, after: timedelta, limit: int = 1000) -> list[UUID]
    # kind='compliance' AND state='dispatched' AND started_at IS NULL AND dispatched_at < now - after
def lock_for_sweep(conn, job_id: UUID) -> SweepJob | None
    # root FOR UPDATE SKIP LOCKED, then the job FOR UPDATE SKIP LOCKED; None if either is held;
    # joins scan -> policy (deleted_at) and agent (status)
def unit_result_uuids(conn, job: SweepJob) -> set[UUID]     # job and sibling (sibling as in TASK-195)
def end_job(conn, job_id: UUID, state: str, now: datetime) -> bool
    # UPDATE … WHERE job_id = %s AND state IN ('dispatched','running')  (rowcount 1 = this sweep ended it)
def insert_retry(conn, *, original: SweepJob, job_id: UUID, payload, eval_spec, created_at, pickup_by) -> None
```

## 4. Service (`bm/services/scheduler/sweep.py`, TASK-202)

Three steps appended to `STEPS` after the M3 four, each in its own transaction (the M3 isolation is kept):
- `compliance_deadline`: for each id of `past_deadline`, `job = lock_for_sweep(...)` (skip None); re-check `deadline_at < now` and the state; `have = unit_result_uuids(job)`; `state = after_deadline(any_result = bool(have & job uuids), all_have_results = job uuids <= have)`; `end_job(...)`; when `state in {'failed','partial'}` and `job.retry_of is None` and not `policy_deleted` and not `agent_decommissioned`: `payload, spec = build.retry(job.payload, job.eval_spec, missing, job_id=uuid4(), created_at=now, original_is_retry=False)` and `insert_retry(...)` with `pickup_by = now + 24 h`.
- `never_started`: same with `never_started(conn, now, timedelta(hours=24))`; outcome `failed` (no batch was ever accepted, so no result exists in this job; the sibling cannot exist yet).
- `scan_states`: `ids = refresh_candidates(...)`; `facts = unit_facts(ids)`; for each scan, `derive()` and `set_scan_state(...)` only on change.

`SweepResult` gains `deadline_ended`, `never_started_failed`, `retries`, `scans_refreshed`. `SweepJobs` and `Stores` gain the new repositories as protocols (the M3 `pg_stores` factory adds them), so the unit tests keep passing fakes.

## 5. Edge cases (tests: TP-M9-15)

- Exactly once retry: `end_job` only succeeds from `dispatched`/`running`, so a second sweep finds nothing; the barrier test runs two sweeps.
- Deadlock freedom: root then job, `SKIP LOCKED`, the same order as intake; a skipped job is handled next sweep.
- A fault after `end_job` and before `insert_retry` rolls both back (same transaction), so the next sweep retries the whole step (CHK-M9-345).
- `max_parallel_plugins` is not read here: the deadline was fixed at the start transition (REQ-217 (1)).
- Inventory jobs: no new query matches `kind = 'inventory'`; the M3 `inventory_timeout` step is unchanged.
- A policy delete (M7) cancels queued jobs without touching `scan`; `scan_states` picks the scan up (`finished_at` NULL) on the next run.
