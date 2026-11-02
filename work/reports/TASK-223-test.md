# TASK-223 TEST (r0 and r1): PASS

Tester: tester-m10c, 2026-11-01. tester-m10 wrote the PD-45 rewrite (`compliance_linux_test.go`, `pull_test.go`) earlier; tester-m10c added the r1 rows, the remaining handler rows and the CHK-M4-223 rewrite. Full rigor (agent, TS §8.2 second approval). REQ-245, REQ-249 (2)–(4), REQ-250 (1)–(3); #28, #78, #131. Decisions rows:
- "TASK-223 (compliance loop) nil-handler choice accepted";
- "PD-45 rewrite of the M4 loops tests accepted";
- "#140 reading …" (TASK-223 r1);
- "The PD-45 compliance tests are Linux-only";
- "User decisions before the M10 merge" (2), the CHK-M4-223 rewrite.

Code under test: `agent/internal/agent/loops/compliance.go` (r1 `fill`), `jobs.go`, `pull.go`, `run.go`, `heartbeat.go`. Impl report: `work/reports/TASK-223-impl.md`.

Test files (Linux-only where they record a job: M4's state store can't fsync a directory on Windows):
- `agent/internal/agent/loops/compliance_linux_test.go`: the PD-45 rows and the nil handler. It was renamed from `compliance_test.go` at main's ruling. tester-m10c fixed one timing assumption (below).
- `agent/internal/agent/loops/compliance_r1_linux_test.go` (new): r1 and the handler rows.
- `agent/internal/agent/loops/pull_test.go`: CHK-M4-223 rewritten, plus a fail-fast in `TestJobPickupRecheckedAtStart`.
- Binary level: `e2e/agent_binary_m10.sh` (TASK-227 report).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race ./internal/spool/ ./internal/agent/loops/` | **158/158 passed**, 0 failed, 0 skipped |
| W, repeats | `-count=5 -run 'TestR1\|TestNilCompliance'`; `-count=3 -run 'TestHandler\|TestR1'` | ok, 0 failed |
| L (Windows) | `go test ./internal/agent/loops/` | see the gate report: the Linux-only files don't build there. The 5 failing M4 rows are pre-existing (Seen.Add → syncDir) |
| plants | 10 (r1 ×3, nil handler ×2, -367, -369, -384) plus CHK-M10-271 ×9 | **19/19 red** |

## PD-45 old → new (decisions "PD-45 rewrite … accepted")

| Old (M4) | New (M10) |
| --- | --- |
| CHK-M4-220 (#74 single runner_unavailable batch, no runner contact) | `TestPD45ComplianceThroughRunner`, `TestPD45RunnerUnavailableFill`, `TestPD45Results409Dropped` (CHK-M10-073, -074) |
| CHK-M4-221 (#74 batches) | `TestPD45Batches` (CHK-M10-065 at handler level, up to 5,000 plugins) |
| CHK-M4-223 (no `runner.sock`/`"unix"` anywhere in `internal/agent/**`) | **CHK-M10-271** `TestNoOtherJobSourceStatic`, rewritten per the user's decision (2026-11-01 (2)): `runner.sock` and AF_UNIX are allowed only in `internal/agent/runnerclient`; dialling only in runnerclient and transport; listening nowhere. The exec and RunJob/Handle caller assertions are kept |
| CHK-M4-101, CHK-M4-185 | unchanged (sync point per the PD-45 row; REQ-250 (1) has its own row) |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-073 | CODE | W | `TestPD45ComplianceThroughRunner` | PASS | REQ-245 (1), (5), (6): the start notice first, each plugin once, the final last. One runner request with the pulled job and the heartbeat's `max_parallel_plugins` 2. The canary `execute` is never run, logged or stored, and the state dir holds only `seen_jobs.json` and `spool/` |
| CHK-M10-074 | CODE | W | `TestPD45RunnerUnavailableFill`; `TestHandlerFailureWords` (8 words) | PASS | For `connect`, `timeout`, `broken`, `protocol`, `refused_busy`, `refused_foreign_agent`, `refused_replayed` and `refused_malformed`:<br>• the received result is kept;<br>• plugins 2 and 3 are `runner_unavailable`, with the final;<br>• exactly one runner request (CHK-M10-358);<br>• `last_error` = `runner_unavailable: <word>`, then null on the next heartbeat (the `broken` row).<br>**Test fix (mine):** the old row also required the fill items to be *inside* the final batch. #131 (b)/#141 allow an empty final after they're posted, and it was red once in WSL. It now asserts both fill items are posted and the final is the last post. main accepted the fix; reviewer-m10c is to confirm it isn't a loosening |
| CHK-M10-076, -359 (binary) | APP | W | walk `sigterm` | PASS | A cancel mid-job keeps the spooled result and sends no final and no fill; after a restart the result is posted, still with no final, and nothing is resent |
| CHK-M10-077 | CODE | W | `TestPD45ComplianceThroughRunner`; walk (all scenarios) | PASS | No command or pattern canary in any state file; agent output carries no canary |
| CHK-M10-078 | CODE / APP | W | `TestHandlerOneJobAtATime`; `TestJobPickupRecheckedAtStart` (M4); walk `invheld` | PASS | CHK-M10-369: while job 1 is held, the runner gets 1 call; after release both run, at most 1 at once over 2 calls. REQ-249 (2): a job whose `pickup_by` passes while an earlier one runs is never started and is logged. CHK-M10-370 (binary): inventory is uploaded while the runner holds the compliance job |
| CHK-M10-079 | CODE | W | `TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`; `TestHeartbeatRunStateValues` (M4) | PASS | REQ-250 (1): while results wait (503), the heartbeat's `spool_bytes` equals `Spool.Size()` (over 180,000; CHK-M10-367). REQ-250 (3): 3 more heartbeats make no runner call (CHK-M10-384). `current_job_id` comes from the run state (M4 row) |
| Nil handler (decisions row; REQ-249 (4)) | CODE | W | `TestNilComplianceHandlerRefusesButInventoryRuns` | PASS | 4 compliance jobs are refused ("no compliance handler", ≥ 4 lines), both inventory jobs run, `last_error` is set, there are 0 results posts, and the pull loop keeps running |
| r1 (c): a forced Put error, markers fit | CODE | W | `TestR1PutErrorFillsMarkers` | PASS | Result 1 is stored. The runner's 2nd result names a plugin not in the job, so `Put` fails. The final posts carry result 1 whole plus `spool_overflow` markers for 2 and 3 (exit null, empty streams). The foreign result is never posted (CHK-M10-392). There's a Warn line and no `last_error` |
| r1 (c): markers can't be stored | CODE | W | `TestR1MarkersCannotBeStored` | PASS | The bound is manifest + result 1 + 100 bytes. Result 1 is in an outstanding post, so it can't be converted, and the 2nd result fails. One ERROR line holds `job_id` and `"count":2`, with no output. The next heartbeat carries `spool: results not kept`. Plugins 2 and 3 are never posted (the manager shows them not run); result 1 is posted; the spool stays within its bound |
| CHK-M10-271 (was CHK-M4-223) | CODE | L, W | `TestNoOtherJobSourceStatic` | PASS | See above; 9 plants (below) |
| plant r1 `nofill` | CODE | W | the fill after a Put error removed | PASS (red) | "1 plugins posted, want 3"; the lost-line row is red too |
| plant r1 `unavailfill` | CODE | W | the fill uses `runner_unavailable` | PASS (red) | "plugin 2: … want a spool_overflow marker" |
| plant r1 `nolost` | CODE | W | no log or `last_error` for lost plugins | PASS (red) | "no lost-results line" |
| plant nil handler: panic | CODE | W | `panic` in place of the refusal | PASS (red) | The package panics |
| plant nil handler: early return | CODE | W | the pull loop returns without a handler | PASS (red) | "0 inventory jobs run, want 1" |
| CHK-M10-367 | CODE | W | `spoolBytes()` returns 0 | PASS (red) | The spool_bytes condition was never reached (120 s) |
| CHK-M10-369 | CODE | W | `go run(job)` in the worker | PASS (red) | "2 runner calls while the first job is held, want 1" |
| CHK-M10-384 | CODE | W | the heartbeat dials `runner.sock` | PASS (red) | CHK-M10-271: "loops/heartbeat.go reaches the runner socket or AF_UNIX"; "opens a socket ([net.Dial])" |
| CHK-M10-271 plants (9) | CODE | W | a `"unix"` dial in loops; `runner.sock` in state and in transport; `net.UnixAddr`/`"unixpacket"`; `x/sys/unix` in enrol; `net.Listen` in transport; `net.Dial` in loops; `os/exec` in loops; a `Handle` caller outside pull/jobs | PASS (red ×9) | Each failed for its reason; base green |

## Acceptance (TASK-223: "fake manager, fake runner, fake clock: REQ-245 (1)–(6), REQ-249 (2)–(4) and REQ-250 (1)–(3) hold, and the M4 pull and heartbeat suites pass except the PD-45 rows")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-245 (1)–(6) | CHK-M10-073, -074, -076, -077; walk | PASS |
| REQ-249 (2)–(4) | CHK-M10-078, nil handler | PASS |
| REQ-250 (1)–(3) | CHK-M10-079, -074 | PASS |
| r1 | the two r1 rows and 3 plants | PASS |
| M4 pull and heartbeat suites pass except the PD-45 rows | WSL 158/158 (CHK-M4-223 rewritten as CHK-M10-271 per the user) | PASS |
