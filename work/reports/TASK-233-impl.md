# TASK-233 IMPL: results view (pure): status parse, `include_output`, item mapping, results CSV

Implementer: impl-manager-a. REQ-267, REQ-268, REQ-269. Risk high (second look, PD-47). Spec: TS §6.2 L1083, L1123; §6.3 L1144; §4.5 L603; §4.4 L585. Answers applied: #144, #146. Plan: `work/plans/TASK-235.md` §2.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/results_view.py` (new, 159 lines, 116 of code) | the whole task |

It depends on `ResultRow` from `manager/bitscan_manager/repositories/result_reads.py` (TASK-235, delivered at the same time). Plan §2 allows that one import: "the row dataclass type".

## Interface (frozen once W1 passes)

```python
Status = Literal["PASS", "FAIL", "ERROR", "NOT_RUN"]
STATUSES: Final  # the four, in that order
CSV_MAX_ROWS: Final = 100_000
CSV_HEADER: Final  # the 17 #146 (b) names, in order
OUTPUT_COLUMNS: Final = ("stdout", "stderr")
class InvalidResultQuery(Exception)          # str(exc) == "status"
@dataclass(frozen=True) class ResultQuery: status: Status | None; agent_id: UUID | None
def parse_query(status: str | None, agent_id: UUID | None) -> ResultQuery
def include_output(role: str) -> bool
def item(row: ResultRow, *, with_output: bool) -> dict[str, object]
def csv_header(*, with_output: bool) -> tuple[str, ...]
def csv_text(rows: Iterable[ResultRow], *, with_output: bool) -> str
```

## Rules

- **`include_output(role)`.** True only for the exact strings `operator` and `admin`. Any other value (`viewer`, `""`, `Admin`, unknown) is False, so it fails closed. It is the only place the role rule lives. The caller passes `principal.role` (the current role), never the token kind.
- **`parse_query`.** `status` must equal one of the four exactly (case-sensitive, no trimming). Otherwise it raises `InvalidResultQuery("status")`. The message names the parameter only and never the value.
- **`item(row, with_output=False)`.** Exactly the 22 keys of `ScanResultItem`. With `with_output=True` it also has `stdout` and `stderr` (24 keys). Without output, the two keys are absent, not null.
- **Values in `item`.**
  - `result` is the effective code and `original_result` the stored one. Each maps as the generated `scan_result.result` column does: 0 PASS, 1 FAIL, anything else ERROR.
  - A Not-run row (`code` None) gives `result` null, and `original_result` null.
  - `retry` is `ResultRow.retry` (the result is in a job other than the original).
  - Datetimes are left as datetimes; the API model (`UtcDatetime`) serialises them.
- **`csv_text`.**
  - The header is `CSV_HEADER`, plus `OUTPUT_COLUMNS` only with output. Then one record per row, in the order given.
  - Every cell, header included, goes through `csv_export.write_csv`, which applies `escape_cell` and then RFC 4180 quoting with CRLF line ends.
  - The `csv` module is not used.
  - Cells: null is the empty cell; booleans are `true`/`false`; datetimes are RFC 3339 UTC, `%Y-%m-%dT%H:%M:%S.%fZ` (the same form as the API's `UtcDatetime`); UUIDs and integers use `str()`; verdicts are `PASS`/`FAIL`/`ERROR`; a Not-run `result` is empty.
  - The text is returned as `str`. Encoding (UTF-8, no BOM) is the route's job, as for `/packages/search.csv`.
- **Purity.** The module imports only the standard library, `csv_export.write_csv` and the `ResultRow` type. It does no I/O, no logging and no clock read, and does not use `re`.

## For the tester (tester-m11)

- CHK-M11-005 names the models `ResultItem`/`ResultItemWithOutput`. They are now `ScanResultItem` and `ScanResultItemWithOutput`, in `bitscan_manager.api.user.scan_views` (main approved the rename; see the TASK-232 report).
- CHK-M11-014 (purity) has two readings. Read directly, `results_view` imports `bitscan_manager.repositories.result_reads` for the row type, which plan §2 allows. Read transitively, importing `services.packages.csv_export` already loads psycopg and `repositories.packages` through `services/packages/__init__.py`, as does the `services.jobs` package `__init__` (`pull`). So a transitive "no psycopg" check cannot pass for any module that reuses `csv_export`. A check on the module's own import statements does pass.
- `ResultRow` is built with keywords (see the TASK-235 report for its fields). `retry` is a property, not a field.

## Commands run

`PYTHONPATH` and `MYPYPATH` point at this worktree's `manager/`. I used the `Bitscan-m9/manager/.venv` tools; see TASK-232 for why.

| Command | Result |
| --- | --- |
| `ruff check` (the new and changed files) | All checks passed |
| `ruff format --check` (the same files) | already formatted |
| `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` | Success, 187 files |
| `ruff check manager` / `ruff format --check manager` / `mypy … manager` | Fail **only** in `manager/tests/m11_pg_fixtures.py`: 62 × E501, format, 1 × arg-type at line 171. That is the tester's in-progress file; every product file is clean |

No tests were run (tester's job).
