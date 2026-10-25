# M3 gate G5 fix: coverage precision (impl)

## Change

`manager/pyproject.toml`, `[tool.coverage.report]`: added `precision = 2` (one line). Nothing else changed.

## Reason

Finding from tester-h, checked by the lead. With no `precision`, coverage.py rounds the total to 0 digits before it compares it with `fail_under = 85`, so a total from 84.5 % to 84.99 % passed (a plant at 84.80 % passed). `.claude/rules/testing.md` says "at least 85 %". Lead ruling (2026-10-24): set `precision = 2`. This brings the gate back in line with the rule and lowers nothing.

## CI workflow (`.github/workflows/manager.yml` L124)

CI runs `pytest --cov=bitscan_manager/services --cov-fail-under=85` with `working-directory: manager`, so coverage reads `manager/pyproject.toml`. `--cov-fail-under` replaces only the threshold. In pytest-cov 7.1.0 (the venv's version), `plugin.py` L272-273 sets `cov_precision` from the coverage config's `precision` whenever `--cov-precision` is not given. L373 then calls `should_fail_under(total, fail_under, cov_precision)`. CI does not pass `--cov-precision`, so the pyproject `precision = 2` applies there too. **No workflow change is needed.**

## Files

- `manager/pyproject.toml` (only file changed)

## Checks run (Windows, `manager/.venv`)

- `ruff check manager`: All checks passed
- `ruff format --check manager`: 215 files already formatted
- No tests run. tester-h re-runs the G5 clean run and both plants on Linux.
