# TASK-216 REVIEW: runner hygiene and start-up refusals (`hygiene_linux.go`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-237 (1) and the hygiene half of REQ-237. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-216-impl.md`: `agent/internal/runner/hygiene_linux.go` (new, sha256 `701fc721…`, one file, inside the estimate).

TEST: PASS (`work/reports/TASK-216-test.md`). 18/18 on WSL with `-race`, and 7/7 plants red (CHK-M10-329, -340, -385, -386, plus 3 extras).

Spec read: TS §3 L152, §3.7 L276, L283, L316–L321, §8.1 L1245; #137; plan TASK-215 §5.

My re-run (Windows host): `GOOS=linux go vet ./internal/runner/` is clean, `GOOS=linux go test -c` compiles, and `GOOS=linux golangci-lint run ./internal/runner/` gives 0 issues. The hash matches. The file is Linux-only, so its tests can't run on Windows. WSL's default user has no Go toolchain, and I did not raise to root to repeat them, so the run evidence is the tester's.

## Checks
1. **Non-dumpable first (TS §3.7 L283).** `Harden` sets `PR_SET_DUMPABLE` 0 and reads it back with `PR_GET_DUMPABLE`, refusing if it is still set. The read-back makes the plant fail twice (329 red). TASK-228 must call it first; I'll check that there.
2. **Refusals (#137).** In order: euid 0; then any bit outside `CAP_DAC_READ_SEARCH` in `CapEff` or `CapBnd`; then `/sys/fs/cgroup` statfs magic ≠ `CGROUP2_SUPER_MAGIC`; then `/proc/self/cgroup` not exactly one `0::/…` line.
   - Each refusal is one fixed message naming the check.
   - A missing, repeated or non-hex capability line, or an unreadable `/proc` file, is refused (fail closed).
   - Plants 340, 385, 386, 216a and 216b are red.
3. **No capability beyond the unit's (security invariants; TS §3.7 L319–L320).** The check enforces at start-up that the runner holds nothing beyond the unit's `AmbientCapabilities=` and `CapabilityBoundingSet=`. A unit or drop-in that adds a capability makes the runner refuse instead of running plugins with it.
4. **No output, nothing logged.** Errors carry fixed words only.

## NOT RUN rows and cover
- **REQ-237 (2):** on a sandbox host, `CapEff` and `CapBnd` are `…04` and a plugin gets EACCES on `/proc/<runner>/mem` and `environ`.
- **REQ-237 (3):** a cgroup v1 boot on u2204.
- **REQ-237 (4):** a planted unit with `CAP_SYS_ADMIN`.
- **The VM halves of CHK-M10-329, -340 and -386.**

All are NOT RUN (safety-classifier refusal, VM sandbox).

- **Cover:**
  - CHK-M10-110/-112 (injected probes) and CHK-M10-111 (`PR_GET_DUMPABLE` 0 in a real child process). These are adequate for the decision logic, and for "the flag is set".
  - REQ-237 (4): the capability check is the same code path the planted unit would hit, so the unit-level plant is a close cover.
- **Unproven on a real host:**
  - that non-dumpable plus the unit's `~@debug` filter actually yields EACCES for a same-uid plugin on `/proc/<runner>/mem`, `environ` and `ptrace` (kernel and seccomp behaviour, not this code);
  - that a real cgroup v1 or hybrid boot gives the statfs magic and `/proc/self/cgroup` shape the probes assume;
  - that the real unit gives exactly `CapEff`/`CapBnd` `0000000000000004`.

  TASK-228's binary row under `systemd-run` with the unit's properties can cover the last of these without a VM. I'll ask for that there.

## Findings
None blocking or should-fix.

1. nit, `hygiene_linux.go:60-70`: only `CapEff` and `CapBnd` are checked, as #137 states. `CapPrm` (from which a process can raise `CapEff` with `capset`) and `CapAmb` (passed to every plugin on exec) aren't. Under the verbatim unit both are subsets of the bounding set, so this adds nothing today. Checking all four lines would make the refusal independent of how the process was started. It's a cheap addition to the same loop.
