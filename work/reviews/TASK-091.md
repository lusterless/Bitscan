# TASK-091 REVIEW: dpkg watcher

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/inventory/watch.go` and `agent/internal/inventory/watch_linux.go`, revision 1 (`IN_ONLYDIR`), per `work/reports/TASK-091-impl.md`. Sources: TS §3.4 L239, REQ-102, #80 (agreed 2026-10-24), and the lead ruling that a queue overflow counts as a change.

TEST: FAIL in round 1 on CHK-M4-064 (a regular file was accepted as the watch target). After r1, PASS from tester-m4b: the re-run by name is 4/4; the set is 46/47 plus 1 named skip, which passes 1/1 as `bstester`; the `-race` run gives the same; 16/16 plants are red. When I wrote this, the tester's verdict had come by message, and main had not yet written `work/reports/TASK-091-test.md`.

## Checks
1. Spec:
   - The watch is on the directory, with `IN_MOVED_TO|IN_CLOSE_WRITE`, and only the name `status` counts (L239, REQ-102 (1) and (5)).
   - The debounce fires at `max(last change + 60 s, previous signal + 10 min 30 s)`, which is #80 exactly. A change during the quiet period, the hold-off or a blocked send is merged into one pending signal, never dropped (REQ-102 (2)).
   - `last` is taken after the send completes, so two signals are always at least `HoldOff` apart in one process (REQ-102 (3)).
   - When the watch cannot be set (missing path, a file because of `IN_ONLYDIR`, EACCES, the inotify limit, a non-Linux build), `Run` returns an error at once for the caller to log. Nothing in the scheduled inventory depends on the watcher (REQ-102 (4)).
2. Security invariants:
   - No listening socket and no network.
   - Only the standard library's `syscall`: no `x/sys/unix`, no `unsafe`, and events are parsed with `encoding/binary`.
   - There is no configuration input, so the watcher cannot be turned off (G2).
   - Error text holds only the fixed path and errno, with no file content.
3. Scope: 2 new files, about 140 lines, inside the task's area. golangci-lint has no exclusions for them.
4. Tests: the rename and close-write paths run against real inotify on a fake clock. They cover the storm from idle and after a signal, a change during the hold-off, a slow receiver, a timeline against a model, other names and masks, set failures (including the r1 file case), a directory removed after start (`IN_IGNORED` ends `Run`), cancellation with no leaked goroutine, and hostile event bytes with no panic. They can fail: 16/16 plants are red.
5. Re-run by the reviewer (Windows, gates only; the tests are Linux-only):
   - `gofmt -l agent`: prints nothing.
   - `GOOS=linux go vet ./internal/inventory/`: clean.
   - `GOOS=linux golangci-lint run ./internal/inventory/...`: 0 issues.
6. Correctness:
   - `Close` on the non-blocking fd in Go's poller unblocks the reader goroutine. `failed` has a buffer of 1, so the goroutine exits even after `Run` has returned.
   - A truncated or oversized length field ends the scan (`end > len(b)`) without a panic.
   - A negative `After` duration fires at once on the real clock.

## Findings
1. nit (spec-silent; tester-m4b raised it with main), `watch.go:80`. `last` lives in memory only. After an agent restart, the first signal has no hold-off, so a restart within 10 minutes of the last unscheduled upload can send another. The manager still enforces its limit (TS §3.4 L239: 429), and REQ-101 (4) has TASK-104 retry that 429 with back-off. So the 10-minute rule holds on the wire, but REQ-102 (3) holds only within one process. No change, unless the user wants `last` persisted in the state directory. If they do, it is a TASK-104 or TASK-088 follow-up, not this task.
2. nit, `watch_linux.go:28`. `IN_MOVE_SELF` is not watched. A deleted `/var/lib/dpkg` ends `Run` through `IN_IGNORED` (tested), but a renamed one would leave the watch silently on the moved directory. dpkg never renames that directory, and the scheduled inventory still runs, so I accept it as is. Optionally, add `IN_MOVE_SELF` and treat it like `IN_IGNORED`.
