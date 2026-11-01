# TASK-212 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (spool, TS §8.2 second approval). REQ-247; TS §3.3 L222, L224, L226, §3.5 L248, §4.4 L577–L578; #4, #57, #78 (d), #131 (d), #139. Tested in two parts, each with its own checks and plants, per the lead's ruling (decisions row "TASK-212 (spool) accepted as built at 489 code lines"):
- part 1: persistence;
- part 2: the API and in-flight state.

Code under test (impl-agent-m10b, `work/reports/TASK-212-impl.md`): `agent/internal/spool/spool.go` (sha256 `3e9e668de2723114…`, which includes TASK-219's `Put` call site) and `manifest.go` (`365adae8231f4eb8…`). TASK-219's `overflow.go` (`b40f234e8fecaadf…`) is in the tree; no row below relies on `Put` answering `ErrFull`.

Test files (new):
- `agent/internal/spool/spool_test.go` (internal package `spool`, so the crash hook can be set; `bc923c0dd9d340b2…`)
- `agent/internal/spool/spool_linux_test.go` (`8807d88dbebb51b9…`)

Plan rows: CHK-M10-025 to -034, plus mutation rows CHK-M10-356, -359 and -366.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v ./internal/spool/` | **21/21 passed** (the 2 Linux-only tests are not built there), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/spool/` | **23/23 passed**, 0 failed, 0 errors, 0 skipped |
| static | gofmt; `golangci-lint run --uniq-by-line=false ./internal/spool/` (Windows and `GOOS=linux`) | clean |
| plants | 14 runs, each in its own `/root/bstest-m10-mut-<id>` | **13/13 real plants red**. One plant (`212h`, open mode 0644) stayed green because the code also `Chmod`s to 0600. That's a correct second guard; its companion `212h2` (the `Chmod` at 0644) is red |

## Part 1: persistence (manifest, items, reload, expiry, crash, modes, symlinks)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-025, -026, -029 | CODE | L, W | `TestP1ReopenOrderAndInterrupted` | PASS | REQ-247 (1), (3). `Size()` equals the bytes on disk after every write. Two jobs: job 2 received first, job 1 a second later with the lower id. After reopen nothing is dropped and the order is: job 2 start, job 2 `[001 002 003]` with `final`, then job 1 start, job 1 `[001 002]` with **no** final (it was running, so now interrupted, #131 (d); CHK-M10-359). `Put` to the interrupted job → `ErrJobEnded`. The spool is empty (0 bytes, no directories) once everything is answered |
| CHK-M10-028 | CODE | L, W | `TestP1CrashBetweenSteps` (8 subtests) | PASS | REQ-247 (2), CHK-M10-366. The crash hook fires at each of `created`, `written`, `synced` and `renamed`, for an item and for the manifest. Reopen leaves no `.tmp` and `Size()` = disk. A crashed item is absent for the three pre-rename steps and complete after `renamed`. A crashed manifest write keeps the old manifest (interrupted, no final) before the rename and the new one (final) after it |
| CHK-M10-028 | CODE | L, W | `TestP1PlantedPartialFiles` | PASS | Planted on disk: a truncated item, an item with 65,537 bytes of stdout (fails `proto.NewResult`), a partial `.tmp` item, a partial `job.json.tmp`, and a truncated `job.json` in a second job. `Open` reports `Dropped{job1, 2, unreadable}` and `Dropped{job2, 0, unreadable}`, removes job 2's directory, keeps `Size()` = disk, and delivers only plugin 1 of job 1 |
| CHK-M10-030 | CODE | L, W | `TestP1Expiry` | PASS | REQ-247 (4): received 7 d − 1 s and exactly 7 d ago → kept; 7 d + 1 s → `Dropped{job, 2, expired}`, size 0, nothing offered |
| CHK-M10-031 | CODE | L, W | `TestP1OnlyResultsAndNoCommand` | PASS | REQ-247 (5), CHK-M10-356, and "only redacted output can be written". Every exported method of `*Spool` takes only `wire.UUID`, `[]wire.UUID`, `proto.Result`, `spool.Batch`, `int` or `time.Duration`: no string, bytes, reader or `wire.ResultItem` write path. The manifest's keys are exactly `job_id, received_at, plugins, start_acked, finished, interrupted, final_acked`. No spool file holds an `execute` or `redaction_patterns` key. Together with `TestP1PlantedPartialFiles`, this shows that only items passing `proto.NewResult` are ever read back. (The spool cannot tell redacted text from raw; the guarantee is that its only input type is the runner's `proto.Result`, and the runner redacts, TASK-214) |
| CHK-M10-032 | CODE | W | `TestP1ModesLinux` | PASS | REQ-247 (6): the spool directory, the job directory and every file: dirs 0700, files 0600 |
| CHK-M10-033 | CODE | W | `TestP1SymlinksLinux` | PASS | REQ-247 (7). A symlinked spool directory is refused by `Open`. Symlinks to an outside file planted as the next item, the next item's `.tmp` and `job.json.tmp` are replaced, never followed: `Put`, `Put` and `Finish` succeed, and the outside file is unchanged with nothing created beside it. A symlinked `job.json` and a symlinked job directory at `Open` are not followed. **Recorded:** that job is dropped `unreadable`; a later `StartJob` of the symlinked id fails; the outside file is still unchanged |

