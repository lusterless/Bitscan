# TASK-176 IMPL: evaluator model and normaliser (the interface)

Implementer: impl-manager-m8. REQ-187, REQ-193, REQ-202. Risk high. Plan: `work/plans/TASK-178.md` §2. Spec: TS §4.5 L589–L593, L597, L599; §5.2 (`eval_detail`); SR §2.4. Answers applied: #12, #112 (a), #115, #116 (a), (b), #117 (shape of `PluginSpec`).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/__init__.py` (new, 5 lines) | Docstring only. Exports nothing. |
| `manager/bitscan_manager/services/evaluator/model.py` (new, 115 lines / 94 non-blank) | `Operator`, `VerdictCode`, `PASS`/`FAIL`/`ERROR`, `Detail`, `INTAKE_DETAILS`, `STDOUT_CAP`/`STDERR_CAP`, `Verdict`, `PluginSpec`, `ResultLike` |
| `manager/bitscan_manager/services/evaluator/normalise.py` (new, 17 lines / 12 non-blank) | `WHITESPACE`, `normalise()` |

Size: 137 lines in total, against an estimate of 130. Most of `model.py` is the 14-line `Operator` literal (one value per line, the ruff format layout) and the protocol's six properties. No file outside the task's list was changed.

## Interface (exactly as the plan's §2)

```python
Operator = Literal["equals", "not_equals", "contains", "not_contains", "regex", "not_regex",
                   "eq", "ne", "gt", "ge", "lt", "le", "empty", "not_empty"]
VerdictCode = Literal[0, 1, 2]; PASS = 0; FAIL = 1; ERROR = 2      # all Final[VerdictCode]
class Detail(StrEnum): OVERSIZE="oversize", SPOOL_OVERFLOW="spool_overflow",
    RUNNER_UNAVAILABLE="runner_unavailable", TIMED_OUT="timed out", NO_EXIT_CODE="no exit code",
    CANNOT_RUN="cannot run", NOT_FOUND="not found", KILLED_BY_SIGNAL="killed by signal",
    STDOUT_TRUNCATED="stdout truncated", CANNOT_EVALUATE="cannot evaluate",
    STDOUT_NOT_NUMERIC="stdout not numeric"
INTAKE_DETAILS: frozenset[Detail] = {OVERSIZE, SPOOL_OVERFLOW, RUNNER_UNAVAILABLE}
STDOUT_CAP = 65_536; STDERR_CAP = 16_384                          # UTF-8 bytes, "strictly over"
@dataclass(frozen=True, slots=True) class Verdict: code: VerdictCode; detail: Detail | None
@dataclass(frozen=True, slots=True) class PluginSpec: plugin_uuid: UUID; name: str; operator: str; expected: str
class ResultLike(Protocol): read-only exit_code: int | None, stdout: str, stderr: str,
    timed_out: bool, truncated: bool, error: str | None
WHITESPACE = " \t\n\v\f\r"
def normalise(text: str) -> str: return text.replace("\r\n", "\n").strip(WHITESPACE)
```

## How each acceptance point is met

- **`Operator` equals `importer.model.OPERATORS` in order:** the literal is written in the importer's tuple order (text, regex, numeric, presence). Scratch check: `typing.get_args(Operator) == OPERATORS` holds. It is a separate `Literal` (a `Literal` cannot be built from a runtime tuple); the tester's equality test is what keeps the two in step.
- **`Verdict` invariant (REQ-193 (4)):** `__post_init__` raises `ValueError` (fixed text, no input quoted) when:
  - the code is not an `int` of value 0, 1 or 2. `type(code) is int` also refuses `True`/`False`, so `Verdict(True, None)` is refused rather than stored as 1. That is stricter than the plan's "code in (0, 1, 2)"; no caller passes a bool;
  - the code is 2 and the detail is not a `Detail` member (None, or a plain `str` such as `"oversize"`, are refused);
  - the code is 0 or 1 and the detail is not None.
  - Scratch check: `Verdict(0, TIMED_OUT)`, `Verdict(1, OVERSIZE)`, `Verdict(2, None)`, `Verdict(3, None)`, `Verdict(-1, None)`, `Verdict(True, None)` and `Verdict(2, "oversize")` all raise; `Verdict(0, None)`, `Verdict(1, None)` and `Verdict(2, Detail.OVERSIZE)` are accepted.
