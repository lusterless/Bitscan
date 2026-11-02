# TASK-215 REVIEW: cgroup v2 supervisor, plugin cgroups and the sweep

Verdict: APPROVED (round 2, on the r1 test evidence; round 1 was CHANGES_REQUESTED for test evidence only)

Reviewer: reviewer-m10, 2026-10-30. REQ-238, REQ-240 (sweep), REQ-237 (delegation part). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-215-impl.md`:
- `agent/internal/runner/cgroup.go` (sha256 `6d919f5b…`, 181 code lines);
- `sweep.go` (`07070fed…`, 114);
- `cgroup_linux.go` (`48bf11ae…`, 54).

That's 349 code lines in 3 files, split by the lead's ruling. The excess is the `CgroupFS` seam, which plan §2 asks for. The wider sweep (strays in the service-cgroup root are pid-killed too) was accepted by the lead under TS §3.7 L284. The product files are unchanged between round 1 and round 2 (same hashes).

TEST: PASS (`work/reports/TASK-215-test.md`):
- the fake tree 8/8 (Windows and WSL `-race`);
- the delegated real-kernel rows 5/5;
- 14/14 plants red;
- **r1 evidence:** the delegated rows 5/5 again, now as the unit's user. The test records uid 999, gid 988, `CapEff`/`CapPrm`/`CapBnd`/`CapAmb` 0x4 and NoNewPrivs 1, under `systemd-run -p Delegate=yes -p User=bitscan-runner … -p NoNewPrivileges=yes`. Plants 338 and 339 are red in that mode. The delegated test file hash is `23dbd0b0…`, which I checked.

Spec read: TS §3 L152, §3.5 L249–L250, §3.7 L283–L285, L314–L357, L365, §8.1 L1245; #136 (a), #137, #138; plan TASK-215 §2, §4.

My re-run (Windows): `go test -count=1 -run TestCgroup ./internal/runner/` ok. `GOOS=linux golangci-lint run --build-tags delegated ./internal/runner/` gives 0 issues. The hashes match the test report.

## Checks (code: no finding)
1. **Born in its own cgroup (#136 (a)).** `StartIn`, under the spawn lock, does four things:
   - writes the runner's pid to `p-<n>/cgroup.procs`;
   - **re-reads `/proc/self/cgroup`** and refuses to start unless the runner is really in `p-<n>`;
   - calls `start`;
   - always calls `ensureSupervisor`.

   No sweep, kill or second spawn can run during the hop (CHK-M10-106). On the real kernel, as the unit's user, a plugin's first instruction and its first fork are both in `p-1` (CHK-M10-102).
2. **Never touches anything outside its own subtree (REQ-238).** Every path is relative to an `os.Root` on the own cgroup. Names are `p-<counter>` and `supervisor`, never job input. The sweep follows only plain directories and refuses empty, `.`, `..`, `/` and `\` names, and a symlink entry is never touched.
3. **The sweep (TS §3.5 L250, §3.7 L284, #138 (a)).**
   - Every pass first calls `ensureSupervisor`.
   - It pid-kills strays in the service root and in `supervisor` through a pidfd. The pid is re-checked as still listed after `pidfd_open`, so a recycled pid is never signalled.
   - Every other cgroup (`supervisor`'s children included) gets `cgroup.kill`, a wait for `populated 0`, then an rmdir children-first.
   - Passes repeat until one finds nothing, within a 5 s bound, after which it fails and the runner must exit (fail closed).
   - Plants 338, 339, 215a and 215b are red on the fake tree and on the real kernel, as root and as `bitscan-runner`.
4. **The runner moved by a plugin (#138 (b)).** `ensureSupervisor` runs before every `cgroup.kill` and every sweep pass, so the runner doesn't kill itself (plant 215d red). The race window is the accepted #138 (c) residual.
5. **Start-up refusals (#137).** `Setup` refuses on:
   - a missing `cgroup.kill`;
   - an un-creatable `supervisor`;
   - a failed move;
   - any `/proc/self/cgroup` other than one `0::/…` line (hybrid and v1 refused).

   `Open` leaves the start-up sweep to the caller (TASK-228).
6. **No logging in these files**, and errors are fixed words or wrapped with `%w`.

## Findings
None open.

1. **Resolved (round 1 should-fix, test evidence).** The delegated rows first ran as root. The r1 re-run as `bitscan-runner` exercises the permission-gated steps:
   - the delegated `cgroup.procs` writes;
   - `mkdir` and `cgroup.kill` as the unit's user;
   - `pidfd_open` and `pidfd_send_signal` on same-uid processes without `CAP_KILL`.

   All pass, and the plants are red there. The lead recorded the rule ("Delegated real-kernel rows must run as the unit user"), and it is now builder checklist item 21.
2. nit, `cgroup.go:44`: `rootFS.Mkdir` uses 0755 for plugin cgroups. That's fine: the runner owns them, and `UMask=0077` in the unit makes them 0700 anyway.

## NOT RUN rows and cover
- **REQ-238 (2)–(4) on a sandbox host, and the VM halves of CHK-M10-336 to -339:** NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover:** the delegated real-kernel rows in WSL, as root and as `bitscan-runner` with the unit's identity, capabilities and NoNewPrivileges.
- **Adequacy:** now adequate for this task's code: the hop, `cgroup.kill` of a forked tree, the strays everywhere, the runner moved back, and the plants red.
- **Unproven on a real host:** the rest of the verbatim unit, which affects plugins more than this code:
  - `ProtectSystem=strict` keeping the delegated subtree writable;
  - `TasksMax=64` and `MemoryMax=256M` with 8 parallel plugins;
  - the `SystemCallFilter=` set (`pidfd_*` in `@system-service`);
  - `RestrictNamespaces=yes`.

  TASK-228's `systemd-run` row with the full unit properties can cover most of these without a VM. The real-host remainder is G76.
