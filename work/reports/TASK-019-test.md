# TASK-019 TEST report: `bitscan-manager db maintain`

Tester: tester. REQ-028 (and REQ-025 (2) on a maintain-created partition). Date 2026-10-20. Impl report: `work/reports/TASK-019-impl.md`. Decisions #43, #44.

## Verdict: PASS

## Tests added or changed

- `manager/tests/test_db_maintain.py` (TP-M1-13): 12 unit and 7 pg cases. Written from TS §5.3 L1047, REQ-028, #43, #44 and the plan interface before maintain.py was read. The drop cases were then aligned to calendar months, because the plan refuses non-month partitions.
- `manager/tests/test_cli.py`: `db maintain` is now a real command.
- The malformed-DSN case covers the TASK-013 `_scrub` nit.

## Commands and counts

- Windows: ruff, format and mypy (38 files) clean; the unit part passes.
- WSL, `CI=true pytest --cov=bitscan_manager/services --cov-fail-under=85`: 430 passed, 0 skipped. Each maintain pg case uses its own container, migrated through the CLI.
- Mutations of maintain.py in the WSL copy: 7, each red (the pre-check removal is caught by the month assertion).

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-028 (1) creates exactly the missing months (clock +2) | CHK-M1-170 | PASS |
| (2) second run changes nothing | CHK-M1-171 | PASS |
| (3) owner and default ACL; app 42501 on new partitions | CHK-M1-172, CHK-M1-177 | PASS |
| (4) drops only at ≥ 400 days (#44); rows kept elsewhere | CHK-M1-173 | PASS |
| (5) no DELETE, only partition DDL | CHK-M1-174 | PASS |
| (6) refuses over default-partition rows, naming it | CHK-M1-175 | PASS |
| (7) CLI exit codes, variable named, no canary | CHK-M1-176, CHK-M1-179 | PASS |
| (8) psycopg.sql only | CHK-M1-178 | PASS |
| TASK-013 nit: malformed DSN straight to the runner | CHK-M1-055-r2 | PASS |

## Revision 1 and Revision 2 (amendments to #44: clock guard, naive clock, run lock; guard (c))

Verdict: **PASS** (both revisions). Date 2026-10-20. Impl report: `work/reports/TASK-019-impl.md`, "Revision 1" and "Revision 2".

Tests added or changed in `manager/tests/test_db_maintain.py`:

- Revision 1:
  - clock far ahead: drops refused, the clock named, the window created;
  - a future `job_created_at` refuses drops; a row exactly at now does not;
  - a correct clock keeps the 400-day drop;
  - CLI: exit 1 when drops are refused (pg), and the exit-code mapping with a stubbed plan (Windows);
  - a naive `now` is refused;
  - two concurrent runs, plus a deterministic lock-wait test (holds `hashtext('db_maintain')`, sees the wait in pg_locks, then a fresh plan).
- Revision 2 (guard c):
  - the second-run scenario, which found the gap;
  - the contiguous control;
  - 1-hole and 2-hole gaps, with the window still created;
  - CLI exit 1 naming the month;
  - pure `missing_months` and the 12-then-"and K more" message.
- From the decision text: the earlier drop tests now fill every month between their old partition and the window, so they keep testing their own rule and not guard (c).

Finding during revision 1 (CHK-M1-186, probe in the WSL copy only): with the clock +24 months, run 1 refused the drops but created the skewed window. Run 2 passed guards (a) and (b) and dropped 10 in-retention partitions, the current month included. Reported to main; the user approved guard (c) (the second amendment to #44), built as revision 2. The probe is not in the tree; CHK-M1-187 replaces it.

Commands and counts:

- Windows: ruff, format and mypy --strict are clean. pytest: 366 passed, pg skipped, coverage 100 %.
- WSL, clean run: 547 passed, 0 skipped, coverage 100 %, 0 leftover containers.
- Mutations (WSL copy), each red:
  - guard (a) removed: 1;
  - guard (b) removed: 2;
  - run lock removed: 2;
  - CLI exit 0 on refusal: 2;
  - guard (c) removed: 5.

| Amendment item | Check | Result |
| --- | --- | --- |
| (a) no partition contains now: drops refused, window created, exit 1, clock named | CHK-M1-180, CHK-M1-183 | PASS |
| (b) newest job_created_at later than now: drops refused | CHK-M1-181, CHK-M1-183 | PASS |
| normal 400-day drop unaffected | CHK-M1-182, CHK-M1-188 | PASS |
| naive now refused | CHK-M1-184 | PASS |
| run lock: an overlapping run waits, then plans afresh | CHK-M1-185 | PASS |
| second-run gap (finding) | CHK-M1-186 | FAIL in rev 1, fixed by rev 2 |
| (c) gap: drops refused, months named, window created, exit 1 | CHK-M1-187, CHK-M1-189, CHK-M1-190, CHK-M1-191 | PASS |

Accepted residual risk (decisions.md, second amendment): a forward skew smaller than the window plus one month gives a contiguous skewed window. It passes all three guards, so data can be dropped up to about 5 months early. Only the M2 clock-skew alert can catch it.
