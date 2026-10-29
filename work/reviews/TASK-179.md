# TASK-179 REVIEW: `result_verdict()`, the intake verdict

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-194, REQ-205 (2). High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-179-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/verdict.py` (54 lines).

TEST: PASS (`work/reports/TASK-179-test.md`, tester-m8). 205/205 and 10/10 plants red.

Spec read: TS §4.5 L593, L596, L599; §3.3 L226; §6.5 L1184; SR §2.4 L149, L152; #12, #57, #112 (c), #113, #116.

My re-run on Windows: `pytest` on the verdict, eval_spec, score and property files gives 216 passed; `mypy --strict`, `ruff check` and `ruff format --check` are clean.

## Checks
1. **Caps "whatever the agent claims" (L599, #116).**
   - `over_caps` measures the received stdout and stderr in UTF-8 bytes and refuses anything strictly over 65,536 or 16,384. It never reads the `truncated` flag.
   - Encoding uses `surrogatepass`, so a lone surrogate counts and nothing raises.
   - Boundaries and multi-byte rows are pinned. CHK-M8-339 (characters), -340 (`>=`) and -341 (flag only) are red.
2. **Order (#112 (c)).** The checks run oversize, then `spool_overflow`, then `runner_unavailable`, then any other non-None `error` (`cannot evaluate`), then `classify`. A runner error never reaches `classify` (spy row; CHK-M8-342 red). The out-of-contract error branch fails closed rather than comparing (x179-unknown red).
3. **Only stdout compared (SR L152).** stderr feeds only the cap, and is never passed to `classify` (CHK-M8-343 red, stderr noise rows).
4. **Contract.** `ResultLike` accepts the real M3 `ResultItem` under mypy. The module imports only `evaluator.evaluate` and `evaluator.model`, with nothing from `api/` or `repositories` (CHK-M8-108).
5. **SR §1.1 through `eval_spec` (REQ-205 (2)).** The round trip through `build_eval_spec`, then `parse_eval_spec`, then `get`, gives PASS, FAIL, FAIL, PASS.
6. **Output.** Details are constants, and the canary in stdout, stderr and `error` appears in no verdict.

## Findings
None blocking or should-fix.
