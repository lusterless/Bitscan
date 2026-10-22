# TASK-023 TEST report: runtime dependencies for M2

Verdict: **PASS**. Tester, 2026-10-21. REQ-034. Impl report: `work/reports/TASK-023-impl.md`.

## Commands run
- L: fresh-venv `pip install --require-hashes` of both locks; planted hash and pin tampering on lock copies (6 cases); `uv pip install --python-platform {x86_64,aarch64}-manylinux_2_28 --target` for both locks; lock regeneration and `cmp`; `pytest tests/test_lock_files.py` plus planted lock lines; ruff, ruff format, mypy --strict, the full suite.
- W (`tester2_t023.sh`): a fresh copy in `/root/bitscan-tester`, fresh venvs from both locks, import check, the full suite with `CI=true`.

## Counts
- `test_lock_files.py`: 17 passed (3 new tests, 2 names added to OUT_OF_SCOPE). Planted lock lines: 9/9 red, control green.
- Suite: L 370 passed and 181 skipped (pg); W 551 passed, 0 skipped.

## Criteria
| REQ-034 | Result | Rows |
| --- | --- | --- |
| (1) hashed installs on Windows and Linux | PASS (aarch64 by proxy) | CHK-M2-001, -002, -003 |
| (2) new packages import | PASS | CHK-M2-004 |
| (3) no test or lint tool in the runtime lock | PASS | CHK-M2-005 |
| (4) locks reproduce byte for byte | PASS | CHK-M2-006 |
| (5) no OpenTelemetry SDK or exporter, no OIDC library | PASS (only `opentelemetry-api`, pre-existing) | CHK-M2-005 |

Rows are in [tests/m2/report.md](../../tests/m2/report.md).

## Notes
- The G5 coverage gate is red in the current tree (36 %). The cause is `services/audit/disk_queue.py` (TASK-033), which has no tests yet. It is not caused by this task, and G5 is re-checked in TASK-033 TEST.
- `/root/venv-m2` in WSL is now built from the new dev lock (the tester's venv; the M1 `/root/venv` is untouched).
- Test file changed by the tester: `manager/tests/test_lock_files.py`.
