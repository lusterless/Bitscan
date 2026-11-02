# TASK-209 TEST: PASS (r1)

Tester: tester-m10, 2026-10-30. Full rigor (protocol, TS §8.2 second approval). REQ-234; TS §3.7 L281–L283, §3.5 L249, L252, §6.5 L1165–L1184; #29, #60, #116 (a), #130 (b)–(e), (i), #131 (b), #140. Lead ruling Q1 (decisions row "tester-m10's M10 plan questions"): over the socket, out-of-bound jobs, including `max_parallel_plugins` 0 or 9, get `malformed`; inventory gets `not_compliance`.

Code under test (impl-agent-m10, `work/reports/TASK-209-impl.md`, r1): `agent/internal/runner/proto/frame.go` (sha256 `db691d15b463e71a…`) and `proto.go` (`cbfef864391248a1…`). Test file (new): `agent/internal/runner/proto/proto_test.go` (`d20390a47a62998c…`). Plan rows: CHK-M10-001 to -010, plus mutation rows CHK-M10-323 and -324 (`tests/m10/test-plan.md`). I wrote the plan rows before reading the code, then bound them to the interface. The interface additions are `RefusalFor` and `ErrNotCompliance`.

**Round 0 finding (fixed in r1):** `RefusalFor` mapped `max_parallel_plugins` 0 or 9 to `bad_parallel`, which goes against the lead's Q1 ruling. I raised it before the verdict, and impl-agent-m10 fixed it in r1 (`ErrBadParallel` removed). Every run below is on r1.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows, go1.27.2) | `go test -count=1 -v ./internal/runner/proto/` from `agent/` | **108/108 passed** (9 tests, 99 subtests), 0 failed, 0 errors, 0 skipped |
| W (WSL Ubuntu 24.04, `/root/bstest-m10-base`, go1.27.2 linux/amd64) | `go test -race -count=1 -v ./internal/runner/proto/` | **108/108 passed**, 0 failed, 0 errors, 0 skipped |
| static | `gofmt -l internal/runner/proto`, `golangci-lint run --uniq-by-line=false ./internal/runner/proto/` (Windows and `GOOS=linux`, v2.14.0), `GOOS=linux go vet` | clean, 0 issues |
| plants | 12 plants, each in its own `/root/bstest-m10-mut-<id>` (a copy of the base, removed afterwards), running only the named test | **12/12 red**, each a test failure (no build error) |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-001 | CODE | L, W | `TestRoundTrip` | PASS | A request, `accepted`, `done`, `refused` with each of the 13 words, and three results (plain; `runner_unavailable` with null exit; multi-byte + NUL + quotes, exit 137, both flags) round-trip to equal values. The header is the body length (BE uint32). Bodies are compact JSON. Exact wire shapes `{"type":"accepted"}`, `{"type":"done"}`, `{"type":"refused","reason":"busy"}` |
| CHK-M10-002 | CODE | L, W | `TestContractFixtureJobsCarriedUnchanged` | PASS | Every compliance job in `manager/tests/contract/fixtures/jobs/response_valid_*.json` (compliance, mixed, plugins_5000, ten_jobs) goes through WriteRequest → ReadRequest with its JSON deep-equal to the fixture |
| CHK-M10-003 | CODE | L, W | `TestRequestRefusals`, `TestRequestRecordedCases` | PASS | 31 refusals, each with a zero `Request` returned: `command` beside `job`; unknown key in the job or a plugin; `v` 0/2/"1"/1.0/missing; mpp missing/0/9/−1/"2"/1.5/null; job missing/null; 0 and 5,001 plugins; timeout 0/601; 51 patterns; two values; value + number; array; bare string; `plugins` without a job; `V`/`Job` case variants; broken JSON. `RefusalFor` gives `not_compliance` for the inventory job and `malformed` for all 30 others (Q1). Accepted: mpp 1 and 8, 5,000 plugins, 50 patterns, `[]`, uppercase agent id. `WriteRequest` refuses mpp 0/9 and v 2 and writes 0 bytes. **Recorded:** invalid UTF-8 inside `execute` is refused; a duplicate `v` key is accepted; trailing whitespace after the object is accepted |
| CHK-M10-004 | CODE | L, W | `TestFrameBounds` | PASS | Headers 33,554,433 (request), 1,048,577 (reply) and 0xFFFFFFFF are refused with `ErrFrame` after reading exactly 4 bytes (a reader that fails the test on any further read). At exactly 33,554,432 and 1,048,576 the body is read and refused as `ErrMalformed`, not `ErrFrame`. A valid ~30 MiB request (5,000 × 6,000-char commands) is accepted. A zero header, 2 header bytes, and 100 announced with 50 sent are each `ErrFrame` for request and reply. A clean EOF wraps `io.EOF`. Exactly one frame is consumed per read. Constants 33,554,432 / 1,048,576 / 65,536 / 16,384 / v 1 |
| CHK-M10-005 | CODE | L, W | `TestReplyRefusals` | PASS | 18 reply refusals, all `ErrMalformed`: unknown/missing/number `type`; extra keys on each shape; `accepted` with `reason`; `refused` with an unknown, empty, uppercase or missing word; `result` without `result`; an unknown key or `error: "timeout"` inside the item; `Type` case variant; two values; array. `WriteReply` refuses an unknown kind, an unknown word, a missing word and a zero `Result`, writing 0 bytes |
| CHK-M10-006 | CODE | L, W | `TestResultCaps` | PASS | By both `NewResult` and a hand-built reply frame: stdout 65,536 B ok and 65,537 refused (ASCII; 21,845 × `€` + 1/+2; 16,384 emoji / +1); stderr 16,384 ok, 16,385 and 8,192 × `é` + 1 refused; `error` null/`runner_unavailable`/`spool_overflow` ok, `timeout`/`""` refused; error with exit code, stdout or stderr refused; bad UUID refused; NUL kept. `NewResult` refuses invalid UTF-8 in stdout or stderr. A maximal item (65,536 + 16,384 × U+0001, 6 bytes each escaped) fits one reply frame |
| CHK-M10-007 | CODE | L, W | `TestResultEncapsulation` | PASS | `Result` has no exported field. The input item and `Item()`'s output are both copies (exit-code and error pointers too). The zero `Result` can't be sent |
| CHK-M10-008 | CODE | L, W | `TestUnavailableAndOverflow` | PASS | `UnavailableResult(uuid, now +01:00)`: exit null, empty streams, flags false, `runner_unavailable`, `started_at` = `finished_at` = now, sent in UTC `Z`. `OverflowMarker` keeps the uuid and both original timestamps (text equal), with exit null, empty streams, flags false and `spool_overflow`. Both pass `NewResult` and have exactly the nine Results keys |
| CHK-M10-009 | CODE | L, W | `TestNoCommandAPI` | PASS | AST listing: the exported API is `Item, NewResult, OverflowMarker, ReadReply, ReadRequest, RefusalFor, UnavailableResult, WriteReply, WriteRequest`. None takes a `string`, `[]string`, `[]byte`, rune or variadic string parameter, or any `wire` type other than `UUID`, `Job` or `ResultItem`. No exported struct field is a plain string or bytes. `Request` has exactly `V:int, Job:wire.Job, MaxParallelPlugins:int` |
| CHK-M10-010 | CODE | L, W | `TestPurityWordsAndErrors` | PASS | Non-test files import only the standard library and `internal/agent/wire`: no `os*`, `syscall`, `net*`, `log*`, `unsafe` or third-party import, and no platform file. The exported `Reason` constants are exactly the 13 #130 (d) words, and each can be sent. Request and reply decode errors, and `NewResult` errors, for canary-bearing inputs (unknown key, execute, `v`, bare body, type, reason, a 160 KB stdout) contain no canary. REQ-234 (5): passes on Windows and Linux |
| CHK-M10-323 | CODE | W | plant: `ReadRequest` uses `json.Unmarshal` instead of `wire.DecodeStrict` | PASS (red) | `TestRequestRefusals` failed ("command beside job" and the other unknown-key rows accepted) |
| CHK-M10-324 | CODE | W | plant: the `Kind` case of `checkRequest` removed | PASS (red) | `TestRequestRefusals` failed (inventory job accepted) |
| extra 209a | CODE | W | plant: body read before the length check | PASS (red) | `TestFrameBounds` failed (read past 4 bytes) |
| extra 209b | CODE | W | plant: zero-length frame allowed | PASS (red) | `TestFrameBounds` failed |
| extra 209c, d | CODE | W | plants: stdout cap + 1; stderr cap + 3 | PASS (red) | `TestResultCaps` failed for each |
| extra 209e | CODE | W | plant: error item may carry an exit code | PASS (red) | `TestResultCaps` failed |
| extra 209f | CODE | W | plant: refused word not validated on read | PASS (red) | `TestReplyRefusals` failed |
| extra 209g | CODE | W | plant: `Item()` returns the inner item without copying | PASS (red) | `TestResultEncapsulation` failed |
| extra 209h | CODE | W | plant: `RefusalFor` never answers `not_compliance` | PASS (red) | `TestRequestRefusals` failed |
| extra 209i | CODE | W | plant: stdout UTF-8 check removed | PASS (red) | `TestResultCaps` failed |
| extra 209j | CODE | W | plant: `accepted`/`done` decoded leniently | PASS (red) | `TestReplyRefusals` failed (extra keys accepted) |

## Acceptance (TASK-209: "Unit on Windows and Linux: REQ-234 (1)–(5) hold")

| REQ-234 | Rows | Verdict |
| --- | --- | --- |
| (1) round trips, fixtures carried unchanged | CHK-M10-001, -002 | PASS |
| (2) refused at decode without reading an oversize frame whole | CHK-M10-003, -004, -005; plants 323, 324, 209a, 209b | PASS |
| (3) result caps and error rules, by both NewResult and the decoder | CHK-M10-006, -007, -008 | PASS |
| (4) no command API | CHK-M10-009 | PASS |
| (5) Windows and Linux | L and W runs | PASS |

## Notes (no finding)

1. Recorded, not asserted (none of these is a REQ-234 criterion): a duplicate key (`{"v":1,"v":1,…}`) is accepted, because Go's decoder takes the last value and `checkShape` sees the collapsed map. That's consistent in both passes, so the value checked is the value used. Trailing whitespace after the object is accepted. The agent's own encoder never sends either.
2. G75 (the import-boundary half) and G78 are covered later by CHK-M10-196 and the serve-loop rows (TASK-225). 323 and 324 turn G75 red here; their G78 half is re-planted at TASK-225.
