# TASK-142 IMPL: value helpers shared with M8

Implementer: impl-manager-m7c. REQ-152, REQ-153, REQ-154. Risk high (importer; two approvals). Spec: SR §2.3 (`PluginId`, `ExpectedResult`), §2.4 (operators, "multiline", "Numbers are …"), §3.3 (`control_ref`, 32); TS §4.5 (RE2, linear time); open questions #13 (number grammar), #17 (XML-whitespace trimming), #109 (UUID form), all approved 2026-10-27 as recommended.

## Files

| File | Non-blank lines | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/values.py` (new) | 107 (68 without docstrings and comments) | Below. |

No other file changed. It imports `CONTROL_REF_MAX` and `Code` from `model.py` (TASK-140) and `re2` (google-re2). No `re`, no I/O, no logging, no clock.

## Interface (TASK-144 and M8's `evaluate()` import these; M8 must not copy them)

**Trimming contract.** Every check takes the value **already trimmed** and never trims it itself. That way each caller keeps its own rule: the importer uses `trim_xml` (#17), and the evaluator uses its CRLF and whitespace normalisation (SR §2.4). So `is_number(" 1")` is `False` by design. The importer calls `is_number(trim_xml(v))`.

- `XML_WHITESPACE = " \t\r\n"`; `trim_xml(text) -> str` strips only those four characters from both ends. U+00A0 and other Unicode spaces stay (#17).
- `is_number(text) -> bool` checks the #13 grammar `[+-]?[0-9]+(\.[0-9]+)?` with ASCII digits only. It is hand-written, with no regex: an optional sign, then `isascii() and isdigit()` on the whole part and on the fraction after one point.
  - Rejected: an exponent, `nan`, `inf`, `_`, `0x…`, `.5`, `5.`, a lone sign, `+-1`, `1.2.3`, the empty string, and non-ASCII digits such as U+0661.
- `parse_number(text) -> Decimal | None` returns `Decimal(text)` for a #13 number and None otherwise. Building a Decimal from a string is exact at any length, and Decimal comparisons are exact, which is the "compared as exact decimals" part of #13 for M8.
- `compile_pattern(pattern) -> Pattern` compiles `"(?m)" + pattern` with google-re2 and `Options.log_errors = False`, then returns it. On failure it raises `PatternError`.
  - Why `(?m)`: SR §2.4 says `regex` is "multiline; use ^/$ to anchor", and RE2's default syntax makes `^`/`$` match only at the ends of the text. So the BIT013 check compiles exactly what the evaluator will search with.
  - The other options are RE2 defaults: UTF-8, case-sensitive, `.` does not match newline, leftmost-first, `max_mem` 8 MiB.
  - `PatternError(ValueError)` has the fixed message "not a valid RE2 pattern" and is raised `from None`, so RE2's error text is never carried or chained (REQ-153).
  - A lone surrogate (`UnicodeEncodeError`) is also a `PatternError`.
  - `Pattern` is a `Protocol` with `search(text) -> object | None`, which is what M8 needs; google-re2 has no type stubs.
- `is_valid_pattern(pattern) -> bool` is the BIT013 test: `compile_pattern` accepts the pattern.
- `is_plugin_uuid(text) -> bool` checks the #109 form: exactly 36 characters, `-` at indexes 8, 13, 18 and 23, and lowercase `0-9a-f` everywhere else. Version and variant bits are not checked.
- `ControlRef(value: str | None, warning: Code | None)` is a frozen, slotted dataclass. `value` is None whenever `warning` is set.
- `control_ref(plugin_name) -> ControlRef` takes the leading ASCII `[0-9]+(\.[0-9]+)*` of the trimmed name. It is greedy, and a point not followed by a digit ends the reference: `1.3.` gives `1.3` and `1..2` gives `1`.
  - No reference (including a leading `.` or Arabic-Indic digits): `(None, BIT101)`.
  - A reference over 32 characters: `(None, BIT103)`. One of exactly 32 is kept.

## Acceptance points (checked by a throwaway script on Windows, not a test file)

1. #13 accept: `0`, `-1`, `+2.5`, `14`, `007`, `-0.0`. Reject: `abc`, `1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `+`, ``, `1.2.3`, `+-1`, ` 1`, `١`.
2. `^MaxAuthTries\s+[1-4]$` compiles and matches the line `MaxAuthTries 3` inside `"a\nMaxAuthTries 3\n"` (multiline). `(?=x)`, `(a)\1`, `[` and `"\ud800"` are refused.
3. #109: the lowercase hyphenated form is accepted. Uppercase, braced, `urn:uuid:`, unhyphenated and a non-hex `g` are refused.
4. `control_ref`: `1.3.1.1 - Ensure` gives `1.3.1.1`; `Ensure` gives BIT101; a 32-digit reference is kept; a 33-digit one gives BIT103; Arabic-Indic digits give BIT101.
5. `trim_xml(" \t\r\n x  \n")` is `"x "`.
6. A 3,990-character pattern (`(a|b)*c` × 570) is checked in about 2 ms.
7. stderr was **0 bytes** for the whole run, refused patterns included (`log_errors = False`).

## Static gates (Windows, `manager/.venv`)

- `ruff check` and `ruff format --check` on this file: pass. On all of `manager/`, the only findings are in `manager/tests/test_bit_parse.py` (tester-owned, in progress): S105 and E501, and one file that needs reformatting. None is in product code.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI command): Success, no issues in 255 source files.

## For the tester (tester-m7b, TP-M7-04, `manager/tests/test_bit_values.py`)

- Pure unit. No PostgreSQL and no fixtures needed.
- Test the trimming contract as stated above: the checks take trimmed text. If you read #13 as "the helper trims", tell me and I'll ask main. I did not guess.
- For "nothing on stderr", run a refused pattern in a subprocess, or with `capfd`. RE2's logging is C++ writing to fd 2, so `capsys` won't see it.
- For the RE2-versus-`re` point, `(?=x)` and `(a)\1` compile under Python `re` but not here. A planted `import re` under `services/importer/` is caught by ruff TID251 (the banned-api rule).
- google-re2's `compile` has an LRU cache of 128 entries per (pattern, options). Repeated timings of the same pattern measure a cache hit, so time distinct patterns.
