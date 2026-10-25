# TASK-114 IMPL: `GET /api/v1/packages/search.csv`

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-116, REQ-115. Plan: `work/plans/TASK-113.md` (TASK-114 parts). TS §6.2 L1117, §6.3 L1142, §7.3 L1224; #84 as approved.

## Files

- `manager/bitscan_manager/repositories/packages.py`:
  - **Refactored, same SQL.** The three page statements are now one `_SELECT` template plus a per-shape `_Shape` (select list, `GROUP BY`, `ORDER BY`, keyset condition, row type) in `_SHAPES`, and `LIMIT` is appended for pages. The rendered page SQL for all three shapes is the same as TASK-110's (checked offline with `as_string`). This lets the export reuse exactly the paging filters and order.
  - New methods: `read_only_snapshot()` (`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`, which must be the transaction's first statement), `count_capped(f, shape, cap)` (`SELECT count(*) FROM (SELECT 1 … WHERE … [GROUP BY …] LIMIT cap + 1) s`), and `stream(f, shape)` (the full ordered query through the named server-side cursor `package_export`, `itersize` 1000).
- `manager/bitscan_manager/services/packages/search.py`: `CSV_MAX_ROWS = 100_000` (data rows), `CSV_HEADERS`, the `ExportStore` Protocol, `TooManyRows`, `export_csv(store, query, cap)`.
  - `export_csv` counts first and raises before streaming when the count is over `cap`.
  - Cells are the JSON values as text (UUIDs lower-case, counts in decimal). Every cell goes through TASK-111's `write_csv`, so escaping happens only there.
- `manager/bitscan_manager/api/user/packages.py`: `CsvResponse` (`text/csv`, which Starlette sends as `text/csv; charset=utf-8`) and the route `search_packages_csv`.
  - Same viewer dependency and `search_params` as the JSON route. It declares no `limit` or `cursor`, so those are ignored.
  - One transaction: `read_only_snapshot()` first, then `export_csv`. The body is complete before the response starts.
  - `TooManyRows` becomes 400 `invalid_request` with the fixed detail `Invalid request: more than 100000 rows; narrow the filters`.
  - Success sends `Content-Disposition: attachment; filename="packages.csv"`, UTF-8 without BOM and CRLF line ends.
- `manager/openapi.json`: **re-exported**.
  - Since TASK-113 the file is now 780 lines added against the commit and none removed. The new operation lists the eleven TS §7.1 parameters (no `limit` or `cursor`).
  - Its 200 is only `text/csv` with `{"type": "string"}` (no `application/json`), and its errors are 400/401/403/429/503 as problem+json.
  - Two exports compared byte-identical.

## AC mapping (REQ-116)

| AC | Where |
| --- | --- |
| (3) CSV rows equal the JSON pages, same order, all shapes | `stream` uses the same `_SHAPES` filters and order as the pages |
| (4) `=HYPERLINK("http://x")` | through `write_csv` (ad-hoc: `"'=HYPERLINK(""http://x"")"`) |
| (5) over cap gives 400 before any byte | count before stream; the body is built before the `Response` |
| (6) headers | `CsvResponse` and `Content-Disposition` |
| (7) token groups | `VIEWER` dependency |

Ad-hoc sanity with a fake `ExportStore` (not a test file):
- The header row and escaped, quoted cells are correct, with a lower-case UUID.
- `cap=2` with 3 groups raises `TooManyRows` and `stream` is never called.
- An empty result gives the header row only.

## Checks run (from `Bitscan-m5/manager`, M3 venv)

`ruff check`, `ruff format --check` and `mypy --strict` on `bitscan_manager` all pass (110 files). No tests run. All edited files have LF line ends.

## For the tester

- **Re-run TP-M5-03 (`test_package_repo_pg.py`).** TASK-110's repository was restructured here. The SQL text is unchanged, but your PASS was on the earlier file.
- `count_capped` returns `min(count, cap + 1)`. The cap counts data rows (rows or groups), not the header.
- The server-side cursor passes bound parameters through `DECLARE` (psycopg uses the extended protocol). It needs the PostgreSQL run to confirm.
- `serve`'s 300 s `statement_timeout` bounds a slow export, which becomes the M2 500 problem with no partial body.
- The file sizes exceed the plan's estimates: the repository is 347 lines in total, 225 for the route module and 106 for the service. Most of the extra is per-shape declarations and docstrings.
