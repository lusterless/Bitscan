# TASK-144 TEST: PASS

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost with the user's machine). REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. Spec: SR §2.1–§2.4, §3.3, §3.5, §4, §4.1; answers #2, #13, #16, #17, #105 (e), (g), #109, #110. Checks CHK-M7-065 to -077 and mutation rows CHK-M7-326, -348 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_validate.py`. Implementation: `manager/bitscan_manager/services/importer/validate.py` (impl report `work/reports/TASK-144-impl.md`).

C = Linux cloud container, Ubuntu 24.04.5, 4 cores, CPython 3.12.3, venv `manager/.venv` (pytest 9.1.1, xdist 3.8.0, hypothesis 6.170.2, google-re2 1.1.20251105, defusedxml 0.7.1), `CI=true`. PostgreSQL is not needed for this task: it is unit-only, and no check here uses it. Plants in the scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/mut` (manager, bits, docs), imported first through `PYTHONPATH`, with a 2251/2251 control run; product files in the main checkout never edited.

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit_validate.py` | 687/687 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final, with the added test) | C | same | 689/689 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit_fixtures.py tests/test_bit_fuzz.py` | 231/231 passed, 0 skipped |
| importer unit neighbours | C | `pytest -q tests/test_bit_parse.py tests/test_bit_structure.py tests/test_bit_values.py tests/test_bit_model.py` | 744/744 passed, 0 skipped |
| load | C | full manager suite, `pytest -n 8` on 4 cores, 3 times (PostgreSQL tests not run: no Docker image, see TASK-145 report) | 8143/8143, 8145/8145, 8147/8147 passed, 0 failed |
| static | C | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` (repo root) | clean; 276 files formatted; mypy: no issues in 276 source files |

## Test added (tester-owned; does not weaken anything)

