# TASK-199 plan: result intake (design note D2), with the TASK-186, 190 and 195 interfaces

Planner: planner-m9, 2026-10-30. REQ-206, REQ-214 to REQ-217, REQ-226, REQ-227. Open items: #12, #116 (d), #121, #124, #127 (a)–(c), #129 (c). Two approvals (PD-39) for TASK-190, 195, 199 and 204.

## 1. Spec quotes

- TS §6.1 L1071: "A result post is accepted only for a job addressed to that agent, within `dispatched_at` + 7 days, and only for plugin ids listed in that job; anything else returns 409 and is audit-logged. A second result for the same plugin is ignored (first wins)."
- TS §4.4 L578: "For each host and plugin in a scan, the first result to arrive wins, whether it came from the original job or the retry. The API enforces this by locking the original job row (`SELECT … FOR UPDATE` on `COALESCE(retry_of, job_id)`) while inserting, and skipping plugins that already have a result in the original job or its retry. `scan_result.job_created_at` is always copied from `scan_job.created_at`."
- TS §4.4 L581: "dispatched or running jobs become `cancelled`, and later result posts for them get 409 `job_not_acceptable` and are not stored."
- TS §4.5 L587: "against the `eval_spec` recorded when the job was queued … stores the result and its verdict in one insert." L603: snapshots "from the job's `eval_spec` and payload".
- TS §3.3 L222: the empty batch "moves the job to `running` and starts its deadline (§4.4); only the first start notice counts."

## 2. Pure interfaces

`bm/services/jobs/states.py` (TASK-186):

```python
JobState = Literal["queued","dispatched","running","completed","partial","failed","cancelled","expired"]
FINAL: Final = frozenset({"completed", "expired", "cancelled"})
ACCEPTING: Final = frozenset({"dispatched", "running", "failed", "partial", "completed"})
LATE_WINDOW: Final = timedelta(days=7)
DEADLINE_SLACK: Final = timedelta(minutes=10)

def deadline_at(started_at: datetime, timeouts: Sequence[int], max_parallel: int) -> datetime
    # started + timedelta(seconds = -(-sum(timeouts) // max_parallel)) + 10 min; ValueError on mpp ∉ 1..8 or empty
def accepts_results(kind: str, state: str, dispatched_at: datetime | None, now: datetime) -> bool
@dataclass(frozen=True)
class BatchOutcome: state: JobState; start: bool        # start = set started_at/deadline_at now
def after_batch(state: JobState, *, stored: int, all_have_results: bool, final: bool) -> BatchOutcome
def after_deadline(*, any_result: bool, all_have_results: bool) -> JobState   # completed | partial | failed
```

