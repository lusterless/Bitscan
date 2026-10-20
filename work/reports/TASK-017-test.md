# TASK-017 TEST report: migration m0004 (system tables)

Tester: tester. REQ-024. Date 2026-10-20. Impl report: `work/reports/TASK-017-impl.md`.

## Verdict: PASS

## Tests added

- `manager/tests/test_schema_system.py` (TP-M1-09), 30 pg cases, written from TS §5.2 L827–L840 and L941–L990 before the migration was read.
- `conftest.migrate_to()`: upgrades to a named revision as bitscan_migrate with SET ROLE bitscan_owner. It reaches the m0004-only state that the CLI never stops at.

## Commands and counts

- Windows: ruff, format and mypy (32 files) clean.
- WSL (`/root/bitscan-tester`, `/root/venv-tester`), `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 358 passed, 0 skipped.
- Mutations of m0004 in the WSL copy: 9, each red.

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-024 (1) diff-equal; system_schedule and setting empty at m0004 | CHK-M1-096 | PASS |
| (2) no `enabled` column; job_kind and interval CHECKs | CHK-M1-097 | PASS |
| (3) user_token CHECK, hash, partial index | CHK-M1-098 | PASS |
| (4) app_user defaults and labels | CHK-M1-098 | PASS |
| (5) task kind and state | CHK-M1-098 | PASS |
| (6) audit_log hash columns (append-only grants are m0005, TP-M1-10) | CHK-M1-098 | PASS |
| REQ-020 with m0004 | CHK-M1-050-r5 | PASS |
