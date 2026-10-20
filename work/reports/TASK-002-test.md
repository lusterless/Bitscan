# TASK-002 TEST report: manager package skeleton

Tester: tester. REQ-003 to REQ-008. Date 2026-10-20. Impl report: `work/reports/TASK-002-impl.md`. CPython 3.12.10, `manager/.venv` from the dev lock plus the editable install.

## Verdict: PASS

The PostgreSQL-marked tests (TASK-003) are skipped locally with "not run: Docker unavailable". They do not count toward this verdict.

## Tests added

- `manager/tests/test_app.py` (13 tests), `manager/tests/test_openapi.py` (5) and `manager/tests/test_cli.py` (15). They were written from REQ-006 to REQ-008 and the TASK-002 plan interface before the code was read.
- 15 source mutations in throwaway copies each turn at least one test red: docs and schema served, CORS added, route added, env read at import, network in `create_app`, unsorted or CRLF export, version bump, stale committed JSON, serve returns 0, usage on stdout, help fails, and CLI socket, env read and DB import.
- One mutation, `docs_url="/docs"` with `openapi_url=None`, is equivalent: FastAPI serves no docs without a schema URL. It stays green, which is correct.

## Commands and counts

- Tree: ruff check, ruff format --check, mypy --strict (12 files) and `pytest --cov=bitscan_manager/services --cov-fail-under=85`: all exit 0 (55 passed, 3 skipped as not run, coverage 100 %).
- Gate plants in a copy of `manager/` without `.venv`, deleted afterwards: 33. Each was red with the expected code (F401, TID251, S608, format, no-untyped-def, fail-under), and the 6 negative controls were green.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| ruff, ruff format, `mypy --strict` and the coverage command pass | CHK-M0-020, CHK-M0-027, CHK-M0-029, CHK-M0-032 | PASS |
| REQ-003 (2) to (6): unused import, misformat, XML parsers (also xmlrpc and plistlib), f-string SQL, `re` | CHK-M0-021 to CHK-M0-028 | PASS |
| REQ-004 (2), (3): unannotated product and test function | CHK-M0-030, CHK-M0-031 | PASS |
| REQ-005 (2), (3): report lists only services; untested module fails the gate | CHK-M0-033, CHK-M0-034 | PASS |
| REQ-006 (1) to (5): 404 doc and API paths, no routes, no CORS, distinct apps, no env or network | CHK-M0-035 to CHK-M0-039 | PASS |
| REQ-007 (1) to (5): byte-identical canonical export, 3.1, empty paths, committed file in sync and red on a change | CHK-M0-040, CHK-M0-041 | PASS (the `git diff` form runs in CI) |
| REQ-008 (1), (2): `--help` 0; everything else non-zero on stderr, with no env, socket or DB | CHK-M0-042 to CHK-M0-044 | PASS |
| TASK-001 plan step 3: installs from hashed locks with `--no-deps --no-build-isolation` | CHK-M0-045 | PASS |
