# TASK-212 IMPL: result spool store (`internal/spool`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-247. Spec: TS §3.3 L222, L224, L226; §3.5 L248; §4.4 L577–L578. Open items applied: #4, #57, #78 (d), #131 (d), #139 (decisions 2026-10-30). Plan: `work/plans/TASK-212.md` §2, §3. High risk (TS §8.2 second approval).

## Files

- `agent/internal/spool/spool.go` (new): `Spool`, `Open`, `StartJob`, `Put`, `Finish`, `Size`, `Next`, `Ack`, `Drop`, `Close`.
- `agent/internal/spool/manifest.go` (new): `Manifest`, `Dropped`, the atomic write, directory fsync, item read and check, and loading a job directory.

No other file changed. No new module. The package imports `internal/agent/wire`, `internal/runner/proto` and the standard library.

**Size: 489 code lines without comments and blank lines (estimate 180).** The cause: the plan's API needs all of the following, and Go writes each error path out:
- the reload path (`Open`: leftover `.tmp` files, unreadable entries, 7-day expiry, the interrupted mark, recounting the size);
- the start / items / final sequencing with the hold rule and the body-size bound;
- in-flight tracking;
- job removal.

Nothing outside plan §2–§3 was added. Two helpers were folded together (`fs.ReadDir` over `os.Root.FS()`) to cut repetition.

## Interface (frozen once W2 passes)

```go
var ErrFull, ErrUnknownJob, ErrJobEnded, ErrUnknownPlugin error

type Manifest struct {
    JobID wire.UUID; ReceivedAt wire.Time; Plugins []wire.UUID  // 1..5000
    StartAcked, Finished, Interrupted, FinalAcked bool
}
type Dropped struct { Job wire.UUID; Items int; Reason string } // "expired" | "unreadable"
type Batch struct { Job wire.UUID; Start bool; Items []proto.Result; Final bool /* + unexported seqs */ }

type Spool struct { Log *slog.Logger /* + unexported */ }
func Open(dir string, maxBytes int64, now func() time.Time) (*Spool, []Dropped, error)
func (s *Spool) StartJob(id wire.UUID, plugins []wire.UUID) error
func (s *Spool) Put(id wire.UUID, r proto.Result) error
func (s *Spool) Finish(id wire.UUID) error
func (s *Spool) Size() int64
func (s *Spool) Next(maxItems, maxBytes int, holdYoung time.Duration) (Batch, bool)
func (s *Spool) Ack(b Batch) error
func (s *Spool) Drop(b Batch) error
func (s *Spool) Close() error
```

- `Spool.Log` is reserved for TASK-219's overflow log lines (plan §4: "logged once with `job_id` and `plugin_uuid`"). TASK-219 may change only the `Put` call site in `spool.go`, so the field is declared here. Nothing reads it yet, and nil means `slog.Default()`.
- Test hook (unexported, like `state.Store.crash`): `s.crash func(file, step string) error`. `file` is the final path inside the spool root (`<job_id>/job.json` or `<job_id>/<seq>.json`). `step` is one of `created`, `written`, `synced` or `renamed`. A non-nil return stops the write there, as a crash would.

## Layout and rules (#139)

- `<dir>/<job_id>/job.json` holds the manifest. `<dir>/<job_id>/<seq>.json` holds one Results item each: `wire.Encode` of the `wire.ResultItem`, `seq` 12 digits zero-padded from 1.
- Files are 0600 (`O_CREATE|O_EXCL` at 0600, then `Chmod` 0600). Directories are 0700: the spool directory is created with `os.Mkdir(dir, 0o700)` if missing, and job directories with `root.Mkdir(id, 0o700)`.
- **Atomic write:** remove a stale `<name>.tmp`, create it `O_EXCL`, write, fsync, close, rename to `<name>`, fsync the directory. `Open` deletes every `*.tmp` unread. On Windows, `syncDir` is a no-op (`runtime.GOOS` check), because Windows cannot fsync a directory and the pure suites also run there. On Linux every directory fsync runs.
- **`os.Root`:** after `os.Lstat` proves `dir` itself is a real directory (a symlinked spool path is refused), every access goes through `os.OpenRoot(dir)`.
  - In the listing, an entry is a job only if it is a real directory (`Type().IsDir()`, so a symlink is never followed) named as a lowercase UUID.
  - An item is loaded only if it is a regular file named exactly `%012d.json`.
  - Anything else is ignored.
