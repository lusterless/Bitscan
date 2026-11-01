# TASK-215 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (cgroups, TS §8.2 second approval). REQ-238, REQ-240 (the sweep), REQ-237 (the cgroup part of the start-up refusals); TS §3.5 L249–L250, §3.7 L284, L322–L323, L365, §8.1 L1245; #136 (a), #137, #138. The wider sweep (strays in the service-cgroup root are pid-killed too, and `supervisor/supervisor` is caught) was accepted by the lead under TS §3.7 L284 and is asserted as built.

Code under test (impl-agent-m10, `work/reports/TASK-215-impl.md`; split per the lead into three files): `agent/internal/runner/cgroup.go` (sha256 `6d919f5ba0131888…`), `sweep.go` (`07070fed83849316…`), `cgroup_linux.go` (`48bf11ae1634d528…`).

Test files (new):
- `agent/internal/runner/cgroup_test.go` (`2c89efd356a08173…`): portable fake-tree tests. The fake models the kernel rules the code relies on: one cgroup per pid, `cgroup.procs` moves a whole process, `cgroup.kill` kills the whole subtree (the runner too, if it's there), `rmdir` only when the cgroup is empty and has no children, and symlink entries.
- `agent/internal/runner/cgroup_delegated_linux_test.go` (`9dace1cae4f84145…`, build tag `delegated`): the real code in a delegated cgroup.

Plan rows: CHK-M10-100 to -106, plus mutation rows CHK-M10-336 to -339 (the G72 half).

## Where the delegated rows ran

In WSL Ubuntu 24.04: cgroup2fs, systemd 255, with `systemd-run --wait --pipe --collect -p Delegate=yes <race-built test binary> -test.run Delegated` (the script `deleg.sh`, kept outside the repo). The transient unit's cgroup was `/system.slice/run-uNN.service`. So the delegated rows ran locally, not only in CI. They need `-tags delegated` and `systemd-run`, so a plain `go test ./...` does not run them. **For the lead / impl-deploy:** G72's delegated half needs a CI step that runs them the same way (see the note at the end).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -run TestCgroup ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -run TestCgroup -v ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| WD (delegated, -race) | `deleg.sh base ./internal/runner/ Delegated` | **5/5 passed** (1 test, 4 subtests), unit exit 0 |
| static | gofmt; golangci-lint (Windows; `GOOS=linux --build-tags delegated`) | clean |
| plants | 14 runs (10 fake tree, 4 delegated) | **14/14 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-100 | CODE | L, W | `TestCgroupExactOperations` | PASS | REQ-238 (1). The exact operation log is: `mkdir supervisor`, `write supervisor/cgroup.procs <self>`, `mkdir p-1`, `write p-1/cgroup.procs <self>`, `write supervisor/cgroup.procs <self>`, `write p-1/cgroup.kill 1`, `rmdir p-1`. Nothing else is written. The child is born in `p-1`, dies at `cgroup.kill`, and the runner ends in `supervisor`. Names are `p-1`, `p-2`, `p-3`, from a counter |
| CHK-M10-101 | CODE | L, W | `TestCgroupSetupRefusals`, `TestCgroupSweepKillsEveryStray` (symlink entry) | PASS | `/proc/self/cgroup` refused when empty, two `0::` lines, a v1 line beside `0::`, a v1-only line, a relative path, `0:/x`, `0::`. `Setup` refused with no `cgroup.kill`, when `supervisor` can't be made (not delegated), and when the move into `supervisor` fails; an existing `supervisor` is fine. A symlink entry `p-9` is never touched by the sweep |
| CHK-M10-102 | APP | WD | `TestDelegatedCgroups` (setup + "plugin born in its own cgroup") | PASS | REQ-238 (2), (3). After `Open`, the runner's `/proc/self/cgroup` ends in `/supervisor`. The plugin's first action `cat /proc/self/cgroup` and its first fork (`sleep 30 &`) are both in `<service>/p-1`. The runner is back in `supervisor` straight after `StartIn` |
| CHK-M10-103 | APP | L, W, WD | `TestCgroupSweepKillsEveryStray`; delegated "sweep kills strays everywhere" | PASS | Strays in `supervisor`, `supervisor/x/y`, `p-3`, `p-3/child`, `q/r`, `supervisor/supervisor` and the service root are all killed. Only `supervisor` is left (REQ-238 (4)) and the runner is alive in it. Real kernel: 6 `sleep 300` strays (supervisor, supervisor/x, p-77, p-77/child, q/r, the service root) all die within 3 s, the subtree holds only `supervisor`, there's no cgroup under `supervisor`, and the runner is alive. **Recorded:** a write into the service root's `cgroup.procs` was accepted (subtree_control empty) |
| CHK-M10-104 | APP | L, W, WD | `TestCgroupRunnerMovedBack`; delegated "runner moved by a plugin" | PASS | #138 (b). Moved into the plugin's cgroup, the runner is moved back before `Kill`, so it doesn't kill itself, and before the sweep. Real kernel: the runner moved into `p-88` → after `Sweep` it's in `supervisor`, and the `sleep` beside it is dead |
| CHK-M10-105 | APP | L, W, WD | `TestCgroupWaitEmptyBound`; delegated "kill a forked tree" | PASS | `WaitEmpty` honours the caller's deadline (100 ms, not 5 s), `emptyWait` = 5 s, and a populated cgroup can't be removed. Real kernel: `sh -c 'sleep 300 & sleep 300 & (sleep 300 &); wait'` → `cgroup.kill` → `populated 0` after 11 ms (recorded), then rmdir |
| (extra) | CODE | L, W | `TestCgroupStartInFailsClosed` | PASS | The hop fails closed. A refused write to `p-n/cgroup.procs` → `start` not called. `/proc/self/cgroup` not showing `p-n` after the write → `start` not called. `start`'s own error is returned. In every case the runner is back in `supervisor` |
| (extra) | CODE | L, W | `TestCgroupSweepRepeatsAndFailsClosed` | PASS | A stray that moves to a new cgroup just before each of 3 kills is caught by a later pass. An unkillable stray makes `Sweep` return an error after about 5 s (so the runner exits) |
| CHK-M10-106 | CODE | L, W | `TestCgroupSpawnLock` (-race on W) | PASS | While a hop is open, a concurrent `Sweep`, another `StartIn` and a `Kill` make no operation at all; they run after the hop closes |
| CHK-M10-338 | CODE | W, WD | plant: `killPids` dropped | PASS (red) | Fake: `SweepKillsEveryStray`, `SweepRepeatsAndFailsClosed` failed. Delegated: the strays in `supervisor` and the service root survived. The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-339 | CODE | W, WD | plant: `supervisor`'s children skipped | PASS (red) | Fake: `SweepKillsEveryStray` failed. Delegated: the stray in `supervisor/x` survived and `x` was left. VM half NOT RUN |
| CHK-M10-336 (G72 half) | CODE | W | plant: the `p-n/cgroup.procs` write and the post-hop check removed (child born in `supervisor`) | PASS (red) | `ExactOperations`, `StartInFailsClosed` failed. (With only the write removed, the post-hop check still refuses the start, which is fail closed.) VM half NOT RUN |
| CHK-M10-337 (G72 half) | CODE | W, WD | plant: `kill` writes nothing | PASS (red) | Fake: 4 tests failed. Delegated: `cgroup not empty: context deadline exceeded` in every subtest. VM half NOT RUN |
| extra 215a | CODE | W, WD | plant: the service root left out of the pid kill | PASS (red) | Fake and delegated (stray 6 in the service root survived) |
| extra 215b | CODE | W | plant: one sweep pass only | PASS (red) | `SweepRepeatsAndFailsClosed` failed (the escaping stray survived) |
| extra 215c | CODE | W | plant: the post-hop `here()` check weakened | PASS (red) | `StartInFailsClosed` failed |
| extra 215d | CODE | W | plant: no `ensureSupervisor` before `cgroup.kill` | PASS (red) | `RunnerMovedBack` failed (the runner killed itself) |
| extra 215e | CODE | W | plant: no `cgroup.kill` presence check | PASS (red) | `SetupRefusals` failed |
| extra 215f | CODE | W | plant: multi-line `/proc/self/cgroup` accepted | PASS (red) | `SetupRefusals` failed |

## Acceptance (TASK-215: "on a fake cgroup tree REQ-238 (1) holds; under `systemd-run -p Delegate=yes` a planted stray in supervisor, in a nested cgroup and in a plugin cgroup are all gone after Sweep, and the runner stays alive in supervisor")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-238 (1) on a fake tree, including `..`/`/`/symlink refusal | CHK-M10-100, -101 | PASS |
| strays in supervisor, nested and in a plugin cgroup gone after `Sweep` (delegated) | CHK-M10-103 (WD) | PASS |
| the runner alive in supervisor | CHK-M10-103, -104 (WD) | PASS |
| REQ-238 (2)–(4) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-102, -103 (WD, the real kernel in WSL) |

## Note for the lead (not a finding against TASK-215)

The delegated tests are behind `//go:build linux && delegated` and need root plus `systemd-run -p Delegate=yes`, so `go test ./...` in CI doesn't run them. For G72's "delegated parts under `systemd-run -p Delegate=yes` (CI)", `agent.yml` (impl-deploy) needs a step such as:

```sh
go test -c -race -tags delegated -o runner.test ./internal/runner/
sudo systemd-run --wait --pipe --collect -p Delegate=yes ./runner.test -test.run Delegated -test.v
```

I'll add the TASK-221 and TASK-224 delegated tests to the same binary.

## r1 evidence: delegated rows as the unit's user (reviewer-m10 finding 1; decisions row "Delegated real-kernel rows must run as the unit user")

The same delegated binary and plants 338/339 were re-run unprivileged, as the runner unit's user. The command (via `deleg.sh` with `M10_AS_RUNNER=1`; binary copied to `/opt/m10test`, mode 0755):

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p WorkingDirectory=/opt/m10test /opt/m10test/base-__internal_runner_.test -test.run Delegated -test.v`

Setup in WSL: `useradd --system --no-create-home --shell /usr/sbin/nologin bitscan-runner` → `uid=999(bitscan-runner) gid=988(bitscan-runner)`. No test step needed root. The test file now logs its identity (`recordIdentity`); delegated test sha256 is `23dbd0b0d1e2e055…`.

| Run | Identity (recorded by the test) | Count / result |
| --- | --- | --- |
| `TestDelegatedCgroups` | uid 999, euid 999, gid 988; CapEff, CapPrm, CapBnd and CapAmb 0x4; NoNewPrivs 1 | **5/5 passed**, unit exit 0. Same evidence as root: plugin and first fork in `p-1`; 6 strays killed, including the service root (the write into the service root's `cgroup.procs` was accepted for the delegated user); runner moved back from `p-88`; forked tree emptied |
| plant CHK-M10-338 (`killPids` dropped), as bitscan-runner | same | **red**: strays 1 (supervisor) and 6 (service root) survived |
| plant CHK-M10-339 (`supervisor` children skipped), as bitscan-runner | same | **red**: stray 2 in `supervisor/x` survived and `x` was left |

So the cgroup and pidfd paths work with only `CAP_DAC_READ_SEARCH` and `NoNewPrivileges`, as the unit's user, and the plants still go red there. No product finding. The TASK-221 and TASK-224 delegated rows will use the same mode.
