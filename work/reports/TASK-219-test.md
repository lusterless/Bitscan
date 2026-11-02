# TASK-219 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (spool overflow, TS §8.2 second approval). REQ-248; TS §3.3 L226, §6.5 L1184, §4.5 L593; #140.

Code under test (impl-agent-m10b, `work/reports/TASK-219-impl.md`): `agent/internal/spool/overflow.go` (sha256 `b40f234e8fecaadf…`) and the `Put` call site in `spool.go` (`3e9e668de2723114…`). Test file (new): `agent/internal/spool/overflow_test.go` (`9dcb385ff311e2af…`, internal package, for the crash hook). Plan rows: CHK-M10-059 to -064, plus mutation rows CHK-M10-364 and -365.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 ./internal/spool/` (whole package, TASK-212 rows included) | ok: **29/29 passed** (L builds no Linux file), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/spool/` | **31/31 passed** (8 of them overflow tests and subtests), 0 failed, 0 errors, 0 skipped |
| static | golangci-lint (Windows) | clean |
| plants | 5 | **5/5 red** |

One test bug was fixed before the verdict: the across-jobs row drained without finishing the jobs, so the held batches never came out and the asserts held vacuously. It now finishes both jobs and checks the item counts first.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-059 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (1): a 1 MiB spool and 30 results of 64 KiB stdout. After every `Put`, both `Size()` and the disk bytes are ≤ 1,048,576, and `Size()` = disk. The oldest results are markers and the newest are whole, with no whole result before a marker. **Recorded:** 15 markers, 15 whole. The conversion is logged and no output is in the log |
| CHK-M10-060 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (2): once drained, every one of the 30 plugins is posted exactly once, in seq order. Each marker keeps its own `plugin_uuid`, `started_at` and `finished_at` (CHK-M10-365: no result vanishes) |
| CHK-M10-061 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (3): each marker passes `proto.NewResult` and the strict `ResultItem` decode. `error` = `spool_overflow`, `exit_code` null, empty streams, flags false (the #140 shape) |
| CHK-M10-062 | CODE | L, W | `TestOverflowSparesInFlight` | PASS | REQ-248 (4): with 4 results handed out by `Next` and not answered, a `Put` that needs room converts none of them; the new item is stored as a marker instead. After the `Ack`, later items that aren't in flight are converted first |
| CHK-M10-063 | CODE | L, W | `TestOverflowAcrossJobs`, `TestOverflowNewItemAndMarkerDrop` | PASS | Across jobs, the older job's results convert first: job 1 `[marker × 3]`, job 2 whole. A result bigger than the whole spool is stored as a marker, not refused. With 39 more markers into a 3,000-byte spool, the oldest markers are dropped with a log line, the size stays ≤ the bound with `Size()` = disk, everything left is a marker, and the newest marker survives |
| CHK-M10-064 | CODE | L, W | `TestOverflowConversionAtomic` (3 subtests) | PASS | A crash at `created`, `written` or `synced` while a result is rewritten as a marker → after reopen the item is still the whole, complete result under its seq, nothing is dropped, and size = disk |
| CHK-M10-364 | CODE | W | plant: newest converted first (reverse order) | PASS (red) | `TestOverflowOldestFirst`, `AcrossJobs`, `SparesInFlight` failed |
| CHK-M10-365 | CODE | W | plant: a dropped result becomes `runner_unavailable` (no `spool_overflow` marker) | PASS (red) | the overflow tests failed |
| extra 219a | CODE | W | plant: in-flight items converted | PASS (red) | `TestOverflowSparesInFlight` failed |
| extra 219b | CODE | W | plant: no new-item marker (`ErrFull` instead) | PASS (red) | `NewItemAndMarkerDrop`, `SparesInFlight` failed |
| extra 219c | CODE | W | plant: whole results dropped instead of markers | PASS (red) | `TestOverflowNewItemAndMarkerDrop` failed |

## Acceptance (TASK-219: "REQ-248 (1), (2) and (4) hold and the size never exceeds the bound after any Put")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| (1) oldest → markers, newest whole, ≤ 1 MiB | CHK-M10-059, plant 364 | PASS |
| (2) each converted result posted exactly once as its own marker | CHK-M10-060, plant 365 | PASS |
| (3) markers valid; M9 intake stores them ERROR `spool_overflow` | CHK-M10-061 (the M9 intake half is M9's REQ-215 (3), unchanged) | PASS |
| (4) an in-flight batch not converted | CHK-M10-062, plant 219a | PASS |
| size never over the bound after any `Put` | every `Put` in CHK-M10-059, -063 | PASS |

No finding.
