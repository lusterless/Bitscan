# TASK-025 TEST report: runtime contract and app database pool

Verdict: **PASS** (code round 2, revision 1; Linux mutations in round 3). Tester, 2026-10-21. REQ-044, REQ-055, REQ-056 (contract parts). Impl report: `work/reports/TASK-025-impl.md` (revision 1).

## Rounds
- Round 1: **FAIL** on CHK-M2-036. Expected `ping()` False within about 2 s when the server stops answering. Actual, with the container paused by `docker pause`: no result after 60.0 s; True after unpause. Diagnosis: `SET LOCAL statement_timeout` is enforced by the server, so it cannot fire when the server is silent on an open pooled connection.
- Round 2 (revision 1, own-connection probe with a 2 s wait): passes on L. The full W suite passed (996 passed, 0 skipped), but the W mutation stage hung for over 2 h on the round-1 ping mutant. The cause was a test defect: no time limit around `ping()`. The lead stopped it.
- Round 3: every `ping()` and `close()` in the PostgreSQL tests runs on a thread with a 10 s limit. `tester2_t025r3.sh` ran once, alone (preflight `other runs=0 containers=0`). Control green; all three mutants red; docker pause probe as expected; no leftovers.

## Commands run
- L: `pytest tests/test_runtime.py` (19 tests) and 10 mutations plus control; ruff, ruff format, `mypy --strict` (74 files).
- W: the lead's clean run (full suite 996 passed, 0 skipped, services coverage 99.32 %); `tester2_t025r3.sh` (3 mutants, each under `timeout 120`; docker pause probe under `timeout 180`).

## Criteria
| Acceptance (TASK-025) | Result | Rows |
| --- | --- | --- |
| a `Runtime` from fakes passes `mypy --strict` | PASS | CHK-M2-030 |
| on-commit hooks after commit, never after rollback | PASS | CHK-M2-031, -034 |
| pool connections are `bitscan_app`, READ COMMITTED, not autocommit; an audit append commits | PASS | CHK-M2-033 |
| no DSN canary in errors or logs when the database is unreachable | PASS | CHK-M2-035 |
| `ping()` for /readyz never raises and is bounded | PASS (round 3) | CHK-M2-036 |
| nested transaction refused | PASS | CHK-M2-037 |

Mutations: 10/10 on L and 3/3 on W red, controls green. Rows are in [tests/m2/report.md](../../tests/m2/report.md). Test files added: `test_runtime.py`, `test_db_pool_pg.py`.

## Notes
- Out of scope here (decisions 2026-10-21, "Database time bounds"): a statement on an already-open connection has no client-side limit. It moves to TASK-045 (keepalives, `tcp_user_timeout` 300 s, `statement_timeout` 5 min).
- Test change: `test_db_pool_pg.py` uses a pausable TCP proxy rather than importing `docker` (the M1 harness rule). The real `docker pause` stays a probe in the WSL script.
