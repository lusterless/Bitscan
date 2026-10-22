# TASK-043 TEST report: /api/v1/users routes

Verdict: **PASS**. Tester, 2026-10-22. REQ-052, REQ-046 (1), (3), (5), REQ-045 (1), REQ-054 (3), (4), REQ-038 (4); #47, #53, #56; lead rulings 2026-10-22 (PATCH takes exactly one action; POST 201; `{disabled:true}` 400; route walk sees the `admin_totp` marker). Impl report: `work/reports/TASK-043-impl.md`.

## Commands run
- W: `tester2_t046r1.sh`, alone: wave files 238 passed; full suite 1505 passed, 0 skipped, services 99.32 %; 11 mutants plus control.
- L: ruff, ruff format, mypy --strict (120 files); `test_cli.py`, `test_openapi.py`, `test_app.py`, `test_auth_dependencies.py`: 69 passed (27 PG tests need Docker, run on W).

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-052 (1)–(7) actions and their effects | PASS | CHK-M2-230 |
| REQ-046, REQ-045 (1) wrong callers refused on every method | PASS | CHK-M2-231 |
| REQ-054 (3), (4) 15-minute sink gate | PASS | CHK-M2-232 |
| REQ-052 (9) no hash or seed in responses | PASS | CHK-M2-233 |
| REQ-052 (6) restricted sign-in after reset | PASS | CHK-M2-234 |
| REQ-038 (4) pagination and ids | PASS | CHK-M2-235 |
| G6 export and paths | PASS | CHK-M2-236 |
| UTC timestamps | PASS | CHK-M2-045-r043 |
| TASK-041 follow-up: `admin_totp` marker | PASS | CHK-M2-216-r043 |

Mutations: 10 of 11 red, control green. `post-admin-allowed` is equivalent (the service also refuses admin; covered alone by `test_users_service.py:210-221`, and both layers together by the red `post-admin-allowed-both-layers`). Test defects of mine fixed before the evidence run: a missing comma in the caller list, and the unverified-admin expectation (`totp_enrolment_required`). Test file added: `test_users_api_pg.py`; updated: `test_auth_dependencies.py`, `test_app.py`, `test_openapi.py`.

## Revision 1 (reviewer finding 1: a PATCH field sent as null triggered its action)
Verdict: **PASS**. Impl report: `work/reports/TASK-043-impl.md` ("Revision 1").
- Test added: `test_users_api_pg.py::test_patch_null_is_refused_unless_it_is_the_documented_value`. `{revoke_tokens: null}`, `{disabled: null}` and `{role: null}` each give 400 `invalid_request` and change nothing (rows, tokens, audit count), on enabled and disabled targets with TOTP, a session and an API token. `{totp: null}` still resets TOTP and `{disabled: false}` still re-enables with `user.enable` (existing tests).
- Commands: W `tester2_t043r1.sh`, alone: 135 passed in the users files; full suite 1511 passed, 0 skipped, services 99.32 %. L: ruff, ruff format, mypy --strict clean.
- Mutations: 7 of 8 red, control green. The old "presence counts" behaviour (`documented-check-removed`) is red. `null-role-accepted` is equivalent, because the service refuses role `"None"` with the same 400.
- Rows: CHK-M2-230-r1, CHK-M2-305-w9r1.
