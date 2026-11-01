# TASK-223 IMPL: compliance handler, run state and heartbeat (`internal/agent/loops`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-245, REQ-249, REQ-250. Spec: TS §3 L152; §3.3 L202, L211, L212, L222; §3.5 L248–L252; §3.7 L275, L282; §4.4 L577; §6.5 L1163. Open items applied: #28, #78 (c)–(e), #131. Plans: `work/plans/TASK-209.md` §7, `work/plans/TASK-212.md` §6. High risk (TS §8.2 second approval).

## Files (all five in the task list, nothing else)

| File | Change |
| --- | --- |
| `agent/internal/agent/loops/compliance.go` | new, 67 code lines: `RunnerClient`, `Compliance`, `Handle` |
| `agent/internal/agent/loops/jobs.go` | the #74 `Unavailable` handler and its `post` are removed (−60 lines); `compliance()` refuses a job when there is no handler |
| `agent/internal/agent/loops/pull.go` | a nil `Compliance` is no longer replaced by `Unavailable`; `Loop` logs one error line; doc comment updated |
| `agent/internal/agent/loops/run.go` | `Deps.SpoolBytes func() int64`; doc comment of `ComplianceHandler` updated |
| `agent/internal/agent/loops/heartbeat.go` | `spool_bytes` = `Deps.SpoolBytes()` (nil → 0, never negative) |

## Interface (used by TASK-227)

```go
type RunnerClient interface {
    Run(ctx context.Context, job wire.Job, maxParallel int, onResult func(proto.Result) error) error
} // *runnerclient.Client

type Compliance struct { Run *Run; Spool *spool.Spool; Sender *Sender; Runner RunnerClient }
func (c *Compliance) Handle(ctx context.Context, job wire.Job) // implements ComplianceHandler

Deps.SpoolBytes func() int64 // pass spool.Size
```

## `Handle` (plan TASK-209 §7)

