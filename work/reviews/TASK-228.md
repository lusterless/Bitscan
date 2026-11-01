# TASK-228 REVIEW: `bitscan-runner` main (`cmd/bitscan-runner/main.go`)

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-237, REQ-238, REQ-240, REQ-251. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-228-impl.md`: `agent/cmd/bitscan-runner/main.go` (sha256 `17cdd764…`), which replaces the M0 stub and carries `//go:build linux`. The current file also holds two later changes from other tasks, reviewed with them:
- the m0 `init` lock (TASK-221 r2);
- `pathless()` (TASK-224 r2).

TEST: PASS (`work/reports/TASK-228-test.md`).
- The runner ran in WSL under a transient unit carrying **all 37 `[Service]` directives of the shipped unit, read verbatim, and the 5 `[Socket]` directives**. None was rejected, and 34/34 checks passed.
- `pathless` passed 8/8.
- Two binary-level plants are red. The m0-lock plant could not be reproduced at binary level; it is red at unit level (TASK-221).

Spec read: TS §3 L152; §3.5 L249–L250; §3.7 L276–L285, L289–L359 (units); §8.4 L1287; #137, #138 (a); decisions rows "TASK-224 (job) and TASK-225 (serve) design points accepted" (3) and "TASK-215 split" (Setup, then Sweep).

My re-run (Windows host): `gofmt` reports nothing; `GOOS=linux go vet ./cmd/bitscan-runner/` is clean; `golangci-lint` on GOOS=linux reports 0 issues; and on Windows, `go vet ./...` skips this file, as designed.

## Checks
1. **The cleanup covers only the unit's PrivateTmp mounts (the lead's must-check).**
   - `deploy/systemd/bitscan-runner.service` sets `PrivateTmp=yes`, and the unit is unchanged in M10 (`git diff --stat deploy/systemd` is empty).
   - `PrivateTmp=yes` gives the unit its own `/tmp` and `/var/tmp`. Those are exactly `TmpDirs` at `main.go:69`, and nothing else is emptied. Inside that namespace, only the runner and its plugins can create entries, so the cleanup removes nothing the runner didn't create.
   - CHK-M10-188e, under the verbatim unit: the private `/tmp` and `/var/tmp` are empty after the job, and the host's `/tmp/m10c-host-marker` and `/var/tmp/m10c-host-marker` are untouched.
   - The `notmp` plant is red.
2. **Start-up order (plan TASK-215 §5).** `Harden` (first) → `CheckStartup` → `LookupUID("bitscan")` → `FromSystemd` → `Open` → the start-up `Sweep` → `Serve`.
   - A failure is one `start-up refused` line, and the process exits 1.
   - Under the verbatim unit every check passes: CapInh, CapPrm, CapEff, CapBnd and CapAmb are each `0x4`, NoNewPrivs is 1, and Seccomp is 2 (CHK-M10-188a, b).
   - The process is not dumpable (CHK-M10-189), and the `noharden` plant is red.
3. **Runs jobs under the real unit.** 8 parallel plugins run in 8 separate `p-<n>` cgroups at niceness 10 as uid 999, under `TasksMax=64` and `MemoryMax=256M`, followed by 10 more 8-plugin jobs.
   - The pidfd kills and the sweep work under the syscall filter, and the cgroup writes work under `ProtectSystem=strict` and `RestrictNamespaces=yes`.
   - No survivors (CHK-M10-188c, d).
   - These are TASK-215's unproven items, now shown in WSL.
4. **TASK-213's and TASK-217's unproven items, now shown in WSL.**
   - The runner reads `agent_id` through the `bitscan:bitscan` 0700 state dir.
   - `runner.sock` is `root:bitscan 0660` in a `root:root 0755` `/run/bitscan`. `nobody` gets EACCES; root connects and is refused by the uid check.
5. **SIGTERM.** The running job is cancelled and swept inside `Serve`, then a final `Sweep` runs and the process exits 0. No plugin is left a second later (CHK-M10-191).
6. **Fatal cleanup.** It exits 1, with `reason` given as op and errno only. The journal holds no plugin-chosen path, checked with a canary bind mount.
7. **Logs** (REQ-251 (3)). Text `slog` on stderr goes to journald. No execute or stdout canary and no `/etc/shadow` content appear (CHK-M10-190). Job lines carry `job_id`.
8. **Import boundary** (REQ-251 (1)). There is no `net/http`, `crypto/tls` or agent transport (`TestImportBoundary`; plant 381 red). The binary is `CGO_ENABLED=0` and static.

## NOT RUN rows and cover
- **The runner on a sandbox VM through the driver, and the cgroup v1 boot refusal on u2204:** NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** this WSL row with all 37 verbatim directives (systemd 255, Ubuntu 24.04), plus TP-M10-09's injected cgroup v1 refusal. That is adequate for `main`.
- **Unproven on a real host:**
  - the same row on Ubuntu 22.04 (systemd 249, kernel 5.15). That covers the `@system-service` set there, including whether `fchmodat2` gets ENOSYS or EPERM in the chmod-retry path of `RemoveTempDir` (see TASK-221);
  - the real cgroup v1 boot;
  - the runner started by its socket from the installed `.deb`.

## Findings
None blocking or should-fix.

1. nit, `main.go:69`: the `/tmp` and `/var/tmp` emptying relies on the unit's `PrivateTmp=yes` and is not checked at start-up. A run outside the unit, with a hand-made `LISTEN_*`, would empty the shared `/tmp` of the runner uid's own files. The sticky bit and the lack of `CAP_FOWNER` keep everyone else's files safe. A fail-closed start-up check would close this: both paths must be mount points in the runner's own namespace, as the TASK-224 test already checks with `/proc/self/mountinfo`. Optional.
2. nit, recorded by the tester: the m0-lock plant can't be shown at binary level, because in the real runner m0 never picked up a start goroutine. The lock is proven by the unit-level plant, and the `init` is present.
