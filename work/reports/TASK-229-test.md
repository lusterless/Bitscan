# TASK-229 TEST (r0, r1, r2; local parts): PASS

Tester: tester-m10c, 2026-11-01. One approval (TS §8.2; PD-43). REQ-257, REQ-260; decisions rows:
- "The delegated runner tests in CI are a TASK-229 r1";
- "Delegated real-kernel rows must run as the unit user";
- "TASK-229 r2: the CI delegated step matches the TASK-224 job rows".

Under test: `.github/workflows/agent.yml` (impl-deploy-m10 r0/r1, impl-deploy-m10c r2; `work/reports/TASK-229-impl.md`):
- the gates job's "Runner and capread start-up refusals" step (r0), which replaces the M0 stub step;
- the go-test-ubuntu job's "Runner delegated cgroup tests" step (r1, r2), on `ubuntu-22.04` and `ubuntu-24.04`.

## How (local only; no push, so no hosted run)

`ci229.py` (outside the repo) parses the workflow and writes every `run:` block to a file. Each step's own shell was then run in WSL, from a copy:
- **Refusal step:** run as written by root, except two things. The "self" cases run as a non-root user `m10c-ci`, because the CI job user is non-root with a full bounding set. And the two `apt-get` lines are dropped (strace is installed).
- **Delegated step:** run as written, with `GITHUB_WORKSPACE=/opt/m10c/ws-<plant>` (a copy) and `RUNNER_TEMP=/root/m10c/rt`. Its `sudo systemd-run … -p User=bitscan-runner …` ran as is; root's sudo is a no-op. No step was refused by a safety check.
- Plants were made in each copy's files or in the extracted step script, never in the worktree.

## Runs

| Run | Command | Result |
| --- | --- | --- |
| YAML parse | `python3 -I ci229.py agent.yml` (PyYAML 6.0.1) | parses. `permissions: contents: read`. Every `uses:` is pinned to a 40-hex SHA. Jobs: gates on `ubuntu-24.04`; go-test-ubuntu with matrix `[ubuntu-22.04, ubuntu-24.04]` |
| `bash -n` | all 12 `run:` blocks | 12/12 OK |
| refusal step, M10 binaries | built by the step before it (static linux/amd64) | step exit **0** (6/6 cases) |
| delegated step, M10 tree | as written (r2) | step exit **0**: 37 `--- PASS`, 0 `--- FAIL` |
| plants | 3 refusal, 5 delegated | **8/8 red** |
| actionlint, shellcheck | — | NOT RUN: not installed on this host. Cover: the YAML parse, `bash -n`, and the step scripts run end to end |
| hosted PR run on both runners | — | NOT RUN: no push in this session (lead's brief). The local runs above are the same commands |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-313a (refusal step green on M10) | CODE | W | refusal step on the M10 build | PASS | All 6 cases: the exact stderr line (`time=` stripped), the exit code, empty stdout, and no socket call after the binary's execve. The cases:<br>• runner, full bounding set: `CapBnd holds capabilities beyond CAP_DAC_READ_SEARCH`, 1;<br>• runner as bitscan-runner with only dac_read_search: `sdsock: LISTEN_PID is not this process`, 1;<br>• `capread --serve`: the no-usable-socket line, 1;<br>• capread with no argument and with `/bin/sh`: the usage line, 2;<br>• `nft_ruleset` with the helper off: `not enabled`, 1 |
| CHK-M10-313b (red on the M0 stubs) | CODE | W | runner stub (`328b097`) | PASS (red) | Step exit 1. Both runner cases: "stderr is not the one expected line … got: bitscan-runner: not implemented" |
| CHK-M10-313c | CODE | W | capread stub (`328b097`) | PASS (red) | Step exit 1. All four capread cases red (exit 1 where 2 was wanted, and the stub line) |
| CHK-M10-313d | CODE | W | plant: the runner calls `net.Listen("unix", …)` before `run()` | PASS (red) | Step exit 1. strace shows `socket`/`bind`/`listen` after the execve, in both runner cases |
| CHK-M10-313e (r1/r2 delegated step green) | CODE | W | delegated step | PASS | It runs as bitscan-runner, ambient/bounding CAP_DAC_READ_SEARCH, NoNewPrivileges, PrivateTmp, StateDirectory and the r2 WorkingDirectory. The binary is in `/opt/delegated`, and the chmod loop gives o+x down the tree and o+r on the TS. Result: 37 PASS, unit exit 0 |
| plant A (r1) | CODE | W | a failing `TestDelegatedPlantedFailure` added | PASS (red) | Step exit 1 ("a test failed") |
| plant B (r1) | CODE | W | `-tags delegated` dropped from the build | PASS (red) | "no TestDelegated test passed; want at least one" |
| plant C (r2) | CODE | W | `-p PrivateTmp=yes` dropped | PASS (red) | `TestDelegatedJobTmpEmptied`: "refusing to empty /tmp and /var/tmp: they are not private mounts" |
| plant D (r2) | CODE | W | `-p WorkingDirectory=` dropped | PASS (red) | `TestDelegatedJobRedaction` fails: the TS isn't found from `/` |
| plant E | CODE | W | `-test.run NoSuchTestM10c` (zero tests run) | PASS (red) | "no TestDelegated test passed; want at least one" |
| CHK-M10-313f `go test ./...` on both hosts | CODE | — | `go-test-ubuntu` matrix | PASS (static) | The step `GOOS=linux GOARCH=amd64 go test ./...` sits in the matrix job on `ubuntu-22.04` and `ubuntu-24.04`. Its WSL equivalent is in the gate report |
| REQ-257 (2) | CODE | L | `grep -n 'arm64\|debian:12' .github/workflows/agent.yml` | PASS | nothing found |

## Acceptance (TASK-229: "the new step passes on the M10 binaries and turns red when the M0 stub runner is put back, and `go test ./...` runs on both runners")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| passes on M10 | CHK-M10-313a, e | PASS (local) |
| red with the M0 stubs | CHK-M10-313b, c | PASS (local) |
| `go test ./...` on both runners | CHK-M10-313f | PASS (static); hosted run NOT RUN (no push) |
