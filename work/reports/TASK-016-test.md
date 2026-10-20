# TASK-016 TEST report: migration m0003 (scanning)

Tester: tester. REQ-023. Date 2026-10-20. Impl report: `work/reports/TASK-016-impl.md`.

## Verdict: PASS

## Tests added

`manager/tests/test_schema_scanning.py` (TP-M1-08), 10 pg cases, written from TS §5.2 L842–L938 before the migration was read. The direct-to-default cases use a job dated 2000-01-01, so they stay valid once m0005 adds the monthly partitions.

## Commands and counts

- Windows: ruff, format and mypy (30 files) clean.
- WSL (`/root/bitscan-tester`, `/root/venv-tester`), `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 328 passed, 0 skipped.
- Mutations of m0003 in the WSL copy: 11, each red. One first attempt was an invalid plant (the trigger pointed at a table not yet created) and was replaced by "trigger BEFORE UPDATE only".

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-023 (1) diff-equal to TS §5.2 L842–L938 | CHK-M1-090 | PASS |
| (2) scan_job CHECKs, pickup_by, partial ix_job_pending | CHK-M1-091 | PASS |
| (3) RANGE partitioning, DEFAULT partition | CHK-M1-092 | PASS |
| (4) trigger through the parent and the default partition | CHK-M1-093 | PASS |
| (5) eval_code, generated result, snapshot NOT NULLs | CHK-M1-094 | PASS |
| (6), (7) scan trigger, deletes, reeval CHECK | CHK-M1-095 | PASS |
| TS §5.2 L916: default partition empty after migrate | CHK-M1-096-pre | PASS |
| REQ-020 with m0003 | CHK-M1-050-r4 | PASS |
