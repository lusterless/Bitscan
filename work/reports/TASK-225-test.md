# TASK-225 TEST: PASS

Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-234, REQ-235 (4), REQ-236 (2), REQ-261; TS §3.7 L281–L285; #130 (b)–(g); Q1 (decisions "tester-m10's M10 plan questions"); decisions "TASK-224 (job) and TASK-225 (serve) design points" (1), (2).

Code under test: `agent/internal/runner/serve.go` (unchanged since its IMPL; `work/reports/TASK-225-impl.md`).

Test file (new): `agent/internal/runner/serve_linux_test.go`, package `runner`, 10 tests and 16 subtests. It runs a real Unix socket (`net.ListenUnix` behind the `Listener` interface), the real `Checks` with a temporary `agent_id` file, and a fake executor (`fakeExec`, the exec counter, CHK-M10-H02). Canaries go in every `execute`, in a pattern and in every result's stdout. Each harness's cleanup fails the test if a canary reaches the runner log (CHK-M10-171).

## Where

The file is Linux-only. On Windows AF_UNIX, a refusal sent without reading the request can arrive as a reset (impl-agent-m10b's TASK-218 note), so the `busy` row only means something in WSL. Its Linux behaviour is recorded: the queued `refused busy` frame is read, then `ECONNRESET`, which the test treats as end of stream, and the busy client's write may get `EPIPE`. `serve.go` itself has no build tag; `GOOS=windows go vet ./internal/runner/` is clean.

The two deadline rows wait out the #130 (f) values in wall time (30 s and 60 s). These are spec times, the only ones this file waits for. Every other row is driven by channels.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -run TestServe ./internal/runner/` | **26/26 passed**, 0 failed, 0 skipped |
| W, flake check | the eight fast tests, `-count=5 -race` | ok, 0 failed |
| static | gofmt; `go vet` (linux and windows); `golangci-lint run` (Linux) | clean, 0 issues |
| plants | 9 plants in throwaway copies | **9/9 red** |

## Test fix during this round (mine)

At first, `TestServeCloseCancels/close` stayed green with the connection watcher's `cancel()` removed. The fake executor's write after the close failed, and that cancelled the job instead. The row now reads `accepted` and the result before closing, so only the watcher can cancel. After the fix, base passed 3/3 and the 391serve plant was red in both modes.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-163 | CODE | W | `TestServeGoodJob` | PASS | Replies `accepted,result,result,result,done`, then EOF. The results came in emit order with the plugin uuids. The executor ran once with a request JSON-equal to what was sent. Log: `job_id` and "runner: job done" |
| CHK-M10-164 | CODE | W | `TestServeBusy` | PASS | REQ-235 (4). While job 1641 is held, a second connection gets `refused busy` within 1 s, and its request is never run (executor calls 1). Job 1641 then finishes `accepted,result,done`, and a third job runs (the slot is freed) |
| CHK-M10-165 | CODE | W | `TestServeMalformed` (12 subtests) | PASS | REQ-261, Q1. Each case gets exactly one `refused malformed`, then EOF:<br>• a bare JSON string;<br>• plugins without a job;<br>• `"command"` beside `job` (CHK-M10-323);<br>• an unknown key inside `job`;<br>• `v` 2;<br>• `max_parallel_plugins` 9;<br>• 0 plugins;<br>• a zero-length frame;<br>• an oversize header (33,554,433);<br>• garbage bytes;<br>• two JSON values.<br>An inventory job gets `refused not_compliance` (CHK-M10-324). Exec counter 0. 12 "request refused" log lines, none with request text |
| CHK-M10-166 | CODE | W | `TestServeSecondFrame` | PASS | CHK-M10-322. A second request frame on a running job's connection is never decoded or run: executor calls 1, one `accepted`, and job 1662 never reached the executor. **Recorded:** the second frame's first byte cancels the running job (the watcher's "any read return", which fails closed). After a `refused foreign_agent`, a second frame gets nothing and nothing runs |
| CHK-M10-167 | CODE | W | `TestServeJobChecks` | PASS | REQ-236 (2) through the socket: foreign → `foreign_agent`, `pickup_by` = now → `pickup_passed`, now + 25 h + 1 s → `pickup_too_far`, a resent id → `replayed` (CHK-M10-327 unit half). Exec counter 0. Exactly one log line each: `{"msg":"runner: job refused","job_id":…,"reason":…}` |
| CHK-M10-168 | CODE | W | `TestServeRequestDeadline/{silent,half_header}` | PASS | `requestWait` = 30 s (#130 (f)). A silent connection, or one that sent 2 header bytes, is closed after 30.02 s, with one `refused malformed` frame (recorded). While it waits it holds the one slot, so another connection gets `refused busy` (recorded, #130 (g)). The next connection then runs normally |
| CHK-M10-169 | CODE | W | `TestServeCloseCancels/{close,half-close}` | PASS | TASK-225 acceptance. After `accepted` and the result have been read, closing the client cancels the executor's context within 1 s. A half-close (EOF) cancels too, and no `done` follows |
| CHK-M10-170 | CODE | W | `TestServeWriteDeadline` | PASS | `replyWait` = 60 s. The client stops reading while the executor emits 100 maximal results (65,536 + 16,384 bytes each). The job ended 60.05 s later, with fewer than 101 replies queued and no `done`. The next connection is served (executor calls 2) |
| CHK-M10-171 | CODE | W | every TestServe harness cleanup | PASS | No `M10SRVCANARY` (execute, pattern, stdout) in any runner log record |
| Fatal executor error (design point 2) | CODE | W | `TestServeFatalExecutorError` | PASS | Run returns an error: replies `accepted,result`, no `done`. `Serve` returns that same error (`errors.Is`), the listener refuses new connections, and the log has "job ended, cleanup failed" |
| Shutdown mid-job | CODE | W | `TestServeShutdownMidJob` | PASS | Cancelling `Serve`'s context mid-job cancels the job, `Serve` returns nil after it ends, and there is no `done` |
| CHK-M10-322 | CODE | W | plant: the watcher decodes and runs a second frame | PASS (red) | "executor ran 2 times … want 1 run" |
| CHK-M10-391 (serve half) | CODE | W | plant: the watcher's `cancel()` removed | PASS (red) | "closing the client did not cancel the executor" in both modes. VM half NOT RUN (VM hold, the named gate exception) |
| CHK-M10-382 (serve half) | CODE | W | plant: `execute` logged at accept | PASS (red) | "a canary is in the runner log (CHK-M10-171)" |
| extra 225a | CODE | W | plant: the busy flag never refuses | PASS (red) | The second connection got `accepted,result` (two jobs at once) |
| extra 225b | CODE | W | plant: a refused job still reaches `Exec.Run` | PASS (red) | "executor ran 4 times for refused jobs" |
| extra 225c | CODE | W | plant: `done` written after a cancelled job | PASS (red) | "done after a cancelled job: accepted,result,done" |
| extra 225d | CODE | W | plant: a fatal `Run` error ignored | PASS (red) | "Serve kept running after a fatal executor error" |
| extra 225e | CODE | W | plant: no 30 s request deadline | PASS (red) | Still open at the test's 45 s bound; the next connection got `refused busy` |
| extra 225f | CODE | W | plant: no 60 s write deadline | PASS (red) | "the job is still running 90 s after the client stopped reading" |

## Acceptance (TASK-225: "with a fake executor and a Unix socket, REQ-235 (4), REQ-236 (2) and the REQ-261 malformed-request cases hold, and closing the client cancels the executor's context within 1 s")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-235 (4) busy | CHK-M10-164 | PASS (WSL) |
| REQ-236 (2) refusals through the loop | CHK-M10-167 | PASS |
| REQ-261 malformed and non-job requests | CHK-M10-165, -166 | PASS |
| close → cancel within 1 s | CHK-M10-169 | PASS |
| #130 (f) deadlines | CHK-M10-168, -170 | PASS |
| REQ-261 host part (G78 through the driver) | CHK-M10-280 to -289 | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the rows above, plus TASK-213's checks |
