# TASK-101 plan: run state, loops and `main`

Covers TASK-101 (run state, heartbeat loop), TASK-103 (pull, job checks, dispatch) and TASK-106 (`main`). REQ-095, REQ-097, REQ-098, REQ-103, REQ-104. Owner: impl-agent. **Two approvals.** Tests: TP-M4-16, TP-M4-18, TP-M4-21; mutation rows CHK-M4-330 to 335, 345, 355, 356. Blocked on **#30**, **#74**, **#78**, **#81**.

## Spec quotes

- TS §3.3 L198–L206: two independent timers; heartbeat 300 s ± 30 s; pull every `job_pull_seconds` ± 30 s; manager values override `agent.yaml`, clamped 60–3,600 s and 1–8.
- L211–L214: "Nothing in a heartbeat response can make the agent run anything. The agent runs only jobs it fetched itself … only if it (1) is addressed to this host's `agent_id`, (2) has `pickup_by` in the future and no more than 25 h away, and (3) has not been run before. The agent remembers job ids for 7 days in its state directory."
- L216: "If a pull returns an empty list, the agent does nothing until the next timer fires: no extra polling and no collection."
- L222: "Jobs run one at a time, in the order the pull returned them, except inventory jobs, which run as soon as they are pulled".

## Run state (`loops/run.go`)

```go
type Run struct {
    ctx    context.Context; cancel context.CancelFunc // cancelled on a Stop class or SIGTERM
    clock  Clock; client *transport.Client; tokens *token.Holder; state *state.Store
    pull   atomic.Int64      // seconds, from the last heartbeat response, clamped
    lastErr atomic.Pointer[string] // sent once in the next heartbeat (#78), then cleared
    current atomic.Pointer[wire.UUID] // compliance job in progress (#78); never set in 0.x except during the #74 handling
}
type InventoryRunner interface{ RunJob(ctx context.Context, jobID wire.UUID); Unscheduled(ctx context.Context) }
type ComplianceHandler interface{ Handle(ctx context.Context, job wire.Job) }
func (r *Run) Stop(reason string) // logs the re-enrol line once and cancels ctx (#81: the process stays up, idle)
```

## Heartbeat (`loops/heartbeat.go`)

At start, one heartbeat at once, then every 300 s ± 30 s (TASK-090). Body per #78; `runner_helpers` = `["capread"]` if `/run/bitscan/capread.sock` exists (#30), else `[]`; `clock` = the agent's time. On success: set the pull interval, then `tokens.MaybeRotate`. Classes per TASK-093; `Wait` (403 `pending_approval`) keeps heartbeating with back-off; `Stop` calls `Run.Stop`.

## Pull and job checks (`loops/pull.go`, `loops/jobs.go`)

First pull after the first heartbeat attempt, then every `pull ± 30 s`. Each job in the answer, in order:
1. `agent_id` equals the stored id; `now < pickup_by ≤ now + 25 h`; `job_id` not in `seen_jobs.json`. Any failure: log the reason (fixed words), do not run, and still record the id as seen (a refused id is never retried).
2. Record the id as seen (persisted) **before** acting on it, so a crash cannot run it twice.
3. `inventory`: `InventoryRunner.RunJob` at once (in its own goroutine, one at a time per kind). `compliance`: `ComplianceHandler.Handle` per #74; in 0.x nothing is executed.

## `main` (TASK-106)

Load `agent.yaml` (refuse at start-up on error), open the state store, read `/etc/machine-id`, build TLS and client, enrol if #81 says, start heartbeat, pull and the watcher, wait for `SIGTERM`/`SIGINT` (cancel the context; give in-flight calls 5 s; never leave a partial state file) or for `Run.Stop` (then idle until a signal). Logs: `log/slog` text to stderr (journald), level from `log_level` (#4); version injected with `-ldflags -X main.version=…` by the build (TASK-102).
