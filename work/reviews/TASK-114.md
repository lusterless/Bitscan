# TASK-114 REVIEW: `GET /api/v1/packages/search.csv`

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search). Not a two-approval task.

Scope reviewed (`work/reports/TASK-114-impl.md`):
- `manager/bitscan_manager/repositories/packages.py`: the `_SHAPES` restructure, `read_only_snapshot`, `count_capped` and `stream`;
- `manager/bitscan_manager/services/packages/search.py`: `CSV_MAX_ROWS`, `CSV_HEADERS`, `_cells` and `export_csv`;
- `manager/bitscan_manager/api/user/packages.py`: `CsvResponse` and `search_packages_csv`;
- the re-exported `manager/openapi.json`.

Sources: TS §6.2 L1117, §6.3 L1142, §7.3 L1224, REQ-115, REQ-116 and #84 (a)–(d).

TEST: PASS (`work/reports/TASK-114-test.md`, CHK-M5-150..160). The run gave 408/409; the one failure was a test bug, re-run 1/1. Red plants:
- CHK-M5-333: stdlib `csv.writer` bypasses `escape_cell`.
- CHK-M5-334: (a) cap removed, (b) cap checked after the body is built, (c) `>=` off-by-one.
- CHK-M5-336: the agent dependency used instead of `VIEWER`.
- CHK-M5-361..363: reversed order, no `Content-Disposition`, `limit` honoured.

The TASK-110 repository suite passes again on the restructured SQL (58/58).

## Checks
1. **Cap before any byte (lead's point 1).**
   - `count_capped` runs `count(*)` over the filtered rows or groups with `LIMIT cap + 1`, so it never counts past 100,001.
   - `export_csv` raises `TooManyRows` when the count is greater than `cap`, before `stream` is called.
   - The route builds the whole body inside the transaction before it creates the `Response`, so a refusal is a 400 problem with no CSV byte.
   - The boundaries hold: 100,000 is served and 100,001 is refused (plants 334 (a)–(c)).
   - `read_only_snapshot` is the first statement of the transaction, so the count and the stream see one REPEATABLE READ, READ ONLY snapshot. The count cannot disagree with the rows, and the route can write nothing (REQ-115 (5)).
2. **Every cell escaped (lead's point 2).**
   - Every value goes `_cells` → `write_csv` → `csv_line` → `_quote(escape_cell(c))`. Header cells take the same path.
   - The TASK-111 r1 function is the only CSV writer in the tree, and the service has no other text path.
   - `=HYPERLINK("http://x")` comes out as `"'=HYPERLINK(""http://x"")"` (plant 333 is red).
3. **#84 format.**
   - The header row is the JSON field names in TS §7.1 order for each shape. Rows are in the same order and with the same filters as the JSON pages, because `stream` uses the same `_SHAPES` statement without `LIMIT` (CHK-M5-361).
   - The response is `text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="packages.csv"`, UTF-8 without BOM and CRLF line ends.
   - `limit` and `cursor` are not declared, so they are ignored.
4. **Auth and refusals.** The route has the same `VIEWER` dependency and `search_params` as TASK-113, so only `bsu_`/`bsk_` are accepted and the same 400s apply. The over-cap `detail` is fixed text with no client value (checklist 12).
5. **SQL.**
   - The `_SHAPES` restructure keeps every fragment fixed in `psycopg.sql`, with every value bound (checklist 2 still holds: the order and keyset use `::debversion`).
   - The named server-side cursor reads 1,000 rows per fetch, and is used inside the transaction.
6. Re-run by the reviewer (with TASK-113):
   - `ruff check` and `ruff format --check` pass on `manager`.
   - `mypy --strict` passes (110 files).
   - A fresh OpenAPI export is byte-identical to `manager/openapi.json`.
   - The CSV operation's 200 is `text/csv` only, with no 422.
7. Scope: 3 source files and the re-export, over the plan's estimate. Most of the excess is the per-shape declarations that let the export reuse the paging SQL exactly. For package search, with one round, I accept that.

## Findings
1. nit, `api/user/packages.py:219`. The body is built as one `str` and then encoded, so a 100,000-row export holds about two copies in memory (a few tens of MB with long hostnames). That is acceptable for v1 under the cap. Re-check it with the deferred load test, together with the TASK-060 64 MiB copy.
