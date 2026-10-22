# TASK-042 TEST report: users service

Verdict: **PASS**. Tester, 2026-10-21. REQ-052, REQ-041, REQ-055; #7, #50, #53, #56 (d) (answer (4)); lead rulings on TASK-042. Impl report: `work/reports/TASK-042-impl.md`. Two-approval task.

## Commands run
- L: `pytest tests/test_users_service.py` → 50 passed; 15 mutations plus control; ruff, ruff format, mypy --strict.
- W: `tests/test_users_service_pg.py` in `tester2_t034.sh` and `tester2_w4mut.sh` (2 W mutations); full suite 1248 passed, 0 skipped; `accounts.py` 100 %.

## Criteria
| REQ-052 | Result | Rows |
| --- | --- | --- |
| (1) create, duplicate, username rules (ASCII only) | PASS | CHK-M2-220 |
| (2) disable keeps the row, revokes everything | PASS | CHK-M2-221 |
| (3), (4) promotion needs TOTP; raise ends sessions; lowering ends sessions and API tokens | PASS | CHK-M2-222 |
| (5) last active admin, also under concurrency | PASS | CHK-M2-223, -228 |
| (6) TOTP reset by another admin or the CLI, not oneself | PASS | CHK-M2-224 |
| (7) revoke a user's tokens | PASS | CHK-M2-225 |
| (8) change and audit in one transaction; one alert per event | PASS | CHK-M2-226, -229 |
| #53 (g) re-enable | PASS | CHK-M2-227 |

Mutations: 15/15 unit and 2/2 Linux red, control green, including the requested double alert on promotion to admin. Test files added: `test_users_service.py`, `test_users_service_pg.py`.
