# TASK-111 REVIEW: CSV writer with formula escaping

Verdict: APPROVED (round 2, revision 1). Round 1 was APPROVED with one wording nit for main (Finding 1). The lead ruled for the literal TS §6.3 reading (decisions 2026-10-25), and r1 implements that ruling.

Reviewer: reviewer, 2026-10-25. One review round (package search). Not a two-approval task.

Scope reviewed: `manager/bitscan_manager/services/packages/csv_export.py` (`work/reports/TASK-111-impl.md`, including "Revision 1"). Sources: TS §6.3 L1142 and the security invariant on CSV cells, REQ-116 (1), (2) and (4), #84 (c) and (d), and the lead's r1 ruling.

TEST:
- Round 1: PASS. `test_csv_export.py` 131/131, and plants CHK-M5-331, -332 and escape-after-quoting are red.
- r1: PASS (`work/reports/TASK-111-test.md`). 142/142 with the oracle updated to the ruling. The plant of the old condition is red on `" \tabc"` (8 failed). Rows CHK-M5-080..086 (r1) and -360.

## Checks
1. Spec and #84:
   - A cell gets one `'` when its first character after the run of leading whitespace (`str.lstrip()`) is `=`, `+`, `-` or `@`.
   - r1 also prefixes a cell when that whitespace run holds a tab or a CR.
   - Tab and CR are whitespace themselves, so "starts with a tab or CR" is the same check with nothing in front. A lone `\t` and `" \tabc"` are now prefixed.
   - An empty `rest` is never a trigger.
   - The prefix comes before the RFC 4180 quoting. Header cells are escaped, and each line ends in CRLF.
2. r1 only adds escaping: every cell prefixed before is still prefixed. A tab that is not leading (`a\tb`) is unchanged, which is correct, because it cannot start a formula.
3. Security: the function is pure, uses no regular expression, and logs nothing. There is one shared function for every export.
4. Scope: 1 file, about 40 lines. r1 changes two lines and the docstring.

## Findings
1. Closed by r1 (lead ruling 2026-10-25): leading whitespace followed by a tab or CR is now prefixed, as TS §6.3 L1142 reads literally.
