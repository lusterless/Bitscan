# TASK-142 REVIEW: value helpers shared with M8

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-152, REQ-153, REQ-154. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/services/importer/values.py` (107 non-blank lines), per `work/reports/TASK-142-impl.md`. One file.

TEST: PASS (`work/reports/TASK-142-test.md`, 144/144 on Windows and WSL).
- Property tests check against independent RE2 oracles for the number grammar, the UUID form and `control_ref`.
- These plants turned it red: CHK-M7-325 (Python `re`) and 12 extra plants, including `log_errors = True`, `(?m)` dropped, the RE2 error chained, `str.strip()`, and Unicode `isdigit`. None survived.

My re-run: included in the 677 unit tests above (`test_bit_values.py`); gates clean.

Spec read: SR §2.3, §2.4 (numbers; regex "multiline"), §3.3 (`control_ref`, 32); TS §4.5 (RE2, linear time); #13, #17, #109. Security invariant: RE2 for every regular expression touching untrusted patterns.

## Checks
1. **RE2 only (invariant, TS §4.5).**
   - `compile_pattern` uses google-re2 with `log_errors = False`, so nothing reaches fd 2, also in a fresh process.
   - Errors become `PatternError("not a valid RE2 pattern")` raised `from None`, so no RE2 text or input is carried (REQ-153). A lone surrogate is also a `PatternError`.
   - `(?=x)` and `(a)\1` are refused; Python `re` would accept them (a guard test shows this).
   - There is no `re` import.
2. **One form for import and evaluation.** It compiles `"(?m)" + pattern`, the SR §2.4 multiline reading. `(?m)` is a standalone flag group, so a pattern cannot undo the prefix's meaning except with its own flags, which then apply equally at evaluation. M8 must import this helper, not copy it (owner notes).
3. **Numbers (#13).** A hand-written `[+-]?[0-9]+(\.[0-9]+)?` with ASCII digits only. `parse_number` gives an exact `Decimal`.
4. **UUID (#109).** Exactly 8-4-4-4-12 lowercase hexadecimal; braces, `urn:`, uppercase and the unhyphenated form are refused.
5. **`control_ref` (SR §3.3).** The leading ASCII `[0-9]+(\.[0-9]+)*`. No reference gives BIT101; over 32 characters gives BIT103 with no value.
6. **Trimming (#17).** Only space, tab, CR and LF are removed. The checks take text that is already trimmed: a documented contract that the tests pin.

## Findings
None blocking or should-fix.

1. nit, for M8's review: `compile_pattern` relies on RE2's default `max_mem` (8 MiB). A very large but valid pattern could be refused as BIT013. That is the safe direction, and it is the same at evaluation.
