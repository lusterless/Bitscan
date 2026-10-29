# TASK-144 IMPL: content validators

Owner: impl-manager-m7b. REQ-152, REQ-153, REQ-154, REQ-155, REQ-180; #2, #13, #16, #17, #105, #109, #110. Spec: SR §2.1–§2.4, §3.3, §4, §4.1. Risk: high (importer; two approvals). Built against TASK-140 (model), TASK-142 (`values.py`, as written in the tree) and TASK-151 (`store.py` types).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/validate.py` | new | 255 |

No other file was changed. The row estimated 180 lines; much of the extra comes from ruff format wrapping the message strings.

## Interface

`validate(parsed: ParsedPolicy) -> Validated(findings, rules, candidate)`:
- `findings`: every file-local content finding, warnings included (#110). They are ordered by line, then by rule order within a line (REQ-155 (5)).
- `rules`: `RuleKeys(policy_name, policy_name_line, plugin_ids)`, always built, because the structure has passed. `policy_name` is the trimmed name, or None if it failed BIT017. `plugin_ids` holds `RuleId(plugin_uuid, line of <PluginId>, index)` for each id that passed BIT004, first use only (the "valid, distinct" ids).
- `candidate`: the store's `Candidate` and `CandidatePlugin`s, or None when any finding here rejects. The pipeline also sets it to None for BIT016 and BIT102 (TASK-154 plan §4).

## Rules

All text is trimmed with `values.trim_xml` (#17: space, tab, CR and LF only; U+00A0 stays). Lengths are counted in code points.

| Value | Rule |
| --- | --- |
| `PolicyName` | 1–128 |
| `PolicyDescription` | 0–4,000 |
| `FamilyName` | 1–128 |
| `PluginName` | 1–255 |
| `PluginDescription` | 0–4,000 |
| `ExpectedResult` | 0–4,000 |
| Any of the above out of range | BIT017 |
| `Execute` | 1–16,384, otherwise BIT008; whitespace only counts as empty |
| `PolicyStatus` | ASCII, case-insensitive `enabled`/`disabled`, stored lowercase; anything else BIT003 |
| `PluginId` | `values.is_plugin_uuid` (#109), otherwise BIT004; a repeated id is BIT005 on the second use, at its line |
| `Execute/@timeout` | #105 (e): ASCII digits only, not trimmed (so `" 30"` is BIT017), leading zeros allowed, 1–600, absent means 60; anything else BIT017. The value is bounded before `int()`, so a 5,000-digit attribute cannot reach Python's int-string limit |
| `Operator` | missing is BIT010 (#2); not one of the 14 (ASCII, case-insensitive) is BIT010; stored lowercase |
| `ExpectedResult` | missing is BIT011 (#2) |
| `ExpectedResult` against a valid `Operator` | empty exactly with `empty`/`not_empty`, otherwise BIT014; numeric operators need `values.is_number` (#13), otherwise BIT012; `regex`/`not_regex` need `values.is_valid_pattern` (RE2 through the TASK-142 helper, never `re`), otherwise BIT013 |
| More than 5,000 plugins | BIT017 at `Policy/PluginsGroups`, line of plugin 5,001 |
| Control reference | from `values.control_ref` on the trimmed `PluginName`: BIT101 (Warn) when none, BIT103 (Warn) when over 32 characters |

Notes on the rules:
- A missing `Operator` or `ExpectedResult` is reported at the `Plugin` line, with path `Plugin[n]/Operator` or `Plugin[n]/ExpectedResult`.
- An over-long `ExpectedResult` (BIT017) is not parsed or compiled further. That bounds the RE2 work; the file is rejected anyway.
- The control-reference warning is computed even when the name fails its length check, so a whitespace-only `PluginName` gets BIT017 and BIT101. Fixture `bit017-pluginname-whitespace` expects both.
- Every message is fixed text per rule, quoting at most 64 characters of the value through `model.quote` (#105 (g)).
- `format_version` in the candidate is always `1.0`. BIT016 (from the structure check) rejects any other value, and it does not stop these rules (SR L250).

**BIT007 has no file-local part here.** It needs the server folder and the database, so the store's `decide` raises it (TASK-151). Its file input is `RuleKeys.policy_name` with its line, built here. BIT015 works the same way, through `RuleKeys.plugin_ids`.

## Checks run here (scratch harness outside the tree; the tests are tester-m7b's)

- **Fixtures.** Every `bits/tests/manifest.json` fixture without a placeholder (174) was run through `parse_bit` → `structure.check` → `validate`. The code sets, first-finding lines and element paths all match the manifest. The only exceptions are the 8 fixtures for BIT102, BIT007 and BIT015, which belong to TASK-146 and the store.
- **SR §1.1 example.** No finding, and the expected candidate: `control_ref` `1.3.1.1`, `timeout_s` 30, `execute` exactly the SR text, and its SHA-256.
- **REQ-152:**
  - Bounds at the limit and one over, with `é`, so bytes and characters differ.
  - Whitespace-only names and `Execute`.
  - `ENABLED`/`Disabled` stored lowercase; `on` gives BIT003; `EQUALS` is stored as `equals`; `equal` gives BIT010.
  - Timeouts `0`, `601`, `30s`, `1.5`, `-1`, `+5`, `" 30"` and an empty value give BIT017; `1`, `600` and `0600` pass; absent gives 60.
  - 5,000 plugins pass and 5,001 get BIT017.
  - A duplicate id gives BIT005 at the second line and is excluded from `plugin_ids`.
  - Three faults are all reported, in line order.
- **REQ-153:**
  - `eq` passes with `0`, `-1` and `+2.5`; `abc`, `1e3` and `.5` give BIT012.
  - `(?=x)`, `(a)\1` and `[` give BIT013, while `^MaxAuthTries\s+[1-4]$` passes.
  - `empty` with `x`, and `equals` with an empty value, give BIT014.
  - A 4,000-character pattern takes 1 ms.
- **REQ-154.** BIT101, BIT103 at 33 characters, and 32 characters kept.
- **Gates.** `ruff check manager`, `ruff format --check manager` (274 files) and `mypy --strict --config-file manager/pyproject.toml manager` (274 files) are clean. There is no `re` or `xml.*` import.

## For the tester (TP-M7-06, `test_bit_validate.py`)

This is a pure unit module, so it can be built from `ParsedPolicy` objects directly or through `parse_bit` and `structure.check`. G1 plants: `import re` in this module is CHK-M7-348, and skipping the `not_regex` BIT013 check is CHK-M7-326.
