# TASK-091 TEST: dpkg watcher (inotify, #80 debounce)

**Verdict: PASS** (round 2, after revision 1). Round 1 failed on one subtest of CHK-M4-064, a regular file at the watch path; the record is kept below. Revision 1 adds `IN_ONLYDIR` to the watch mask. The failing test re-run by name passes 4/4. The whole watcher set, re-run because the fix touched code all its tests share, passes 46/47 with 1 named skip (it runs as bstester, 1/1), and the same under `-race`. Mutation plants: 16/16 red (round 1).

REQ-102; TS §3.4 L239; #80; lead ruling 2026-10-24 (overflow counts as a change). Tester: tester-m4b. Full rigor (agent). Test file (new): `agent/internal/inventory/watch_linux_test.go`, which uses real inotify on temporary directories, a fake clock that records every After deadline, and readiness and mask read from /proc/self/fdinfo.

## Commands
- W root: `go test -count=1 -v -run Watch ./internal/inventory/` → 44/47 passed, 2 failed (1 leaf + its parent), 0 errors, 1 named skip. The same with `-race` (CGO on): 44/47, no race.
- W-u (bstester): `-test.run TestWatchPermissionDeniedReturnsError` → 1/1 passed.
- gofmt -l and go vet clean. L: `GOOS=linux golangci-lint run ./internal/inventory/...` → 0 issues.
- Plants in throwaway copies: 16/16 red, after the control.
- Round 2 (r1): `-run '^TestWatchSetFailuresReturnError$'` → 4/4 passed; `-run Watch` → 46/47 (1 named skip), and the same with `-race`; bstester 1/1; lint 0 issues (rows CHK-M4-064-r1, CHK-M4-060..067-r1).

## Acceptance criteria
- A rename onto status and a close after a write each signal once after the #80 delay: PASS ([CHK-M4-060](../../tests/m4/report.md), [-061](../../tests/m4/report.md)).
- 50 changes in 10 minutes signal once, plus once after the hold-off; signals are never closer than 10 min 30 s: PASS (CHK-M4-062, including the model timeline).
- Other file names signal nothing: PASS (CHK-M4-063).
- A failed watch returns an error the caller can log: **FAIL** in round 1 (CHK-M4-064), PASS in round 2 (CHK-M4-064-r1). Missing directory, inotify limit, EACCES and a removed directory pass; a regular file at the path failed in round 1.
- Also PASS: cancel without leaks (CHK-M4-065), injected path and clock (-066), overflow counts as a change (-067).

## Failure (round 1)
- Test: `TestWatchSetFailuresReturnError/regular_file_instead_of_directory`.
- Expected: Run returns an error at once (CHK-M4-064 lists "a file instead of a directory").
- Actual: Run does not return within 1 s.
- Diagnosis: `InotifyAddWatch(fd, dir, IN_MOVED_TO|IN_CLOSE_WRITE)` succeeds on a regular file. Events on a file watch carry no name, so the watcher never signals and nothing is logged. Fix: add `IN_ONLYDIR` (ENOTDIR), or Stat the path first. Owner: impl-agent.

## Observations (not defects of this task)
- The hold-off is in memory only, so it is not kept across a restart (the manager answers 429; TASK-104 backs off). Asked to main.
- IN_MOVE_SELF is not handled (a renamed directory would be followed silently); not expected for /var/lib/dpkg.
