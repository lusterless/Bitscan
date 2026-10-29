# TASK-178 REVIEW: `classify()` and `evaluate()`

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-186, REQ-192, REQ-193, REQ-205. High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-178-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/evaluate.py` (88 lines).

TEST: PASS (`work/reports/TASK-178-test.md`, tester-m8). 489/489 (934/934 combined) and 15/15 plants red.

Spec read: TS §4.5 L587–L600; SR §1.1 L87, §2.4 L145–L153; #112 (b)–(d), #113, #114; design note D1.

My re-run on Windows:
- `pytest tests/test_evaluate.py tests/test_evaluator_property.py tests/test_security_m8.py`: 537 passed.
- `mypy --strict` on the package and the three test files: clean.
- `ruff check`: clean.

## Checks
1. **Signature (TS L600).** `evaluate(operator, expected, stdout, exit_code, timed_out, truncated)` has exactly these six positional-or-keyword parameters with no defaults, and returns `VerdictCode`. It is `classify(...).code`, so there is one comparison path (CHK-M8-060, -061).
2. **ERROR before comparison, in #112 (c) order (TS L593, #114).** `_run_error` runs these checks in order, and the first match returns:
   1. `timed_out`;
   2. `exit_code is None`;
   3. 126;
   4. 127;
   5. `>= 128` or `< 0`;
   6. `truncated`.

   Only after that are both strings normalised and compared, so a timed-out or truncated result is never compared at all. The boundary rows 125/126/127/128, −1, −2³¹, 2³¹−1 and None are pinned (CHK-M8-062, -136). CHK-M8-331 (`> 128`), -333 (negative or None) and -336 (order swap) are red.
3. **The exit code never decides otherwise (L598).** Codes 0–125 reach `compare` unchanged, and the `grep` row (exit 1, empty stdout, `empty`) is PASS. CHK-M8-330 is red.
4. **No false PASS.**
   - `not_regex` on a refused pattern or a lone surrogate is `cannot evaluate`.
   - `ne` on a non-numeric stdout is `stdout not numeric`, and on a non-numeric expected value `cannot evaluate`.
   - Unknown or upper-case operators, including negated spellings such as `NOT_CONTAINS`, are `cannot evaluate`.
   - `not_contains` and `not_equals` always have comparable text. When the run checks fail they are ERROR, because those checks come first.
   - CHK-M8-072 hunts these rows, and CHK-M8-338 (catching only one signal) turns the 10,000-input totality property red.
5. **Normalisation (L597).** Both `expected` and `stdout` go through `normalise`. The extra plant (expected not normalised) is red.
6. **Totality and purity (REQ-186 (3), (4); REQ-202).**
   - There's no broad `except`. The only exceptions caught are the two signals.
   - `Verdict` is built only with valid pairs.
   - The imports are `typing` and the evaluator modules only: no logging, clock, I/O or state. The audit-hook probe, caplog, capsys and the clock patch are all clean.
   - Details are `Detail` constants, so no input or exit code reaches one (CHK-M8-075; -362 and -363 red).
7. **SR §1.1 (REQ-205 (1)).** The four rows give 0, 1, 0, 1.

## Findings
None blocking or should-fix.
