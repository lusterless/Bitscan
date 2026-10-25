# TASK-090 REVIEW: back-off and jittered intervals

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/schedule/interval.go` and `agent/internal/agent/schedule/backoff.go` (`work/reports/TASK-090-impl.md`). Sources: TS §3.3 L202–L206 and L226, #4, and the lead ruling of 2026-10-24 (±10 % per step, never above 330 s).

TEST: PASS (`work/reports/TASK-090-test.md`): 12/12 as root, as `bstester` and under `-race`, and 14/14 plants red, including CHK-M4-338.

## Checks
1. Spec:
   - The heartbeat is 300 s ± 30 s, uniform (TS §3.3, #4: fixed).
   - The pull interval is `job_pull_seconds` clamped to 60–3,600, ± 30 s (L203, L206).
   - The back-off is 10, 20, 40, 80, 160 s, then 300 s, each ±10 %, so never above 330 s. It resets after a success (L226).
2. Security and robustness:
   - Only the injected `Clock` and `Source` are used, and `CryptoSource` avoids a seeded global generator.
   - `Sleep` returns `ctx.Err()` at once when the context is done, so SIGTERM is not delayed.
   - The doubling is capped before multiplication, so it cannot overflow.
   - No configuration input can disable or stretch a loop beyond the clamp.
3. Scope: 2 new files, about 75 lines.
4. Tests: fixed-`Source` edge values (u = 0 and u near 1), the distribution over draws, the reset, the clamp at both ends, and context cancellation. Plants for the cap, the spread, a missing jitter, one-sided jitter, the wall clock and an ignored context are all red.
5. Re-run by the reviewer (Windows): `gofmt` prints nothing, and `GOOS=linux` vet and golangci-lint on `schedule` report 0 issues.

## Findings
None.
