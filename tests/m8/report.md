# M8 test report

Phase report for M8 (evaluator). Each section is folded by the lead, unchanged, from the tester's per-task report `work/reports/<id>-test.md` (the source); headings are demoted one level. The harness blocks tester sub-agents from writing this file (user ruling 2026-10-27).

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-176 | TASK-176 TEST: PASS | `work/reports/TASK-176-test.md` |
| TASK-177 | TASK-177 TEST: PASS | `work/reports/TASK-177-test.md` |
| TASK-178 | TASK-178 TEST: PASS | `work/reports/TASK-178-test.md` |
| TASK-179 | TASK-179 TEST: PASS | `work/reports/TASK-179-test.md` |
| TASK-180 | TASK-180 TEST: PASS | `work/reports/TASK-180-test.md` |
| TASK-181 | TASK-181 TEST: PASS | `work/reports/TASK-181-test.md` |
| TASK-182 | TASK-182 TEST: PASS | `work/reports/TASK-182-test.md` |
| TASK-183 | TASK-183 TEST: PASS (revision 1) | `work/reports/TASK-183-test.md` |
| TASK-184 | TASK-184 TEST: PASS | `work/reports/TASK-184-test.md` |
| TASK-185 | TASK-185 TEST: PASS (revision 1) | `work/reports/TASK-185-test.md` |
| M8-gate | M8 gate (TP-M8-14): PASS | `work/reports/M8-gate-test.md` |

### TASK-176


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-187, REQ-193 (4), REQ-202 (model and normaliser part); TS §4.5 L589–L593, L597, L599; SR §2.4; #112 (a), #115, #116 (a). Code under test: `bm/services/evaluator/__init__.py`, `model.py`, `normalise.py` (impl-manager-m8, `work/reports/TASK-176-impl.md`). New test files: `manager/tests/test_evaluator_model.py`, `manager/tests/test_evaluator_normalise.py`. Plan rows: CHK-M8-001 to -014 (`tests/m8/test-plan.md`).

#### Ruling applied (lead, 2026-10-29, `work/decisions.md` "Normaliser: one-pass CRLF → LF")

