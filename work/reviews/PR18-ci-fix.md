# PR #18 CI fixes REVIEW: test-side fixes and TASK-229 r3

Verdict: APPROVED (one approval)

The scheduler-flake fix is approved on the code. Its run evidence is still to come; see finding 1.

Reviewer: reviewer-m10c, 2026-11-01.

Inputs:
- `work/reports/PR18-ci-fix-test.md` (tester-m10d);
- `work/reports/TASK-229-impl.md` "Revision 3" (impl-deploy-m10c);
- decisions row "PR #18 CI fixes accepted" (2026-11-01).

Scope reviewed, in the working-tree diff against the M10 commits (`6861532`):
- `agent/internal/agent/runnerclient/client_linux_test.go`;
- `agent/internal/capread/capread_linux_test.go`;
- `agent/internal/sdsock/sdsock_linux_test.go`;
- `agent/internal/agent/loops/compliance_linux_test.go`;
- `agent/internal/agent/loops/compliance_r1_linux_test.go`;
- `manager/tests/test_jobs_api_pg.py`;
- `manager/tests/test_serve_scheduler_linux.py`;
- `.github/workflows/agent.yml` (TASK-229 r3).

No product file changed.

My re-run (Windows host):
- `gofmt -l agent` prints nothing.
- `GOOS=linux golangci-lint run ./...` v2.14.0 reports 0 issues.
- `ruff check` and `ruff format --check` on both manager test files: clean.
- The rows themselves are Linux-only and Postgres-backed, so the run evidence is the tester's.

