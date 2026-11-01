# TASK-224 REVIEW: job executor (`internal/runner/job.go`)

Verdict: APPROVED (round 3, r2)

Reviewer: reviewer-m10c, 2026-11-01. REQ-239 (6), REQ-240, REQ-241 (3), (5). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-224-impl.md` (r0, r1, r2):
- `agent/internal/runner/job.go`: sha256 `2e4e33cf…` at r1, `c4f9a85f…` at r2. `//go:build linux`, in 1 file.
- r2 also adds `pathless()` to `agent/cmd/bitscan-runner/main.go` (`17cdd764…`, TASK-228's file). I reviewed only that function and its three call sites here.

TEST: PASS at r1 and r2 (`work/reports/TASK-224-test.md`). All runs are of the whole delegated binary as `bitscan-runner` (uid 999, Cap* 0x4, NoNewPrivs 1, `PrivateTmp=yes`).
- r1: 31/31 three times; 13/13 plants red, including the pre-r1 `stop` on the new moved-shell row.
- r2: 37/37 twice; `TestPathlessDropsPaths` 8/8; 3/3 plants red.

Spec read: TS §3.5 L249–L252, §3.7 L284, §5.3, §8.1 L1245, §8.4 L1287; #113, #134 (h), #135 (c), #136 (d)–(f), #138; decisions rows "TASK-224 (job) and TASK-225 (serve) design points accepted" (1)–(3), "TASK-224 r1", "TASK-224 r2" and "TASK-224 r2: a stderr-only read error also sets truncated".

My re-run (Windows host):
- `gofmt` reports nothing.
- `go vet` is clean on Windows; `GOOS=linux go vet` is clean, with and without `-tags delegated`.
- `golangci-lint run ./...` gives 0 issues on Windows and on GOOS=linux, plain and with `--build-tags delegated`.
- The file is Linux-only; the delegated rows are the tester's.

## Round 1 (r0): CHANGES_REQUESTED
1. **blocking**, `job.go:103-107` with `:128-135`, TS §3.5 L249–L250 (the per-plugin timeout; "no plugin process outlives its job"), §3.7 L284. `stop()` killed the shell only when `cg.Kill()` failed. A plugin whose shell moves itself out of `p-<n>` is the case TS §3.7 L284 expects, and TASK-215's unprivileged rows show the unit user can move pids. For that plugin:
   - `cgroup.kill` succeeds, but the shell lives on.
   - The timer or cancel branch then blocks on `<-waitCh`, so the timeout isn't enforced and `Run` never returns.
   - The after-job sweep never runs, and the runner refuses every later job as `busy`.

   Fix: `stop` always calls `cg.Kill()` and then `s.proc.Kill()`.

## Round 2 (r1): APPROVED, with two nits, which the lead then had fixed as r2
- `stop` is fixed as asked (`job.go:106-109`).
- `Kill` alongside the concurrent `Wait` is safe: pidfd mode, or `sigMu` and `statusDone` in PID mode, so a reused pid is never signalled.
- `TestDelegatedJobMovedShellTimeout` passes (`timed_out`, exit 137, `Run` returns in 2.02 s, nothing survives), and its plant is red.

## Round 3 (r2)
1. **A capture error is never sent as whole output** (`job.go:113-118`, `:150-156`).
   - Both `Capture` errors are kept. Either one sets `out.Overflow`, so `Apply` reports `truncated`.
   - The manager's M8 `_run_error` turns `truncated` into ERROR `STDOUT_TRUNCATED` for every operator, so a cut stream can't PASS.
   - A stderr-only error also sets the single flag. That fails closed, keeps the exit code and redacted output, and is the lead's ruling.
   - Rows: stdout held open by a child that left the cgroup, stderr only, the EISDIR unit cases, and a control. Plants r2a and r2b are red.
2. **No plugin-chosen path in journald** (`main.go:109-126`, TS §5.3, §8.4).
   - `pathless` gives only the `PathError` op and errno, a bare errno, or "no errno", never `err.Error()` or a path.
   - It is used for the start-up sweep, `Serve`'s fatal error and the final sweep.
   - `refuse()` keeps `err.Error()` only for `Harden`, `CheckStartup`, `LookupUID`, `FromSystemd` and `Open`. Their texts are fixed words plus the runner's own paths, never plugin-made names.
   - The executor's and serve's cleanup lines are fixed words.
   - `TestPathlessDropsPaths` passes 7 cases with a canary, and plant r2c is red.

## Checks (the earlier reviewer's points, and the rest)
1. **PatternError never includes the pattern.** `Run` calls `redact.Compile` once and never logs or returns its error. If it fails, every plugin is reported `runner_unavailable`. `PatternError.Error()` gives only the index (TASK-210).
2. **Growth guard.** `Build` → `Set.Apply` returns `[REDACTED]` alone when a pattern would grow the text past 4 MiB. Plugins are redacted one at a time under `redMu` (#134 (h)). CHK-M10-155 runs a 3 MiB stream with a canary through the real path.
3. **Linux tags and the listener interface.** `job.go`, `spawn_linux.go` and `cmd/bitscan-runner/main.go` carry `//go:build linux`. `serve.go` is portable and takes the two-method `Listener` interface.
4. **An executor error is fatal.** `Run` returns only the joined `Sweep` and `TmpDirs` errors. `serve.go:139-141` returns that error without sending `done`, `Serve` stops, and `main` exits 1. `TestDelegatedJobTmpEmptied/a_failed_cleanup…` and TASK-225's `TestServeFatalExecutorError` cover it.
5. **`TmpDirs` has no default.** A nil value empties nothing (row "no default"). Production sets `/tmp` and `/var/tmp` in `main.go`; see TASK-228.
6. **Per-plugin order.** cgroup → start → capture (with the drain) → timer → `cgroup.kill` and shell kill → wait empty (5 s) → remove → pipes (1 s grace) → temp dir → redact → emit.
   - CHK-M10-147: no survivors at each emit, including `setsid`, a double fork, `trap '' TERM` and a nested cgroup.
   - CHK-M10-156: the temp dir and cgroup are gone before the emit.
   - Children that moved out are killed by the after-job sweep.
7. **Parallelism, cgroup failure and cancel.**
   - At most `MaxParallelPlugins` at once (CHK-M10-152).
   - `ErrExec` affects only that plugin; `ErrCgroup` stops new starts (CHK-M10-153).
   - A cancel emits nothing more (CHK-M10-151).
   - `emit` is serialised by serve's mutex.
8. **Logs.** One line per plugin with ids, `exit_code`, `timed_out` and `duration_ms`. No `execute`, pattern or output (plant 382 red).

## NOT RUN rows and cover
- **Not run:** REQ-240 on a sandbox host, and the VM halves of CHK-M10-337, -343 and -391. These are NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** the WD rows on the real kernel as `bitscan-runner`, with `PrivateTmp=yes`. That is adequate for the executor.
- **Unproven on a real host:** the executor under the full verbatim unit:
  - `TasksMax=64` with 8 forking plugins;
  - `MemoryMax=256M` with eight 1 MiB × 2 captures plus one redaction;
  - `SystemCallFilter` allowing the pidfd calls;
  - `ProtectSystem=strict` leaving `/sys/fs/cgroup` writable.

## Findings
None open. Both round-2 nits were fixed in r2. The "stdout truncated" wording for a stderr-only error is the lead's morning-list item.
