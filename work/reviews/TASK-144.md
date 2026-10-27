# TASK-144 REVIEW: content validators

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. High risk (importer; two approvals, PD-35).

Scope reviewed: frozen worktree at `e2d569c`. Per `work/reports/TASK-144-impl.md` that is one file, `manager/bitscan_manager/services/importer/validate.py` (new, 278 lines, 255 non-blank).

TEST: PASS (`work/reports/TASK-144-test.md`; 689/689, 32/32 plants red, including CHK-M7-326 and CHK-M7-348).

Re-run by me (Linux container; I confirmed the worktree copy is the one imported):
- `test_bit_validate.py`, `test_bit102_lexer.py`, `test_bit102.py` and `test_bit_fixtures.py`: 2268 passed.
- `ruff check manager`: clean. `ruff format --check manager`: 276 files formatted. `mypy --strict` on `services/importer`: clean.

Spec read: SR §2.1–§2.4, §4, §4.1. Answers applied: #2, #13, #16, #17, #105 (e), (g), #109, #110.

## Checks
1. **Per code (SR §4.1).**
   - Lengths: every `LENGTH_LIMITS` value gives BIT017. Values are trimmed with `trim_xml` first (#17) and counted in code points.
   - BIT008: `Execute` 1–16,384 characters after trimming.
   - BIT003: `PolicyStatus` ASCII and case-insensitive, stored lowercase.
   - BIT004 and BIT005: the #109 form; BIT005 goes on each later use, at its own line.
   - `@timeout` (#105 (e)): untrimmed ASCII digits, 1–600, default 60. The value is bounded before `int()`.
   - BIT010 and BIT011 are raised for a missing element at the `Plugin` line (#2).
   - BIT014 comes before BIT012 and BIT013, as SR §2.3 orders them. BIT013 goes through the TASK-142 RE2 helper.
   - BIT101 and BIT103 are Warn and never reject (#110).
   - More than 5,000 plugins is BIT017 at `Policy/PluginsGroups`.
2. **Whole file (REQ-155).**
   - Every finding is collected; they are sorted by line with a stable sort, so rule order holds within a line.
   - `RuleKeys` is always built. `Candidate` is None whenever any finding rejects.
   - A plugin left out of the candidate always comes with a Reject finding, so no plugin is dropped silently.
   - Messages are fixed text; the value goes through `quote()` (#105 (g)).
3. **Invariants.**
   - No `re` import, and no regex outside the RE2 helper.
   - No I/O, and nothing in it runs code.
   - BIT007 and BIT015 get only their inputs here; they run in the store, as planned.

## Tester's question
- Line-sort test (`test_missing_element_at_the_plugin_line_sorts_before_later_lines`): confirmed. This is the one case where sorting matters: a missing `Operator`/`ExpectedResult` reported at the `<Plugin>` line after a later-line finding. The test kills `V-unsorted`.

## Findings
None blocking or should-fix.

1. nit, `validate.py:154` and `validate.py:161-163`: the `Execute` bound is tested twice. Keeping the result of the first test in a local would remove the repetition.
2. Scope note for main, not a finding: 255 non-blank lines against the row's 190, and over the ~200 limit. It is one file, and much of the length is ruff wrapping the message calls. Unlike TASK-145, 146, 151, 153 and 161, `work/decisions.md` has no acceptance row for this size. Please record one.