`test_missing_element_at_the_plugin_line_sorts_before_later_lines[Operator-BIT010, ExpectedResult-BIT011]` (REQ-155 (5)). Plant `V-unsorted` (findings not sorted by line) **survived** the 687 tests as found. Sorting only matters when a missing `Operator`/`ExpectedResult` (reported at the `<Plugin>` line, #2) follows a finding at a later line of the same plugin. No fixture or test built that case. The new test expects exactly `[(BIT010|BIT011, Plugin line), (BIT101, PluginName line), (BIT004, PluginId line)]`, and the plant is now red (2 failed).

## Acceptance criteria (tasks.md TASK-144)

| Criterion | Check | Result |
| --- | --- | --- |
| One fixture per code gets exactly that code with its line and path | CHK-M7-065 | PASS: 90 content and valid fixtures; code set, first-finding line and element path equal the manifest for BIT003, 004, 005, 008, 010–014, 016, 017, 101, 102, 103 |
| SR §1.1 example: no finding, and a `Candidate` equal to the expected normalised values | CHK-M7-066 | PASS: name and line 3, description, `enabled`, family, `1.0`, uuid, line 13, plugin name, `control_ref` `1.3.1.1`, Execute exactly the SR text and its SHA-256, `equals`, `install ok installed`, 30 s; `RuleKeys` with `RuleId(uuid, 13, 1)` |
| REQ-152 (1) bound table | CHK-M7-067 | PASS: each length at its limit accepted and +1 refused (BIT017 with its path; BIT008 for `Execute` at 16,384/16,385), counted in characters with `é` (bytes ≠ characters); trimmed first (#17), U+00A0 not trimmed; whitespace-only names and `Execute` count as empty; descriptions may be empty |
| Enums | CHK-M7-068 | PASS: `ENABLED`, `Disabled` and ` disabled\n` stored lowercase; `on`, empty, fullwidth, `enabled ` (inner), `disabled;` → BIT003 at line 5; `EQUALS` → `equals`; `equal`, `==`, fullwidth → BIT010 at line 17; all 14 operators accepted |
| BIT004 / BIT005 | CHK-M7-069 | PASS: uppercase, braces, `urn:uuid:`, 32-hex, short, empty → BIT004 at line 13 with no `RuleId`; padded id trimmed; a third use of an id gives BIT005 on the 2nd and 3rd uses at their `PluginId` lines; `RuleKeys` holds the first use only |
| Timeout table (REQ-152 (5)) | CHK-M7-070 | PASS: `1`, `600`, `0600`, `00001`, 4,001-digit zero-padded `7` accepted; absent → 60; `0`, `601`, `30s`, `1.5`, `-1`, `+5`, ` 30`, `30 `, empty, Arabic-Indic, fullwidth, `0x1e`, `1e2`, `6000`, `00`, 5,000 nines, `1_0` → BIT017 at `Execute/@timeout` |
| 5,000 plugins pass, 5,001 BIT017 | CHK-M7-071 | PASS: 5,000 → candidate with 5,000 plugins and ids; 5,001 → BIT017 at `Policy/PluginsGroups` (pipeline stops it in the parser; `validate`'s own rule on a built `ParsedPolicy`) |
| Missing `Operator` / `ExpectedResult` (#2) | CHK-M7-072 | PASS: BIT010 for `Plugin[2]/Operator` at the plugin line plus the file's BIT003; BIT011 at line 10; a missing `Operator` gives no BIT014 |
| BIT012 / BIT013 / BIT014 | CHK-M7-073 | PASS: 11 non-numbers × 6 numeric operators → BIT012; 6 numbers pass; 6 non-RE2 patterns × `regex` and `not_regex` → BIT013 (RE2 helper, never `re`); a valid RE2 pattern passes; BIT014 in both directions (9 rows) |
| A file with three faults gets all three in line order and no `Candidate` | CHK-M7-074 | PASS: `three-faults.bit` → BIT003, BIT004, BIT012 at 6, 14, 25; every fixture sorted by line; same-line rule order kept; new missing-element ordering test |
| Warnings have Warn severity and never reject | CHK-M7-075 | PASS: warnings-only file has a candidate, BIT101 and BIT103 both `Severity.WARN`, `rejects` false; listed next to an error |
| Messages (#105 (g)) | CHK-M7-076 | PASS: ≤ 64 characters of value, a 16,384-char value never whole, control characters escaped; exactly the four JSON keys for every fixture |
| No retired code | CHK-M7-077 | PASS: across every fixture |
| `RuleKeys` always built; `Candidate` only without Reject | CHK-M7-066, -074 | PASS: rule keys built on a rejected file, `policy_name` None when it fails BIT017; `Validated` frozen; input not mutated |
| No `import re` | CHK-M7-348 | PASS: AST test and ruff TID251 |

CHK-M7-334 (BIT001/BIT002 failure still runs the content rules) is shared with TASK-143: `validate()` only accepts a `ParsedPolicy`, so TASK-144 has no code path to plant. The stop is in `structure.check` (TASK-143, its plant red there) and in `import_one` (TASK-154). **NOT RUN here** for that reason.

## Plants (scratch copy; each anchor asserted to occur once, file restored after)

Tests run per plant: `tests/test_bit_validate.py tests/test_bit_fixtures.py` (916 tests), `-n 4`.

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-326 | BIT013 only for `regex` (skipped for `not_regex`) | red, 8 failed |
| CHK-M7-348 (G1) | `import re` in `validate.py` | red: `ruff check` TID251 "`re` is banned" (still red with `# noqa: F401`) |
| CHK-M7-348 (AST) | same, ruff silenced with `# noqa: F401, TID251` | red, 1 failed (`test_validate_module_imports_no_re`) |
| V-len-off1 | length limit +1 | red, 14 |
| V-len-bytes | length counted in UTF-8 bytes | red, 12 |
| V-notrim | values not trimmed before the length check | red, 20 |
| V-bit003-case | `PolicyStatus` case-sensitive | red, 5 |
| V-bit003-off | BIT003 removed | red, 19 |
| V-bit004-off | UUID form not checked | red, 32 |
| V-bit005-off | duplicate ids allowed | red, 2 |
| V-bit008-empty | empty `Execute` allowed | red, 5 |
| V-bit008-max | `Execute` limit 16,385 | red, 2 |
| V-timeout-max | timeout up to 6,000 | red, 2 |
| V-timeout-min0 | timeout 0 allowed | red, 7 |
| V-timeout-trim | `@timeout` trimmed | red, 3 |
| V-timeout-default | absent timeout → 30 | red, 1 |
| V-bit010-case | `Operator` case-sensitive | red, 4 |
| V-bit010-missing | missing `Operator` not reported | red, 5 |
| V-bit011-missing | missing `ExpectedResult` not reported | red, 3 |
| V-bit012-off | BIT012 removed | red, 74 |
| V-bit013-off | BIT013 removed | red, 16 |
| V-bit014-oneway | BIT014 only for empty/not_empty with a value | red, 6 |
| V-5001 | plugin cap 5,001 | red, 1 |
| V-unsorted | findings not sorted by line | red, 2 (survived before the added test) |
| V-first-only | only the first finding kept | red, 12 |
| V-bit101-off | BIT101 never raised | red, 12 |
| V-bit103-off | BIT103 never raised | red, 4 |
| V-candidate-on-reject | `Candidate` built despite a Reject | red, 15 |
| V-exec-untrimmed | `Execute` stored and hashed untrimmed | red, 6 |
| V-msg-unquoted | values put in messages raw (no `quote`) | red, 2 |
| V-rulekeys-dup | duplicate id kept in `RuleKeys` | red, 1 |
| V-rulekeys-name | invalid `PolicyName` kept in `RuleKeys` | red, 1 |

**32/32 red** (one after the added test).

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-065 | CODE | C | `pytest -q tests/test_bit_validate.py -k "fixture_codes or every_content_code"` | PASS | 90 fixtures match the manifest | 2026-10-27 |
| CHK-M7-066 | CODE | C | `pytest -q tests/test_bit_validate.py -k "sr_example or format_version or nbsp"` | PASS | no finding; candidate fields and `RuleId` exact | 2026-10-27 |
| CHK-M7-067 | CODE | C | `pytest -q tests/test_bit_validate.py -k "length or trimmed or whitespace or execute_bound"` | PASS | 6 bounds at/over in characters; BIT008 at 16,385 | 2026-10-27 |
| CHK-M7-068 | CODE | C | `pytest -q tests/test_bit_validate.py -k "policy_status or operator"` | PASS | lowercase storage; BIT003 line 5, BIT010 line 17 | 2026-10-27 |
| CHK-M7-069 | CODE | C | `pytest -q tests/test_bit_validate.py -k "plugin_id or duplicate"` | PASS | 7 BIT004 forms; BIT005 on each later use | 2026-10-27 |
| CHK-M7-070 | CODE | C | `pytest -q tests/test_bit_validate.py -k timeout` | PASS | 7 accepted, 18 refused, absent 60 | 2026-10-27 |
| CHK-M7-071 | CODE | C | `pytest -q tests/test_bit_validate.py -k "5000 or 5001"` | PASS | 5,000 pass; 5,001 BIT017 | 2026-10-27 |
| CHK-M7-072 | CODE | C | `pytest -q tests/test_bit_validate.py -k missing` | PASS | BIT010/BIT011 at the plugin line | 2026-10-27 |
| CHK-M7-073 | CODE | C | `pytest -q tests/test_bit_validate.py -k "numeric or regex or re2 or bit014"` | PASS | 66 + 36 + 12 + 2 + 9 rows | 2026-10-27 |
| CHK-M7-074 | CODE | C | `pytest -q tests/test_bit_validate.py -k "faults or sorted or rule_order or plugin_line"` | PASS | 3 faults in line order; new ordering test | 2026-10-27 |
| CHK-M7-075 | CODE | C | `pytest -q tests/test_bit_validate.py -k "warning or control_ref"` | PASS | Warn severity, never rejects | 2026-10-27 |
| CHK-M7-076 | CODE | C | `pytest -q tests/test_bit_validate.py -k "messages or control_characters or long_execute or four_keys"` | PASS | ≤ 64 chars, escaped, four keys | 2026-10-27 |
| CHK-M7-077 | CODE | C | `pytest -q tests/test_bit_validate.py -k retired` | PASS | no retired code in any fixture | 2026-10-27 |
| CHK-M7-334 | CODE | — | — | NOT RUN | no TASK-144 code path: `validate()` takes only a `ParsedPolicy`; the stop is planted at TASK-143 (red) and at TASK-154 | 2026-10-27 |
| CHK-M7-326 | CODE | C | plant: BIT013 skipped for `not_regex` | PASS (red) | 8 failed | 2026-10-27 |
| CHK-M7-348 | CODE | C | plant: `import re` in `validate.py`; `ruff check` | PASS (red) | TID251; AST test 1 failed with ruff silenced | 2026-10-27 |
| CHK-M7-144-extra | CODE | C | 30 further plants (table above) | PASS (red) | 30/30 red | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 689/689 passed, 0 failed, 0 errors, 0 skipped. Plants: 32/32 red.
