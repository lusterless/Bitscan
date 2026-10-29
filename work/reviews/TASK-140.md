# TASK-140 REVIEW: importer model

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-152, REQ-155. High risk (importer; TS §8.2 two approvals: this is the first, the user's is batched per wave).

Scope reviewed: new `manager/bitscan_manager/services/importer/__init__.py` (29 lines) and `model.py` (215 lines, about 150 hand-written), per `work/reports/TASK-140-impl.md`. 2 files, within the row. TEST: PASS (`work/reports/TASK-140-test.md`, CHK-M7-010 to -014; plants 385a, 385b and 386 red).

Spec read: SR §2.1–§2.4, §3.3, §3.5, §4, §4.1; TS §5.2 `plugin_operator` and `policy_status` enums (`m0001_catalog.py` L24–L31); #2, #17, #57, #105 (g).

## Checks
1. **Code table (SR §4.1).** 18 codes, BIT001–BIT005, BIT007, BIT008, BIT010–BIT017, BIT101–BIT103. BIT006, BIT009, BIT018–BIT020 absent. Severity is per rule: only BIT101 and BIT103 warn; BIT102 rejects (SR §4: number range does not imply severity). `severity` is derived from the table, so a finding cannot carry a severity its rule does not have.
2. **Limits (SR §2).** Every length matches SR §2.1–§2.3 (`PolicyName` 1–128, descriptions 0–4,000, `FamilyName` 1–128, `PluginName` 1–255, `Execute` 1–16,384, `ExpectedResult` 0–4,000). Also plugins 1–5,000; timeout 1–600, default 60; `control_ref` 32 (SR §3.3); `formatVersion` `1.0` only, default `1.0`; 5 MiB (#57). The 14 operators are in the DDL enum order.
3. **Finding shape (SR §3.5, REQ-155).** `to_json()` gives exactly `{line, element, code, message}`, with `code` as a plain string. `Code()` coercion in `__post_init__` refuses retired and unknown codes.
4. **Message quoting (#105 (g), REQ-155 (3)).** `quote()` keeps at most 64 source characters. It escapes backslash, `\n`, `\t`, `\r`, other C0 and DEL. This also keeps U+0000 out of the `errors` JSONB (builder checklist 1). Lone surrogates cannot arrive if TASK-141 decodes strictly (its plan does).
5. **Parsed forms.** `Node` holds name, line, ordered attributes, own text and children, as TASK-141 §2 asks. Processing instructions go in `ParseResult.pi_lines` (TASK-141 plan), not in `Node`, so nothing is missing. `ParsedPlugin.operator` and `expected_result` are optional, for #2 (BIT010/BIT011 with the content rules). `RawValue` keeps untrimmed text for TASK-144's #17 trimming.
6. **Purity and security.** No `re`, `xml`, `os`, `logging`, database or clock import; the test checks the imports by AST. Every type is `frozen=True, slots=True`; the mappings are `MappingProxyType`.
7. **Tests.** The oracle reads the SR §4.1 table and the TS §5.2 DDL text itself, so the expected values are not copied from the code. Plants on a code, a severity and a limit turned it red. Re-run by me on Windows: `tests/test_bit_model.py` passes (98 with the lock tests); ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` are clean (248 files).

## Findings
None blocking or should-fix.

1. nit, `manager/tests/test_bit_model.py:325`: `test_node_children_and_attributes_are_tuples` checks the annotation's string form only. `test_model_types_are_frozen_dataclasses` already covers the real property; drop the weaker test or leave it.
2. nit, `model.py:130` (`quote`): C1 controls (U+0080–U+009F) and bidi overrides (U+202A–U+202E, U+2066–U+2069) pass through unescaped. #105 (g) asks only for C0, DEL and backslash, and the UI renders text plainly (TS §6.3), so this is not a defect. Raise it with `main` only if the owner wants message text safe for terminal viewing (the CLI, TASK-166, prints counts, not messages, per #107 (b)).
