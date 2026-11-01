# TASK-220 IMPL: results sender (`internal/agent/loops/results.go`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-246. Spec: TS §3.3 L204, L222, L224, L226; §3.5 L253; §6.3 L1136, L1138; §6.5 L1184. Open items applied: #57, #141. Plan: `work/plans/TASK-212.md` §5. High risk (TS §8.2 second approval).

## Files

- `agent/internal/agent/loops/results.go` (new, 111 code lines). No other file changed.

## Interface (used by TASK-223 and TASK-227)

```go
type Sender struct { Run *Run; Spool *spool.Spool /* + wake chan, buffered 1 */ }
func NewSender(r *Run, s *spool.Spool) *Sender
func (s *Sender) Wake()  // never blocks; call after StartJob, Put and Finish
func (s *Sender) Loop()  // one goroutine; returns when the Run stops (401 or SIGTERM)
```

Constants: `maxBatchBody = 1_572_864` (the uncompressed JSON bound, #57/#141) and `holdYoung = 30 s`. It reuses `maxBatch = 50` from `jobs.go`.

## Behaviour

- **Order:** `Loop` takes batches only from `Spool.Next(50, 1_572_864, 30 s)`. The spool hands out the start notice first, then items in `seq` order, then the final batch, with at most one batch per job out at a time. One goroutine posts them, so a job's final is never posted before every earlier entry of that job was answered (REQ-246 (6)).
- **Body:**
  - `wire.Encode(wire.ResultsRequest{Results: items, Final: b.Final})`, always gzip-compressed, with `transport.Request{Op: OpResults, JobID, Body, Gzip: true}`, so `Content-Encoding: gzip` (#141).
  - The start notice is `{"results":[],"final":false}`: a non-nil empty slice, so it passes the contract.
  - The size bound is enforced by `Spool.Next` (file bytes are the encoded item bytes).
- **Answers (TS §3.3 L224, the M4 classes through `Run.Call`):**
  - `Success` → `Spool.Ack` (the answer is decoded strictly; a bad answer is logged and still counts as sent, as in M4).
  - `Drop` (400, 404, 409, 413, 422, a 403 other than `pending_approval`) → `Spool.Drop`. `Run.Call` has already logged it and set `last_error`. Only that batch is dropped; later batches of the job are still tried (#139 (e)).
  - `Wait` (403 `pending_approval`) and `Retry` (429, 5xx, network) → keep the batch and sleep `schedule.NewBackoff` (10 s doubling to 5 min, ±10 %) on the Run's clock, then resend the same body. A fresh back-off starts with each batch.
  - `Stop` (401) → `Run.Call` stops every loop, and `Loop` returns.
- **Timing (#141):**
  - A batch goes out at once when it is full (50 items or the size bound), when the job is finished or interrupted, and for the start notice.
  - A running job's partial batch is held by the spool until its oldest item is 30 s old.
  - The sender sleeps until `Wake`. The first wake after a post arms one 30 s timer on the Run's clock. Every item spooled since that post is no older than the timer, so when it fires the held items are due and go out.
  - While the spool is non-empty, the timer re-arms on each fire as a safety net. With an empty spool the sender only waits for a wake (no idle polling).
- If a `Spool.Ack`/`Drop` fails, one error line with `job_id` is logged ("may be posted again"; the manager counts a re-post as duplicates).
- An encoding failure (impossible for items that passed `proto.NewResult`) drops the batch and sets `last_error` to "results batch refused".
- **Logs:** `job_id` and fixed words only. No item, stdout or stderr is ever logged.

**Known limit (for the reviewer):** a `Wake` that arrives with nothing new to hold can arm the timer early. A result spooled a little later is then posted at the next fire after it is 30 s old, so at most 30 s later than the rule. TASK-223 wakes only after `StartJob`, `Put` and `Finish`. A start-notice wake is followed by its post, which clears the timer, so this needs a wake with no change.

## How each acceptance point is met (REQ-246)

| Point | Evidence (smoke, Windows, throwaway copy, fake clock, fake Doer, real spool) |
| --- | --- |
| (1) 120 results: start notice, then 50, 50, 20 with `final: true` | After `Finish`: `n=50`, `n=50`, `n=20 final=true`, and then the spool size is 0. |
| (2) Body ≤ 1,572,864 uncompressed, one maximal item alone | `Spool.Next` byte accounting (TASK-212); the encoded body is the file bytes plus the 28-byte frame. Tester row. |
| (3) Each body decompresses to JSON valid against `ResultsRequest` | The fake Doer decompressed and `wire.DecodeStrict`ed every body: no error. |
| (4) 503 ×3 then 200: retried after 10, 20, 40 s and stored once; 409 drops one batch and the next is still posted; 401 stops | 503 at 30 s, then retries following 10 / 20 / 40 s (the clock was advanced in coarser steps), 200 on the fourth. One 409 batch was dropped (`last_error="results 409 "`), and the next three batches were posted. 401 is handled through `Run.Call`'s `Stop` (tester row). |
| (5) Three results then silence: posted 30 s after the first | Three puts at t = 0: nothing at 29 s; `n=3` at 30 s. |
| (6) Final never before earlier entries are answered | One sender goroutine plus the spool's one batch per job in flight. |

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/agent/loops`: nothing.
- `go vet` and `GOOS=linux go vet ./internal/agent/loops/`: clean.
- `golangci-lint run ./internal/agent/loops/...` and the `GOOS=linux` run: 0 issues.

## For the tester (tester-m10, TP-M10-13)

- On Windows each spool write fsyncs a file, so 120 puts plus 3 posts take several seconds. Wait on `Spool.Size() == 0` (bounded), not a fixed sleep.
- Mutation rows (no VM needed):
  - **CHK-M10-360** (51 items): plant `Next(maxBatch+1, …)`.
  - **CHK-M10-361** (over 1,572,864): plant `maxBatchBody = 2_000_000` with 50 items of ~40 KiB.
  - **CHK-M10-362** (409 retried): plant `case transport.Drop:` falling into the back-off.
  - **CHK-M10-363** (429 dropped): plant `case transport.Retry` settling with `Drop`.
  - **CHK-M10-368** (start notice missing or late): plant skipping batches with `b.Start` (Ack without posting).
- The start notice for TASK-223 is created by `Spool.StartJob` plus `Wake()`. The sender needs nothing else.

## Revision 1 (2026-10-30): release and rebuild after a failed attempt

Ruling: decisions row "#140 reading: in-flight protection covers only an outstanding HTTP attempt". Reviewer-m10's rule 2 applies.

`results.go` only:
- `post(b)` now makes **one** attempt and returns its `transport.Class`:
  - `Success` → `Ack`;
  - `Drop` → `Drop`;
  - `Wait` or `Retry` → left in flight;
  - a `Wait`/`Retry` caused by the Run's context ending (SIGTERM) → `Stop`.
- `Loop` keeps one back-off. On `Wait`/`Retry` it calls `Spool.Release(b)` before the back-off sleep, sleeps `back.Next()` on the Run's clock, then goes back to `Spool.Next`. Each retry is a **fresh batch with a fresh body**; the old body is never resent.
  - So an item converted to a `spool_overflow` marker during the back-off is posted as the marker.
  - The batch may hold a different set of items.
- `Success` or `Drop` resets the back-off, which is the same per-batch reset as before.
- Unchanged: the start notice first, ≤ 50 items, the ≤ 1,572,864-byte uncompressed bound, the final flag, the 30 s hold, and one sender goroutine. All of these still come from `Spool.Next`.
- `Wait` (403 `pending_approval`) is a failed attempt too and gets the same release-and-rebuild. The ruling names 429, 5xx and network errors; I applied it to the whole back-off path, since `pending_approval` backs off the same way. Say if `Wait` should keep its batch instead.
- Gates: `gofmt`, `go vet` and golangci-lint (Windows and `GOOS=linux`): clean.

For tester-m10:
- 503 → (convert an in-flight item by filling the spool during the back-off) → 200. The posted body carries the marker for that plugin, and the 503 body is never reposted byte for byte.
- The REQ-246 (4) timing still holds: 10, 20, 40 s.
- CHK-M10-362 and -363 still apply as planted against `post`'s switch.
