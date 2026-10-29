# TASK-143 TEST: PASS

Tester: tester-m7b, 2026-10-27. REQ-151, REQ-176. Spec: SR §2, §2.1–§2.3 (names, order, occurrence), §4 (BIT001/BIT002 first; otherwise every failing rule), §4.1 BIT002 and BIT016; TS §1.4; answers #2, #10, #16, #105 (c), (d), (g). Checks CHK-M7-050 to -057 and plant CHK-M7-334 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_structure.py`. It runs `parse_bit` and then `check` only on a tree, the SR §4 order. Implementation: `manager/bitscan_manager/services/importer/structure.py` (impl report `work/reports/TASK-143-impl.md`).

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | L | `pytest -q tests/test_bit_structure.py` | 253/253 passed, 0 failed, 0 errors, 0 skipped |
| clean | W | `CI=true pytest -q tests/test_bit_structure.py` | 253/253 passed, 0 skipped |
| dependents | L, W | `pytest -q tests/test_bit_parse.py tests/test_bit_fixtures.py` | 276/276, 227/227 passed |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L and W are as in `work/reports/TASK-141-test.md`.

Fixture note: `bit002/miscased-policyName.bit` and `miscased-plugin.bit` had manifest lines [2], which is the header comment line. The builder flagged it; I confirmed it and reported it to tester-m7, who fixed the generator. The rows are now [3, 4] and [10, 11]. The test asserts both findings of each file (missing at the container line, then unknown at the element's line) and that the manifest now agrees.

## Acceptance criteria (tasks.md TASK-143)

| Criterion | Check | Result |
| --- | --- | --- |
| SR §1.1 tree gives a `ParsedPolicy` with the raw values and their lines | CHK-M7-050 | PASS: every field's text, start-tag line (from the text) and #105 (g) path; `@formatVersion` and `Execute/@timeout` at their element's line. Values are raw (`"  ENABLED\n"`, `" EQUALS "` untrimmed); all 15 valid and 75 content fixtures pass the structure; plugins in document order with a 1-based index; frozen |
| Each REQ-151 (2) fixture tree gets BIT002 at the right line and path, and no `ParsedPolicy` | CHK-M7-051 to -053 | PASS: all 50 `bit002/` fixtures give only BIT002, `parsed` None, the first finding on a manifest line, findings sorted by line. Built from the SR example: each of the 8 required leaves missing (one BIT002 at the parent's line, path of the missing element); `Family` and `PluginsGroups` missing; each of 10 elements duplicated (BIT002 at the second); a second `Family` (#10); each of 9 adjacent pairs swapped; 5 mis-cased names and 3 mis-cased roots (no attributes); wrong root (one finding); empty, self-closing and comment-only `PluginsGroups` (#16); unknown elements in 4 containers at their lines; 11 unknown attributes (incl. `Timeout`, `FormatVersion`, `xml:lang`); non-whitespace text in 4 containers incl. CDATA `x` and `&#160;` (#105 (d)); a child in each of 9 leaves; 4 PI places, with lines; `xml:`-prefixed element |
| Whitespace and comments between elements ignored | CHK-M7-053, -057 | PASS: CR LF, tab, comment and whitespace-only CDATA in a container give no finding |
| Namespaced documents: one BIT002, no second report (main's ask on TASK-141 change 1) | CHK-M7-053 | PASS: `xmlns` on the root, `xmlns:b` on a leaf and `xmlns=""` each give exactly one BIT002 from the parser; `check` never runs on them |
| `formatVersion` `1.1` gets BIT016 | CHK-M7-055 | PASS: `1.1`, `1.00`, empty, `2.0`, ` 1.0`, `1.0 `, `1` each give one BIT016 at line 2, `Policy/@formatVersion`, **with** a `ParsedPolicy` (SR §4: only BIT001/BIT002 stop the content rules). Absent gives `format_version` None; `1.0` passes. The 4 `content/bit016-*` fixtures match their manifest line and element |
| A missing `Operator` gives a `ParsedPolicy` with that field marked missing and no BIT002 (#2) | CHK-M7-054 | PASS: plugin 2 of 3 missing `Operator`, or `ExpectedResult`, or both; only that field is None. `bit010-missing` and `bit011-missing` give no finding. An `ExpectedResult` placed before `Operator` is still BIT002 |
| BIT002 masks BIT003, BIT016, BIT102; BIT001 stops before the structure check | CHK-M7-056 | PASS: `plus-bit003`, `plus-bit016`, `plus-bit102` give only BIT002; a BIT002 fault with `formatVersion="9"` gives only BIT002; a not-well-formed file gives only BIT001 |
| Comments never part of a value | CHK-M7-057 | PASS: comments inside `PolicyName` and between CDATA parts of `Execute` are absent from every value; `valid/comments.bit` |
| Messages (#105 (g)) | — | PASS: a 300-character unknown name is quoted cut to 64 characters, the message stays under 160, and the element is the container path. A bad attribute on plugin 3's `Execute` gives `Policy/PluginsGroups/Plugin[3]/Execute…` at that line |

## Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy: ruff clean; `pytest tests/test_bit_structure.py` green.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-334 | a BIT002 other than "missing" still returns a `ParsedPolicy` (content rules would run) | `test_bit002_fixture_…` (attr-on-leaf, child-in-leaf, …) and every `parsed is None` row for those faults |
| extra | order check removed | `order-*` fixtures, swap rows |
| extra | duplicates allowed | `duplicate-*` fixtures, duplicate rows |
| extra | `PluginDescription` optional | missing-PluginDescription fixture and row |
| extra | `Operator` no longer optional | `bit010-missing`, missing-operator-plus-faults, #2 rows |
| extra | empty `PluginsGroups` allowed | empty / self-closing fixtures and rows, miscased-plugin |
| extra | container text check uses `str.strip()` (Unicode) | the `&#160;` row |
| extra | unknown attributes on `Plugin` allowed | unknown-attr-plugin fixture and row |
| extra | children in leaves allowed | child-in-leaf fixture and 9 rows |
| extra | first PI ignored | PI fixtures and rows |
| extra | root name compared case-insensitively | survived at first: the root's `formatVersion` attribute then failed as unknown, masking it. I added `test_miscased_root_without_attributes_is_bit002` (3 params), and the plant is now red |
| extra | BIT016 on a stripped value | ` 1.0`, `1.0 ` rows |
| extra | BIT016 returns no `ParsedPolicy` | the 4 bit016 fixtures through the content-fixture test, `test_bit016_fixtures` |
| extra | unknown children of `PluginsGroups` ignored | miscased-plugin, `<Group/>` row |

All 15 plants are red (one after the added test).

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-050 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "sr_example or raw or valid_and_content or frozen or document_order"` | PASS | raw values, lines and paths; 90 fixtures pass | 2026-10-27 |
| CHK-M7-051 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "missing_required or missing_container"` | PASS | 10 rows, BIT002 at the parent's line with the path | 2026-10-27 |
| CHK-M7-052 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "duplicate or swap or second_family"` | PASS | 10 + 9 + 1 rows | 2026-10-27 |
| CHK-M7-053 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "bit002_fixture or case or root or empty_plugins or unknown or text or leaf or processing or namespace or xml_prefixed"` | PASS | all 50 bit002 fixtures; namespaces one BIT002 | 2026-10-27 |
| CHK-M7-054 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "missing_operator or missing_both or missing_fixtures or expected_before"` | PASS | field None, no BIT002 | 2026-10-27 |
| CHK-M7-055 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "format_version or bit016"` | PASS | 7 values BIT016 with ParsedPolicy; absent / 1.0 pass | 2026-10-27 |
| CHK-M7-056 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "masks or only_bit002 or bit001_stops"` | PASS | only BIT002 / only BIT001 | 2026-10-27 |
| CHK-M7-057 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k comments` | PASS | comments never in a value | 2026-10-27 |
| CHK-M7-334 | CODE | L | plant: ParsedPolicy kept with non-"missing" BIT002 | PASS (red) | bit002 fixture rows failed | 2026-10-27 |
