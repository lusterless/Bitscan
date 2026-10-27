# TASK-142 TEST: PASS

Tester: tester-m7b, 2026-10-27. REQ-152, REQ-153, REQ-154. Spec: SR §2.3 (`PluginId`, `ExpectedResult`), §2.4 (numbers; regex "multiline"; case-sensitive), §3.3 (`control_ref`, 32); TS §4.5 (RE2); security invariants (RE2 for untrusted patterns); answers #13, #17, #109. Checks CHK-M7-040 to -045, plant CHK-M7-325 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_values.py`. Implementation: `manager/bitscan_manager/services/importer/values.py` (impl report `work/reports/TASK-142-impl.md`).

Contract tested as written (impl report, consistent with #17 and SR §2.4): the checks take already-trimmed text, and the importer calls them on `trim_xml(value)`. So `is_number(" 14")` is False and `is_number(trim_xml(" 14 "))` is True.

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | L | `pytest -q tests/test_bit_values.py` | 144/144 passed, 0 failed, 0 errors, 0 skipped |
| clean | W | `CI=true pytest -q tests/test_bit_values.py` | 144/144 passed, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L and W are as in `work/reports/TASK-141-test.md`. W is WSL2 Ubuntu 24.04.5 with CPython 3.12.3, venv `/root/venv-m7b` from the hashed dev lock (google-re2 1.1.20251105).

## Acceptance criteria (tasks.md TASK-142)

| Criterion | Check | Result |
| --- | --- | --- |
| #13 accept and reject lists | CHK-M7-040 | PASS: 10 accepted (incl. `007`, `-0`, a 51-digit decimal); 45 refused (`1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `+`, `--1`, `+-1`, Arabic-Indic, fullwidth, superscript, inner space, `1,5`, padded forms, U+00A0, …); `parse_number` gives the exact `Decimal` (2^53 + 1 > 2^53, 0.1 == 0.10, 1e-22 > 0). Property: 2,000 strings agree with an independent RE2 oracle of the #13 grammar |
| `(?=x)` and `(a)\1` refused while `^MaxAuthTries\s+[1-4]$` compiles | CHK-M7-041 | PASS: 9 RE2 patterns compile (incl. `(a+)+$`, POSIX class, named group, UTF-8). 15 refused: lookahead, negative lookahead, lookbehind, negative lookbehind, backreference, `[`, `(`, `)`, `a{2,1}`, `*`, `\8`, `(?P=n)`, `a++`, `\Z(`, a lone surrogate. Each raises `PatternError("not a valid RE2 pattern")` with no cause or context chained. Guard: Python `re` does accept `(?=x)`, `(a)\1` and `(?<!a)b`, so the CHK-M7-325 plant is detectable |
| The evaluator's form | CHK-M7-041 | PASS: compiled patterns are multiline (`^`/`$` per line, SR §2.4), `.` does not match a newline, case-sensitive, UTF-8 |
| A 4,000-character pattern within 1 s | CHK-M7-041 | PASS: 4 distinct 4,000-char patterns (no LRU hit), and the nested-repeat and 1,000-deep-group cases, each < 1 s |
| Nothing on stderr | CHK-M7-041 | PASS: `capfd` (fd level) and `caplog` empty across all refused patterns. A fresh subprocess (RE2's first compile) writes 0 bytes to fd 2 and fd 1. Guard: stock `re2.compile('(?=x)')` does write to fd 2 in a fresh process |
| #109 forms | CHK-M7-042 | PASS: the SR §1.1 id, nil, all-f, version/variant 0 and f accepted. Refused: uppercase, mixed case, braces, `urn:uuid:`, 32-hex, 35/37 chars, misplaced hyphens, non-hex `g`, Arabic-Indic and fullwidth digits, underscores, padded, all hyphens, empty. Property: 2,000 inputs (uuids, upper-cased uuids, near-miss text) agree with an RE2 oracle |
| Trimming removes only space, tab, CR, LF (U+00A0 stays) | CHK-M7-043 | PASS: U+00A0, U+2003, U+FEFF, VT, FF, NEL and U+2028 all kept; inner whitespace kept |
| `control_ref` for every REQ-154 (1) case | CHK-M7-044 | PASS: `1.3.1.1 - Ensure…` → `1.3.1.1`; `Ensure` → BIT101; `1.3.` → `1.3`; `1..2` → `1`; `1.3.1.1Ensure` → `1.3.1.1`; leading `.`, `-`, Arabic-Indic, fullwidth and superscript → BIT101; 32 characters kept, 33 → BIT103 (dotted and plain forms); a warning never carries a value; frozen. Property: 3,000 names agree with an RE2 oracle of `[0-9]+(\.[0-9]+)*` |
| No `import re`; the module M8 imports | CHK-M7-045 | PASS: AST imports include `re2`; none of `re`, `regex`, `logging`, `os`, `io`, `subprocess`, `socket`, `pathlib`, `time`, `datetime`, `sys`, `xml`, `lxml`. The 8 helpers are exported |

## Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy (no change): `pytest tests/test_bit_values.py` green. The control's ruff run showed 7 findings in another builder's in-progress file at copy time; `ruff check manager` on the tree is clean now.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-325 | BIT013 helper compiles with Python `re` (`noqa: TID251`) | `test_non_re2_patterns_refused` ((?=x), (?!x), (?<=a)b, (a)\1, …) |
| extra | `log_errors = True` | both stderr tests |
| extra | `(?m)` dropped | `test_compiled_pattern_is_multiline` |
| extra | RE2 error chained (no `from None`) | `test_non_re2_patterns_refused` (cause/context check) |
| extra | `str.strip()` (all Unicode space) | U+00A0 / U+2003 / U+FEFF trim rows, padded-number test |
| extra | `isdigit` without `isascii` | Arabic-Indic / fullwidth number rows |
| extra | `float()` grammar | `1e3`, `nan`, `inf`, `1_000`, … rows |
| extra | trailing `.` accepted | `5.`, `0.` rows, number oracle |
| extra | uppercase hex accepted | uppercase / mixed-case rows, UUID oracle |
| extra | hyphen anywhere | misplaced-hyphen rows |
| extra | `control_ref` cap `>=` 32 | 32 kept / 33 BIT103 test |
| extra | Unicode `isdigit` in `control_ref` | Arabic-Indic / fullwidth / superscript rows, oracle |
| extra | trailing `.` kept in the reference | `1.3.`, `1..2` rows, 32/33 test |

All 13 plants are red; none survived.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-040 | CODE | L, W | `pytest -q tests/test_bit_values.py -k number` | PASS | 10 accept / 45 reject rows; exact Decimal; 2,000-case oracle | 2026-10-27 |
| CHK-M7-041 | CODE | L, W | `pytest -q tests/test_bit_values.py -k "pattern or re2 or stderr"` | PASS | 9 compile / 15 refused; multiline; < 1 s; fd 2 empty (in process and fresh process); guards prove `re` and stock RE2 differ | 2026-10-27 |
| CHK-M7-042 | CODE | L, W | `pytest -q tests/test_bit_values.py -k uuid` | PASS | 5 accept / 17 reject; 2,000-case oracle | 2026-10-27 |
| CHK-M7-043 | CODE | L, W | `pytest -q tests/test_bit_values.py -k trim` | PASS | 11 rows; only space, tab, CR, LF removed | 2026-10-27 |
| CHK-M7-044 | CODE | L, W | `pytest -q tests/test_bit_values.py -k control_ref` | PASS | 15 rows + 32/33 + oracle 3,000 | 2026-10-27 |
| CHK-M7-045 | CODE | L | `pytest -q tests/test_bit_values.py -k "imports or exports"` + `ruff check manager` | PASS | no `re`; re2 used; helpers exported | 2026-10-27 |
| CHK-M7-325 | CODE | L | plant: Python `re` in `compile_pattern` | PASS (red) | lookaround/backreference rows failed | 2026-10-27 |
