# Plan TASK-212: result spool and posting (D4)

Covers TASK-212 (`ag/internal/spool/spool.go`, `manifest.go`), TASK-219 (`overflow.go`), TASK-220 (`ag/internal/agent/loops/results.go`) and the spool side of TASK-223. REQ-245 to REQ-248, REQ-250. Open items #4, #57, #78 (d), #124 (f), #131 (d), #139, #140, #141.

## 1. Spec quotes

- TS §3.3 L222: "When the agent starts a compliance job it posts an empty results batch (`{"results": [], "final": false}`), which moves the job to `running` and starts its deadline (§4.4); only the first start notice counts."
- TS §3.3 L224: "400, 404, 409, 413 and 422, and 403 other than `pending_approval`, mean the manager will never accept that batch: the agent drops it from the spool, logs the reason locally and reports it as `last_error` in the next heartbeat. 401 stops the agent (§3.2 step 8); 403 `pending_approval` keeps it waiting. Only 429, 5xx and network errors are retried."
- TS §3.3 L226: "Both loops back off exponentially (10 s → 5 min cap). Finished results are spooled on disk (max 50 MB, already redacted) and sent once the manager is reachable. When the spool is full the oldest results are dropped first, and each dropped plugin is reported as ERROR `spool_overflow`."
- TS §3.5 L248: "The agent never stores plugin commands between jobs." L253: "Results are posted in batches of at most 50 results and at most 1.5 MB (gzip allowed, `Content-Encoding: gzip`). The last batch of a job carries `"final": true`."
- TS §4.4 L577: "When a job ends `failed` or `partial` because its deadline passed (agent crash, reboot), the manager creates one retry". L578: late results accepted until `dispatched_at` + 7 days.

## 2. Spool store (TASK-212)

Layout under `<state_dir>/spool/` (opened through `os.Root`, like `state.Store`):

```
spool/
  <job_id>/job.json       manifest
  <job_id>/<seq>.json     one Results item each (seq: 12-digit zero-padded)
```

```go
package spool

type Manifest struct {
    JobID       wire.UUID   `json:"job_id"`
    ReceivedAt  time.Time   `json:"received_at"`
    Plugins     []wire.UUID `json:"plugins"`   // payload order; never execute or patterns
    StartAcked  bool        `json:"start_acked"`
    Finished    bool        `json:"finished"`
    Interrupted bool        `json:"interrupted"`
    FinalAcked  bool        `json:"final_acked"`
}

type Spool struct { root *os.Root; max int64; now func() time.Time; mu sync.Mutex; size int64; /* index */ }

// Open loads every manifest and item index, marks unfinished jobs Interrupted
// (#131 (d)), drops jobs received more than 7 days ago (#139 (g)), deletes
// leftover temporary files, and recomputes the size.
func Open(dir string, maxBytes int64, now func() time.Time) (*Spool, []Dropped, error)

func (s *Spool) StartJob(job wire.UUID, plugins []wire.UUID) error
func (s *Spool) Put(job wire.UUID, r proto.Result) error // ErrFull until TASK-219
func (s *Spool) Finish(job wire.UUID) error
func (s *Spool) Size() int64                              // spool_bytes (#78 (d))

type Batch struct {
    Job   wire.UUID
    Start bool          // the start notice (empty, final=false)
    Items []proto.Result
    Final bool
    seqs  []uint64
}
// Next returns the oldest postable batch, or false. maxItems 50, maxBytes the
// uncompressed body bound; holdYoung: a running job's partial batch is held
// until its oldest item is 30 s old (#141).
func (s *Spool) Next(maxItems, maxBytes int, holdYoung time.Duration) (Batch, bool)
func (s *Spool) Ack(b Batch) error   // removes items; sets StartAcked / FinalAcked
func (s *Spool) Drop(b Batch) error  // same removal for a drop answer (#139 (e))
```

