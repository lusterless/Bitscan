# TASK-033 TEST report: audit disk queue

Verdict: **PASS** (round 2). Tester, 2026-10-21. REQ-054 (1) queue part, (5) state, (6). Impl report: `work/reports/TASK-033-impl.md` (revisions 1 and 2).

## Rounds
- Round 1 (revision 1): **FAIL** on `tests/test_disk_queue.py::test_peek_zero_returns_nothing`. Expected `peek(0) == []` (docstring "at most max_records"); actual `[rec(1)]`. Cause: the size check came after the append in `peek`.
- Round 2 (revision 2, `max_records <= 0` returns `[]`): every test passes on L and W.

## Commands run
- L: `pytest tests/test_disk_queue.py` (61 tests: 51 run, 10 Linux-only skipped with "not run: Linux only"); the full suite with G5 (535 passed, 222 skipped, 97.63 %); 10 mutations plus a control; ruff, format, mypy.
- W: the same file, 61 passed, `disk_queue.py` 100 % covered; a probe of modes and fsync calls.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-054 (1) order, restart, removal once acknowledged | PASS | CHK-M2-110, -111 |
| REQ-054 (1) folder 0700, files 0600 (Linux) | PASS | CHK-M2-113 |
| REQ-054 (5), #51 (c) state survives restarts, never reset by damage | PASS | CHK-M2-114 |
| REQ-054 (6) cut-off record detected, earlier records kept, never returned | PASS | CHK-M2-112 |
| durability (fsync, short writes) | PASS | CHK-M2-115 |

Mutations: 10/10 red, control green. Rows are in [tests/m2/report.md](../../tests/m2/report.md). Test file added: `manager/tests/test_disk_queue.py`.

## Notes
- Hardening, not a criterion: a stale `.<name>.tmp` that already exists with mode 0644 keeps that mode through `os.replace`. The 0700 folder still blocks other users. Unlinking the tmp first, or using `O_EXCL` / `fchmod`, would close it.
