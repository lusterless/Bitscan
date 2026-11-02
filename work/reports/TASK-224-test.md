# TASK-224 TEST (r1 and r2): PASS

Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-239 (6), REQ-240 (1)–(10), REQ-241 (3), (5); TS §3.5 L249–L250, §3.7 L284; #135 (c), #136 (f), #138. Decisions rows covered:
- "TASK-224 (job) and TASK-225 (serve) design points accepted" (2): the only error `Run` returns is a failed sweep or temp cleanup, and it is fatal;
- the same row (3): `TmpDirs` has no default;
- "TASK-224 r1: always kill the shell when a plugin is stopped";
- "Delegated real-kernel rows must run as the unit user".

Code under test: `agent/internal/runner/job.go` at r1. The `stop` closure now always runs `cg.Kill()` then `s.proc.Kill()`. Impl report: `work/reports/TASK-224-impl.md` (r0, r1).

Test file (new): `agent/internal/runner/job_delegated_linux_test.go`, build tag `linux && delegated`, 10 tests and 6 subtests. It uses the real `Open`, `Sweep` and `Spawn`, a counting `Spawn` wrapper (the exec counter), and the TS-extracted default patterns. It shares the `jobLog` sink with `serve_linux_test.go`.

## Where and how

WSL Ubuntu 24.04 (cgroup2fs, systemd 255). The whole delegated binary runs unprivileged, as the unit's user:

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p StateDirectory=m10c-job -p WorkingDirectory=<tree>/agent/internal/runner <race-built binary> -test.run Delegated -test.v`

The tree holds `docs/spec/Technical_Specification.md`, so the TS extraction resolves. The test logged its identity: `uid 999 euid 999 gid 988; CapEff/CapPrm/CapBnd/CapAmb 0x4; NoNewPrivs 1`.

The `/tmp` row refuses to run unless `/tmp` and `/var/tmp` are mount points of the test's own namespace (`/proc/self/mountinfo`). So it can never empty a host's `/tmp`. Plants ran in throwaway copies, never in the worktree.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| WD, whole delegated binary ×3 | as above | **31/31 passed** each run (cgroup 5, spawn 7, remove-temp 3, job 16), 0 failed, 0 skipped, unit exit 0 |
| static | `gofmt -l`; `go vet` (plain and `-tags delegated`); `golangci-lint run` on Linux, plain and `--build-tags delegated` | clean, 0 issues |
| plants | 13 plants (12 in job.go, 1 spawn plant against the job rows), each in its own copy, delegated as bitscan-runner | **13/13 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-147 | APP | WD | `TestDelegatedJobNoSurvivors` | PASS | REQ-240 (1)–(6), with `max_parallel_plugins` 1. Five plugins keep their processes in their own cgroup:<br>• `sleep … &`;<br>• `setsid nohup sleep … &`;<br>• a double fork;<br>• `trap '' TERM; sleep …` with `timeout_s` 2 (timed_out, 137);<br>• a child moved into `p-<n>/nest`.<br>For each, the subtree holds no process except the runner when its result is emitted. Three plugins move a child out: into `supervisor`, into `supervisor/evil`, and into the service root. After `Run`, for all eight:<br>• no process other than the runner is in the subtree;<br>• no process of uid 999 is running `sleep 300.147`;<br>• the only cgroup is `supervisor`, with nothing under it;<br>• the runner is in `supervisor`.<br>All 8 results arrived once; exit 0, except the timed-out one |
| CHK-M10-148 | APP | WD | `TestDelegatedJobTimeout` | PASS | REQ-240 (7). `sleep 100` with `timeout_s` 2: the result came between 2 and 3 s after the start, `timed_out` true, exit 137, nothing left |
| r1 row (reviewer-m10c, impl-agent-m10r) | APP | WD | `TestDelegatedJobMovedShellTimeout` | PASS | `echo $$ > <base>/supervisor/cgroup.procs; exec sleep 100000` with `timeout_s` 2: `timed_out` true, exit 137. `Run` returned after 2.01–2.02 s (bound 10 s); no `sleep 100000` survived, and the subtree holds only the runner |
| CHK-M10-149 | APP | WD | `TestDelegatedJobRunnerMoved` | PASS | REQ-240 (8), #138 (b). The plugin writes `$PPID` (the runner) into its own `cgroup.procs`. The runner survives, is back in `supervisor`, and the next job runs (`echo ok` gives exit 0, `ok\n`). Recorded: the moving plugin's own result was exit 0, `moved\n` |
| CHK-M10-150 | APP | WD | `TestDelegatedJobTmpEmptied/the_private_/tmp_and_/var/tmp_are_emptied` | PASS | REQ-240 (9), #135 (c). With `TmpDirs` = `/tmp`, `/var/tmp` (the private mounts), the plugin leaves:<br>• `/tmp/x/deep/f` and `/tmp/.h`;<br>• `/var/tmp/y`;<br>• a `/var/tmp/locked` of mode 000 holding a file;<br>• a symlink `/tmp/link` to `/var/lib/m10c-job/outside`.<br>After `Run`, both directories are empty, and the symlink target and its `keep` file are unchanged (no symlink followed) |
| TmpDirs no default (design point 3) | APP | WD | `…/no_default:_TmpDirs_nil_leaves_/tmp_alone` | PASS | With `TmpDirs` nil, a plugin's `/tmp/m10c-nodefault-marker` survives the job |
| Executor errors are fatal (design point 2) | APP | WD | `…/a_failed_cleanup_is_Run's_error_(fatal),_after_every_result` | PASS | With `TmpDirs` = `/nonexistent-m10c`, `Run` emits the 1 result, then returns an error and logs "after-job cleanup failed". The serve half (no `done`, `Serve` returns the error) is TASK-225's `TestServeFatalExecutorError` |
| CHK-M10-151 | APP | WD | `TestDelegatedJobCancel` | PASS | REQ-240 (10). Two `sleep 300.151` plugins run at `max_parallel_plugins` 2 and a third waits. `ctx` is cancelled once both run. `Run` returns, 0 results are emitted (none after the cancel, and the queued third is not reported), and 1 s later no plugin process exists |
| CHK-M10-152 | APP | WD | `TestDelegatedJobParallelCap` | PASS | REQ-239 (6). Eight `date; sleep 2; date` at 3 at once: the maximum overlap from the plugins' own timestamps is exactly 3, done in three rounds (6–8 s). At 1 at once, 3 plugins never overlap |
| CHK-M10-153 | APP | WD | `TestDelegatedJobStartFailures` | PASS | REQ-241 (5), #136 (f). An `ErrExec` at spawn 2: plugin 2 is `runner_unavailable` (exit null, empty streams, flags false), and plugins 1 and 3 ran (`one`, `three`); 3 spawn calls. An `ErrCgroup` at spawn 2: plugins 2–4 are `runner_unavailable`, and there are exactly 2 spawn calls (no further start) |
| CHK-M10-154 | APP | WD | `TestDelegatedJobExitCodesAndOrder` | PASS | REQ-241 (3) at unit level: `exit 3` → 3, `kill -9 $$` → 137, an unknown command → 127, `echo fast` → 0. Emitted in completion order 4, 2, 3, 1, not payload order |
| CHK-M10-155 | APP | WD | `TestDelegatedJobRedaction` | PASS | With the TS-extracted defaults, a `bsa_M10CANARY…` token plus 3 MiB of filler gives stdout `start [REDACTED] end\n…`: ≤ 65,536 bytes, `truncated` true, no `M10CANARY`. The token on stderr gives `[REDACTED]`. The runner log has a per-plugin line (ids, exit, duration) and no canary or filler |
| CHK-M10-156 | APP | WD | `TestDelegatedJobCleanupBeforeEmit` | PASS | At each emit (with `max_parallel_plugins` 1), the plugin's `/tmp/bitscan-p-*` is gone (Lstat ENOENT) and there is no `p-*` cgroup |
| r1 plant: pre-r1 `stop` (shell killed only if `cg.Kill` fails) | CODE | WD | plant `r0stop` | PASS (red) | "Run did not return within 10s: plugins in the subtree [1052]"; "Run blocked on the moved shell" |
| CHK-M10-337 (G72 half) | CODE | WD | plant: `release` without `cg.Kill` | PASS (red) | "plugin 1: processes [1524] still alive when its result is emitted" (and plugins 2–5). VM half NOT RUN (VM hold, the named gate exception) |
| CHK-M10-338 (job half) | CODE | WD | plant: after-job `Sweep` removed | PASS (red) | 3 `sleep 300.147` alive after the job; `p-5` and `supervisor/evil` left |
| CHK-M10-336 (executor half) | CODE | WD | spawn plant 336 (start outside `StartIn`) against the job rows | PASS (red) | Background children alive at every emit; the timeout result came at 3.0035 s (its sleep, in `supervisor`, held the pipes until captureGrace) |
| CHK-M10-341 (executor half) | CODE | WD | plant: `RemoveTempDir` dropped from `plugin()` | PASS (red) | "temp dir /tmp/bitscan-p-… still there when its result is emitted" ×3 |
| CHK-M10-342 | CODE | WD | plant: `TmpDirs` not walked | PASS (red) | `/tmp` held `[.h link x]`, `/var/tmp` held `[locked y]`, and the bad-dir cleanup returned nil |
| CHK-M10-343 | CODE | WD | plant: timer in hours | PASS (red) | The timeout row hung to 15 s (killed by the test); no-survivors hung to 60 s. VM half NOT RUN |
| CHK-M10-391 (executor half) | CODE | WD | plant: the plugin's `ctx.Done()` case removed | PASS (red) | "Run did not return within 20s: plugins in the subtree [4303 4304 4307 4308]". VM half NOT RUN |
| CHK-M10-382 (executor half) | CODE | WD | plant: `out.Data` logged | PASS (red) | "plugin output or command in the runner log" |
| extra 224a | CODE | WD | plant: semaphore of `len(plugins)` | PASS (red) | "at most 8 plugins ran at once, want exactly 3"; 2.01 s instead of three rounds |
| extra 224b | CODE | WD | plant: a cgroup failure doesn't set `stopped` | PASS (red) | "4 spawn calls after a cgroup failure at the 2nd, want 2" |
| extra 224c | CODE | WD | plant: results emitted after the cancel | PASS (red) | "3 results emitted after the cancel" |
| extra 224d | CODE | WD | plant: `p-<n>` not removed in `release` | PASS (red) | "cgroup p-39 still there when the result is emitted" ×3 |

