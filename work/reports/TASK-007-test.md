# TASK-007 TEST report: agent systemd units, verbatim from TS §3.7

Tester: tester. REQ-016. Date 2026-10-20. Impl report: `work/reports/TASK-007-impl.md`.

## Verdict: PASS

All locally runnable checks pass. `systemd-analyze verify` (G17, CHK-M0-124 and CHK-M0-125) is NOT RUN locally (no systemd, WSL or Docker, PD-15) and is carried to TASK-010 CI; this verdict does not cover it.

## Test added

`deploy/tests/check_units_verbatim.py`: written from the TS line ranges in `work/tasks.md` before the unit files were read. It asserts each opening fence is ```` ```ini ```` and each closing fence is ```` ``` ````, compares bytes (LF, final newline), flags CR bytes, end-of-line comments and an `[Install]` section in `bitscan-capread.service`, and with `all` rejects missing or extra files in `deploy/systemd/`.

## Commands and counts

- `$P; python deploy/tests/check_units_verbatim.py agent` and `... all`: exit 0, 5 (agent) / 9 (all) units identical, 0 problems.
- Planted cases in a throwaway copy: 9 run, 9 red with the expected message; unmodified-copy control green. Copy deleted.

## Acceptance criteria (REQ-016) -> rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| (1) five files byte-identical to TS L289-L302, L308-L363, L369-L408, L437-L449, L451-L482 (fences removed) | CHK-M0-120 | PASS |
| (2) no `#` after a directive | CHK-M0-122 | PASS |
| (3) `bitscan-capread.service` has no `[Install]` | CHK-M0-123 | PASS |
| (4) `systemd-analyze verify` exits 0 with no output (binaries installed) | CHK-M0-124 | NOT RUN locally (no systemd) |
| (5) planted EOL comment / unknown directive reported by `systemd-analyze` | CHK-M0-125 | NOT RUN locally (no systemd) |

## Notes

- The impl report's own `sed | cmp` check agrees with the script.
- Two approvals required (TS §8.2): reviewer plus the user.