Rules:
- Atomic write: `name.tmp` with `O_CREATE|O_EXCL|O_WRONLY`, mode 0600, write, `fsync`, rename to `name`, `fsync` the directory. A `.tmp` left by a crash is deleted at `Open` and never read (REQ-247 (2)).
- Size: the sum of file sizes in bytes (manifests included), kept in memory and updated on every write and removal, checked against `spool_max_mb × 1,048,576`.
- Order: jobs by `ReceivedAt`, then `JobID`; items by `seq`.
- `Next` per job: if not `StartAcked` and no item was acked yet → `{Start: true}`; else up to 50 items fitting `maxBytes` (computed with `wire.Encode` of the would-be body); else, when `Finished` and no item is left and not `FinalAcked` → `{Final: true}` (empty). Interrupted jobs never yield a final batch. The last items batch of a finished job carries `Final: true` itself when it empties the job.
- A batch handed out by `Next` is "in flight" until `Ack` or `Drop`; overflow never converts its items (#140), and `Next` never hands out the same item twice.
- Removal: a job directory is deleted when every item is gone and (`FinalAcked` or `Interrupted`).
- Nothing in the spool holds a command, pattern, `eval_spec` or token (REQ-247 (5)); `Put` takes only `proto.Result`.

## 3. The start notice and acceptance

- The manager treats a non-empty first batch as a start too (M9 REQ-217 (2)); if items are acked before the notice (impossible in order, but after a drop of the notice), the notice is considered done.
- A drop answer on the start notice (for example 409 for a job cancelled on the manager) drops only the notice; the items are still tried, each dropped on its own 409 (#139 (e)); M9's #124 (f) keeps these out of the 409-flood alert.

## 4. Overflow (TASK-219)

```go
// makeRoom is called by Put when size+need > max; it converts the oldest
// full results (not in flight) to OverflowMarker, oldest first across jobs,
// until it fits; then drops the oldest markers (log line each) if markers
// alone exceed the bound. It reports whether the new item fits.
func (s *Spool) makeRoom(need int64) (fits bool, err error)
```

`Put`: compute the encoded size; if it does not fit after `makeRoom`, store `proto.OverflowMarker(r)` instead (the new item itself becomes a marker), calling `makeRoom` again for the marker's size. A marker keeps `plugin_uuid`, `started_at` and `finished_at`; `exit_code` null; empty streams; `timed_out`, `truncated` false; `error: "spool_overflow"`. Conversion rewrites the item file atomically under the same `seq`, so its place in the order is kept. Each conversion and each marker drop is logged once with `job_id` and `plugin_uuid` (no output).

## 5. Results sender (TASK-220)

```go
type Sender struct {
    Run   *Run
    Spool *spool.Spool
    wake  chan struct{} // buffered 1
}
func NewSender(r *Run, s *spool.Spool) *Sender
func (s *Sender) Wake()
func (s *Sender) Loop() // until Run's context ends
```

Loop: `b, ok := Spool.Next(50, 1_572_864, 30*time.Second)`; none → wait for `Wake`, a 30 s tick or the context; else post:
- body = `wire.Encode(wire.ResultsRequest{Results: items, Final: b.Final})` (the start notice is `{"results": [], "final": false}`), gzip it, `transport.Request{Op: OpResults, JobID: b.Job, Body: gz, Gzip: true}` through `Run.Call`;
- `Success` → `Ack`, reset back-off; `Drop` → `Drop` (Run.Call already logged it and set `last_error`); `Wait`/`Retry` → keep it and sleep `back.Next()` (10 s doubling to 5 min, jitter, `schedule.NewBackoff`); `Stop` → return.
- One goroutine only, so a job's batches are posted in order (REQ-246 (6)).

## 6. The handler's use of the spool (TASK-223)

`StartJob` before contacting the runner; `Put` for every received result and every #131 (b) fill; `Finish` at the end (not on agent stop); `Wake` after each. `Run.Deps.SpoolBytes = spool.Size` feeds the heartbeat. `cmd/bitscan-agent` (TASK-227) opens the spool at `<state_dir>/spool` with `cfg.SpoolMaxMB × 1,048,576`, logs and sets `last_error` for every `Dropped` entry `Open` returns, starts `Sender.Loop` beside the other loops, and passes the handler to the puller.

## 7. Tests and plants

TP-M10-05, 12, 13, 16; mutation rows CHK-M10-356, -359 to -368, -392.