- **Size:** the sum of the byte sizes of `job.json` and every item file the index holds. It is kept in memory, updated on every write and removal, and checked against `maxBytes`, where TASK-227 passes `spool_max_mb × 1,048,576`. `Size()` is `spool_bytes`.
- **Order:** jobs by `ReceivedAt`, then `JobID`; items by `seq`.
- **`StartJob`:**
  - lowercases the ids;
  - refuses a duplicate job id and an invalid UUID (through `wire.Encode`'s validation);
  - refuses 0 or more than 5,000 plugins;
  - answers `ErrFull` when the manifest does not fit;
  - creates the job directory, then writes the manifest.
- **`Put`:**
  - takes only a `proto.Result`; a zero `Result{}` fails `wire.Encode` (empty UUID);
  - refuses an unknown job (`ErrUnknownJob`), a finished or interrupted job (`ErrJobEnded`) and a plugin uuid not in the manifest (`ErrUnknownPlugin`, defence in depth for CHK-M10-392);
  - answers `ErrFull` when the item does not fit. TASK-219 replaces that one line (marked) with overflow handling.
- **`Next`:**
  - Per job, in spool order, skipping a job that has a batch in flight:
    1. the start notice while `!StartAcked`;
    2. else up to `maxItems` items while the body `{"results":[…],"final":false}` (28 bytes of frame plus each item's file size plus one comma between items) stays ≤ `maxBytes`, with at least one item always taken;
    3. else, for a finished job with no items left, an empty `Final` batch.
  - The last items batch of a finished job carries `Final: true` itself when it empties the job.
  - **Hold rule (#141):** a *running* job's batch that is not full (fewer than `maxItems`, and not cut by size) is held until its oldest item is `holdYoung` old. Items loaded at `Open` have no put time, and their jobs are never running.
  - An interrupted job never yields a final batch.
  - An item file that no longer decodes or passes `proto.NewResult` at `Next` time is removed, never sent.
- **`Ack` / `Drop`** (the same settlement, plan §2):
  - remove the batch's item files;
  - set `StartAcked` (a dropped notice also ends it, plan §3; a settled items batch implies it);
  - set `FinalAcked` for a final batch;
  - delete the job directory when no items are left and (`FinalAcked` or `Interrupted`).
  - Settling a batch that was not handed out is an error.
- **`Open`:**
  - deletes `.tmp` files;
  - removes an item that fails strict decoding or `proto.NewResult` (`Dropped{Reason: "unreadable"}` with the count);
  - removes a job whose manifest is missing, undecodable or names another id (`Dropped{Reason: "unreadable"}`);
  - drops a job received more than 7 days ago (`now − ReceivedAt > 7 d`, `Dropped{Reason: "expired", Items: n}`);
  - marks every job that is neither finished nor interrupted `Interrupted` and saves it;
  - removes an interrupted or final-acked job with no items left.
  - The caller (TASK-227) logs each `Dropped` and sets `last_error`. Expiry runs at `Open` only, as the plan states; while the agent runs, the manager's own refusal after 7 days drops old batches through the answer classes.

## How each acceptance point is met (REQ-247)

| Point | Where |
| --- | --- |
| (1) put, list in order, ack; size equals the bytes on disk | `Put`, `Next`, `settle`; `s.size` is updated with each file's written length and removed size. Smoke: `Size()` equals the sum of regular files on disk after puts, a reopen and acks, and is 0 when empty. |
| (2) a crash between any two steps leaves no item or a complete one | `writeFile` plus `crash` steps. Only `<name>` is ever read, and it appears only by rename after fsync. `.tmp` files are deleted at `Open`. A crash at `written` on a `Put` left `000000000002.json.tmp`, which reopen removed, with no item and no `Dropped`. |
| (3) after reopen, the same order; a running job is interrupted | `load` sorts and `reopen` marks. Smoke: after reopen, `Put` gives `ErrJobEnded`, the pending item comes out of `Next`, no `Final` follows, and the job is then removed. |
| (4) 7 days + 1 s → dropped | `load`: `> keepFor`. Smoke: `Dropped{…, 1, expired}`, and nothing left on disk. |
| (5) no canary `execute` or pattern in any spool file | `Manifest` holds uuids, times and booleans only. `Put` accepts only `proto.Result` (a Results item). There is no other write path. |
| (6) files 0600, directories 0700 | as above (Linux check: tester). |
| (7) a planted symlink is never written through | `os.Root` refuses escapes. A symlinked spool directory is refused by `Lstat`. Symlinked job directories or items are ignored at `Open`. A symlink named like a `.tmp` or item file is unlinked or replaced by `Remove`/`Rename`, which do not follow it. |

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l .`: lists only `internal/runner/proto/proto_test.go` (the tester's file, not mine). My files are clean.
- `go vet ./internal/spool/`, `GOOS=linux go vet ./internal/spool/`: clean.
- `golangci-lint run ./internal/spool/...` and the `GOOS=linux` run: 0 issues.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- Smoke test (Windows) in a throwaway copy outside the repo, never in the tree. It covered:
  - start notice first;
  - one batch in flight;
  - the 30 s hold;
  - order;
  - reopen → interrupted, item sent, no final;
  - a dropped notice ends it;
  - the size bound cuts one 60 KB item from a 100,000-byte bound;
  - the last items batch is final;
  - finished with nothing → empty final;
  - `ErrFull` with the size never over the bound;
  - 120 items → `[50 50 20 final]`;
  - crash at `written` leaves a `.tmp` that is removed at reopen;
  - expiry.

## For the tester (tester-m10, TP-M10-05)

- Run on Linux for the modes, the directory fsyncs and the symlink rows; the pure rows also run on Windows.
- The crash hook is `s.crash` (package-internal test). Steps and `file` are described above.
- Mutation rows targeting this task (no VM needed):
  - **CHK-M10-356** (the job with `execute` written into the spool): plant by adding `Execute string` to `Manifest` and filling it in `StartJob` (needs a plugin list carrying commands). A canary grep over the spool directory turns it red.
  - **CHK-M10-359** (final for an interrupted job): plant by removing `j.m.Interrupted = true` in `reopen`. The reopened job then stays "running", and once it finishes a final would follow. Also plant `b.Final = all` without `j.m.Finished`.
  - **CHK-M10-366** (a non-atomic write): plant `writeFile` writing straight to `name`. A crash at `written` (with a crash hook that also cuts the data) then leaves a partial `<seq>.json`. `Open` decodes strictly and re-checks through `proto.NewResult`, so a cut JSON object is never sent. What turns red is the reopen: it reports `Dropped{unreadable}` where the atomic build reports nothing, and the item is lost. Also plant "skip the `.tmp` cleanup and read `.tmp` files as items".
- Behaviours to assert that the plan leaves implicit:
  - `Put` of a plugin not in the job → `ErrUnknownPlugin`;
  - `StartJob` with no room → `ErrFull`;
  - a duplicate `StartJob` is refused;
  - `Ack` of a batch not in flight is refused;
  - a second `Next` while a job's batch is out does not return that job again.

## Revision 1 (2026-10-30): `Spool.Release`, a frozen-API delta the lead approved

Ruling: decisions row "#140 reading: in-flight protection covers only an outstanding HTTP attempt". Reviewer-m10's rule 1 applies.

- `spool.go` gets one method; nothing else in the file changes:

  ```go
  func (s *Spool) Release(b Batch) error
  ```

- It hands a batch back unanswered after a failed post attempt. It **only** clears the in-flight mark of the job and of its items, so overflow (TASK-219) may convert those items again.
- It removes no file, sets neither `StartAcked` nor `FinalAcked`, and writes no manifest.
- Releasing a batch that wasn't handed out answers `errNotInFlight`, as `Ack`/`Drop` do.
- The next `Next` builds a fresh batch, which may hold different items (for example markers).
- Gates: `gofmt`, `go vet` and golangci-lint (Windows and `GOOS=linux`), plus the linux/amd64 build: clean.

For tester-m10:
- After `Next` and then `Release`: `Size()` and the files on disk are unchanged, and the manifest bytes are unchanged.
- A second `Next` returns the same job again.
- A full spool's `Put` can now convert the released items.
- A `Release` of a batch never handed out is an error.
