# TASK-241 IMPL: results service (`results_page`, `results_csv`)

Implementer: impl-manager-a. REQ-267, REQ-268, REQ-269. Risk high (second look, PD-47). Spec: TS §6.2 L1083, L1123; §4.5 L603; §4.4 L585; §6.3 L1144. Answers applied: #144, #146. Plan: `work/plans/TASK-235.md` §4; signatures from `work/plans/TASK-232.md` §5. Built on TASK-233 (`results_view`), TASK-235 (`result_reads`) and TASK-240 (`ScanNotFound`), all unchanged.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/results_read.py` (new, 60 lines of code) | the whole task |

## Interface

```python
ScanNotFound                     # re-exported: the same class as services.jobs.scan_views.ScanNotFound
class TooManyRows(Exception)
@dataclass(frozen=True) class ResultPage:
    items: list[dict[str, object]]          # results_view.item() mappings
    next_after: tuple[UUID, int] | None     # (agent_id, position) of the last item if another page exists
    with_output: bool                       # the flag the items were built with
def results_page(db, scan_id, query: ResultQuery, role: str, limit: int,
                 after: tuple[UUID, int] | None) -> ResultPage          # raises ScanNotFound
def results_csv(db, scan_id, query: ResultQuery, role: str) -> str     # raises ScanNotFound, TooManyRows
```

Plan §5 says `results_page` returns a `ResultPage` without defining it. The type is defined here:
- The service does not build the cursor. Cursors are an API concern (`api/pagination`, HMAC scope), so it returns the keyset `next_after` and TASK-244 encodes it under the `scan_results:<scan_id>:<status>:<agent_id>` scope.
- `with_output` is returned so the route builds the concrete `Page[ScanResultItemWithOutput]` or `Page[ScanResultItem]` from the same flag the items were built with (reviewer note on TASK-232).

## Behaviour

- **The role rule:** `with_output = results_view.include_output(role)`, decided once per call. `role` is the caller's current role (`principal.role`), never the token kind. The flag selects both the repository's statement variant (the viewer one selects NULL for stdout and stderr) and the item mapping (no `stdout`/`stderr` keys for a viewer).
- **One transaction per call:**
  1. `result_reads.read_only_snapshot` is the first statement (REPEATABLE READ, READ ONLY);
  2. `result_reads.exists`, so an unknown scan raises `ScanNotFound` rather than giving an empty page;
  3. one read.
- **Page:** it reads `limit + 1` rows and shows the first `limit`. The extra row only sets `next_after` to the last shown item's `(agent_id, position)`.
- **CSV:**
  - `results_export(..., max_rows=CSV_MAX_ROWS)` reads at most 100,001 rows. If more than 100,000 come back, `TooManyRows` is raised before any text is built (#146 (e)).
  - Otherwise the body is `results_view.csv_text(rows, with_output=…)`, where every cell goes through `escape_cell`.
  - The route encodes it as UTF-8 and sends it in one response.
- Nothing is written and nothing is logged. No exception carries result text.

## Notes

- `ScanNotFound` is TASK-240's class, so the routes map one 404 type for both services.
- No PostgreSQL run by me.

## Commands run

`PYTHONPATH` and `MYPYPATH` point at this worktree's `manager/`. I used the `Bitscan-m9/manager/.venv` tools; see TASK-232 for why.

| Command | Result |
| --- | --- |
| `ruff check` / `ruff format --check` on the file | clean |
| `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` | Success, 189 files |

Files outside the task list: none. `api/user/reevaluate.py` shows as modified in the working tree; that is TASK-243 (impl-manager-b), not me.