## Acceptance (TASK-224: "under `systemd-run -p Delegate=yes`, REQ-240 (1)–(7), (9), (10) and REQ-239 (6) hold through `Executor.Run`, and REQ-241 (5) holds with injected failures")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-240 (1)–(6) | CHK-M10-147 | PASS |
| REQ-240 (7) | CHK-M10-148; r1 moved-shell row | PASS |
| REQ-240 (8) (beyond the acceptance) | CHK-M10-149 | PASS |
| REQ-240 (9) | CHK-M10-150 | PASS |
| REQ-240 (10) | CHK-M10-151 | PASS |
| REQ-239 (6) | CHK-M10-152 | PASS |
| REQ-241 (5) | CHK-M10-153 | PASS |
| r1: the timeout holds for a shell that left its cgroup | r1 row and its plant | PASS |
| REQ-240 on a sandbox host | — | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the WD rows above, on the real kernel as bitscan-runner |

## Note for TASK-229 (impl-deploy-m10; sent to `main`)

The delegated binary now also holds the job rows. They need four things the `agent.yml` delegated step doesn't give them today:
- `-p PrivateTmp=yes`. The `/tmp` row refuses to run without private mounts, and a private `/tmp` hides any binary placed under `/tmp`.
- `-p StateDirectory=m10c-job`.
- the test binary outside `/tmp` and outside `$HOME`, which bitscan-runner can't read on hosted runners. For example, `/opt/delegated`.
- a `WorkingDirectory` whose `../../../docs/spec/Technical_Specification.md` exists (the TS-extracted patterns).

