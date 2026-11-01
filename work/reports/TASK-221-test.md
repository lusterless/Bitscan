# TASK-221 TEST (r1 and r2): PASS

Tester: tester-m10c (replacing tester-m10), 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-239 (1)–(5), (7), REQ-241 (5) (spawn half), REQ-238 (3); TS §3.5 L249, §3.7 L276, L283; #31, #135 (a), #136 (a)–(c), (f); decisions rows "TASK-221 r1: confined temp-dir chmod" and "TASK-221 r2: keep the main OS thread out of Spawn"; builder checklist items 21 and 22.

Code under test: `agent/internal/runner/spawn_linux.go` (r1: `RemoveTempDir` chmods through `os.Root`; r2: comment only) and `agent/cmd/bitscan-runner/main.go` (r2: `func init() { runtime.LockOSThread() }`). Impl report: `work/reports/TASK-221-impl.md` (r1, r2).

Test file: `agent/internal/runner/spawn_delegated_linux_test.go` (build tag `linux && delegated`; written by tester-m10, extended here). Changes by tester-m10c:
- a `TestMain` that locks m0 to the main goroutine, mirroring the r2 `init`;
- `threadNiceness`: every thread's niceness (stat field 19) and I/O class (`ioprio_get`);
- the CHK-M10-128 part 2 row now runs 20 spawns from 4 goroutines;
- the symlink-swap race runs 1,000 rounds instead of 300 (the r0 plant once survived to round 216);
- `os.Chmod` → `unix.Chmod` and an unused `nolint` dropped, so the file is lint-clean with `--build-tags delegated`.

## Where and how

