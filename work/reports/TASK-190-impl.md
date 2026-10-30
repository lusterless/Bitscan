# TASK-190 IMPL: intake plan (pure)

Implementer: impl-manager-m9. REQ-214, REQ-215, REQ-216. Risk high (TS §8.2 second approval, PD-39). Spec: TS §6.1 L1071, §4.4 L578, §4.5 L587, L596, L599, L603. Answers applied: #12, #116 (d), #121, #124 (a), (b).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/intake_plan.py` (new, 159 lines) | `IntakeItem`, `ResultRow`, `PluginNotInJob`, `Plan`, `storable()`, `plan()` |

No file outside the task's list was changed. Reuses M8's `EvalSpec`, `result_verdict`, `classify`, `Detail`, `ResultLike`, `Verdict`.

## Interface (as plan TASK-199 §2, plus `IntakeItem`)

```python
class IntakeItem(ResultLike, Protocol):      # + plugin_uuid: UUID, started_at, finished_at: datetime
@dataclass(frozen=True, slots=True)
class ResultRow: plugin_uuid; eval_code: int; eval_detail: str | None; exit_code: int | None
    stdout; stderr; timed_out; truncated; plugin_name_snap; execute_snap; operator_snap; expected_snap
    started_at: datetime; finished_at: datetime
class PluginNotInJob(Exception)              # fixed message
@dataclass(frozen=True, slots=True)
class Plan: rows: tuple[ResultRow, ...]; duplicates: int
def storable(text: str) -> str
def plan(spec: EvalSpec, payload_plugins: Mapping[UUID, str], existing: Collection[UUID],
         items: Sequence[IntakeItem]) -> Plan
```

`IntakeItem` is new. M8's `ResultLike` has no `plugin_uuid`, `started_at` or `finished_at`, and the module cannot import `api.agent.schemas.ResultItem`. The M3 `ResultItem` satisfies it structurally.

## Behaviour

1. Membership first, for every item: a uuid with no `spec.get()` entry or not in `payload_plugins` raises `PluginNotInJob` before any row is built. The whole batch is refused (#124 (a)).
2. Duplicates: an item is a duplicate when its uuid is in `existing` (the job and its sibling, from the caller) or an earlier item of the batch had it. First in batch order wins, and `duplicates` counts the rest (#124 (b)). For an accepted batch, `len(rows) + duplicates == len(items)`.
3. `verdict = result_verdict(entry, item)` on the text **as received**, so the caps are measured first (#121 (b)).
4. An `oversize` result gets `stdout` and `stderr` of `""` (#116 (d)). Otherwise both go through `storable()`: U+0000 and every surrogate code point become U+FFFD with `str.translate`, and the text is returned unchanged when it holds neither.
5. When the stored stdout differs from the received one, the verdict is computed again on the stored text (#121 (c)).
6. Snapshots: `plugin_name_snap`, `operator_snap` and `expected_snap` come from the `eval_spec` entry, and `execute_snap` from `payload_plugins`. `exit_code`, `timed_out`, `truncated`, `started_at` and `finished_at` are kept as sent. `eval_detail` is `Detail.value` or None.

## Departure from the plan's wording in step 5 (for the reviewer and `main`)

Plan TASK-199 §2 step (4) says to recompute "through `result_verdict` with a proxy whose stdout/stderr are the replaced values". I recompute with M8's `classify()` on the stored stdout, and only when the first verdict came from the comparison (`item.error is None` and not `oversize`). The reasons:
- U+FFFD is 3 UTF-8 bytes and U+0000 is 1. A `result_verdict` proxy would measure the caps again on the replaced text, so a 65,000-byte stdout with 300 NULs would turn into `oversize` while keeping its text. That contradicts #121 (b) (caps measured on the received text) and #116 (d) (oversize is stored with empty streams).
- M8's `reevaluate` keeps the `INTAKE_DETAILS` verdicts and runs `classify()` on the stored text. Using `classify()` here makes intake and re-evaluation agree (#121 (c), L596).
- A runner-error verdict (`spool_overflow`, `runner_unavailable`, or a non-contract error giving `cannot evaluate`) does not depend on the text, so it is kept as it is.

For every input where a proxy gives no `oversize`, the result is the same as the plan's wording.

## For the tester

- `existing` is the caller's job: CHK-M9-322 (the sibling ignored) is a TASK-199/195 plant. At plan level, pass the sibling's uuids in `existing` and expect a duplicate.
- Only stdout feeds the verdict. A stderr-only replacement changes the stored stderr but not the verdict.
- `ResultRow.eval_code` is an `int` (0, 1 or 2).
- Imports: `services.evaluator.{eval_spec, evaluate, model, verdict}` only (plus stdlib). No db, repository, API, psycopg or logging.

## Plants

- CHK-M9-323: drop the `seen.add`. A second item for one plugin is then planned twice.
- CHK-M9-324: `continue` instead of `raise` in the membership loop.
- CHK-M9-330: keep `item.stdout` for `oversize`.
- CHK-M9-331: compute the verdict after `storable()` without recomputing, or skip `storable()`.
- CHK-M9-332: take `execute_snap` from anything but `payload_plugins`. There is no catalog input here, so the plant is `entry.name`.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
