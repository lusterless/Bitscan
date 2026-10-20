# TASK-004 IMPL report: Go module, golangci-lint config, three binary stubs

REQs: REQ-010, REQ-011, REQ-012. Spec: TS §2.1, §2.2 (pull, not push), §3.1 (binary names), §3.7 (sockets from systemd units), §8.2 (gofmt, golangci-lint, no CGO, `%w`). Needs two approvals (TS §8.2; PD-3).

## Files (all new, LF, 5 files, about 70 lines)

- `agent/go.mod`: `module bitscan.local/agent` (PD-14 (a)), `go 1.27.2` (PD-14 (b), installed toolchain). No dependencies, so no `go.sum`.
- `agent/.golangci.yml`: golangci-lint v2 format (`version: "2"`), for golangci-lint 2.14.0 (PD-14 (c)).
  - `linters.default: standard` (errcheck, govet, ineffassign, staticcheck, unused) plus `errorlint` (`errorf: true`), `gosec` and `forbidigo`.
  - `forbidigo` with `analyze-types: true`, so import aliases and method calls are caught. With this setting forbidigo matches a method as `pkg.Type.Method`, with no pointer marker. Messages cite TS §2.2 / §3.7. It forbids:
    - `net.{Listen, ListenTCP, ListenUDP, ListenUnix, ListenUnixgram, ListenPacket, ListenIP, ListenMulticastUDP}` and the methods `net.ListenConfig.{Listen, ListenPacket}` (pkg `^net$`);
    - `http.{ListenAndServe, ListenAndServeTLS, Serve, ServeTLS}` and the methods `http.Server.{ListenAndServe, ListenAndServeTLS, Serve, ServeTLS}` (pkg `^net/http$`);
    - everything in `net/http/httptest` (pattern `^httptest\.`), for example `NewServer`, `NewTLSServer`, `NewUnstartedServer`;
    - `syscall.Listen` (pkg `^syscall$`).
  - Exclusion: `forbidigo` only, for paths matching `_test\.go$`.
  - Formatter: `gofmt`.
- `agent/cmd/bitscan-agent/main.go`, `agent/cmd/bitscan-runner/main.go`, `agent/cmd/bitscan-capread/main.go`: write `<name>: not implemented` to stderr and exit 1. They take no flags, read no config, open no file and use no network or socket.

## How to run (Git Bash; prefix the brief's PATH line)

From `agent/`:
```
gofmt -l .                       # run from the repo root as: gofmt -l agent
go mod verify
golangci-lint run ./...
for a in amd64 arm64; do CGO_ENABLED=0 GOOS=linux GOARCH=$a go build -trimpath -o bin/linux_$a/ ./cmd/...; done
for f in bin/linux_*/*; do go version -m "$f"; done
```

## Results on the Windows dev box (2026-10-20)

| Check | Result |
| --- | --- |
| `gofmt -l agent` | prints nothing |
| `go mod verify` | `all modules verified`, exit 0 |
| `go vet ./...`, `golangci-lint config verify` | exit 0 |
| `golangci-lint run ./...` | `0 issues.`, exit 0 |
| `CGO_ENABLED=0` linux/amd64 and linux/arm64 builds of `./cmd/...` | exit 0, 6 binaries |
| `go version -m` on all 6 | `CGO_ENABLED=0`, `GOOS=linux`, matching `GOARCH`, path `bitscan.local/agent/cmd/<name>`, `go1.27.2` |
| Run the ELF stubs; `file` says statically linked | NOT RUN: no Linux, Docker or WSL on this machine. Runs in CI (TASK-010) |

Plants were made in a `mktemp -d` copy (go.mod, .golangci.yml, cmd/, plus `internal/p/`) and then deleted. Each one went into a non-test file unless noted:

| Plant | lint exit | Reported by |
| --- | --- | --- |
| `net.Listen("tcp", ":1")` | 1 | gosec G102, and forbidigo (seen with `--enable-only forbidigo` on `127.0.0.1:1`) |
| `n2.ListenTCP` (aliased `net` import), `net.ListenUDP`, `net.ListenUnix`, `net.ListenPacket` | 1 | forbidigo |
| `http.ListenAndServe`, `http.ListenAndServeTLS` | 1 | gosec G114, and forbidigo (both seen with `--enable-only forbidigo`) |
| `&tls.Config{InsecureSkipVerify: true}` | 1 | gosec G402 |
| `os.Remove("x")` with the error ignored | 1 | errcheck |
| `fmt.Errorf("read: %v", err)` | 1 | errorlint |
| gofmt-clean `_test.go` calling `net.Listen`, `httptest.NewServer`, referencing `http.ListenAndServe` | 0 (`0 issues.`) | none (forbidigo excluded) |
| unformatted `.go` file | `gofmt -l agent` lists it | gofmt |

