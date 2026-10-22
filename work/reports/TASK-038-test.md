# TASK-038 TEST report: sign-in and sign-out

Verdict: **PASS** (revision 1). Tester, 2026-10-22. REQ-048, REQ-042, REQ-047, REQ-035 (5); #47, #48, #49, #50, #54, #55, #58; decisions 2026-10-21 ("sign-in memory bound", "OpenAPI error contract") and 2026-10-22 (DatabaseUnavailable → 503). Impl report: `work/reports/TASK-038-impl.md` (revision 1). Two-approval task.

## Rounds
- Round 1: `test_openapi_error_contract` failed. The `/readyz` 503 was documented without `application/problem+json` content, while the app answers problem+json. Revision 1 documents every error response with problem+json.
- Round 2 (revision 1): all pass.

## Commands run
- L: `pytest tests/test_login.py` (18); 12 mutations plus control; ruff, ruff format, mypy --strict (108 files); full suite 1023 passed, 305 skipped (pg, Linux).
- W: `pytest tests/test_login_pg.py` and the wave 5 files (124 passed); 15 TASK-038 Linux mutants red against a green control; full suite 1367 passed, 0 skipped.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-048 (1) one 401 for every failure | PASS | CHK-M2-170 |
| REQ-048 (2) one Argon2id run on every path; memory bound | PASS | CHK-M2-171, -186 |
| REQ-048 (3), (4) back-off; never locked | PASS | CHK-M2-172, -173 |
| REQ-048 (5), REQ-046 (d) session row; restricted admin | PASS | CHK-M2-174, -176 |
| REQ-042 (2), (3) single-use code, also concurrently | PASS | CHK-M2-175 |
| REQ-047 (1), (5) per-IP limit; proxy headers ignored | PASS | CHK-M2-177, -183 |
| REQ-048 (7) alerts and audit | PASS | CHK-M2-178 |
| REQ-048 (6) logout | PASS | CHK-M2-179 |
| REQ-048 (8), REQ-041 (5) no secrets | PASS | CHK-M2-180 |
| #58 vault down; DatabaseUnavailable 503 | PASS | CHK-M2-181, -187 |
| REQ-035 (5), CHK-M2-185 OpenAPI contract | PASS | CHK-M2-182, -185 |
| bad bodies | PASS | CHK-M2-184 |
| CHK-M2-045 timestamps under Asia/Singapore | PASS | CHK-M2-045-r038 |

Mutations: 12 Windows plus 15 Linux, all red, controls green. Test files added: `test_login.py`, `test_login_pg.py`.

## Notes
- The order-dependent verify-count failure impl-manager saw was my test (`_dummy_hash` is cached). Fixed; not a product issue.
- Three test-design errors in my first wave 5 run (back-off tripped by my own sequence; a queue check that expected files to remain with the sink up) were fixed. The affected mutants were re-run against a green control.
