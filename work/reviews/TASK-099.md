# TASK-099 REVIEW: token holder and rotation

Verdict: APPROVED (round 2, revision 1). Round 1 was APPROVED with one point for the user (Finding 1). The user chose option (b), and r1 implements it.

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed for the task including r1.**

Scope reviewed: `agent/internal/agent/token/holder.go` and `agent/internal/agent/token/rotate.go` (`work/reports/TASK-099-impl.md`, including its "Revision 1" section). Sources: TS §3.2 steps 7–8, §6.5 Rotate, REQ-099, #62, and the decisions of 2026-10-23 (lost-response retry, the 24 h rule, the 30-day cap). r1 follows the user's ruling of 2026-10-25 that every Drop answer waits 24 h.

TEST:
- Round 1: PASS (`work/reports/TASK-099-test.md`): 29/29, the same under `-race`, and 18/18 plants red (CHK-M4-347 to -349).
- Round 2 (r1): PASS from tester-m4 (by message). Each of the 9 Drop statuses makes no call within 24 h, then a call with the old token at +24 h, while Retry answers are still tried at the next heartbeat. The package passes 38/38. The plant that restores the old 403-only condition is red. The Retry-also-waits plant is equivalent: that path is unreachable. Rows CHK-M4-155-r1*.

## Checks
1. Spec:
   - The window opens at `issued_at + max(TTL − 30 d, TTL ÷ 2)`, from the token's own TTL. When the times are not known (TASK-088's crash case), the window counts as open and the manager decides.
   - On 200: strict decode, then `SaveToken`, then the holder is swapped, so the new token is persisted before any loop uses it.
   - A lost or unreadable answer, or a failed save, keeps the old token. The next attempt therefore sends the old token, which is the manager's lost-response retry (TS §3.2 step 7).
   - 429 waits for `Retry-After` (the 24 h rule). Any 401 returns `ErrStop` and latches, so no later call is made (step 8, #81 (a)).
   - r1: every Drop answer, 403 `forbidden` included, waits 24 h.
   - An expired token is still sent, and its 401 stops the agent (REQ-099 (6)).
2. Concurrency: `TryLock` held for the whole call, so concurrent triggers give exactly one call (200 rounds under `-race`). `Holder` is an `RWMutex`, and `set` is unexported, so only the rotator can change the token.
3. Security: errors hold fixed words, the status and the problem type, never a token. `%+v` of a `Token` is redacted. The rotate body is `{}`.
4. Scope: 2 new files, about 105 lines. r1 changes one condition and one comment.
5. Re-run by the reviewer (Windows):
   - After r1, `gofmt -l internal/agent/token` prints nothing.
   - `GOOS=linux golangci-lint run ./internal/agent/token/...` reports 0 issues.
6. r1 correctness:
   - `if resp.Class == transport.Drop { notBefore = now + 24 h }` runs only after the Success, Stop and Retry cases have returned.
   - A 403 `pending_approval` (Wait class) is still tried at the next heartbeat. That is consistent with the heartbeat's own waiting.
   - A 200 whose body or save fails stays on the lost-answer path, not the 24 h wait. That is correct: the manager did answer, and the retry with the old token is what TS §3.2 step 7 expects.
   - The window is at least 30 days, so a 24 h pause cannot make the token expire.

## Findings
1. Closed by r1: rotate answers in the Drop class were retried at every heartbeat. The user chose option (b), and every Drop answer now waits 24 h.
2. nit, `rotate.go:85`. The `switch resp.Class` runs before `err` is looked at, and `transport.Success` is the zero value of `Class`. With `*transport.Client` this is safe, because every error path sets `Class` (`client.go:149-192`). A future `Doer` that returns `(Response{}, err)` would be treated as success and fail later, in the strict decode of an empty body. Optional: check `err != nil` first, or make the zero `Class` a non-success value. That second option is TASK-093's file.
3. nit, `rotate.go:92-95`. If `SaveToken` writes `token` and then fails on `token.json`, the disk holds the new token and the holder keeps the old one. Without a restart this is harmless: the next attempt sends the old token, and the manager issues a fresh one. Combined with a lost response on that retry and then a restart, the agent would start on a token the manager has already discarded, so the host would need re-enrolment. That needs three faults together. No change; recorded for the M4 gate's crash review.
