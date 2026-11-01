# TASK-225 REVIEW: runner serve loop (`internal/runner/serve.go`)

Verdict: APPROVED (round 3, r1)

Reviewer: reviewer-m10c. Rounds 1–2 were on 2026-11-01 and round 3 on 2026-11-02. REQ-234, REQ-235 (4), REQ-236 (2), REQ-261. High risk, full rigor. **PD-43: the TS §8.2 second approval is to be re-applied after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-225-impl.md` (r0, and r1 with its fatal-path extension): `agent/internal/runner/serve.go` only. Its sha256 is `a21528c8…` at r0 and `03cca52a…` at r1. It is portable (no build tag).

TEST:
- **r0 PASS** (`work/reports/TASK-225-test.md`): WSL `-race` 26/26, plus the fast rows re-run 5 times; 9/9 plants red.
- **r1 PASS** (`work/reports/PR18-ci-fix-test.md` §6):
  - fast rows 3750/3750 at `-count=50 -cpu 1,2,4`, both as uid 1000 and as root;
  - deadline rows 12/12;
  - three new rows;
  - plants P1 (LIFO defers restored), P2 (`handle`'s close-to-wake restored) and P4 (the `failed` check removed) all red;
  - control P3 (the r1 order with a 2 ms gap) green.

Spec read:
- TS §3.5 L250 and §3.7 L281–L285;
- #130 (b)–(g);
- Q1 of "tester-m10's M10 plan questions";
- decisions rows "TASK-224 (job) and TASK-225 (serve) design points" (1), (2), "TASK-225 r1: clear busy before the connection is closed" and "TASK-225 r1 scope".

My re-run on the Windows host, at r1:
- `gofmt` prints nothing.
- `go vet ./internal/runner/` is clean on Windows, and with `GOOS=linux -tags delegated`.
- `golangci-lint run` gives 0 issues on Windows and with `GOOS=linux`.
- The hash matches the tester's.

## Round 1: CHANGES_REQUESTED (test file only)
1. **should-fix** (gate G8, owner tester-m10c), `serve_linux_test.go:177`: gosec G115 on `uint32(len(body))`. **Fixed in round 2** with a checked bound, no `nolint`.

## Round 3 (r1): busy cleared before the close, and no job after a fatal error
Cause: on the PR #18 22.04 CI run, the TestServeMalformed subtests after the first got `refused busy`. The handler's defers ran LIFO, so the connection closed before `busy` was cleared. A client that saw EOF and dialled again could then be refused while the runner was idle.

1. **Order** (`serve.go:85-90`). One deferred func runs:
   1. `busy.Store(false)`;
   2. `conn.Close()`;
   3. `wg.Done()`, last, so `Serve`'s `wg.Wait` covers the close.

   By then `handle` has returned, and it ends every job-side step itself:
   - `Exec.Run` waits for all plugin goroutines, releases them, and runs the sweep and the `TmpDirs` emptying;
   - then comes the `done` reply;
   - then the reader is woken and `<-readDone` is waited on.

   So clearing `busy` there can't let two jobs overlap.
2. **Reader wake** (`serve.go:138-145`). `handle` wakes its 1-byte reader with `SetReadDeadline(time.Now())` instead of a close. A deadline also applies to a `Read` that is already pending (`net.Conn` contract). If setting it fails, the fallback is a close, so `<-readDone` can't hang. Client close and half-close still cancel the executor within 1 s; the r0 row stays green.
3. **No job after a failed cleanup** (scope (2); TS §3.5 L250; the fail-closed rule for executor errors).
   - Inside `once.Do`, the order is `s.fatal`, then `failed.Store(true)`, then the listener close. All of that runs before the deferred `busy.Store(false)`.
   - The accept loop checks `failed` **after** the busy CAS. When it's set, the connection is closed with no reply and `Serve` returns `s.fatal` after `wg.Wait`.
   - Why that placement is exact: a won CAS read either the initial `false` (no job has run yet) or the `false` stored after `failed=true`. Go's atomics are sequentially consistent, so the following `Load` sees `failed`.
   - A check before the CAS, as the decisions text says, would leave a window between the check and the CAS. The code is right; the text should follow it (finding 2).
   - A lost CAS also checks the flag, so no `busy` reply goes out after a fatal error, and the agent doesn't retry into a dying runner.
   - `s.fatal` is read only after the atomic `Load`, so there is no data race.
   - Rows: `TestServeNoJobAfterFatal`, deterministic, with a listener that hands out a connection after `Close` (plant P4 red), and `TestServeTightDialAroundFatal`.
4. **Accepted-path busy row.** `TestServeNextConnectionAfterEndNeverBusy` runs 200 rounds that cycle through a decode refusal, a check refusal and a finished job, dialling again at once each time. No round is refused busy. Plant P2 is red only on the job rounds, as expected.
5. **Unchanged from r0:**
   - one request per connection, decoded strictly as a single frame;
   - the checks run before `accepted`;
   - the 30 s and 60 s deadlines;
   - `emit` under a mutex;
   - fixed-word logs (the canary sweep stays green);
   - the `Listener` interface.

## NOT RUN rows and cover
- **REQ-261 host part (G78 through the driver, CHK-M10-280 to -289) and the VM half of CHK-M10-391:** NOT RUN under the VM hold, the named gate exception (decisions 2026-11-01 (1)).
  - Cover: the socket rows above with the real `Checks`, plus TASK-213's checks and TASK-217's peer check. That is adequate for the serve loop.
- **r1 on hosted 22.04:** proven only by the PR's re-run, which is where the r0 defect showed.
- **Unproven on a real host:** the loop behind the real `sdsock` listener under `bitscan-runner.socket`.

## Findings
None blocking or should-fix.

1. nit, `serve.go:95-101` (r0, unchanged): a silent `bitscan`-uid peer holds the one slot for the full 30 s request deadline. This is bounded, and the tester recorded it (CHK-M10-168).
2. Note for `main` (decisions text, not code): row "TASK-225 r1 scope" (2) says to check the fatal flag "before the CAS". The built check is after the CAS, which is the exact placement (check 3). Align the row's text with the code.
