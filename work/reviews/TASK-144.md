# TASK-144 REVIEW: content validators

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/services/importer/validate.py` (278 lines, 255 non-blank), per `work/reports/TASK-144-impl.md`. One file.

TEST: PASS (`work/reports/TASK-144-test.md`, 687/687 on WSL, on the merged head `25d41ec`).
- Dependents green.
- 24 plants red (including CHK-M7-326 and -348), control green.

My re-run (Windows venv): `test_bit_validate.py` plus `test_bit102_lexer.py` gave 860/860. `ruff check`, `ruff format --check` and `mypy --strict --config-file manager/pyproject.toml` are clean on `services/importer` (15 files).

Spec read: SR §2.1–§2.4, §3.3, §3.5, §4 (L250), §4.1; TS §4.1; #2, #13, #16, #17, #105 (e), (g), #109, #110 (all approved with the M7 breakdown, decisions 2026-10-27); the BIT016 ruling (decisions L317).

## Checks
1. **Limits (SR §2, REQ-152).** Each text value is trimmed with `trim_xml` (#17: space, tab, CR and LF only) and then checked against `model.LENGTH_LIMITS`. Lengths count code points, as `VARCHAR(n)` does.
   - `Execute` gives BIT008, and whitespace only counts as empty.
   - Every other length gives BIT017.
   - The limits match SR L99–L122 and the DDL columns: `policy_name` and `family_name` 128, `plugin_name` 255.
2. **Enums.** `PolicyStatus` and `Operator` are matched ASCII-only and case-insensitively, then stored lowercase (BIT003, BIT010). The `isascii` guard stops Unicode case folding from matching.
3. **PluginId.** The #109 form gives BIT004. BIT005 fires on each later use, at its line. `RuleKeys.plugin_ids` holds only valid ids, first use only, which is what TASK-151 `check_ownership` expects.
4. **`@timeout` (#105 (e)).** ASCII digits only and not trimmed. Leading zeros are allowed, and the value is cut to 3 digits before `int()`, so a long attribute can't reach the int-string limit. The range is 1–600 and the default is 60. Anything else is BIT017 at `…/Execute/@timeout`.
5. **#2.** A missing `Operator` is BIT010 and a missing `ExpectedResult` is BIT011, each at the `Plugin` line with the child path. A missing or invalid operator skips the BIT012–BIT014 checks, so no spurious BIT014 appears.
6. **BIT012–BIT014 (SR §2.4).** BIT014 fires in both directions. BIT012 uses `values.is_number` (#13). BIT013 uses `values.is_valid_pattern`, which is RE2 with the evaluator's `(?m)` form, as the M8 interface requires. An over-long `ExpectedResult` is never compiled. There is no `re` or `xml.*` import (security invariants: RE2, defusedxml).
7. **Warnings (REQ-154, #110).** BIT101 and BIT103 come from `values.control_ref` on the trimmed name and are Warn severity. A file with only warnings still gets a `Candidate`.
8. **Order and shape (SR L250, REQ-155).** Every failing rule is reported. Findings are sorted by line with a stable sort, so rule order holds within a line. Messages are fixed text, and file values appear only through `model.quote` (at most 64 characters, controls escaped, #105 (g)). There is no I/O and no logging, so nothing reaches logs.
9. **Candidate.** It is built only when no Reject finding remains. Every path that returns None for a plugin value adds a Reject finding first, so a `Candidate` never misses a plugin. `execute_sha256` is the SHA-256 of the trimmed UTF-8 `Execute`, as SR §3.3 says.

## Findings
None blocking or should-fix.

1. nit, `validate.py:154` and `:161-162`: the `Execute` length test runs twice. Compute it once into a local and reuse it.
2. nit, `validate.py:74`: the `low == high` branch of the message can't happen, because no limit in `LENGTH_LIMITS` has equal bounds. Drop it.
3. nit, `validate.py:263`: the BIT014 message for a presence operator reads "ExpectedResult must be empty with empty and with no other operator", which is unclear. Suggested: "ExpectedResult must be empty with {operator}."
4. nit, scope: 255 non-blank lines against the 190 estimate, all in one file. The impl report says ruff format's wrapping accounts for most of the overrun. No acceptance is recorded in `work/decisions.md`; the lead may want to note it, as for TASK-148, 150 and 151.
5. Carried to TASK-154 (not a finding here): `Candidate.format_version` is always `1.0`, so it depends on the pipeline rejecting the file on BIT016, as `work/plans/TASK-154.md` §4 and the impl report say. I'll check this in the TASK-154 review.