| Plant (part 1) | Result | Evidence |
| --- | --- | --- |
| CHK-M10-366: no temporary file (write straight to the item name) | PASS (red) | `TestP1CrashBetweenSteps` failed |
| CHK-M10-359: a running job reopened as finished | PASS (red) | `TestP1ReopenOrderAndInterrupted` failed (a final was posted) |
| CHK-M10-356: an `execute` field added to the manifest | PASS (red) | `TestP1OnlyResultsAndNoCommand` failed |
| 212a: expiry window 7 d + 1 s | PASS (red) | `TestP1Expiry` failed |
| 212b: an item failing `NewResult` is read back as an unavailable item | PASS (red) | `TestP1PlantedPartialFiles` failed |
| 212e: size not reduced when items are removed | PASS (red) | `TestP1ReopenOrderAndInterrupted`, `TestP2InFlightAndFinal` failed |
| 212g: `os.Stat` instead of `os.Lstat` on the spool path | PASS (red) | `TestP1SymlinksLinux` failed |
| 212h2: files chmodded 0644 | PASS (red) | `TestP1ModesLinux` failed |
| 212h: `O_CREATE` at 0644 (with the `Chmod` 0600 kept) | green: not a fault | the explicit `Chmod` keeps 0600, a correct second guard |

## Part 2: the API and in-flight state

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-034 | CODE | L, W | `TestP2StartJobRules` | PASS | An uppercase job id is stored lowercase, and its lowercase plugin is accepted. Refused: a duplicate job, 0 plugins, 5,001 plugins, a bad job uuid, a bad plugin uuid. 5,000 is accepted. **`ErrFull` when the manifest doesn't fit** (100-byte spool), with 0 bytes and no directory left |
| CHK-M10-034 | CODE | L, W | `TestP2PutRules` | PASS | Unknown job → `ErrUnknownJob`. **A plugin not in the job → `ErrUnknownPlugin`** (CHK-M10-392 defence). A zero `Result` is refused. An uppercase plugin is accepted. After `Finish`: `Put` and a second `Finish` → `ErrJobEnded`. `Finish` of an unknown job → `ErrUnknownJob` |
| CHK-M10-026, -027 | CODE | L, W | `TestP2NextHoldAndBounds` | PASS | The start notice comes first. **Hold (#141):** 3 items of a running job are held at 29 s and go at 30 s. 50 ready items go at once. Size bound: ~40 KiB items under a 100,000-byte bound → 2 per batch, and the encoded body ≤ the bound. A single item over the bound still goes, alone |
| CHK-M10-026, -027 | CODE | L, W | `TestP2InFlightAndFinal` | PASS | **In flight:** with job 1's notice out, `Next` offers job 2's notice, then nothing. A batch that was never handed out can't be settled, and the same batch can't be settled twice. A **dropped** notice still lets the items go (#139 (e)). A finished job with nothing left → an empty `final`; nothing after it; the directory is removed. The last items batch carries `final` itself. Size is 0 at the end |
| CHK-M10-034 | CODE | L, W | `TestP2ConcurrentPutAndDrain` (-race on W) | PASS | 8 jobs × 40 items put from 8 goroutines while one drainer does `Next`/`Ack`: 320 distinct items, each handed out exactly once, 8 finals, size = disk, no race report |

| Plant (part 2) | Result | Evidence |
| --- | --- | --- |
| 212c: the in-flight check removed | PASS (red) | `TestP2InFlightAndFinal` failed |
| 212d: the hold rule removed | PASS (red) | `TestP2NextHoldAndBounds` failed |
| 212f: the `ErrUnknownPlugin` check removed | PASS (red) | `TestP2PutRules` failed |
| 212i: the `StartJob` `ErrFull` bound ×1000 | PASS (red) | `TestP2StartJobRules` failed |

## Acceptance (TASK-212: "in a temporary directory with a fake clock, REQ-247 (1)–(7) hold")

| REQ-247 | Rows | Verdict |
| --- | --- | --- |
| (1) put, list in order, ack; size = bytes on disk | CHK-M10-025, -026, `checkSize` after every step | PASS |
| (2) crash between any two steps | CHK-M10-028 (8 hook points + planted partial files), plant 366 | PASS |
| (3) reopen order; running job interrupted | CHK-M10-029, plant 359 | PASS |
| (4) 7 d + 1 s dropped | CHK-M10-030, plant 212a | PASS |
| (5) no `execute` or pattern in the spool; only results | CHK-M10-031, plant 356 | PASS |
| (6) 0600 / 0700 | CHK-M10-032, plant 212h2 | PASS |
| (7) a planted symlink is never written through | CHK-M10-033, plant 212g | PASS |

No finding against the product. The `Put`/overflow behaviour is TASK-219's.

## r1 delta: `Spool.Release` (tester-m10c, 2026-11-01)

Decisions "#140 reading: in-flight protection covers only an outstanding HTTP attempt". Only the new method is under test. File: `agent/internal/spool/release_test.go`, new and portable.

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test ./internal/spool/` | **32/32 passed** (the 29 earlier plus 3 new) |
| W (WSL, -race) | `go test -race ./internal/spool/ ./internal/agent/loops/` | **158/158 passed** |
| plants | 3 in `spool.go` (throwaway copies) | **3/3 red** |

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| R1-1 Release only clears the in-flight mark | CODE | L, W | `TestReleaseOnlyClearsInFlight` | PASS | Releasing the start notice and then an items-with-final batch leaves `Size()`, every file and the manifest bytes unchanged (sha256 per file). The next `Next` hands out the start notice again (StartAcked stays false), then the same items with `final` (FinalAcked stays false) |
| R1-2 a batch never handed out is an error | CODE | L, W | `TestReleaseOfABatchNeverHandedOut`, plus the acked case | PASS | Release errors for an unknown job, for a start notice never handed out, for the same batch twice, and for an acked batch. The refusals change nothing on disk |
| R1-3 released items are convertible; the retry is fresh | CODE | L, W | `TestReleasedItemsConvertible` | PASS | 4 × 64 KiB are handed out, then released. A `Put` that needs room converts the oldest released item, and the next batch carries its marker first and the newest result whole, within the 300,000 bound |
| plant: Release does nothing | CODE | W | `relnoop` | PASS (red) | `TestReleaseOnlyClearsInFlight` failed (nothing handed out again) |
| plant: Release clears the job's mark only | CODE | W | `reljobonly` | PASS (red) | "the oldest released item was not converted: the retry would resend the old body" |
| plant: Release of a batch not in flight accepted | CODE | W | `relany` | PASS (red) | "Release of an acked batch: no error"; "Release of an unknown job's batch: no error" |

Binary level: the overflow walk (`e2e/agent_binary_m10.sh overflow`, TASK-220 report) shows that a released batch's items become markers.
