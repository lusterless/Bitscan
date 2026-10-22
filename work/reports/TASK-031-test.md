# TASK-031 TEST report: app_user and user_token repositories

Verdict: **PASS**. Tester, 2026-10-21. REQ-044, REQ-048, REQ-051, REQ-052 (repository parts). Impl report: `work/reports/TASK-031-impl.md`. Two-approval task. This is the first run of these statements against PostgreSQL.

## Commands run
- W: `tester2_t033.sh` (fresh copy `/root/bitscan-tester`, `/root/venv-m2`, `CI=true`): `pytest tests/test_user_repos_pg.py` → 31 passed.
- W: `tester2_mut031.sh`: 12 mutations in copies under `/root/bitscan-mut/<name>/manager`, plus a control.
- L: ruff (and S608 planted in a copy), ruff format, mypy --strict (55 files), the full suite.

## Criteria
| Acceptance (TASK-031) | Result | Rows |
| --- | --- | --- |
| every function works as `bitscan_app` with only the TS §5.2 grants | PASS | CHK-M2-091, -095 |
| TOTP-step update: exactly one of two concurrent callers | PASS (deterministic interleave and 10 threads) | CHK-M2-092 |
| back-off atomic under 10 concurrent failures; 1…900 s; no SMALLINT overflow | PASS | CHK-M2-093 |
| token lookup by `token_hash` only | PASS | CHK-M2-094 |
| admin-row locking | PASS | CHK-M2-096 |
| ruff S608 | PASS | CHK-M2-090 |

Mutations: 12/12 red, control green. Rows are in [tests/m2/report.md](../../tests/m2/report.md). Test file added: `manager/tests/test_user_repos_pg.py`.
