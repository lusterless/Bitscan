# TASK-199 IMPL: result intake service and the plugin results counter

Implementer: impl-manager-m9b, 2026-10-30. REQ-214, REQ-215, REQ-216, REQ-217, REQ-226, REQ-227. Open items #12, #116 (d), #121, #124, #127 (a), (c), #129 (c). Plan: `work/plans/TASK-199.md` §4 (design note D2). TS §8.2 second approval (PD-39).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/intake.py` | new, 138 lines |
| `manager/bitscan_manager/services/audit/metrics.py` | +14 lines: `PLUGIN_RESULT_LABELS`, `PLUGIN_RESULTS` (exported as `bitscan_plugin_results_total{result}`), every label from zero; docstring names the new fixed label set |

No other file changed. Builds on TASK-186 (`states`), TASK-190 (`intake_plan`), TASK-195 (`repositories/job_intake`), M8 `parse_eval_spec`, M3 `read_settings`/`SettingsRepo`.

## Interface

```python
class IntakeBatch(Protocol):            # api.agent.schemas.ResultsRequest satisfies it (checked with mypy)
    results: Sequence[IntakeItem]; final: bool   # read-only properties
@dataclass(frozen=True) class Accepted: accepted: int; duplicates: int
@dataclass(frozen=True) class Refused:  reason: Literal["job_not_acceptable", "eval_spec_invalid"]; own_cancelled: bool
def accept_results(db: Database, *, agent_id: UUID, job_id: UUID, batch: IntakeBatch, now: datetime) -> Accepted | Refused
```

The plan typed `batch` as `ResultsRequest`; a service cannot import the API layer, so `IntakeBatch` is a structural protocol over it.

## Order inside the one transaction (plan §4)

1. `lock_unit` (root `FOR UPDATE`, then the posted job `FOR UPDATE`).
2. Refused `job_not_acceptable` when: unknown job; `agent_id` differs; `accepts_results(kind, state, dispatched_at, now)` false (inventory, `queued`, `expired`, `cancelled`, past `dispatched_at + 7 days`; the boundary itself is accepted). `own_cancelled = kind == 'compliance' and state == 'cancelled'` only when the job is this agent's (#124 (f)); every other refusal has `own_cancelled = False`.
3. `parse_eval_spec(job.eval_spec)`; `EvalSpecError` → `Refused("eval_spec_invalid")`, logged as `result batch refused: eval_spec unreadable (<ExceptionType>)` only (#124 (h)).
4. `existing = result_uuids([job] + [sibling])` (#127 (a)).
5. `plan(spec, {uuid: execute from the payload}, existing, batch.results)`; `PluginNotInJob` → refused, whole batch (#124 (a)).
6. `insert_results` (one INSERT, `received_at = now`, the manager clock, #124 (e)).
7. `after_batch(job.state, stored, all_have_results = payload uuids ⊆ existing ∪ new, final)`; on `start`: `deadline_at(now, payload timeouts, max_parallel_plugins read now with read_settings(SettingsRepo(conn)))` through `job_intake.start`; then `set_state` when the state changed, with `finished_at = now` on entry into `completed`/`partial`/`failed` (#127 (c)), so a late `failed → partial` moves `finished_at`, `partial → partial` does not.
8. `tx.on_commit(PLUGIN_RESULTS.labels(result=…).inc(n))` per verdict of the stored rows only (REQ-226 (2): duplicates and refusals add nothing; a rollback runs no hook).

Every refusal is raised inside the `with db.transaction()` block (before any write) and caught outside it, so the transaction rolls back and the locks are released. The caller (TASK-204 route) then writes M3's `agent.result_refused` entry in its own transaction, passing `own_cancelled` to skip the flood count.

## Acceptance points

- REQ-214 (1)–(3), (6): refusals as step 2/3/5, nothing stored, no job change; accepting states answer counts; a fault after the INSERT propagates and rolls everything back.
- REQ-215: verdict, snapshots and text rules come from `intake_plan` against the job's own `eval_spec` (never the catalog); `job_created_at` and the single INSERT from `job_intake`.
- REQ-216: the root lock in `lock_unit` and the sibling's results in `existing`; in-batch duplicates in `plan`.
- REQ-217: step 7.
- REQ-226: `metrics.py` and step 8.
- REQ-227 (4): the module never logs or raises with stdout, stderr, `execute` or expected text.

## Gates (Windows, worktree venv)

ruff check, ruff format --check, mypy --strict (Windows and `--platform linux`) on `manager`: green. PostgreSQL behaviour is for the tester (TP-M9-12).

## Plants for the tester (mutation table)

- CHK-M9-320 / -321: in `repositories/job_intake.lock_unit` (TASK-195 report).
- CHK-M9-322: drop `unit.append(other)`.
- CHK-M9-327: pass `job.created_at` instead of `job.dispatched_at` to `accepts_results`.
- CHK-M9-328: drop the kind check (plant in `states.accepts_results`, or bypass it here for `kind == 'inventory'`).
- CHK-M9-329: there is no catalog read here; the plant is to build `spec` from the current `policy_plugin`/`plugin` rows instead of `job.eval_spec`.
- CHK-M9-333: pass `item.finished_at` as `received_at`.
- CHK-M9-374: call `PLUGIN_RESULTS…inc` directly instead of `tx.on_commit`, or count `len(batch.results)`.
- CHK-M9-375: `log.debug("%s", item.stdout)` inside `_intake` (the canary must catch it).
- CHK-M9-380 (with TASK-204): `own_cancelled` always False, or always True.
