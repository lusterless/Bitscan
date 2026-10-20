# TASK-018 TEST report: migration m0005 (privileges, view, seeds, partitions)

Tester: tester. REQ-025, REQ-026, REQ-027 (and REQ-029 (3) as bitscan_app). Date 2026-10-20. Impl report: `work/reports/TASK-018-impl.md`. Decisions #40 to #43; scanner scope ruling 2026-10-20.

## Verdict: PASS

## Tests added or changed

- `manager/tests/test_grants.py` (TP-M1-10): a statement-probe matrix generated from the catalog, plus the explicit cases.
- `manager/tests/test_seeds_partitions.py` (TP-M1-11).
- `manager/tests/test_schema_diff.py` (TP-M1-12): the whole schema including ACLs.
- `manager/tests/test_debversion.py`: the bitscan_app case.
- `manager/tests/test_db_migrate.py`: the scoped bind-trap scanner.
- `manager/tests/spec_sql.py`: `redaction_patterns()` reads the spec's text fence.

All were written from TS §5.2 L992–L1013, L1037–L1042, L832–L833 and TS §8.6 before m0005 was read, except the scanner scope, which was changed after main's ruling.

## Commands and counts

- Windows: ruff, format and mypy (36 files) clean.
- WSL (`/root/bitscan-tester`, `/root/venv-tester`), `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 408 passed, 0 skipped.
- Plants in the WSL copy:
  - m0006 G19: 5, each red;
  - m0006 G20 and default privileges: 4, each red;
  - m0005: 7 red, and 2 equivalent mutants identified (the v_plugin grant, partition order).

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-025 (1) app SELECT and INSERT everywhere, exact UPDATE and DELETE sets | CHK-M1-130 | PASS |
| (2) no change to results, audit or imports, including partitions | CHK-M1-131 | PASS (the db maintain partition is TASK-019) |
| (3) no DELETE on core rows | CHK-M1-132 | PASS |
| (4) jobs and scans cannot be moved | CHK-M1-133 | PASS |
| (5) retention's set, checkpoint insert, sequence | CHK-M1-134 | PASS |
| (6) v_plugin | CHK-M1-135 | PASS |
| (7) default privileges on later tables | CHK-M1-136 | PASS |
| (8) TRUNCATE, REFERENCES, TRIGGER; migrate holds nothing | CHK-M1-137 | PASS |
| G20 | CHK-M1-139 | PASS |
| REQ-026 (1)–(7) | CHK-M1-140 to CHK-M1-146 | PASS |
| REQ-027 (1)–(3), G19 | CHK-M1-150 to CHK-M1-152 | PASS |
| REQ-029 (3) as bitscan_app | CHK-M1-138 | PASS |
| Bind-trap scanner scope (ruling) | CHK-M1-059-r2 | PASS |

## Notes

- On PG15+, PUBLIC keeps USAGE on schema public, so the spec's `GRANT USAGE ON SCHEMA public` has no visible effect. CREATE stays refused (CHK-M1-137-pg16).
- Equivalent mutants (no observable change, the reference behaves the same): removing `GRANT SELECT ON v_plugin`, and creating the partitions before the grants. Both are covered by the default privileges or `GRANT ... ON ALL TABLES`.