My first run found that `normalise` is **not idempotent**. hypothesis gave `s = "\x1c\r\r\n\x1c"`: `normalise(s) = "\x1c\r\n\x1c"`, and normalising that again gives `"\x1c\n\x1c"`. The simplest case is `"a\r\r\nb"` → `"a\r\nb"` → `"a\nb"`. **The impl report's "idempotent by construction" is wrong**; the reviewer should note it. The ruling picked option (b): keep the one-pass replace (TS §4.5 L597, "CRLF becomes LF"). Idempotence and "no CRLF survives" are claimed only for inputs with no CR right before a CRLF. The rows `"a\r\r\nb"` → `"a\r\nb"`, `"a\r\nb"` → `"a\nb"` and `"a\rb"` unchanged are must-hold. The planner narrows the REQ-187 (2) wording.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_evaluator_model.py tests/test_evaluator_normalise.py` | 99/101 passed, 2 failed (`test_normalise_is_idempotent`, `test_trim_set_and_interior_are_exact`: the conflict above), 0 errors, 0 skipped |
| r1 (after the ruling) | same, properties narrowed, `test_one_pass_crlf_rows` added | **102/102 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 4 plants in `/root/bstest-m8-mut-<id>` (removed after each), same two files | 4/4 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on both test files (worktree venv) | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-001 | CODE | W | r1 | PASS | `get_args(Operator)` == `importer.model.OPERATORS` == the SR §2.4 table order, 14 distinct | 2026-10-29 |
| CHK-M8-002 | CODE | W | r1 | PASS | PASS/FAIL/ERROR = 0/1/2 (plain `int`); `get_args(VerdictCode) == (0, 1, 2)` | 2026-10-29 |
| CHK-M8-003 | CODE | W | r1 | PASS | `Detail` values are exactly the eleven #112 (a) strings in #112 (c) order, lowercase ASCII, no aliases. `INTAKE_DETAILS` is a frozenset {oversize, spool_overflow, runner_unavailable} | 2026-10-29 |
| CHK-M8-004 | CODE | W | r1 | PASS | `STDOUT_CAP` 65,536, `STDERR_CAP` 16,384 | 2026-10-29 |
| CHK-M8-005 | CODE | W | r1 | PASS | Accepted: (0, None), (1, None), and (2, d) for all 11 details. Refused with `ValueError` (22 rows): (0/1, detail), (2, None), (3, …), (−1, …), (255, …), `True`/`False`, `2.0`, `"2"`, `None`, (2, plain str `"oversize"`/`"timed out"`/`"bogus"`/`""`), (0, `""`). The message quotes no input | 2026-10-29 |
| CHK-M8-006 | CODE | W | r1 | PASS | `Verdict` and `PluginSpec` frozen; fields `code, detail` and `plugin_uuid, name, operator, expected`; equality by value | 2026-10-29 |
| CHK-M8-007 | CODE | W | r1 | PASS | mypy `--strict` (pyproject config) accepts `ResultItem` → `ResultLike` (exit 0) and refuses a dataclass without `error` (exit 1). `ResultLike` has exactly the six read-only properties | 2026-10-29 |
| CHK-M8-008 | CODE | W | r1 | PASS | `evaluator/__init__.py` AST is one string `Expr` | 2026-10-29 |
| CHK-M8-010 | CODE | W | r1 | PASS | REQ-187 (1): the three `install ok installed` forms are equal. 23 table rows hold, including `"a\rb"` kept, `"\v\fx\t"` → `x`, `"\r\r\n"` → `""`, `"x\r"` → `x`, NUL and a lone surrogate kept. 24 Unicode spaces (U+001C–U+001F, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF) kept at both edges. No NFC/NFKC, no casefold | 2026-10-29 |
| CHK-M8-011 | CODE | W | r1 | PASS | The test file has no CR byte (it reads its own bytes) | 2026-10-29 |
| CHK-M8-012 | CODE | W | r1 | PASS | Idempotent on 10,000 hypothesis strings without `"\r\r\n"` (ruling). The one-pass rows hold, and `normalise(normalise("a\r\r\nb")) == "a\nb"` is pinned as documented behaviour | 2026-10-29 |
| CHK-M8-013 | CODE | W | r1 | PASS | 3,000 strings: the output is a contiguous slice of the CRLF-folded input; removed edges ⊆ #115 set; kept edges ∉ it; no CRLF survives (under the ruling) | 2026-10-29 |
| CHK-M8-014 | CODE | W | r1 | PASS | `model.py` and `normalise.py` import nothing from `logging`, `re`, `psycopg`, `bm.*` (AST, no relative imports) | 2026-10-29 |
| CHK-M8-324 | CODE | W | plant: `.replace("\r\n", "\r\n")` (CRLF kept) | PASS (red) | 6 failed: the table CRLF rows, the one-pass rows, the trim property | 2026-10-29 |
| CHK-M8-325 | CODE | W | plant: `.strip()` | PASS (red) | 25 failed: the Unicode-space rows (U+00A0, U+2003 …), REQ-187 named rows, the trim property | 2026-10-29 |
| CHK-M8-337 | CODE | W | plant: `return` before the detail checks | PASS (red) | 11 failed: every (code, detail) mismatch row | 2026-10-29 |
| CHK-M8-364 | CODE | W | plant: code set `(0, 1, 2, 3)` | PASS (red) | 1 failed: `Verdict(3, None)` (it also turns CHK-M8-130 red once TASK-178's property suite exists) | 2026-10-29 |

#### Acceptance (TASK-176 row)

- `Operator` values equal `importer.model.OPERATORS` in order → CHK-M8-001.
- `Verdict(0, Detail.TIMED_OUT)`, `Verdict(2, None)`, `Verdict(3, None)` raise → CHK-M8-005 (and more).
- `Detail` is exactly the eleven #112 values → CHK-M8-003.
- The REQ-187 table holds → CHK-M8-010 (REQ-187 (3) and (5) go through `classify`, so they are tested in TASK-178).
- A `ResultItem` type-checks as `ResultLike` under `mypy --strict` → CHK-M8-007.
- REQ-187 (2) as narrowed by the ruling → CHK-M8-012.

#### Notes

- The stricter `type(code) is int` (bool refused) is confirmed by the `True`/`False` rows.
- The normaliser's one-pass behaviour on `"\r\r\n"` is now pinned by must-hold rows. A future change to repeat the replace until no CRLF is left would turn `test_one_pass_crlf_rows` red, and that is intended.

### TASK-177


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-188, REQ-189, REQ-190, REQ-191; TS §4.5 L595, L600; SR §2.4 (L130–L143, L153); #11, #13, #112 (a). Code under test: `bm/services/evaluator/operators.py` (impl-manager-m8, `work/reports/TASK-177-impl.md`). New test file: `manager/tests/test_evaluator_operators.py`. Plan rows: CHK-M8-020 to -051 (`tests/m8/test-plan.md`).

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_operators.py` | **397/397 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (after my lint-only edits to the test file) | the same file, in the 934-test combined run with `test_evaluate.py`, `test_evaluator_property.py`, `test_security_m8.py` | 934/934 passed (397 of them here) |
| plants | 14 plants in `/root/bstest-m8-mut-<id>` (removed after each) | 14/14 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file (worktree venv) | clean |

#### Report rows (tests/m8/report.md)

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

#### Acceptance (TASK-177 row)

Every row of the REQ-188 to REQ-191 tables gives the stated boolean or signal: CHK-M8-021 to -050. A lone surrogate in stdout under `regex` and `not_regex` gives `CannotEvaluate`, not an exception: CHK-M8-034. REQ-189 (6) has both halves: G1 red on the `re` plant, and the spy.

#### Notes (no defect)

- `compile_pattern` is called on every evaluation, with no `lru_cache`. That is fine at this size; the linear-time rows show it.

### TASK-178


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-186, REQ-192, REQ-193, REQ-205 (1); REQ-187 (3), (5) and REQ-190 (4) end to end; TS §4.5 L589–L600; SR §1.1 L87, §2.4; #112 (vocabulary, order, totality), #113, #114. Code under test: `bm/services/evaluator/evaluate.py` (impl-manager-m8, `work/reports/TASK-178-impl.md`). New test files: `manager/tests/test_evaluate.py`, `manager/tests/test_evaluator_property.py` (TASK-178 part), `manager/tests/test_security_m8.py` (static part: CHK-M8-220, -221, -223, -224). Plan rows: CHK-M8-060 to -077, -130 to -132, -136, -220 to -224.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluate.py tests/test_evaluator_property.py` | **489/489 passed**, 0 failed, 0 errors, 0 skipped |
| r2 | `pytest tests/test_evaluator_operators.py tests/test_evaluate.py tests/test_evaluator_property.py tests/test_security_m8.py` | **934/934 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 15 plants in `/root/bstest-m8-mut-<id>`, each running `test_evaluate.py`, `test_evaluator_property.py`, `test_security_m8.py` (537 tests) | 15/15 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the three test files | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-060 | CODE | W | r1 | PASS | REQ-186 (2): `evaluate` and `classify` take exactly `operator, expected, stdout, exit_code, timed_out, truncated`, all positional-or-keyword, with no defaults | 2026-10-29 |
| CHK-M8-061, -069 | CODE | W | r1 | PASS | REQ-186 (1): on every row, `evaluate == classify.code` and the code is in {0, 1, 2} (a plain int). Each of the 14 operators PASSes and FAILs with detail None | 2026-10-29 |
| CHK-M8-062 | CODE | W | r1 | PASS | REQ-192 (1): exits 0, 1, 2, 3, 100, 124, 125 never decide (14 operators × PASS and FAIL). 126 `cannot run`; 127 `not found`; 128, 129, 137, 143, 255, 256, 2³¹−1, −1, −9, −2³¹ `killed by signal`; None `no exit code` (14 operators × 2) | 2026-10-29 |
| CHK-M8-063, -064 | CODE | W | r1 | PASS | REQ-192 (2): `timed_out` → `timed out`, and `truncated` → `stdout truncated`, for all 14 operators on PASS and FAIL input. `contains`, with the expected text inside the kept text, is ERROR when truncated | 2026-10-29 |
| CHK-M8-065 | CODE | W | r1 | PASS | REQ-192 (3): exit 1, `""`, `empty` → PASS; `not_empty` → FAIL; `not_contains`, `equals ""` → PASS | 2026-10-29 |
| CHK-M8-066 | CODE | W | r1 | PASS | REQ-192 (4): `EQUALS`, `equal`, `""`, `Equals`, ` equals`, `regexp` → ERROR `cannot evaluate` | 2026-10-29 |
| CHK-M8-067 | CODE | W | r1 | PASS | REQ-193 (1): one case gives each of the 8 evaluation details (the 3 intake details are in TASK-179) | 2026-10-29 |
| CHK-M8-068 | CODE | W | r1 | PASS | REQ-193 (2) and #112 (c), 17 rows. Timed out + 137 + truncated → `timed out`; 127 + truncated → `not found`; truncated + non-numeric → `stdout truncated`. Also: None + truncated, 126 + timed out, 128/−1 + truncated, a bad operator after each run check, bad expected and bad stdout → `cannot evaluate` | 2026-10-29 |
| CHK-M8-070, -071 | CODE | W | r1 | PASS | REQ-187 (3): `Install…` vs `install…` FAIL. (5): expected `x\r\n` vs `x` PASS. REQ-190 (4): `" 42\r\n"` `eq 42` PASS. Also `regex ^a$` vs `a\r\nb` PASS; `empty` on `"\r\n"`, `" \r\n\t"`, `" "` PASS; U+00A0 `not_empty` PASS and `empty` FAIL (REQ-191 (1), the lead's confirmation) | 2026-10-29 |
| CHK-M8-072 | CODE | W | r1 | PASS | The false-PASS hunt: `not_regex` (refused patterns, surrogates), `ne` (non-numeric stdout or expected), and upper/padded spellings of negated operators are never PASS. They are ERROR `cannot evaluate`/`stdout not numeric`. The 10 non-numeric stdouts × 6 operators give `stdout not numeric`, and so do multi-line `5\n6` and `5\r\n6` | 2026-10-29 |
| CHK-M8-073 | CODE | W | r1 | PASS | REQ-205 (1): 0, 1, 0, 1 for the four SR §1.1 rows | 2026-10-29 |
| CHK-M8-074 | CODE | W | r1 | PASS | REQ-186 (4): over 131 paths covering every operator and ERROR path, two passes give equal verdicts. No log record at DEBUG (caplog), nothing on stdout/stderr (capsys). A `sys.addaudithook` probe sees no `open`, `socket.*`, `subprocess.Popen`, `os.system`/`exec`/`posix_spawn`, `os.remove`/`rename` or `shutil.*` | 2026-10-29 |
| CHK-M8-075 | CODE | W | r1 | PASS | With the canary in operator, expected and stdout (9 ERROR paths), the detail is a `Detail` member and holds no canary and no exit code | 2026-10-29 |
| CHK-M8-076 | CODE | W | r1 | PASS | `time.time`/`monotonic`/`perf_counter`/`*_ns` patched to raise: every path still gives a verdict. The module globals are unchanged after 131 calls | 2026-10-29 |
| CHK-M8-077 | CODE | W | r1 | PASS | 1 MiB stdout (and 1 MiB expected for text operators) under each of the 14 < 2 s; 65,536 lines < 1 s | 2026-10-29 |
| CHK-M8-130 | CODE | W | r1 | PASS | REQ-186 (3): 10,000 hypothesis inputs (the 14, uppercased, odd and random operators; text with surrogates, CR, NUL, U+00A0; exit codes over [−2³¹, 2³¹−1] and None; both flags). No exception; code in {0, 1, 2}; detail None iff the code is 0 or 1; `evaluate == classify.code`; an unknown operator is always 2 | 2026-10-29 |
| CHK-M8-132 | CODE | W | r1 | PASS | 5,000 generated #13 number pairs (sign, up to 60 digits, fraction) × 6 operators agree with the `Decimal` oracle. 2,000 equal values in different spellings are `eq` and not `ne` | 2026-10-29 |
| CHK-M8-136 | CODE | W | r1 | PASS | 3,000 cases: with no flags and passing input, ERROR iff None, < 0, 126, 127 or ≥ 128; the detail is one of the four exit-code details | 2026-10-29 |
| CHK-M8-131 (classify half) | CODE | W | r1 | PASS | 3,000 cases (no CR CR LF, per the ruling): pre-normalising both strings never changes the verdict | 2026-10-29 |
| CHK-M8-220 | CODE | W | r2 | PASS | REQ-202 (1) for all 7 pure modules (`model`, `normalise`, `operators`, `evaluate`, `verdict`, `eval_spec`, `score`). The static transitive graph reaches only the evaluator modules plus `importer.model`/`values`, with no `logging`/`re`/psycopg/fastapi. In a fresh interpreter (PYTHONPATH = this copy; child `bitscan_manager.__file__` checked), the newly loaded `bitscan_manager.*` modules are the same, with no psycopg/fastapi/starlette/pydantic | 2026-10-29 |
| CHK-M8-221, -223, -224 | CODE | W | r2 | PASS | `scores`/`reevaluate` import no `api`, no `repositories.catalog*`, no `re`/`logging`. No logging call in `evaluator/` or the two repositories formats a result field. No `re`/`regex`/`sre_*` import in any M8 file. The pure modules have no `getLogger`/`print(` | 2026-10-29 |
| CHK-M8-330 | CODE | W | plant: exit 1 → FAIL | PASS (red) | 17 failed: `test_grep_exit_1_with_empty_output`, `ordinary_exit_codes[*-1]`, both properties | 2026-10-29 |
| CHK-M8-331 | CODE | W | plant: `> 128` | PASS (red) | 18 failed: `error_exit_codes[*-128-killed by signal]`, the boundary row, properties | 2026-10-29 |
| CHK-M8-332 | CODE | W | plants: no 126 branch; no 127 branch | PASS (red) | 18 / 20 failed: the 126 (127) rows across 14 operators | 2026-10-29 |
| CHK-M8-333 | CODE | W | plants: drop `< 0`; None coerced to 0 | PASS (red) | 45 / 18 failed: every negative row; every None row | 2026-10-29 |
| CHK-M8-334 | CODE | W | plant: no `timed_out` branch | PASS (red) | 20 failed: the 14-operator timed-out rows, order rows | 2026-10-29 |
| CHK-M8-335 | CODE | W | plant: `truncated` ignored | PASS (red) | 20 failed: the 14-operator truncated rows, the `contains` row, order rows | 2026-10-29 |
| CHK-M8-336 | CODE | W | plant: `truncated` checked first | PASS (red) | 7 failed: the `test_detail_order` rows (137 + timed out + truncated gives `stdout truncated`) | 2026-10-29 |
| CHK-M8-338 (classify half) | CODE | W | plant: only `NotNumeric` caught | PASS (red) | 31 failed, including G63 `test_classify_and_evaluate_are_total` (`CannotEvaluate` escapes) | 2026-10-29 |
| CHK-M8-361 | CODE | W | plant: `from bitscan_manager.repositories import catalog` in `evaluate.py` | PASS (red) | 4 failed: the static and runtime import graphs for `evaluate` and `verdict` (G65) | 2026-10-29 |
| CHK-M8-362 | CODE | W | plants: `logging…debug("stdout=%s", stdout)`; `raise ValueError("not numeric: " + stdout)` | PASS (red) | 5 failed (`test_pure_no_log_no_output_no_io` caught the record; G65 graph/logging rows) / 78 failed (totality, canary, every non-numeric row) | 2026-10-29 |
| CHK-M8-363 | CODE | W | plant: detail forced to `"stdout not numeric: " + stdout` (bypassing `Verdict`) | PASS (red) | 69 failed: `test_detail_never_quotes_input`, the non-numeric rows, totality (detail not a `Detail`) | 2026-10-29 |
| extra x-noexpnorm | CODE | W | plant: expected not normalised | PASS (red) | 7 failed: REQ-187 (5) rows and the pre-normalised property | 2026-10-29 |

#### Acceptance (TASK-178 row)

- REQ-186 (1) → CHK-M8-061; (2) → -060; (4) → -074, -076.
- REQ-192 (1)–(4) → -062 to -066.
- REQ-193 (1)–(3) → -067 to -069.
- REQ-205 (1) → -073.
- The REQ-186 (3) property found no exception in 10,000 inputs → -130; the -338 plant turns it red.
- CHK-M8-364 (`Verdict` accepting 3, TASK-176) also turns CHK-M8-130 red, because a 3 can't be produced; the TASK-176 row stands.

#### Notes (no defect)

- `classify` normalises inside its comparison, after the run checks. So a timed-out or truncated result is ERROR without its text being looked at. That matches D1.

### TASK-179


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-194 (1)–(6), REQ-205 (2); TS §4.5 L593, L596, L599; §3.3 L226; SR §2.4 ("Only stdout is compared"); #12, #57, #112 (c), #113, #116. Code under test: `bm/services/evaluator/verdict.py` (impl-manager-m8, `work/reports/TASK-179-impl.md`). New test file: `manager/tests/test_evaluator_verdict.py`. Plan rows: CHK-M8-100 to -109.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | **205/205 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants, each running those three files plus `test_evaluator_property.py` (210 tests) | 10/10 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-100 | CODE | W | r1 | PASS | `utf8_size` counts 1/2/3/4-byte characters. stdout 65,536 ASCII bytes passes and 65,537 is `oversize`. `"€"×21,845+"a"` (65,536 bytes) passes; `"€"×21,846` (21,846 characters, 65,538 bytes) is `oversize`. `"😀"×16,384` passes, and one more byte is `oversize` | 2026-10-29 |
| CHK-M8-101 | CODE | W | r1 | PASS | stderr 16,384 passes and 16,385 is `oversize`; `"€"×5,462` (16,386 bytes) is `oversize`, `"€"×5,461+"a"` passes. Seven flag sets (none, `truncated` false/true, `timed_out`, exit None/127/−1) never avoid the cap. The `truncated` flag alone is `stdout truncated`, not `oversize` | 2026-10-29 |
| CHK-M8-102 | CODE | W | r1 | PASS | A lone surrogate counts 3 bytes (surrogatepass) with no exception; the cap boundary holds at 65,536/65,537 and 16,384/16,385 with surrogates | 2026-10-29 |
| CHK-M8-103 | CODE | W | r1 | PASS | REQ-194 (2): oversize stdout or stderr with `error` `spool_overflow`, `runner_unavailable` or `bogus` (and with timed out) → `oversize` | 2026-10-29 |
| CHK-M8-104 | CODE | W | r1 | PASS | REQ-194 (3): `spool_overflow` / `runner_unavailable` → ERROR with that detail even for passing stdout, exit None or timed out; a spy on `verdict.classify` records 0 calls. With `error` None, exactly one call with `(operator, expected, stdout, exit_code, timed_out, truncated)` | 2026-10-29 |
| CHK-M8-105 | CODE | W | r1 | PASS | `error` `bogus`, `""`, `SPOOL_OVERFLOW`, ` spool_overflow`, `timed out` → ERROR `cannot evaluate`, `classify` not called | 2026-10-29 |
| CHK-M8-106 | CODE | W | r1 | PASS | REQ-194 (4): 16,384 bytes of `ERROR: permission denied` never change a PASS. Expected text in stderr never makes a FAIL a PASS; stderr `nullok` doesn't fail `not_contains`; stderr `0` doesn't feed `eq`; stderr doesn't make `empty` FAIL | 2026-10-29 |
| CHK-M8-107 | CODE | W | r1 | PASS | REQ-194 (5), REQ-205 (2): through `build_eval_spec` → `parse_eval_spec` → `get` of the SR §1.1 plugin: PASS, FAIL, FAIL (exit 1), PASS (trailing LF) | 2026-10-29 |
| CHK-M8-108 | CODE | W, L | r1; G3 | PASS | REQ-194 (6): real M3 `ResultItem`s (`model_validate`) give PASS, FAIL, `spool_overflow`, `oversize`, `no exit code`; mypy --strict accepts the call; `verdict.py` imports nothing from `api` or `repositories` (AST) | 2026-10-29 |
| CHK-M8-109 | CODE | W | r1 | PASS | 12 results × 5 specs (incl. a refused pattern, a bad operator): inside the caps with no error, `result_verdict == classify` | 2026-10-29 |
| canary | CODE | W | r1 | PASS | A canary in stdout, stderr and `error` (also at oversize sizes) is in no verdict | 2026-10-29 |
| CHK-M8-339 | CODE | W | plant: `len(text)` | PASS (red) | 4 failed: the byte rows (`€`, emoji, stderr `€`, surrogates) | 2026-10-29 |
| CHK-M8-340 | CODE | W | plants: stdout `>=`; stderr `>=` | PASS (red) | 4 / 2 failed: the exact-cap rows | 2026-10-29 |
| CHK-M8-341 | CODE | W | plant: oversize ⇔ `truncated` | PASS (red) | 20 failed: flags rows, oversize-before-error, `ResultItem` oversize, agreement rows | 2026-10-29 |
| CHK-M8-342 | CODE | W | plants: classify still called on `spool_overflow`; its result returned | PASS (red) | 1 failed (the spy row) / 2 failed (spy row, `ResultItem` row) | 2026-10-29 |
| CHK-M8-343 | CODE | W | plants: stdout + stderr compared; stderr instead | PASS (red) | 4 / 4 failed: stderr cap row, classify-args spy, stderr rows | 2026-10-29 |
| extra x179-order | CODE | W | plant: runner error before oversize | PASS (red) | 1 failed: oversize wins over `spool_overflow` | 2026-10-29 |
| extra x179-unknown | CODE | W | plant: an unknown `error` falls to `classify` | PASS (red) | 5 failed: the unknown-error rows give PASS | 2026-10-29 |

#### Acceptance (TASK-179 row)

REQ-194 (1) → -100, -101; (2) → -103; (3) → -104; (4) → -106; (5) → -107; (6) → -108; REQ-205 (2) → -107. Every security row (S: -339, -341, -342) has a plant that went red.

### TASK-180


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-195 (1)–(4); TS §4.5 L587, L603; §5.2 L880, L888; §3.5 L248; #117. Code under test: `bm/services/evaluator/eval_spec.py` (impl-manager-m8b, `work/reports/TASK-180-impl.md`). New test file: `manager/tests/test_eval_spec.py`. Plan rows: CHK-M8-110 to -116.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | 205/205 passed, 0 failed, 0 errors, 0 skipped |
| plants p1 | 12 plants (four files, 210 tests each) | 11/12 red; **x180-quote stayed green** (a test gap, mine; see below) |
| r2 (test strengthened) | `pytest tests/test_eval_spec.py` | **101/101 passed**, 0 failed, 0 errors, 0 skipped |
| plants p2 | x180-quote again, plus a second quote plant on the uuid message | 2/2 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

#### Test gap found and closed (no product defect)

Plant x180-quote (`EvalSpecError("eval_spec values must be strings: " + repr(value))`) passed all of r1. My canary inputs had no non-string value holding the canary, and the "small fixed set of messages" bound was too loose. Added (r2): canary inputs as list, dict and nested values, and `test_one_fixed_message_per_refusal`, where different inputs refused for the same reason must give one identical message (six groups: name type, expected type, uuid, operator, name length, expected length). Both quote plants are now red. The product's messages are fixed and quote nothing.

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-110 | CODE | W | r2 | PASS | REQ-195 (1): round trip through `json.dumps(allow_nan=False)` / `json.loads` for 1, 2, 14 and 5,000 plugins (non-ASCII names), plus 500 hypothesis specs of 1–50 entries; order kept; `build` output is exactly the #117 shape (only `plugins`; each entry exactly the four string keys; lowercase uuid). `parse` doesn't mutate its input | 2026-10-29 |
| CHK-M8-111 | CODE | W | r2 | PASS | REQ-195 (2): 52 refusals, each `EvalSpecError` (a `ValueError`): not an object (list, str, int, None, bytes); `{}`; missing `plugins`; extra top keys; `plugins` dict/tuple; empty; 5,001 entries; entry not an object; each of the four keys missing; `execute`/`timeout_s`/other extra; duplicate uuid; uppercase, braced, urn, 32-hex, short, padded, int, None and `UUID`-object uuids; operator `EQUALS`/`""`/`equal`/padded; name `""` and 401 chars; expected 4,001; int/None/list/bool/float values. Accepted: 5,000 entries, name 1 and 400 (also non-ASCII), expected 0 and 4,000 (also `€`), each of the 14 operators. `EvalSpec(...)` refuses the same seven cases itself | 2026-10-29 |
| CHK-M8-112 | CODE | W | r2 | PASS | 18 canary inputs: the canary is in no `str`/`repr`/`args`/`__cause__`/`__context__`. Six refusal groups each give one identical message | 2026-10-29 |
| CHK-M8-113 | CODE | W | r2 | PASS | REQ-195 (3): `get` returns each listed entry and None for an unknown uuid | 2026-10-29 |
| CHK-M8-114 | CODE | W | r2 | PASS | REQ-195 (4): the SR §1.1 entry holds the name, `equals` and `install ok installed`; a recursive key walk finds only `plugins, plugin_uuid, name, operator, expected` (no `execute`, no `timeout_s`) | 2026-10-29 |
| CHK-M8-115 | CODE | W | r2 | PASS | Lengths count characters (`€`×400 accepted); a lone-surrogate name never crashes the parser | 2026-10-29 |
| CHK-M8-116 | CODE | W | r2 | PASS | 2,000 hypothesis JSON-like values (nested dicts/lists, NaN floats, uuids, operator names): `parse` raises only `EvalSpecError`, and anything accepted builds back to the same value | 2026-10-29 |
| CHK-M8-344 | CODE | W | plants: entry keys ⊇ (extras accepted); duplicate check off; top key `"plugins" in` | PASS (red) | 4 / 2 / 2 failed: the extra-key, duplicate and extra-top-key rows | 2026-10-29 |
| CHK-M8-345 | CODE | W | plant: `build` writes `"execute": ""` | PASS (red) | 16 failed: round trips, the shape row, the SR §1.1 key walk, the boundaries, the generated round trip | 2026-10-29 |
| extra x180-upper | CODE | W | plant: lowercase check off | PASS (red) | 1 failed: uppercase uuid | 2026-10-29 |
| extra x180-5001 / name401 / name0 / exp4001 | CODE | W | plants: each bound off by one | PASS (red) | 2 failed each: the parse row and the constructor row | 2026-10-29 |
| extra x180-types | CODE | W | plant: int accepted as a value | PASS (red) | 5 failed (`TypeError` escapes: totality) | 2026-10-29 |
| extra x180-op | CODE | W | plant: operator check off | PASS (red) | 6 failed | 2026-10-29 |
| extra x180-quote, x180-quote-uuid | CODE | W | plants: message quotes `repr(value)` | PASS (red, p2) | 3 / 2 failed: the fixed-message groups and the canary row | 2026-10-29 |

#### Notes for M9 (no defect here)

- `parse_eval_spec` accepts a lone surrogate in `name` or `expected` (a valid Python `str`). PostgreSQL JSONB refuses `\ud800`, so M9's job builder can't store such a value anyway. Worth a line in M9's builder tests.
- The `<family name> - <plugin name>` composition is the caller's (M9). `build_eval_spec` stores `name` as given; the SR §1.1 row passes the composed name.

### TASK-181


Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-196 (1)–(3), REQ-197 (1), (2); TS §4.5 L601–L602, §4.4 L583; #119, #120. Code under test: `bm/services/evaluator/score.py` (impl-manager-m8b, `work/reports/TASK-181-impl.md`). New test file: `manager/tests/test_evaluator_score.py`. Plan rows: CHK-M8-120 to -124, -134.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | **205/205 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 8 plants (four files, 210 tests each) | 8/8 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-120 | CODE | W | r1 | PASS | REQ-196 (1): (3,1,5,7) → `HostScore(3,1,5,7,0.75)`; (0,0,4,2) → None; (0,3,0,0) → 0.0 (not None); (1,0,0,0) → 1.0; (1,2,0,0) → exactly 1/3; (0,0,0,0) → None. The score is an unrounded `float` | 2026-10-29 |
| CHK-M8-121 | CODE | W | r1 | PASS | REQ-196 (2): each count negative → `ValueError`; a bool count is refused | 2026-10-29 |
| CHK-M8-134 | CODE | W | r1 | PASS | REQ-196 (3): 3,000 hypothesis count sets up to 10⁹: None iff passed + failed = 0, else in [0, 1] and equal to p/(p+f); other errors and not-run values never change it | 2026-10-29 |
| CHK-M8-122 | CODE | W | r1 | PASS | REQ-197 (1): no rows → the original, provenance None (also from an empty iterator). Ids 5, 9, 7 in all 6 orders, with `reevaluated_at` against id order → id 9's code, detail, version, user and time, and the original unchanged beside it. Equal timestamps → the highest id; a one-shot iterator works | 2026-10-29 |
| CHK-M8-123 | CODE | W | r1 | PASS | REQ-197 (2): rows of another plugin, another job or both (ids 100–102) are ignored; adding a matching id 4 then wins | 2026-10-29 |
| CHK-M8-124 | CODE | W | r1 | PASS | ERROR → PASS gives detail None; PASS → ERROR carries the re-evaluation's detail. 2,000 hypothesis row sets match a max-id oracle | 2026-10-29 |
| CHK-M8-346 | CODE | W | plant: ERROR in the denominator | PASS (red) | 3 failed: the REQ-196 rows, counts carried, the independence property | 2026-10-29 |
| CHK-M8-347 | CODE | W | plant: 0 ÷ 0 → 0.0 | PASS (red) | 2 failed: `(0,0,4,2)` row, the property | 2026-10-29 |
| CHK-M8-348 (unit) | CODE | W | plants: lowest id; `reevaluated_at`; "always the later row" | PASS (red) | 9 / 9 / 7 failed: the permutation rows, the equal-time row, the iterator row, the oracle | 2026-10-29 |
| extra x181-filter | CODE | W | plant: plugin not filtered | PASS (red) | 2 failed | 2026-10-29 |
| extra x181-neg | CODE | W | plant: `count < -1` | PASS (red) | 4 failed | 2026-10-29 |

#### Acceptance (TASK-181 row)

REQ-196 (1) → -120; (2) → -121; (3) → -134; REQ-197 (1) → -122; (2) → -123. The PostgreSQL half of CHK-M8-348 (the SQL) is in TASK-182 and TASK-184.

### TASK-182


Tester: tester-m8, 2026-10-29. Full rigor. REQ-197, REQ-198 (1)–(5); TS §4.5 L601–L602, §4.4 L577–L583, §5.2 (no index on `scan_result_reeval`); #119. Code under test: `bm/repositories/results.py` (impl-manager-m8b, `work/reports/TASK-182-impl.md`). New test files: `manager/tests/evaluator_pg_fixtures.py` (TP-M8-01 builder), `manager/tests/test_results_repo_pg.py`. Plan rows: CHK-M8-140 to -142, -150 to -160.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_results_repo_pg.py` | **15/15 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 8 plants (7 pytest, 1 ruff) | 8/8 red |
| static (L) | whole-tree `ruff check manager` (after fixing my builder's E501s, which the reviewer flagged), `ruff format --check`, `mypy --strict` on both files | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-140, -142 | APP | W | r1 | PASS | The builder's rows (owner-written) read back as `bitscan_app`: 11 results whose `job_created_at` equals the job's; the TS §6.5 payload and the #117 `eval_spec` (no `execute`). Host B's retry was created next month: its results sit in a second monthly partition, and none in the default. The trigger refuses a `job_created_at` off by 1 s | 2026-10-29 |
| CHK-M8-141 | APP | W | r1 | PASS | Checksums are stable; one byte changed in one row changes the parent checksum, and a rollback restores it | 2026-10-29 |
| CHK-M8-150 | APP | W | r1 | PASS | REQ-198 (1a): `effective_results` returns exactly the scan's 11 results (originals and the retry), ordered by agent, job and plugin, each with its agent (a retry result carries the original's agent). A result without re-evaluation has the effective verdict = the original, with provenance None | 2026-10-29 |
| CHK-M8-151 | APP | W | r1 | PASS | Ids base+5 (ERROR, +1 h), base+9 (PASS, −5 h), base+7 (FAIL, +9 h) → effective PASS from base+9 with its `policy_version` 9, user 90 and time; original FAIL beside it | 2026-10-29 |
| CHK-M8-152 | APP | W | r1 | PASS | REQ-198 (1b): A (2,1,1,1) all four kinds; B (2,1,0,0), the retry fills the missing plugins; C (0,0,0,3) queued; D (2,0,0,0), FAIL re-evaluated to PASS; E (0,0,2,0) | 2026-10-29 |
| CHK-M8-153, -154 | APP | W | r1 | PASS | REQ-198 (2), (3): the second scan's job never appears. Its re-evaluation rows (higher ids, same agent and plugins) don't touch scan 1. The second scan alone gives 5 rows and (2,3,0,0) | 2026-10-29 |
| CHK-M8-155 | APP | W | r1 | PASS | A planted duplicate (original and retry both hold a plugin) is counted twice, (1,1,0,1), not hidden. A queued retry's plugins are not run once each, not twice | 2026-10-29 |
| CHK-M8-157 | APP | W | r1 | PASS | Unknown scan → `[]` for both. A scan with no jobs → `[]`. Jobs and no results → no rows, and counts (0,0,0,2) plus (0,0,0,0) for an empty payload | 2026-10-29 |
| CHK-M8-158 | APP | W | r1 | PASS | REQ-198 (5): `EXPLAIN (ANALYZE, FORMAT JSON)` of both statements has exactly one node on `scan_result_reeval`, `Actual Loops` = 1, and no SubPlan above it | 2026-10-29 |
| CHK-M8-159 | APP | W | r1 | PASS | Each function issues exactly one statement (`WITH … SELECT`), with no write or row-lock word, and the scan id bound as a parameter (not in the SQL text) | 2026-10-29 |
| CHK-M8-160 | APP | W | r1 | PASS | Agent A's inventory job adds no host | 2026-10-29 |
| CHK-M8-348 (SQL) | APP | W | plants: `reeval_id ASC`; `reevaluated_at DESC` | PASS (red) | 2 / 2 failed: highest-id row, host counts | 2026-10-29 |
| CHK-M8-349 | CODE | W | plant: an f-string query appended to `results.py` | PASS (red) | ruff `S608`, exit 1 | 2026-10-29 |
| CHK-M8-351 | APP | W | plant: `LEFT JOIN LATERAL (… FROM scan_result_reeval … LIMIT 1)` per result | PASS (red) | 2 failed: the EXPLAIN rows (`Actual Loops` > 1) | 2026-10-29 |
| CHK-M8-352 | APP | W | plants: counts ignore retry results; planned without DISTINCT and with retries | PASS (red) | 2 failed (B (2,0,0,2)) / 3 failed (retry plugins counted twice) | 2026-10-29 |
| extra x182-scanfilter / x182-kind | APP | W | plants: no scan filter; inventory jobs included | PASS (red) | 7 / 6 failed | 2026-10-29 |

#### Acceptance (TASK-182 row)

REQ-198 (1)–(5) → the rows above; (4) is the S608 plant. The REQ-197 (3) property is in TASK-184.

#### Notes (no defect)

- Impl note (3) confirmed: an original job with an empty `plugins` list gives its agent (0,0,0,0) rather than dropping it.

### TASK-183


Tester: tester-m8, 2026-10-29. Full rigor. REQ-200, REQ-201 (lock, one statement, chunks), REQ-204 (1); TS §4.5 L601, §5.2 L994–L1006; #118 (f), (h). Code under test: `bm/repositories/reeval.py` r1 (impl-manager-m8b, `work/reports/TASK-183-impl.md`, "Revision 1": `StoredResult.eval_code`; NULL stdout kept as None). New test file: `manager/tests/test_reeval_repo_pg.py`. Plan rows: CHK-M8-170 to -176, -225.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_reeval_repo_pg.py` | 39/40 passed, 1 failed: `test_no_update_delete_or_row_lock`. A **test bug** (mine): the substring `TRUNCATE` matched the column `truncated` |
| r1 re-run | `pytest "tests/test_reeval_repo_pg.py::test_no_update_delete_or_row_lock"` (whole-word check) | **1/1 passed**, so the file is **40/40** |
| plants | 8 plants (7 pytest, 1 ruff) | 8/8 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-170 | APP | W | r1 | PASS | As `bitscan_app` with only the TS §5.2 grants: `lock_scan` returns `ScanRef(scan, policy, 3)` (the scan's version, not the policy's 4); None for an unknown scan; `RuntimeError` in autocommit | 2026-10-29 |
| CHK-M8-171 | APP | W | r1 | PASS | After an owner "import" (v2, a changed expected, a changed operator, a dropped plugin): version 2, not deleted, exactly the two listed plugins with their current (operator, expected); a read-only mapping. Deleted → `deleted` True; no listed plugins → `{}` with v2; unknown → None. A statement spy sees exactly 1 SELECT | 2026-10-29 |
| CHK-M8-172 | APP | W | r1 | PASS | (2,500, chunk 1,000), (2,500, 3), (50, 1): every chunk ≤ size, only the last short, each result exactly once; `pg_cursors` shows the server-side cursor during iteration. Values carried: stdout (NULL kept as None, r1), exit code, flags, original `eval_code` and `eval_detail`. Retries are included (also across partitions); other scans and inventory jobs are excluded; an unknown scan gives none; `chunk=0` → `ValueError` | 2026-10-29 |
| CHK-M8-173 | APP | W | r1 | PASS | N = 0, 1, 7, 1,000: returns N and adds exactly N with the given version 42, user 77, codes and details; `reevaluated_at` is the column default (`now()` of the transaction) | 2026-10-29 |
| CHK-M8-174 | APP | W | r1 | PASS | Two sessions on one scan: the second waits (`pg_locks` advisory, not granted, polled at 20 ms) until the first commits. Two scans don't wait. The lock is released at rollback | 2026-10-29 |
| CHK-M8-175 | APP | W | r1 re-run | PASS | All four functions: verbs only SELECT/INSERT, no UPDATE/DELETE/TRUNCATE/MERGE (whole words) and no `FOR UPDATE`/`SHARE`/`NO KEY`/`KEY SHARE`; 5 statements in all (lock 2, definitions 1, cursor 1, insert 1) | 2026-10-29 |
| CHK-M8-225 | APP | W | r1 | PASS | REQ-204 (1): as `bitscan_app`, `UPDATE … SET eval_code`, `UPDATE … WHERE false`, `DELETE`, `DELETE … WHERE false` and `TRUNCATE` on `scan_result` (parent), the current-month partition, `scan_result_default` and `scan_result_reeval` all raise `InsufficientPrivilege` (20 rows). The app has SELECT on the 7 tables read, and INSERT but no UPDATE/DELETE on `scan_result_reeval` | 2026-10-29 |
| CHK-M8-350 | CODE | W | plant: an f-string `DELETE` query in `reeval.py` | PASS (red) | ruff `S608`, exit 1 | 2026-10-29 |
| CHK-M8-354 | APP | W | plant: an extra version-only statement before the definitions read | PASS (red) | 2 failed: one-statement spy (2 ≠ 1), statement count (6 ≠ 5). The race form is in TASK-185 | 2026-10-29 |
| CHK-M8-358 | APP | W | plant: the advisory lock replaced by `concat(…)` | PASS (red) | 1 failed: "not waiting" | 2026-10-29 |
| CHK-M8-360 | APP | W | plant: `fetchall()` | PASS (red) | 3 failed: every chunk-size row | 2026-10-29 |
| extra x183-session-lock | APP | W | plant: `pg_advisory_lock` (session level) | PASS (red) | 1 failed: release at rollback | 2026-10-29 |
| extra x183-coalesce | APP | W | plant: `COALESCE(r.stdout, '')` (the r1 plant) | PASS (red) | 1 failed: `'' is None` | 2026-10-29 |
| extra x183-noretry / x183-ownerpolicy | APP | W | plants: retries skipped; plugins by `owner_policy_id` instead of `policy_plugin` | PASS (red) | 1 / 2 failed | 2026-10-29 |

#### Acceptance (TASK-183 row)

The functions work with only the TS §5.2 grants → -170 to -173, -225. One statement → -171. Chunks ≤ size and each result once → -172. Inserting N adds N → -173. Two sessions serialise and two scans don't → -174. S608 plus a planted f-string → -350.

### TASK-184


Tester: tester-m8, 2026-10-29. Full rigor. REQ-197 (3), REQ-199 (1)–(4); TS §2.1 L105, §4.5 L602, §4.4 L579, L583; #119, #120. Code under test: `bm/services/evaluator/scores.py` (impl-manager-m8b, `work/reports/TASK-184-impl.md`) over `repositories/results.py` (TASK-182). New test file: `manager/tests/test_scores_pg.py`. Plan rows: CHK-M8-180 to -184.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scores_pg.py` | **5/5 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 5 plants | 5/5 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-180 | APP | W | r1 | PASS | REQ-199 (1), on the REQ-198 fixture: A `HostScore(2,1,1,1,2/3)`, B (2,1,0,0,2/3), C (0,0,0,3,None) queued, D (2,0,0,0,1.0) re-evaluated FAIL→PASS, E (0,0,2,0,None) all ERROR; ordered by agent | 2026-10-29 |
| CHK-M8-181 | APP | W | r1 | PASS | REQ-199 (2): a late result → C (1,0,0,2,1.0); a re-evaluation → (0,1,0,2,0.0); another → ERROR, (0,0,1,2,None). Each next call reflects the change at once | 2026-10-29 |
| CHK-M8-182 | APP | W | r1 | PASS | REQ-199 (3): an unknown scan → `[]` | 2026-10-29 |
| CHK-M8-183 | APP | W | r1 | PASS | REQ-199 (4): the statement spy sees only `WITH … SELECT`, with no write word | 2026-10-29 |
| CHK-M8-184 | APP | W | r1 | PASS | REQ-197 (3): 200 random sets (seeded; 1–4 plugins, 1–3 hosts, random results, retries for missing plugins, up to 60 re-evaluation rows with random ids and times, some on pairs without results). `effective_results` and `effective()` (fed every row of those jobs plus unrelated rows from other scans) agree on code, detail, id, version, user and the original for every result | 2026-10-29 |
| extra x184-cache | APP | W | plant: scores memoised per scan | PASS (red) | 1 failed: "computed when read" | 2026-10-29 |
| extra x184-swap / x184-errors | APP | W | plants: passed and failed swapped; errors added to failed | PASS (red) | 2 / 2 failed | 2026-10-29 |
| CHK-M8-348 (property) | APP | W | plants in `results.py`: `reeval_id ASC`; `reevaluated_at DESC` | PASS (red) | 3 / 2 failed, including `test_sql_and_effective_agree_on_200_random_sets` (e.g. `(2,'cannot evaluate',3024) == (1,None,3091)`) | 2026-10-29 |

#### Acceptance (TASK-184 row)

REQ-199 (1)–(4) → -180 to -183; the REQ-197 (3) property on 200 random sets → -184, which goes red on both ordering plants.

### TASK-185


Tester: tester-m8, 2026-10-29. Full rigor. REQ-200 (1)–(9), REQ-201 (1)–(5), REQ-202 (2), REQ-204 (2); TS §4.5 L601, §2.2 L114, §5.2 L929–L938, L1005–L1006, §5.3 L1049; #12, #118 (a)–(h), #119. Rulings applied (2026-10-29): NULL stdout fails closed; "Re-evaluation fails closed on an unrecognised stored ERROR detail"; order: intake detail → unknown ERROR detail → NULL stdout → `classify()`. Code under test: `bm/services/evaluator/reevaluate.py` r1 over `bm/repositories/reeval.py` r1 (impl-manager-m8b, `work/reports/TASK-185-impl.md`, "Revision 1"). New test files: `manager/tests/test_reevaluate_pg.py` (own migrated container, so the audit chain check sees only this module's writes), `manager/tests/test_reevaluate_race_pg.py`. Plan rows: CHK-M8-190 to -201, -210 to -214, -222.

#### Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_reevaluate_pg.py tests/test_reevaluate_race_pg.py` | 30/38 passed, 8 failed: a **test bug** (mine): `make_job(state="succeeded")` is not a `scan_state` value (TS §5.2: `completed`) |
| r1 re-run | `pytest tests/test_reevaluate_pg.py` (the 8 failures were all in this file; the race file was 7/7 in r1) | **31/31 passed**, so **38/38** overall, 0 skipped, 0 containers left |
| all M8 | the 14 M8 test files together | **1,345/1,345 passed**, 0 skipped |
| plants | 16 plants (15 in one batch, plus the race form of -354) | 16/16 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on both files | clean |

#### Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-190 | APP | W | r1 re-run | PASS | REQ-200 (1): 6 results (PASS, FAIL, `stdout not numeric`, `oversize`, `runner_unavailable`, since-dropped) after an import (v2: P2 expected → `y`, P3 operator → `not_empty`, P6 dropped) → `ReevalResult(…, scan_policy_version=1, policy_version=2, rows_added=5, not_in_version=1)`. Rows: P1, P2, P3 → (0, None); P4 → (2, `oversize`), even though `empty` would PASS; P5 → (2, `runner_unavailable`); P6 → none; all v2 and user 4242 | 2026-10-29 |
| CHK-M8-191, -198 | APP | W | r1 re-run | PASS | REQ-200 (2), (9): `scan_result` checksums (parent and every partition), `scan` and `scan_job` are identical before and after; earlier `scan_result_reeval` rows are unchanged and 5 are appended; the statement spy sees no UPDATE/DELETE/TRUNCATE/MERGE (whole words) | 2026-10-29 |
| CHK-M8-192 | APP | W | r1 re-run | PASS | REQ-200 (3): after a second import (v3), the second run adds 5 more (10 in all). `effective_results` shows run 2's ids, v3 and user 4243 for every re-evaluated result (P1 now FAIL, original PASS beside it); the dropped P6 keeps its original | 2026-10-29 |
| CHK-M8-193 | APP | W | r1 re-run | PASS | REQ-200 (4): one entry with actor `user:4242`, action `scan.reevaluate`, target `scan:<id>`, detail exactly `{policy_id, scan_policy_version: 1, policy_version: 2, rows_added: 5, not_in_version: 1}`; `audit_log` +1 exactly, no `alert` key; `verify_chain` ok | 2026-10-29 |
| CHK-M8-194 | APP | W | r1 re-run | PASS | REQ-200 (5): a deleted policy → `PolicyDeleted`; an unknown id → `ScanNotFound` (the message carries no id). Neither writes a row or an audit entry; `wake` is not called | 2026-10-29 |
| CHK-M8-195 | APP | W | r1 re-run | PASS | REQ-200 (6): chunks forced to 2, the second `insert_reevals` raises after the first chunk really inserted → the exception propagates, with no row, no audit entry and no `wake` | 2026-10-29 |
| CHK-M8-196, -197 | APP | W | r1 re-run | PASS | REQ-200 (7): a scan with no results writes the audit entry (`rows_added` 0) and no row. (8): a disabled policy's scan → 5 rows | 2026-10-29 |
| CHK-M8-200 | APP | W | r1 re-run | PASS | `wake` runs exactly once, after commit (inside it, another session already sees the entry) | 2026-10-29 |
| CHK-M8-199, -201, r1 rows | APP | W | r1 re-run | PASS | 19 stored rows under `empty`. Intake details kept (`oversize`, `spool_overflow`, `runner_unavailable`, also with NULL stdout: the intake detail wins). An ERROR with NULL, `' Oversize '`, `'OVERSIZE'`, `'oversize '` or unknown detail → `cannot evaluate`, never PASS. NULL stdout with code 0 or 1 → `cannot evaluate`. Known details re-classified on the stored values: `timed out` (timed_out), `stdout truncated`, `not found` (127) stay ERROR; `cannot evaluate`/`stdout not numeric` with stdout `""` → PASS; FAIL `x` → FAIL. None raises | 2026-10-29 |
| CHK-M8-222 | APP | W | r1 re-run | PASS | REQ-202 (2): with the canary in stdout, stderr, expected and a pattern, caplog at DEBUG over a run, `effective_results` and a `PolicyDeleted` run: the canary is in no log message or args, no exception, no audit detail and no re-evaluation row; the details are only #112 constants. `reevaluate.py` holds no `logging`/`print(` | 2026-10-29 |
| CHK-M8-210 | APP | W | r1 | PASS | REQ-201 (1): A pauses after reading its definitions (v1, holding the lock); an import commits v2; B starts and waits on the advisory lock (`pg_locks` probe) and has no result; A is released. Both commit: A's 6 rows v1/FAIL, B's 6 rows v2/PASS, `min(B ids) > max(A ids)`; every effective verdict is B's (PASS, user 2, v2) | 2026-10-29 |
| CHK-M8-211 | APP | W | r1 | PASS | REQ-201 (2): an import committing after `lock_scan` → every row v2/PASS; after `current_definitions` → every row v1/FAIL; and between the first `FROM policy` statement and the rest → still consistent. No row records one version while using the other's definitions | 2026-10-29 |
| CHK-M8-212 | APP | W | r1 | PASS | REQ-201 (3): a result stored by another session after the first chunk was read and before the commit gets no row (`rows_added` 1); the next run includes it (2, the late one FAIL) | 2026-10-29 |
| CHK-M8-213 | APP | W | r1 | PASS | REQ-201 (4): 20,000 results with 4,000-byte stdout (80 MB if held at once) → `rows_added` 20,000; every insert ≤ 1,000 rows; peak `tracemalloc` < 64 MiB | 2026-10-29 |
| CHK-M8-214 | APP | W | r1 | PASS | REQ-201 (5): B on another scan completes (6 rows) while A is paused holding its own scan's lock | 2026-10-29 |
| CHK-M8-353 | APP | W | plant: an `UPDATE scan_result …` in the run | PASS (red) | 34 failed with `InsufficientPrivilege: permission denied for table scan_result`: the grant refuses it and the tests see the failure (G64, G65) | 2026-10-29 |
| CHK-M8-355 | APP | W | plant: intake step removed | PASS (red) | 6 failed: `oversize` and so on become PASS under `empty` (or `cannot evaluate` when stdout is NULL) | 2026-10-29 |
| CHK-M8-356 | APP | W | plant: rows for dropped plugins | PASS (red) | 5 failed: 6 rows, `rows_added` 6 | 2026-10-29 |
| CHK-M8-357 | APP | W | plant: deleted policy allowed | PASS (red) | 2 failed: DID NOT RAISE `PolicyDeleted` | 2026-10-29 |
| CHK-M8-359 | APP | W | plants: audit entry missing; written in its own earlier transaction | PASS (red) | 3 failed / 5 failed, including the fault row (the entry survived the fault) | 2026-10-29 |
| CHK-M8-360 (service) | APP | W | plant: all chunks merged into one | PASS (red) | 2 failed: the 20,000 row (20,000 > 1,000), the fault row | 2026-10-29 |
| CHK-M8-358 (race) | APP | W | plant: lock replaced by `concat(…)` | PASS (red) | 1 failed: "B is not waiting on the lock" | 2026-10-29 |
| CHK-M8-354 (race) | APP | W | plant: version read in its own statement and then used (two replacements) | PASS (red) | 1 failed: `test_import_inside_the_definitions_read_never_mixes_versions`, a row recording v1 with v2's PASS. (The batch's one-replacement variant left the version taken from the combined statement, so it changed nothing and stayed green, as expected; the repository half of -354 is red in TASK-183.) | 2026-10-29 |
| CHK-M8-362 (service) | APP | W | plant: `logging…warning("re-evaluating %s", row.stdout)` | PASS (red) | 3 failed: the canary row, the no-logging row, and the memory row (logging every stdout pushed the peak to 341 MB) | 2026-10-29 |
| r1 order swap | APP | W | plant: NULL stdout checked before intake | PASS (red) | 2 failed: NULL + `oversize`/`spool_overflow` → `cannot evaluate` | 2026-10-29 |
| r1 drop step 2 | APP | W | plant: the unknown-detail step off | PASS (red) | 5 failed: NULL, `' Oversize '`, `'OVERSIZE'`, `'oversize '` and unknown ERRORs PASS under `empty` | 2026-10-29 |
| r1 COALESCE | APP | W | plant: `COALESCE(r.stdout, '')` in the repository | PASS (red) | 2 failed: NULL-stdout PASS/FAIL rows become PASS | 2026-10-29 |
| extra x185-wake-early / x185-version | APP | W | plants: `wake()` inside the transaction; the scan's version recorded instead of the current one | PASS (red) | 1 / 4 failed | 2026-10-29 |

#### Acceptance (TASK-185 row)

REQ-200 (1)–(9) → -190 to -198 (and -199 to -201); REQ-201 (1)–(5) → -210 to -214; REQ-202 (2) → -222; REQ-204 (2) → -191, -198. Every security row (S: -353, -354, -355, -358, -359, -362) has a plant that went red. The coordinator's must-hold rows (NULL/unknown/case or whitespace intake values fail closed and never PASS; `timed out` re-classified; intake details kept; NULL stdout + intake detail keeps the intake detail) and both requested plants (order swap, drop step 2) are in the r1 rows.

### M8-gate


**Final (2026-10-29, after the CHK-M2-232 ruling):** G18 re-run on the final tree, `-n 0`, web build present: **10,228/10,228 passed, 0 failed, 0 errors, 0 skipped**, services coverage **98.50 %**. See "CHK-M2-232 fix" and "Environment note" at the end. The first run's results are kept below as the record.

Tester: tester-m8, 2026-10-29. Tree: worktree `Bitscan-m8`, branch `m8-evaluator` = main `67a6dfa` plus the uncommitted M8 files. Product: `bm/services/evaluator/{__init__,model,normalise,operators,evaluate,verdict,eval_spec,score,scores,reevaluate}.py`, `bm/repositories/results.py`, `bm/repositories/reeval.py` (r1). Tester: 14 test files plus `tests/m8/test-plan.md`. W runs use my own copy `/root/bstest-m8-base`, venv `/root/venv-m8` (hashed locks plus `-e` of the copy), `PYTHONPATH` pinned to the copy, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0` (free memory 2,294–2,808 MB, below the 3,000 MB `-n 2` floor). All of my containers were removed after each run (0 `m8t` containers left).

#### Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check manager` (whole tree, L) | PASS | "All checks passed!" (S608 and the `re` ban included). Plants: CHK-M8-320 (`TID251 re is banned`), -349 and -350 (`S608`), each exit 1 |
| G2 | `ruff format --check manager` (L) | PASS | 337 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager`, plus the same with `--platform linux` (L) | PASS | "Success: no issues found in 337 source files", both. Plant: an untyped `def _untyped(x)` in `evaluate.py` → `no-untyped-def`, exit 1 (W) |
| G4 | fresh `/root/venv-m8` from `pip install --require-hashes -r manager/requirements-dev.txt` (W) | PASS | install ok. `git diff 67a6dfa -- manager/requirements.txt manager/requirements-dev.txt manager/pyproject.toml` is empty (no new dependency) |
| G5 | services coverage in the G18 run (W) | PASS | **98.46 %** (4,853/4,929 lines) of `bm/services`, including `services/evaluator` at 99.42 % (340/342; only `eval_spec.py` L92–93 missed). Plant: 800 untested statements in `reevaluate.py` (sized from the clean report: ≥ 781 needed) → 4,853/5,732 = **84.67 %** < 85 %, and `--cov` itself reports "FAIL Required test coverage of 85.0% not reached" |
| G6 | `tests/test_openapi.py` in G18, and `git diff 67a6dfa -- manager/openapi.json` | PASS | green in G18; the diff is empty. Plant: a `POST /scans/{scan_id}/reevaluate` stub on the rebuild router → `test_committed_file_matches_a_fresh_export` and `test_module_command_writes_the_same_bytes` red |
| G34 | `tests/test_invariants_m3.py` in G18 | PASS | green. **G6 red, G34 green by design** (decisions row "M8 gate row G34: the planted violation corrected"): `POST /scans/{id}/reevaluate` is a TS §6.2 route, so the route walk allows it; with the stub planted, `test_invariants_m3.py` + `test_openapi.py` gave 37 passed, 2 failed (both G6). No route is proven by G6 plus the empty diffs `git diff 67a6dfa -- manager/openapi.json manager/bitscan_manager/api manager/bitscan_manager/db/migrations` |
| G18 | full manager suite, `pytest -n 0 --cov` (W) | **10,222 passed, 2 failed, 3 errors**, 0 skipped (`-rs` lists none), 41 min 59 s. See "G18 findings": the 3 errors and 1 failure are an environment gap (no web build in my copy), now fixed and re-run 7/7. The other failure is pre-existing and order-dependent, outside M8 |
| G62 | evaluator unit suite (7 files) | PASS | inside 1,345/1,345 (all M8 files) and inside G18 |
| G63 | `test_evaluator_property.py` | PASS | inside 1,345 and G18; at the gate I added `test_verdict_constructs_exactly_when_valid` (CHK-M8-364's G63 half): plant code set `(0,1,2,3)` → red `(3, None)` |
| G64 | `test_results_repo_pg.py`, `test_reeval_repo_pg.py`, `test_scores_pg.py`, `test_reevaluate_pg.py`, `test_reevaluate_race_pg.py` | PASS | 15 + 40 + 5 + 31 + 7 = 98/98 (W), and inside G18 |
| G65 | `test_security_m8.py` | PASS | inside 1,345 and G18 |

All M8 files together (W, `-n 0`, before G18): **1,345/1,345 passed**, 0 failed, 0 errors, 0 skipped.

#### G18 findings

| Test | Result | Diagnosis | Re-run |
| --- | --- | --- | --- |
| `test_security_m5.py` (3 tests, ERROR at setup: `live` fixture) and `test_readme_m5_walk_linux.py::test_the_m5_readme_sections_behave_as_written` (FAILED) | environment | "the web UI build is missing: run `npm run build` in web/". `manager/bitscan_manager/webui/` is git-ignored and built by CI (`manager.yml` "npm run build"); my copy had none. Not M8 (`git diff 67a6dfa -- web` is empty) | Built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`, never in the worktree), copied into `/root/bstest-m8-base` only: **7/7 passed** (both files) |
| `test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes` (CHK-M2-232) | FAILED, pre-existing, order-dependent | In G18 it failed at L425 (`shipper.refusing()` still True after 5 `run_once` on recovery). The log shows the shipper draining the session database's ~3,000 audit entries 500 at a time: 5 cycles can't drain a database the whole suite wrote to, so the outage never clears. Run alone it fails earlier (L417: 200 instead of 503); inside its own file it passes (31/31). **On a clean main `67a6dfa` copy it fails alone the same way (2/2 runs, L417, `assert 200 == 503`).** M8 adds audit rows (re-evaluation entries) to the shared session database, which likely pushes the full-suite volume past what 5 cycles drain. M8 does not touch the shipper, the users routes or this test | Not fixed: it's an M2 test (owner tester) whose fixture shares the session database. **Needs a ruling** (below) |

