# TASK-176 REVIEW: evaluator model and normaliser (the interface)

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-187, REQ-193, REQ-202. High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-176-impl.md`. Three new files:
- `manager/bitscan_manager/services/evaluator/__init__.py`: docstring only (5 lines).
- `manager/bitscan_manager/services/evaluator/model.py`: 115 lines.
- `manager/bitscan_manager/services/evaluator/normalise.py`: 17 lines.

TEST: PASS (`work/reports/TASK-176-test.md`, tester-m8). 102/102 and 4/4 plants red (CHK-M8-324, -325, -337, -364).

Spec read: TS §4.5 L587–L600, §5.2 L892–L938; SR §2.4 L124–L154; #112, #115, #116; decisions 2026-10-29 "Normaliser: one-pass CRLF → LF".

My re-run on Windows (M7 venv, `PYTHONPATH` set to the M8 `manager/`, imports checked to resolve to the M8 tree):
- `pytest tests/test_evaluator_model.py tests/test_evaluator_normalise.py`: 102 passed.
- `ruff check manager` passes and `ruff format --check manager` is clean (324 files).
- `mypy --strict` on the package and both test files: no issues.

## Checks
1. **Operators (SR §2.4 L128–L143).** `Operator` holds exactly the 14 operators, in `importer.model.OPERATORS` order. It can't be derived from the tuple at type level, so CHK-M8-001 keeps the two in step. Evaluation functions take `str`, so they stay total (#112 (d)).
2. **Return codes (TS §4.5 L589–L593).** `VerdictCode` is `Literal[0, 1, 2]`.
   - `Verdict.__post_init__` refuses a code outside {0, 1, 2}, including `bool`, `2.0` and `"2"`. It also refuses a detail on PASS or FAIL, and an ERROR whose detail isn't a `Detail` member.
   - That makes "anything else" unrepresentable rather than silently stored. The error messages are fixed text.
3. **`eval_detail` vocabulary (#112 (a)).** Exactly the eleven values, all fixed words, so none can carry stdout, expected values or patterns (REQ-193). `INTAKE_DETAILS` is the #12 set.
4. **Caps (#116, #57).** 65,536 and 16,384 bytes, documented as strictly-over. They're constants only; TASK-179 applies them.
5. **Normaliser (TS L597, SR L151, #115).** The function does a one-pass CRLF → LF, then strips the six ASCII whitespace characters. There's no case folding and no Unicode normalisation, and a lone CR and Unicode spaces are kept. This matches the lead's one-pass ruling. The non-idempotence on `"\r\r\n"` can't produce a false PASS: both sides go through the same function, and an interior `\r\n` left over in stdout only makes `equals` stricter.
6. **Purity (REQ-202).** `model.py` imports only `dataclasses`, `enum`, `typing` and `uuid`; `normalise.py` imports only `typing`. There's no logging, I/O or state (CHK-M8-014).
7. **`ResultLike`.** It has exactly the six read-only fields. A real mypy run shows the M3 `ResultItem` conforms, and a type without `error` is refused (CHK-M8-007).
8. **Tests.** The tests can fail: every plant went red. CRLF inputs are built in code, and the file is checked to hold no CR byte. The Unicode-space rows cover 24 code points.

## Findings
None blocking or should-fix.

1. nit (resolved): the impl report's original "idempotent by construction" claim was wrong (`"a\r\r\nb"`). The report now carries the correction, and the tests pin the one-pass rows.
2. Carried to TASK-185: `Verdict` refuses a plain `str` detail. Re-evaluation reads `scan_result.eval_detail` as text, so it has to map the stored text to a `Detail` before building a `Verdict`, and it must handle a stored text outside the vocabulary without raising. Otherwise one bad row fails the whole run. I'll check this in the TASK-185 review.
