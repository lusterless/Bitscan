# TASK-176 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-187, REQ-193 (4), REQ-202 (model and normaliser part); TS §4.5 L589–L593, L597, L599; SR §2.4; #112 (a), #115, #116 (a). Code under test: `bm/services/evaluator/__init__.py`, `model.py`, `normalise.py` (impl-manager-m8, `work/reports/TASK-176-impl.md`). New test files: `manager/tests/test_evaluator_model.py`, `manager/tests/test_evaluator_normalise.py`. Plan rows: CHK-M8-001 to -014 (`tests/m8/test-plan.md`).

## Ruling applied (lead, 2026-10-29, `work/decisions.md` "Normaliser: one-pass CRLF → LF")

My first run found that `normalise` is **not idempotent**. hypothesis gave `s = "\x1c\r\r\n\x1c"`: `normalise(s) = "\x1c\r\n\x1c"`, and normalising that again gives `"\x1c\n\x1c"`. The simplest case is `"a\r\r\nb"` → `"a\r\nb"` → `"a\nb"`. **The impl report's "idempotent by construction" is wrong**; the reviewer should note it. The ruling picked option (b): keep the one-pass replace (TS §4.5 L597, "CRLF becomes LF"). Idempotence and "no CRLF survives" are claimed only for inputs with no CR right before a CRLF. The rows `"a\r\r\nb"` → `"a\r\nb"`, `"a\r\nb"` → `"a\nb"` and `"a\rb"` unchanged are must-hold. The planner narrows the REQ-187 (2) wording.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_evaluator_model.py tests/test_evaluator_normalise.py` | 99/101 passed, 2 failed (`test_normalise_is_idempotent`, `test_trim_set_and_interior_are_exact`: the conflict above), 0 errors, 0 skipped |
| r1 (after the ruling) | same, properties narrowed, `test_one_pass_crlf_rows` added | **102/102 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 4 plants in `/root/bstest-m8-mut-<id>` (removed after each), same two files | 4/4 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on both test files (worktree venv) | clean |

## Report rows (tests/m8/report.md)

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

## Acceptance (TASK-176 row)

- `Operator` values equal `importer.model.OPERATORS` in order → CHK-M8-001.
- `Verdict(0, Detail.TIMED_OUT)`, `Verdict(2, None)`, `Verdict(3, None)` raise → CHK-M8-005 (and more).
- `Detail` is exactly the eleven #112 values → CHK-M8-003.
- The REQ-187 table holds → CHK-M8-010 (REQ-187 (3) and (5) go through `classify`, so they are tested in TASK-178).
- A `ResultItem` type-checks as `ResultLike` under `mypy --strict` → CHK-M8-007.
- REQ-187 (2) as narrowed by the ruling → CHK-M8-012.

## Notes

- The stricter `type(code) is int` (bool refused) is confirmed by the `True`/`False` rows.
- The normaliser's one-pass behaviour on `"\r\r\n"` is now pinned by must-hold rows. A future change to repeat the replace until no CRLF is left would turn `test_one_pass_crlf_rows` red, and that is intended.