Without them, the CI step goes red on `TestDelegatedJobTmpEmptied` and `TestDelegatedJobRedaction`.

## Revision 2 (2026-11-01): capture errors set `truncated`; cleanup logs carry no path

Code: `job.go` r2 keeps both `Capture` errors and sets `out.Overflow` when either stream errors (decisions row "TASK-224 r2: a stderr-only read error also sets truncated"). `cmd/bitscan-runner/main.go` r2 adds `pathless()`, which logs sweep and cleanup errors as the operation and errno only. Impl report: "Revision 2 (2026-11-01)".

New tests:
- `TestDelegatedJobCaptureErrorTruncated` (job file, 1 test and 5 subtests);
- `agent/cmd/bitscan-runner/main_test.go` (new, `//go:build linux`, package `main`, `TestPathlessDropsPaths`, 1 test and 7 subtests).

| Run | Command | Count |
| --- | --- | --- |
| WD, whole delegated binary ×2 | as above | **37/37 passed** each run (the 31 above plus 6), unit exit 0 |
| W | `go test -race ./cmd/bitscan-runner/` | **8/8 passed** |
| static | gofmt, vet, `golangci-lint run ./...` on Linux, plain and `--build-tags delegated` | 0 issues |
| plants | 3 | **3/3 red** |

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| r2 (1), stdout | APP | WD | `TestDelegatedJobCaptureErrorTruncated/stdout_held_open_by_a_child_that_left_the_cgroup` | PASS | A child moves itself to `supervisor` and keeps stdout open. The plugin waits until the move shows in `/proc/$!/cgroup`, then prints `ok` and exits. After captureGrace (the row took 1.22 s), the read end is closed and `Capture` errors. Result: exit 0, stdout `ok
`, `truncated` true. Nothing left after the job |
| r2 (1), stderr only | APP | WD | `…/stderr_only_held_open` | PASS | The same with only stderr held: `truncated` true |
| r2 control | APP | WD | `…/control:_no_read_error,_truncated_false` | PASS | `echo ok; echo e >&2` gives `truncated` false |
| r2 (1), unit | APP | WD | `…/unit:_a_{stdout,stderr}_read_that_fails_(EISDIR)` | PASS | A `Spawn` wrapper swaps the stream for an opened directory, so every read is EISDIR. `truncated` is true for each stream |
| r2 (1), manager verdict | CODE | — | existing `manager/tests/test_evaluate.py` L155–L165, L194, L213 (M8, unchanged) | PASS (by reference) | `evaluate.py` `_run_error`: `truncated` → ERROR `STDOUT_TRUNCATED` for every operator, including a PASS input. So a cut stream can never be PASS |
| r2 (2), unit | CODE | W | `TestPathlessDropsPaths` (7 cases) | PASS | `*fs.PathError{unlinkat, /tmp/M10PATHCANARY-x/f, EACCES}` gives `unlinkat: permission denied`, wrapped or joined behind canary text. `*os.LinkError{rename, EXDEV}` gives `invalid cross-device link`. A PathError without an errno gives `readdir`, a bare errno `device or resource busy`, no errno `no errno`. No output holds the canary or `/tmp`. The end-to-end half (the built runner under systemd-run, its stderr grepped) is a TASK-228 row |
| plant r2a | CODE | WD | `Capture` errors dropped again (the pre-r2 code) | PASS (red) | All four error rows red: "truncated false … want true" |
| plant r2b | CODE | WD | only a stdout error sets `truncated` | PASS (red) | Exactly the two stderr rows red |
| plant r2c | CODE | W | `pathless` returns `err.Error()` | PASS (red) | "pathless kept a path: \"unlinkat /tmp/M10PATHCANARY-x/f: permission denied\"" |
