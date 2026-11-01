# PR #18 CI fix (tester-m10d): test-side fixes, PASS

Tester: tester-m10d, 2026-11-01. Tree: worktree `Bitscan-m10`, branch `m10-runner` (PR #18). Only test files were changed. No product file was edited, and no plant was left in the worktree.

CI runs read: agent.yml run **41292894924** (`go test (linux/amd64)` red on ubuntu-22.04 and ubuntu-24.04, so the delegated step never ran) and manager.yml run **41292894919** (`pytest with coverage gate` red twice on the same test).

Environments:
- **WN:** WSL Ubuntu 24.04, as the non-root user `bstester` (uid 1000, no sudo). This is the CI condition. Go `/opt/go1.27.2`, with my own GOCACHE and GOMODCACHE (`/home/bstester/m10d`), and a copy of the worktree at `/home/bstester/m10d/fix`.
- **WR:** the same copy run as root (GOCACHE `/root/m10d`).
- **WM:** WSL as root, a full worktree copy at `/root/m10d/repo`, my own venv (`/root/m10d/venv`, `pip install --require-hashes -r manager/requirements-dev.txt`, then `-e manager`), Docker 29.9.1 for Testcontainers.
- **L:** Windows 11 (lint only).

Every Go run used `-race -count=1` unless a count is given. Plants were made only in throwaway copies (`/home/bstester/m10d/p-*`, `/root/m10d/p-*`) by a script that refuses the worktree path and requires each edit to match exactly once.

## Verdict

| # | Failure | Cause | Kind | Fix |
| --- | --- | --- | --- | --- |
| 1 | `TestConnectPermissionDeniedLinux`, `TestPeerCheckThroughSdsock`, `TestPeerCheck` FAIL as non-root | each one called `t.Fatal` when euid ≠ 0, and CI's `go test` runs as the non-root runner user | test | a named `t.Skip` when not root (the M4 form), **plus a new root step in agent.yml** (needs impl-deploy, below) that runs them under sudo and is red unless each one passed |
| 2 | `TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`: spool_bytes 180969, Size 180968 | test race: the heartbeat was built between the last `Put` and `Finish`, and `Finish` rewrites `job.json` 1 byte shorter | test (no product off-by-one) | compare only once the spool is at rest, against a heartbeat built after that point |
| 3 | `TestPD45Batches/50_plugins`: "the retry after a 503 sent different bytes" | TASK-220 r1 rebuilds the batch with `Next` after each failed attempt, so a full 50-item batch posted before `Finish` (final=false) comes back as the final (final=true) | test (expected behaviour) | old → new assertion: same plugins, each once, each the same result or its marker; a final copy stays final |
| 4 | manager `test_default_partition_is_empty_after_migrate`: `scan_result_default` holds 1 row (both attempts) | an M9 test, `test_jobs_api_pg.py::test_well_formed_batches_for_jobs_that_cannot_take_them_are_409`, commits a result for a job dated 2026-10-23. Since 2026-11-01, `db migrate` creates no October partition, so the row lands in the default partition of the shared session database | test, date-dependent (not M10, not product) | the culprit removes its stored row in a `finally`, as `planted_default_row` does; the assertion is unchanged |
| 5 | manager flake `test_slow_runs_never_execute_twice_at_once` (attempt 1 only) | test race: serve sets the scheduler's stop flag only after the uvicorn and catalog shutdown, so a run that starts after `signalled` can still give up with `SchedulerStopping`, but it wasn't counted as in flight | test (not product) | the launcher traces when `SchedulerRunner.stop()` begins; "in flight" = still running at that moment; the assertion is unchanged (§5) |

## 1. Root-only rows

**Cause.** All three began with `if os.Geteuid() != 0 { t.Fatal(...) }`. They pass only as root, because they run peers or the client as other uids through `setpriv`. Every M10 run of them (TASK-217, -218 r1, -222) was in WSL as root. CI's `go test ./...` runs as the hosted runner's non-root user. The delegated step can't host them either: it runs as `bitscan-runner` with only `CAP_DAC_READ_SEARCH` and `NoNewPrivileges=yes`, and `setpriv --reuid` needs CAP_SETUID/CAP_SETGID.

**Choice: (a), a named skip plus a root CI step, not (b), a build tag.**
- It matches the M4 rows. M4 handles euid-dependent rows with a **named `t.Skip`** that says which run covers the row: `state_linux_test.go:474` ("named skip: root reads mode-0000 files; this case runs in the bstester run") and `inventory/watch_linux_test.go:680` ("needs a non-root user; run this test as bstester"). Those rows run in CI only because CI happens to be non-root. Build tags are used only for the `delegated` rows, which need a delegated cgroup subtree as `bitscan-runner`; a plain root run can't give them that either.
- The rows stay compiled and linted by the plain `golangci-lint run ./...`. A tag would need a third lint invocation, and the child helpers (`TestEACCESChild`, `TestCapreadChild`, `TestSdsockChild`) and shared helpers would have to move with them or trip `unused`.
- A WSL root run (`go test ./...` as root, the way every M10 task tested them) still runs them with no flag.
- The cost is that the plain non-root run only shows SKIP. That is why the root step is **required**: evidence R5 below shows that with the peer check removed, the non-root sdsock and capread suites are fully green, so nothing else in CI would catch CHK-M10-320.

**Change** (test files only):
- `agent/internal/agent/runnerclient/client_linux_test.go` `TestConnectPermissionDeniedLinux`: `t.Fatal("needs root to run the client as nobody")` → `t.Skip("named skip: needs root to run the client as nobody (setpriv); this row runs in agent.yml's root step and in WSL as root")`.
- `agent/internal/capread/capread_linux_test.go` `TestPeerCheckThroughSdsock` and `agent/internal/sdsock/sdsock_linux_test.go` `TestPeerCheck`: `t.Fatal(...)` → `t.Skip("named skip: needs root to run peers as other uids (setpriv); this row runs in agent.yml's root step and in WSL as root")`.
- Each test gets a comment naming the root step. Nothing else in the tests changed.

**agent.yml change needed (impl-deploy).** In job `go-test-ubuntu`, add this step right after `go test (linux/amd64)` (before the delegated step):

```yaml
      # Root-only rows (named skips in the non-root go test above): the
      # sdsock and capread peer checks and the runner client's EACCES case
      # run peers or the client as other uids through setpriv, which needs
      # root. Built as this user, run under sudo. Red unless each named test
      # passed; a skip, a missing row or any FAIL is red.
      - name: Root-only tests (sudo)
        working-directory: agent
        run: |
          dir="$(mktemp -d)"
          chmod 0755 "$dir"
          rc=0
          for spec in \
            "internal/agent/runnerclient:TestConnectPermissionDeniedLinux" \
            "internal/capread:TestPeerCheckThroughSdsock" \
            "internal/sdsock:TestPeerCheck"; do
            pkg="${spec%%:*}"
            test="${spec#*:}"
            name="$(basename "$pkg")"
            GOOS=linux GOARCH=amd64 go test -c -race -o "$dir/$name.test" "./$pkg/"
            log="$RUNNER_TEMP/root-$name.log"
            (cd "$pkg" && sudo "$dir/$name.test" -test.run "^$test\$" -test.count=1 -test.v) 2>&1 | tee "$log" || rc=1
            if ! grep -qE "^--- PASS: $test \(" "$log"; then
              echo "root-only row $test did not pass as root"
              rc=1
            fi
            if grep -qE -- '--- (FAIL|SKIP)' "$log"; then
              echo "$name: a root-only row failed or skipped (above)"
              rc=1
            fi
          done
          exit "$rc"
```

It needs `setpriv` (util-linux) and `python3`, both on the hosted Ubuntu images. `sudo`'s default secure_path finds both. The binaries are built as the job user, so no root-owned files land in the Go cache. Until this step lands, the three rows are only skipped in CI, so **PR #18 should not merge before it**.

**Evidence.** The step body above was run as `root-step.sh` (byte-identical apart from two emulation hooks: `SUDO=""`, and building as uid 1000 through `setpriv`, because `bstester` has no sudo).

| Row | Where | Command | Result |
| --- | --- | --- | --- |
| R1 | WN | `go test -race -count=1 -json` loops, runnerclient, capread, sdsock (copy of the fix) | **195/198 passed, 0 failed, 3 skipped**. The 3 skips are exactly the named rows. loops 124/124, runnerclient 37/38, capread 18/19, sdsock 16/17 |
| R2 | WR | same, as root | **201/201 passed, 0 failed, 0 skipped**. loops 124, runnerclient 38, capread 19, sdsock 20 (TestPeerCheck's 3 subtests run) |
| R3 | WR | the root step, emulated (built as uid 1000, run as root) | **exit 0**. `--- PASS: TestConnectPermissionDeniedLinux` (child: `WORD=connect FAILURE=true CTX=false RESULTS=0 UID=65534 SECONDS=0.0`), `--- PASS: TestPeerCheckThroughSdsock`, `--- PASS: TestPeerCheck` with its 3 subtests |
| R4 | WN | the root step without root (every row skips) | **exit 1**. Each row: `--- SKIP` then "root-only row … did not pass as root" and "a root-only row failed or skipped". The step can't go green on skips |
| R5 | WN | plain non-root run of sdsock and capread with the peer check removed (CHK-M10-320 plant) | **34/36 passed, 0 failed, 2 skipped** (the two named rows). So without the root step, CI misses a removed peer check |
| R6 | WR | the root step on a copy with the peer check removed and EACCES retried as busy | **exit 1**: all three rows `--- FAIL` |
| R0 | WN | baseline: the unfixed tree, non-root | 195/198 passed, **3 failed** (the three rows, with the CI messages) |

Root plants, each in its own copy, run as root (WR):

| Plant | Test | Result |
| --- | --- | --- |
| CHK-M10-320, peer check removed (`peer_linux.go`: `if true \|\| …`) | sdsock `TestPeerCheck` | red: 1/4 passed, 3 failed; `peer [0 0] got "ok"`, `uid 64999 with gid 0 got "ok"` |
| CHK-M10-320, the same | capread `TestPeerCheckThroughSdsock` | red: `peer uid 0 got "ok\nserved"` |
| CHK-M10-321, gid compared, not uid (`return cred.Gid`) | sdsock `TestPeerCheck` | red: 1/4 passed; `peer [64998 64999] got "ok"`, `uid 64999 with gid 0 got "ok"` |
| EACCES retried as busy (dial error → `refused_busy`) | runnerclient `TestConnectPermissionDeniedLinux` | red: `WORD=refused_busy … SECONDS=28.0` |

## 2. spool_bytes 180969 vs Size 180968: a test race, not a product off-by-one

**Product path checked.** `heartbeat.go:50` sets `SpoolBytes: r.spoolBytes()`, and `heartbeat.go:91-96` returns `max(r.d.SpoolBytes(), 0)`. Both the test harness (`compliance_r1_linux_test.go:102`) and the agent (`cmd/bitscan-agent/main.go:102`) wire `SpoolBytes` straight to `sp.Size`, and `spool.go:254-258` returns `s.size` under the spool lock. There is no arithmetic of its own, so the heartbeat reports the spool's exact size at the moment the body is built.

**What moves the size by 1 byte.** `Size` includes `job.json` (`manifest.go:126`, `s.size += n - j.mSize`). `job.json` is rewritten when the start notice is acknowledged (`spool.go:351-358`, `"start_acked":false` → `true`) and at `Finish` (`spool.go:239-251`, `"finished":false` → `true`). Each rewrite is exactly 1 byte shorter (`len("false") - len("true")`).

**The race.** The test took the **first** heartbeat over 180,000 bytes, then read `Spool.Size()` later, on the assumption that neither changes after the job finishes ("both unchanged since the job finished"). The three ~60 kB results pass 180,000 only after the third `Put`. A heartbeat built between that `Put` and `Finish` (whose fsyncs make the window wider on a slow disk) carries the size from before `Finish`. By the time the test reads `Size()`, `Finish` has landed, so the two differ by exactly 1 byte: 180969 vs 180968, which is what CI saw.

**Diagnosis plant (shows it is the reading moment).** In a copy of the **old** test, a 200 ms sleep before `Finish` (`compliance.go:70`) widens the window, and a 300 ms sleep before the test reads `Size()` stands in for a late test goroutine. Result: **0/3 passed**, every time `heartbeat spool_bytes 180969, Spool.Size() 180968`, the same numbers as CI. The **new** test with the same product delay: **3/3 passed**.

**Fix** (`compliance_r1_linux_test.go`, `TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`). The assertion is unchanged (heartbeat `spool_bytes` == `Spool.Size()`), but it is now checked at a defined moment:
1. Drive until `job.json` holds both `"start_acked":true` and `"finished":true`. Every results post is answered 503, so after that nothing changes the spool.
2. Read `Size()`. It takes the spool lock, so `Finish` has already counted the new manifest. The size must be over 180,000.
3. Record the heartbeat count n. The heartbeat loop builds one body at a time, so every heartbeat from index n+1 on was built after step 2. Each one must carry exactly that size.
4. `Size()` must be unchanged afterwards. The runner-call assertions that follow are kept as they were.

Plants on the new test (WN): CHK-M10-367, spool_bytes 0 → red (`heartbeat 12 at rest: spool_bytes 0, Spool.Size() 180968`). spool_bytes + 1 → red (`spool_bytes 180969, Spool.Size() 180968`).

## 3. TestPD45Batches/50_plugins: old → new expectation

**Why the bytes differ.** TASK-220 r1 (decisions "#140 reading", 2026-10-30) releases a batch after every failed attempt (`results.go:65-67`, `Spool.Release`) and rebuilds it with `Next` before the retry. With 50 plugins the batch is full, so it is handed out as soon as the 50th result is spooled, possibly before `Compliance.Handle` calls `Finish` (`compliance.go:70`). That first attempt goes out with `final=false` and is answered 503. By the time of the retry the job has finished, and a batch that empties a finished job is its final batch (`spool.go` `Next` doc), so the retry goes out with `final=true`: the same 50 results in different bytes. 1, 51, 120 and 5,000 plugins can't hit this. With 1 plugin the batch isn't full, so it is held until the job finishes. With 51 or more, the first batch never empties the job. That matches CI, where only 50_plugins failed.

**Why it passed in WSL.** Timing. On a fast disk the sender's `Next` after the 50th `Put` usually runs after `Finish` (two fsyncs) has landed, so both attempts are built from a finished job (final=true) and the bytes match. On the slower 22.04 runner the sender won the race. The diagnosis plant makes the CI order certain: a 20 ms sleep before `Finish` turns the **old** test red **5/5** ("the retry after a 503 sent different bytes"), and the **new** test passes **5/5** with the same plant.

**Old → new.**
- Old: `bytes.Equal(res[1].req.Body, res[2].req.Body)`: the retry after a 503 repeats the 503'd post byte for byte.
- New (`sameResults`): the retry holds exactly the 503'd post's plugins (the same count, none missing, none extra, none twice; the 503'd post itself has no duplicate), and each item is either `reflect.DeepEqual` to the 503'd item or to its `proto.OverflowMarker`. A 503'd post that was final must stay final; final=false → true is allowed.
- Kept unchanged: the start notice is first and empty; every post ≤ 50 items and ≤ 1,572,864 bytes uncompressed; only the last post is final; no plugin is posted twice after acceptance; the total equals n; a retry happened.

Plants on the new test (WN): a lost item (`Release` drops the oldest item) → red in all 5 sizes ("holds 49 results, the 503'd post 50", "holds 0 results, the 503'd post 1", "holds plugin …051, which the 503'd post did not"). A duplicate (with the 20 ms window: the final retry repeats item 0 in place of item 1) → red 3/3 ("holds plugin …001 twice"). A changed result (with the window: the final retry's stdout gains "x") → red 3/3 ("the retry changed plugin …001's result: {…"stdout":"out 0x"…}, was {…"out 0"…}"). The marker branch isn't exercised here (a 50 MB spool never converts); conversion and markers are covered by TASK-219's overflow rows. The "final stays final" check has no plant of its own: a retry that drops `final` leaves the job without a final post, so the test's drive condition would time out (red after 120 s) before reaching `sameResults`.

## Stress and static gates

| Check | Where | Result |
| --- | --- | --- |
| `TestHandlerSpoolBytesAndNoRunnerFromHeartbeat` ×20 | WN | **20/20 passed** |
| `TestPD45Batches` 1/50/51/120 plugins ×10 at `-cpu 1,2,4` | WN | **150/150 passed** |
| spool_bytes + PD45 5000 plugins ×3 at `-cpu 1,2` | WN | **18/18 passed** |
| `gofmt -l agent` | WR and L | prints nothing |
| `golangci-lint run ./...` v2.14.0, GOOS=linux | WR (native) and L (`GOOS=linux GOARCH=amd64`) | **0 issues** in both |
| `golangci-lint run --build-tags delegated ./...` | WR and L | **0 issues** in both |

The full agent suite was not re-run. Only these five test files changed, and per the speed rules the full suite runs at the milestone gate and in CI.

## 4. Manager: `test_default_partition_is_empty_after_migrate`

**CI flags.** manager.yml runs `pytest --cov=bitscan_manager/services --cov-fail-under=85` from `manager/` with `CI=true` and the pinned Ryuk image. There is **no `-n`** (pyproject has no addopts), so CI runs the suite serially, in file name order, on one session database (`conftest.pg_server` / `migrated_db`) shared by every test that doesn't take `own_migrated_server`. The new M10 test files didn't change the order: everything before `test_schema_scanning.py` is unchanged since M9.

**Which test writes the row.** I used an out-of-repo diagnostic plugin (`-p default_probe`, nothing added to the repo). After each test it counts `scan_result_default` on the session database and records the first test after which the count changed, with the row's details. WM run, CI conditions (`CI=true`, serial, the same order), every file up to and including `test_schema_scanning.py`: **2 failed, 9,977 passed** in 51 min. The failures were `test_default_partition_is_empty_after_migrate` (`assert 1 == 0`, the CI failure, reproduced) and `test_readme_m5_walk_linux.py` ("the web UI build is missing", because my copy has no `web/` build; it doesn't touch the database). The probe saw exactly one change, after `tests/test_jobs_api_pg.py::test_well_formed_batches_for_jobs_that_cannot_take_them_are_409`: count 0 → 1. The row has `job_created_at 2026-10-23 11:57:00+00`, a compliance job created at that time, stdout `install ok installed`, and policy `M9 policy …`, the test's REQ-214 (2) case (`test_jobs_api_pg.py:726-746`). That case creates its own dispatched job with `created_at=T0 - 3 min` (T0 = 2026-10-23 12:00 UTC) through `sf.owner_job`, which commits, and posts one result. The real intake stores it (200, accepted 1), and the row is committed.

**Why now.** m0005 creates the `scan_result` partitions for the current UTC month and the next three (`PARTITION_MONTHS = 4`, `m0005_privileges_seeds.py:97,137`, from `datetime.now(UTC)`). Up to 2026-10-31, the database CI migrated had `scan_result_2026_10`, so the row went there, and M9's CI and the M10 gate (G18) were green. The PR #18 run was on **2026-11-01** (UTC), so the freshly migrated database starts at 2026-11, and the October-dated row falls into `scan_result_default`. This doesn't depend on M10: **main would now fail the same way** on any re-run.

**Product or test?** Test. The intake copies `job_created_at` from the job (TS §5.2: the trigger requires them equal), and the default partition exists to catch rows outside the monthly window (TS §5.3; `fleet_alerts.py:136` alerts on it). In production a job's `created_at` is `now()`, inside a partition that `db maintain` keeps. The October date comes only from the test's fixed clock. No migration or seed writes the row: the probe saw 0 rows after every earlier test, including the migrate.

**Other tests hit.** The suite relies on the shared database's default partition being empty: `test_fleet_alerts_pg.py::test_default_partition_rows` asserts no `default_partition_rows` alert before it plants and removes its own row (`planted_default_row`, `test_fleet_alerts_pg.py:343-362`). In CI order that file runs before the culprit, so it was green. Run after the culprit, it fails too (evidence M2).

**Fix** (`manager/tests/test_jobs_api_pg.py`, test file only). The REQ-214 (2) block is wrapped in `try/finally`. The `finally` deletes the stored result as `bitscan_owner` (`DELETE FROM scan_result WHERE job_id = %s`, the job's own id), as `planted_default_row` does. Every assertion is unchanged: 200 with `{"accepted": 1, "duplicates": 0}`, no refusal entry, results count + 1. `test_default_partition_is_empty_after_migrate` and `test_default_partition_rows` are untouched.

I considered and rejected two alternatives. (a) Giving the "after migrate" check a database of its own would leave the leak in place for `test_fleet_alerts_pg`. (b) Re-dating the job to the real `now()` would change the test's clock semantics (dispatch and pickup windows against its fixed `Clock`).

| Row | Where | Command | Result |
| --- | --- | --- | --- |
| M1 | WM | serial, CI=true, every file ≤ `test_schema_scanning.py`, unfixed tree, with the probe | **9,977 passed, 2 failed** (the CI failure reproduced, plus the no-web-build row); probe: the culprit leaves 1 row |
| M2 | WM | the culprit, then `test_fleet_alerts_pg.py::test_default_partition_rows`, then `test_schema_scanning.py::test_default_partition_is_empty_after_migrate`, unfixed tree | **1/3 passed, 2 failed**: `default_partition_rows` alert present (`assert [...] == []`) and `assert 1 == 0` |
| M3 | WM | the same three, fixed tree | **3/3 passed**; probe: no change in `scan_result_default` after any test |
| M4 | WM | plant: the culprit fails after the result is stored (it expects + 2) | culprit red (`assert 1 == (0 + 2)`), the next two **green**, no row left: the `finally` cleans up on failure too |
| M5 | WM | `test_fleet_alerts_pg.py test_jobs_api_pg.py test_schema_scanning.py`, serial (CI) | **119/119 passed**, 0 failed, 0 skipped |
| M6 | WM | the same, `-n 2` | **119/119 passed**, 0 failed, 0 skipped |
| M7 | WM | the rest of the suite (`test_jobs_api_pg.py`, then all 38 files after `test_schema_scanning.py`), fixed tree, serial, with the probe | **1,322 passed, 0 failed, 3 errors**. The errors are `test_security_m5.py` rows needing the web UI build, which my copy lacks (environment; CI builds it). Probe: **no change** in `scan_result_default` after any test. With M1, the culprit is the only test in the suite that leaves a default-partition row |
| M8 | WM | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | "All checks passed!"; 386 files already formatted; "Success: no issues found in 386 source files" |

## 5. Manager flake: `test_slow_runs_never_execute_twice_at_once` (CHK-M3-232)

Fixed at main's request after the four fixes above were accepted. It failed on manager.yml attempt 1 and passed on the re-run:

> `AssertionError: ('offline_sweep', [{… 'message': 'scheduler run failed', …}], {'sweep': 0, 'inventory': 0, 'schedules': 0})`, `assert 1 <= 0` (`test_serve_scheduler_linux.py:393`)

**Cause: a test race in what counts as "in flight".** (My first reading, a microsecond gap between `signalled` and `send_signal`, was too narrow. The real window is wider.)
- The test took `signalled` just before SIGTERM. It then counted as in flight only the runs that were running at `signalled` (`v[0] < signalled < v[1]`). Only those may log `SchedulerStopping`.
- serve doesn't stop the scheduler at SIGTERM. First uvicorn shuts down, then `ServeLifecycle.stop()` stops the catalog (a bounded wait), and only then calls `SchedulerRunner.stop()`, which sets the stop flag (`cli/serve.py:187-193`; `runner.py:173-176`). Until then the scheduler keeps starting runs, which is correct.
- The test's own timing makes the race likely. With 2.5 s runs on a 1 s interval and `max_instances=1`, a run starts every 3 s. `until()` returns within 0.2 s of run 3 ending, so `signalled` falls about 0.1–0.3 s before the next start.
- If shutdown takes longer than that gap, run 4 starts after `signalled`. If the flag is then set during run 4, run 4 logs `SchedulerStopping` but wasn't counted, so `in_flight` is 0. That is exactly what CI saw. In WSL, shutdown usually finishes inside the gap, so the test passed there.
- Not product: a run that is running when stop begins is meant to give up with `SchedulerStopping` (TASK-071 r1).

**Fix** (`manager/tests/test_serve_scheduler_linux.py`, test file only):
- **The launcher** (test code) wraps `SchedulerRunner.stop` to trace `scheduler stopping` just before the real `stop()` sets the flag.
- **In flight:** a run now counts as in flight if it is still running when `stop()` begins (`v[1] > stopping`). With no overlaps and every run ended, those are exactly the runs that can meet the stop flag.
- **Tighter in one way:** a run that ended between SIGTERM and the stop no longer counts, so it may not fail.
- **New check:** the trace holds exactly one `scheduler stopping`, after `signalled`.
- **Unchanged:** the assertion (`len(mine) <= in_flight[kind]` per job), the overlap and open-run checks, "every failure is `SchedulerStopping`", and the job-name check.
- **Other tests:** the G27 test and the other launcher users ignore the new trace line: it isn't `pool closed`, doesn't start with `start`, and comes before the pool closes.

| Row | Where | Command | Result |
| --- | --- | --- | --- |
| F1 | WM | diagnosis plant on the **old** test: serve sleeps 1.5 s before `scheduler.stop()` (standing in for a slow shutdown), ×3 | **0/3 passed**; each time CI's exact `{'sweep': 0, 'inventory': 0, 'schedules': 0}`, `assert 1 <= 0`. A 3 s delay is too long to show it (run 4 has ended before the flag), which fits the timing above |
| F2 | WM | the same plant on the **new** test, ×3 | **3/3 passed** |
| F3 | WM | the real defect, two sweeps at once (`max_instances=2` for the sweep job only), new test, ×3 | **0/3 passed**: `('sweep', {1: [721.06, 723.64], 2: [722.05, 724.62], …})`, `assert [(1, 2), …] == []` (the overlap check) |
| F3b | WM | `max_instances=2` for every job, ×3 | red 3/3 through **inventory** overlaps. The pool's 3 threads are taken by two inventory runs and one sweep, so a second sweep can't start; hence F3 plants the sweep alone |
| F4 | WM | stop doesn't wait (`shutdown(wait=False)`), ×2 | green 2/2. Not this test's defect: the flag is still set first, so the in-flight run gives up and still writes its end trace. G27 (`test_sigterm_waits_for_the_running_sweep_and_nothing_runs_after_close`, `end[1] < closed[0]`) covers stop-waits |
| F5 | WM | stress: the new test ×30, separate runs (`CI=true`) | **30/30 passed**, 0 failed |
| F5b | WM | the new test with the stop delayed 0.5, 1.0, 2.0 and 2.5 s (across the old test's red window), ×2 each | **8/8 passed** |
| F6 | WM | `tests/test_serve_scheduler_linux.py` (the whole module; the launcher is shared) | **9/9 passed** |
| F7 | WM | ruff check, ruff format --check, mypy --strict (manager) | clean |