#### M8 mutation table (CHK-M8-320 to -364)

Every row was planted in a throwaway copy (`/root/bstest-m8-mut-<id>`, removed after each) and went red on its named gate. Per-task evidence is in the TASK reports; rows run at the gate are marked **gate**.

| CHK | Red in | Source |
| --- | --- | --- |
| 320 S | G1 (TID251) and G62 (`(?=x)` rows; the full file hangs on `re` backtracking, timeout exit 124) | TASK-177 |
| 321, 322 | G62 (multiline, `foo`/`xfoo`) | TASK-177 |
| 323 S | G62 (18 `not_regex` rows) | TASK-177 |
| 324, 325 | G62 (CRLF rows; U+00A0 and Unicode-space rows) | TASK-176 |
| 326, 327, 328, 329 S | G62 | TASK-177 |
| 330, 331, 332, 333, 334 S, 335 S, 336 | G62 (and G63 for 330, 333) | TASK-178 |
| 337 | G62 (11 rows) | TASK-176 |
| 338 S | G63 (`test_classify_and_evaluate_are_total`), G62 (`KeyError` rows) | TASK-177, 178 |
| 339 S, 340, 341 S, 342 S, 343 | G62 | TASK-179 |
| 344 S, 345 S | G62 | TASK-180 |
| 346, 347 | G62 (G63 property too) | TASK-181 |
| 348 S | G62 (unit, 9 rows), G64 (SQL rows and the 200-set property) | TASK-181, 182, 184 |
| 349 S, 350 S | G1 (S608) | TASK-182, 183 |
| 351 | G64 (EXPLAIN `Actual Loops` row) | TASK-182 |
| 352 | G64 (host B, duplicate and retry rows) | TASK-182 |
| 353 S | G64 and G65 (34 tests see `InsufficientPrivilege`) | TASK-185 |
| 354 S | G64 (one-statement spy, TASK-183) and the race row `test_import_inside_the_definitions_read_never_mixes_versions` (TASK-185) | TASK-183, 185 |
| 355 S, 356, 357 | G64 | TASK-185 |
| 358 S | G64 (TASK-183 lock row; TASK-185 race row "B is not waiting on the lock") | TASK-183, 185 |
| 359 S | G64 (missing: 3 rows; own transaction: 5 rows, including the fault row) | TASK-185 |
| 360 | G64 (chunk rows; 20,000-result row) | TASK-183, 185 |
| 361 S | G65 (static and runtime import graphs) | TASK-178 |
| 362 S | G62 (no-log row) and G65 (canary, no-logging rows) | TASK-178, 185 |
| 363 S | G62 and G65 (canary detail rows, 69 failed) | TASK-178 |
| 364 | G62 (`Verdict(3, None)`), **gate**: G63 (`test_verdict_constructs_exactly_when_valid`) | TASK-176; gate |

