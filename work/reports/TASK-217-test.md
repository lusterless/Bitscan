# TASK-217 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (socket activation and peer check, TS §8.2 second approval). REQ-235 (1), (2), (5), (6); TS §2.2 L111, §3.7 L281–L283, L289–L302, L486–L493; #130 (j). Lead's ruling "TASK-217 fd 3 handling": fd 3 is kept open, and REQ-235 (5) is asserted as written (`/proc/<pid>/fdinfo/3` carries `O_CLOEXEC`), along with "no fd above 2 lacks `O_CLOEXEC`".

Code under test (impl-agent-m10, `work/reports/TASK-217-impl.md`): `agent/internal/sdsock/listen_linux.go` (sha256 `63d1c4e7d2e80ea6…`) and `peer_linux.go` (`1b4e694f2d027e4f…`). Test file (new): `agent/internal/sdsock/sdsock_linux_test.go` (`4ab05c3b8eed1ff0…`). Plan rows: CHK-M10-117 to -122, plus mutation rows CHK-M10-320, -321 and -330 (the G72 halves).

How it runs: the listening socket is passed to a child copy of the test binary as fd 3 (`ExtraFiles`), with `LISTEN_PID` set to the child's own pid by an exec wrapper (`/bin/sh -c 'LISTEN_PID=$$ exec "$0" …'`), as systemd does. Peers with other uids connect through `setpriv --reuid/--regid --clear-groups python3`. The run is as root in WSL.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race, root) | `go test -race -count=1 -v ./internal/sdsock/` | **20/20 passed** (6 tests, 14 subtests), 0 failed, 0 errors, 0 skipped |
| static | `GOOS=linux go vet`, `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/sdsock/` | clean |
| plants | 7 | **7/7 red** |

The first run found a data race in the test harness (reading the child's output buffer while `exec` wrote it); it was fixed with a locked buffer. That was a test bug, not a product one.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-117 | APP | W | `TestPeerCheck/expected_uid_served` | PASS | Expected uid 64999. A client running as 64999:64999 gets `ok`, and the child serves it and exits 0 |
| CHK-M10-118 | APP | W | `TestPeerCheck/root_and_other_uids_refused,_then_the_right_one_served` | PASS | REQ-235 (1). Peers uid 0, uid 64998, and uid 64998 with the **expected uid number as gid** are each closed before any reply (the client's canary write is never answered; it reads EOF). The right peer is served afterwards. stderr has exactly 3 log lines, naming `uid=0`, `uid=64998`, `uid=64998`, and no payload (no canary) |
| CHK-M10-118 | APP | W | `TestPeerCheck/expected_uid_0_serves_root_only` | PASS | Expected uid 0: uid 64999 with gid 0 is refused (CHK-M10-321, the gid is not compared). Root is served |
| CHK-M10-119 | APP | W | `TestFromSystemdRefusals` (11 subtests) | PASS | REQ-235 (2). Each case is refused with its own one-line error naming the check, and nothing accepted. `LISTEN_PID` missing, 1, or the parent's pid; `LISTEN_FDS` 0, 2, or unset; fd 3 a regular file, a datagram Unix socket, a non-listening stream socket, a TCP listener; no fd 3 at all. (Exit 1 for the binaries is TASK-228/226's row) |
| CHK-M10-120 | APP | W | `TestCloexecLinux` | PASS | REQ-235 (5), CHK-M10-330. After `FromSystemd`, `/proc/self/fdinfo/3`, `/4` and `/5` (the socket and two extra inherited files) have `O_CLOEXEC`. A scan of every fd above 2 finds none without `FD_CLOEXEC`. A shell exec'd afterwards has exactly fds `0,1,2` (`ls /proc/$$/fd`) |
| CHK-M10-121 | CODE | W | `TestLookupUID` | PASS | `root` → 0; an unknown user → error. Recorded: `bitscan-runner` → 999 (the WSL system user). The test build is pure Go |
| CHK-M10-122 | CODE | W | `TestNoOtherListenerStatic` | PASS | REQ-235 (6), an AST scan of all non-test agent code. The only `net.FileListener` is in `internal/sdsock/listen_linux.go`. No `net.Listen*`, `syscall.Socket`/`Bind`/`Listen` or `unix.Socket`/`Bind`/`Listen` anywhere. (The G8 half is in TASK-211) |
| CHK-M10-320 | CODE | W | plant: the peer check removed | PASS (red) | `TestPeerCheck` (2 subtests) failed. The VM half (G76) is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-321 | CODE | W | plant: the gid compared instead of the uid | PASS (red) | `TestPeerCheck` (2 subtests) failed |
| CHK-M10-330 | CODE | W | plant: fd 3 left without close-on-exec | PASS (red) | `TestCloexecLinux` failed. VM half NOT RUN |
| extra 217a | CODE | W | plant: no `LISTEN_PID` check | PASS (red) | 3 `LISTEN_PID` subtests failed (served instead of refused) |
| extra 217b | CODE | W | plant: no `LISTEN_FDS` check | PASS (red) | 3 `LISTEN_FDS` subtests failed |
| extra 217c | CODE | W | plant: no `SO_ACCEPTCONN` check | PASS (red) | the non-listening stream socket subtest failed |
| extra 217e | CODE | W | plant: only fd 3 marked close-on-exec | PASS (red) | `TestCloexecLinux` failed (fds 4 and 5 inheritable) |

## Acceptance (TASK-217: "a Unix socket passed as fd 3 to a child test process: REQ-235 (1), (2) and (5) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-235 (1) expected uid accepted; any other (0 included) closed before a byte is read; one log line with the uid only | CHK-M10-117, -118 | PASS |
| REQ-235 (2) bad `LISTEN_*` or fd 3 refused | CHK-M10-119 | PASS |
| REQ-235 (5) fd 3 `O_CLOEXEC`; a plugin sees only 0, 1, 2 | CHK-M10-120 | PASS |
| REQ-235 (6) static | CHK-M10-122 (+ G8, TASK-211) | PASS |
| REQ-235 (3) on a sandbox host (group member closed; non-member EACCES) | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-118 |
| REQ-235 (4) busy | TASK-225 (CHK-M10-164) | — |

No finding.
