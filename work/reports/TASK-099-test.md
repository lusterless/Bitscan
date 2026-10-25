# TASK-099 TEST: token holder and rotation
**Verdict: PASS.** REQ-099; TP-M4-14, CHK-M4-150 to -158; mutation rows CHK-M4-347 to -349. Full rigour (agent).
Commands: `go test ./internal/agent/token/` and `CGO_ENABLED=1 go test -race`; `tester3_m4_plants.py t099`.
Counts: 29/29, -race 29/29; plants 18/18 red.

| Criterion (REQ-099) | Evidence |
| --- | --- |
| (1) no rotate before the window, one after; every later call uses the new token | CHK-M4-150, -151; CHK-M4-348 (4 forms) red |
| (2) lost answer: the retry sends the old token and keeps the fresh one | CHK-M4-152; new-token-on-retry plant red |
| (3) crash before the state write leaves the old token; the next attempt rotates again | CHK-M4-153, -158; CHK-M4-349 (2 forms) red |
| (4) concurrent triggers: exactly one call | CHK-M4-154 (200 rounds, also under -race); CHK-M4-347 red |
| (5) 429 waits for Retry-After, 403 forbidden for 24 h, 401 stops | CHK-M4-155; five plants red |
| (6) an expired token is still sent; its 401 stops | CHK-M4-156; local-expiry plant red |
| no token in body, errors or output | CHK-M4-157; plant red |

Not covered here: "only a successful heartbeat calls MaybeRotate" is TASK-101 (TestHeartbeatTimerAndBody, TestHeartbeatAnswerTriggersNothing). Spec-silent and left as implemented: 3xx/400/404/409/422 rotate answers are retried at the next heartbeat (already raised with the user).

## Round 2 (revision 1, user ruling 2026-10-25): PASS
Every rotate answer in the Drop class (3xx, 400, 403 other than pending_approval, 404, 409, 413, 422, any other answer not retried) waits 24 h, and the old token stays in use. TestRotationOtherAnswersKeepOldToken was extended to 9 statuses: no call within 24 h, then one attempt with the old token at +24 h. Retry answers still retry at the next heartbeat. Counts: the two named tests 10/10 and 8/8; the package 38/38; the plant that restores the 403-only condition is red (29/38). A second plant (Retry also waits) is an equivalent mutant: that line cannot be reached for Retry. Rows CHK-M4-155-r1, CHK-M4-150..158-r1, CHK-M4-155-r1-mut.
