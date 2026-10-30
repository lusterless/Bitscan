# TASK-200 IMPL: cancel service `cancel_scan()`

Implementer: impl-manager-m9. REQ-219, REQ-220, REQ-227. Risk high. Spec: TS §4.4 L573, L581, §6.2 L1122. Answers applied: #122 (g), #127 (d), (f), #129 (a). Built on TASK-187 (`scan_state.derive`) and TASK-194 (`repositories/scan_progress.py`, impl-manager-m9b).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/cancel.py` (new, 56 lines) | `ScanNotFound`, `ScanCancelled`, `cancel_scan()` |

No file outside the task's list was changed.

## Interface

```python
class ScanNotFound(Exception)                    # 404
@dataclass(frozen=True, slots=True)
class ScanCancelled: scan_id: UUID; state: ScanState; cancelled_jobs: int
def cancel_scan(tx: Tx, *, scan_id: UUID, actor: str, now: datetime) -> ScanCancelled
```

The answer maps directly to the #122 (g) 200 body `{scan_id, state, cancelled_jobs}`.

## Order, in the caller's transaction

1. `scan_row(conn, scan_id, lock=True)`. None raises `ScanNotFound`. The scan row lock serialises two cancels of one scan.
2. `cancel_open_jobs(conn, scan_id, now)`: queued, dispatched and running compliance jobs (originals and retries) become `cancelled` with `finished_at = now`. Other jobs are untouched.
3. `unit_facts(conn, [scan_id])`, then `derive()`. These run in the same transaction, so they see step 2.
4. `set_scan_state(conn, scan_id, state, now if finished else None)`. It writes only on change, and `finished_at` is never moved (#127 (e)).
5. One `scan.cancel` entry: actor as given, target `scan:<scan_id>`, detail `{cancelled_jobs: n}`.

Nothing is sent to any agent: cancel is manager-side only. A cancelled queued job is never pulled (pull selects `state = 'queued'`), and a post for a cancelled job is refused by `states.accepts_results` (REQ-214).

Lock order: the scan row, then open jobs. Intake (root then job) and the sweep's job steps never lock a scan row. The sweep's `scan_states` step locks scan rows but no jobs. So no cycle can form. A cancel whose `UPDATE` meets a job held by an intake post waits for it, and READ COMMITTED re-checks the state after that commit.

## Resolved point

A no-op repeat cancel writes one `scan.cancel` entry with `{cancelled_jobs: 0}`: one entry per call, as built (main's ruling, decisions 2026-10-30 "M9 builder rulings" (2)).

## For the tester (tester-m9b)

- An unknown id raises before any write. The route maps it to 404.
- A scan whose `unit_facts` is empty (it cannot exist, #3) makes `derive()` raise `ValueError`. That is an invariant failure, not a refusal.

## Plants

- CHK-M9-359: the repository side (`state IN ('queued')`).
- CHK-M9-360: through `derive()` (see TASK-187).
- REQ-220 (3): drop step 4. The scan then stays `running`/`queued` after the cancel until the next sweep.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`) on `manager/bitscan_manager`: pass.