- **`Detail` is exactly the eleven #112 values**, in the #112 (c) order. Scratch check: the list of values equals the #112 list.
- **REQ-187 normaliser table:**
  - `normalise` replaces every CRLF with LF first, then strips only `WHITESPACE` (space, tab, LF, VT, FF, CR) at both ends. Nothing else changes.
  - Scratch check: `"install ok installed\r\n"` and `"\r\n  install ok installed \n"` give `"install ok installed"`; `"a\r\nb"` gives `"a\nb"`; `"a\rb"` is unchanged; `" x"` and `"x "` keep U+00A0 and U+2003; `"\v\fx\t"` gives `"x"`.
  - **Not idempotent (correction, r0 doc fix).** The replacement is one pass of `str.replace("\r\n", "\n")`, the spec's literal rule (TS §4.5 L597; decisions row "Normaliser: one-pass CRLF → LF"). A CR directly before a CRLF therefore forms a new CRLF:
    - `normalise("a\r\r\nb") == "a\r\nb"`;
    - `normalise("a\r\nb") == "a\nb"`.

    So `normalise(normalise(s)) != normalise(s)` for such inputs, and a REQ-187 (2) idempotence property must exclude a CR before CRLF (or be stated over the inputs where it holds). The edge trim alone is idempotent. The code stays as built. The `normalise.py` docstring makes no idempotence claim.
- **`ResultItem` type-checks as `ResultLike` under `mypy --strict`:** scratch check outside the tree (`/tmp/m8-176-scratch/typecheck176.py`, passing an `api.agent.schemas.ResultItem` to a `ResultLike` parameter) reports no issues. `ResultItem.error` is `Literal["spool_overflow", "runner_unavailable"] | None`, which a read-only `str | None` property accepts.
- **REQ-202 purity:** `model.py` imports only `dataclasses`, `enum`, `typing` and `uuid`; `normalise.py` imports only `typing`. Neither imports logging, db, repositories, api, psycopg or the importer.

## Static gates (Windows)

This worktree has no `manager/.venv`, so I ran the tools from `Bitscan-m7\manager\.venv\Scripts`, with the worktree as cwd. The main checkout's venv lacks `python_multipart`, so mypy there reports 4 import-not-found errors in M7's `policy_import.py`, which are not in my files.

- `ruff check manager`: all checks passed.
- `ruff format --check manager`: 314 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 314 files.
- The same with `--platform linux`: no issues in 314 files.

## Plants for the tester (M8 mutation table rows aimed at TASK-176)

- **CHK-M8-324:** in `normalise`, drop `.replace("\r\n", "\n")`. Red row: `"a\r\nb"` → `"a\nb"`.
- **CHK-M8-325:** `.strip(WHITESPACE)` → `.strip()`. Red rows: U+00A0 / U+2003 kept.
- **CHK-M8-337:** delete the body of `Verdict.__post_init__`, or only one of its two branches. Red rows: `Verdict(0, TIMED_OUT)`, `Verdict(2, None)`.
- **CHK-M8-364:** change the first check to `self.code not in (0, 1, 2, 3)`, or remove it. Red row: `Verdict(3, None)`.
- Extra boundary rows worth pinning:
  - `Verdict(2, "oversize")`: a plain `str` is refused, so plant `isinstance(..., str)` to see it;
  - `Verdict(True, None)`;
  - `normalise("\r\r\n") == ""`;
  - `normalise("a\r\r\nb") == "a\r\nb"` (one-pass replacement);
  - `normalise("x\r") == "x"`;
  - `"\v"` and `"\f"` trimmed (plant: `WHITESPACE = " \t\n\r"`).