Gate-only plants: G3 untyped function (red), G5 800-statement plant (red, 84.67 %), G6 route stub (red), G34 route stub (green by design, see G34).

45/45 table rows red; 22/22 security rows red.

#### NOT RUN at the M8 gate (by design)

- TS §8.3 Integration "verdict uses the queued `eval_spec` after a catalog change" end to end through intake: **M9**. M8 proves the API-level half: the pure modules take a `PluginSpec`, and the import graph shows no catalog access (CHK-M8-220).
- End to end scan → results: **M11** nightly. Load tests: deferred by the user.
- CI (GitHub Actions): not run here (no push).

#### Ruling needed

`test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes` fails in the full single-worker run, and alone (also on clean main `67a6dfa`). It passes in its own file. Options:
- (a) Accept it as a pre-existing M2 test-isolation defect, outside M8, and open a test task. For example, give the `env` fixture its own migrated server, or drain until `refusing()` is False with a bound, rather than exactly 5 cycles.
- (b) Fix it now as a test-only change. I own test files, but this is M2's test, so I'd want your word first.
- (c) Re-run G18 with `-n 2` once memory allows, to see whether a different worker split avoids it. That would hide rather than fix it, so not recommended.

The gate verdict for the M8 gates themselves is PASS: G1–G6, G34, G62–G65, the mutation table, 0 skipped.

