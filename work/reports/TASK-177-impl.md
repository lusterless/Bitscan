# TASK-177 IMPL: the 14 operators

Implementer: impl-manager-m8. REQ-188, REQ-189, REQ-190, REQ-191. Risk high. Plan: `work/plans/TASK-178.md` §3 (design note D2). Spec: TS §4.5 L593, L595, L600; SR §2.4 (SR L130–L143, L153). Answers applied: #11 (operators as written), #13 (number grammar, reused), #112 (a) (`cannot evaluate`).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/operators.py` (new, 131 lines / 95 non-blank) | `NotNumeric`, `CannotEvaluate`, `COMPARISONS`, `compare()` |

Size: 131 lines, against an estimate of 110. The extra lines are one small function per text and presence operator, written out rather than as lambdas so each one is named in tracebacks and coverage. No other file was changed.

## Interface

```python
class NotNumeric(Exception): ...        # no args, no text
class CannotEvaluate(Exception): ...    # no args, no text
COMPARISONS: Final[Mapping[str, Callable[[str, str], bool]]]   # read-only MappingProxyType, (expected, stdout) -> bool
def compare(operator: str, expected: str, stdout: str) -> bool  # inputs already normalised; raises only the two signals
```

## How each acceptance point is met

- **Dispatch:** `COMPARISONS` is a read-only `MappingProxyType` with exactly the 14 keys, in `importer.model.OPERATORS` order. Scratch check: `tuple(COMPARISONS) == OPERATORS`.
  - The keys are written out as literals, not zipped from the importer's tuples, so each operator's function can be read off its line. The tester's equality test keeps them in step.
  - `compare` looks up the operator exactly (case-sensitive) and raises `CannotEvaluate` for anything not in the table: `EQUALS`, `equal`, `""`. The importer stores the value lowercase (SR §2.3).
- **Text (REQ-188):** `==`, `!=`, `in` and `not in` on the given strings. Nothing is case-folded.
- **RE2 (REQ-189):** `_matches` calls `values.compile_pattern(expected)` at the module attribute on every call, so a spy on `values.compile_pattern` sees each one. Then it calls `.search(stdout)`.
  - `compile_pattern` adds `(?m)` and silences RE2's log. The module never imports `re2` or `re`.
  - `PatternError` becomes `CannotEvaluate`, and so does the `UnicodeEncodeError` that `search` raises for a lone surrogate in stdout. Both are raised `from None`, so no chained exception carries text.
  - `not_regex` is `not _matches(...)`, so a signal propagates and `not_regex` never passes on a pattern or text it could not check (CHK-M8-323).
  - **No `lru_cache`.** The plan allows one, but none is used, for three reasons:
    - per-call compilation keeps the "only `values.compile_pattern` compiles" spy simple;
    - there is no module state;
    - RE2 compilation of a catalog pattern is microseconds.
  - If re-evaluation (TASK-185) profiling shows otherwise, a cache can be added later.
- **Numeric (REQ-190):** `_numeric(test)` checks the parsed expected value first: if `values.parse_number(expected)` is None, it raises `CannotEvaluate`. Then a None `parse_number(stdout)` raises `NotNumeric`. Then `test(stdout_value, expected_value)` runs on two `Decimal`s, with `operator.eq/ne/gt/ge/lt/le`.
  - Decimal construction from a string, and Decimal comparison, are exact at any length. There is no `int()` or `float()`.
- **Presence (REQ-191):** `stdout == ""` / `!= ""`. `expected` is not read.
- **Totality:** the only raises are the two signals. `compile_pattern` raises only `PatternError` (it catches `UnicodeEncodeError` and `re2.error` itself). `search` raised only `UnicodeEncodeError` on the probes below. `parse_number` returns None and never raises: `is_number` runs before `Decimal()`, so `Decimal` only ever sees `[+-]?[0-9]+(\.[0-9]+)?` in ASCII.

## Scratch check (outside the tree, `/tmp/m8-176-scratch/check177.py`; not a test)

All of these hold:
- REQ-188 (2), (3): `contains` `PermitRootLogin no` in a multi-line dump is True and `permitrootlogin no` is False; `not_contains` `nullok` against `nullok_secure` is False.
- REQ-189 (1)–(5):
  - the MaxAuthTries rows and the `not_regex` PermitEmptyPasswords row hold;
  - `foo` in `xfoo` is True;
  - `^foo$` against `a\nfoo\nb` is True;
  - `^a.b$` against `a\nb` is False;
  - `(?=x)`, `(a)\1` and `[` give `CannotEvaluate` under both `regex` and `not_regex`;
  - a lone surrogate in stdout gives `CannotEvaluate` under both;
  - `(a*)*b` against 65,536 `a` characters takes about 13 ms.
- REQ-190 (1)–(3), (5):
  - every listed PASS and FAIL row holds, the 2⁵³ + 1 row included;
  - `abc`, empty, `1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `5 6`, `5\n6` and `٣` give `NotNumeric` for all six operators;
  - a 5,000-digit comparison is exact;
  - expected `abc` gives `CannotEvaluate`, even when stdout is also `abc` (the expected value is checked first).
- REQ-191 (3): `empty` with expected `junk` and stdout `""` is True.
- REQ-192 (4) (via `compare`): `EQUALS`, `equal` and `""` give `CannotEvaluate`.

REQ-190 (4) (`" 42\r\n"`) is the normaliser's job: `classify` (TASK-178) normalises before `compare`.

## Static gates (Windows, tools from `Bitscan-m7\manager\.venv`; this worktree has no venv)

- `ruff check manager`: all checks passed. The `re` ban (TID251) is unaffected: no `re` import.
- `ruff format --check manager`: 316 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 316 files.
- The same with `--platform linux`: no issues in 316 files.

## Plants for the tester (rows aimed at TASK-177)

- **CHK-M8-320:** `import re` and `re.search(expected, stdout, re.M)` in `_matches`. Red in G1 (TID251), and G62 (`(?=x)` compiles under `re`).
- **CHK-M8-321:** `re2.compile(expected)` directly (no `(?m)`). Red row: `^foo$` against `a\nfoo\nb`.
- **CHK-M8-322:** `.search` → `.fullmatch`/`.match`. Red row: `foo` in `xfoo`.
- **CHK-M8-323:** in `_not_regex`, catch `CannotEvaluate` and return True. Red rows: `(?=x)` / `[` under `not_regex`.
- **CHK-M8-326:** `stdout.lower() == expected.lower()` in `_equals`, or `.casefold()` in `_contains`.
- **CHK-M8-327:** `test(float(stdout), float(expected))`. Red row: 2⁵³ + 1.
- **CHK-M8-328:** replace `values.parse_number` with a `Decimal(text)` in try/except `InvalidOperation`. Red rows: `1e3`, `nan`, `inf` (`Decimal` accepts all three), `1_000` (Python accepts underscores).
- **CHK-M8-329:** in `_numeric`, return True for `ne` on non-numeric stdout.
- **CHK-M8-338 (operators half):** in `compare`, `COMPARISONS[operator]` instead of `.get` (raises `KeyError`).
- Extra rows worth pinning:
  - swapping the two numeric checks (stdout first) makes `eq` `abc` against stdout `abc` `NotNumeric` instead of `CannotEvaluate`;
  - `_empty` reading `expected` (REQ-191 (3)).