All rows ran delegated and unprivileged, as the unit's user (checklist item 21), in WSL Ubuntu 24.04 (cgroup2fs, systemd 255):

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p WorkingDirectory=/opt/m10c <go test -c -race -tags delegated binary> -test.run Delegated -test.v`

The test logged its identity: `uid 999 euid 999 gid 988; CapInh/CapPrm/CapEff/CapBnd/CapAmb 0000000000000004; NoNewPrivs 1`. These files are Linux-only, so there is no Windows row. Plants ran in throwaway copies (`/root/m10c/w-mut-<plant>`); the worktree holds none.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| WD r1 (before r2) | delegated binary, `-test.run Delegated` | 14/15 passed, 1 failed (CHK-M10-128 part 2, below), 0 skipped |
| WD r2 ×3 | same, after the r2 product change and the TestMain lock | **15/15 passed** each time (TestDelegatedCgroups 5, TestDelegatedSpawn 7, TestDelegatedRemoveTempDir 3), unit exit 0 |
| static | `gofmt -l`; `go vet` and `golangci-lint run` on Linux, with and without `--build-tags delegated`, `./internal/runner/... ./internal/agent/...` | clean, 0 issues |
| plants | 14 plants, each in its own copy, delegated as bitscan-runner | **14/14 red** |

## Round 1 failure and fix (r2)

| Check | Expected | Actual on r1 | Diagnosis |
| --- | --- | --- | --- |
| CHK-M10-128 part 2 | every runner thread at niceness 0 after the spawns | one thread at niceness 10: tid == pid (m0), state S, `wchan futex_do_wait`; the other 6 threads were at 0 | Spawn's locked goroutine sometimes ran on m0. When a locked goroutine exits on m0, the Go runtime parks that thread forever instead of ending it, so m0 stayed at nice 10 and I/O idle. Reported to `main`. Ruled option (a), a product fix: TASK-221 r2 adds the `init` lock in `cmd/bitscan-runner`, and the test binary gets the same lock in `TestMain`. **1/1 passed at r2** (×3 runs) |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-127 | APP | WD | `TestDelegatedSpawn/environment,_descriptors,…` | PASS | REQ-239 (1), (2), (4), (5), (7). Values:<br>• `/proc/$$/environ` is exactly `PATH=/usr/sbin:/usr/bin:/sbin:/bin`;<br>• `readlink /proc/$$/fd/0` is `/dev/null`;<br>• the shell's fds are `0,1,2`;<br>• cmdline is `/bin/sh\|-c\|<execute>`;<br>• `pwd` is the `Spawned.TempDir` under `/tmp/bitscan-p-`, mode 700, `ls -A` empty;<br>• `id -u` is 999, not 0;<br>• the temp dir is gone after `RemoveTempDir` |
| CHK-M10-128 | APP | WD | `TestDelegatedSpawn/niceness_10_and_I/O_class_idle` | PASS (r2) | Part 1: the plugin's stat field 19 is 10 and `ionice -p $$` is `idle`. Part 2: after 20 concurrent spawns, every runner thread, m0 included, is at niceness 0 and not I/O idle (r1 FAIL above) |
| CHK-M10-129 | APP | WD | `…/born_in_its_own_cgroup,_with_its_first_fork` | PASS | The plugin's own `/proc/$$/cgroup` and its first fork's are the same `…/p-<n>`, never `supervisor` (#136 (a), REQ-238 (3)) |
| CHK-M10-130 | APP | WD | `…/no_Pdeathsig` | PASS | `sleep 2; echo done` exits 0 with `done`: it isn't killed when the start thread is discarded (#136 (c)) |
| CHK-M10-131 | APP | WD | `TestDelegatedRemoveTempDir/static` | PASS | A tree with a `0000` subdirectory chain and a symlink `sub` → an outside directory (mode 0500, holding `keep`). After `RemoveTempDir`, the tree is gone (Lstat ENOENT), the outside mode is still 0500 and `keep` is still there |
| CHK-M10-131 r1 (decisions row; checklist 22) | APP | WD | `TestDelegatedRemoveTempDir/race` | PASS | 1,000 rounds. A goroutine (the "parallel plugin") keeps swapping the locked subdir `x` for a symlink to the runner-owned 0500 outside directory and back, while `RemoveTempDir` runs. The outside mode stayed 0500 in every round |
| CHK-M10-132 | APP | WD | `…/a_cgroup_that_can't_be_entered` | PASS | The cgroup is removed before `Spawn`. Result: `ErrCgroup` (`openat p-N/cgroup.procs: no such file or directory`), `Spawned` nil, the marker file is never touched, and 0 temp dirs are left |
| (extra) | APP | WD | `…/each_plugin_its_own_temp_dir_and_cgroup` | PASS | Two plugins get a different `pwd` and cgroup |
| CHK-M10-331 (G72 half) | CODE | WD | plant `Env: os.Environ()` | PASS (red) | ENV showed `LANG…PATH=/usr/local/sbin…USER=bitscan-runner…INVOCATION_ID…`. VM half NOT RUN (VM hold, the named gate exception, decisions 2026-11-01 (1)) |
| CHK-M10-332 | CODE | WD | plants `TMPDIR=<dir>` added; `PATH` with `/usr/local/bin` | PASS (red ×2) | ENV mismatch in each |
| CHK-M10-333 (G72 half) | CODE | WD | plant `Stdin: os.Stdin` | PASS (red) | `FD0 = "pipe:[17196]"`. VM half NOT RUN |
| CHK-M10-334 (G72 half) | CODE | WD | plant: `setpriority` skipped | PASS (red) | `NICE "0" IO "idle"`. VM half NOT RUN |
| CHK-M10-335 (G72 half) | CODE | WD | plant: `ioprio_set` skipped | PASS (red) | `NICE "10" IO "none: prio 0"`. VM half NOT RUN |
| CHK-M10-336 (G72 half) | CODE | WD | plant: `cmd.Start()` outside `StartIn` | PASS (red) | SELF and KID were both `…/supervisor`, and a spawn into a removed cgroup started a process. VM half NOT RUN |
| CHK-M10-341 (spawn half) | CODE | WD | plant: `RemoveTempDir` does nothing | PASS (red) | "the temp dir is still there", "the temp tree is still there", 7 temp dirs left |
| extra 221a | CODE | WD | plant: the r0 path-based `filepath.WalkDir` + `unix.Chmod(path, 0o700)` | PASS (red ×5) | Red at rounds 22, 11, 12, 216 and 16 at 300 rounds, then at rounds 161 and 6 at 1,000 rounds: "outside dir mode 700: a chmod left the temp tree" |
| extra 221b | CODE | WD | plant: no chmod retry | PASS (red) | `unlinkat …/locked/deep/f: permission denied` (REQ-240 (9) cleanup) |
| extra 221c | CODE | WD | plant: `SysProcAttr{Pdeathsig: SIGKILL}` | PASS (red) | The plugins were killed when the start thread ended (exit 137, empty output) |
| extra 221d | CODE | WD | plant: `defer runtime.UnlockOSThread()` in the start goroutine | PASS (red) | 6 non-m0 threads at niceness 10 and I/O idle |
| extra 221e | CODE | WD | plant: the m0 lock removed (TestMain's lock dropped, mirroring the r2 `init`) | PASS (red) | "runner thread 1424 (m0, the main thread) state S niceness 10 ioprio-idle true". The same plant against the built runner binary (main.go `init` removed) is a TASK-228 row |
| extra 221f | CODE | WD | plant: temp dir re-moded 0755 | PASS (red) | `MODE = "755"` |

## Acceptance (TASK-221: "under `systemd-run -p Delegate=yes`, REQ-239 (1)–(5) and (7) hold for a test command and the child appears in its own cgroup from its first instruction")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-239 (1), (2), (4), (5), (7) | CHK-M10-127 | PASS |
| REQ-239 (3) | CHK-M10-128 | PASS (r2) |
| born in its own cgroup, first instruction and first fork | CHK-M10-129 | PASS |
| r1: the chmod never leaves the temp tree; the tree is still removed | CHK-M10-131, -131 r1, plant 221a | PASS |
| r2: no runner thread is left lowered | CHK-M10-128 part 2, plants 221d, 221e | PASS |
| REQ-239 (1)–(5) on a sandbox host | — | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the WD rows above, on the real kernel as bitscan-runner |

Every TASK-221 delegated test is in the binary that TASK-229 r1's CI step runs (`-test.run Delegated`).
