# TASK-214 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (capture and result, TS §8.2 second approval). REQ-241, REQ-242 (through the capture path); TS §3.5 L251–L252, §6.5 L1184, §4.5 L593; #113, #114, #134 (b), #136 (e).

Code under test (impl-agent-m10, `work/reports/TASK-214-impl.md`): `agent/internal/runner/capture.go` (sha256 `d4356a39ef64f116…`) and `result.go` (`af62b47cf72642ba…`). Test files (new):
- `agent/internal/runner/capture_test.go` (`1e8b8b1be03e16d7…`)
- `agent/internal/runner/capture_linux_test.go` (`9946f2954ac7d17f…`; real processes, harmless payloads only)

Plan rows: CHK-M10-044 to -050, plus mutation rows CHK-M10-346, -355 and -357.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -run 'Capture\|ExitCode\|Build\|Unavailable' -v ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | same, with `-race` | **10/10 passed** (the 2 Linux process rows included), 0 failed, 0 errors, 0 skipped |
| static | gofmt; golangci-lint (Windows and `GOOS=linux`) | clean |
| plants | 7 | **7/7 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-044 | CODE | L, W | `TestCaptureLimitAndDrain`, `TestCaptureReadError` | PASS | Over an `os.Pipe`, writers of 0, 1, 1,048,576, 1,048,577 and 3 MiB all finish (the rest is drained, never blocked). The kept data is exactly the first `min(n, 1 MiB)` bytes, and `Overflow` is false at exactly 1 MiB and true at 1 MiB + 1. On a read error the bytes kept so far come back with the error (10 bytes, and 1 MiB with `Overflow`) |
| CHK-M10-045 | APP | W | `TestCaptureRealProcessBothPipesLinux`, `TestCaptureTwoStreamsConcurrently` | PASS | `sh -c 'head -c 3145728 /dev/zero >&2; head -c 3145728 /dev/zero'` with both pipes captured concurrently exits cleanly. Each stream keeps 1 MiB with `Overflow`. A silent stream beside a 3 MiB one doesn't deadlock. (TASK-214 acceptance: "a writer producing 3 MiB is never blocked") |
| CHK-M10-046 | CODE | L, W | `TestExitCodeMapping`, `TestExitCodeRealProcessesLinux` | PASS | REQ-241 (1): 0, 1, 126, 127, 255 → themselves; signals 9 → 137, 15 → 143, 11 → 139, 1 → 129, 6 → 134; never negative. Real wait statuses on Linux: `exit 3` → 3, `exit 126` → 126, `exit 255` → 255, `kill -9 $$` → 137, `kill -15 $$` → 143, `kill -11 $$` → 139, an unknown command → 127 (REQ-241 (3) at unit level) |
| CHK-M10-047 | CODE | L, W | `TestBuildItem` | PASS | REQ-241 (2), (4). A +01:00 start with nanoseconds → `started_at` and `finished_at` both end in `Z`, start ≤ end, the same instant kept. A clock step back gives `finished_at` = `started_at`, never earlier. `exit_code` 137 with `timed_out` true. stdout `bsa_` and stderr `password=` → `[REDACTED]`. `truncated` comes from stdout overflow; a 20,000-byte stderr is cut to 16,384 with `truncated` false. Every item passes `proto.NewResult` |
| CHK-M10-048 | CODE | L, W | `TestBuildFallbackNeverRaw` | PASS | CHK-M10-357: an outcome that `NewResult` refuses (bad plugin uuid) → `runner_unavailable`, null exit, empty streams. The raw canary is in neither the item JSON nor any log record (default slog captured) |
| CHK-M10-049 | CODE | L, W | `TestCaptureThenBuildOverflow` | PASS | REQ-242 (6) through capture: 1 MiB + 1 byte of `a` through a pipe, with pattern `a+` → `[REDACTED]`, `truncated` true |
| CHK-M10-050 | CODE | L, W | `TestUnavailableShape` | PASS | REQ-241 (5) item shape: null exit, empty streams, flags false, `runner_unavailable`. (Forcing exec or cgroup failure for one plugin is the executor's row, TASK-224 CHK-M10-153) |
| CHK-M10-346 | CODE | W | plant (a): the drain removed | PASS (red) | 5 tests failed, including `TestCaptureTwoStreamsConcurrently` and `TestCaptureRealProcessBothPipesLinux`, both blocked to the 30 s bound |
| CHK-M10-346 | CODE | W | plant (b): the read limit removed | PASS (red) | 4 tests failed (3 MiB kept) |
| CHK-M10-355 | CODE | W | plant: a signal death reported as −1 | PASS (red) | `TestExitCodeMapping`, `TestExitCodeRealProcessesLinux` failed |
| CHK-M10-357 | CODE | W | plant (a): raw stdout instead of redacted | PASS (red) | `TestCaptureThenBuildOverflow` (and the redaction asserts) failed |
| CHK-M10-357 | CODE | W | plant (b): a refused item returned as is (a zero Result) instead of `runner_unavailable` | PASS (red) | `TestBuildFallbackNeverRaw` failed |
| extra 214b | CODE | W | plant: the clock-step clamp removed | PASS (red) | `TestBuildItem` failed |
| extra 214c | CODE | W | plant: `Overflow` only above 1 MiB + 1 | PASS (red) | `TestCaptureLimitAndDrain`, `TestCaptureThenBuildOverflow` failed |

## Acceptance (TASK-214: "REQ-241 (1), (2), (4) hold, a writer producing 3 MiB is never blocked, and REQ-242 (6) holds through the capture path")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-241 (1) exit statuses and signals | CHK-M10-046, plant 355 | PASS |
| REQ-241 (2) times | CHK-M10-047, plant 214b | PASS |
| REQ-241 (4) every item passes NewResult (or becomes runner_unavailable) | CHK-M10-047, -048, plants 357a/b | PASS |
| a 3 MiB writer never blocked | CHK-M10-044, -045, plant 346a | PASS |
| REQ-242 (6) through capture | CHK-M10-049, plant 214c | PASS |
| REQ-241 (3) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-046 (real processes in WSL) and TASK-224's CHK-M10-154 |

No finding.
