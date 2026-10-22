# TASK-026 TEST report: problem details and cursor pagination

Verdict: **PASS** (round 3). Tester, 2026-10-21. REQ-038; #47 (d), #48, #52; lead rulings 2026-10-21 (413 `too_large`; `about:blank`; "Lead rulings on TASK-026 TEST questions"). Impl report: `work/reports/TASK-026-impl.md` (revisions 1 and 2).

## Rounds
- Round 1: **FAIL** on `tests/test_problems.py::test_client_chosen_keys_are_not_echoed[extra-key|dict-key]`. Expected no client-chosen string in `detail`; actual `Invalid request: body.CANARYKEY` and `body.m.CANARYKEY`. Lead ruled both FAIL.
- Round 2 (revision 1): **FAIL** on `test_client_chosen_parameter_keys_are_not_echoed[query|cookie|header]`. Actual `query.<key>`, `cookie.<key>`, `header.<key>` (plus every header the client sent). Cause: the non-body branch kept `loc[:2]`.
- Round 3 (revision 2): all pass.

## Commands run
- L: `pytest tests/test_problems.py tests/test_pagination.py tests/test_timestamps.py tests/test_app_hardening.py tests/test_app.py` → 154 passed; 14 mutations plus control in throwaway copies; ruff, ruff format, mypy --strict (74 files).
- W: the lead's clean run → full suite 996 passed, 0 skipped, coverage 99.32 %.

## Criteria
| REQ-038 | Result | Rows |
| --- | --- | --- |
| (1) problem details for every error class | PASS | CHK-M2-040 |
| (2) no trace, SQL, DSN, token or password in error bodies | PASS | CHK-M2-041 |
| (3) field named, never value or client-chosen key; 400 | PASS (round 3) | CHK-M2-042 |
| (4) limit 1–500, default 50, walk, null last cursor, tampered and foreign cursors | PASS | CHK-M2-043, -044 |
| (5) RFC 3339 UTC timestamps: the shared type | PASS; responses re-checked in TASK-038, -041, -043 | CHK-M2-045 |
| #52 ids as JSON integers | PASS | CHK-M2-046 |

Mutations: 14/14 red, control green. Test files added: `test_problems.py`, `test_pagination.py`, `test_timestamps.py`.