#### CHK-M2-232 fix (ruling: option (b), `work/decisions.md` "CHK-M2-232 test isolation fix")

Test-only change to `manager/tests/test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes`. No product file changed.

**Cause, found by probe in a throwaway copy:**
- *Alone on a fresh database:* `audit_log` was empty when the test began. `env.admin()` and `env.user()` insert rows directly and write no audit entry, so the shipper had nothing to deliver, `run_once()` never failed, and `outage_since` stayed None. Every call then returned 200, not 503 (L417). That is why it also failed alone on clean `67a6dfa`.
- *Full suite:* the shared session database held about 3,000 entries, and each cycle reads at most `BATCH` (500). Five fixed recovery cycles could not drain it, so `refusing()` stayed True (L425).

**Fix (assertions kept exactly):**
- Before the outage, the test makes one audited change through the API (`POST /users`, 201), so there is always something to deliver.
- After the outage, it asserts `refusing()` is still False before 15 minutes.
- The recovery step now drains until `refusing()` is False, bounded by `count(audit_log) // BATCH + 5` cycles. Hitting the bound fails the test with "not drained in N cycles".
- Kept unchanged: 200 at 14:59; 503 `audit_sink_unavailable` for every method at 15:00 with unchanged state; `/api-tokens` still 200 during the outage; cleared only once drained, then 200.

