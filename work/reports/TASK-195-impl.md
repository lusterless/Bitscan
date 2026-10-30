# TASK-195 IMPL: result intake repository

Implementer: impl-manager-m9b, 2026-10-30. REQ-215, REQ-216, REQ-217, REQ-230. Open items #124 (c), #127 (f). Plan: `work/plans/TASK-199.md` §3. TS §8.2 second approval (PD-39).

## Files

- `manager/bitscan_manager/repositories/job_intake.py` (new, 196 lines including the INSERT text).

No other file changed.

## Interface

```python
@dataclass(frozen=True)
class IntakeJob: job_id; kind; agent_id; scan_id: UUID | None; retry_of: UUID | None; state: str
                 created_at; dispatched_at | None; started_at | None; payload: dict; eval_spec: Any

def lock_unit(conn, job_id: UUID) -> IntakeJob | None
def sibling(conn, job: IntakeJob) -> tuple[UUID, datetime] | None
def result_uuids(conn, jobs: Sequence[tuple[UUID, datetime]]) -> set[UUID]
def insert_results(conn, job: IntakeJob, rows: Sequence[ResultRow], received_at: datetime) -> int
def start(conn, job_id, started_at, deadline_at) -> bool
def set_state(conn, job_id, state: str, finished_at: datetime | None) -> bool
```

**Differences from plan §3 (please test against these):**
- `sibling_id() -> UUID | None` became `sibling() -> (job_id, created_at) | None`: the plan's `result_uuids` takes `(job_id, job_created_at)` pairs for partition pruning, so the sibling's `created_at` is needed and `IntakeJob` does not hold it.
- `start` and `set_state` return `bool` (rowcount 1) instead of `None`.
- `start` also requires `state = 'dispatched'` (not only `started_at IS NULL`), so a never-started job the sweep failed can never be moved back to `running`.
- `set_state` accepts only `running`, `completed`, `partial` (else `ValueError`) and only moves a job from `dispatched`, `running`, `failed` or `partial`: a final state is never left (defence in depth; the job is locked by `lock_unit` in the same transaction).

`ResultRow` is imported from the pure `services/jobs/intake_plan.py` (TASK-190).

## How it meets the acceptance points

- **Root, then job, FOR UPDATE:** (1) `SELECT COALESCE(retry_of, job_id)` without a lock (stable: no grant on `retry_of`); (2) when the posted job is a retry, `SELECT 1 … WHERE job_id = <root> FOR UPDATE`; (3) the posted job `… FOR UPDATE` with payload and `eval_spec`. For an original, (3) is the root lock. A second session posting to the same unit waits at its root lock; after the wait it re-reads (READ COMMITTED) and sees the first's rows through `result_uuids`.
- **Sibling (#127 (f)):** a retry's original by primary key; an original's retry (`WHERE retry_of = %s`, a full read since no index exists) only when the original is `failed` or `partial`, the only states in which a retry can exist.
- **Unit result uuids:** one statement over `unnest(job_ids, created_ats)` joined to `scan_result` on `job_id` and `job_created_at` (partition key given).
- **One INSERT per batch:** `INSERT INTO scan_result (...) SELECT %(job)s, %(created)s, t.… FROM unnest(14 typed arrays)`; `job_created_at` = the job's `created_at` (the trigger accepts it), `received_at` = the caller's (manager) clock, `operator_snap` `CAST(... AS plugin_operator)`; `result` is generated and never written. No rows → 0 without SQL.
- **Start once:** `UPDATE … SET state = 'running', started_at, deadline_at WHERE job_id = %s AND state = 'dispatched' AND started_at IS NULL`.
- No UPDATE or DELETE on `scan_result`; on `scan_job` only `state`, `started_at`, `deadline_at`, `finished_at`. Every statement is parameterised.
- The module logs nothing; no stdout, stderr or command text appears in any error it raises.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour (two-session lock wait, trigger, one statement) is for the tester (TP-M9-10).

## Plants for the tester (mutation table)

- CHK-M9-320: remove `FOR UPDATE` from `_JOB` and from the root lock in `lock_unit`.
- CHK-M9-321: skip step (2) (lock only the posted job).
- CHK-M9-334: drop `AND started_at IS NULL` and `AND state = 'dispatched'` in `start`.
- CHK-M9-322 (repository side): `sibling` returns None always.
- CHK-M9-376: an f-string query.

## Revision 1 (2026-10-30, after tester-m9b's TEST FAIL)

**Cause:** `sibling()` looked for an original's retry only when the original was `failed` or `partial`. An original that ended `failed`/`partial` at its deadline gets a retry, and a late batch can then make it `completed` (TS §4.4 L577, L582). After that `sibling()` returned None, so a post to the completed original no longer saw the retry's results and stored a second result for a plugin the retry already held (breaks L578, REQ-216 (2)).

**Fix:** `sibling()` now searches `WHERE retry_of = %s` for every original in `failed`, `partial` or `completed` (`_MAY_HAVE_RETRY`); a dispatched or running original cannot have a retry yet. The docstring's reasoning is corrected. Cost: a post to a `completed` original (duplicates only) now also does the full `retry_of` read (#127 (f)).

Only `manager/bitscan_manager/repositories/job_intake.py` changed. Gates green. The planner's note "sibling looked up only when the posted job is a failed or partial original" (#127 (f), plan TASK-199 §3) is stale; I've reported it to `main` (the planner owns that file).

Plant: put `_MAY_HAVE_RETRY` back to `{"failed", "partial"}`; `test_a_completed_original_still_sees_its_retrys_results` and the two `sibling` rows must turn red.
