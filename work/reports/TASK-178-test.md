# TASK-178 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-186, REQ-192, REQ-193, REQ-205 (1); REQ-187 (3), (5) and REQ-190 (4) end to end; TS §4.5 L589–L600; SR §1.1 L87, §2.4; #112 (vocabulary, order, totality), #113, #114. Code under test: `bm/services/evaluator/evaluate.py` (impl-manager-m8, `work/reports/TASK-178-impl.md`). New test files: `manager/tests/test_evaluate.py`, `manager/tests/test_evaluator_property.py` (TASK-178 part), `manager/tests/test_security_m8.py` (static part: CHK-M8-220, -221, -223, -224). Plan rows: CHK-M8-060 to -077, -130 to -132, -136, -220 to -224.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluate.py tests/test_evaluator_property.py` | **489/489 passed**, 0 failed, 0 errors, 0 skipped |
| r2 | `pytest tests/test_evaluator_operators.py tests/test_evaluate.py tests/test_evaluator_property.py tests/test_security_m8.py` | **934/934 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 15 plants in `/root/bstest-m8-mut-<id>`, each running `test_evaluate.py`, `test_evaluator_property.py`, `test_security_m8.py` (537 tests) | 15/15 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the three test files | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-060 | CODE | W | r1 | PASS | REQ-186 (2): `evaluate` and `classify` take exactly `operator, expected, stdout, exit_code, timed_out, truncated`, all positional-or-keyword, with no defaults | 2026-10-29 |
| CHK-M8-061, -069 | CODE | W | r1 | PASS | REQ-186 (1): on every row, `evaluate == classify.code` and the code is in {0, 1, 2} (a plain int). Each of the 14 operators PASSes and FAILs with detail None | 2026-10-29 |
| CHK-M8-062 | CODE | W | r1 | PASS | REQ-192 (1): exits 0, 1, 2, 3, 100, 124, 125 never decide (14 operators × PASS and FAIL). 126 `cannot run`; 127 `not found`; 128, 129, 137, 143, 255, 256, 2³¹−1, −1, −9, −2³¹ `killed by signal`; None `no exit code` (14 operators × 2) | 2026-10-29 |
| CHK-M8-063, -064 | CODE | W | r1 | PASS | REQ-192 (2): `timed_out` → `timed out`, and `truncated` → `stdout truncated`, for all 14 operators on PASS and FAIL input. `contains`, with the expected text inside the kept text, is ERROR when truncated | 2026-10-29 |
| CHK-M8-065 | CODE | W | r1 | PASS | REQ-192 (3): exit 1, `""`, `empty` → PASS; `not_empty` → FAIL; `not_contains`, `equals ""` → PASS | 2026-10-29 |
| CHK-M8-066 | CODE | W | r1 | PASS | REQ-192 (4): `EQUALS`, `equal`, `""`, `Equals`, ` equals`, `regexp` → ERROR `cannot evaluate` | 2026-10-29 |
| CHK-M8-067 | CODE | W | r1 | PASS | REQ-193 (1): one case gives each of the 8 evaluation details (the 3 intake details are in TASK-179) | 2026-10-29 |
| CHK-M8-068 | CODE | W | r1 | PASS | REQ-193 (2) and #112 (c), 17 rows. Timed out + 137 + truncated → `timed out`; 127 + truncated → `not found`; truncated + non-numeric → `stdout truncated`. Also: None + truncated, 126 + timed out, 128/−1 + truncated, a bad operator after each run check, bad expected and bad stdout → `cannot evaluate` | 2026-10-29 |
| CHK-M8-070, -071 | CODE | W | r1 | PASS | REQ-187 (3): `Install…` vs `install…` FAIL. (5): expected `x\r\n` vs `x` PASS. REQ-190 (4): `" 42\r\n"` `eq 42` PASS. Also `regex ^a$` vs `a\r\nb` PASS; `empty` on `"\r\n"`, `" \r\n\t"`, `" "` PASS; U+00A0 `not_empty` PASS and `empty` FAIL (REQ-191 (1), the lead's confirmation) | 2026-10-29 |
| CHK-M8-072 | CODE | W | r1 | PASS | The false-PASS hunt: `not_regex` (refused patterns, surrogates), `ne` (non-numeric stdout or expected), and upper/padded spellings of negated operators are never PASS. They are ERROR `cannot evaluate`/`stdout not numeric`. The 10 non-numeric stdouts × 6 operators give `stdout not numeric`, and so do multi-line `5\n6` and `5\r\n6` | 2026-10-29 |
| CHK-M8-073 | CODE | W | r1 | PASS | REQ-205 (1): 0, 1, 0, 1 for the four SR §1.1 rows | 2026-10-29 |
| CHK-M8-074 | CODE | W | r1 | PASS | REQ-186 (4): over 131 paths covering every operator and ERROR path, two passes give equal verdicts. No log record at DEBUG (caplog), nothing on stdout/stderr (capsys). A `sys.addaudithook` probe sees no `open`, `socket.*`, `subprocess.Popen`, `os.system`/`exec`/`posix_spawn`, `os.remove`/`rename` or `shutil.*` | 2026-10-29 |
| CHK-M8-075 | CODE | W | r1 | PASS | With the canary in operator, expected and stdout (9 ERROR paths), the detail is a `Detail` member and holds no canary and no exit code | 2026-10-29 |
| CHK-M8-076 | CODE | W | r1 | PASS | `time.time`/`monotonic`/`perf_counter`/`*_ns` patched to raise: every path still gives a verdict. The module globals are unchanged after 131 calls | 2026-10-29 |
| CHK-M8-077 | CODE | W | r1 | PASS | 1 MiB stdout (and 1 MiB expected for text operators) under each of the 14 < 2 s; 65,536 lines < 1 s | 2026-10-29 |
| CHK-M8-130 | CODE | W | r1 | PASS | REQ-186 (3): 10,000 hypothesis inputs (the 14, uppercased, odd and random operators; text with surrogates, CR, NUL, U+00A0; exit codes over [−2³¹, 2³¹−1] and None; both flags). No exception; code in {0, 1, 2}; detail None iff the code is 0 or 1; `evaluate == classify.code`; an unknown operator is always 2 | 2026-10-29 |
| CHK-M8-132 | CODE | W | r1 | PASS | 5,000 generated #13 number pairs (sign, up to 60 digits, fraction) × 6 operators agree with the `Decimal` oracle. 2,000 equal values in different spellings are `eq` and not `ne` | 2026-10-29 |
| CHK-M8-136 | CODE | W | r1 | PASS | 3,000 cases: with no flags and passing input, ERROR iff None, < 0, 126, 127 or ≥ 128; the detail is one of the four exit-code details | 2026-10-29 |
| CHK-M8-131 (classify half) | CODE | W | r1 | PASS | 3,000 cases (no CR CR LF, per the ruling): pre-normalising both strings never changes the verdict | 2026-10-29 |
| CHK-M8-220 | CODE | W | r2 | PASS | REQ-202 (1) for all 7 pure modules (`model`, `normalise`, `operators`, `evaluate`, `verdict`, `eval_spec`, `score`). The static transitive graph reaches only the evaluator modules plus `importer.model`/`values`, with no `logging`/`re`/psycopg/fastapi. In a fresh interpreter (PYTHONPATH = this copy; child `bitscan_manager.__file__` checked), the newly loaded `bitscan_manager.*` modules are the same, with no psycopg/fastapi/starlette/pydantic | 2026-10-29 |
| CHK-M8-221, -223, -224 | CODE | W | r2 | PASS | `scores`/`reevaluate` import no `api`, no `repositories.catalog*`, no `re`/`logging`. No logging call in `evaluator/` or the two repositories formats a result field. No `re`/`regex`/`sre_*` import in any M8 file. The pure modules have no `getLogger`/`print(` | 2026-10-29 |
| CHK-M8-330 | CODE | W | plant: exit 1 → FAIL | PASS (red) | 17 failed: `test_grep_exit_1_with_empty_output`, `ordinary_exit_codes[*-1]`, both properties | 2026-10-29 |
| CHK-M8-331 | CODE | W | plant: `> 128` | PASS (red) | 18 failed: `error_exit_codes[*-128-killed by signal]`, the boundary row, properties | 2026-10-29 |
| CHK-M8-332 | CODE | W | plants: no 126 branch; no 127 branch | PASS (red) | 18 / 20 failed: the 126 (127) rows across 14 operators | 2026-10-29 |
| CHK-M8-333 | CODE | W | plants: drop `< 0`; None coerced to 0 | PASS (red) | 45 / 18 failed: every negative row; every None row | 2026-10-29 |
| CHK-M8-334 | CODE | W | plant: no `timed_out` branch | PASS (red) | 20 failed: the 14-operator timed-out rows, order rows | 2026-10-29 |
| CHK-M8-335 | CODE | W | plant: `truncated` ignored | PASS (red) | 20 failed: the 14-operator truncated rows, the `contains` row, order rows | 2026-10-29 |
| CHK-M8-336 | CODE | W | plant: `truncated` checked first | PASS (red) | 7 failed: the `test_detail_order` rows (137 + timed out + truncated gives `stdout truncated`) | 2026-10-29 |
| CHK-M8-338 (classify half) | CODE | W | plant: only `NotNumeric` caught | PASS (red) | 31 failed, including G63 `test_classify_and_evaluate_are_total` (`CannotEvaluate` escapes) | 2026-10-29 |
| CHK-M8-361 | CODE | W | plant: `from bitscan_manager.repositories import catalog` in `evaluate.py` | PASS (red) | 4 failed: the static and runtime import graphs for `evaluate` and `verdict` (G65) | 2026-10-29 |
| CHK-M8-362 | CODE | W | plants: `logging…debug("stdout=%s", stdout)`; `raise ValueError("not numeric: " + stdout)` | PASS (red) | 5 failed (`test_pure_no_log_no_output_no_io` caught the record; G65 graph/logging rows) / 78 failed (totality, canary, every non-numeric row) | 2026-10-29 |
| CHK-M8-363 | CODE | W | plant: detail forced to `"stdout not numeric: " + stdout` (bypassing `Verdict`) | PASS (red) | 69 failed: `test_detail_never_quotes_input`, the non-numeric rows, totality (detail not a `Detail`) | 2026-10-29 |
| extra x-noexpnorm | CODE | W | plant: expected not normalised | PASS (red) | 7 failed: REQ-187 (5) rows and the pre-normalised property | 2026-10-29 |

## Acceptance (TASK-178 row)

- REQ-186 (1) → CHK-M8-061; (2) → -060; (4) → -074, -076.
- REQ-192 (1)–(4) → -062 to -066.
- REQ-193 (1)–(3) → -067 to -069.
- REQ-205 (1) → -073.
- The REQ-186 (3) property found no exception in 10,000 inputs → -130; the -338 plant turns it red.
- CHK-M8-364 (`Verdict` accepting 3, TASK-176) also turns CHK-M8-130 red, because a 3 can't be produced; the TASK-176 row stands.

## Notes (no defect)

- `classify` normalises inside its comparison, after the run checks. So a timed-out or truncated result is ERROR without its text being looked at. That matches D1.
