# TASK-228 IMPL: `bitscan-runner` main (`cmd/bitscan-runner/main.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-237, REQ-238, REQ-240, REQ-251. Spec: TS §3 L152, §3.5, §3.7 L276–L285, §8.4 L1287. Open items applied: #137, #138 (a). Plan: `work/plans/TASK-215.md` §5 (the order in `main`). Depends on TASK-215, TASK-216, TASK-217, TASK-224 and TASK-225 (all reported).

## Files

- `agent/cmd/bitscan-runner/main.go`: rewritten (the M0 stub replaced), 102 lines, 69 code lines (estimate 110). It's `//go:build linux`: the runner is Linux only and every call it makes (`Harden`, `CheckStartup`, `sdsock`, `Open`, `Spawn`, `JobExecutor`) is Linux code. On Windows, `go build ./...` and `go vet ./...` skip it, as they skip `internal/sdsock`.

No other file changed.

## Start-up order (plan §5; the lead's "Setup, then Sweep" from the TASK-215 split)

1. `runner.Harden()`: `PR_SET_DUMPABLE` 0 first, checked by `PR_GET_DUMPABLE`.
2. `runner.CheckStartup(runner.SystemProbe())`: refuses euid 0, a `CapEff` or `CapBnd` beyond `CAP_DAC_READ_SEARCH`, no cgroup2, or a non-unified `/proc/self/cgroup`.
3. `sdsock.LookupUID("bitscan")`, then `sdsock.FromSystemd(uid, log)`: every inherited fd above 2 is made close-on-exec, then the `LISTEN_*` and fd 3 checks.
4. `runner.Open(log)`: own cgroup, `cgroup.kill`, `supervisor`, and the move.
5. `cg.Sweep(context.Background())`: the **start-up sweep**.
6. `signal.NotifyContext(SIGTERM, SIGINT)`, then `Server{Listener: ln, Checks: NewChecks(AgentIDPath), Exec: &JobExecutor{CG, Spawn: runner.Spawn, Now: time.Now, TmpDirs: {"/tmp", "/var/tmp"}, Log}, Clock: time.Now, Log}.Serve(ctx)`.

A failure in steps 1–5 gives one log line, `start-up refused` with `reason=<fixed words>`, and exit 1. systemd restarts the runner every 10 s, and the agent sees `runner_unavailable: connect` or `timeout` (#131 (e)).

## Shutdown and failure

- **SIGTERM or SIGINT:** `ctx` is cancelled. `Serve` closes the listener and waits for the running job. That job's context is cancelled, so the executor kills the running plugin cgroups, emits nothing more, and sweeps and empties `/tmp` and `/var/tmp`. Then main runs one more `Sweep` and exits 0.
- **Fatal executor error** (a sweep or the `/tmp` emptying failed, TASK-224 and TASK-225 contract): `Serve` returns it, main logs one line and exits 1, and systemd's default `KillMode=control-group` kills whatever is left in the service cgroup (#138 (c)).

## Acceptance points

- **REQ-251 (1):** `GOOS=linux go list -deps ./cmd/bitscan-runner` contains no `net/http`, `crypto/tls`, `internal/agent/transport`, `internal/agent/loops` or `internal/agent/state`. `os/exec` appears only through `internal/runner/spawn_linux.go`, as TASK-211 allows. The runner imports `internal/agent/wire` through `proto`, which is pure types.
- **REQ-251 (3) logs:** stderr only (journald), `slog` text lines, the same handler as `bitscan-agent`. Lines carry `job_id` and `agent_id` where known (serve and executor). Never `execute`, a pattern, output or a token. Every error text the main logs is a fixed-word error from these packages.
- **REQ-251 (5) / G10:** `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath ./cmd/bitscan-runner` gives `ELF 64-bit LSB executable, x86-64, statically linked`. Checked with `file`.
- **REQ-237 (2):** `CapEff` and `CapBnd` = `0000000000000004` comes from the verbatim unit. The runner refuses if they're wider (TASK-216). The REQ-237 (2) host row itself is a sandbox row.
- **REQ-238, REQ-240 at start-up:** `Open`, then `Sweep`, before the first `Accept`.
- **`version`:** set by `build-deb.sh`'s `-X main.version=…` and logged at start. Unlike the agent, the runner doesn't refuse an unversioned build: it sends its version nowhere, and the spec gives no such rule.

## Gates (from `agent/`)

- `gofmt -l cmd internal/runner internal/sdsock` on non-test files: nothing.
- `GOOS=linux go vet ./cmd/bitscan-runner/` and `GOOS=linux golangci-lint run ./cmd/bitscan-runner/... ./internal/runner/... ./internal/sdsock/...`: clean.
- Windows `go vet ./cmd/... ./internal/runner/... ./internal/redact/...`: clean (runner main skipped).
- The static linux/amd64 build passes, and `file` shows `statically linked`.

## Known red until TASK-229: CI `agent.yml`

`.github/workflows/agent.yml`, step "Run linux/amd64 runner and capread stubs" (L86–L109), asserts that `bitscan-runner`'s stderr is exactly `bitscan-runner: not implemented`. The real runner now refuses on a hosted runner with one `slog` line instead: a GitHub runner's `CapBnd` is the full set, and it has no `LISTEN_PID`. So this step **will be red on the branch until TASK-229** (impl-deploy), which replaces it with start-up refusal checks, as planned. TASK-228 doesn't touch `.github/`.

## For the tester (tester-m10, TP-M10-19)

These are Linux rows: under `systemd-run` with the verbatim runner unit's properties plus a socket unit (WSL with cgroup2, or CI), the driver's job runs.

| CHK | Plant | Red in |
| --- | --- | --- |
| -381 | `cmd/bitscan-runner` imports `net/http` or `internal/agent/transport` (S) | G75 (`go list -deps`) |
| -385, -386, -340, -329 (binary level) | Comment out `Harden` or `CheckStartup` in `run`. The unit-level plants are TASK-216's. | |
| — | Drop the start-up `Sweep` | A stray left in the service cgroup by a killed previous instance survives the restart |
| — | `TmpDirs` empty in main | CHK-M10-342 at binary level |

REQ-251 (1) for `cmd/bitscan-runner` is the `go list -deps` check above. The `cmd/bitscan-agent` half is TASK-227's (impl-agent-m10b).