`after_batch` (#127 (a), #124 (d)): `dispatched` → start; then completed if all, partial if final, else running. `running` → completed / partial (final) / running. `failed`/`partial`: `stored == 0` → unchanged; else completed if all, else partial. `completed` → completed. Any other state raises (callers check `accepts_results` first).

`bm/services/jobs/intake_plan.py` (TASK-190):

```python
@dataclass(frozen=True)
class ResultRow:                  # one INSERT row, values only
    plugin_uuid: UUID; eval_code: int; eval_detail: str | None
    exit_code: int | None; stdout: str; stderr: str; timed_out: bool; truncated: bool
    plugin_name_snap: str; execute_snap: str; operator_snap: str; expected_snap: str
    started_at: datetime; finished_at: datetime

class PluginNotInJob(Exception): ...

@dataclass(frozen=True)
class Plan: rows: tuple[ResultRow, ...]; duplicates: int

def storable(text: str) -> str          # #121 (c): U+0000 and lone surrogates -> U+FFFD
def plan(spec: EvalSpec, payload_plugins: Mapping[UUID, str],   # uuid -> execute, from payload
         existing: Collection[UUID], items: Sequence[ResultLike]) -> Plan
```

Order inside `plan`, per item: (1) membership: a uuid not in `payload_plugins` or with no `spec.get(uuid)` → raise `PluginNotInJob` (the whole batch, #124 (a)); checked for every item before any row is built. (2) Duplicate if in `existing` or already planned in this batch. (3) `verdict = result_verdict(entry, item)` on the **received** text (caps measured as sent, #121 (b)); (4) if `verdict.detail is Detail.OVERSIZE`: stdout and stderr `""` (#116 (d)); otherwise `storable(stdout)`, `storable(stderr)` and, when either changed, the verdict is recomputed on the replaced text through `result_verdict` with a proxy whose `stdout`/`stderr` are the replaced values, so the stored text is the evaluated text (#121 (c)). (5) Snapshots: `name`, `operator`, `expected` from `entry`; `execute` from `payload_plugins`.

Lone surrogate detection: `ch` in `\ud800`–`\udfff` (Python strings from `json.loads` hold them as single code points). Use `"".join` over a translation; no regex needed.

## 3. Repository interface (TASK-195, `bm/repositories/job_intake.py`)

```python
@dataclass(frozen=True)
class IntakeJob:
    job_id: UUID; kind: str; agent_id: UUID; scan_id: UUID | None; retry_of: UUID | None
    state: str; created_at: datetime; dispatched_at: datetime | None
    started_at: datetime | None; payload: dict[str, Any]; eval_spec: Any

def lock_unit(conn, job_id: UUID) -> IntakeJob | None
    # 1. SELECT COALESCE(retry_of, job_id) FROM scan_job WHERE job_id = %s          (no lock)
    # 2. SELECT … FROM scan_job WHERE job_id = <root> FOR UPDATE
    # 3. if job_id != root: SELECT … FROM scan_job WHERE job_id = %s FOR UPDATE
    # returns the posted job (None if unknown). retry_of never changes (no grant), so step 1 is stable.
def sibling_id(conn, job: IntakeJob) -> UUID | None
    # job.retry_of if set; else, only when job.state in ('failed','partial','completed')
    # (a late result can complete an original after its retry exists; decisions 2026-10-30,
    # "First result wins includes completed originals"):
    # SELECT job_id FROM scan_job WHERE retry_of = %s (full read: no index, #127 (f)); else None
    # (a dispatched or running original cannot have a retry yet)
def result_uuids(conn, jobs: Sequence[tuple[UUID, datetime]]) -> set[UUID]
    # by (job_id, job_created_at) so partitions are pruned
def insert_results(conn, job: IntakeJob, rows: Sequence[ResultRow], received_at: datetime) -> int
    # ONE INSERT … SELECT FROM unnest(...) ; operator_snap CAST AS plugin_operator; job_created_at = job.created_at
def start(conn, job_id, started_at, deadline_at) -> None
    # UPDATE … SET state='running', started_at=%s, deadline_at=%s WHERE job_id=%s AND started_at IS NULL
def set_state(conn, job_id, state, finished_at: datetime | None) -> None
```

## 4. Service (`bm/services/jobs/intake.py`)

```python
@dataclass(frozen=True)
class Accepted: accepted: int; duplicates: int
@dataclass(frozen=True)
class Refused: reason: Literal["job_not_acceptable", "eval_spec_invalid"]; own_cancelled: bool
def accept_results(db: Database, *, agent_id: UUID, job_id: UUID, batch: ResultsRequest,
                   now: datetime) -> Accepted | Refused
    # max_parallel_plugins is read with read_settings(SettingsRepo(tx.conn)) inside the transaction
```

One `db.transaction()`:
1. `job = lock_unit(conn, job_id)`; refuse when None, `job.agent_id != agent_id`, `job.kind != 'compliance'`, or `not accepts_results(...)`. `own_cancelled = job.state == 'cancelled'` (the agent matches) for #124 (f).
2. `spec = parse_eval_spec(job.eval_spec)`; `EvalSpecError` → `Refused("eval_spec_invalid")`, logged with the exception type only.
3. `existing = result_uuids([job] + [sibling])`.
4. `p = plan(spec, payload_plugins(job.payload), existing, batch.results)`; `PluginNotInJob` → refuse.
5. `insert_results(...)` (skipped when no rows); `have = existing | {r.plugin_uuid for r in p.rows}`; `all_have = set(job's payload uuids) <= have`.
6. `out = after_batch(job.state, stored=len(p.rows), all_have_results=all_have, final=batch.final)`; if `out.start`: `start(conn, job_id, now, deadline_at(now, timeouts, max_parallel_plugins))`; if the state changed, `set_state(..., finished_at=now if out.state in {'completed','partial','failed'} else None)`.
7. `tx.on_commit(lambda: PLUGIN_RESULTS.labels(result).inc(n))` per result label (REQ-226).

A `Refused` returns after the transaction rolls back; the route then calls M3's `refuse_results` in its own transaction, passing `own_cancelled` so the flood window is skipped (the one change to `refuse_results`'s call site, not its module: TASK-204 adds a `count_flood: bool = True` keyword in `services/jobs/pull.py`, which it owns).

`services/audit/metrics.py`: `PLUGIN_RESULTS = Counter("bitscan_plugin_results", "Stored plugin results by verdict.", ["result"], registry=REGISTRY)`, with `PASS`, `FAIL`, `ERROR` labelled from zero.

## 5. Edge cases (tests: TP-M9-06, TP-M9-12, TP-M9-16)

- Concurrent original and retry posts: both lock the root first; the second sees the first's row in `result_uuids` after the first commits (READ COMMITTED re-read after the lock wait).
- The sweep marks the same root failed while a post holds it: the sweep's lock waits (or skips with SKIP LOCKED); after our commit it re-checks state and deadline.
- A start notice for a `failed` job: accepted `{0, 0}`, nothing changes.
- The route must not log stdout/stderr; the log line carries `agent_id`, `job_id`, `accepted`, `duplicates` only.