1. `Spool.StartJob(job_id, plugin uuids in payload order)`, then `Sender.Wake()`. The sender posts the start notice first (TS §3.3 L222). If the spool refuses the job (for example `ErrFull`), one error line is logged with `job_id`, `last_error` is set to "spool: compliance job not recorded", and the runner is not contacted.
2. `Runner.Run(ctx, job, Run.MaxParallelPlugins(), onResult)`. `MaxParallelPlugins` is the clamped heartbeat value, or the `agent.yaml` value before any heartbeat answer (REQ-245 (6)). `onResult` calls `Spool.Put` (TASK-219 overflow included), records the plugin and wakes the sender.
3. **`ctx` ended** (SIGTERM, or a 401 stopping the Run): return at once. There is no fill and no `Finish`, so no final batch is ever sent for this job. The spool marks it interrupted at the next start, and its spooled items are still posted (#131 (d)).
4. **`*runnerclient.Failure`:**
   - log one Warn line with `job_id` and the word;
   - set `last_error` to `runner_unavailable: <word>`;
   - spool `proto.UnavailableResult(uuid, now)` for every plugin of the job without a received result. Results already received are kept (#131 (b)).
5. **Any other error** (a result the spool could not keep): log, and set `last_error` to "spool: result not kept". The missing plugins are not relabelled: neither manager error value fits "the agent's disk refused it".
6. `Spool.Finish`, then `Wake`. The final batch follows the items. The job is never resent to the runner, and the puller goes on to the next job.

The handler holds only the plugin uuids. The job (and so every `execute` and pattern) lives only in the `Handle` call and in the request the client writes. Nothing is logged except `job_id` and reason words.

## Other points

- **Nil handler refused** (task row). The plan doesn't say how; I chose the form that keeps G2. `Loop` logs one error line at start, and each compliance job is refused through `Puller.refuse` ("job refused: no compliance handler" as `last_error`). It is not run another way. Inventory jobs keep running. A panic or a `Loop` that refused to start would also have stopped inventory.
- **One at a time, in pull order** (REQ-249): unchanged. `work()` runs the compliance channel in one goroutine, and its `pickup_by` check before start stays (REQ-249 (2)). Inventory has its own channel and goroutine (REQ-249 (3), CHK-M10-370).
- **Heartbeat** (REQ-250):
  - `current_job_id` is set by the unchanged `compliance()` wrapper;
  - `last_error` uses the M4 send-once-then-clear (#78 (e)), so each job that meets an unavailable runner sets it again;
  - `spool_bytes` is the spool's `Size()`;
  - the heartbeat answer still only sets intervals: it never reaches the handler or the runner.

## Smoke run (Windows, throwaway copy outside the repo)

Real `runnerclient` against a fake runner on AF_UNIX, a real spool, the real `Sender`, and a fake Doer that decompresses every body:

| Case | Posts seen | `last_error` |
| --- | --- | --- |
| normal (3 results, done) | `final=false []`, then `final=true [001:ok 002:ok 003:ok]` | none |
| EOF after 1 of 3 | `final=false []`, then `final=true [002:ok 001:runner_unavailable 003:runner_unavailable]` | `runner_unavailable: broken` |
| `refused bad_patterns` | `final=false []`, then `final=true` with all three `runner_unavailable` | `runner_unavailable: refused_bad_patterns` |
| ctx cancelled after 1 result | only the start notice; spool 514 bytes = heartbeat `spool_bytes` 514 | none |
| …then a reopen (agent restart) | `Next`: 1 item, `Final` false; then nothing (no final) | none |

- `max_parallel_plugins` seen by the runner: `[4 4 4]` (the `agent.yaml` value, no heartbeat yet).
- Canary sweep: `CANARY-EXEC-xyz` (in every `execute`) and `CANARY-PAT` (the pattern) appear in no file under the state directory.

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/agent cmd`: nothing.
- `go build ./...` and `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- `golangci-lint run --tests=false ./...` and the `GOOS=linux` run: 0 issues. `go vet` of the non-test code: clean.
- **The test package doesn't compile until the tester's PD-45 rewrite.** `internal/agent/loops/pull_test.go:240` uses `loops.Unavailable`, which this task removes as its row requires. So `go vet ./internal/agent/loops/` and a full `golangci-lint run ./...` report that type-check error on the test package. G8 and G73 are red until `pull_test.go` drops the reference.

## For the tester (tester-m10, TP-M10-16; PD-45)

- **First:** rewrite the TP-M4-18 `#74` rows in `pull_test.go` (the `loops.Unavailable` fallback at line 240 and its checks) to REQ-245, with the old → new CHK list (PD-45).
- **Still pending the user, per main:** `TestNoOtherJobSourceStatic` (CHK-M4-223/-220) forbids `runner.sock` and `"unix"` under `internal/agent/**`. `runnerclient/client.go` has both by design, and `loops/compliance.go` imports `runnerclient`.
- Mutation rows (no VM needed):
  - **CHK-M10-356:** the job, with `execute`, written to the spool or state dir. Plant `Spool.StartJob` getting the job (it would need a field). The canary sweep above turns red.
  - **CHK-M10-358:** resent to a restarted runner. Plant a second `Runner.Run` after a `Failure`. The fake runner's request count is then 2.
  - **CHK-M10-359:** a final for an interrupted job. Plant `Spool.Finish` before the `ctx.Err()` return.
  - **CHK-M10-367:** `spool_bytes` still 0. Plant `SpoolBytes: 0` in `heartbeat()`.
  - **CHK-M10-369:** two compliance jobs at once. Plant `go p.Compliance.Handle(...)` in `compliance()`.
  - **CHK-M10-383:** a received result's stdout logged. Plant a `Log().Info("result", "stdout", …)` in `onResult`. A canary grep of the logs turns red.
  - **CHK-M10-384:** a heartbeat answer connects to the runner. There is no code path; the fake runner sees no connection after heartbeats alone.
- On Windows the spool fsyncs every file; wait on `Spool.Size()`, not a fixed sleep.

## Revision 1 (2026-10-30): fill after a `Put` error

Ruling: decisions row "#140 reading: in-flight protection covers only an outstanding HTTP attempt" (TASK-223 r1).

`compliance.go` only. There is a new helper, `fill(jobID, ids, got, overflow)`:
- **Runner unavailable** (`*runnerclient.Failure`): unchanged first step. Each plugin with no stored result gets `runner_unavailable`. If a `Put` fails, that plugin and every later one get a `spool_overflow` marker instead.
- **A result could not be spooled** (`onResult`'s `Put` failed, so the client stopped the job): every plugin of the job with no stored result is stored as a `spool_overflow` marker. That includes the plugin whose result failed and the plugins that never ran. Markers come from `proto.OverflowMarker(proto.UnavailableResult(id, now))`, so `exit_code` is null, both streams are empty, and both times are now.
- If a marker cannot be stored either, those plugins are counted. Then one error line with `job_id` and `count` only (no output), and `last_error` = `spool: results not kept`.
- The job is then finished as before, and the sender is woken.
- The old `last_error` "spool: result not kept" on the first `Put` error is replaced by a Warn line, because the plugins are now reported. `last_error` is set only if the markers fail too.
- Gates: `gofmt`, `go vet` and golangci-lint (Windows and `GOOS=linux`): clean.

For tester-m10:
- A spool whose `Put` fails after 1 of 3 results (for example a tiny `maxBytes` with in-flight items, or a crash hook): the final batch holds result 1 plus two `spool_overflow` markers.
- When even markers fail: no fill items, one log line holding `job_id` and `count`, and `last_error` `spool: results not kept`. A canary grep of the log finds no output.
