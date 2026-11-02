# TASK-217 IMPL: systemd socket activation and peer check (`internal/sdsock`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-235. Spec: TS §2.2 L111, §3.7 L281–L283, L289–L302, L486–L493; security invariants "Never add". Open item applied: #130 (j). Plan: `work/plans/TASK-209.md` §5. Depends on TASK-211 (reported). Shared by the runner (TASK-225/228) and capread (TASK-222/226, impl-agent-m10b).

## Files

- `agent/internal/sdsock/listen_linux.go` (new, 118 lines, 84 code lines): package doc, `Listener`, `FromSystemd`, `Close`, `cloexecInherited`, `checkListening`.
- `agent/internal/sdsock/peer_linux.go` (new, 69 lines, 52 code lines): `Accept`, `peerUID`, `LookupUID`.

136 code lines against an estimate of 130. No other file changed. The package is Linux only. On Windows, `go build ./...` and `go vet ./...` skip it without error (checked).

## Interface

```go
type Listener struct{ /* *net.UnixListener, fd 3 *os.File, expected uid, logger */ }
func FromSystemd(expectUID uint32, log *slog.Logger) (*Listener, error)
func (l *Listener) Accept() (*net.UnixConn, error)   // only peers with expectUID
func (l *Listener) Close() error
func LookupUID(name string) (uint32, error)
```

`Close` is added to plan §5's listing: the serve loop closes the listener to stop `Accept` at shutdown.

## How each acceptance point is met

| REQ-235 | Where |
| --- | --- |
| Close-on-exec first (description; (5)) | `FromSystemd` first scans `/proc/self/fd` and sets `FD_CLOEXEC` on **every** descriptor above 2, fd 3 included (`F_GETFD`, then `F_SETFD` with the flag added), before any other check. The directory's own descriptor is closed when the scan ends; its `EBADF` is skipped. |
| (2) start-up refusals | `LISTEN_PID` missing, not a number, or not `os.Getpid()`; `LISTEN_FDS` not exactly `"1"`; fd 3 not a socket (`fstat` type); `SO_DOMAIN` ≠ `AF_UNIX`; `SO_TYPE` ≠ `SOCK_STREAM` (a datagram socket); `SO_ACCEPTCONN` ≠ 1 (not listening). Each gives one fixed-word error, which `main` logs as one line before exit 1 (TASK-228). |
| Adoption | `os.NewFile(3)` then `net.FileListener` (the only call, in this file, as the TASK-211 lint requires). Go dups the fd with `O_CLOEXEC`. `LISTEN_FDNAMES` is ignored, and the environment is not cleared (plugins get a fresh environment, REQ-239). |
| (1) peer uid | `Accept` loops on `AcceptUnix`, reads `SO_PEERCRED` through `SyscallConn().Control`, and returns only a connection whose `Uid == expectUID`. Every other peer, uid 0 included, and one with no readable credentials, is closed **before any byte is read**, with one `Warn` line holding only the uid. It compares the uid, never the gid (CHK-M10-321). |
| (5) fd 3 carries `O_CLOEXEC` | **Deviation from plan §5, which closes the original fd 3:** fd 3 is kept open. It is marked close-on-exec by the scan and held by the `Listener`, so the `os.File` finaliser can't close it. Then `/proc/<pid>/fdinfo/3` exists and shows `O_CLOEXEC`, as REQ-235 (5) reads, and no descriptor above 2 lacks the flag (plan §5's unit assertion). The runner holds two descriptors for one socket, both close-on-exec. Closing fd 3 as the plan says would make REQ-235 (5)'s `fdinfo/3` check either fail or read an unrelated file. I took the REQ's wording; tell me if the lead prefers the plan's. |
| (6) static | No `net.Listen*`, `syscall.Socket/Bind/Listen` or `unix.Socket/Bind/Listen`. `net.FileListener` appears only in `listen_linux.go`. |
| `LookupUID` | `os/user.Lookup`. With `CGO_ENABLED=0` it parses `/etc/passwd` in pure Go. The uid is parsed as 32-bit. |
| (3), (4) | Sandbox host rows; `busy` is the serve loop (TASK-225). |

No agent-side peer check is added (#130 (j)).

## Gates (from `agent/`)

- `gofmt -l .` on non-test files: nothing.
- `go build ./...` and `go vet ./...` on Windows: OK (package skipped).
- `GOOS=linux go vet ./internal/sdsock/` and `GOOS=linux golangci-lint run ./internal/sdsock/...`: clean.
- `golangci-lint run ./...` on Windows: 0 issues in non-test files.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- A scratch test (`FromSystemd` refuses without `LISTEN_PID`) compiled for linux in a throwaway copy, and was not run (Linux runs are the testers').

## For the tester (tester-m10, TP-M10-10)

Linux only. Use a child test process started with a Unix socket as fd 3: `ExtraFiles`, plus `LISTEN_PID` set in the child. The TASK-211 lint lifts the exec rule in `_test.go`.

| CHK | Plant | Notes |
| --- | --- | --- |
| -320 | `Accept` returns every connection (drop the uid compare) | S, VM |
| -321 | Compare `cred.Gid` | S |
| -330 | Skip `cloexecInherited` (fd 3 has no `O_CLOEXEC` in `fdinfo`) | S, VM |

Extra rows worth planting:
- `checkListening` without the `SO_ACCEPTCONN` row: a bound, non-listening socket as fd 3 is accepted.
- `LISTEN_FDS` `"2"` accepted.
- The peer is closed after a read rather than before. A test can assert that a refused peer's write still sits unread (the server read nothing) by checking that the client gets EOF or a reset with no reply.
