# TASK-104 IMPL: inventory jobs and watcher uploads

REQ-101, REQ-102, REQ-100. TS §3.4 (L239–L240, L244), §3.3 L224–L226, §6.5 L1186. #72 (a), (e); #80; lead rulings 2026-10-24 Q2 (a failed collection uploads nothing). Plan `work/plans/TASK-104.md`, "Upload loop". **Two approvals (TS §8.2, agent).** No tests were run (tester's job).

## Files

| File | Code lines | What |
| --- | --- | --- |
| `agent/internal/agent/loops/inventory.go` (new) | 130 | `Inventory` (implements `InventoryRunner` from TASK-101's `run.go`), `NewInventory`, `RunJob`, `Unscheduled`, `Watch`, and the types `Collector` and `DpkgWatcher`. |

No other file changed. It uses `run.go` (TASK-101), `inventory.HoldOff` and the `Watcher` (TASK-091), and production passes `inventory.CollectBody` (TASK-094, 095) as the `Collector`.

## API

```go
type Collector func(ctx context.Context) ([]byte, error)                   // inventory.CollectBody
type DpkgWatcher interface { Run(ctx context.Context, out chan<- struct{}) error } // *inventory.Watcher
func NewInventory(r *Run, collect Collector) *Inventory
func (inv *Inventory) RunJob(ctx context.Context, jobID wire.UUID)  // called by TASK-103 for each accepted inventory job
func (inv *Inventory) Unscheduled(ctx context.Context)              // one unscheduled upload
func (inv *Inventory) Watch(ctx context.Context, w DpkgWatcher)      // TASK-106 runs it in a goroutine with inventory.NewWatcher(inventory.DpkgDir, clock)
```

## Behaviour

- **Upload:** `PUT /api/v1/agent/{id}/inventory`, plus `?job_id=<id>` for a job, through `Run.Call` with `Gzip: true`. The transport sets `Content-Encoding: gzip` and `Content-Type: application/json`, and `Call` sets the current token. The body is built once per attempt series, and a retry sends the same bytes. The collector takes only `ctx`, so no job, heartbeat or answer value reaches a command (#35, CHK-M4-101 and -345).
- **Answers:** Success (204) ends the upload. Drop (409, 413, 422, 400, 404, a 403 other than `pending_approval`) is logged and becomes `last_error` (`inventory 422 about:blank`) in `Call`, with no retry. Stop (any 401) stops every loop, in `Call`. Wait (403 `pending_approval`), 429, 5xx and network errors are retried with a fresh `schedule.Backoff` per upload (10, 20 … 300 s, ±10 %). 429's `Retry-After` is not used, as in the heartbeat loop.
- **Job uploads (`RunJob`):** the 30-minute window starts when `RunJob` is called. A retry whose back-off would end after `received + 30 min` is not made, and one fixed line is logged with the `job_id`. Job uploads run one at a time (mutex) and never wait for the unscheduled hold-off (#72 (e): only the `dispatched` case is exempt from the manager's window).
- **Unscheduled uploads:** one at a time (mutex). Before each attempt, the upload waits until `HoldOff` (10 min 30 s, #80) after the last unscheduled upload answered with success, so two accepted unscheduled uploads are never closer than that, also after 429 retries. A watcher signal that arrives during the hold-off or a back-off wait marks the body stale, and the next attempt collects again, so the latest state is sent (the signal replaces the pending one; it does not make a second upload).
- **`Watch`:** runs the watcher in a goroutine and makes one unscheduled upload per signal until `ctx` ends. If the watch cannot be set, or fails later, one fixed line is logged and `Watch` returns. Job uploads are independent of it (REQ-102 (4)). `Watch` waits for its goroutine before returning.
- **Collection failure (Q2):** nothing is uploaded. One fixed line is logged, and `last_error` = `inventory collection failed` (not set when `ctx` ended). No error text is logged.
- **Logs:** fixed text, with only `agent_id` and `job_id` attributes. No body, package list, token or host text is logged.

## Checks run (Windows, golangci-lint 2.14.0)

- `gofmt -l agent/internal/agent/loops`: nothing.
- `GOOS=linux go vet ./internal/agent/loops/`: clean. `CGO_ENABLED=0 GOOS=linux go build ./...`: ok.
- `golangci-lint run ./internal/agent/loops/`, GOOS=linux and windows: 0 issues. The whole-tree run is red only from the tester's `internal/inventory/watch_linux_test.go` (reported to tester-m4b).
- Builder checklist: 10 (every wait selects on `ctx`) and 11 (nothing secret or host-sourced in logs) hold; the rest are manager-side.

## For the tester

TP-M4-19 (CHK-M4-235 to -241), mutation rows CHK-M4-350 to -352 and -337. Build a `Run` with TASK-101's `Deps` (fake `Doer`, fake clock, seeded source), then `NewInventory(run, fakeCollector)`, or `inventory.CollectBody` for the gzip and `list_sha256` checks. For the watcher cases, pass a fake `DpkgWatcher` whose `Run` sends on `out`, or returns an error at once for CHK-M4-240. `RunJob` and `Unscheduled` block until they finish; run them in goroutines when the fake clock must be advanced.
