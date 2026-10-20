# TASK-015 TEST report: migration m0002 (fleet and inventory)

Tester: tester. REQ-022, REQ-029. Date 2026-10-20. Impl report: `work/reports/TASK-015-impl.md`.

## Verdict: PASS

One deviation was raised and accepted by the lead: REQ-029 (2) is re-run with the host's dpkg, not the container's (see Notes).

## Tests added

- `manager/tests/test_schema_fleet.py` (TP-M1-06): 15 pg cases, written from TS §5.2 L709–L825 before the migration was read.
- `manager/tests/test_debversion.py` (TP-M1-07): 3 unit and 5 pg cases.
- `manager/tests/fixtures/debversion_pairs.tsv`: 1275 pairs, generated with dpkg 1.22.6.

## Commands and counts

- Windows: ruff, format and mypy (28 files) clean; unit cases pass, pg skipped `not run: Docker unavailable`.
- WSL (`/root/bitscan-tester`, `/root/venv-tester`), `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 318 passed, 0 skipped.
- Mutations in the WSL copy: 7 of m0002 plus the G21 fixture flip, each red.

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-022 (1) diff-equal to TS §5.2 L709–L825 | CHK-M1-080 | PASS |
| (2) tokens stored only as hashes; machine_id | CHK-M1-081 | PASS |
| (3) enrollment_token limits and defaults | CHK-M1-082 | PASS |
| (4) agent status, request sets, RESTRICT, cascades | CHK-M1-083 | PASS |
| (5), (6) package identity, index definitions | CHK-M1-084 | PASS |
| REQ-029 (1) fixture of at least 500 pairs with the categories | CHK-M1-100 | PASS |
| (2) dpkg agrees with every pair (G21) | CHK-M1-101 | PASS (host dpkg, accepted) |
| (3) debversion agrees, as bitscan_owner | CHK-M1-103 | PASS |
| (4) at least 20 text-versus-debversion differences | CHK-M1-104 | PASS |
| (5) EXPLAIN uses ix_package_name_debver | CHK-M1-105 | PASS |
| (6) package.version stays VARCHAR(255) | CHK-M1-106 | PASS |

## Notes

- RESTRICT is checked through `pg_constraint.confdeltype = 'r'`, because PostgreSQL reports RESTRICT and NO ACTION with the same SQLSTATE (23503).
- REQ-029 (2): dpkg runs on the pg host (WSL Ubuntu, the CI Ubuntu runner), not in the test container, because the harness exposes no container handle after the superuser ruling. Accepted by the lead (work/decisions.md, 2026-10-20): TS §7.2 requires a test against `dpkg --compare-versions` on at least 500 pairs, which this satisfies.
