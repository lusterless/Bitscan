# TASK-085 TEST: M3 carry-overs (upload.py stores seam, two README sentences)
**Verdict: PASS.** REQ-112; TP-M4-24, CHK-M4-280 to -284; mutation row CHK-M4-366. Standard rigour (manager carry-over, no behaviour change).
Commands: W `tester3_m4_pytest.sh` (CI=true, xdist) on the new unit file and the TASK-074 route suites; W OpenAPI export plus cmp; L ruff, ruff format, mypy --strict; `tester3_m4_py366.py`.
Counts: unit 31/31; route set 1258/1258, 0 skipped; plants 4/4 red (control 179/179).

| Criterion (REQ-112) | Evidence |
| --- | --- |
| (1) The M3 inventory route suites (TASK-074's) pass unchanged on Linux | CHK-M4-281 1258/1258; the pg_stores wiring plant red only there |
| (2) New unit tests cover upload.py with fake stores, no database | CHK-M4-280-r1 31/31; the factory-ignored plant red only there |
| (3) manager/openapi.json byte-identical (G6) | CHK-M4-282 |
| (4) The two README sentences match the behaviour (M3 route tests) | CHK-M4-283 (three named tests passed; the second sentence states both answers, per the lead's 2026-10-25 ruling) |
| Static gates on the changed files | CHK-M4-284 |

Rows: CHK-M4-280 (NOT RUN, runner bug), -280-r1, -281, -282, -283, -284, -366.
