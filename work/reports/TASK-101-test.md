# TASK-101 TEST: run state and heartbeat loop
**Verdict: PASS** (round 2, revision 1). REQ-097, REQ-095, REQ-103 (and REQ-096 (3) for the later-heartbeat 401). TP-M4-16, CHK-M4-185 to -193; mutation rows CHK-M4-335, -338, -355. Full rigour (agent).
Commands: `go test -count=1 ./internal/agent/loops/` and `CGO_ENABLED=1 go test -race`; `tester3_m4_plants.py t101`.
Counts: round 1 package 82/82, -race 82/82, 25/25 plants red; CHK-M4-189-r1 FAIL 5/8 after my test extension. Round 2: the two tests 8/8, control 21/21, 7/7 stop plants red, package -race 83/83.

| Criterion (TASK-101 / REQ-097) | Evidence |
| --- | --- |
| Heartbeats every 270–330 s (first at start, 20 more); body matches #78 and HeartbeatRequest | CHK-M4-185; uptime-0, clock-is-start and first-heartbeat-delayed plants red |
| runner_helpers follows a planted capread.sock (#30, any file) | CHK-M4-186; helpers-constant and socket-only plants red |
| A new job_pull_seconds changes the pull interval; the max_parallel clamp | CHK-M4-187; 187, 187b and 187c (rewritten) red |
| A heartbeat answer triggers no other call; rotate only after a successful heartbeat | CHK-M4-188; 355, 355b, 158 and 158b red |
| A 401 stops every loop within 1 s (also from another loop and from rotation); the re-enrol line logged once; the Run stays up | CHK-M4-189, -189-r2; 335, 335b, 189, 189b and both r1 plants red |
| 403 pending_approval and 503/429/network use the back-off and reset | CHK-M4-190, -191; 338, 338b and pending-on-timer plants red |
| last_error: next heartbeat, then null; ≤ 1,024 chars; type sanitised | CHK-M4-192; four plants red |
| Cancel ends the loops within 1 s, no goroutine left | CHK-M4-193 (TestHeartbeatCancel) |
| No token or body in logs | TestHeartbeatLogsNoSecrets; 339 and 339b red |

Round 1 FAIL (fixed): 401 enrollment_rejected on a heartbeat (REQ-096 (3)) and a rotation 401 (TS §3.2 step 8) logged "must be re-enrolled" without "with a new enrolment token". Revision 1 adds enrollment_rejected to the new-token types and stops with that line on token.ErrStop. My tests had missed both cases; they now check them.
Rows: CHK-M4-185..193, -185..193-r1, -185..193-mut, -189-r1 (FAIL), -189-r2, -185..193-r1-mut, -185..193-r2.
