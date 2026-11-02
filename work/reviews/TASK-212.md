# TASK-212 REVIEW: result spool store (`internal/spool`)

Verdict: APPROVED (r0, reviewer-m10, 2026-10-30; r1 delta `Spool.Release` APPROVED, reviewer-m10c, 2026-11-01, see the last section)

Reviewer: reviewer-m10, 2026-10-30. REQ-247. High risk, full rigor. Reviewed in two parts, persistence and then the API and in-flight state, per the decisions row "TASK-212 (spool) accepted as built at 489 code lines". **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-212-impl.md`: `agent/internal/spool/spool.go` (sha256 `3e9e668d…`) and `manifest.go` (`365adae8…`). `spool.go` already carries TASK-219's one-line `Put` call site (`s.fit`, line 224). I reviewed it as TASK-212's `ErrFull` slot only; `overflow.go` is TASK-219's. 489 code lines in 2 files, against an estimate of 180. The lead accepted the size; nothing in it is outside plan TASK-212 §2–§3.

TEST: PASS (`work/reports/TASK-212-test.md`). 21/21 on Windows and 23/23 on WSL with `-race`, and 13/13 real plants red (CHK-M10-356, -359, -366 and 10 extras). Each part has its own checks and plants.

Spec read: TS §3.1 L162, §3.3 L222, L224, L226, §3.5 L248, L251, §4.4 L577–L578; #4, #57, #78 (d), #131 (d), #139; plan TASK-212 §2–§3, §6.

My re-run (Windows): `go test -count=1 ./internal/spool/` ok. `gofmt -l` is empty, `golangci-lint run` gives 0 issues on Windows and with `GOOS=linux`, and `GOOS=linux go vet` is clean. The hashes match the test report.

## Part 1: persistence
1. **Atomic writes (REQ-247 (2)).** Each write follows the same sequence:
   - a stale `.tmp` is removed (a planted symlink there is unlinked, never followed);
   - the `.tmp` is created `O_EXCL` at 0600, then explicitly `Chmod`ed to 0600, so the mode doesn't depend on the umask;
   - it is written, fsynced and closed;
   - it is renamed into place;
   - the directory is fsynced.

   Only final names are ever read. `Open` deletes `.tmp` files unread. The crash hook at all four steps, for items and manifests, leaves the old or the new file, never a partial one (CHK-M10-028, plant 366 red).
2. **Reload fails closed.** Every item is decoded strictly and re-checked through `proto.NewResult`, so a truncated or over-cap file is removed and reported (`Dropped{…, unreadable}`), never sent. A missing, bad or foreign-id manifest drops its job. A job received more than 7 days ago is dropped as `expired` (`> keepFor`, boundaries tested). Every job that was neither finished nor interrupted is marked interrupted, so its items are sent and its final batch never is (#131 (d), plant 359 red).
3. **File safety (REQ-247 (6), (7)).**
   - `Lstat` refuses a symlinked spool path.
   - All access then goes through `os.Root`.
   - Job directories are taken only from real directories with lowercase UUID names, and items only from regular files with exact `%012d.json` names.
   - Files are 0600 and directories 0700 (Linux test).
   - Planted symlinks at an item, its `.tmp` or `job.json.tmp` are replaced, not written through. A symlinked `job.json` or job directory is not followed.
4. **Size (REQ-247 (1), #78 (d)).** The in-memory size is the sum of the manifest and item file sizes. It is updated after each successful write and removal, and matches the disk after every step of every test.

## Part 2: API and in-flight state
5. **Nothing but results reaches the spool (REQ-247 (5), TS §3.5 L248, L251).**
   - `Manifest` holds ids, the receive time and four booleans: no command, pattern or `eval_spec`.
   - The only write path for result data is `Put(id, proto.Result)`. A `Result` comes only from the runner's checked replies (or the #131/#140 constructors), and `Put` re-encodes it through `wire.Encode`, so a zero `Result{}` or one with an empty UUID is refused. This closes my TASK-209 nit 2 on the spool side.
   - The spool can't tell redacted text from raw. The guarantee is its input type, plus redaction in the runner (TASK-210, 214). `TestP1OnlyResultsAndNoCommand` checks the exported method set, and plant 356 is red.
6. **Defence in depth (CHK-M10-392).** `Put` refuses a plugin not in the job's manifest (`ErrUnknownPlugin`), an unknown job and an ended job.
7. **Batch sequencing (#139, #141).**
   - The start notice comes first.
   - Items follow in `seq` order, at most `maxItems`, within the body bound (28 bytes of frame + item sizes + commas, verified to keep the encoded body ≤ the bound).
   - A finished job then gets an empty final, or the last items batch carries `final` itself.
   - An interrupted job never gets a final.
   - A running job's partial batch is held until its oldest item is `holdYoung` old (29 s held, 30 s sent).
   - At most one batch per job is in flight. A batch that was never handed out, or one already settled, cannot be settled.
   - A dropped notice still lets the items go (#139 (e)).
   - 8 × 40 concurrent puts with one drainer under `-race`: each item is handed out exactly once.
8. **Errors.** Every error is wrapped with `%w` or is a fixed sentinel. None contains file content or a path from input. Nothing in the package logs.

## NOT RUN rows and cover
None. Every row is pure or Linux-only and ran in WSL. The spool's behaviour on a real host under the agent unit is a G76 row: `ReadWritePaths=/var/lib/bitscan-agent`, and `UMask=0077` doesn't matter here because of the explicit `Chmod`. That needs no extra cover beyond these tests.

## Findings
None blocking or should-fix.

1. nit, `spool.go:227-233` with `manifest.go:93-99`: `writeFile` can return an error **after** the rename, when the directory fsync fails. `Put` then returns an error without indexing the file or advancing `nextSeq`. The durable item is then:
   - left uncounted in `Size()`;
   - overwritten by the next `Put` of that job (same seq);
   - deleted with the job directory;
   - or, after a restart, loaded and sent.

   Every outcome stays closed: nothing raw, no duplicate the manager can't handle (first result wins), and a size drift of one item at most. Consider advancing `nextSeq` before the write, so a seq is never reused, and indexing the item when the error came after the rename.
2. nit, `spool.go:297-303`: an item that fails to decode at `Next` time is removed with no log line and no `last_error`. `Open` reports the same case through `Dropped`. The `Log` field exists, so consider one line with `job_id` and the seq. It's a can't-happen path: the file was validated and fsynced when written.
3. nit, `spool.go:292-309`: `batch` reads up to 50 item files from disk before deciding the hold rule, and `Put` wakes the sender after every result. So a running job with a young partial batch re-reads its items on every wake. Deciding the hold from `j.items` (sizes and `putAt`) before reading would avoid the I/O.
4. nit, plan-level, `spool.go:335-337`: `Drop` of an items batch that carried `final` marks `FinalAcked`. The manager then never receives a final for that job, so it ends by deadline (`partial`) and M9 creates its single retry, which re-runs the job on the host. That matches plan §2 ("same removal"), and TS §4.4 handles it. An empty final queued after a dropped final-carrying batch would avoid the re-run. It's a TASK-220 question for the sender's answer handling, if the lead wants it.
5. nit, `spool.go:88`: a spool directory that already exists is not re-moded to 0700. It sits inside the 0700 state directory, so nothing is exposed.

Cross-task notes, not findings for this task:
- `StartJob` answers `ErrFull` when even the manifest won't fit (accepted by the lead). When the spool is full, a new job is then not run at all, rather than displacing older results. I'll check in TASK-219 and 223 that this shows as `last_error` (it does: `compliance.go:42-45`) and that the manager's never-started path handles it.
- On a `Put` error the handler finishes the job without filling the remaining plugins (`compliance.go:74-76`). I'll judge that in TASK-223.

## r1 delta: `Spool.Release` (reviewer-m10c, 2026-11-01): APPROVED

Ruling: decisions row "#140 reading: in-flight protection covers only an outstanding HTTP attempt" (a frozen-API delta the lead approved). Scope: `spool.go:321-336`, the new `Release` method only. `spool.go` is now `a0e6ab18…`. No other line of the file changed for r1.

TEST: PASS (`work/reports/TASK-212-test.md`, "r1 delta"). New file `release_test.go`, portable:
- Windows: 32/32;
- WSL `-race`: 158/158, spool plus loops;
- plants: 3/3 red (`relnoop`, `reljobonly`, `relany`).

My re-run: `go test -count=1 ./internal/spool/` passes on Windows. `gofmt`, vet and golangci-lint are clean on Windows and with `GOOS=linux`.

Checks against the brief (Release only clears the in-flight mark):
1. Under `s.mu`, `Release` finds the job. It refuses with `errNotInFlight` if the job is unknown or not in flight, the same as `Ack` and `Drop`. It then clears `j.flight` and each item's `flight`, and nothing else.
2. **No removal:**
   - there is no `removeItems` and no `removeJob` call;
   - no file is written;
   - `size` is unchanged.

   R1-1 compares the sha256 of every file, the manifest included.
3. **No start or final bookkeeping:** `StartAcked` and `FinalAcked` are untouched. R1-1 shows the start notice handed out again after its release, and the same items with `final` handed out again.
4. **Released items can be converted again by overflow**, and the next `Next` builds a fresh batch, so the retry carries the marker, never the old body (R1-3; the `reljobonly` plant is red). The binary-level overflow walk (TASK-220 report) shows the same thing end to end.

Only the one sender calls `Release`, as `Ack` and `Drop` are called, and at most one batch per job is in flight, so clearing every item mark of the job clears exactly the released batch. The r1 delta has no findings. The r0 nits stay as accepted (decisions 2026-11-01 (3)).
