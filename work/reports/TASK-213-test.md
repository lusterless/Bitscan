# TASK-213 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (runner job checks, TS §8.2 second approval). REQ-236, REQ-244 (the runner-check half); TS §3.3 L212, §3.7 L282, L285, §8.1 L1239, §8.3 L1283; #130 (d), #132. The lead's Q2 ruling applies: a job refused `seen_full` is not recorded.

Code under test (impl-agent-m10, `work/reports/TASK-213-impl.md`): `agent/internal/runner/checks.go` (sha256 `26dd331c071f8a56…`). Test files (new):
- `agent/internal/runner/checks_test.go` (internal package `runner`, so the 100,000-id bound can be reached by filling the set directly; `b1cb67f30551d34e…`)
- `agent/internal/runner/checks_linux_test.go` (the FIFO row; `18d1e50f1a1c79a2…`)

Plan rows: CHK-M10-035 to -043, plus mutation rows CHK-M10-324 to -328, -351, -352 and -393.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v -run TestChecks ./internal/runner/` | **58/58 passed** (subtests included; the FIFO row is Linux only), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v -run TestChecks ./internal/runner/` | **59/59 passed**, 0 failed, 0 errors, 0 skipped |
| static | gofmt; `golangci-lint run --uniq-by-line=false ./internal/runner/` (Windows and `GOOS=linux`) | clean |
| plants | 16, each in its own `/root/bstest-m10-mut-<id>` | **16/16 red**, each a test failure for the planted reason |

