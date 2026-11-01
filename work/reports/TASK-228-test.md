# TASK-228 TEST: PASS

Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-237 (2), REQ-238, REQ-240, REQ-251 (1), (3); TS §3 L152, §3.5, §3.7 L276–L285, L289–L359. Decisions rows covered:
- TASK-215 approval: "unproven: ProtectSystem=strict on the cgroup tree, TasksMax and MemoryMax with 8 plugins, SystemCallFilter including pidfd, RestrictNamespaces";
- TASK-216 approval: "(c) moved to WSL: CapEff/CapBnd = 4, also CapPrm and CapAmb";
- TASK-213 approval: "unproven: the runner reads `agent_id` through the 0700 state dir";
- TASK-217 approval: "socket root:bitscan 0660 in a root 0755 dir; a non-member gets EACCES";
- TASK-221 r2 at binary level;
- TASK-224 r2 end to end.

Code under test: `agent/cmd/bitscan-runner/main.go`. Its r2 changes are the m0 `init` lock (TASK-221 r2) and `pathless` (TASK-224 r2). Impl report: `work/reports/TASK-228-impl.md`.

## How (WSL Ubuntu 24.04, cgroup2fs, systemd 255; root runs the harness only)

Test files (new, tester-owned):
- `e2e/runner_unit_m10.sh`;
- `e2e/runner_client_m10.py`, the agent's half of #130, run as user `bitscan`.

The harness runs the built static runner under a **transient** `systemd-run --unit=m10c-runner` carrying:
- **all 37 `[Service]` directives of `deploy/systemd/bitscan-runner.service`**, read from the file verbatim: User/Group, both capability lines, NoNewPrivileges, Delegate, ProtectSystem=strict, PrivateTmp, NoExecPaths/ExecPaths, ProtectHome=read-only, UMask, PrivateDevices, PrivateIPC, RemoveIPC, the Protect*, Restrict*, LockPersonality, both SystemCallFilter lines, SystemCallErrorNumber, RestrictAddressFamilies, IPAddressDeny, both InaccessiblePaths lines, MemoryMax=256M, TasksMax=64, CPUQuota=25%, Restart=always, RestartSec=10;
- the 5 `[Socket]` directives of `bitscan-runner.socket` as `--socket-property`.

**systemd-run accepted every directive; none was rejected, so there is no NOT RUN property.** Differences from the shipped unit:
- ExecStart is `/usr/local/lib/m10c/bitscan-runner` (under `/usr`, so `ExecPaths=` allows it);
- `[Unit]`/`[Install]` don't apply to a transient unit.

The shipped units were never installed or enabled.

