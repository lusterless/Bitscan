# TASK-141 TEST: PASS (revision 1)

Tester: tester-m7b, 2026-10-27. REQ-150, REQ-176, REQ-180. Spec: TS §4.1 L516–L517, §8.1 L1251; SR §4, §4.1 BIT001; answers #57, #105 (a), (b), (c), (f), (g). Checks CHK-M7-020 to -028 and plants CHK-M7-320, -321, -322, -323, -347 (tests/m7/test-plan.md). Test files: `manager/tests/test_bit_parse.py`, `manager/tests/test_bit_fuzz.py` and the helper `manager/tests/bit_unit.py`. Implementation: `manager/bitscan_manager/services/importer/parse.py` (impl report `work/reports/TASK-141-impl.md`, including "Revision 1").

## Rounds

| Round | Verdict | What |
| --- | --- | --- |
| 1 | FAIL | `test_bit_parse.py::test_utf16_without_bom_is_bit001` (6 params). Expected exactly one BIT001 (REQ-150, D1, #105 (f): UTF-8 only). Actual: no finding and a full tree. Repro: `parse_bit(sr_example().decode().encode("utf-16-le"))`. Cause: UTF-16 bytes without a BOM are valid UTF-8 (NUL is valid UTF-8), so the strict decode passed, and expat's `initScan` detects UTF-16 from `3C 00` / `00 3C` even when given `encoding="utf-8"`. The declared-encoding pre-check never ran, because the buffer does not start with the bytes `<?xml`. 270/276 passed. |
| 2 (rev 1) | PASS | Any 0x00 byte is now BIT001 before the decode. 276/276. |

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| round 1 | L | `pytest -q tests/test_bit_parse.py` | 270/276 passed, 6 failed, 0 errors, 0 skipped |
| re-run of the failing test | L | `pytest -q "tests/test_bit_parse.py::test_utf16_without_bom_is_bit001"` | 6/6 passed |
| clean, rev 1 | L | `pytest -q tests/test_bit_parse.py` | 276/276 passed, 0 failed, 0 errors, 0 skipped |
| clean, rev 1 | W | `CI=true pytest -q tests/test_bit_parse.py` | 276/276 passed, 0 skipped |
| fuzz | W | `CI=true pytest -q tests/test_bit_fuzz.py` | 4/4 passed (10,500 generated inputs) |
| fuzz | L | `pytest -q tests/test_bit_fuzz.py` | 4/4 passed |
| dependents | W | `pytest -q tests/test_bit_fixtures.py tests/test_bit_model.py tests/test_bit_structure.py` | 227/227, 71/71, 253/253 passed |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L = Windows 11, `manager/.venv` (CPython 3.12.10). W = WSL2 Ubuntu 24.04.5, kernel 6.18 WSL2, CPython 3.12.3. Copy `/root/bstest-m7b-base` (rsync without `.venv`, `__pycache__`, `.git`), venv `/root/venv-m7b` (`pip install --require-hashes -r manager/requirements-dev.txt` + `--no-deps -e manager`), `CI=true`, no containers (pure unit).

## Acceptance criteria (tasks.md TASK-141)

| Criterion | Check | Result |
| --- | --- | --- |
| Every BIT001 fixture gives exactly one BIT001: external entity by file and URL, parameter entity, billion laughs, quadratic blow-up, DTD only, UTF-16, ISO-8859-1, invalid UTF-8, not well-formed, empty, 5 MiB + 1 | CHK-M7-020, -023, -025 | PASS: all 35 `bits/tests/bit001` fixtures; DOCTYPE fixtures at the DOCTYPE line with a DTD message; manifest lines (invalid UTF-8 line 5, mismatched tags line 4); messages hold no input text. Also UTF-16 LE/BE without a BOM (3 declarations each), NUL anywhere, 7 non-UTF-8 declarations (ASCII bodies, so only D1 catches them), XML 1.1/2.0, 4 BOMs at line 1, and 6 bad-UTF-8 forms × 4 places at line 7 |
| No file or network access | CHK-M7-021 | PASS: audit hook (`open`, `socket.*`, `urllib.*`, `subprocess.*`, `os.*` exec/spawn/listdir, `ctypes.*`) records nothing; canary content never in the result; a local listener sees no connection (xxe-file, external-dtd-file, xinclude, xxe-url, parameter-entity, external-dtd-url). Guard test: the hook does see a real `open` |
| Defence in depth (all three defusedxml layers) | CHK-M7-320, -322 | PASS: parser built with `forbid_dtd`, `forbid_entities`, `forbid_external` all True (spy). With the DTD layer neutralised, all 6 entity fixtures still get "Entity declarations ..." with no side effects and < 64 MiB. With DTD and entity layers neutralised, xxe-file and xxe-url get "External references ...", with no canary and no connection |
| Under 64 MiB peak memory | CHK-M7-022 | PASS: billion laughs, quadratic blow-up, valid 5 MiB file, 5 MiB of text in one element, 35,015-element cap case: `tracemalloc` peak < 64 MiB, < 2 s each |
| A valid 5 MiB file parses | CHK-M7-023 | PASS: exactly 5,242,880 bytes, no finding; 5,242,881 gives BIT001 with `line` null and the parser never constructed (spy); oversize garbage gets the size rule, not the encoding rule |
| SR §1.1 example tree, lines match the file | CHK-M7-024 | PASS: start-tag lines computed from the text by a separate scanner equal the tree's, in pre-order, for the SR example, all 15 `valid/` fixtures and both samples. `Execute` text is the untrimmed CDATA, `attributes == (("timeout", "30"),)`. CDATA, text and comments joined (comments dropped); predefined entities and char refs decoded; CRLF and a lone CR normalised and counted; attribute order kept; multi-line start tag at the `<` line |
| #105 (a) caps | CHK-M7-026 | PASS: depth 16 ok, 17 BIT002 at the 17th element's line; 35,014 elements ok, 35,015 BIT002 at its line; 5,000 `Plugin` (bare and canonical) ok, 5,001 BIT017 at the 5,001st; 8 attributes ok, 9 BIT002 |
| Namespaces one BIT002 (impl change 1) | CHK-M7-053 (parser half) | PASS: default, prefixed, `xmlns=""`, unbound element and attribute prefix, and the 3 fixtures each give one BIT002 at the declaring line, never BIT001 |
| PIs recorded for TASK-143 | CHK-M7-024 | PASS: `pi_lines` = (3, 5) for an inner and a trailing PI; the declaration not counted; fixtures (7,) and (3,) |
| 10,000 random inputs raise nothing | CHK-M7-027 | PASS: 4,000 random byte strings, 4,000 mutations of the SR example and both samples, 2,500 XML token soups; each returns a `ParseResult` with ≤ 1 finding of BIT001/BIT002/BIT017, `root` None iff there is a finding, a line within the input, < 2 s |
| No `xml`/`lxml` import | CHK-M7-028, -347 | PASS: AST scan of `parse.py` (also no `re`, `subprocess`, `socket`, `urllib`, `http`, `logging`, `time`, `os`, `io`, `pathlib`, … and no `open`/`eval`/`exec` calls) and of every module under `services/importer/` (no `xml`, `lxml`, `re`). No log record and no stdout/stderr for every bit001, bit002 and valid fixture |

## Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy (no change): ruff clean, `pytest tests/test_bit_parse.py -k "not utf16_without_bom"` green. Plants were run on rev 0, with the known round-1 failure excluded so that each plant's own red test is visible.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-320 | `forbid_external=False` | `test_parser_built_with_all_three_forbids`, `test_external_layer_holds_…` (2) |
| CHK-M7-321 | `forbid_dtd=False` | `test_bit001_fixture_gives_exactly_one_bit001` (dtd-only, dtd-element-decl, external-dtd-file, …), `test_dtd_refused_at_the_doctype_line` |
| CHK-M7-322 | `forbid_entities=False` | spy test, `test_entity_layer_holds_…` (6) |
| CHK-M7-323 | size cap 50 MiB | `test_one_byte_over_is_bit001_and_never_parsed`, `test_oversize_garbage_…` |
| CHK-M7-347 | `import xml.etree.ElementTree` in parse.py | ruff rc 1 (TID251); `test_parser_imports_only_safe_modules`, `test_no_importer_module_imports_xml_or_lxml` |
| extra | declared-encoding check removed | iso-8859-1-ascii, us-ascii fixtures; 7 declaration tests |
| extra | XML version check removed | xml-1.1 fixture; 2 version tests |
| extra | depth `>=` → `>` | depth-17 tests (2) |
| extra | element cap `>` → `>=` | 35,014 / 35,015 tests |
| extra | attribute cap + 1 | `test_8_attributes_accepted_9_refused` |
| extra | plugin cap + 1 | 5,001-plugin tests (2) |
| extra | collector gets a `comment` method | `test_cdata_text_and_comments_joined_in_order` |
| extra | `start_ns` no longer stops | namespace tests, xinclude canary test |
| equivalent | BOM check removed | survives: FF FE / FE FF / 00 00 FE FF are already invalid UTF-8, so the strict decode gives the same BIT001 at line 1 |
| equivalent | UTF-8 error line from `exc.end` | survives: `start` and `end` of a UTF-8 error never span a newline |
| equivalent | expat message quoted whole | survives: without a DTD, expat reports an undefined entity itself, with no name in its text. The code-11 special case is defensive only |

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-020 | CODE | L, W | `pytest -q tests/test_bit_parse.py` (bit001 params) | PASS | 35/35 fixtures, one BIT001 each; rev 0 FAIL on UTF-16 without BOM (6), fixed in rev 1, re-run 6/6 | 2026-10-27 |
| CHK-M7-021 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "never_opened or never_fetched or layer or forbids"` | PASS | audit hook empty, listener silent, canary absent; three defusedxml layers each proven alone | 2026-10-27 |
| CHK-M7-022 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "bombs or 5_mib"` | PASS | peak < 64 MiB, < 2 s | 2026-10-27 |
| CHK-M7-023 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "5_mib or one_byte_over or oversize or empty"` | PASS | 5,242,880 passes; 5,242,881 BIT001, parser not built | 2026-10-27 |
| CHK-M7-024 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "tree or lines or cdata or entities or crlf or pi"` | PASS | lines from the text = tree lines (SR example, 15 valid fixtures, 2 samples) | 2026-10-27 |
| CHK-M7-025 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "utf or declar or bom or xml_other"` | PASS | 8 accepted declarations; non-UTF-8, BOMs, invalid UTF-8 (line 7), UTF-16 no BOM → BIT001 | 2026-10-27 |
| CHK-M7-026 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "depth or elements or plugins or attributes or namespace"` | PASS | 16/17, 35,014/35,015, 5,000/5,001, 8/9 boundaries; namespaces one BIT002 | 2026-10-27 |
| CHK-M7-027 | CODE | L, W | `pytest -q tests/test_bit_fuzz.py` | PASS | 4/4 (10,500 inputs); W 7.9 s | 2026-10-27 |
| CHK-M7-028 | CODE | L | `pytest -q tests/test_bit_parse.py -k imports` + `ruff check manager` | PASS | AST scan clean; ruff clean | 2026-10-27 |
| CHK-M7-320 | CODE | L | plant `forbid_external=False` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-321 | CODE | L | plant `forbid_dtd=False` | PASS (red) | ≥ 3 failed | 2026-10-27 |
| CHK-M7-322 | CODE | L | plant `forbid_entities=False` | PASS (red) | 7 failed | 2026-10-27 |
| CHK-M7-323 | CODE | L | plant cap 50 MiB | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-347 | CODE | L | plant `import xml.etree.ElementTree` | PASS (red) | ruff rc 1; 2 failed | 2026-10-27 |

## Notes for main and the reviewer

- Impl change 3 (BIT017 at the 5,001st `Plugin` in the parser) is tested as built. Main accepted it on 2026-10-27 as an amendment to #105 (a), because TS L517 puts the 5,000-plugin limit on the parse step. A 5,001-plugin file therefore reports only BIT017.
- Impl change 4 (8-attribute cap) is in the approved #105 (a).
- The first Windows fuzz run stalled for more than 10 minutes while parse.py was being revised under it. The same suite takes 8 s on W and passes on L, and I found no product cause. I could not stop the stalled process from my session; it has since exited.
