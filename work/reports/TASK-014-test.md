# TASK-014 TEST report: migration m0001 (policy catalog)

Tester: tester. REQ-021, REQ-020 (and the REQ-027 method). Date 2026-10-20. Impl report: `work/reports/TASK-014-impl.md`. Decision #40 (reference method), #41.

## Verdict: PASS

## Tests added or changed

- `manager/tests/schema_diff.py` (TP-M1-05): extracts the reference from the spec, dumps the catalog and reports differences by object.
- `manager/tests/test_schema_catalog.py`: 3 unit and 14 pg cases. They were written from TS §5.2 L638–L707 before the migration was read.
- `manager/tests/conftest.py`: the `reference_db` fixture and `create_reference_db` (#40).
- `manager/tests/test_db_migrate.py`: the bind-trap scanner and its test (CHK-M1-059).

## Commands and counts

- Windows: ruff, format and mypy (25 files) clean; 263 passed, 30 pg skipped `not run: Docker unavailable`.
- WSL, `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85` in /root/bitscan-tester: 293 passed, 0 skipped, gate reached.
- Mutations of m0001 in the WSL copy: 7, each red.
- Local plants on the migration: G1 S608, G2 format, G3 unannotated `upgrade()`, a working `downgrade()`, and 2 bind traps; each red.

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-021 (1) catalog objects diff-equal to TS §5.2 L638–L707 | CHK-M1-070 | PASS |
| (2) enum labels in spec order | CHK-M1-071 | PASS |
| (3) timeout_s bounds and default; mode and outcome sets | CHK-M1-072 | PASS |
| (4) defaults | CHK-M1-073 | PASS |
| (5) uniqueness, FK, cascade | CHK-M1-074 | PASS |
| REQ-020 (4) forward-only, now with a real migration | CHK-M1-053-r2 | PASS |
| m1 brief: no `:word` bind traps | CHK-M1-059 | PASS |
| G1, G2, G3 on a migration | CHK-M1-058-r2, CHK-M1-022, CHK-M1-023-r2 | PASS |
| REQ-020 (1)-(3) with m0001 | CHK-M1-050-r2 | PASS |

## Notes

- The reference database needs one more superuser step: the database half of the Bootstrap for `bitscan_ref`. It is listed in `tests/m1/test-plan.md` as superuser item 4. The spec DDL itself runs as bitscan_owner.
- Per-domain diffs leave ACLs out. Grants are compared once, in TASK-018 (CHK-M1-150).
