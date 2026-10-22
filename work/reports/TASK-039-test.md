# TASK-039 TEST report: TOTP enrolment and replacement

Verdict: **PASS** (round 2, revision 1). Tester, 2026-10-22. REQ-049, REQ-043 (1); #49 (b), #53 (b), #58; lead rulings on TASK-039 (a) one alert entry, (b) 403/409, (c) failures count (user decision). Impl report: `work/reports/TASK-039-impl.md` (revision 1). Two-approval task.

## Rounds
- Round 1: **FAIL** on ruling (c). Failed replacement attempts (wrong password, wrong code, reused code) were not counted: `failed_logins` stayed 0, with no back-off and no `login_failures` alert. A start during back-off was not refused. Evidence: the CHK-M2-192a tests and the "not counted" mutants, which reproduce the round 1 code and fail them.
- Round 2 (revision 1): replacement failures go through the sign-in failure path; during back-off only the dummy check runs. All pass. My first run of the original tests was void (my own wrong expected type, which made the control red), and is not counted.

## Commands run
- W: `tester2_t039.sh` (TASK-039 plus login files, 71 passed; full suite 1394 passed, 0 skipped; 20 mutants) and `tester2_t040.sh` (1 strengthened-test mutant), each alone.
- L: ruff, ruff format, mypy --strict (112 files).

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-049 (1) API tokens refused | PASS | CHK-M2-190 |
| REQ-049 (2) restricted admin enrols; old token refused; 24 h max kept | PASS | CHK-M2-191 |
| REQ-049 (3) replacement needs password and a fresh code | PASS | CHK-M2-192 |
| ruling (c) failures count; back-off honoured | PASS (round 2) | CHK-M2-192a |
| REQ-049 (4) wrong confirmation keeps the old seed | PASS | CHK-M2-193 |
| REQ-049 (5) one alert per event | PASS | CHK-M2-194 |
| REQ-049 (6), REQ-043 (1) only ciphertext stored | PASS | CHK-M2-195 |
| REQ-049 (7), #53 (b) | PASS | CHK-M2-196 |
| #49 (b), #58 | PASS | CHK-M2-197, -198 |
| no secrets; OpenAPI | PASS | CHK-M2-199, -185-r039 |

Mutations: 20/20 red against a green control. One mutant (the real password verified during back-off) survived until the back-off test also asserted that only the dummy hash is verified. Test file added: `test_totp_enrol.py`; updated: `test_login.py`.
