# TASK-177 REVIEW: the 14 operators

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-188 to REQ-191. High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-177-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/operators.py` (131 lines).

TEST: PASS (`work/reports/TASK-177-test.md`, tester-m8). 397/397 and 14/14 plants red.

Spec read: TS §4.5 L593, L595, L600; SR §2.4 L128–L143, L153; #11, #13, #112 (a).

My re-run on Windows:
- `pytest tests/test_evaluator_operators.py`: 397 passed.
- `mypy --strict` on the module and its test: clean.
- `ruff check manager` passes for every TASK-177 file. Its 4 E501 errors are all in the tester's in-progress `tests/evaluator_pg_fixtures.py` (TP-M8-01), not this task's; carried to the gate.

## Checks
1. **Exactly 14 operators (SR L128–L143).** `COMPARISONS` is a read-only mapping with exactly the 14 keys, in importer order. The lookup is exact and case-sensitive, and anything else is `CannotEvaluate` (CHK-M8-020: 18 near-miss names).
2. **Text.** `==`, `!=`, `in` and `not in` on normalised text, with no folding.
3. **RE2.**
   - Patterns compile only through `values.compile_pattern`, which adds `(?m)` and silences the RE2 log; the module imports no `re` or `re2`.
   - Matching is a search, not a full match.
   - `PatternError` and the stdout `UnicodeEncodeError` both become `CannotEvaluate`, raised `from None`.
   - `not_regex` negates `_matches`, so a signal passes through it, and `not_regex` can't PASS on an uncheckable pattern or text.
   - My own probes found no other exception: `\C` on multi-byte text, `\x{D800}`, `\x{10FFFF}`, NUL, a 70,000-character stdout, and `a{1001}` and nested repetition (both refused, giving `cannot evaluate`).
4. **Numeric (SR L153, #13).**
   - Both values go through `values.parse_number`, and the expected value is checked first (`cannot evaluate` before `stdout not numeric`, CHK-M8-043).
   - The comparison is `Decimal`, which is exact. There's no `int()` or `float()` (AST row CHK-M8-044).
   - `ne` never PASSes on non-numeric stdout (CHK-M8-329 red).
5. **Presence.** Compares stdout with `""` and never reads `expected`.
6. **Totality and output.** The only raises are the two signals, both with no arguments and no text. The canary property (CHK-M8-051) shows no input reaches a signal's `str`, `repr` or `args`.
7. **Plants.** Every plant aimed at this task went red: CHK-M8-320 to -323, -326 to -329, -338 (operators half), plus the order-swap and `empty`-reads-expected extras.

## Findings
None blocking or should-fix.

1. nit (no change asked): `contains` and `not_contains` with an empty expected value give PASS and FAIL. That follows the SR L132 definition ("includes ExpectedResult"), and BIT014 refuses an empty expected value for these operators at import, so it can only be reached through a hand-written `eval_spec`. I'm only noting it so the TASK-180 review can confirm `parse_eval_spec` was meant to accept an empty `expected` (#117 gives no minimum).
