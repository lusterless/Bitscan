# TASK-011 TEST report: runtime database dependencies

Tester: tester. REQ-018. Date 2026-10-20. Impl report: `work/reports/TASK-011-impl.md`. Windows: CPython 3.12.10, pip 25.0.1. WSL: Ubuntu 24.04.5 x86_64, CPython 3.12.3. uv 0.13.1.

## Verdict: PASS

The real aarch64 install is NOT RUN (there is no arm64 host). The wheel-hash proxy covers aarch64 (CHK-M1-003), and CI runs Linux x86_64.

## Tests changed

`manager/tests/test_lock_files.py` gains `test_runtime_lock_has_the_database_stack`. It checks that alembic, sqlalchemy 2.x, psycopg 3.x and psycopg-binary are present at the same version, with psycopg listed once. A planted removal of alembic turns it red.

## Commands and counts

- Fresh-venv installs: 4 (2 locks on Windows and 2 on WSL), all exit 0 with 0 builds.
- Tampering plants: 7 (3 per lock on Windows, plus 1 on WSL), all exit 1 with the expected pip message.
- Linux proxy: 142 wheel downloads, 0 problems.
- Lock regeneration: 2/2 byte-identical.

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-018 (1): both locks install with `--require-hashes` in fresh 3.12 venvs on Windows and Linux; aarch64 via the proxy | CHK-M1-001, CHK-M1-003 | PASS (aarch64 real install NOT RUN) |
| G4: one altered `alembic` hash is red (also removed hashes and an unpinned line) | CHK-M1-002 | PASS |
| REQ-018 (2): `import alembic, sqlalchemy, psycopg` after the runtime install; libpq with TLS | CHK-M1-004 | PASS |
| REQ-018 (3): no test or lint tool in the runtime lock | CHK-M1-005 | PASS |
| REQ-018 (4): the recorded lock command reproduces both files byte for byte | CHK-M1-006 | PASS |
| REQ-018 (5): mypy --strict still exits 0 (and ruff, format, coverage gate) | CHK-M1-007 | PASS |

## Notes

- `psycopg[binary]` bundles its own libpq: 18.4 on Windows, 18.6 on Linux, both with TLS. The lead decided to keep it (work/decisions.md, 2026-10-20).
- `manager/.venv` was re-synced with uv and has no pip. The proxy therefore ran from a fresh pip venv built from the dev lock.
