# TASK-004 plan: Go module, golangci-lint config, binary stubs

REQs: REQ-010, REQ-011, REQ-012. Owner: impl-agent. Depends on: none. Needs two approvals (TS §8.2 L1268; PD-3).

## Spec quotes

- TS §8.2 L1265: "**Go:** `gofmt`, `golangci-lint`, no CGO, context-aware cancellation on every job, errors wrapped with `%w`; modules verified with `go.sum`."
- TS §3.1 L158: binaries `/usr/sbin/bitscan-agent`, `/usr/sbin/bitscan-runner`, `/usr/sbin/bitscan-capread`.
- TS §2.2 L111: "Agents initiate every connection, so endpoints need no open inbound port."
- TS §3.7: the runner and capread sockets are systemd socket units (`ListenStream=` in `bitscan-runner.socket` and `bitscan-capread.socket`), so the binaries receive the socket from systemd and never call `net.Listen`.

## Approach

- `agent/go.mod`: module path PD-14 (a); `go` directive at a currently supported release, PD-14 (b) (the user's memory note says 1.22, which is no longer supported: PD-11). No dependencies, so no `go.sum` in M0; `go mod verify` then prints "all modules verified".
- `agent/.golangci.yml` (golangci-lint v2 config format, version pinned in PD-14 (c)):
  - linters: the standard set (`errcheck`, `govet`, `ineffassign`, `staticcheck`, `unused`) plus `errorlint` (wrap with `%w`), `gosec` (G402 catches `InsecureSkipVerify: true`) and `forbidigo`;
  - `forbidigo` with type analysis, forbidding `net.Listen`, `net.ListenTCP`, `net.ListenUDP`, `net.ListenUnix`, `net.ListenUnixgram`, `net.ListenPacket`, `net.ListenIP`, `net.ListenMulticastUDP`, `http.ListenAndServe` and `http.ListenAndServeTLS`, each with a message citing TS §2.2;
  - an exclusion so `forbidigo` does not apply to `_test.go` files (tests may start an `httptest` server as a fake manager);
  - formatters: `gofmt`.
- `agent/cmd/<name>/main.go` for the three binaries: `package main`, a `main()` that writes `<name>: not implemented` to stderr and exits 1. No flags, no config reading, no network, no file access.
- Build (used by TESTs and TASK-010): `CGO_ENABLED=0 GOOS=linux GOARCH=<arch> go build -trimpath -o bin/linux_<arch>/ ./cmd/...` from `agent/` (output path PD-9). `-trimpath` costs nothing now and helps the TS §3.1 reproducible-build check in M6.

## Edge cases

- With `CGO_ENABLED=0`, a file with `import "C"` is silently left out of the build (impl-agent finding, `work/reports/TASK-004-impl.md`):
  - if the package has other Go files, the build **exits 0**;
  - only if it is the package's only file does the build fail ("build constraints exclude all Go files").

  So the build alone does not prove there is no cgo. REQ-010 (3) is checked by the `go list` CgoFiles step in TASK-010, not by the build. This task needs no change for it: the stubs have no cgo files.
- `errcheck` may exclude `fmt.Fprintln` by default; the stub must still be lint-clean.
- Line endings: `.gitattributes` forces LF, but an editor that writes CRLF makes `gofmt -l` list the file. That is the gate working, not a false positive.

## Not in this task

`agent/internal/*` packages (M6), any network, TLS or spool code, `go.sum`.
