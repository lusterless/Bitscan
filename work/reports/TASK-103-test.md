# TASK-103 TEST: job pull, job checks and dispatch
**Verdict: PASS.** REQ-098, REQ-104; TP-M4-18, CHK-M4-215 to -224; mutation rows CHK-M4-330 to -334, -356. Full rigour (agent).
Commands: `go test -count=1 ./internal/agent/loops/` and `CGO_ENABLED=1 go test -race`; `tester3_m4_plants.py t103`.
Counts: package 84/84, -race 84/84; plants 32/32 red (control 84/84).

| Criterion (TASK-103 / REQ-098, REQ-104) | Evidence |
| --- | --- |
| Pulls every job_pull_seconds ± 30 s after the first heartbeat; an empty answer causes no other call and no collection | CHK-M4-215; extra-pull, collection, interval-change, no-back-off, before-first-heartbeat and last-pull plants red |
| Foreign, expired (now and now − 1 s), more than 25 h, and replayed jobs (same pull, earlier pull, after a restart, 7 d − 1 s) refused and not run; own id in upper case accepted; boundaries now + 25 h and now + 1 s accepted | CHK-M4-216, -217; 330, 330b, 331, 331b, 331c, 332, 332b, 332c, 333, 334 red |
| The id is persisted as seen before the job is acted on; a failed record runs nothing | CHK-M4-218; three plants red |
| An inventory job goes to the inventory runner once, at once, alongside compliance | CHK-M4-219; plant red |
| A compliance job produces exactly the #74 calls (runner_unavailable items at the handling time, batches ≤ 50, only the last final, 503 retried, 409 dropped once and shown as last_error) and no process execution | CHK-M4-220, -221; 356 and seven batch/answer plants red |
| Pull order, compliance one at a time, current_job_id, ≤ 10 jobs per pull | CHK-M4-222; three plants red |
| No job from any other source; no exec, ForkExec or runner.sock in agent/internal/agent | CHK-M4-223 (TestNoOtherJobSourceStatic) |
| The execute string is never logged or stored; only seen_jobs.json changes | CHK-M4-224; plant red |

Test-side fixes this round (my bugs, no product change): the exec canary moved from a fixed /tmp path into t.TempDir(); two unbounded `<-done` waits are now bounded at 5 s; two gaps closed (409 re-count after the back-off; TestFirstPullWaitsForFirstHeartbeat). For review, as flagged in the impl report: a refused job also sets last_error (#78 (e) "local failure"), and a dropped results batch ends that job's remaining batches; both are tested as implemented.
Rows: CHK-M4-215..224, -mut-a, -220-r1, -mut, -r2.
