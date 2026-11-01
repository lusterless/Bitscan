# TASK-221 REVIEW: plugin start (`internal/runner/spawn_linux.go`), r1 and r2

Verdict: APPROVED

Reviewer: reviewer-m10c (replacing reviewer-m10), 2026-11-01. REQ-239 (1)–(5), (7), REQ-241 (5) (spawn half). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-221-impl.md` (r0, r1, r2):
- `agent/internal/runner/spawn_linux.go` (sha256 `33919119…`): r1 changes `RemoveTempDir`; r2 changes only the comment at L111-115.
- r2 adds `func init() { runtime.LockOSThread() }` to `agent/cmd/bitscan-runner/main.go` L29-34. That file is TASK-228's; I reviewed only these lines here.

TEST: PASS (`work/reports/TASK-221-test.md`).
- Delegated runs as `bitscan-runner` (uid 999, Cap* 0x4, NoNewPrivs 1, `PrivateTmp=yes`), per checklist item 21: 15/15, three times.
- 14/14 plants red, among them:
  - the r0 path-based chmod, red 7 times in the 1,000-round swap race;
  - both m0-lock plants.
- r1 needed a second round: CHK-M10-128 part 2 failed on m0, and r2 fixed it.

Spec read: TS §3.5 L249–L250, §3.7 L276, L283–L284; #31, #135 (a), (b), #136 (a)–(c), (f); decisions rows "TASK-221 (spawn) choices accepted", "TASK-221 r1: confined temp-dir chmod", "TASK-221 r2: keep the main OS thread out of Spawn"; checklist items 21 and 22.

My re-run (Windows host):
- `gofmt -l .` prints nothing.
- `GOOS=linux go vet -tags delegated ./internal/runner/` is clean.
- `GOOS=linux golangci-lint run --build-tags delegated ./internal/runner/... ./cmd/...` and the full `golangci-lint run ./...` (Windows and GOOS=linux) report 0 issues.
- No `nolint` in non-test code.
- The delegated rows need Linux and a delegated cgroup, so the run evidence is the tester's.

## Checks
1. **r1: the chmod can't follow a swapped symlink out of the temp tree (checklist 22).**
   - `RemoveTempDir` opens `os.OpenRoot(dir)`, walks `root.FS()` and calls `root.Chmod(name, 0o700)` on directories only.
   - I checked the Go 1.27.2 source. `os.Root` resolves every intermediate component with `openat(O_NOFOLLOW)`, and a symlink that leaves the root is refused. For the last component, `chmodat` calls `checkSymlink` and then `unix.Fchmodat(..., AT_SYMLINK_NOFOLLOW)` (`os/root_unix.go:177`).
   - On Linux that is `fchmodat2`. Kernel 5.15 has no `fchmodat2`, so it falls back to `O_PATH|O_NOFOLLOW` plus `/proc/self/fd`, and refuses a symlink with EOPNOTSUPP (`internal/syscall/unix/fchmodat_linux.go:14-51`). A swap between the readlink check and the chmod therefore changes the link or fails; it never follows the link.
   - The 1,000-round race row (CHK-M10-131 r1) and plant 221a show this on the real kernel.
2. **No lint dodge.** `unix.Chmod` and `path/filepath` are gone. gosec G302 does not fire on `root.Chmod`, so `.golangci.yml` has no G302 exclusion and there is no `nolint`. The only lint lifts for this file are TASK-211's G204 and forbidigo exceptions.
3. **r2: no runner thread is left lowered (#136 (b)).**
   - The `init` lock keeps the main goroutine on m0. Spawn's locked goroutines therefore always end on a non-main thread, and the runtime ends that thread.
   - Nothing in `run()` needs main-thread affinity: `PR_SET_DUMPABLE` is per process, there is no cgo, and the only per-thread calls are inside Spawn's goroutine.
   - The test binary mirrors the lock in `TestMain`, and plant 221e (lock removed) is red with m0 at nice 10.
4. **REQ-239 (1)–(5), (7), unchanged since r0 and rechecked:**
   - the struct-literal `exec.Cmd` (no `LookPath`): `/bin/sh -c`, `Env` exactly the `PATH` line, stdin `/dev/null`, two `os.Pipe` write ends, no `SysProcAttr` (no `Pdeathsig`);
   - a 0700 `/tmp/bitscan-p-*` working directory, with no `TMPDIR`;
   - the child is born in `p-<n>` through `StartIn`.

   CHK-M10-127 to -130 and -132 are PASS, and plants 331 to 336 are red.
5. **Errors and logs.** `execute` never reaches an error. Nothing in the file logs.

## NOT RUN rows and cover
- **REQ-239 (1)–(5) on a sandbox host, and the VM halves of CHK-M10-331 and -333 to -336:** NOT RUN, under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** the WD rows run on the real kernel as `bitscan-runner` with the unit's capabilities. That is adequate for this code.
- **Unproven on a real host:**
  - the same behaviour under the full verbatim unit (`SystemCallFilter=@system-service`, `RestrictNamespaces=yes`, `ProtectSystem=strict`);
  - in particular, whether `fchmodat2` gets ENOSYS or EPERM from the seccomp filter on 22.04 (systemd 249). EPERM would skip the `/proc/self/fd` fallback, so the chmod-retry path fails. `RemoveTempDir` then errors, and `Run` treats that as fatal: the runner exits and systemd discards its private `/tmp`. That fails closed. It matters only after a plugin has done `chmod 000` on its own subdirectory.

## Findings
None blocking or should-fix.

1. nit, `spawn_linux.go:160`: `os.OpenRoot(dir)` follows a symlink if a plugin renames its own temp directory and puts a link in its place. This is reviewer-m10's leftover optional nit. It's bounded (same uid, the chmod is 0700 only) and accepted as built (decisions 2026-11-01 (3)).
