# TASK-220 REVIEW: results sender (`internal/agent/loops/results.go`), r0 and r1

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-246 (1)–(6). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-220-impl.md` (r0, r1): `agent/internal/agent/loops/results.go` (sha256 `a6763fc7…`), new, portable, 111 code lines in 1 file.

reviewer-m10 found at r0 that the batch was held in flight through the whole back-off. That is the #140 finding, ruled in decisions "#140 reading: in-flight protection covers only an outstanding HTTP attempt". r1 is the fix, and it uses TASK-212 r1's `Spool.Release`.

TEST: PASS at r1 (`work/reports/TASK-220-test.md`).
- Windows: 115/115 (23 × 5).
- WSL `-race`: 158/158 (spool + loops).
- Binary overflow walk: 18/18.
- Plants: 8/8 red. Plant (d) (no `Release`) is red both at unit level and through the binary walk.

Spec read: TS §3.3 L222, L224, L226; §3.5 L253; §6.5 Results; #57, #139 (d), (e), #141; the #140 ruling.

My re-run (Windows host):
- `gofmt` prints nothing.
- `go vet` is clean on Windows and with `GOOS=linux`.
- `golangci-lint run ./...` gives 0 issues on Windows and with `GOOS=linux`.
- `go test ./internal/spool/` passes.

On Windows, five M4 pull rows in `./internal/agent/loops/` fail: TestJobChecks, TestJobSeenSevenDays, TestJobSeenBeforeAct, TestJobDispatchOrder and TestJobPickupRecheckedAtStart. They go through M4's `state.writeFile` → `syncDir` (a directory fsync), which Windows refuses. `internal/agent/state` is unchanged since M4. This is the pre-existing Windows limit recorded in "The PD-45 compliance tests are Linux-only". Not M10, not this task.

## Checks
1. **r1: release before the back-off, a fresh body after it** (the brief).
   - A `Wait` or `Retry` answer leaves the batch in flight. `Loop` then calls `Spool.Release(b)` **before** `schedule.Sleep(back.Next())`, and only then goes back to `Spool.Next`.
   - The old body is never kept or resent. `post` builds the body from the batch it is given, and every retry is a new `Next`.
   - `TestSenderRetryIsFresh` checks this: a Put during the back-off converts the oldest released item, the retry body differs, and it carries `001:spool_overflow`.
   - The binary walk shows the same: the first 503'd batch's plugins (001–005) end as markers, the newest stay whole, and all 30 are posted once.
   - The back-off keeps its sequence across the release: gaps of exactly 10/20/40 s, capped at 5 min. It is reset only on `Success` or `Drop`.
2. **The M4 answer classes** (TS §3.3 L224).
   - 200: `Ack`.
   - 400/404/409/413/422 and a 403 other than `pending_approval`: `Drop` that batch only. Later batches are still posted (#139 (e)), the batch is not retried, and `last_error` is set through `Run.Call`.
   - 429, 5xx and network errors: release and back off.
   - 403 `pending_approval`: release and back off. That still keeps the results (nothing is dropped), which is the agent rule's "keep the batch". The builder's choice is fine.
   - 401: `Run.Call` stops every loop, and so does a cut attempt after SIGTERM (`Stop`).

   CHK-M10-068, -362 and -363 cover these.
3. **Batches** (REQ-246 (1)–(3), TS §3.5 L253).
   - The start notice `{"results":[],"final":false}` goes first.
   - A batch holds at most 50 items and at most 1,572,864 bytes of uncompressed JSON. That bound is enforced by `Next`'s byte accounting and was checked with escaping-heavy and maximal items.
   - Every body is gzip (`Content-Encoding: gzip`) and decodes strictly.
   - Only the last batch is final.

   CHK-M10-065 to -067 cover these; plants 360, 361 and 368 are red.
4. **The 30 s rule and ordering** (REQ-246 (5), (6)).
   - A running job's partial batch is held until its oldest item is 30 s old (CHK-M10-069; the `holdYoung = 29 s` plant is red).
   - One goroutine posts, and the spool keeps one batch per job in flight, so the final never overtakes an unanswered batch (CHK-M10-070).
5. **No idle polling.** With an empty spool the sender waits only for `Wake` or the Run's end. The `hold` timer re-arms only while `Size() > 0`.
6. **Logs.** Only `job_id` and fixed words: no item, stdout or token (CHK-M10-072).

## NOT RUN rows and cover
- **Not run:** the sender against the real M9 manager (G79). It is NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** the unit rows with a fake manager, the binary walk, and M9's own intake tests of the same contract. That is adequate.
- **Unproven on a real host:** the gzip body accepted by the real manager's 1.5 MB decompressed cap under load.

## Findings
None blocking or should-fix.

1. nit (documented by the builder, confirmed by `TestSenderLatePostLimit`): a `Wake` with nothing new can arm the 30 s timer early. A result spooled later is then posted up to 30 s after the rule says, 40 s after spooling in the row. That's bounded and only affects latency.
