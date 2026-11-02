# TASK-226 TEST: PASS

Tester: tester-m10c, 2026-11-01. Full rigor (capread, TS §8.2 second approval). REQ-253 (1), (2), REQ-252 (the helper wiring); TS §3.7 L437–L484; #142 (f), (g). Decisions rows:
- "TASK-226 (capread client and main) accepted as built": main is linux-only; the answer is buffered and printed after a clean end; an error word must match `[a-z0-9_ ]{1,40}`; only the name is forwarded;
- "TASK-222 … additions";
- the TASK-222 approval row, which asks for a helper-unit row in WSL.

Code under test: `agent/internal/capread/client.go` and `agent/cmd/bitscan-capread/main.go` (`work/reports/TASK-226-impl.md`). The server half is TASK-222 (PASS).

Test files (new):
- `agent/internal/capread/client_test.go`: portable, 6 tests (+2 subtests);
- `agent/internal/capread/client_linux_test.go`: the cut-off and refused-socket rows;
- `agent/cmd/bitscan-capread/main_test.go`: linux, builds the binary with `CGO_ENABLED=0` and runs it.

The fake helper listens on a Unix socket in a short temporary directory and records every byte each client sends.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race ./internal/capread/... ./cmd/bitscan-capread/` | **20/20 passed** (TASK-222's 11 included), 0 failed, 0 skipped |
| L (Windows, no -race: there is no C compiler here, and -race needs cgo) | `go test ./internal/capread/ ./cmd/...` | **8/8 passed** (the portable client rows; the linux files don't build here) |
| build | `GOOS=linux go list ./cmd/...` lists `cmd/bitscan-capread`; `GOOS=windows go list ./cmd/...` lists only `cmd/bitscan-agent` (recorded, as built). `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/bitscan-capread` gives an ELF x86-64, statically linked | as expected |
| static | gofmt; vet (linux and windows); `golangci-lint run ./...` on Linux | clean, 0 issues |
| plants | 6 in `client.go` | **6/6 red** |
| WSL helper unit row | `capread_unit.sh` (outside the repo) | see CHK-M10-217w; one half NOT RUN |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-176a | CODE | L, W | `TestClientSendsOnlyTheName` | PASS | Only the request name is sent. The helper received exactly `audit_rules\n`, and after the request line nothing more, for both names |
| CHK-M10-176b | CODE | L, W | `TestClientCopiesOutput` | PASS | A 1 MiB binary answer (every byte value) is printed byte for byte, exit 0, stderr empty. 1 MiB + 1 gives `bitscan-capread: too_large`, exit 1, stdout empty. An empty `ok` answer gives exit 0 |
| CHK-M10-176c | CODE | L, W | `TestClientErrorWords` (23 answers) | PASS | `error timeout` gives exactly the line `bitscan-capread: timeout` on stderr, exit 1. The same holds for `not_installed`, `unknown_request`, `too_large`, `failed 126` and 40×`a`. These are printed as `bad answer` (words outside `[a-z0-9_ ]{1,40}`, and bad first lines):<br>• 41×`a`, an empty word, `Timeout`, `a-b`, `a;b`, a tab, `ESC[2J`, `CR`, `é`;<br>• a bare `error`, `oops`, `OK`, `ok `, an 80-byte first line.<br>No answer, `ok` with no newline, or `error timeout` with no newline gives `no answer`. stdout is empty in every case |
| CHK-M10-176d | CODE | L, W | `TestClientNoAnswerTimeout/{silent,stalls_mid-stream}` | PASS | `clientTimeout` = 30 s (#142 (f)). A silent helper, or one that sends `ok` plus about 64 KiB and then stalls, gives `bitscan-capread: timeout`, exit 1, after 29–35 s, with **nothing printed** |
| CHK-M10-176e (lead's row) | CODE | W | `TestClientCutOffAnswer` (20 rounds) | PASS | An answer cut off mid-stream prints nothing and exits non-zero. The helper sends `ok` plus about 88 KB, then closes with the request unread, so the client's read ends in ECONNRESET after partial data. Every round: exit 1, 0 bytes printed, `bitscan-capread: no answer`. **Recorded:** a helper that closes *cleanly* after partial output can't be told apart from a complete answer: #142 has no length field |
| CHK-M10-176f | CODE | L, W | `TestClientNotEnabled`; `TestClientRefusedSocket` (W) | PASS | REQ-253 (3) at unit level: a missing socket, or a bound socket nobody listens on (ECONNREFUSED), gives `bitscan-capread: not enabled`, exit 1. `Socket` is `/run/bitscan/capread.sock` |
| CHK-M10-177a (lead's row) | CODE | L, W | `TestClientArgsRefusedLocally` (15 argument lists) | PASS | An unknown name is refused locally, before any connection. Each of these exits 2 with the usage line, stdout empty, and the listening fake saw **0 connections**: none, `""`, `nft_ruleset extra`, `audit_rules nft_ruleset`, `/bin/sh`, `NFT_RULESET`, `nft_ruleset\n`, `nft_ruleset `, `--serve`, `--serve x`, `../nft_ruleset`, `/usr/sbin/nft`, `unknown_request`, `nft_ruleset;id` |
| CHK-M10-177b | APP | W | `TestCapreadBinary` (the built static binary) | PASS | These exit 2 with the usage line: no argument, `""`, `nft_ruleset extra`, `/bin/sh`, `audit_rules nft_ruleset`, `--serve x`, `NFT_RULESET`. `--serve` with no `LISTEN_*`, with `LISTEN_PID=1`, or with only `LISTEN_FDS` exits 1 with exactly one stderr line. With no helper, `nft_ruleset` gives `bitscan-capread: not enabled`, exit 1 |
| CHK-M10-217w (TASK-222 approval row; REQ-252 (5), (6) in WSL) | APP | W | `capread_unit.sh` | PASS (nft) / **NOT RUN** (audit, below) | Setup: a transient `systemd-run --unit=m10c-capread` with all 23 `[Service]` directives of `deploy/systemd/bitscan-capread.service` (read from the file, verbatim) and all 5 `[Socket]` directives of `bitscan-capread.socket` as `--socket-property`. **systemd-run accepted every one; none rejected.** ExecStart is `/opt/m10c/bin/bitscan-capread --serve`, the built static binary (the only change). The real units are not installed (0 unit files) and were never enabled.<br>Socket: `root:bitscan-runner 0660` in `/run/bitscan` (`root:root 0755`).<br>A bitscan-runner client (uid 999) running `nft_ruleset` gets exit 0 and 13,432 bytes, **byte-equal to root's `nft -j list ruleset`** (valid JSON, 65 `nftables` entries).<br>Helper process: Uid/Gid 64884 (DynamicUser), **CapInh/CapPrm/CapEff/CapBnd/CapAmb all `0000000040001000`**, NoNewPrivs 1, Seccomp 2.<br>Another uid is refused: `m10c-peer` (uid 997, in group bitscan-runner) and root (uid 0) connect and are closed without a reply (`bitscan-capread: no answer`, exit 1). The journal shows `sdsock: peer refused uid=997` and `uid=0`. `nobody` (not in the group) gets EACCES from the 0660 socket (`not enabled`).<br>The journal has `request answered command=/usr/sbin/nft result=ok` and 0 lines with ruleset text. After the stop, the socket file is removed |
| CHK-M10-217w audit half | APP | W | same | **NOT RUN** (not possible in WSL) | `auditctl -l` fails for **root itself** in this WSL distro: exit 255, "Error sending rule list data request (Operation not permitted)". The WSL kernel refuses audit netlink requests from the distro, which runs outside the initial PID namespace. So real `auditctl -l` output can't be shown here. Recorded: through the helper, a bitscan-runner client gets `bitscan-capread: failed 255`, the same exit status root gets, and nothing on stdout. Setup note: `auditctl` was installed from the Ubuntu archive's `auditd` package (binary only, no daemon) plus `libauparse0`. Cover: TASK-222's rows with a swapped table (fixed argv, empty env, `failed <code>`) and the VM row (held) |
| plant "print as it streams" (lead's row) | CODE | W | `io.Copy(stdout, …)` in place of the buffered read | PASS (red) | `TestClientCutOffAnswer`: "88000 bytes printed"; `TestClientCopiesOutput`: 1 MiB + 1 printed |
| plant: error word unchecked | CODE | W | `wordRe` skipped | PASS (red) | `TestClientErrorWords`: 41×`a` printed as a word |
| plant: unknown names connect | CODE | W | the `Known` check removed | PASS (red) | `TestClientArgsRefusedLocally`: `""`, `/bin/sh`, `NFT_RULESET` and others connected and printed `X` |
| plant: more than the name sent | CODE | W | the socket path appended to the request | PASS (red) | "request bytes \"audit_rules /tmp/cr…/c.sock\\n\"" |
| plant: timeout 60 s | CODE | W | `clientTimeout = 60 * time.Second` | PASS (red) | `TestClientNoAnswerTimeout` refuses the constant (30 s, #142 (f)) |
| plant: 1 MiB cap removed | CODE | W | `too_large` branch dropped | PASS (red) | 1 MiB + 1 printed, exit 0 |

## Acceptance (TASK-226: "unit with a fake server and the built binary run by hand: REQ-253 (1), (2) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-253 (1): name only, output copied, exit codes, the error line | CHK-M10-176a–f | PASS |
| REQ-253 (2): other argument lists exit 2 without connecting | CHK-M10-177a, b | PASS |
| `--serve` wiring through sdsock and TASK-222 | CHK-M10-177b, CHK-M10-217w | PASS |
| REQ-252 (5), (6) with real `nft`, CapEff 0x40001000, other uids refused | CHK-M10-217w | PASS for nft in WSL; audit NOT RUN in WSL (kernel refuses audit netlink to the distro); VM row NOT RUN (VM hold, the named gate exception) |
