# TASK-255 TEST: PASS

Tester: tester-m11b, 2026-11-08. Low risk, one approval; this change strengthens a gate (G5). REQ-292; `.claude/rules/testing.md` ("at least 85 % line coverage on `manager/services`"); TS §8.3. Code under test: `manager/pyproject.toml` `[tool.coverage.report]`, where `precision` goes from 2 to 4 and `fail_under = 85` is unchanged. impl-manager-b, `work/reports/TASK-255-impl.md`.

Test file (new): `manager/tests/test_coverage_floor.py`, 2 functions, 5 items.

Each case is a **real coverage run**: the real pytest, pytest-cov 7.1.0 and coverage.py 7.16.2 from the hashed venv, in a subprocess, with `--cov-fail-under=85` as `manager.yml` passes it and `--cov-config` pointing at the committed `manager/pyproject.toml`. The run is over a generated package whose covered share is exact. A module has `covered` of `total` statements run by its one test (the two `def` lines plus a called function, against an uncalled one). The verdict is the subprocess exit code.

## Runs (W, `/root/m11t`, `CI=true`)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 0 tests/test_coverage_floor.py` | 5/5 passed, 0 failed, 0 errors, 0 skipped |
| 2 | same, after reordering the assertions so the exit code is checked first (plant finding, below) | 5/5 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-255 (a) | `test_coverage_floor.py::test_committed_floor_is_85_at_four_digits` | PASS | `fail_under` = 85 (not lowered), `precision` = 4, `branch` = false (lines) |
| TASK-255 (b): 84.99 % exits non-zero | `::test_real_coverage_run_against_the_floor[84.9955]`, `[84.99]` | PASS | 5,693 / 6,698 (the M9 plant, which prints as "85.00 %" at two digits) exits non-zero with "Coverage failure: total of 84.9955 is less than fail-under=85.0000". 8,499 / 10,000 also exits non-zero (84.9900). |
| TASK-255 (c): exactly 85.00 % passes | `::test_real_coverage_run_against_the_floor[85.00]`, `[85.0149]` | PASS | 5,695 / 6,700 = 85.0000 % exits 0, with no "Coverage failure" line. 5,696 / 6,700 = 85.0149 % exits 0. |

## Plants (throwaway copies; log `/root/m11t/logs/plants-255.jsonl`)

3 plants, 3 red.

| Plant | Fault | Red tests |
| --- | --- | --- |
| P255-precision-2 | `precision = 2`, the old value | All 5. The `[84.9955]` run **exits 0** (`assert (0 == 0) is False`): the original defect, caught on the exit code. |
| P255-precision-3 | `precision = 3` | the config row, and all 4 runs on the printed form |
| P255-floor-lowered | `fail_under = 84.99` | the config row. The runs stay green, because the CLI's `--cov-fail-under=85` overrides the config, as in CI. |

Plant finding: in the first round the precision-2 plant was red only because of the printed form ("85.00%" against "84.9955%"). The test now checks the exit code before the text, and the plant is red for the right reason.

## Acceptance (lead's brief: "in a real coverage run, a total of 84.99 % must exit non-zero, and exactly 85.00 % must pass")

Rows (b) and (c), with the precision-2 plant showing the old configuration let 84.9955 % through.

## Notes

- The runs use a generated package, not `bm/services/`. A full-suite G5 run sized to 84.99 % would take the whole manager suite twice. The gate under test is the same: the same pytest-cov `--cov-fail-under` path, the same config file, and coverage.py's `should_fail_under`. The real G5 figure on the services tree is CHK-M11-311, at the wave end (reported to four digits).
- The impl report says nothing parses the coverage output. That matches what I saw: no test or harness file reads the TOTAL line.
