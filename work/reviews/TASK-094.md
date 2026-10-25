# TASK-094 REVIEW: os_info collector and the fixed command runner

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.** Reviewed under the drain, as the review already in progress.

Scope reviewed:
- `agent/internal/inventory/command.go`, `command_linux.go` (r1; approved by the lead as a 4th file), `osinfo.go` and `osinfo_linux.go`, plus the `agent/.golangci.yml` exclusion (`work/reports/TASK-094-impl.md`).
- Checked against TS §3.4 L232–L238 and L240, §6.5 L1186, REQ-100, #35 and #77, and the lead rulings of 2026-10-24: Q1 (`ip_addresses` never null), the G204 scoped exclusion, and the size kept as one task.

TEST: PASS after round 1 (`work/reports/TASK-094-test.md`; rows CHK-M4-095 to -102). Round 0 failed CHK-M4-097: the background child of a killed command survived. r1 runs each command in its own process group and SIGKILLs the group. golangci-lint over the whole module, with the exclusion in place, reports 0 issues on both GOOS values.

## Checks
1. Spec and #35:
   - The only execs are `/usr/bin/hostnamectl`; `ip -j addr` from four fixed paths; and `dpkg-query -W -f=<TS §3.4 format>`.
   - There is no shell. The environment is exactly `PATH` and `LC_ALL=C`, the working directory is `/`, stdin and stderr are `/dev/null`, and each command has a time limit and an output cap.
   - `uname` and `nproc` are read without exec.
   - os_info fields follow #77, and every failure leaves a fixed reason in `raw.errors`. `ip_addresses` is `[]` with a reason on any failure (Q1), never null.
   - The `raw` size is capped at 256 KiB, measured without HTML escaping, so the measure is never below the manager's.
2. **The G204 exclusion, checked again after r1 as the lead asked.**
   - `path: ^internal/inventory/command\.go$`, `linters: [gosec]`, `text: G204`.
   - It is anchored, so it covers neither `command_test.go` nor `command_linux.go`.
   - `command_linux.go` imports `os/exec` only for the `*exec.Cmd` type and calls nothing that starts a process, so G204 has nothing to report there.
   - The only `exec.` call in non-test code is `command.go:100`. There is still no `//nolint`. The exclusion is no wider than the ruling.
3. r1, process groups:
   - `Setpgid` is set, and `cmd.Cancel` kills `-pgid` with SIGKILL, so the kill at the limit or the output cap reaches grandchildren. `WaitDelay` still bounds the wait on the pipes.
   - `reap` kills the group again after `Wait`, so no child outlives the call.
   - The agent runs as `bitscan`, so even a mistaken group kill reaches only that user's processes. It needs no extra privilege and no unit change.
4. Security invariants:
   - No argument comes from a job, a heartbeat or the manager (mutation rows CHK-M4-344 and -345).
   - Error and reason text never carry host output.
   - Inventory cannot be disabled from here.
5. Re-run by the reviewer (Windows): `gofmt` prints nothing; `GOOS=linux` vet and golangci-lint on `inventory` report 0 issues (run with TASK-091).

## Findings
1. nit, `command_linux.go:12-14`. The comment says the sweep after `Wait` "cannot hit an unrelated process". That holds while any group member is alive. When none is left, the pgid number is free, and in the microseconds between `Wait` and `reap` it could in theory be reused by a new group leader. The agent is unprivileged, so only another `bitscan` process could be hit. Optional: soften the comment, or skip `reap` when `Wait` reported that the group is gone. No behaviour change needed.
2. nit (builder checklist item 14), `osinfo.go:347`. `readSmall` opens `/etc/os-release`, `/proc/meminfo` and `/proc/uptime` without a type check, so a FIFO would block collection. These paths are owned by root or the kernel. `ReadOSRelease` also runs at enrolment, before the loops start. Optional: reuse the stat-then-nonblocking-open pattern from `config.readableFile`.
