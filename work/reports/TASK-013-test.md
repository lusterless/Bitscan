# TASK-013 TEST report: Alembic environment, migration runner, `db migrate`

Tester: tester. REQ-020 (and the TP-M1-01 part of REQ-032). Date 2026-10-20. Impl report: `work/reports/TASK-013-impl.md`. WSL Ubuntu 24.04, Docker Engine, PostgreSQL 16 test image with TLS; `/root/venv` from the hashed dev lock.

## Verdict: PASS

This is the first run against a real PostgreSQL. impl-manager's WSL smoke run was blocked, so these are the first real-database results.
- Every REQ-020 case I could run passes on a Bootstrap-only container driven through the installed CLI.
- The forward-only checks are vacuous until `m0001` exists (TASK-014). They are re-run then.
- The TP-M1-02 harness checks (CHK-M1-031 to -036) belong to tester-b (PD-17) and are not covered here.

## Tests added or changed

- `manager/tests/test_db_migrate.py` (TP-M1-04), 14 cases: 6 pg, 8 local.
- `manager/tests/test_cli.py`, updated for REQ-008 as narrowed by REQ-020.
- `manager/tests/test_conftest_hook.py` (TP-M1-01), 10 cases.
- Harness additions (TP-M1-02): `bootstrapped_server()`, the `fresh_pg_server`, `migrated_db`, `app_conn`, `retention_conn` and `owner_conn` fixtures, and `run_cli`.

## Commands and counts

- Windows: ruff, format and mypy (22 files) clean; `pytest` 200 local cases pass, pg skipped `not run: Docker unavailable`.
- WSL, `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 274 passed, 0 skipped, gate reached; no leftover containers.
- Mutations: 5 in the db runner and the CLI, each red; 7 in the hook, each red.
- One-off: `db migrate` from a non-editable wheel install.

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-020 (1) Bootstrap-only database, migrate exits 0 at head | CHK-M1-050 | PASS (head `base`) |
| (2) everything owned by bitscan_owner; alembic_version in public (#41) | CHK-M1-051 | PASS |
| (3) second run changes nothing | CHK-M1-052 | PASS |
| (4) forward-only: no downgrade, other db commands refused | CHK-M1-053 | PASS (static part vacuous until m0001) |
| (5) non-member role exits non-zero, creates nothing | CHK-M1-054 | PASS |
| (6) unset variable named; no canary on any path | CHK-M1-055 | PASS |
| (7) serve, users, bits and unknown keep the M0 behaviour | CHK-M1-056 | PASS |
| (8) works from a non-editable wheel install | CHK-M1-057 | PASS |
| (9) S608 active | CHK-M1-058 | PASS |
| REQ-032 (6) conftest hook (pytester) | CHK-M1-030 | PASS |

## Notes

- Exit codes are 0 success, 1 database failure, 2 configuration or usage, as the impl report says.
- The ownership test depends on the final `connection.commit()`. Without it, `alembic_version` is never made durable, and the mutation run shows the test catches that.
