# TASK-177 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-188, REQ-189, REQ-190, REQ-191; TS §4.5 L595, L600; SR §2.4 (L130–L143, L153); #11, #13, #112 (a). Code under test: `bm/services/evaluator/operators.py` (impl-manager-m8, `work/reports/TASK-177-impl.md`). New test file: `manager/tests/test_evaluator_operators.py`. Plan rows: CHK-M8-020 to -051 (`tests/m8/test-plan.md`).

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_operators.py` | **397/397 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (after my lint-only edits to the test file) | the same file, in the 934-test combined run with `test_evaluate.py`, `test_evaluator_property.py`, `test_security_m8.py` | 934/934 passed (397 of them here) |
| plants | 14 plants in `/root/bstest-m8-mut-<id>` (removed after each) | 14/14 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file (worktree venv) | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-020 | CODE | W | r1 | PASS | `tuple(COMPARISONS) == importer.model.OPERATORS` (14). The mapping is read-only (`TypeError` on assignment). Each of the 14 returns a plain `bool`. 18 non-operators (`EQUALS`, `Equals`, `equal`, `""`, padded, NUL-suffixed, `regexp`, `!=`, `==`, `EQ`, `NOT_REGEX`, `not-regex`, Cyrillic `е`, ZWSP-suffixed …) raise `CannotEvaluate` | 2026-10-29 |
| CHK-M8-021–024 | CODE | W | r1 | PASS | REQ-188: 33 text rows (≥ 4 per operator: match, no match, multi-line, case difference, start/end, non-ASCII, no NFC). REQ-188 (2) `PermitRootLogin no` in an sshd dump PASS and `permitrootlogin no` FAIL. (3) `nullok` vs `nullok_secure` → `not_contains` False. Each pair is an exact negation on every row | 2026-10-29 |
| CHK-M8-030–032 | CODE | W | r1 | PASS | REQ-189 (1)–(3): the SR examples; `foo`/`xfoo` True; `^foo$` in `a\nfoo\nb` True; `^foo`/`xfoo` False; `\A…\z` keep whole-text meaning; `.` never matches `\n`. 25 rows; `regex`/`not_regex` exact negations | 2026-10-29 |
| CHK-M8-033 | CODE | W | r1 | PASS | 14 refused patterns (`(?=x)`, `(?!x)`, `(?<=x)`, `(?<!x)`, `(a)\1`, `[`, `(`, `)`, `a{2,1}`, `*`, `x**`, `\p{NoSuchClass}`, `(?P=n)`, `a{1001}`). Each, for both operators and four stdouts, raises `CannotEvaluate`, never a bool (the false-PASS hunt). `values.compile_pattern` refuses all 14 | 2026-10-29 |
| CHK-M8-034 | CODE | W | r1 | PASS | Lone surrogates in stdout (3 forms) and in the pattern raise `CannotEvaluate` for both operators, never `UnicodeEncodeError` | 2026-10-29 |
| CHK-M8-035 | CODE | W | r1 | PASS | REQ-189 (5): `(a*)*b` against 65,536 `a` finishes < 1 s for both operators; `^y$` over 65,536 lines < 1 s | 2026-10-29 |
| CHK-M8-036 | CODE | W | r1 | PASS | REQ-189 (6): a spy on `values.compile_pattern` sees exactly `["^a$", "^b$", "["]`. With `re2.compile` poisoned, `compare` cannot match through a private compile. The AST shows no `re`/`re2`/`regex`/`logging`/`psycopg`/db/repositories/api import | 2026-10-29 |
| CHK-M8-037 | CODE | W | r1 | PASS | Case-sensitive by default; an author's `(?i)` is honoured | 2026-10-29 |
| CHK-M8-040, -041 | CODE | W | r1 | PASS | REQ-190 (1), (2): the 28 numeric rows (incl. `-0`, `007`, `+0`, boundaries per operator, 2⁵³ + 1). All six operators agree with a `Decimal` oracle on every row. 5,000-digit integers and a 5,000-digit fraction compare exactly | 2026-10-29 |
| CHK-M8-042 | CODE | W | r1 | PASS | REQ-190 (3): 30 non-numbers (`abc`, `""`, `1e3`, `1E3`, `1e-3`, `nan`, `NaN`, `inf`, `-inf`, `Infinity`, `1_000`, `0x10`, `0b1`, `.5`, `5.`, `5 6`, `5\n6`, `٣`, `１`, `+`, `-`, `--1`, `+-1`, `1-`, `1,000`, `1.2.3`, `12abc`, and unnormalised ` 1`, `1 `, U+00A0) × six operators → `NotNumeric`; `ne` is never True | 2026-10-29 |
| CHK-M8-043 | CODE | W | r1 | PASS | REQ-190 (5): seven bad expected values × six operators → `CannotEvaluate`, checked before stdout (expected `abc`, stdout `abc` → `CannotEvaluate`) | 2026-10-29 |
| CHK-M8-044 | CODE | W | r1 | PASS | No `float(`/`int(`/`eval(` call in `operators.py` (AST) | 2026-10-29 |
| CHK-M8-050 | CODE | W | r1 | PASS | REQ-191: `""` empty; `"0"`, `"x"`, U+00A0, `"false"` not empty (on normalised text; the `"\n"`, `" \r\n\t"` and U+0020 rows go through `classify` in TASK-178). (3) A non-empty expected never changes the result | 2026-10-29 |
| CHK-M8-051 | CODE | W | r1 | PASS | hypothesis, 5,000 cases (any operator string including surrogates): `compare` returns a `bool` only for the 14, otherwise raises only `NotNumeric`/`CannotEvaluate`. The two signals are distinct classes. The canary is in no signal's `str`/`repr`/`args` | 2026-10-29 |
| CHK-M8-320 | CODE | W | plant: `import re`, `re.search(…, re.M)` | PASS (red) | Full file: the run hung on `(a*)*b` (Python `re` backtracking) until `timeout` (exit 124). Without the two linear-time rows: 42 failed, including `regex-(?=x)` and `not_regex-(?=x)` "DID NOT RAISE CannotEvaluate". G1: ruff `TID251 re is banned` (exit 1) | 2026-10-29 |
| CHK-M8-321 | CODE | W | plant: own `re2.compile` without `(?m)` | PASS (red) | 10 failed: multiline rows (`^foo$` in `a\nfoo\nb`), the compile spy, the import AST | 2026-10-29 |
| CHK-M8-322 | CODE | W | plants: `fullmatch`; `match` | PASS (red) | 10 / 7 failed: `foo`/`xfoo`, the multiline rows | 2026-10-29 |
| CHK-M8-323 | CODE | W | plant: `not_regex` returns True on `CannotEvaluate` | PASS (red) | 18 failed: every refused pattern and surrogate row under `not_regex` | 2026-10-29 |
| CHK-M8-326 | CODE | W | plants: `equals` lowercased; `contains` casefolded | PASS (red) | 2 / 2 failed: the case rows and the negation check | 2026-10-29 |
| CHK-M8-327 | CODE | W | plant: `float()` comparison | PASS (red) | 7 failed: the 2⁵³ + 1 rows, the oracle, 5,000 digits, the AST | 2026-10-29 |
| CHK-M8-328 | CODE | W | plant: bare `Decimal()` with `InvalidOperation` → None | PASS (red) | 126 failed: `1e3`, `nan`, `inf`, `1_000`, `.5`, padded … for stdout and expected | 2026-10-29 |
| CHK-M8-329 | CODE | W | plant: `ne` True on non-numeric stdout | PASS (red) | 30 failed: every `ne` non-number row | 2026-10-29 |
| CHK-M8-338 (operators half) | CODE | W | plant: `COMPARISONS[operator]` | PASS (red) | 20 failed: `KeyError` on unknown operators, the hypothesis signal property, the canary row | 2026-10-29 |
| extra x-swap | CODE | W | plant: stdout parsed before expected | PASS (red) | 42 failed: bad expected with bad stdout → `NotNumeric` | 2026-10-29 |
| extra x-empty | CODE | W | plant: `empty` reads expected | PASS (red) | 1 failed: REQ-191 (3) | 2026-10-29 |

## Acceptance (TASK-177 row)

Every row of the REQ-188 to REQ-191 tables gives the stated boolean or signal: CHK-M8-021 to -050. A lone surrogate in stdout under `regex` and `not_regex` gives `CannotEvaluate`, not an exception: CHK-M8-034. REQ-189 (6) has both halves: G1 red on the `re` plant, and the spy.

## Notes (no defect)

- `compile_pattern` is called on every evaluation, with no `lru_cache`. That is fine at this size; the linear-time rows show it.
