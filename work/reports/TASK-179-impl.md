# TASK-179 IMPL: `result_verdict()`, the intake verdict

Implementer: impl-manager-m8. REQ-194, REQ-205. Risk high. Plan: `work/plans/TASK-178.md` §5. Spec: TS §4.5 L593, L596, L599; §3.3 L226; §3.5 L251–L252; §6.5 L1184; SR §2.4 SR L149. Answers applied: #12, #57, #112 (c), #113, #116 (a)–(c).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/verdict.py` (new, 57 lines / 47 non-blank) | `utf8_size()`, `over_caps()`, `result_verdict()` |

Size: 57 lines, against an estimate of 45 to 70. No other file was changed.

## Interface (the plan's §5)

```python
def utf8_size(text: str) -> int                      # len(text.encode("utf-8", "surrogatepass"))
def over_caps(stdout: str, stderr: str) -> bool      # > STDOUT_CAP or > STDERR_CAP, bytes
def result_verdict(spec: PluginSpec, result: ResultLike) -> Verdict
```

`classify` is imported by name (`from ...evaluator.evaluate import classify`). A spy must therefore patch `bitscan_manager.services.evaluator.verdict.classify`; patching `evaluate.classify` does not reach it.

## How each acceptance point is met

- **Order (#112 (c)):**
  1. `over_caps(stdout, stderr)` → ERROR `oversize`;
  2. `error == "spool_overflow"` → ERROR `spool_overflow`;
  3. `error == "runner_unavailable"` → ERROR `runner_unavailable`;
  4. any other non-None `error` (outside the wire contract; `ResultItem` allows only the two) → ERROR `cannot evaluate`, as the plan says;
  5. otherwise `classify(spec.operator, spec.expected, result.stdout, result.exit_code, result.timed_out, result.truncated)`.
- **Caps (#116):**
  - UTF-8 bytes, strictly over 65,536 / 16,384, from `model.STDOUT_CAP` / `STDERR_CAP`.
  - `surrogatepass` counts a lone surrogate as 3 bytes, so `utf8_size` never raises.
  - The agent's `truncated` flag is not read for the cap.
- **Runner errors (#12):** each returns before `classify` is reached, so no comparison runs.
- **stdout only (REQ-194 (4)):** stderr is used only in `over_caps`. It is never passed to `classify`.
- **Types (REQ-194 (6)):** `result` is the `ResultLike` protocol (TASK-176). The module imports only `evaluator.evaluate` and `evaluator.model`, nothing from `api/`.
- **Purity:** there is no logging, no I/O and no state. Every detail is a `Detail` constant, so nothing from stdout or stderr is quoted.

## Scratch check (outside the tree, `/tmp/m8-176-scratch/check179.py` and `check205.py`, the worktree venv; not a test)

All of these hold:
- REQ-194 (1):
  - stdout of 65,536 `a` passes the cap (and is FAIL under `equals`), while 65,537 is `oversize`;
  - 32,768 × `é` (2 bytes each) passes, and adding one `a` makes it `oversize` at 32,769 characters;
  - stderr of 16,384 passes and 16,385 is `oversize`; 8,193 × `é` in stderr is `oversize`;
  - 21,845 lone surrogates plus `a` (65,536 bytes) passes, and 21,846 surrogates (65,538 bytes) are `oversize`.
- REQ-194 (2): oversize with `error` `spool_overflow` gives `oversize`.
- REQ-194 (3): `spool_overflow`, `runner_unavailable` and `other` give their ERROR with a `classify` spy (patched on `verdict`) seeing no call. A clean result is one call.
- REQ-194 (4): 100 lines of `error: permission denied` in stderr leave a PASS a PASS.
- REQ-194 (5): the SR §1.1 entry with stdout `install ok installed\n` and exit 0, passed as a real validated `ResultItem`, gives `Verdict(0, None)`.
- REQ-194 (6): a scratch module passing a `ResultItem` to `result_verdict` is clean under `mypy --strict`.
- REQ-205 (2): the SR §1.1 plugin built with m8b's `EvalSpec`/`build_eval_spec`, round-tripped through JSON and `parse_eval_spec`, then `spec.get(uuid)`, gives codes 0, 1, 0, 1 for stdout `install ok installed`/exit 0, `""`/0, `install ok installed\n`/0 and `""`/1.

## Static gates (Windows, `Bitscan-m8\manager\.venv`)

- `ruff check manager`: all checks passed.
- `ruff format --check manager`: 322 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 322 files.
- The same with `--platform linux`: no issues in 322 files.

## Plants for the tester (rows aimed at TASK-179)

- **CHK-M8-339:** `utf8_size` → `len(text)`. Red rows: the `é` rows.
- **CHK-M8-340:** `>` → `>=` in `over_caps`. Red rows: exactly 65,536 / 16,384.
- **CHK-M8-341:** replace `over_caps(...)` with `result.truncated and over_caps(...)`, or with `result.truncated` alone. Red row: an oversize stdout with `truncated` false.
- **CHK-M8-342:** in the `spool_overflow` branch, call `classify(...)` and return its verdict (or return `Verdict(ERROR, ...)` after calling it). Red: the spy row.
- **CHK-M8-343:** pass `result.stdout + result.stderr` (or `result.stderr`) as stdout to `classify`. Red row: a noisy stderr under `equals` / `empty`.
- Extra rows:
  - swap the oversize and runner-error checks: oversize + `spool_overflow` gives `spool_overflow`;
  - `"strict"` instead of `"surrogatepass"`: a lone-surrogate stdout raises `UnicodeEncodeError` (totality, G63);
  - drop the `result.error is not None` branch: `error="other"` reaches `classify` (a spy sees one call).
