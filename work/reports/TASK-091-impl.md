# TASK-091 IMPL: dpkg watcher

REQ-102. TS §3.4 (L239), §8.1 (L1257); #80 (agreed 2026-10-24); plan `work/plans/TASK-104.md`, section "Watcher"; lead ruling 2026-10-24 (an inotify queue overflow counts as a change). **Two approvals (TS §8.2, agent).**

No tests were run (that is the tester's job). The debounce was checked in a throwaway copy outside the tree with a fake clock and a fake watch; it is deleted. inotify itself needs Linux and was not run here.

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/inventory/watch.go` (about 80 non-comment lines, all platforms) | The constants `DpkgDir`, `Quiet` (60 s) and `HoldOff` (10 min 30 s); the `dirWatch` seam and its `openWatch` default ("not available"); `Watcher`, `NewWatcher(dir, clock)`, `Run(ctx, out)` and the debounce. |
| `agent/internal/inventory/watch_linux.go` (about 60) | `init` sets `openWatch` to the inotify implementation: `InotifyInit1(IN_CLOEXEC\|IN_NONBLOCK)`, `InotifyAddWatch(dir, IN_MOVED_TO\|IN_CLOSE_WRITE)`, event parsing with `encoding/binary` (no `unsafe`). Standard-library `syscall` only. |

The inventory package's other files (`osinfo`, `command`, `dpkg`, `body`) belong to impl-agent-2 (TASK-094 and TASK-095) and are untouched.

## Behaviour

- **`Run(ctx, out chan<- struct{})`** sets the watch on `dir` and returns its error at once if the watch cannot be set (a missing directory, the inotify limit, or a non-Linux build). The caller logs it, and scheduled inventory is unaffected (REQ-102 (4)). Otherwise `Run` blocks until `ctx` is done (it returns `ctx.Err()`) or the watch fails (a wrapped error).
- **Events:** only the name `status` with `IN_MOVED_TO` or `IN_CLOSE_WRITE` counts. Other names in the directory count for nothing (REQ-102 (5)). `IN_Q_OVERFLOW` counts as a change (lead ruling). `IN_IGNORED` (the watch removed, for example the directory deleted) ends `Run` with an error. One read batch with any relevant event is one change, and changes the debouncer has not yet taken are merged.
- **Debounce (#80):**
  1. Each change restarts a 60 s quiet period.
  2. When the quiet period ends, `Run` signals if 10 min 30 s have passed since the previous signal, otherwise as soon as they have.
  3. A change during the quiet period or the hold-off is kept, so the latest state is always signalled once.
  4. The time of the previous signal is taken after the send completes, so two signals are always at least `HoldOff` apart.
  5. The first signal after start-up has no hold-off.
- **Sending:** `Run` sends each signal with a blocking `select` against `ctx`, so no signal is dropped. While the receiver is busy, new changes wait in the merged channel (and, past that, in the kernel queue; an overflow there is again a change).
- **Shutdown:** `Close` on the non-blocking inotify file, which sits in Go's poller, unblocks the reader goroutine when `Run` returns. No goroutine is left blocked.
- **Clock:** only the injected `schedule.Clock`. Both the path and the clock are injectable: `NewWatcher(t.TempDir(), fake)`.

## Scratch run (evidence, not a test)

The fake clock was advanced in 1 s steps, with a fake `dirWatch` standing in for inotify.

- One change at t = 0 gives a signal at 60 s.
- Then 50 changes, one every 12 s from t = 120 s (the last at 708 s), give exactly one signal at 768 s: the quiet period ends at 768 s, after the hold-off (60 s + 10 min 30 s = 690 s). Nothing else was signalled within 30 minutes.
- Cancelling the context returns `context canceled`.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l internal/inventory`: prints nothing.
- `go vet ./internal/inventory` on windows, and with `CGO_ENABLED=0 GOOS=linux GOARCH=amd64`: clean.
- `go build ./...` for linux/amd64: clean.
- `GOOS=linux golangci-lint run ./internal/inventory/...`: `0 issues`.

## For the tester (TP-M4-06, `watch_linux_test.go`)

- Use a temporary directory and the real inotify path through `NewWatcher(dir, fakeClock)`.
  - Planting `status` by rename (write `status.new`, then `os.Rename` it onto `status`) gives `IN_MOVED_TO`.
  - Writing and closing `status` gives `IN_CLOSE_WRITE`.
  - Writing another name gives nothing.
- A fake clock needs `Now` and `After(d)`, and `After` must handle `d <= 0` by firing at once.
- Events arrive asynchronously from the kernel, so wait briefly for the debouncer to take each event before advancing the fake clock.
- A failed watch: `NewWatcher(filepath.Join(dir, "missing"), clk).Run(ctx, out)` returns an error at once.

## Revision 1 (TEST FAIL r1: `TestWatchSetFailuresReturnError/regular_file_instead_of_directory`, CHK-M4-064)

Cause: `inotify_add_watch` accepts a regular file. A file watch never names `status` in its events, so the watcher ran and never signalled, and nothing was logged.

Fix, in `agent/internal/inventory/watch_linux.go` only: the watch mask now includes `IN_ONLYDIR`. The kernel answers `ENOTDIR` for anything but a directory, in the same call, so there is no stat-then-watch gap. `openInotify` then returns `inventory: watch <dir>: not a directory`, which reaches the caller exactly like the existing ENOENT and EACCES errors. Events and debounce are unchanged.

Gates (Windows, Git Bash, from `agent/`): `gofmt -l` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/inventory/` clean; `GOOS=linux golangci-lint run ./internal/inventory/...` 0 issues.

For the tester: re-run only `TestWatchSetFailuresReturnError`. Your observations (a) (`last` in memory only, across restarts) and (b) (`IN_MOVE_SELF`) are not changed here; (a) is with main.
