# TASK-040 TEST report: change own password

Verdict: **PASS**. Tester, 2026-10-22. REQ-050, REQ-041; #53 (a), #56 (b); lead rulings on TASK-040 and TASK-039 (c). Impl report: `work/reports/TASK-040-impl.md`. Two-approval task.

## Commands run
- W: `tester2_t040.sh`, alone: `tests/test_password_change.py` (16) plus the enrolment and login files, 58 passed; full suite 1410 passed, 0 skipped; 11 mutants plus control, each pytest under `timeout 600`.
- L: ruff, ruff format, mypy --strict (112 files).

## Criteria
| REQ-050 | Result | Rows |
| --- | --- | --- |
| (1) API token refused | PASS | CHK-M2-200 |
| (2) wrong current password refused, counted; back-off honoured | PASS | CHK-M2-201 |
| (3), REQ-041 (2) new-password rules, checked first | PASS | CHK-M2-202 |
| (4), #53 (a) all sessions end, the caller's too; API tokens kept | PASS | CHK-M2-203 |
| (5) one audit entry, no password | PASS | CHK-M2-204 |
| restricted admin; no secrets; hashing under the gate | PASS | CHK-M2-205 |

Mutations: 11/11 red, control green, including both you asked for: the old "not counted" behaviour, and the new-password hash outside the gate. Test file added: `test_password_change.py`.