### Round 2 (TEST FAIL CHK-M0-076; scope ruled by `main`)

`.golangci.yml` gained the method, `httptest` and `syscall` patterns above (now 43 lines). The clean tree still gives `0 issues.`, `go mod verify` still passes and both builds still succeed.

One gofmt-clean non-test file holds all 12 forms: `lc.Listen` on a `net.ListenConfig` var, `(&net.ListenConfig{}).ListenPacket`, `s.ListenAndServe`, `s.ListenAndServeTLS`, `s.Serve`, `s.ServeTLS` on `&http.Server{Addr, ReadHeaderTimeout}`, `http.Serve`, `http.ServeTLS`, `httptest.NewServer`, `httptest.NewTLSServer`, `httptest.NewUnstartedServer` (aliased import), `syscall.Listen`. Results:
- `--enable-only forbidigo` exits 1 with 12 forbidigo issues, one per line.
- A full lint exits 1, both with the default GOOS and with `GOOS=linux`.

The same file renamed to `_test.go` gives no forbidigo issue (`--enable-only forbidigo` exits 0). In that file gosec G114 still flags the package-level `http.Serve` and `http.ServeTLS` calls. gosec is not excluded for tests (G402 ruling), so a green `_test.go` control must not call `http.Serve`/`http.ServeTLS`. `httptest`, `net.Listen` and `http.Server` methods in tests stay green.

The round-1 plants were re-run against the new config and all still exit 1: `net.Listen` and `http.ListenAndServe` (forbidigo-only), aliased `ListenTCP` (forbidigo), `InsecureSkipVerify` (gosec), ignored error (errcheck), `%v` wrap (errorlint).

Not covered, because they are outside the stdlib list `main` ruled on: `golang.org/x/sys/unix.Listen` and raw `syscall.Bind`/`syscall.Socket`. Both were closed in round 3.

### Round 3 (REVIEW CHANGES_REQUESTED, `work/reviews/TASK-004.md` findings 1 to 3, plus `main`'s additions)

`.golangci.yml` changes (now 67 lines; still 5 files):
- `linters.exclusions.generated: disable`, which `golangci-lint config verify` accepts on 2.14.0. A `// Code generated ... DO NOT EDIT.` header no longer hides a file (finding 1).
- forbidigo also forbids the types `http.Server` and `net.ListenConfig`, so embedding them or calling through an interface is caught (finding 2).
- forbidigo forbids the field `tls.Config.InsecureSkipVerify` (pkg `^crypto/tls$`), so a field assignment after construction is caught. gosec G402 still catches the literal form (finding 3).
- `main` additions: `syscall.{Socket,Bind}` (added to the `syscall.Listen` pattern), `unix.{Listen,Socket,Bind}` (pkg `^golang\.org/x/sys/unix$`), `net.FileListener`, all citing TS §2.2. Also `nolintlint` with `require-specific` and `require-explanation`.
- The `_test.go` exclusion is now scoped: path `_test\.go$`, linter `forbidigo`, `text: no listening socket`. Every listener message contains that phrase, so listener rules stay lifted in tests. The `InsecureSkipVerify` message does not, so the field rule still applies in tests, as `main` ruled for G402.

Proofs (throwaway `mktemp -d` copies, deleted afterwards; plants gofmt-clean):