WSL set-up:
- user `bitscan` created (missing before);
- `/var/lib/bitscan-agent` created `bitscan:bitscan 0700`, with `agent_id` (0644). It was removed afterwards, as were the marker files and the binary dir.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W, unit row | `e2e/runner_unit_m10.sh <worktree> /opt/m10c/ru-base base` | **34/34 passed**, 0 failed, 0 errors, 0 skipped |
| W | `go test -race ./cmd/bitscan-runner/` (TASK-224 r2 `pathless`) | 8/8 passed |
| plants | 3 binary-level variants of the same walk, plus 1 below | 2/3 red; 1 NOT REPRODUCED at binary level (recorded below) |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-188a (REQ-237 (2); TASK-216 (c)) | APP | W | unit row | PASS | The runner's `/proc/<pid>/status`: Uid/Gid 999/988; **CapInh, CapPrm, CapEff, CapBnd and CapAmb each `0000000000000004`**; NoNewPrivs 1; Seccomp 2 |
| CHK-M10-188b (start-up checks) | APP | W | unit row | PASS | `Harden`, `CheckStartup`, `FromSystemd`, `Open` and `Sweep` all pass under the verbatim unit. The journal has "bitscan-runner started", and the socket is `root:bitscan 660` in `/run/bitscan` `root:root 755` |
| CHK-M10-188c (8 parallel plugins) | APP | W | job 1 (8 plugins, `max_parallel_plugins` 8) | PASS | `accepted`, 8 `result`, `done`, EOF. The plugins' own timestamps show 8 running at once, under TasksMax=64 and MemoryMax=256M. Each plugin: exit 0, its own `…/p-<n>` (8 distinct, never `supervisor`), niceness 10, uid 999. With CAP_DAC_READ_SEARCH a plugin reads `/etc/shadow` through ProtectSystem=strict. Then 10 more jobs of 8 plugins each ended `done` (88 spawns in all) |
| CHK-M10-188d (cgroup moves and kills; TASK-215's unproven items) | APP | W | job 1 | PASS | Each plugin backgrounded `sleep 300.228`. After the job:<br>• no such process is left (the kill and the after-job sweep with pidfd ran under `SystemCallFilter=@system-service ~@debug…`);<br>• the service subtree holds only `supervisor`;<br>• the runner's `/proc/<pid>/cgroup` ends in `/supervisor`.<br>The delegated writes worked under ProtectSystem=strict, and plugin start worked under RestrictNamespaces=yes |
| CHK-M10-188e (cleanup only on the PrivateTmp mounts) | APP | W | job 1 | PASS | Each plugin wrote `/tmp/p<n>` and `/var/tmp/q<n>`. After the job, `nsenter -t <runner> -m ls -A /tmp /var/tmp` lists nothing. The host's `/tmp/m10c-host-marker` and `/var/tmp/m10c-host-marker` are untouched |
| TASK-213 unproven item | APP | W | job 1 accepted | PASS | Under the verbatim unit, the runner (bitscan-runner, only CAP_DAC_READ_SEARCH) read `/var/lib/bitscan-agent/agent_id` through the `bitscan:bitscan 0700` directory: the job's `agent_id` check passed. The agent state dir is unchanged |
| TASK-217 unproven items (REQ-235 (3) in WSL) | APP | W | unit row | PASS | `nobody` (not in group `bitscan`) gets EACCES from `runner.sock` (0660). Root connects and is closed without any frame (the peer uid check); the journal has `peer refused … uid=0` |
| CHK-M10-189 (dumpable) | APP | W | unit row | PASS | `/proc/<runner>/environ` is owned by root, not bitscan-runner: `PR_SET_DUMPABLE` 0. The outside-systemd refusals (exit 1, one line) are TASK-229's step, run locally there |
| TASK-221 r2 at binary level | APP | W | unit row | PASS | After 88 spawns, every runner thread (7–15 seen) is at niceness 0 |
| CHK-M10-190 (REQ-251 (3)) | APP | W | journals of jobs 1–3 | PASS | No `CANARY` (execute and stdout canaries) and no `SHADOW` output in the journal. Job lines carry `job_id` |
| CHK-M10-191 (SIGTERM mid-job) | APP | W | job 2 | PASS | Two `sleep 300.191` plugins run. `systemctl kill -s TERM --kill-whom=main` reaches only the runner, so systemd killed nothing itself. The runner exited with status 0 ("bitscan-runner stopped"), and 1 s later no plugin process exists. The client saw no `done` |
| TASK-224 r2 end to end (pathless) | APP | W | job 3 with `-p BindReadOnlyPaths=/opt/m10c/ro-canary:/var/tmp/M10PATHCANARY-ro` | PASS | The after-job `/var/tmp` emptying fails on the read-only bind mount. No `done`. The journal gives "after-job cleanup failed", "job ended, cleanup failed" and `bitscan-runner stopping: cleanup cannot be guaranteed reason="unlinkat: read-only file system"`, with **no `M10PATHCANARY`** anywhere; the runner exited 1 |
| plant: `TmpDirs` nil in main | CODE | W | variant `notmp` | PASS (red) | 29/31: the private `/tmp` held `p0…p7` and `/var/tmp` held `q0…q7` after the job, and job 3's cleanup "failure" never happened (`done` sent) |
| plant: `Harden` skipped | CODE | W | variant `noharden` | PASS (red) | 30/31: "runner not dumpable" red (`environ` owned by bitscan-runner) |
| plant: the m0 `init` lock removed (TASK-221 r2) | CODE | W | variant `nolock` | **NOT REPRODUCED** at binary level (recorded) | 32/32 green twice. After 88 spawns, no runner thread was at nice 10. The real runner's main goroutine sits in `Serve`, and in these runs m0 never picked up a start goroutine, so this binary-level row can't tell lock from no lock. The lock's effect is proven at unit level: the delegated binary's plant `notestmainlock` is red, with m0 at nice 10. The `init` is present in main.go L31–36 (read) |
| CHK-M10-381 | CODE | L, W | `TestImportBoundary` (TASK-227 report) | PASS | `cmd/bitscan-runner` links no `net/http*`, `crypto/tls` or agent transport; the plant is red |

## Acceptance (TASK-228: "under `systemd-run` with the verbatim runner unit's properties and a socket unit (WSL with cgroup2, or CI), the driver's job runs and REQ-237 (2) and REQ-251 (1), (3) hold for `cmd/bitscan-runner`")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| A job runs under the verbatim unit (the harness client in place of the held driver) | CHK-M10-188c–e | PASS |
| REQ-237 (2) | CHK-M10-188a | PASS |
| REQ-251 (1) | CHK-M10-381 / TestImportBoundary | PASS |
| REQ-251 (3) | CHK-M10-190 | PASS |
| On a sandbox VM through the driver | — | NOT RUN: VM hold (the named gate exception). Cover: this WSL row with all 37 verbatim directives |
