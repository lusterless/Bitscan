# TASK-106 IMPL: `bitscan-agent` main

REQ-103, REQ-096. TS §3.1–§3.4, §3.2 step 8; #81 (a), (c); plan `work/plans/TASK-101.md`, "`main` (TASK-106)"; decisions 2026-10-24 "M4 work split" (`var version string` for TASK-102's `-X main.version`). **Two approvals (TS §8.2, agent).** No tests were run (tester's job).

**Spec-silent points, approved by the lead as coded (decisions 2026-10-24):** (1) an empty version exits 1; (2) local start-up refusals exit 1 with one fixed line and no manager call; (3) a refused enrolment stays idle until SIGTERM; SIGTERM exits 0 within 5 s. See "Start-up and exit" below.

## Files

| File | Code lines | What |
| --- | --- | --- |
| `agent/cmd/bitscan-agent/main.go` (replaces the M0 stub) | 106 | `var version string`, `main`, `run() int`, `refuse`. |

No other file changed. It wires TASK-087 (config), TASK-088 (state, seen ids), TASK-089/093 (TLS, client), TASK-098 (enrol), TASK-099 (token holder, rotator), TASK-101 (Run, heartbeat), TASK-103 (`Puller`, impl-agent), TASK-104 (`Inventory`, `Watch`) and TASK-091/094/095 (`inventory.NewWatcher`, `inventory.CollectBody`).

## Start-up and exit

1. `SIGTERM` and `SIGINT` cancel the root context (`signal.NotifyContext`).
2. **No version** (built without `-X main.version=…`): one line, exit 1. Every heartbeat and the enrol body would fail the contract self-check (`agent_version` min 1). **Testers: build with `-ldflags "-X main.version=<v>"`.**
3. `config.Load(config.Path)`, then the log level from `log_level` (`debug`, `info`, `warn`, `error`; `slog` text handler on stderr, so journald), then `enrol.ReadMachineID("/etc/machine-id")`, `transport.NewTLSConfig(ca_file, pin, "")`, `transport.NewClient`, `state.Open(state_dir)` and `store.LoadSeen` (fail closed, W1 ruling). Any failure: one line `start-up refused reason=<fixed package text>`, exit 1. None of these texts holds a token or a body. Restart=always restarts the agent, but no manager call is made.
4. `enrol.Enroller.Start` (#81 (c)): neither `token` nor `enroll.token` gives `ErrNoCredentials`, a start-up refusal, exit 1. A 401 (`enrol.ErrStop`), or any other error that is not retried, logs one line and the process **stays up idle** until a signal (#81 (a)), so the unit's 10 s restart never resends the enrolment. A signal during the enrolment back-off exits 0.
5. The loops run under one `loops.Run` with `RealClock` and `CryptoSource`. They are `Run.Heartbeat`, `Puller{Run, Seen, Inventory}.Loop` (a nil `Compliance` is #74's `Unavailable`) and `Inventory.Watch` on `inventory.DpkgDir`. The manager's `job_pull_seconds` and `max_parallel_plugins` replace the `agent.yaml` values from the first heartbeat on.
6. A 401 on any loop stops the loops (TASK-101); `main` keeps waiting for a signal (idle, #81 (a)).
7. On a signal, the loops end through the cancelled context. `main` waits at most 5 s for them, then exits 0. State writes are atomic (TASK-088), so an exit never leaves a partial state file.

## Rules held

- No listening socket, no exec here (commands are only in `internal/inventory/command.go`), and no write outside the state directory (the only writer is `state`).
- Logs: fixed messages, with `version` and `agent_id` attributes at start. No token, header, body, package list or plugin output is logged.

## Checks run (Windows, golangci-lint 2.14.0)

- `gofmt -l agent/cmd agent/internal/agent/loops`: nothing.
- `GOOS=linux go vet ./cmd/bitscan-agent/ ./internal/agent/loops/`: clean.
- `CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.version=0.1.0~pre1-1" ./cmd/bitscan-agent`: ok, and the version string is in the binary.
- `golangci-lint run ./cmd/bitscan-agent/ ./internal/agent/loops/` with GOOS=linux and windows: 0 issues.

## For the tester

TP-M4-21 (CHK for SIGTERM during a heartbeat, a pull and an upload; the canary sweep; the verbatim unit in WSL; no listening socket). The binary reads only the production paths (`/etc/bitscan/agent.yaml`, `/etc/machine-id`, `/etc/os-release`, `state_dir`), with no test-only flags or environment inputs (W1 ruling). Point `agent.yaml`'s `manager_url` and `ca_file` at the fake manager.
