# TASK-255 IMPL: coverage floor precision

Implementer: impl-manager-b, 2026-11-08. This is the tooling follow-up from `work/status.md` 2026-10-30 (tester-m9b, M9 gate plant p1, `tests/m9/report.md` L1155–L1159). The rule it restores: `.claude/rules/testing.md` asks for "at least 85 % line coverage on `manager/services`" (TS §8.3). It continues the M3 G5 fix (`work/reports/M3-gate-g5-fix-impl.md`, which set precision 2). **No gate lowered:** `fail_under = 85` is unchanged.

## File (+4 / −1)

`manager/pyproject.toml`, `[tool.coverage.report]` only:
- `precision` goes from 2 to 4;
- a three-line comment explains why.

## Cause

pytest-cov 7.1.0 (pinned in `requirements-dev.txt`) decides the gate in `pytest_runtestloop` with coverage.py 7.16.2's `should_fail_under(total, fail_under, precision)`, which is `round(total, precision) < fail_under`.
- `total` is the unrounded `pc_covered`.
- `manager.yml` L140 passes `--cov-fail-under=85` but no `--cov-precision`, so the precision comes from `[tool.coverage.report] precision`. That's why no workflow change is needed.
- The M9 plant was 5,693 / 6,698 = 84.99552 %. `round(84.99552, 2)` is 85.0, which is not below 85, so the run exits 0.
- pytest-cov's separate "FAIL Required test coverage … Total coverage: 85.00%" line is only printed. It uses an unrounded `<` and a fixed `.2f`, and doesn't set the exit code.

## Why 4 digits are exact, not merely finer

- Lines only (`branch = false`), so `total = 100·c/N` for N statements.
- Under 85 %, `85N − 100c` is a positive multiple of 5, so the total is at least `5/N` below 85.
- Rounding to p digits lifts a total to 85 only if it is within `0.5·10^−p` of it.
- So precision p is exact whenever `N < 10^(p+1)`. With 4 digits, that means any services tree under 100,000 statements; M9 measured about 6,700.

I didn't use a raw comparison because there is no option for one: both coverage.py and pytest-cov always round. Rounding also keeps a true 85.00 % passing even when float division gives 84.99999999999999.

## Visible effect

- The coverage report, and pytest-cov's "Coverage failure: total of … is less than fail-under=85.0000" line, now show 4 decimals.
- pytest-cov's "Total coverage: xx.xx%" summary stays at 2 decimals (hard-coded `.2f` in pytest-cov).
- Nothing in `.github/`, `deploy/tests/`, `e2e/` or `manager/tests/` parses the coverage output (grep for `precision`, `TOTAL … %`, `--cov-report` and coverage json or xml: no hits).

## Checks run (Windows, venv of the main checkout)

- `tomllib` parse of `manager/pyproject.toml`: `{'fail_under': 85, 'precision': 4, 'show_missing': True}`.
- `ruff check manager && ruff format --check manager`: clean.
- I modelled coverage.py's own `should_fail_under` from the installed 7.16.2 ("fails" means the gate goes red):

  | Total | Precision 2 | Precision 3 | Precision 4 |
  | --- | --- | --- | --- |
  | 5,693 / 6,698 (the M9 plant) | passes | fails | fails |
  | 84,999 / 100,000 | passes | fails | fails |
  | 85.0 and 17 / 20 | passes | passes | passes |
  | 84,999 / 99,999 (the bound) | passes | passes | fails |

## For the tester (plant asked for by the lead)

The real G5 run in WSL (`pytest --cov=bitscan_manager/services --cov-fail-under=85` from `manager/`, as `manager.yml` L140):
- with an untested-statement plant sized so the total is 84.99 % (for example the M9 p1 sizing, 5,693 / 6,698), it must exit non-zero, with "Coverage failure: total of 84.9955 …";
- with a plant sized to exactly 85.00 % (c / N = 17 / 20 at N a multiple of 20), it must exit 0.

No workflow file changed, and no file outside `manager/pyproject.toml`.
