# TASK-181 REVIEW: pure score and effective-verdict rule

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-196, REQ-197 (1), (2). High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-181-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/score.py` (113 lines).

TEST: PASS (`work/reports/TASK-181-test.md`, tester-m8). 205/205 and 8/8 plants red.

Spec read: TS §4.5 L601–L602, §4.4 L583; #119, #120.

My re-run on Windows: 216 passed across the four pure-module files. `mypy --strict` and `ruff` are clean.

## Checks
1. **Score (L602, #120).**
   - The score is passed ÷ (passed + failed), unrounded, or None when the sum is 0, so 0 ÷ 0 is never 0.0.
   - ERROR and Not run are carried as counts but never enter the ratio.
   - A negative or non-int count, `bool` included, is a fixed-text `ValueError`.
   - CHK-M8-346 and -347 are red; the property row covers counts up to 10⁹.
2. **Latest-row rule (L601, #119).** `effective` filters by job and plugin, then the highest `reeval_id` wins, whatever the order or `reevaluated_at`.
   - The detail comes from the winning row even when it's NULL, so ERROR re-evaluated to PASS gives detail None.
   - The original is always returned beside it (`result` and `original_result` for M11).
   - CHK-M8-348 (unit) is red for the lowest-id, by-time and last-row plants.
3. **Purity.** The imports are stdlib only. `Effective` mirrors `results.EffectiveRow` field for field (minus `agent_id`), so TASK-184's SQL-versus-pure property can compare them.

## Findings
None blocking or should-fix.
