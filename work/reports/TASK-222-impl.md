# TASK-222 IMPL: capread helper server (`internal/capread`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-252. Spec: TS §3.7 L277, L437–L484, L493, L500–L501; §8.1 L1244; security invariants (capread lines). Open item applied: #142. Depends on TASK-211 and TASK-217 (both reported). High risk (TS §8.2 second approval).

## Files

- `agent/internal/capread/capread.go` (new, 10 code lines, all platforms): `Socket`, the two-name `commands` table, `Known(name)`.
- `agent/internal/capread/serve_linux.go` (new, 136 code lines, Linux only): request reading, `Serve`, `serveOne`, `run`, the 1 MiB cap.

Request reading and the reply words live in `serve_linux.go`, not `capread.go`. On Windows nothing would use them, so `unused` turns the lint red there. No other file changed.

## Interface

```go
const Socket = "/run/bitscan/capread.sock"
func Known(name string) bool                           // for the client and main (TASK-226)

type Listener interface { Accept() (*net.UnixConn, error); Close() error } // *sdsock.Listener
func Serve(ctx context.Context, l Listener, log *slog.Logger) error        // linux
```

TASK-226's `--serve` does `sdsock.LookupUID("bitscan-runner")` → `sdsock.FromSystemd(uid, log)` → `capread.Serve(ctx, l, log)`. The peer check is sdsock's `Accept` (REQ-235): a peer with any other uid is closed before a byte is read.

## Behaviour (#142)

- **Table:** `nft_ruleset` → `/usr/sbin/nft -j list ruleset`; `audit_rules` → `/usr/sbin/auditctl -l`. These are the only processes the package starts. The argv comes only from the table: no byte of a request reaches `exec`.
- **Request:** exactly one known name and LF, at most 32 bytes, read within 5 s.
  - Anything else answers `error unknown_request` and runs nothing: an unknown name, bytes after the LF, no LF within 32 bytes, or EOF before an LF.
  - A read error or the 5 s deadline closes the connection without an answer.
- **Run:**
  - a missing binary (`os.Stat` ENOENT) gives `error not_installed`;
  - otherwise `exec.CommandContext` with `Env = []string{}`, which is empty, not inherited (a nil `Env` would inherit, CHK-M10-373); `Dir` is `/`; stdin and stderr are `/dev/null`, so stderr is never sent;
  - a 10 s limit (`error timeout`); `WaitDelay` 1 s.
- **Output cap:** stdout is kept up to 1,048,576 bytes. The first byte over cancels the command, and the answer is `error too_large` with **none** of the output (#142 (c)).
- **Exit:** 0 → `ok\n` followed by stdout, then close. Non-zero → `error failed <code>` with no output. A signal death is 128 + the signal number. A start failure that is not "missing" (for example EACCES) → `error failed 126`, the shell's "cannot execute" code.
- **One request at a time:** `Serve` accepts and serves connections one after another, one request each (#142 (d)). Others wait in the socket backlog.
- **Write deadline (an addition, for the reviewer):** 10 s for the reply, so a client that stops reading cannot hold up the next request. The client waits at most 30 s in total (#142 (f)). Without a bound, one stuck client would block the helper.
- **Shutdown:** `ctx` ending closes the listener (`context.AfterFunc`), and `Serve` returns nil.
- **Logs:**
  - `Warn` "request refused" with `result=unknown_request` (the request text is never echoed);
  - `Warn` "request not read; closed";
  - `Info` "request answered" with `command` (the fixed table path) and `result` (the word, or `ok`).
  - Never output or stderr.

## How each acceptance point is met (REQ-252)

| Point | Where |
| --- | --- |
| (1) the two names run their fixed argv with an empty `Env`; `nft_ruleset x`, `NFT_RULESET`, `../nft`, an empty line, 33 bytes and a third name → `error unknown_request`, nothing run | `readRequest` (map lookup of the exact bytes before the LF; nothing after it), `run`'s `cmd.Env = []string{}`. Tests swap the package `commands` table for test commands. |
| (2) peer uid 0, `bitscan` or any other: closed without a reply | `sdsock.Listener.Accept` (TASK-217); `Serve` sees only accepted peers. |
| (3) over 10 s → `error timeout`; over 1 MiB → `error too_large` with nothing sent | `run`: `context.WithTimeout`, then `capped.Write` cancels on the byte past the cap; `serveOne` writes only the error line. |
| (4) two clients at once served one after the other | the sequential accept loop |
| (5), (6) sandbox host rows | VM / G77 (tester) |

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/capread`: nothing.
- `go vet` (Windows) and `GOOS=linux go vet ./internal/capread/`: clean.
- `golangci-lint run ./internal/capread/...` and the `GOOS=linux` run: 0 issues. The G204 and process-start exceptions for `serve_linux.go` come from TASK-211; no nolint.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- Not run: the code is Linux only, and Linux runs are the testers'.

## For the tester (tester-m10, TP-M10-14; Linux: WSL or CI)

- Test seams:
  - the package variable `commands` (swap in test commands, for example a script that sleeps 11 s, or prints 1 MiB + 1 bytes, or prints its environment);
  - `Serve` takes the `Listener` interface. A test can pass an adapter around a `net.UnixListener` (`AcceptUnix`) for rows (1), (3) and (4). Row (2) needs the real `sdsock.Listener` with a child process given fd 3, as in TP-M10-10.
- Mutation rows (S = security; VM rows also need a sandbox host):

| CHK | Plant | Notes |
| --- | --- | --- |
| -371 | add a third name to `commands` | S, VM |
| -372 | pass the request text as an argument (`append(argv, name)`) | S |
| -373 | `cmd.Env = nil` (inherits) | S, VM |
| -374 | `Serve` given a plain listener in `--serve` (TASK-226), or sdsock's uid check removed | S, VM |
| -375 | `runTimeout = 60 * time.Second` | |
| -376 | the cap removed, or `out.buf[:maxOutput]` sent with `ok` on overflow | |
| -377 | `go serveOne(...)` in `Serve` | |
