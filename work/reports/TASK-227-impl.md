# TASK-227 IMPL: `bitscan-agent` main for M10

Implementer: impl-agent-m10b, 2026-10-30. REQ-245, REQ-246, REQ-247, REQ-249, REQ-251. Spec: TS §1.1 G2; §2.2 L111; §3.3 L222, L226; §3.5; §3.7 L275. Plan: `work/plans/TASK-212.md` §6. Depends on TASK-219, 220, 223 (all reported). High risk (TS §8.2 second approval).

## Files

- `agent/cmd/bitscan-agent/main.go`: +31 / −3. No other file changed.

## What changed

After enrolment, in this order:
1. **Spool:** `spool.Open(<state_dir>/spool, spool_max_mb × 1,048,576, clock.Now)` (#4, #57). On success, `sp.Log = log` (overflow lines, TASK-219), `Deps.SpoolBytes = sp.Size` (heartbeat `spool_bytes`), and `sp.Close()` at exit.
2. `loops.NewRun(..., SpoolBytes: spoolBytes)`.
3. **Dropped entries** that `Open` returned: one Warn line each (`job_id`, `items`, `reason` `expired` or `unreadable`), and `last_error` = `spool: results dropped at start (<reason>)` (#139 (g); plan §6).
4. **Results sender:** `loops.NewSender(r, sp)`, with `Loop` started beside the heartbeat, pull and inventory loops (one goroutine, REQ-246 (6)).
5. **Compliance handler:** `&loops.Compliance{Run: r, Spool: sp, Sender: sender, Runner: &runnerclient.Client{}}` (the default socket `/run/bitscan/runner.sock`, real clock), passed as `Puller.Compliance`.

**If the spool cannot be opened** (a choice for the reviewer): start-up is **not** refused. Refusing would also stop inventory, which nothing in M10 may do (G2, REQ-249 (4)). Instead:
- one error line with the reason;
- `last_error` = `spool: not opened; compliance jobs refused`;
- `Compliance` stays a nil interface, so every compliance job is refused and logged by the puller (TASK-223);
- heartbeat `spool_bytes` is 0;
- inventory runs as before.

**SIGTERM mid-job:** the signal context cancels `Run.Context()`. The `Compliance.Handle` call and the runner client both use it, so the client's watcher cuts the runner connection at once (deadline into the past, then the deferred `Close`). The runner then cancels the job. The handler returns without `Finish`, so no final batch is sent for that job (#131 (d)); its spooled items stay on disk for the next start. The existing 5 s grace for in-flight work applies.

## REQ-251 (1): import boundary (checked)

`GOOS=linux go list -deps ./cmd/bitscan-agent`:
- from the runner tree, only `internal/runner/proto` (through `spool` and `runnerclient`);
- no `internal/runner` package other than `proto`, no `internal/redact`, no `internal/capread`, no `internal/sdsock`;
- `os/exec` comes only from `internal/inventory` (the M4 #35 command runner, unchanged).

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l cmd`: nothing.
- `go build ./...` (Windows): OK. `GOOS=linux go vet ./cmd/bitscan-agent/`: clean.
- `golangci-lint run --tests=false ./...` and the `GOOS=linux` run: 0 issues. A full run including tests also shows the TASK-223 note: `loops/pull_test.go` still names the removed `loops.Unavailable` until the PD-45 rewrite.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/bitscan-agent`: OK.
- Not run: the binary end to end. That is TP-M10-19 (`cmd/bitscan-agent/main_test.go`, a fake manager and a fake runner), on Linux.

## For the tester (tester-m10, TP-M10-19)

- **End to end:** a fake manager plus a fake runner listening at `/run/bitscan/runner.sock`. `runnerclient.Socket` is a constant and `main` uses the default `Client{}`, so the binary test needs that path; inside a sandbox or container it is writable. Otherwise run the walk on the sandbox host (G77/G76).
- **SIGTERM mid-job:** the fake runner holds after one result. After SIGTERM the process exits 0 within 5 s, `spool/<job_id>/job.json` has `finished: false`, and the one item file is present. After a restart the item is posted, the job is marked interrupted and no final follows.
- **Spool unopenable** (for example a regular file at `<state_dir>/spool`): the agent starts; a pulled compliance job is refused ("job refused: no compliance handler"); an inventory job is still uploaded; the first heartbeat's `last_error` is the spool line.
- Mutation rows:
  - **CHK-M10-380:** importing `internal/runner` or `internal/redact` into `cmd/bitscan-agent`. The `go list -deps` boundary test turns red. S.
  - **CHK-M10-370:** inventory waits for compliance. This needs the pull loop (TASK-223) plus `main`; plant a shared worker channel in `pull.go`. G73, G41.
