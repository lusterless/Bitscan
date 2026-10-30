# TASK-187 IMPL: scan state derivation (pure)

Implementer: impl-manager-m9. REQ-207, REQ-219. Risk high. Spec: TS §4.4 L579–L580. Answers applied: #22, #127 (d), (e) (also the `jobs-and-scans.md:40` own question: cancelled after results is `partial`/`completed`).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/scan_state.py` (new, 49 lines) | `Unit`, `ScanState`, `derive()` |

No file outside the task's list was changed.

## Interface (as plan TASK-202 §2)

```python
@dataclass(frozen=True, slots=True)
class Unit:
    open: bool            # a job of the unit is queued, dispatched or running
    complete: bool        # every plugin of the original's payload has a result in the unit
    has_results: bool
    any_cancelled: bool
    all_queued: bool      # every job of the unit is still queued

ScanState = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
def derive(units: Sequence[Unit]) -> tuple[ScanState, bool]   # (state, finished)
```

## Behaviour

In this order: empty list → `ValueError`; any unit open → (`queued` if every unit `all_queued`, else `running`; finished False); every unit complete → `completed`; any unit `has_results` → `partial`; any unit `any_cancelled` → `cancelled`; else `failed`; finished True for all four. `ScanState` cannot hold `dispatched` or `expired`. The derivation reads only the five facts; consistency between them (e.g. `all_queued` implies `open`) is the caller's (TASK-194's SQL), not checked here.

## For the tester

- REQ-207 (1) rows map directly: "one expired and one queued" is `[Unit(open=False, all_queued=False, ...), Unit(open=True, all_queued=True, ...)]` → `running`.
- Imports: stdlib only.

## Plants

CHK-M9-360 (move the `any_cancelled` check above `has_results`), -361 (derive per job, the caller's change, not reachable in this module alone; the per-unit `complete` fact is the guard), -362 (return `"dispatched"` from the open branch: also a mypy error, so plant with a `cast`).

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