| Plant | Exit | Reported by |
| --- | --- | --- |
| clean tree, default GOOS and `GOOS=linux` | 0, `0 issues.` | none |
| `// Code generated by hand. DO NOT EDIT.` + `net.Listen` | 1 | forbidigo |
| `type S struct{ http.Server }; s.ListenAndServe()` | 1 | forbidigo |
| `type L interface{ ListenAndServe() error }; var l L = &http.Server{...}` | 1 | forbidigo |
| `type C struct{ net.ListenConfig }; c.Listen(...)` | 1 | forbidigo |
| `c.InsecureSkipVerify = true` in a non-test file / in `_test.go` | 1 / 1 | forbidigo / forbidigo |
| `&tls.Config{InsecureSkipVerify: true}` in `_test.go` | 1 | gosec G402 |
| `syscall.Socket` + `syscall.Bind` (SOCK_DGRAM) | 1 | forbidigo (2 issues) |
| `net.FileListener(os.NewFile(3, "s"))` | 1 | forbidigo |
| `unix.Socket`, `unix.Bind`, `unix.Listen` (copy with `go get golang.org/x/sys@v0.49.0`, GOOS=linux) | 1 | forbidigo (3 issues) |
| `syscall.Socket`/`Bind` and `net.FileListener` in `_test.go` | 0 | none |
| `//nolint` / `//nolint:all // x` / `//nolint:forbidigo` (no explanation) on a `net.Listen` line | 1 / 1 / 1 | nolintlint |
| `//nolint:forbidigo // x` on a `net.Listen` line | 0 | none (residual, see below) |
| `http.Client` with `http.Transport` and `tls.Config{MinVersion: TLS12}` | 0 | none |
| round-2 12-form file / same as `_test.go` (forbidigo-only) | 1 (14 issues: the type references add 2 lines) / 0 | forbidigo |
| round 1 again: aliased `ListenTCP`, literal `InsecureSkipVerify`, ignored error, `%v` wrap | 1 each | forbidigo, gosec, errcheck, errorlint |

Also re-checked: `gofmt -l` is empty, `go mod verify` passes and both `CGO_ENABLED=0` linux builds succeed.

What remains (not closable in `.golangci.yml`):
- A specific, explained `//nolint:forbidigo // reason` still suppresses. TASK-010 adds a CI grep for `nolint` in non-test files (the planner is adding it); otherwise review catches it.
- `//go:linkname` to a forbidden function, and `net/http/fcgi.Serve` (serves on stdin): not forbidden (reviewer finding 6).
- `net.FileConn` / `net.FilePacketConn` are not forbidden; `main` ruled on `FileListener` only.
- Linux-only files are linted only with `GOOS=linux`; CI must lint on Linux (reviewer finding 5, TASK-010).

**Note for the M6 breakdown:** the runner and capread receive their sockets from systemd (TS §3.7) and will need `net.FileListener` (and probably `x/sys/unix` for `SO_PEERCRED`). Each needs a narrow exclusion scoped by path to `agent/cmd/bitscan-runner/`, `agent/internal/runner/`, `agent/cmd/bitscan-capread/` and `agent/internal/capread/`, and only for the specific pattern. That change needs two approvals (TS §8.2). `bitscan-agent` packages keep every listener rule.

## For the tester

1. golangci-lint keeps one issue per line by default. When gosec and forbidigo both flag the same line (`net.Listen` on all interfaces, `http.ListenAndServe`), only gosec is printed. To prove forbidigo itself fires, use `--enable-only forbidigo` or bind to `127.0.0.1`. The exit code is non-zero either way.
2. Make plants gofmt-clean. Otherwise the gofmt formatter makes lint exit non-zero, and the REQ-012 (4) "test file passes" check gives a false FAIL. My first `_test.go` plant hit this.
3. As the plan says, only `forbidigo` is excluded for `_test.go`. `InsecureSkipVerify: true` in a `_test.go` file is still reported by gosec G402. I read REQ-012 (4) "the same calls" as items (1) and (2), which are calls, and not item (3), which is a struct field. **Decided by `main` (2026-10-20):** keep it strict, with no G402 exclusion for `_test.go`. A future TLS test that needs a self-signed certificate must use a test CA through `ca_file`, not `InsecureSkipVerify`.
4. REQ-010 (3) / plan edge case: a planted `import "C"` file fails the `CGO_ENABLED=0` build only when it is the only file in a package that `./cmd/...` imports ("build constraints exclude all Go files", exit 1). If it sits next to other files, for example `cmd/bitscan-agent/c.go`, Go silently drops it and the build exits 0. A package made only of that file and not imported is skipped by `./...` ("matched no packages"). The binaries still contain no cgo code. The plan's "Either way the build exits non-zero" is wrong for the side-by-side case. **Decided by `main` (2026-10-20):** this task's files do not change. The planner rewords REQ-010 (3), and TASK-010 adds a CI `go list` CgoFiles check that fails when the list is non-empty. For this task, test REQ-010 (3) only with the case where the `import "C"` file is the only file in a package that `./cmd/...` imports.
5. `agent/bin/` is gitignored (`.gitignore:22`). I deleted my build output, so rebuild before running `go version -m`.
