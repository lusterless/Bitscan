# TASK-186 IMPL: job state rules (pure)

Implementer: impl-manager-m9. REQ-206, REQ-217. Risk high. Spec: TS §4.4 L562–L582, §3.3 L222. Answers applied: #124 (a), (d), #127 (a)–(c).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/states.py` (new, 121 lines) | the state rules below |

No file outside the task's list was changed.

## Interface (frozen for M10/M11 once W1 passes)

```python
JobState = Literal["queued","dispatched","running","completed","partial","failed","cancelled","expired"]
FINAL: Final = frozenset({"completed", "expired", "cancelled"})
ACCEPTING: Final = frozenset({"dispatched", "running", "failed", "partial", "completed"})
LATE_WINDOW: Final = timedelta(days=7)
DEADLINE_SLACK: Final = timedelta(minutes=10)
NEVER_STARTED_AFTER: Final = timedelta(hours=24)       # for TASK-202's sweep
MAX_PARALLEL_MIN, MAX_PARALLEL_MAX: Final = 1, 8
TRANSITIONS: Final[Mapping[str, frozenset[str]]]       # read-only
def allowed(old: str, new: str) -> bool
def deadline_at(started_at: datetime, timeouts: Sequence[int], max_parallel: int) -> datetime
def accepts_results(kind: str, state: str, dispatched_at: datetime | None, now: datetime) -> bool
@dataclass(frozen=True, slots=True)
class BatchOutcome: state: JobState; start: bool
def after_batch(state: str, *, stored: int, all_have_results: bool, final: bool) -> BatchOutcome
def after_deadline(*, any_result: bool, all_have_results: bool) -> JobState
```

## Behaviour

- `TRANSITIONS` is the REQ-206 list exactly: `queued → dispatched | expired | cancelled`; `dispatched → running | failed | cancelled`; `running → completed | partial | failed | cancelled`; `failed | partial → completed | partial`; the three final states map to the empty set. Staying in a state (a non-final batch on `running`) is not a transition, so `running → running` is refused by `allowed()`. `allowed()` returns False for unknown names.
- `deadline_at`: `started + timedelta(seconds = -(-Σ // mpp)) + 10 min` in integers. `ValueError` for `max_parallel` outside 1–8 or empty `timeouts`.
- `accepts_results`: `kind == "compliance"`, state in `ACCEPTING`, `dispatched_at` not None and `now <= dispatched_at + 7 days` (boundary inclusive).
- `after_batch` (#127 (a), #124 (d)):
  - `dispatched`: `start=True`; then `completed` if `all_have_results`, else `partial` if `final`, else `running`. An empty batch counts (the start notice).
  - `running`: the same, `start=False`.
  - `failed`/`partial`: `stored == 0` → unchanged (a start notice or only duplicates); else `completed` if all, else `partial`.
  - `completed` → `completed`.
  - `queued`, `expired`, `cancelled` or anything else: `ValueError` (callers check `accepts_results` first).
- `after_deadline`: `completed` if every plugin has a result, `partial` if some, else `failed`. Also used for the never-started rule (no result can exist, so `failed`).
- `start` is only ever True from `dispatched`, so a second start notice can never reset `started_at`/`deadline_at` at this level. TASK-195's `start()` also writes only `WHERE started_at IS NULL`.

## For the tester

- Additions beyond the plan's §2 list, all pure: `TRANSITIONS` and `allowed()` (REQ-206 says the module holds the allowed transitions, and (1) refuses every pair the table does not allow), `NEVER_STARTED_AFTER`, `MAX_PARALLEL_MIN/MAX`.
- `after_batch` takes `state: str` (callers pass the DB text); it returns `JobState`.
- Imports: `collections.abc`, `dataclasses`, `datetime`, `types`, `typing` only. No `bitscan_manager` module other than the package `__init__`s (`services/jobs/__init__.py` imports `pull.py`, which is pure).

## Plants (mutation table)

CHK-M9-325 (`cancelled` added to `ACCEPTING`), -326 (`<` for `<=` in `accepts_results`), -334 (`start=True` from `running`), -335 (`sum // mpp`, or `mpp` ignored), -336 (`timedelta(seconds=10)` slack), -337 (`partial` returned when not `final`), -338 (`completed` branch returning `partial`).

## Gates

From the worktree root: `manager/.venv/Scripts/ruff.exe check manager` (pass), `ruff.exe format --check manager` (pass), `mypy.exe --strict --config-file manager/pyproject.toml manager` with and without `--platform linux` (pass, 349 files).
