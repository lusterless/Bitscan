# TASK-222 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (capread server, TS §8.2 second approval). REQ-252 (1)–(4); TS §3.7 L277, L437–L484, L493, L500–L501; #142. The lead added two rows: (a) a client that never reads its reply is cut off after about 10 s and the next client is served; (b) a missing binary answers `not_installed` and a non-executable one answers `error failed 126`. Plus a plant that removes the write deadline.

Code under test (impl-agent-m10b, `work/reports/TASK-222-impl.md`): `agent/internal/capread/capread.go` (sha256 `09b1683a77054ad8…`) and `serve_linux.go` (`7b55e70f1776b81f…`). Test file (new): `agent/internal/capread/capread_linux_test.go` (`9a18cf104ab55b8f…`). It's an internal package test: the two-name table is swapped for harmless `/bin/sh` scripts and `/usr/bin/env`. Plan rows: CHK-M10-137 to -142, plus mutation rows CHK-M10-371 to -377 (the G74 halves).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race, root) | `go test -race -count=1 -v ./internal/capread/` | **9/9 passed**, 0 failed, 0 errors, 0 skipped |
| L (Windows) | the server is Linux only (`serve_linux.go`); the package's portable `client.go` is TASK-226's | n/a for this task |
| static | `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/capread/` | clean |
| plants | 10 | **10/10 red** |

Two test bugs were fixed before the verdict:
- an environment probe through `/bin/sh` saw the shell's own `PWD`; it now uses `/usr/bin/env` with no shell;
- the peer-check client didn't catch the reset of a refused connection.

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-137 | APP | W | `TestNamesRunFixedArgvEmptyEnv`, `TestRealTableIsTheSpecs` | PASS | REQ-252 (1). `nft_ruleset\n` → `ok\nNFT-OUT\n`: stdout only, the command's stderr is never sent. The command's argv is exactly its table entry (no request text). `audit_rules\n` runs in `/`. **`/usr/bin/env` as the command prints nothing**: the environment is empty (CHK-M10-373). No output or environment value appears in the log. The real table is exactly `nft_ruleset` → `/usr/sbin/nft -j list ruleset` and `audit_rules` → `/usr/sbin/auditctl -l`, and `Known` accepts only those two names. `Socket` = `/run/bitscan/capread.sock` |
| CHK-M10-138 | APP | W | `TestRefusedRequests` | PASS | REQ-252 (1). Each of these answers exactly `error unknown_request` and runs nothing (a marker file is never created): `nft_ruleset x`, `NFT_RULESET`, `../nft`, `/usr/sbin/nft`, an empty line, 33 bytes without LF, 32 bytes + LF, `nft_ruleset` without LF then EOF, `nft_ruleset\r\n`, two names, a third name, a NUL in the name, a leading or trailing space, and an empty request (CHK-M10-371, -372) |
| CHK-M10-139 | APP | W | `TestPeerCheckThroughSdsock` | PASS | REQ-252 (2), through the real `sdsock`. A child copy of the test binary gets the socket as fd 3 with `LISTEN_PID=$$`, expecting uid 64990. Peers uid 0, 64991 and 998 (through `setpriv`) are closed with no reply. Uid 64990 gets `ok\nserved` (CHK-M10-374) |
| CHK-M10-140 | APP | W | `TestOutcomes` | PASS | REQ-252 (3). Exactly 1 MiB of output → `ok` + 1,048,576 bytes. 1 MiB + 1 → exactly `error too_large`, with **none** of the output sent (CHK-M10-376). `exit 3` → `error failed 3`; `kill -9 $$` → `error failed 137`. Lead's (b): a missing binary → `error not_installed`, and a non-executable file → `error failed 126`. `sleep 60` → `error timeout`, answered in 9–12 s (the 10 s spec timeout, wall time; CHK-M10-375). Constants: 10 s, 1 MiB, 32 bytes, 5 s |
| CHK-M10-141 | APP | W | `TestSequential` | PASS | REQ-252 (4): two clients at once. The second command starts after the first ends (timestamps written by the commands) (CHK-M10-377) |
| CHK-M10-142 | APP | W | `TestRequestDeadline` | PASS | A client that connects and sends nothing doesn't hold the helper: the next client is answered within 8 s (the 5 s request deadline), and the idle client gets nothing |
| lead (a) | APP | W | `TestStalledReaderCutOff` | PASS | A client sends `big\n` (1,000,000 bytes of output) and never reads. The next client is served after **9.85 s** (recorded; the bound is 8–15 s) |
| CHK-M10-371 | CODE | W | plant: an unknown name runs a command | PASS (red) | `TestRefusedRequests` failed. The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-372 | CODE | W | plant: the request name added as an argument | PASS (red) | `TestNamesRunFixedArgvEmptyEnv` failed |
| CHK-M10-373 | CODE | W | plant: `cmd.Env = os.Environ()` | PASS (red) | `TestNamesRunFixedArgvEmptyEnv` failed (the env probe printed the environment). VM half NOT RUN |
| CHK-M10-374 | CODE | W | plant: the peer check removed (in `sdsock`) | PASS (red) | `TestPeerCheckThroughSdsock` failed. VM half NOT RUN |
| CHK-M10-375 | CODE | W | plant: timeout 60 s | PASS (red) | `TestOutcomes` failed |
| CHK-M10-376 | CODE | W | plants: (a) the cap removed; (b) the cut output sent as `ok` | PASS (red) | `TestOutcomes` failed for each |
| CHK-M10-377 | CODE | W | plant: requests served concurrently | PASS (red) | `TestSequential` failed |
| lead (a) plant | CODE | W | plant: the write deadline removed (read deadline only, no reply deadline) | PASS (red) | `TestStalledReaderCutOff` failed: the stalled reader held the helper past 25 s |
| extra 222b | CODE | W | plant: no `not_installed` check | PASS (red) | `TestOutcomes` failed |

## Acceptance (TASK-222: "unit with the in-package command table swapped and a Unix socket: REQ-252 (1)–(4) hold")

| REQ-252 | Rows | Verdict |
| --- | --- | --- |
| (1) the two names, fixed argv, empty env; every other request `unknown_request` and nothing run | CHK-M10-137, -138 | PASS |
| (2) peer uid 0, `bitscan` or any other: closed without a reply | CHK-M10-139 (uid 998 stands in for `bitscan`) | PASS |
| (3) 10 s timeout; over 1 MiB → `too_large` with nothing sent | CHK-M10-140 | PASS |
| (4) one at a time | CHK-M10-141, -142, lead (a) | PASS |
| (5), (6) on a sandbox host (real `nft`, `auditctl`, CapEff 0x40001000) | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-137 to -141 |

No finding.
