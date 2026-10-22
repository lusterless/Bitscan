# TASK-041 TEST report: API tokens

Verdict: **PASS**. Tester, 2026-10-22. REQ-051, REQ-040 (3), (5), REQ-046 (2), (e); #8, #47, #52; lead ruling 2026-10-22 (201 Created; shown once). Impl report: `work/reports/TASK-041-impl.md`. Two-approval task.

## Commands run
- W: `tester2_t041.sh`, alone: `tests/test_api_tokens.py` (30) plus the OpenAPI, login and app files, 67 passed; full suite 1441 passed, 0 skipped; 12 mutants plus control.
- L: ruff, ruff format, mypy --strict (115 files); `tests/test_openapi.py` corrected, plus 1 mutant.

## Criteria
| REQ-051 | Result | Rows |
| --- | --- | --- |
| (1) lifetimes, name length | PASS | CHK-M2-210 |
| (2), REQ-040 (3) shown once, never listed in clear | PASS | CHK-M2-211 |
| (3) other users' tokens out of reach | PASS | CHK-M2-212 |
| (4) revoked token refused | PASS | CHK-M2-213 |
| (5) one alert per creation | PASS | CHK-M2-214 |
| (6), #8 an API token may revoke its own | PASS | CHK-M2-215 |
| (7), (8), REQ-046 who may create | PASS | CHK-M2-211, -216 |
| REQ-040 (5) no raw token at rest | PASS | CHK-M2-217 |
| REQ-054 (4) sink gate not applied | PASS | CHK-M2-218 |
| pagination; UTC timestamps | PASS | CHK-M2-219 |

Mutations: 12/12 red, control green. Test file added: `test_api_tokens.py`; corrected: `test_openapi.py` (CHK-M2-021-r041).
