# TASK-020 TEST report: audit chain append

Tester: tester. REQ-030. Date 2026-10-20. Impl report: `work/reports/TASK-020-impl.md`. Decision #38. TP-M1-14.

## Verdict: PASS

## Tests

- `manager/tests/test_audit_chain.py` (unit, no PostgreSQL):
  - the #38 reference, written independently of the code, plus two hand-computed known-answer vectors;
  - each field changes the hash; NULL differs from empty; non-ASCII is kept as UTF-8;
  - the fake-repo call order; NaN and inf refused before any repo call; a repo failure inserts nothing;
  - nothing printed or logged, and no network connection opened.
- `manager/tests/test_audit_append_pg.py` (PostgreSQL, a container per test, migrated through the CLI):
  - server time and the canonical jsonb text;
  - 8 × 25 concurrent writers;
  - a held append blocks the next writer, on commit and on rollback;
  - appends as bitscan_app and as bitscan_retention without UPDATE or DELETE;
  - isolation refusals: connection level, session default and autocommit;
  - column limits; nothing logged; a rolled-back id gap.
- Fixes by this tester:
  - the lint and type issues;
  - an `isolation_level` keyword wrongly passed to `psycopg.connect()` (a test bug);
  - AuditError is now imported from `bitscan_manager.services.audit`, its stable name across the TASK-021 move.

## Commands and counts

- Windows:
  - `ruff check manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml manager` are clean;
  - `pytest --cov=bitscan_manager/services --cov-fail-under=85`: 364 passed, 159 skipped (pg), coverage 100 %.
- WSL (CI=true, Ryuk pinned, a fresh copy, the venv from the hashed dev lock): 523 passed, 0 skipped, coverage 100 %, 0 leftover containers.
- Mutations (WSL copy):
  - lock removed: 3 red;
  - SHOW isolation check removed: 2 red.

## Acceptance criteria → [tests/m1/report.md](../../tests/m1/report.md)

| REQ-030 | Check | Result |
| --- | --- | --- |
| (1) links, genesis, recomputed row_hash | CHK-M1-200, CHK-M1-203 | PASS |
| (2) 8 concurrent writers, 200 entries, one chain | CHK-M1-204, CHK-M1-228 | PASS |
| (3) held append waits on the advisory lock; relinks after a rollback | CHK-M1-205, CHK-M1-228 | PASS |
| (4) app and retention append without UPDATE or DELETE | CHK-M1-206 | PASS |
| (5) RR, SERIALIZABLE and autocommit never fork | CHK-M1-207, CHK-M1-228 | PASS |
| (6) column limits | CHK-M1-208 | PASS |
| (7) no logs, no output, no network | CHK-M1-202, CHK-M1-209 | PASS |
| (8) pure hash; unit coverage gate on Windows | CHK-M1-200, CHK-M1-201 | PASS |
