# TASK-219 REVIEW: spool overflow (`internal/spool/overflow.go`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-248. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-219-impl.md`: `agent/internal/spool/overflow.go` (new, sha256 `b40f234e…`) and the one-line `Put` call site in `spool.go` (`3e9e668d…`, line 224: `s.fit(j, r, b)` in place of TASK-212's `ErrFull`). Within the shared-file rule (tasks.md "Shared files").

TEST: PASS (`work/reports/TASK-219-test.md`). 29/29 on Windows and 31/31 on WSL with `-race` (the whole spool package), and 5/5 plants red (CHK-M10-364, -365, plus 3 extras).

Spec read: TS §3.3 L226, §6.5 L1184, §4.5 L593; #140; plan TASK-212 §4.

My re-run (Windows): `go test -count=1 ./internal/spool/` ok. `golangci-lint run` gives 0 issues on Windows and with `GOOS=linux`. The hashes match.

## Checks
1. **Oldest first, across jobs (TS §3.3 L226).** `convertOldest` walks jobs in spool order (received time, then id) and items in seq order. It converts full results to `spool_overflow` markers under the same seq, so their place in the order is kept, until the new item fits (plant 364 red).
2. **Every dropped plugin is reported (REQ-248 (2), (3)).** A marker keeps `plugin_uuid`, `started_at` and `finished_at`, with exit null, empty streams and flags false. It passes `proto.NewResult` and strict decoding, and each converted plugin is posted exactly once (plant 365 red).
3. **The #140 order of last resorts.** After conversion, the new item itself becomes a marker. Then the oldest error items not in flight are dropped, each with one log line holding `job_id` and `plugin_uuid` only. `ErrFull` comes only when not even a marker fits. The size never exceeds the bound after a `Put`, and `Size()` equals the disk.
4. **In flight is protected (REQ-248 (4)).** Neither step touches an item in a batch handed out by `Next` (219a red).
5. **Crash safety.** Conversion rewrites through TASK-212's atomic `writeFile`. A crash at any step leaves the whole result. The `n > 0` branch counts a file that was renamed into place even when the directory fsync then failed, which avoids the size drift I noted for `Put` in TASK-212.
6. **No output in logs.** The three log lines carry ids only.

## NOT RUN rows and cover
None for this task.

## Findings
None blocking or should-fix for this task's code.

1. nit, `overflow.go:43`: when the new item is already an error item (a `runner_unavailable` fill from the handler), `fit` turns it into `spool_overflow`, and the manager loses the more specific reason. Both are ERROR (TS §4.5 L593). Consider keeping an error item as it is: it's already marker-sized, so only the drop step applies to it.

## Cross-task point raised to the lead (affects TASK-220 and TASK-223, not this code)
TASK-220's sender keeps a batch handed out by `Next` in flight for its whole back-off during a manager outage (`results.go:96-112`: `Wait`/`Retry` sleep and resend the same batch without settling it). Combined with #140's in-flight protection, the oldest batch (up to 50 items and 1,572,864 bytes) can never be converted or dropped while the manager is down:
- **At the default `spool_max_mb` 50:** that is about 3 % of the spool, and harmless.
- **At `spool_max_mb` 1 or 2 (allowed, #4):** the in-flight batch can be most of the spool. REQ-248 (1)'s "oldest become markers, newest stay whole" is then inverted in the real flow: the oldest stay whole and the newest become markers. Once in-flight items plus manifests leave no room for a single marker, `Put` returns `ErrFull`. The TASK-223 handler then ends the job with its remaining plugins unreported (`compliance.go:74-76`).

TASK-219's tests drive `Put` without a concurrent sender, so they don't show this. Whether "a batch being posted" (#140) covers the back-off between attempts is a reading of #140, not of the spec. I've asked `main` to rule. It will be handled in the TASK-220 and TASK-223 reviews, not here.
