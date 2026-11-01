# TASK-220 TEST (r0 and r1): PASS

Tester: tester-m10c, 2026-11-01. Full rigor (agent, TS §8.2 second approval). REQ-246 (1)–(6), REQ-248 (1), (2) at binary level; TS §3.3 L222–L226, §3.5 L253; #139 (d), (e), #141. Decisions: "#140 reading: in-flight protection covers only an outstanding HTTP attempt" (r1: release before the back-off, rebuild with `Next`).

Code under test: `agent/internal/agent/loops/results.go` at r1, using `Spool.Release` (TASK-212 r1). Impl report: `work/reports/TASK-220-impl.md`.

Test files:
- `agent/internal/agent/loops/results_test.go` (new, portable, 10 tests and 13 subtests). It runs the real `Sender` over a real spool in a temporary directory. Only `clock.After` waiters move time, and the earliest is fired once the sender has been quiet for 30 ms. Plus a fake manager.
- Binary level: `e2e/agent_binary_m10.sh` scenario `overflow` (TASK-227 report). It runs the built agent with `spool_max_mb: 1`. The fake runner sends 5 results of 64 KiB, pauses 32 s, then sends 25 more. The fake manager answers 503 to every batch holding items until the runner is done, and 200 afterwards.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=5 -run TestSender ./internal/agent/loops/` | **115/115 passed** (23 × 5) |
| W (WSL, -race) | `-count=3 -run 'TestSender\|TestRelease'`; then the whole of `./internal/spool/ ./internal/agent/loops/` | ok ×3; **158/158 passed** |
| W, binary | overflow walk | **18/18 passed** |
| plants | 7 in `results.go`/`jobs.go` (unit), plus plant (d) through the binary walk | **8/8 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-065 | CODE | L, W | `TestSenderBatches` | PASS | A finished job of 120 gives posts `0,50,50,20F`. The start notice body is exactly `{"results":[],"final":false}`. Items go once, in seq order, and nothing follows the final |
| CHK-M10-066 | CODE | L, W | `TestSenderByteBound` (2) | PASS | Every body is ≤ 1,572,864 bytes of uncompressed JSON. 50 items of 32 KiB that escape (`"\`, U+0001, `é`) went as `0,30,20F`. Maximal items (65,536 × U+0001 stdout and 16,384 × U+0002 stderr, 6 bytes each escaped) went 3 per batch (recorded) |
| CHK-M10-067 | CODE | L, W | every test (`posts`) | PASS | Every body is gzip (`Gzip` set, decompresses) and decodes strictly as `ResultsRequest` |
| CHK-M10-068 | CODE | L, W | `TestSenderAnswerClasses` (11) | PASS | REQ-246 (4):<br>• 503 ×3 then 200: retry gaps exactly `[10s 20s 40s]`, stored once;<br>• 429: kept, the same body 10 s later (CHK-M10-363);<br>• 409, 400, 404, 413, 422, 403 `rate_limited` and 403 `forbidden` on batch 2: `0,50,50,50F`, batch 2 sent once, batch 3 still posted, never retried, the "not retried" line with `results <status> <type>` (last_error), spool empty (CHK-M10-362);<br>• 403 `pending_approval`: kept, the same body after 10 + 20 s;<br>• 401: the sender stops after 1 post;<br>• cap: gaps `[10s 20s 40s 1m20s 2m40s 5m0s 5m0s 5m0s]` |
| CHK-M10-069 | CODE | L, W | `TestSenderThirtySeconds` | PASS | REQ-246 (5). Three results of a running job, then silence. The sender waits exactly 30 s, nothing is posted at 29 s, and the batch is posted 30 s after the first result (3 items, not final) |
| TASK-220 documented late-post limit | CODE | L, W | `TestSenderLatePostLimit` | PASS | A Wake with nothing new arms the timer early, and a result spooled 20 s later is posted **40 s** after it was spooled (recorded). That's within the stated "at most 30 s later than the rule" (bound 30–60 s) |
| CHK-M10-070 | CODE | L, W | `TestSenderFinalWaitsForEarlier` | PASS | REQ-246 (6). Batch 2 is answered 503 twice: posts `0,50,50,50,50,50F`. Posts 2–4 are all batch 2, and the final waits until batch 2 is answered; posts are strictly ordered |
| CHK-M10-071 | CODE | L, W | `TestSenderWake` | PASS | A finished job goes out on `Wake` with no clock movement. 100 concurrent Wakes give `0,3F`, posted once |
| CHK-M10-072 | CODE | L, W | `TestSenderLogsNoOutput` | PASS | With a 409 drop, the log holds no `M10SENDCANARY` stdout and no token |
| r1: the retry is a fresh body; a converted item goes as its marker | CODE | L, W | `TestSenderRetryIsFresh` | PASS | Driven as TASK-223 drives it: a wake after StartJob and after each Put. The running job's 4 × 64 KiB batch is answered 503, released, and its 10 s back-off begins. A 5th result Put during the back-off converts the oldest released item. The retry body differs from the first. Recorded: `[001:spool_overflow 002:whole 003:whole 004:whole 005:whole]` |
| (a) binary: oldest become markers, including the in-flight batch; newest stay whole | APP | W | overflow walk | PASS | The first 503'd batch held plugins 001–005. At the end, markers are plugins 1–15 (001–005 among them) and 16–30 are whole. The spool's file bytes never exceeded the bound (max 991,038 of 1,048,576 over 165 samples) |
| (b) binary: every plugin eventually posted | APP | W | overflow walk | PASS | Once the manager returns, all 30 plugins are posted exactly once (as a result or a marker, in the marker shape) and the final is posted |
| (d) plant: no Release before the back-off | CODE | W | `results.go` Release skipped: overflow walk; and unit | PASS (red) | Walk 13/18. After the 503 the batch stayed in flight, nothing more was posted, 0 markers and 0 whole items arrived, and the wait timed out. Unit: `TestSenderRetryIsFresh` and the pending_approval row never got their retry |
| CHK-M10-360 | CODE | W | `maxBatch = 51` | PASS (red) | `TestSenderBatches` "posts 0,18F, want 0,50,50,20F", and the 409 row was red |
| CHK-M10-361 | CODE | W | `maxBatchBody = 3_000_000` | PASS (red) | "a body of 2955597 bytes uncompressed (bound 1,572,864)" |
| CHK-M10-362 | CODE | W | a drop answer retried | PASS (red) | "posts 0,50,50,50,50F, want 0,50,50,50F with batch 2 sent once" |
| CHK-M10-363 | CODE | W | a 429/503 dropped | PASS (red) | The 503 ×3 and 429 rows never got their retry |
| CHK-M10-368 | CODE | W | the start notice acked without posting | PASS (red) | "posts 50,50,20F, want 0,50,50,20F" |
| extra 220a | CODE | W | `holdYoung = 29 s` | PASS (red) | "the sender waits 29s, want 30 s" |

## Acceptance (TASK-220: "fake clock and fake manager: REQ-246 (1)–(6) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-246 (1)–(6) | CHK-M10-065 to -071 | PASS |
| r1 release and rebuild | r1 row, (a), (b), plant (d) | PASS |
