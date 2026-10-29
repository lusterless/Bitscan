# TASK-178 IMPL: `classify()` and `evaluate()`

Implementer: impl-manager-m8. REQ-186, REQ-192, REQ-193, REQ-205. Risk high. Plan: `work/plans/TASK-178.md` §4 (design note D1). Spec: TS §4.5 L587–L600; SR §2.4 (SR L145–L153), SR §1.1 L87. Answers applied: #12, #112 (b), (c), (d), #113, #114.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/evaluate.py` (new, 88 lines / 77 non-blank) | `classify()`, `evaluate()`, private `_run_error()` |

Size: 88 lines, against an estimate of 60 to 100. No other file was changed.

## Interface (the plan's §4; the `evaluate` signature is exactly TS §4.5 L600)

```python
def classify(operator: str, expected: str, stdout: str,
             exit_code: int | None, timed_out: bool, truncated: bool) -> Verdict
def evaluate(operator: str, expected: str, stdout: str,
             exit_code: int | None, timed_out: bool, truncated: bool) -> VerdictCode
    # == classify(...).code
```

## How each acceptance point is met

- **Order (#112 (c), D1):** `_run_error` runs these checks in order, and the first match returns:
  1. `timed_out` → `timed out`;
  2. `exit_code is None` → `no exit code`;
  3. `== 126` → `cannot run`;
  4. `== 127` → `not found`;
  5. `>= 128 or < 0` → `killed by signal`;
  6. `truncated` → `stdout truncated`.

  Only then are both strings normalised and passed to `operators.compare()`:
  - `CannotEvaluate` → `cannot evaluate`;
  - `NotNumeric` → `stdout not numeric`;
  - True / False → PASS / FAIL with detail None.

  Every ERROR check therefore runs before any comparison.
- **Exit codes never decide otherwise (REQ-192 (1), (3)):** codes 0 to 125 reach the comparison unchanged. Exit 1 with empty stdout under `empty` is PASS (the `grep` case).
- **`truncated` (#113):** ERROR for every operator, the unknown ones included, because it is checked before `compare`.
- **Totality:** there is no bare or broad `except`. Steps 1 to 6 are comparisons on the declared types. `normalise` is `str.replace` and `str.strip`, which never raise on any `str`, lone surrogates included. `compare` raises only the two signals (TASK-177), and both are caught. `Verdict` construction can't fail, since every code and detail pair built here meets the invariant.
- **Purity (REQ-186 (4), REQ-202):** the module imports only `typing` and the three evaluator modules. There is no `logging`, db, repositories, api, psycopg or clock, and no module state beyond three `Final` ints. No message or detail carries input: every detail is a `Detail` constant.

## Scratch check (outside the tree, `/tmp/m8-176-scratch/check178.py`, the worktree's own venv; not a test)

All of these hold:
- REQ-186 (2): `inspect.signature(evaluate)` has exactly `operator, expected, stdout, exit_code, timed_out, truncated`.
- REQ-192:
  - (1): exits 0, 1, 2 and 125 are PASS; 126, 127, 128, 255, 256, −1 and None are ERROR, each with its detail;
  - (2): `timed_out` gives `timed out`, and `truncated` gives `stdout truncated` for all 14 operators and `bogus`;
  - (3): the `grep` row is PASS;
  - (4): `EQUALS`, `equal` and `""` give `cannot evaluate`.
- REQ-193 (2):
  - 137 + timed out + truncated gives `timed out`;
  - 127 + truncated gives `not found`;
  - truncated + non-numeric gives `stdout truncated`.
- REQ-187 (3), (5) and REQ-190 (4): the case difference is FAIL; expected `x\r\n` against `x` is PASS; `" 42\r\n"` with `eq 42` is PASS.
- REQ-205 (1): all four SR §1.1 rows give 0, 1, 0, 1.
- Totality sweep, 20,000 random inputs (seeded), drawn from:
  - the 14 operators plus `""`, `EQ`, a lone surrogate and `regexx`;
  - strings over an alphabet with CR, LF, U+00A0, lone surrogates and regex metacharacters;
  - exit codes from −2³¹ to 2³¹−1, small values around the boundaries, and None;
  - random flags.

  It found no exception. Every code was in {0, 1, 2}, every detail was None exactly when the code was 0 or 1, `evaluate == classify().code`, and repeat calls were equal. Nothing went to stderr, and no log record was emitted at DEBUG on the root logger.

## Static gates (Windows, `Bitscan-m8\manager\.venv`)

- `ruff check manager`: all checks passed.
- `ruff format --check manager`: 319 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 319 files.
- The same with `--platform linux`: no issues in 319 files.

## Plants for the tester (rows aimed at TASK-178)

- **CHK-M8-330:** in `classify`, `if exit_code == 1: return Verdict(FAIL, None)` before `compare`. Red row: the `grep` row.
- **CHK-M8-331:** `exit_code > _SIGNAL_MIN`. Red row: 128.
- **CHK-M8-332:** delete the 126 or 127 branch. Red rows: 126 / 127, which fall through to PASS.
- **CHK-M8-333:**
  - drop `or exit_code < 0`, which makes −1 PASS;
  - or replace the None branch with `exit_code = exit_code or 0`, which makes None PASS. The `>=` on None would raise, so the plant has to coerce.
- **CHK-M8-334 / -335:** delete the `timed_out` / `truncated` branch.
- **CHK-M8-336:** move the `truncated` check to the top. Red row: 137 + timed out + truncated gives `stdout truncated`.
- **CHK-M8-338 (classify half):** catch only `NotNumeric`. An unknown operator then raises `CannotEvaluate` out of `classify` (G63).
- **CHK-M8-361:** add `from bitscan_manager.repositories import catalog` (import graph, G65).
- **CHK-M8-362:** `logging.getLogger(__name__).debug("stdout=%s", stdout)` in `classify`; or `raise ValueError(stdout)`.
- **CHK-M8-363:** this needs `Detail` widened or bypassed, because `Verdict` refuses a non-`Detail` detail. Plant `Verdict(ERROR, Detail.STDOUT_NOT_NUMERIC)` → `Verdict.__new__` plus `object.__setattr__(v, "detail", "stdout not numeric: " + stdout)`. Or, simpler, plant in `Verdict.__post_init__` by removing the isinstance check and building `"stdout not numeric: " + stdout` here. The G62 and G65 canaries must see it.
- Extra row: skip `normalise(expected)` (normalise only stdout). Red row: expected `x\r\n` against `x`.
