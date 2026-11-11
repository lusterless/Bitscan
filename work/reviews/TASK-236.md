# TASK-236 REVIEW: retention rules (pure)

Reviewer: reviewer-m11, 2026-11-08. Round 1.

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/services/retention/__init__.py`, `manager/bitscan_manager/services/retention/rules.py` (both new, about 120 lines), against TS §5.3 L1049, L1053, REQ-274, REQ-276 (prefix rule), REQ-278 (clock and future-row decisions), #150 (a)–(e), (g), (j), plan `work/plans/TASK-242.md` §2. Reports: `work/reports/TASK-236-impl.md`, `work/reports/TASK-236-test.md` (PASS, 49/49, 20/20 plants red).

## Checks

- Spec conformance: ages 400 / 180 / 90 / 90 / 30 days and 3 calendar years match TS §5.3 L1049 and the approved #150 answers; strict `<` boundary (row at the cutoff kept) matches REQ-274 (1); Feb 29 → Feb 28 matches REQ-274 (3); naive instants raise `ValueError` with fixed text (REQ-274 (4)); `audit_prefix` returns only a stored id, stops at the first non-expired entry and at the shipped cursor, and returns None before the first ship (#150 (d), REQ-276 (2), (5)); `clock_doubt` is `> 5 min` either way and `future_rows` is `> now + 1 day` (#150 (j)). Constants and signatures match plan §2.
- Security invariants: no I/O, no logging, no SQL, no `re`; nothing touches inventory data. Not applicable otherwise.
- Scope: two files, both listed for the task; no frozen file, migration or dependency touched. The three extra `ValueError` guards (`limit < 1`, ids out of order, negative years) fail closed and are tested.
- Tests: re-run on Windows with the main venv: `pytest tests/test_retention_rules.py` 49 passed; `ruff check`, `ruff format --check` and `mypy --strict` on the package and the test file clean. The tests compare against independent literals (dates, ids), not against the module's own constants alone, and the plants (399 days, `>=` boundaries, no `abs`, uncapped cursor, 365-day years, local-zone years, `limit` ignored) all went red; the two first-round survivors were closed by strengthening the tests.

## Findings

1. nit, `rules.py:96`: the ascending-id guard checks only the rows walked before the break, so an out-of-order tail after a stop is not reported. Harmless (the walk already stopped, and TASK-238 reads `ORDER BY audit_id`); no change needed.
