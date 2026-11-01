# TASK-216 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (runner hygiene, TS §8.2 second approval). REQ-237 (1) and the hygiene half of REQ-237; TS §3 L152, §3.7 L276, L283, §8.1 L1245; #137.

Code under test (impl-agent-m10, `work/reports/TASK-216-impl.md`): `agent/internal/runner/hygiene_linux.go` (sha256 `701fc72157d46ecc…`). Test file (new): `agent/internal/runner/hygiene_linux_test.go` (`ca9d4745b8d3aa9d…`; Linux only, like the code). Plan rows: CHK-M10-110 to -112, plus mutation rows CHK-M10-329, -340, -385 and -386 (the G72 halves).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -run 'TestCheckStartup\|TestSystemProbeLinux\|TestHardenLinux' -v ./internal/runner/` | **18/18 passed** (3 tests, 15 subtests), 0 failed, 0 errors, 0 skipped |
| static | `GOOS=linux go vet`, `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/runner/` | clean |
| plants | 7 | **7/7 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-110 | CODE | W | `TestCheckStartup` (15 subtests) | PASS | REQ-237 (1) with injected probes. Passing set: euid 998, `CapEff`/`CapBnd` 0x4, cgroup2 magic, one `0::` line; `CapEff` 0 also passes (a subset). Each failing input refuses with a one-line message naming its check: euid 0 (CHK-M10-385); `CapBnd` 0x1ffffffffff; `CapEff` with `CAP_SYS_ADMIN` (0x200004, CHK-M10-386 unit part); `CapEff` `CAP_NET_ADMIN` only; `CapBnd` with `CAP_DAC_OVERRIDE`; tmpfs magic 0x01021994 and cgroup v1 magic 0x27e0eb at `/sys/fs/cgroup` (CHK-M10-340); a statfs error; hybrid and v1 `/proc/self/cgroup`. At least 6 distinct messages. With euid 0 and every capability, the euid line wins (that check comes first) |
| CHK-M10-112 | CODE | W | `TestCheckStartup` | PASS | Fail closed: no `CapEff` line, two `CapEff` lines, non-hex `CapEff`, `/proc/self/status` unreadable, `/proc/self/cgroup` unreadable → each refused |
| (extra) | CODE | W | `TestSystemProbeLinux` | PASS | The real probe on WSL as root refuses with "effective uid is 0" (recorded). On this cgroup2 host, with good capabilities injected and a non-root euid, the real statfs and `/proc/self/cgroup` pass |
| CHK-M10-111 | APP | W | `TestHardenLinux` | PASS | In a child process, `Harden()` → `PR_GET_DUMPABLE` = 0. The parent test process is still dumpable (1). REQ-237 (2) on a sandbox host (`/proc/<runner>/mem`, `environ` → EACCES) is NOT RUN (safety-classifier refusal (VM sandbox)); this row is its cover |
| CHK-M10-329 | CODE | W | plant: `PR_SET_DUMPABLE` not set | PASS (red) | `TestHardenLinux` failed (Harden's own post-check also refuses). VM half NOT RUN |
| CHK-M10-340 | CODE | W | plant: the statfs magic check removed | PASS (red) | `TestCheckStartup` failed. The VM half (the u2204 cgroup v1 boot) is NOT RUN |
| CHK-M10-385 | CODE | W | plant: euid 0 accepted | PASS (red) | `TestCheckStartup`, `TestSystemProbeLinux` failed |
| CHK-M10-386 | CODE | W | plant: the capability check made ineffective | PASS (red) | `TestCheckStartup`, `TestSystemProbeLinux` failed. The planted-unit VM half is NOT RUN |
| extra 216a | CODE | W | plant: only `CapEff` checked (`CapBnd` ignored) | PASS (red) | `TestCheckStartup` failed |
| extra 216b | CODE | W | plant: a repeated `CapEff` line accepted | PASS (red) | `TestCheckStartup` failed |
| extra 216c | CODE | W | plant: the `/proc/self/cgroup` parse ignored | PASS (red) | `TestCheckStartup` failed |

## Acceptance (TASK-216: "unit with injected readers: REQ-237 (1) holds; on Linux PR_GET_DUMPABLE returns 0 after Harden()")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-237 (1) each failing input refuses with its own line; the passing set starts | CHK-M10-110, -112 | PASS |
| `PR_GET_DUMPABLE` 0 after `Harden()` | CHK-M10-111 | PASS |
| REQ-237 (2)–(4) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-110, -111 and TASK-228's binary rows |

No finding.
