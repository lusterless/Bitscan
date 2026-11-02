# TASK-223 REVIEW: compliance handler, run state and heartbeat (`internal/agent/loops`), r0 and r1

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-245, REQ-249 (2)–(4), REQ-250 (1)–(3). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-223-impl.md` (r0, r1), all in `agent/internal/agent/loops/`:
- `compliance.go` (sha256 `c98e6aba…`, new);
- `jobs.go` (`eb809e8f…`, the #74 handler removed);
- `pull.go` (`cd6a6365…`);
- `run.go` (`0fa172f4…`);
- `heartbeat.go` (`0645a3ba…`).

That is five files, as the task row lists. r1 changes `compliance.go` only.

TEST: PASS at r1 (`work/reports/TASK-223-test.md`).
- WSL `-race`: 158/158.
- Plants: 19/19 red, made up of 10 handler, r1 and nil-handler plants and the 9 CHK-M10-271 plants.
- The PD-45 old-to-new list is recorded, and CHK-M4-223 is rewritten as CHK-M10-271 per the user's decision (2026-11-01 (2)).

Spec read:
- TS §1.1 G2; §3 L152; §3.3 L202, L211–L212, L222, L224, L226; §3.5 L248–L252; §3.7 L275, L282; §4.4 L575–L577; §6.5;
- #28, #78 (c)–(e), #131;
- decisions rows "TASK-223 … nil-handler choice", "PD-45 rewrite … accepted", "#140 reading …" (TASK-223 r1), "The PD-45 compliance tests are Linux-only" and "User decisions before the M10 merge" (2).

My re-run (Windows host):
- `gofmt`, `go vet` and `golangci-lint run ./...` are clean on Windows and with `GOOS=linux`.
- The handler rows are Linux-only, because M4's state store fsyncs a directory. The five pre-existing M4 Windows failures are recorded in TASK-220's review.

## Checks
1. **r1: after any `Put` error, no plugin is silently left out** (the brief).
   - **A result can't be spooled.** `onResult`'s `Put` fails, and the client returns that error unwrapped as a `Failure`. `fill(…, overflow=true)` then stores a `spool_overflow` marker (exit null, empty streams) for every plugin with no stored result, including the plugin whose result failed and the ones that never ran.
   - **The runner is unavailable.** `fill(…, false)` stores `runner_unavailable`. After the first `Put` error it switches to markers for the rest.
   - **A marker can't be stored either.** Those plugins are counted, and there is one ERROR line with `job_id` and `count` only (no output). `last_error` is set to `spool: results not kept`.
   - `TestR1PutErrorFillsMarkers` and `TestR1MarkersCannotBeStored` cover this, and plants `nofill`, `unavailfill` and `nolost` are red.
   - UUIDs are lower-cased on both sides (`lowerID`, and spool `Put`), so the `got` map and the spool's plugin check agree.
2. **Whole job to the runner, never resent** (REQ-245; #131 (b)). One `Runner.Run` per job, with the clamped `max_parallel_plugins`. On a `Failure`:
   - the received results are kept;
   - the rest are filled;
   - `last_error` becomes `runner_unavailable: <word>`, sent once and then cleared (#78 (e));
   - the job is finished.

   CHK-M10-074 checks this for 8 words. CHK-M10-358 shows one runner request.
3. **Stopping mid-job** (#131 (d)). When the ctx ends, `Handle` returns with no fill and no `Finish`, so no final is ever sent. CHK-M10-076 and -359 show this at binary level.
4. **The job never lands on disk** (REQ-245; TS §3.5 L248). The handler keeps only the plugin uuids. The job, and with it every `execute` and pattern, lives only in the `Handle` call. CHK-M10-077 runs a canary sweep over the state dir and the logs, and plant 356 is red.
5. **One job at a time; inventory never blocked** (REQ-249).
   - Compliance runs in one worker, so plant 369 is red.
   - `pickup_by` is re-checked at start.
   - Inventory has its own worker (CHK-M10-078, and CHK-M10-370 at binary level).
6. **Nil handler** (ruled choice). It is refused per job through `Puller.refuse`, with `last_error` set. The pull loop and inventory keep running (G2), so both plants (`panic`, early return) are red.
7. **Heartbeat** (REQ-250).
   - `spool_bytes` is `Deps.SpoolBytes()`: nil gives 0, and it is never negative (plant 367 is red).
   - A heartbeat answer never reaches the handler or runner (plant 384 is red, through CHK-M10-271).
8. **The CHK-M4-223 rewrite** (user decision (2)), `pull_test.go:713-787`. It doesn't weaken the no-other-job-source guard.
   - The old checks are all kept: no `os/exec`, `syscall.Exec`, `ForkExec` or `os.StartProcess`, and `RunJob`/`Handle` called only from `pull.go`/`jobs.go`.
   - `runner.sock` and AF_UNIX in every spelling Go offers are allowed **only** in `internal/agent/runnerclient`. The spellings are network names, `net.*Unix*`, `syscall`/`unix` AF_UNIX and socket calls, and the `x/sys/unix` import.
   - New and stricter: dialling only in `runnerclient` and `transport`, and listening nowhere.
   - The test fails if the allowed site isn't actually seen (≥ 2 sites), so a broken walk can't pass. 9/9 plants are red.
9. **PD-45 `TestPD45RunnerUnavailableFill` change** (`compliance_linux_test.go:301-352`). It's not a loosening; I confirmed this to main on 2026-11-01. Up to the first final the test still requires:
   - exactly 3 items over all posts;
   - the received one kept;
   - 2 fill items of the right shape;
   - the final as the last post;
   - 1 runner request.

   A missing fill item, or a final posted before the fills, is still red. The dropped "final holds items" assertion was stricter than #141, which allows an empty final.

## NOT RUN rows and cover
- **Not run:** the handler against the real runner and manager on a sandbox host (G79, the agent half of G78). These are NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:**
  - the WSL rows with the real spool, sender and `runnerclient` against a fake runner;
  - the binary walk (TASK-227);
  - the real runner under its verbatim unit (TASK-228).

  That is adequate.
- **Unproven on a real host:** the full chain from agent to real runner to real manager, in one run.

## Findings
None blocking or should-fix.

1. nit, `compliance.go:57-59`: when the ctx ends in the window after the runner returned `done`, the job is left unfinished instead of finished. The next start marks it interrupted, so its items are sent but no final. The manager then ends it by deadline (`partial`), and M9 retries it once. This fails closed and is rare.
