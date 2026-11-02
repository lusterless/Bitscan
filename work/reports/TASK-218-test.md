# TASK-218 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (runner client, TS §8.2 second approval). REQ-245 (the client half), REQ-234; TS §3.5 L249, §3.7 L282; #130 (f), (g), (j), #131 (a), (c).

Code under test (impl-agent-m10b, `work/reports/TASK-218-impl.md`): `agent/internal/agent/runnerclient/client.go` (sha256 `d41cbab0c072b17e…`). Test file (new): `agent/internal/agent/runnerclient/client_test.go` (`bc6405b7353cdb50…`). Plan rows: CHK-M10-051 to -058, plus mutation row CHK-M10-392 (the client half).

The fake runner is a Unix socket in a temporary directory that plays a #130 frame script per connection and records each request. The fake clock fires its timers only when the test moves it, and moves only when the client's own timer of the expected length is armed, so the tests use no sleeps for ordering. The busy row runs on Linux (impl note: an AF_UNIX reset on Windows drops the buffered reply).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/agent/runnerclient/`, run 3 times | **35/35 passed** each time, 0 failed, 0 errors, 0 skipped |
| static | `go vet` (Windows); `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/agent/runnerclient/` | clean |
| plants | 7 | **7/7 red** |

Two test bugs were fixed before the verdict:
- the deadline rows armed the clock against the dial's stale timer;
- the busy rows moved the clock while a request was in flight.

Both now wait for the exact timer, and three back-to-back runs were green.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-051 | CODE | W | `TestNormalRun` | PASS | Exactly one request on one connection: `v` 1, `max_parallel_plugins` the value passed (5), `job` equal to the job given (id and plugins deep-equal). Results 2, 1, 3 are delivered once each, in the order received. Returns nil after `done` |
| CHK-M10-052 | CODE | W | `TestFailureWords` (26 subtests) | PASS | #131 (c) words. No socket → `connect`. A bound socket with no listener (ECONNREFUSED) → `connect`. `refused <w>` → `refused_<w>` for all 12 words other than busy. EOF after 2 of 5 → `broken` with 2 delivered. EOF before any reply → `broken`. A frame cut inside its body → `broken`. An oversize reply header, a malformed reply, `done` as the first reply → `protocol`. A result for a plugin not in the job, and a repeated result → `protocol`, with the bad item **not** delivered (CHK-M10-392 client half). A second `accepted`, or `refused` after `accepted` → `protocol`. Every failure used exactly one connection (never resent). **Recorded:** `done` after 1 of 3 results → `protocol`. **Not run:** EACCES on the socket (the test runs as root, which bypasses the mode); `connect` is covered by the two rows above |
| CHK-M10-052 (timeout), CHK-M10-054 | CODE | W | `TestDeadlines` | PASS | No first reply: no return at 29 s, `timeout` at 30 s. After `accepted` with `timeout_s` 30/31/32: no return at 61 s, `timeout` at 62 s (max + 30 s) |
| CHK-M10-053 | CODE | W | `TestBusy` | PASS | Always busy: redialled every 2 s, `refused_busy` after 30 s, 15 connections in total (recorded). Busy 3 times then accepted → a normal run with its result |
| CHK-M10-055 | CODE | W | `TestCancel` | PASS | `ctx` cancelled mid-run → `context.Canceled`, not a `*Failure`. The fake runner sees the connection close |
| CHK-M10-057 | CODE | W | `TestOnResultError` | PASS | An `onResult` error stops the run after the first result, with a non-`Failure` error |
| CHK-M10-056, -058 | CODE | W | `TestClientStatic` | PASS | `client.go` imports no log, slog, `os/exec` or `internal/runner/*` other than `proto`. It calls no `time.Now`/`Sleep`/`After`/`NewTimer` (only the injected clock) and prints nothing. `Socket` = `/run/bitscan/runner.sock` |
| plant 218a | CODE | W | the busy retry removed | PASS (red) | `TestBusy` failed (both subtests) |
| plant 218b | CODE | W | busy retried for 60 s | PASS (red) | `TestBusy/always_busy` failed |
| CHK-M10-392 | CODE | W | a result for a plugin not in the job (or repeated) delivered | PASS (red) | `TestFailureWords` (2 subtests) failed. The handler half is in TASK-223 |
| plant 218d | CODE | W | first reply limit 31 s | PASS (red) | `TestDeadlines/no_first_reply_in_30_s` failed |
| plant 218e | CODE | W | EOF before `done` reported as `protocol` | PASS (red) | `TestFailureWords` (2 EOF subtests) failed |
| plant 218f | CODE | W | the gap ignores `timeout_s` | PASS (red) | `TestDeadlines/gap_after_accepted` failed |
| plant 218g | CODE | W | `refused` without the reason word | PASS (red) | 11 `refused_*` subtests failed |

## Acceptance (TASK-218: "against a fake runner on a Unix socket with a fake clock, every #131 (a) failure kind yields its word, busy is retried every 2 s for 30 s, and a normal run delivers each result once, in order received")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| every #131 (a) kind → its word | CHK-M10-052, -054 | PASS (EACCES not run as root; covered by the connect rows) |
| busy every 2 s for 30 s | CHK-M10-053 | PASS |
| a normal run delivers each result once, in order | CHK-M10-051 | PASS |

No finding.

## r1 (reviewer-m10 finding 1; the lead's two r1 rows)

Test files only; no product change. `client_test.go` is now `6513d8585d9d99e7…`, and there's a new `client_linux_test.go` (`a322a5e9abb05021…`).
- The "socket with no listener" subtest (`syscall.Bind` of AF_UNIX, which fails with "invalid argument" on Windows) moved to `client_linux_test.go` as `TestConnectRefusedLinux`. It isn't built on Windows, so nothing is skipped.
- New portable row `TestConnectAfterListenerGone`: a runner socket whose listener closed and whose file was removed → `connect`, on Windows and Linux.
- New row `TestConnectPermissionDeniedLinux` (builder checklist 21). A root-owned 0660 socket. A copy of the test binary runs the client as uid 65534 (`setpriv --reuid=65534 --regid=65534 --clear-groups`), so the connect gets EACCES. Asserted: word `connect`, a `*Failure` (not a ctx stop), 0 results, 0 connections reaching the runner, and a return in under 5 s with the real clock (a busy retry would take 30 s). **Recorded:** `WORD=connect FAILURE=true CTX=false RESULTS=0 UID=65534 SECONDS=0.0`.

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v ./internal/agent/runnerclient/` | **35/35 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race, root; the EACCES child runs as nobody) | `go test -race -count=1 -v ./internal/agent/runnerclient/` | **38/38 passed**, 0 failed, 0 errors, 0 skipped |
| plant 218h | EACCES mapped to `refused_busy` (so it is retried as busy) | **red**: `TestConnectPermissionDeniedLinux` failed after 28 s (the busy retry) |
| static | golangci-lint, Windows and `GOOS=linux` | clean |

The acceptance table is unchanged; the "EACCES not run" note above is now **run** (W, as uid 65534).
