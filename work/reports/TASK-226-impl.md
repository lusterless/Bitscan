# TASK-226 IMPL: capread client and `bitscan-capread` main

Implementer: impl-agent-m10b, 2026-10-30. REQ-253, REQ-252 (the `--serve` wiring). Spec: TS §3.7 L437–L484, L493, L501. Open item applied: #142 (f), (g). Depends on TASK-222 (reported). High risk (TS §8.2 second approval).

## Files

- `agent/internal/capread/client.go` (new, 72 code lines, all platforms): `Client`.
- `agent/cmd/bitscan-capread/main.go` (replaces the M0 stub, 37 code lines; `//go:build linux`).

No other file changed.

**Why `main.go` is Linux only:** it imports `internal/sdsock`, which has only `_linux.go` files. A Windows build of the command would fail on "build constraints exclude all Go files". With the tag, `go build ./...` and `go vet ./...` on Windows skip the command, as they already skip `sdsock`. The shipped build is `GOOS=linux` (REQ-010).

## Interface

```go
// package capread
func Client(args []string, socket string, stdout, stderr io.Writer) int // exit code
```

`main`:
- `os.Args[1:]` exactly `["--serve"]` → `serve()`;
- anything else → `capread.Client(args, capread.Socket, os.Stdout, os.Stderr)`.

## Behaviour (REQ-253, #142 (f), (g))

**Client:**
- **Arguments:** anything other than exactly one of `nft_ruleset` or `audit_rules` writes `bitscan-capread: usage: bitscan-capread nft_ruleset|audit_rules` to stderr and returns **2 without connecting**. That covers no argument, two arguments, `/bin/sh`, `NFT_RULESET`, and `--serve` reaching `Client`.
- **Connect:** `unix` to `/run/bitscan/capread.sock`, 30 s limit. Any dial error (no socket because the helper isn't enabled, refused, permission) → `bitscan-capread: not enabled`, exit 1.
- **Request:** only the name and LF. One 30 s deadline covers the whole exchange.
- **Answer:**
  - First line, at most 64 bytes.
  - `ok` → read the rest to EOF, at most 1 MiB, then write it to stdout **only after a clean end**, exit 0. A partial answer is never printed.
  - `error <word>` → `bitscan-capread: <word>`, exit 1. The word must match `^[a-z0-9_ ]{1,40}$` before it is printed; anything else is `bad answer`, so no control bytes from the socket reach the plugin's stderr.
  - Any other first line, or one over 64 bytes → `bad answer`.
  - The deadline passing → `timeout`. The connection ending early → `no answer`. More than 1 MiB → `too_large`. All exit 1.

**`--serve`:**
1. `sdsock.LookupUID("bitscan-runner")`: pure Go, `/etc/passwd`, no CGO.
2. `sdsock.FromSystemd(uid, log)`: the `LISTEN_*` checks, close-on-exec, peer check per connection (REQ-235).
3. `capread.Serve(ctx, l, log)` until SIGTERM or SIGINT, then exit 0.

A start-up refusal (unknown user, no or bad `LISTEN_*`) is one error line and exit 1 (#142 (g)). Logs are `slog` text on stderr (journald), as `bitscan-agent` does. The `reason` is sdsock's fixed-word error text.

## Smoke run (Windows, throwaway copy outside the repo, fake helper on AF_UNIX)

| Args, helper reply | Exit, stderr, stdout; what the helper received |
| --- | --- |
| `nft_ruleset`, `ok\n{"nftables":[]}\n` | 0; stdout `{"nftables":[]}\n`; sent `nft_ruleset\n` |
| `audit_rules`, `error not_installed\n` | 1; `bitscan-capread: not_installed` |
| `audit_rules`, `error BAD\x1b[31m\n` | 1; `bitscan-capread: bad answer` |
| `audit_rules`, `okay\n` | 1; `bad answer` |
| `audit_rules`, closed without a reply | 1; `no answer` |
| `nft_ruleset x`; `/bin/sh`; no argument; `--serve` given to `Client` | 2; usage line; **nothing sent** (the fake helper saw no request) |
| no socket file | 1; `bitscan-capread: not enabled` |

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/capread cmd`: nothing.
- `go build ./...` (Windows, the command skipped), `go vet`, and `GOOS=linux go vet ./internal/capread/ ./cmd/bitscan-capread/`: clean.
- `golangci-lint run --tests=false ./...` and the `GOOS=linux` run: 0 issues.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/bitscan-capread`: OK (5.8 MB). It is no longer the M0 stub: there is no `not implemented` line (REQ-255 (3)).

## For the tester (tester-m10, TP-M10-14 and the built binary)

- `Client` is pure Go: rows (1) and (2) of REQ-253 run against a fake helper on Windows and Linux.
- Built-binary rows (Linux):
  - `bitscan-capread`, `bitscan-capread nft_ruleset extra` and `bitscan-capread /bin/sh` exit 2 and connect nowhere. An `strace -f -e connect` or a listener at a test socket path shows no connection.
  - `bitscan-capread --serve` without `LISTEN_FDS` logs one line and exits 1.
- The 30 s `timeout` row needs a fake helper that accepts and never answers (real time: 30 s).
- **REQ-253 (3)** (helper disabled, a plugin gets exit 1 and the fixed line) is a sandbox-host row.
- No mutation row targets this task beyond CHK-M10-374, which fails if `--serve` serves a plain listener instead of `sdsock.FromSystemd`.