One test bug was fixed before the verdict: the case-variant duplicate row used all-digit UUIDs, so the case change was a no-op (plant 213a stayed green). The UUIDs now hold hex letters, and the plant is red.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-035 | CODE | L, W | `TestChecksRefusals` (30 subtests) | PASS | REQ-236 (1), each with its #130 word: foreign `agent_id` → `foreign_agent`; `pickup_by` now and now − 1 s → `pickup_passed`; now + 25 h + 1 s → `pickup_too_far`; inventory → `not_compliance`; 0 and 5,001 plugins, a duplicate `plugin_uuid` (also differing only in case), `timeout_s` 0 and 601 → `bad_plugins`; `max_parallel_plugins` 0 and 9 → `bad_parallel`. `agent_id` file missing, empty, non-UUID, two LFs, CRLF, leading space, 32-hex, a directory, over 64 bytes, two ids, trailing tab, NUL, braced, urn, hyphens moved, only LF, LF + space → `agent_id_unreadable` |
| CHK-M10-036 | CODE | L, W | `TestChecksAccepts` | PASS | Accepted: now + 25 h exactly; now + 1 ns; an uppercase `agent_id` in the job; a file without LF; an uppercase file; `[]` patterns; 5,000 plugins with `timeout_s` 1 and 600; parallel 1 and 8; the five TS defaults |
| CHK-M10-037 | CODE | L, W | `TestChecksOrder` | PASS | #132 (e) order: inventory + bad parallel → `not_compliance`; bad plugins + bad patterns → `bad_plugins`; bad plugins + bad parallel → `bad_plugins`; bad parallel + bad patterns → `bad_parallel`; bad patterns + foreign → `bad_patterns`; bad patterns + unreadable file → `bad_patterns`; unreadable + expired → `agent_id_unreadable`; foreign + expired and foreign + too far → `foreign_agent`; an expired replay → `pickup_passed` (seen is last) |
| CHK-M10-038 | CODE | L, W | `TestChecksRefusedIDRecorded` | PASS | REQ-236 (3): ids refused as foreign, bad parallel, bad patterns and too far are recorded, so the corrected resend is `replayed`. A plain replay → `replayed`. An uppercase replay → `replayed` |
| CHK-M10-039 | CODE | L, W | `TestChecksSeenBound` | PASS | REQ-236 (4): an id is still held at `pickup_by` + 1 min − 1 ns and forgotten at `pickup_by` + 1 min. Filled to 99,999: the 100,000th is accepted, and the next is `seen_full`. **Q2:** the `seen_full` job is not recorded, so the set stays at 100,000. At the bound, a foreign job keeps its own word. Once the filled ids expire, the job refused `seen_full` is accepted as a first run. `MaxSeen` = 100,000 |
| CHK-M10-040 | CODE | L, W | `TestChecksPatterns` | PASS | REQ-244 (1), (2) through the checks: 51 patterns, `(`, `a{1001}`, `\C`, `x*`, `(?:)`, `a?`, `\b`, `^` and `["ok","x*"]` → `bad_patterns`. 50 valid, the five defaults and `[]` → accepted. (REQ-244 (3), the manager-RE2-yes/Go-no case, is end to end: TASK-223's `refused_bad_patterns` row) |
| CHK-M10-041 | CODE | L, W | `TestChecksReadsAgentIDPerJob` | PASS | CHK-M10-393: after the file changes to another id, the next job for the old id is `foreign_agent` and one for the new id is accepted. A deleted file → `agent_id_unreadable` |
| CHK-M10-042 | CODE | L, W | `TestChecksStatic` | PASS | `checks.go` imports no `os/exec`, `log`, `log/slog`, `net` or `x/sys`, and calls no `time.Now`/`Since`/`Until`: the injected `now` is its only clock. It logs nothing (the `job_id` + word log line is the serve loop's, TASK-225, CHK-M10-167) |
| CHK-M10-043 | CODE | L, W | `TestChecksConcurrentSameID` (-race on W) | PASS | 16 goroutines at a barrier, one new id: exactly 1 accepted and 15 `replayed`; no race report |
| (extra) | CODE | W | `TestChecksAgentIDFIFOLinux` | PASS | A FIFO at the `agent_id` path → `agent_id_unreadable` at once (well under the 5 s bound); the check never blocks |
| CHK-M10-324 | CODE | W | plant: the kind check removed | PASS (red) | `TestChecksRefusals`, `TestChecksOrder` failed |
| CHK-M10-325 | CODE | W | plant: the `agent_id` comparison removed | PASS (red) | 5 tests failed (`Refusals`, `Order`, `RefusedIDRecorded`, `SeenBound`, `ReadsAgentIDPerJob`). The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-326 | CODE | W | plant: the window 26 h | PASS (red) | `TestChecksRefusals`, `TestChecksRefusedIDRecorded` failed |
| CHK-M10-327 | CODE | W | plant: the seen check removed | PASS (red) | `TestChecksRefusedIDRecorded`, `TestChecksConcurrentSameID` failed. The VM half is NOT RUN |
| CHK-M10-328 | CODE | W | plant: `pickup_by` = now accepted | PASS (red) | `TestChecksRefusals`, `TestChecksOrder` failed |
| CHK-M10-351 | CODE | W | plant: 51 patterns accepted (in `redact`) | PASS (red) | `TestChecksPatterns` failed (the G72 half; the G71 half is in TASK-210) |
| CHK-M10-352 | CODE | W | plant: a bad pattern skipped (in `redact`) | PASS (red) | `TestChecksPatterns` failed |
| CHK-M10-393 | CODE | W | plant: `agent_id` read once (`sync.Once` cache) | PASS (red) | `TestChecksReadsAgentIDPerJob` failed |
| extra 213a | CODE | W | plant: duplicates compared case-sensitively | PASS (red) | `TestChecksRefusals/duplicate_plugin_uuid_in_another_case` failed |
| extra 213b | CODE | W | plant: `timeout_s` 601 accepted | PASS (red) | `TestChecksRefusals` failed |
| extra 213c | CODE | W | plant: a `seen_full` job recorded (against Q2) | PASS (red) | `TestChecksSeenBound` failed |
| extra 213d | CODE | W | plant: refused ids not recorded | PASS (red) | `TestChecksRefusedIDRecorded` failed |
| extra 213e | CODE | W | plant: forgotten 1 ns after `pickup_by` + 1 min | PASS (red) | `TestChecksSeenBound` failed |
| extra 213f | CODE | W | plant: no type check and a blocking open | PASS (red) | `TestChecksAgentIDFIFOLinux` failed (blocked past 5 s) |
| extra 213g | CODE | W | plant: `max_parallel_plugins` 0 accepted | PASS (red) | `TestChecksRefusals` failed |

## Acceptance (TASK-213: "with a fake clock and a temporary agent_id file, REQ-236 (1)–(4) and REQ-244 (1), (2) hold, and the exec counter stays 0 for every refused request")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-236 (1) refusal table and accepted cases | CHK-M10-035, -036, -037 | PASS |
| REQ-236 (2) exec counter 0 for every refused request | `Checks` holds no executor and imports nothing that can start a process (CHK-M10-042). The counter through the socket is TASK-225's CHK-M10-165/-167 | PASS at this level |
| REQ-236 (3) refused id recorded | CHK-M10-038 | PASS |
| REQ-236 (4) expiry and the 100,000 bound | CHK-M10-039 | PASS |
| REQ-236 (5) through the driver on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-035 to -039 here and CHK-M10-167 (TASK-225) |
| REQ-244 (1), (2) through the checks | CHK-M10-040 | PASS |

## Notes (no finding)

1. On every call, `Check` walks the whole seen map to expire ids (up to 100,000 entries), so a job check is O(n) with n up to 100,000. That's a performance observation, not a correctness one: at one job per connection, a check costs about a millisecond. It is why the bound row fills the set directly instead of through 100,000 calls.
