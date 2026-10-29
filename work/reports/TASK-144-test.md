# TASK-144 TEST: PASS

Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. Spec: SR §2.1–§2.4 (limits, enums, operators), §3.3 (`control_ref`), §3.5 (finding shape), §4 (every failing rule, in document order), §4.1 (codes and severities); answers #2, #13, #16, #17, #105 (e), (g), #109, #110. Checks CHK-M7-065 to -077, plants CHK-M7-326 and -348 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_validate.py`; fixtures `bits/tests/content/`, `bits/tests/valid/`, `bits/tests/manifest.json`. It runs `parse_bit`, then `structure.check`, then `validate` (the SR §4 order). Implementation: `manager/bitscan_manager/services/importer/validate.py` (impl report `work/reports/TASK-144-impl.md`).

## Runs

Code under test: `git archive 25d41ec manager bits docs` (the merged head; `git status` shows no product change in the worktree) unpacked to `/root/bstest-m7b-head`. The earlier copy `/root/bstest-m7b-base` differs from it only in CR LF line endings (`diff --strip-trailing-cr` is empty for the test files and corpora).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit_validate.py` | 687/687 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `test_bit_fixtures.py`, `test_bit_model.py`, `test_bit_structure.py`, `test_bit_values.py`, `test_bit_parse.py`, `test_bit_fuzz.py`, `test_module_imports.py`, each alone | 227/227, 71/71, 253/253, 144/144, 276/276, 4/4, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W = WSL2 Ubuntu 24.04.5, kernel 6.18.54 WSL2, CPython 3.12.3, pytest 9.1.1, venv `/root/venv-m7b` (`pip install --require-hashes -r manager/requirements-dev.txt` + `--no-deps -e manager`; both lock files are unchanged by the merge), `CI=true`, no containers (pure unit). L = Windows 11, `manager/.venv`, static gates only (no Python tests on Windows). No product module imports `validate.py` yet (TASK-154 is not built), so the dependents are the unit suites that share its fixtures, model and value helpers.

## Acceptance criteria (tasks.md TASK-144)

| Criterion | Check | Result |
| --- | --- | --- |
| One fixture per code gets exactly that code with its line and path | CHK-M7-065 | PASS: all 90 valid and content fixtures through parse → structure → validate match their manifest codes, lines and elements; every content code (BIT003, 004, 005, 008, 010–014, 016, 017, 101, 103) has a fixture failing only that code |
| SR §1.1 example: no finding and a `Candidate` equal to the expected normalised values | CHK-M7-066 | PASS: no finding; name, name line 3, description, `enabled`, family `CIS Ubuntu 24.04`, format `1.0`, plugin id, trimmed `Execute` and its SHA-256, `equals`, `install ok installed`, timeout 30, `control_ref` |
| REQ-152 (1) bound table | CHK-M7-067, -071 | PASS: each length at its limit accepted, +1 character refused (BIT017; BIT008 for `Execute` at 16,384), counted in characters with multi-byte `é`; whitespace-only `PolicyName`, `FamilyName`, `PluginName`, `Execute` are empty; descriptions of length 0 pass; trimming (#17) happens before the length check and keeps U+00A0; 5,000 plugins accepted, 5,001 BIT017 |
| Enums and case | CHK-M7-068 | PASS: `ENABLED`/`Disabled` stored lowercase, 9 bad statuses BIT003; all 14 operators in any case stored lowercase; 9 bad operators (`equal`, …) BIT010 |
| `PluginId` | CHK-M7-069 | PASS: 7 #109 forms (uppercase, braces, `urn:uuid:`, 32-hex, …) BIT004; a repeated id BIT005 on each later plugin at its `PluginId` line; a padded id is trimmed |
| `@timeout` (REQ-152 (5)) | CHK-M7-070 | PASS: 7 accepted forms incl. `0600` → 600; 18 refused (`0`, `601`, `30s`, `1.5`, `-1`, `+5`, ` 30`, `30 `, empty, …) BIT017 at `…/Execute/@timeout`; absent → 60 |
| Missing `Operator` / `ExpectedResult` (#2) | CHK-M7-072 | PASS: missing `Operator` in plugin 2 gives BIT010 for `Plugin[2]` plus the file's other faults and no BIT014; missing `ExpectedResult` gives BIT011 |
| BIT012, BIT013, BIT014 | CHK-M7-073 | PASS: 66 numeric rows (#13) for each of the 6 numeric operators, 36 passing; `regex` and `not_regex` refuse `(?=x)`, `(?!x)y`, `(a)\1`, `[`, lookbehind (RE2); BIT014 both directions incl. `empty` with U+00A0 |
| A file with three faults gets all three in line order and no `Candidate` | CHK-M7-074 | PASS: `three-faults.bit` → BIT003, BIT004, BIT012 at lines 6, 14, 25, no `Candidate`; a many-fault file sorted by line; same-line findings keep rule order; every fixture's findings sorted |
| Warnings have Warn severity and never reject | CHK-M7-075 | PASS: `warnings-only.bit` gives BIT101 and BIT103 with Warn severity, `rejects` false, and a `Candidate` (`control_ref` None and a 31-character ref); a warning is listed with an error |
| Messages (#105 (g)) | CHK-M7-076 | PASS: a 5,000-character value is never quoted whole (at most 64 characters), a 16,384-character `Execute` never appears, C0 and DEL escaped; every finding serialises to exactly 4 keys |
| No retired code | CHK-M7-077 | PASS: 180 rows (90 fixtures × 2 views), no BIT006, 009, 018–020 |
| `RuleKeys` whenever the structure passed; `Candidate` only with no Reject finding (`work/plans/TASK-151.md` §2) | — | PASS: `RuleKeys` built on a rejected file; `policy_name` None when invalid, line kept; one `RuleId` per valid distinct id; `Execute` and its SHA-256 trimmed; result frozen; input not mutated |
| G1: no `import re` in `validate.py` | CHK-M7-348 | PASS: AST test plus ruff ban |

## Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first through `PYTHONPATH`, asserted; runner `%TEMP%\m7b-plants\run_plants.py`, definitions `plants_144.json`, `plants_144b.json`)

Control copy (`CTRL-144`, no-op change): ruff clean; `pytest tests/test_bit_validate.py` green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-326 | BIT013 checked for `regex` only, not `not_regex` | `test_regex_operators_need_an_re2_pattern[(?=x)-not_regex]`, `bit013-bracket`, `bit013-lookbehind` fixtures |
| CHK-M7-348 | `import re` at the top of `validate.py` | ruff rc=1 (banned import), collection error |
| CHK-M7-348b | `import re` after `import hashlib` (module still imports) | ruff rc=1; `test_validate_module_imports_no_re` |
| P144-len-off-by-one | length upper bound `high + 1` | `bit017-*-over-limit` fixtures, `test_rule_keys_policy_name_none_when_invalid` |
| P144-bytes | length counted in UTF-8 bytes | `*-at-limit` fixtures, `test_length_at_limit_…[ExpectedResult]` |
| P144-no-trim | value not trimmed before the length check | `bit014-regex-whitespace`, `bit017-*-whitespace`, `test_same_line_findings_keep_rule_order` |
| P144-unicode-trim | `str.strip()` (Unicode) instead of the #17 trim | `test_nbsp_kept_and_unicode_round_trips`, `test_trimmed_before_the_length_check`, `test_bit014_both_directions[empty-\xa0]` |
| P144-execute-limit | `Execute` bound 16,385 | `bit008-too-long`, `test_execute_bound_16384` |
| P144-status-case | `PolicyStatus` compared case-sensitively | `valid/disabled.bit`, `valid/mixed-case-values.bit`, `test_policy_status_any_case…[ENABLED]` |
| P144-bit005-off | duplicate ids allowed | `bit005-duplicate-id`, `test_duplicate_id_bit005_on_each_later_use` |
| P144-timeout-trim | `@timeout` trimmed | `bit017-timeout-space30`, `test_timeout_refused_is_bit017[ 30]`, `[30 ]` |
| P144-timeout-range | lower bound 0 | `bit017-timeout-0`, `test_timeout_refused_is_bit017[0]`, `[00]` |
| P144-timeout-default | default 30 | `test_timeout_absent_is_60` |
| P144-bit014-flip | BIT014 only for presence operators | `bit014-equals-empty`, `test_bit014_both_directions[equals-]` |
| P144-bit012-off | BIT012 for the first 3 numeric operators only | `bit012-ge`, `-le`, `-lt` fixtures |
| P144-warn-reject | `Candidate` only with no finding at all (warnings reject) | `test_warnings_only_file_has_a_candidate`, `test_control_ref_warnings` |
| P144-candidate-always | `Candidate` built even with Reject findings | `test_rule_keys_built_even_when_rejected`, `test_bad_policy_status_is_bit003` |
| P144-unsorted | findings reversed, not sorted | `test_three_faults_on_three_lines_in_order`, `test_many_faults_…`, `test_duplicate_id_…` |
| P144-sha-untrimmed | SHA-256 of the untrimmed `Execute` | `test_sr_example_has_no_finding_and_the_expected_candidate`, `test_candidate_execute_and_sha_are_trimmed` |
| P144-operator-case | operator stored as written | `test_operator_any_case_stored_lowercase`, `valid/mixed-case-values.bit` |
| P144-bit011-off | missing `ExpectedResult` reported as BIT014 | `bit011-missing`, `test_missing_expected_result_is_bit011` |
| P144-ref-warn-off | BIT103 never raised | `bit103-long-control-ref`, `valid/warnings-only.bit` |
| P144-ruleids-dup | a `RuleId` added for an invalid id | `test_bad_plugin_id_is_bit004` (7 rows) |
| P144-quote-whole | the whole value quoted with `repr` | `test_messages_quote_at_most_64_characters` |

All 24 plants are red; the control is green.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-065 | CODE | W | `pytest -q tests/test_bit_validate.py -k "fixture_codes_lines_and_paths or every_content_code_has_a_fixture"` | PASS | 91/91; 90 fixtures match manifest code, line, element | 2026-10-28 |
| CHK-M7-066 | CODE | W | `pytest -q tests/test_bit_validate.py -k sr_example` | PASS | 1/1; no finding, expected `Candidate` | 2026-10-28 |
| CHK-M7-067 | CODE | W | `pytest -q tests/test_bit_validate.py -k "length_at_limit or whitespace_only or execute_bound or trimmed_before or nbsp"` | PASS | 25/25; at limit pass, +1 refused, characters not bytes | 2026-10-28 |
| CHK-M7-068 | CODE | W | `pytest -q tests/test_bit_validate.py -k "policy_status or operator_any_case or bad_operator or all_14"` | PASS | 28/28 | 2026-10-28 |
| CHK-M7-069 | CODE | W | `pytest -q tests/test_bit_validate.py -k "bad_plugin_id or duplicate_id or padded_plugin_id"` | PASS | 9/9; BIT004 forms, BIT005 on the later plugin | 2026-10-28 |
| CHK-M7-070 | CODE | W | `pytest -q tests/test_bit_validate.py -k timeout` | PASS | 66/66; `0600` → 600, absent → 60 | 2026-10-28 |
| CHK-M7-071 | CODE | W | `pytest -q tests/test_bit_validate.py -k "5000 or 5001"` | PASS | 2/2 | 2026-10-28 |
| CHK-M7-072 | CODE | W | `pytest -q tests/test_bit_validate.py -k "missing_operator or missing_expected"` | PASS | 3/3; BIT010 / BIT011, no BIT014 | 2026-10-28 |
| CHK-M7-073 | CODE | W | `pytest -q tests/test_bit_validate.py -k "numeric_operator or regex_operators or valid_re2 or bit014"` | PASS | 142/142 | 2026-10-28 |
| CHK-M7-074 | CODE | W | `pytest -q tests/test_bit_validate.py -k "three_faults or many_faults or sorted_by_line or same_line"` | PASS | 93/93; lines 6, 14, 25 | 2026-10-28 |
| CHK-M7-075 | CODE | W | `pytest -q tests/test_bit_validate.py -k "warnings_only or warning_listed or control_ref_warnings"` | PASS | 7/7; Warn severity, `Candidate` kept | 2026-10-28 |
| CHK-M7-076 | CODE | W | `pytest -q tests/test_bit_validate.py -k "messages_quote or control_characters or long_execute or four_keys"` | PASS | 93/93 | 2026-10-28 |
| CHK-M7-077 | CODE | W | `pytest -q tests/test_bit_validate.py -k no_retired_code` | PASS | 180/180 | 2026-10-28 |
| CHK-M7-315 (TASK-144 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-326 | CODE | W | plant: BIT013 skipped for `not_regex` | PASS (red) | `not_regex` rows and 2 bit013 fixtures failed | 2026-10-28 |
| CHK-M7-348 | CODE | L, W | plant: `import re` in `validate.py` | PASS (red) | ruff rc=1; `test_validate_module_imports_no_re` failed | 2026-10-28 |
