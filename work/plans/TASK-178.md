# TASK-178 plan: `classify()` and `evaluate()` (with the TASK-176 interface and the TASK-177 operators)

Planner: planner-m8, 2026-10-29. Design notes D1 and D2 in `work/tasks.md` ("M8 design notes"). Requirements REQ-186 to REQ-194, REQ-205. Open questions #11, #12, #13 (agreed), #112 to #116 (recommended answers). `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §4.5 L587: "The manager evaluates each result as it arrives, against the `eval_spec` recorded when the job was queued (plugin name, Operator, ExpectedResult)".
- TS §4.5 L589–L593: 0 PASS "Comparison is true"; 1 FAIL "Comparison is false"; "Anything else (stored as 2)" ERROR: "Timeout; exit code 126/127 (cannot run / not found) or ≥ 128 (killed by signal); stdout truncated at 64 KB; numeric operator but stdout is not a number; runner error (`spool_overflow`, `runner_unavailable`); output over the caps".
- TS §4.5 L597: "CRLF becomes LF and leading/trailing whitespace is trimmed from stdout and expected result before comparing; comparison is case-sensitive."
- TS §4.5 L598: "the command's own exit code does not decide PASS/FAIL (`grep` exiting 1 on no match is normal); only the ERROR cases above apply."
- TS §4.5 L600: "one pure function `evaluate(operator, expected, stdout, exit_code, timed_out, truncated) -> 0 | 1 | 2`, with unit tests for every operator and every ERROR case. Regex uses RE2 (linear time) so a bad pattern cannot hang the manager."
- SR §2.4 SR L134: `regex` PASS when stdout "matches the pattern (multiline; use `^`/`$` to anchor)". SR L153: "Numbers are decimal integers or floats with an optional sign; the whole trimmed stdout must be one number."

## 2. TASK-176 interface (`bm/services/evaluator/model.py`, `normalise.py`)

```python
# model.py
from typing import Final, Literal, Protocol
from enum import StrEnum
from uuid import UUID

Operator = Literal["equals", "not_equals", "contains", "not_contains",
                   "regex", "not_regex", "eq", "ne", "gt", "ge", "lt", "le",
                   "empty", "not_empty"]          # == importer.model.OPERATORS, same order (tested)
VerdictCode = Literal[0, 1, 2]
PASS: Final[VerdictCode] = 0
FAIL: Final[VerdictCode] = 1
ERROR: Final[VerdictCode] = 2

class Detail(StrEnum):                            # #112 (a); the stored eval_detail text
    OVERSIZE = "oversize"
    SPOOL_OVERFLOW = "spool_overflow"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    TIMED_OUT = "timed out"
    NO_EXIT_CODE = "no exit code"
    CANNOT_RUN = "cannot run"
    NOT_FOUND = "not found"
    KILLED_BY_SIGNAL = "killed by signal"
    STDOUT_TRUNCATED = "stdout truncated"
    CANNOT_EVALUATE = "cannot evaluate"
    STDOUT_NOT_NUMERIC = "stdout not numeric"

INTAKE_DETAILS: Final = frozenset({Detail.OVERSIZE, Detail.SPOOL_OVERFLOW, Detail.RUNNER_UNAVAILABLE})  # #12
STDOUT_CAP: Final = 65_536   # UTF-8 bytes (#116, #57)
STDERR_CAP: Final = 16_384

@dataclass(frozen=True, slots=True)
class Verdict:
    code: VerdictCode
    detail: Detail | None
    # __post_init__: code in (0, 1, 2); detail is None exactly when code != 2;
    # detail, when set, is a Detail member. Raises ValueError otherwise.

@dataclass(frozen=True, slots=True)
class PluginSpec:            # one eval_spec entry (#117); built and parsed in TASK-180
    plugin_uuid: UUID
    name: str
    operator: str            # str, not Operator: data from JSONB; unknown -> cannot evaluate
    expected: str

class ResultLike(Protocol):  # the six result fields of the M3 ResultItem, read-only
    @property
    def exit_code(self) -> int | None: ...
    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def truncated(self) -> bool: ...
    @property
    def error(self) -> str | None: ...
```

```python
# normalise.py
WHITESPACE: Final = " \t\n\v\f\r"          # #115: C-locale ASCII whitespace

def normalise(text: str) -> str:
    """CRLF -> LF, then trim WHITESPACE at both ends (TS §4.5 L597)."""
    return text.replace("\r\n", "\n").strip(WHITESPACE)
```

