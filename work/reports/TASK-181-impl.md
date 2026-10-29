# TASK-181 IMPL: pure score and effective-verdict rule

Implementer: impl-manager-m8b. REQ-196, REQ-197 (1), (2) (REQ-197 (3) is TASK-184's property test). Risk high. Spec: TS §4.5 L601–L602, §4.4 L583. Answers applied: #119, #120.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/score.py` (new, 113 lines) | `HostScore`, `host_score()`, `ReevalRow`, `Effective`, `effective()` |

No file outside the task's list was changed.

## Interface

```python
@dataclass(frozen=True, slots=True)
class HostScore: passed: int; failed: int; errors: int; not_run: int; score: float | None
def host_score(passed: int, failed: int, errors: int, not_run: int) -> HostScore

@dataclass(frozen=True, slots=True)
class ReevalRow:                      # one scan_result_reeval row
    reeval_id: int; job_id: UUID; plugin_uuid: UUID; policy_version: int
    eval_code: int; eval_detail: str | None; reevaluated_by: int; reevaluated_at: datetime

@dataclass(frozen=True, slots=True)
class Effective:                      # field-for-field the same values as results.EffectiveRow
    job_id: UUID; plugin_uuid: UUID; original_code: int; original_detail: str | None
    code: int; detail: str | None; reeval_id: int | None; policy_version: int | None
    reevaluated_by: int | None; reevaluated_at: datetime | None

def effective(job_id: UUID, plugin_uuid: UUID, original_code: int,
              original_detail: str | None, reevals: Iterable[ReevalRow]) -> Effective
```

`HostScore` has no `agent_id`: it is the pure value, and TASK-184 pairs it with the agent. `Effective.policy_version` corresponds to `results.EffectiveRow.reeval_policy_version` (agent_id is the only field `Effective` lacks), so TASK-184's property test can compare them field by field.

## Behaviour

- `host_score`:
  - Raises `ValueError` (fixed text) for a count that is negative or not exactly an `int`. `type(...) is int` also refuses `True`/`False`, as `Verdict` does; that is stricter than REQ-196 (2), which names only negatives.
  - `score = passed / (passed + failed)` as an unrounded float, or `None` when the sum is 0.
  - `errors` and `not_run` are carried and never used in the ratio.
- `effective`:
  - Ignores rows for another job or plugin.
  - Picks the highest `reeval_id`, whatever the iteration order or `reevaluated_at`.
  - Returns its code, detail and provenance; the detail comes from that row even when it is NULL.
  - With no matching row, `code`/`detail` equal the original and the provenance fields are `None`.
  - The original code and detail are always returned unchanged.

## Acceptance points

- REQ-196 (1): (3,1,5,7) → 0.75 with errors 5 and not_run 7; (0,0,4,2) → None; (0,3,0,0) → 0.0; (1,0,0,0) → 1.0 (scratch check).
- REQ-196 (2): (-1,0,0,0) raises `ValueError`, and so does `True` as a count (scratch check).
- REQ-196 (3): None exactly when passed + failed = 0, and otherwise `passed / (passed + failed)` is in [0, 1], since both counts are non-negative.
- REQ-197 (1): rows 5, 9, 7, with id 9 holding the oldest `reevaluated_at`, give id 9's code and detail; no rows give the original (scratch check).
- REQ-197 (2): rows 99 (another job) and 98 (another plugin) were in the same scratch input and were ignored.
- Purity: imports only `collections.abc`, `dataclasses`, `datetime`, `uuid`.

## Mutation plants (M8 table)

- **CHK-M8-346:** `rated = passed + failed` → `passed + failed + errors`. Expect G62 red (the 0.75 row).
- **CHK-M8-347:** `None if rated == 0` → `0.0 if rated == 0`. Expect G62 red.
- **CHK-M8-348 (pure half):** `row.reeval_id > latest.reeval_id` → `<` (lowest wins), or compare `reevaluated_at`. Expect G62 red (the 5, 9, 7 row with out-of-order times).
- Extra: drop the job/plugin filter in `effective` (REQ-197 (2) row red).

## Gates (worktree root, worktree's own `manager/.venv`)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 321 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`, and with `--platform linux`: no issues in 321 files.
