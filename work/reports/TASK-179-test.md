# TASK-179 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-194 (1)–(6), REQ-205 (2); TS §4.5 L593, L596, L599; §3.3 L226; SR §2.4 ("Only stdout is compared"); #12, #57, #112 (c), #113, #116. Code under test: `bm/services/evaluator/verdict.py` (impl-manager-m8, `work/reports/TASK-179-impl.md`). New test file: `manager/tests/test_evaluator_verdict.py`. Plan rows: CHK-M8-100 to -109.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | **205/205 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants, each running those three files plus `test_evaluator_property.py` (210 tests) | 10/10 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-100 | CODE | W | r1 | PASS | `utf8_size` counts 1/2/3/4-byte characters. stdout 65,536 ASCII bytes passes and 65,537 is `oversize`. `"€"×21,845+"a"` (65,536 bytes) passes; `"€"×21,846` (21,846 characters, 65,538 bytes) is `oversize`. `"😀"×16,384` passes, and one more byte is `oversize` | 2026-10-29 |
| CHK-M8-101 | CODE | W | r1 | PASS | stderr 16,384 passes and 16,385 is `oversize`; `"€"×5,462` (16,386 bytes) is `oversize`, `"€"×5,461+"a"` passes. Seven flag sets (none, `truncated` false/true, `timed_out`, exit None/127/−1) never avoid the cap. The `truncated` flag alone is `stdout truncated`, not `oversize` | 2026-10-29 |
| CHK-M8-102 | CODE | W | r1 | PASS | A lone surrogate counts 3 bytes (surrogatepass) with no exception; the cap boundary holds at 65,536/65,537 and 16,384/16,385 with surrogates | 2026-10-29 |
| CHK-M8-103 | CODE | W | r1 | PASS | REQ-194 (2): oversize stdout or stderr with `error` `spool_overflow`, `runner_unavailable` or `bogus` (and with timed out) → `oversize` | 2026-10-29 |
| CHK-M8-104 | CODE | W | r1 | PASS | REQ-194 (3): `spool_overflow` / `runner_unavailable` → ERROR with that detail even for passing stdout, exit None or timed out; a spy on `verdict.classify` records 0 calls. With `error` None, exactly one call with `(operator, expected, stdout, exit_code, timed_out, truncated)` | 2026-10-29 |
| CHK-M8-105 | CODE | W | r1 | PASS | `error` `bogus`, `""`, `SPOOL_OVERFLOW`, ` spool_overflow`, `timed out` → ERROR `cannot evaluate`, `classify` not called | 2026-10-29 |
| CHK-M8-106 | CODE | W | r1 | PASS | REQ-194 (4): 16,384 bytes of `ERROR: permission denied` never change a PASS. Expected text in stderr never makes a FAIL a PASS; stderr `nullok` doesn't fail `not_contains`; stderr `0` doesn't feed `eq`; stderr doesn't make `empty` FAIL | 2026-10-29 |
| CHK-M8-107 | CODE | W | r1 | PASS | REQ-194 (5), REQ-205 (2): through `build_eval_spec` → `parse_eval_spec` → `get` of the SR §1.1 plugin: PASS, FAIL, FAIL (exit 1), PASS (trailing LF) | 2026-10-29 |
| CHK-M8-108 | CODE | W, L | r1; G3 | PASS | REQ-194 (6): real M3 `ResultItem`s (`model_validate`) give PASS, FAIL, `spool_overflow`, `oversize`, `no exit code`; mypy --strict accepts the call; `verdict.py` imports nothing from `api` or `repositories` (AST) | 2026-10-29 |
| CHK-M8-109 | CODE | W | r1 | PASS | 12 results × 5 specs (incl. a refused pattern, a bad operator): inside the caps with no error, `result_verdict == classify` | 2026-10-29 |
| canary | CODE | W | r1 | PASS | A canary in stdout, stderr and `error` (also at oversize sizes) is in no verdict | 2026-10-29 |
| CHK-M8-339 | CODE | W | plant: `len(text)` | PASS (red) | 4 failed: the byte rows (`€`, emoji, stderr `€`, surrogates) | 2026-10-29 |
| CHK-M8-340 | CODE | W | plants: stdout `>=`; stderr `>=` | PASS (red) | 4 / 2 failed: the exact-cap rows | 2026-10-29 |
| CHK-M8-341 | CODE | W | plant: oversize ⇔ `truncated` | PASS (red) | 20 failed: flags rows, oversize-before-error, `ResultItem` oversize, agreement rows | 2026-10-29 |
| CHK-M8-342 | CODE | W | plants: classify still called on `spool_overflow`; its result returned | PASS (red) | 1 failed (the spy row) / 2 failed (spy row, `ResultItem` row) | 2026-10-29 |
| CHK-M8-343 | CODE | W | plants: stdout + stderr compared; stderr instead | PASS (red) | 4 / 4 failed: stderr cap row, classify-args spy, stderr rows | 2026-10-29 |
| extra x179-order | CODE | W | plant: runner error before oversize | PASS (red) | 1 failed: oversize wins over `spool_overflow` | 2026-10-29 |
| extra x179-unknown | CODE | W | plant: an unknown `error` falls to `classify` | PASS (red) | 5 failed: the unknown-error rows give PASS | 2026-10-29 |

## Acceptance (TASK-179 row)

REQ-194 (1) → -100, -101; (2) → -103; (3) → -104; (4) → -106; (5) → -107; (6) → -108; REQ-205 (2) → -107. Every security row (S: -339, -341, -342) has a plant that went red.