## Checks
1. **Root-only rows: named skip plus a required root step. Enforced, not only skipped.**
   - **The test change.** The three tests (`TestConnectPermissionDeniedLinux`, `TestPeerCheckThroughSdsock`, `TestPeerCheck`) change only their non-root guard, from `t.Fatal` to a named `t.Skip`. That's the M4 form (`state_linux_test.go:474`). No assertion changed.
   - **Coverage of the skips.** A grep of every `Geteuid`/`t.Skip` in the agent tests finds exactly these three M10 skips, and all three are listed in the root step.
   - **Where the step runs.** "Root-only tests (sudo)" (`agent.yml` L202-L232) is in the `go-test-ubuntu` matrix, so it runs on `ubuntu-22.04` and `ubuntu-24.04`. Each binary is built as the job user and run under `sudo` with `-test.run "^<Test>$"`.
   - **The step is red on any of:**
     - a failed `go test -c` (GitHub's `bash -e`);
     - a non-zero test exit (`|| rc=1`);
     - no top-level `^--- PASS: <Test> (` line. That covers both a missing test and a binary that ran nothing;
     - any `--- FAIL` or `--- SKIP` line, subtests included, because the grep is unanchored.

     So a skip can't pass the step. R4 shows this: the same body run without root exits 1.
   - **Plant evidence.** R5 shows why the step is needed: with the peer check removed, the non-root suites are fully green. As root, all of these are red:
     - CHK-M10-320 (peer check removed), in both sdsock and capread;
     - CHK-M10-321 (gid compared instead of uid);
     - EACCES retried as busy.
   - **Verdict on this item:** not a loosening. The rows were never enforceable in a non-root `go test`. Now CI enforces them, which was not the case before.
2. **`TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`** (`compliance_r1_linux_test.go:395-450`).
   - **The assertion is unchanged:** heartbeat `spool_bytes` == `Spool.Size()`. It is now checked at a defined moment:
     - after `job.json` holds both `start_acked` and `finished` true, with every post answered 503 so nothing changes after that;
     - against every heartbeat built after that point. The test skips index n, which may have been mid-build;
     - with a check that `Size()` stays unchanged afterwards.
   - **Is the 1-byte mismatch a product bug?** No. I checked the product path the tester cites: `heartbeat.go` passes `Spool.Size()` through under the spool lock, and each manifest rewrite is exactly `len("false") - len("true")`. So the mismatch is the test's read timing.
   - **Plants:** `spool_bytes` 0 and `+1` are both still red. The diagnosis plant reproduces CI's exact numbers on the old test.
3. **`TestPD45Batches/50_plugins`** (`compliance_linux_test.go:422-548`).
   - **What changed.** "The 503 retry repeats the bytes" is replaced by `sameResults`.
   - **Why.** TASK-220 r1, which I approved, rebuilds the batch with `Next` after each failed attempt. A full batch can therefore leave as `final=false` before `Finish` and come back `final=true`. The byte-equality assertion contradicts the approved r1 behaviour, and the lead's ruling records the old-to-new change.
   - **What the new check still requires:**
     - the same plugin set and count;
     - no plugin missing, extra or twice;
     - each item `DeepEqual` either to the 503'd item or to its `OverflowMarker`;
     - a final 503'd post stays final.
   - **Kept unchanged:** the start notice first, ≤ 50 items and ≤ 1,572,864 bytes per post, only the last post final, nothing posted twice after acceptance, the total equal to n.
   - **Plants:** a lost item, a duplicate and a changed result are all red.
   - **Verdict on this item:** this is the narrowest check that still fits r1. Not a loosening.
4. **Manager `test_jobs_api_pg.py:726-758`.**
   - The REQ-214 (2) block now runs in `try/finally`. The `finally` deletes the row it committed, parameterised by its own job id, as `planted_default_row` does. Every assertion is unchanged.
   - The two default-partition checks (`test_schema_scanning`, `test_fleet_alerts_pg`) are untouched and still demand an empty `scan_result_default`.
   - The cause: a fixed October 2026 date plus the m0005 partition window starting at the current month. That's a test time-bomb. It doesn't depend on M10 and isn't a product defect, so no product change is right.
   - M4 shows the cleanup also runs when the test fails.
5. **Manager `test_serve_scheduler_linux.py`** (the flake fix).
   - **The old proxy.** "In flight" used to mean "running at `signalled`". Serve stops uvicorn and the catalog before the scheduler, so a run that started after SIGTERM but before `SchedulerRunner.stop()` could still meet the stop flag and log `SchedulerStopping`, while the proxy didn't count it.
   - **The new definition.** The harness now records the moment `stop()` begins, by wrapping it in the launched child script only; this is test code. A run counts as in flight if it ended after that moment, which is exactly the set of runs that can meet the stop flag. The test also asserts there is exactly one such moment and that it comes after `signalled`.
   - **Kept unchanged:**
     - no overlap of the same job;
     - every run closed;
     - only `SchedulerStopping` failures;
     - each job's failures ≤ its in-flight count;
     - no unknown job.
   - **Verdict on this item:** this isn't a loosening. A run that spanned `signalled` but ended before `stop()` began is no longer counted, which is stricter. The G27 test (`test_sigterm_waits_for_the_running_sweep_and_nothing_runs_after_close`) keeps the "nothing runs after close" guard.

## NOT RUN rows and cover
- **The hosted CI run of the root step and of the fixed tests.** The step body ran in WSL in three ways:
  - as root, giving exit 0 (R3);
  - without root, giving exit 1 (R4);
  - with plants, giving exit 1 (R6).

  Only the PR run confirms `sudo`, `setpriv` and `python3` on both hosted images.
- **actionlint and shellcheck:** not installed.

## Findings
None blocking or should-fix.

1. Evidence note, owner tester-m10d or `main`: the scheduler fix has no run record yet. `PR18-ci-fix-test.md` describes the race but not a run of the fix. Please add a short record:
   - the test passing several times in WSL;
   - ideally a plant that starts a sweep between SIGTERM and `stop()` and stays green;
   - a plant that logs a non-`SchedulerStopping` failure and is red.

   I approve on the code reading; PR CI is the backstop.
2. nit, `agent.yml` root step: `--- SKIP` is matched anywhere in the log. That's right today, because the three tests have no optional skips of their own. If one ever gains a legitimate sub-skip, the step goes red, which fails closed.
