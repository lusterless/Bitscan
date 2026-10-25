# TASK-114 TEST: GET /api/v1/packages/search.csv

Verdict: **PASS**. Tester: tester-m5. Rigor: standard (package search), with one plant per AC plus the three mutation rows.

Tests: `manager/tests/test_package_search_csv_pg.py` (new, 101 tests, TP-M5-07, CHK-M5-150..160), written from TS §6.2 L1117, §6.3 L1136/L1140/L1142, §7.3 L1224, REQ-115, REQ-116, #84 (a)-(d) and the TASK-111 r1 ruling before the code was read.

Commands (WSL Ubuntu 24.04, CI=true, venv-m5, -n 4):
- `pytest tests/test_package_search_csv_pg.py tests/test_package_search_pg.py tests/test_csv_export.py tests/test_openapi.py` (m5-t114a): 408/409 passed, 1 failed (test bug), 0 errors, 0 skipped.
- Re-run of the failing node id (m5-t114b, m5-t114c): 1/1 passed.
- Plants (m5-mw3, m5-mw3b): control 101/101 passed; CHK-M5-333, 334 (a, b, c), 336, 361, 362, 363 all red for the planted reason.
- `mypy --strict`, `ruff check`, `ruff format --check` on the new file: clean.

AC coverage (REQ-116; rows in tests/m5/report.md):
- (3) CSV = JSON pages, same order, 3 shapes, header row: CHK-M5-150, -151; plant CHK-M5-361.
- (4) `=HYPERLINK("http://x")` -> `"'=HYPERLINK(""http://x"")"`, every trigger incl. the r1 tab/CR forms: CHK-M5-152; plant CHK-M5-333.
- (5) over the 100,000 cap -> 400 before any byte (real 100,001 rows through the API; fake store shows stream never called): CHK-M5-153; plants CHK-M5-334 a/b/c.
- (6) Content-Type and Content-Disposition: CHK-M5-154; plant CHK-M5-362.
- (7) / REQ-115 (1) token groups incl. a stored-valid bsa_: CHK-M5-157; plant CHK-M5-336.
- Same refusals as REQ-113: CHK-M5-156. limit/cursor ignored: CHK-M5-155, plant CHK-M5-363. Nothing written, one of the 600: CHK-M5-158. Document text/csv only, G6: CHK-M5-159. Empty -> header only: CHK-M5-160.

Failure during the run (fixed, test bug): `test_a_stored_valid_agent_token_is_refused`. Expected the bsa_ to be valid on GET /agent/{id}/jobs; actual 401, because the test sent no X-Bitscan-Machine-Id. Now it sends the stored machine-id. The plant run then showed its two cases in the wrong order (the no-id case failed first with 400), so the cases were reordered, and plant 336 was re-run: red with 200 for the full agent credential set.

Notes: the test plan's expected-values table now holds the TASK-111 r1 ruling, the trailing-slash ruling, the drill-down ruling and the G42 r1b rules; new rows CHK-M5-113 and CHK-M5-361..364 are in tests/m5/test-plan.md.