`Operator` is a `Literal` so callers that know the value (tests, M9's builder) get type checking; the evaluation functions take `operator: str` because the value comes from JSONB and must be total (#112 (d)).

## 3. TASK-177 operators (`bm/services/evaluator/operators.py`)

```python
class NotNumeric(Exception): ...      # stdout is not one #13 number
class CannotEvaluate(Exception): ...  # the comparison cannot be made (#112 (a))

def compare(operator: str, expected: str, stdout: str) -> bool:
    """True when the comparison holds. Both strings are already normalised.
    Raises NotNumeric or CannotEvaluate; never anything else."""
```

| Operator | True when | Signals |
| --- | --- | --- |
| `equals` / `not_equals` | `stdout == expected` / `!=` | none |
| `contains` / `not_contains` | `expected in stdout` / `not in` | none |
| `regex` / `not_regex` | `values.compile_pattern(expected).search(stdout) is not None` / `is None` | `values.PatternError` → `CannotEvaluate`; `UnicodeEncodeError` from `search` (lone surrogate) → `CannotEvaluate` |
| `eq` `ne` `gt` `ge` `lt` `le` | `values.parse_number(stdout) <op> values.parse_number(expected)` as `Decimal` | expected not a number → `CannotEvaluate` (checked first); stdout not a number → `NotNumeric` |
| `empty` / `not_empty` | `stdout == ""` / `!= ""` | none |
| anything else | — | `CannotEvaluate` |

- A dispatch table `dict[str, Callable[[str, str], bool]]` keyed by the importer's tuples (`importer.model.NUMERIC_OPERATORS` etc.); a test asserts its keys equal `importer.model.OPERATORS`.
- Never `int()` or `float()` on stdout (the 4,300-digit `int` limit and float rounding; REQ-190 (2)). `Decimal` comparison is exact at any length.
- `compile_pattern` is called per evaluation. An `functools.lru_cache(maxsize=1024)` around it is allowed (patterns are catalog values, bounded per job), since the compiled object is immutable; it must not cache failures as successes.
- The `(?m)` flag and silenced RE2 logging come from `values.compile_pattern`; this module never calls `re2` directly (a spy test).

## 4. TASK-178 `classify()` and `evaluate()` (`bm/services/evaluator/evaluate.py`)

```python
def classify(operator: str, expected: str, stdout: str,
             exit_code: int | None, timed_out: bool, truncated: bool) -> Verdict: ...

def evaluate(operator: str, expected: str, stdout: str,
             exit_code: int | None, timed_out: bool, truncated: bool) -> VerdictCode:
    return classify(operator, expected, stdout, exit_code, timed_out, truncated).code
```

`classify`, in this order (#112 (c); the first match returns):

| Step | Condition | Verdict |
| --- | --- | --- |
| 1 | `timed_out` | ERROR `timed out` |
| 2 | `exit_code is None` | ERROR `no exit code` (#114) |
| 3 | `exit_code == 126` | ERROR `cannot run` |
| 4 | `exit_code == 127` | ERROR `not found` |
| 5 | `exit_code >= 128 or exit_code < 0` | ERROR `killed by signal` (#114) |
| 6 | `truncated` | ERROR `stdout truncated` (#113) |
| 7 | `compare(operator, normalise(expected), normalise(stdout))` raises `CannotEvaluate` | ERROR `cannot evaluate` |
| 8 | … raises `NotNumeric` | ERROR `stdout not numeric` |
| 9 | … returns True / False | PASS / FAIL |

`oversize` and the runner errors are not here: `result_verdict()` (TASK-179) decides them first (#12).

Edge cases the tests pin:
- Exit 0, 1, 2, 125: never decide (REQ-192 (1)); exit 1 with empty stdout under `empty` is PASS (the `grep` case).
- A `bool` passed as `exit_code` is an `int` in Python; the type is `int | None` and callers pass the stored integer. No special case.
- `truncated` makes every operator ERROR, even `contains` with the expected text inside the kept 64 KB (L593 lists the case without an operator exception).
- The expected value is normalised too (L597), so an expected stored with a trailing CRLF (`&#13;&#10;` in the file) still compares.
- Totality: steps 1–6 are comparisons on the declared types; step 7 can only raise the two signals (§3). No bare `except`. The property test (REQ-186 (3)) generates unknown operators, lone surrogates in every string, and exit codes over the full 32-bit range and None.
- Purity: no import of `logging`, `db`, `repositories`, `api`, `psycopg` (REQ-202); no clock; no module state other than the `lru_cache`.

## 5. TASK-179 `result_verdict()` (`bm/services/evaluator/verdict.py`)

```python
def utf8_size(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))   # a lone surrogate counts 3 bytes, never raises

def over_caps(stdout: str, stderr: str) -> bool:
    return utf8_size(stdout) > STDOUT_CAP or utf8_size(stderr) > STDERR_CAP

def result_verdict(spec: PluginSpec, result: ResultLike) -> Verdict:
    if over_caps(result.stdout, result.stderr):
        return Verdict(ERROR, Detail.OVERSIZE)
    if result.error == "spool_overflow":
        return Verdict(ERROR, Detail.SPOOL_OVERFLOW)
    if result.error == "runner_unavailable":
        return Verdict(ERROR, Detail.RUNNER_UNAVAILABLE)
    if result.error is not None:              # outside the contract; total anyway
        return Verdict(ERROR, Detail.CANNOT_EVALUATE)
    return classify(spec.operator, spec.expected, result.stdout,
                    result.exit_code, result.timed_out, result.truncated)
```

- `utf8_size` stops early is not needed: the result batch is at most 1.5 MiB (TS §6.3 L1138), so encoding one string is bounded.
- What intake stores for an `oversize` result (#116 (d)) is M9's code; this module only decides the verdict.

## 6. Tests the plan expects (tester-owned; for orientation)

`test_evaluator_model.py`, `test_evaluator_normalise.py`, `test_evaluator_operators.py`, `test_evaluate.py`, `test_evaluator_verdict.py`, `test_evaluator_property.py` (G62, G63). CRLF inputs are in-code literals. Mutation rows CHK-M8-320 to -343, -361 to -364 target these modules.

## 7. Size

model.py about 100 lines, normalise.py about 15, operators.py about 110, evaluate.py about 60, verdict.py about 45. If `operators.py` grows past 200, the numeric table moves to `operators_numeric.py` (one task id).