| Check | Command (W) | Result |
| --- | --- | --- |
| alone | `pytest "tests/test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes"`, 3 runs | 3/3 passed (1/1 each) |
| its file | `pytest tests/test_users_api_pg.py` | 31/31 passed |
| full suite, single worker | G18 re-run, `-n 0` | passed (inside 10,228/10,228) |
| `-n 2` | `pytest -n 2 tests/test_users_api_pg.py tests/test_audit_append_pg.py tests/test_shipper_pg.py tests/test_reevaluate_pg.py tests/test_results_repo_pg.py` (3,425 MB free) | 97/97 passed |
| plant: outage refusal disabled (`refusing()` returns False) | the test alone | red: 200 where 503 expected |
| plant: refusal never clears (the drained branch disabled) | the test alone | red: "not drained in 5 cycles" (the bound) |
| static | ruff, ruff format, mypy --strict on the file | clean |

Note: the full `-n 2` G18 was not run. Free memory was 2,405 MB when G18 started, below the 3,000 MB floor, so G18 ran single-worker as you agreed. The `-n 2` row above runs the fixed file with the heaviest audit and PostgreSQL neighbours.

#### Environment note (web build)

`manager/bitscan_manager/webui/` is git-ignored and built by CI (`manager.yml`: `npm ci --ignore-scripts`, `npm run build`). The M5 web tests (`test_security_m5.py`, `test_readme_m5_walk_linux.py`) fail closed under `CI=true` without it. For the gate I built it outside the worktree: a temp copy of `web/` (`C:\Users\kaiquan.koh\AppData\Local\Temp\m8t-web`), `npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`. I copied the result into my WSL copy only. M8 changes no web file (`git diff 67a6dfa -- web` is empty).

#### G18 final row

| Gate | Command | Result |
| --- | --- | --- |
| G18 | full manager suite, `pytest -n 0 -rs --cov` on the final tree (with the CHK-M2-232 fix), web build present, `CI=true` | **10,228/10,228 passed, 0 failed, 0 errors, 0 skipped** (1 h 20 min); G5 98.50 % (4,855/4,929); 0 containers left |

The tail of the M8 test-file list is also updated: `test_eval_spec.py` gained the 36-character non-hex uuid row (102/102; `eval_spec.py` 100 %).
