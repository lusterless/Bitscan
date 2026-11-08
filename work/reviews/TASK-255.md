# TASK-255 REVIEW: coverage floor precision

Reviewer: reviewer-m11, 2026-11-08. Round 1. Low risk, one approval.

Verdict: APPROVED

**Scope reviewed:** `manager/pyproject.toml`, `[tool.coverage.report]` only: `precision` 2 → 4, plus a three-line comment. Checked against REQ-292, `.claude/rules/testing.md` ("at least 85 % line coverage on `manager/services`") and TS §8.3.

**Reports:**
- `work/reports/TASK-255-impl.md`
- `work/reports/TASK-255-test.md` (PASS, 5/5 real pytest-cov runs, 3/3 plants red)

## Checks

- **No gate lowered.** `fail_under = 85` is unchanged. `manager.yml:140` still passes `--cov-fail-under=85` with no `--cov-precision`, so the config's precision applies.
- **The fix is exact, not merely finer.** With `branch = false`, the total is 100c/N. Below 85 %, 85N − 100c is a positive multiple of 5, so the total is at least 5/N under 85. Rounding to p digits can only lift it to 85 when 5/N ≤ 0.5·10^−p, that is when N ≥ 10^(p+1). At p = 4 that needs at least 100,000 statements; the services tree is about 6,700. The comment states this correctly.
- **Nothing parses the 2-decimal output.**
  - I grepped `.github/`, `deploy/tests/`, `e2e/`, `manager/tests/` and `tests/` for `TOTAL`, `coverage.json`, `coverage.xml` and `cov-report`.
  - The only hits outside the new test are the shell checkers' own `TOTAL=$((PASSN + FAILN))` counters in `deploy/tests/` and historical report text.
  - pytest-cov's "Total coverage: xx.xx%" summary stays at 2 digits; only the report table and the failure line change.
- **The tests can fail.** Each test runs real pytest, pytest-cov and coverage.py in a subprocess against the committed config, and the verdict is the exit code. The precision-2 plant lets 84.9955 % exit 0, so it is red on the exit code itself, after the tester's reorder.
- **Re-run (Windows, m9 venv):** `tests/test_coverage_floor.py` 5 passed. `ruff check` on the test file is clean.

## Findings

None.
