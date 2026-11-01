# TASK-219 IMPL: spool overflow (`internal/spool/overflow.go`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-248. Spec: TS §3.3 L226 ("When the spool is full the oldest results are dropped first, and each dropped plugin is reported as ERROR `spool_overflow`"), §6.5 L1184. Open item applied: #140. Plan: `work/plans/TASK-212.md` §4. High risk (TS §8.2 second approval).

## Files

- `agent/internal/spool/overflow.go` (new, 100 code lines): `fit`, `convertOldest`, `dropOldestMarkers` and `log`.
- `agent/internal/spool/spool.go`: **only the `Put` call site.** The 3-line `ErrFull` check became `if r, b, err = s.fit(j, r, b); err != nil { return err }`, as the plan allows. Nothing else in `spool.go` changed.

## Behaviour

`Put` calls `fit(j, r, b)` under the spool lock with the new item's encoding `b`. `fit` works through these steps, stopping as soon as the item fits (`size + len ≤ max`):
1. If it already fits, nothing changes.
2. **`convertOldest`:** walk the jobs in spool order (`ReceivedAt`, then `JobID`) and each job's items by `seq`. Convert every full result (`error` null) that is not in flight into `proto.OverflowMarker`:
   - the marker keeps `plugin_uuid`, `started_at` and `finished_at`, with `exit_code` null, empty streams, both flags false and `error: "spool_overflow"`;
   - it is rewritten atomically under the same `seq`, so its place in the order is kept, and its index entry becomes non-full;
   - a conversion that would not shrink the file is skipped (a full result with empty streams encodes shorter than its marker);
   - an unreadable item is skipped: `Next` drops it and never sends it.
3. If it still doesn't fit, **the new item becomes a marker** (`proto.OverflowMarker(r)`, re-encoded).
4. **`dropOldestMarkers`:** remove the oldest error items not in flight (markers, and `runner_unavailable` items, which are the same size class) until the marker fits. Those plugins then show as not run at the manager (#140). A job left empty that may go (interrupted, or final acked) is removed. A running job never is, and manifests holding items are never dropped.
5. If even the marker doesn't fit (manifests alone fill the spool), `ErrFull`.

The order matches #140's "oldest markers dropped last": converting old results, and making the new item a marker, both keep a report per plugin, so they come before any drop.

**In flight:** items of a batch handed out by `Next` (`entry.flight`) are never converted or dropped until `Ack` or `Drop` (REQ-248 (4)).

**Logs** (Warn, through `Spool.Log`, else `slog.Default()`), one line per event, carrying `job_id` and `plugin_uuid` only and never output:
- "spool full: oldest result replaced by a spool_overflow marker";
- "spool full: new result stored as a spool_overflow marker";
- "spool full: spool_overflow marker dropped".

## How each acceptance point is met (REQ-248)

| Point | Where and evidence |
| --- | --- |
| (1) `spool_max_mb` 1, thirty 64 KiB results, the manager down: total ≤ 1 MiB after every put; the oldest become markers, the newest stay whole | `fit`/`convertOldest`. Smoke: after each of 30 `Put`s, `Size()` ≤ 1,048,576 and equals the bytes on disk. Posting order: `MMMMMMMMMMMMMMMFFFFFFFFFFFFFFF` (15 markers, then the 15 newest whole). |
| (2) each converted result is posted exactly once, as a marker with its own uuid and times | Conversion rewrites under the same `seq`; `Next`/`Ack` hand each `seq` out once. The smoke log names each plugin once. |
| (3) markers validate against `ResultItem` | They are built by `proto.OverflowMarker`, then pass `wire.Encode` (validation) and, on read, `proto.NewResult`. |
| (4) a batch being posted is not converted | `e.flight` skip. Smoke: 5 items in flight, then 10 more 64 KiB puts. The 5 in-flight items came back as full results, and the next 5 were converted (`MMMMMFFFFFFFFFF` after the ack). |
| Size never over the bound after any `Put` | Every path returns either a fitting item or an error with nothing written. Smoke with a 1,500-byte bound: markers dropped oldest first, size stays at 1,325, never over. |

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/spool`: nothing.
- `go vet` and `GOOS=linux go vet ./internal/spool/`: clean.
- `golangci-lint run ./internal/spool/...` and the `GOOS=linux` run: 0 issues.

## For the tester (tester-m10, TP-M10-12)

- **This changes TASK-212's `Put` → `ErrFull` behaviour, as planned.** Any TASK-212 row that expects `ErrFull` from `Put` on a full spool now gets a stored item or a marker. `ErrFull` remains only when not even a marker fits, and from `StartJob` when its manifest does not fit.
- Mutation rows (no VM needed):
  - **CHK-M10-364** (overflow drops the newest first): plant by iterating `s.jobs` and `j.items` in reverse in `convertOldest`. Row (1)'s order flips.
  - **CHK-M10-365** (drop without a marker): plant `convertOldest` removing the item (`removeItems`) instead of rewriting it. Row (2) misses plugins.
  - Also plant "skip the `e.flight` check" for row (4).
- `Spool.Log` can take a test logger to assert the three log lines and their fields, and that no stdout reaches them.
