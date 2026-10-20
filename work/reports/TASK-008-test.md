# TASK-008 TEST report: manager systemd units, verbatim from TS §8.7

Tester: tester. REQ-016, REQ-008. Date 2026-10-20. Impl report: `work/reports/TASK-008-impl.md`.

## Verdict: PASS

All locally runnable checks pass. `systemd-analyze verify` (G17, CHK-M0-124 and CHK-M0-125) is NOT RUN locally (no systemd, WSL or Docker, PD-15) and is carried to TASK-010 CI, which also needs `/usr/bin/bitscan-manager` from TASK-002; this verdict does not cover it.

## Test added

`deploy/tests/check_units_verbatim.py` (shared with TASK-007), `manager` and `all` modes.

## Commands and counts

- `$P; python deploy/tests/check_units_verbatim.py manager` and `... all`: exit 0, 4 / 9 units identical, 0 problems.
- Planted cases in a throwaway copy (changed directive value, extra and missing final newline): 3 run, 3 red; control green. Copy deleted.

## Acceptance criteria (REQ-016) -> rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| (1) four files byte-identical to TS L1352-L1401, L1405-L1435, L1439-L1467, L1469-L1480 (fences removed) | CHK-M0-121 | PASS |
| (2) no `#` after a directive | CHK-M0-122 | PASS |
| exactly the nine unit files in `deploy/systemd/` | CHK-M0-123 | PASS |
| (4) `systemd-analyze verify` exits 0 with no output (`/usr/bin/bitscan-manager` installed) | CHK-M0-124 | NOT RUN locally (no systemd) |
| (5) planted error reported by `systemd-analyze` | CHK-M0-125 | NOT RUN locally (no systemd) |
