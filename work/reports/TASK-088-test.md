# TASK-088 TEST: state directory
**Verdict: PASS.** REQ-093; TP-M4-03, CHK-M4-030 to -038; mutation rows CHK-M4-333, -334, -340. Full rigour (agent).
Commands: `go test ./internal/agent/state/` as root and as bstester, `CGO_ENABLED=1 go test -race -run '^TestConcurrent'`, `tester3_m4_plants.py t088` (bstester).
Counts: root 47/47 (earlier rows); bstester 45/47, with one test bug of mine (umask 0777 set before the test made its directory) fixed and re-run (1/1, then 5/5 as bstester and as root); new TestConcurrentSameFileWrites 1/1; -race 2/2. Plants: 19 of 22 red, including all three security rows; 3 survivors with reasons (fsync is unobservable without strace; O_EXCL is equivalent behind os.Root and remove-first; prune-on-load is not observable).

| Criterion | Evidence |
| --- | --- |
| REQ-093 (1) modes 0600/0644/0600/0600 whatever the umask, owner = running user | CHK-M4-030 PASS (bstester uid); CHK-M4-340 red; mode-from-umask red |
| (2) atomic write, a crash at any step gives old or new complete state | CHK-M4-031 PASS; write-in-place, stale-.tmp, times-before-token and unbound-times plants red |
| (3) no symlink or path leads outside | CHK-M4-032, -036 PASS; read-outside-os.Root plant red |
| (4) enroll.token delete after the state write; absent is not an error | CHK-M4-033 PASS; plant red |
| (5) seen ids persisted 7 days, survive restart, corrupt file refuses start-up (fail closed) | CHK-M4-034, -035 PASS; CHK-M4-333 (both forms), -334, fail-open, forgotten-on-failure, first-seen and Has-ignores-age plants red |
| concurrency | CHK-M4-037 PASS with -race; no-lock plant red after the new test |
| no token in errors | CHK-M4-038 PASS; both plants red |

For the reviewer: fsync of the file and the directory is not provable by the unit suite; please check it by reading (or allow installing strace in WSL for a syscall trace).
