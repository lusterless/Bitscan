# TASK-211 IMPL: lint exceptions and the PD-41 module

Implementer: impl-agent-m10b, 2026-10-30. REQ-256 (and REQ-251 (2) through G8). Spec: TS §2.2 L111, §3.3, §3.7, §8.2 L1265. PD-41 (a). High risk (TS §8.2 second approval, PD-43).

## Files

- `agent/.golangci.yml`: +41 / −2.
- `agent/go.mod`: `golang.org/x/sys v0.49.0` as a direct requirement, with a PD-41 comment.
- `agent/go.sum`: two new lines (`golang.org/x/sys v0.49.0 h1:XbzkgYJH…` and its `/go.mod` hash). No other line changed.

No file outside the task list changed.

## What changed

### Module (PD-41 (a))

- `golang.org/x/sys v0.49.0` (the latest release on the proxy, 2026-10-06; its `go.mod` asks for `go 1.26.0`, below our `go 1.27.2`), added with `go get golang.org/x/sys@v0.49.0`. It is a direct `require` with a comment naming its only users (`internal/runner`, `internal/sdsock`, `internal/capread`).
- Nothing imports it yet. Until TASK-215/216/217 import it, `go mod tidy` would remove the line. No CI step runs `tidy`, and an unused requirement doesn't break `go build`, `go vet`, `go mod verify` or the lint. The first runner-side importer keeps it as is.

### Lint (REQ-256)

New forbidigo rules (type-aware, so aliases and method values are caught). All four share one message: "processes start only in the inventory command runner, runner spawn_linux.go and capread serve_linux.go (REQ-256, TS §3.3)."

| Pattern | pkg | Catches |
| --- | --- | --- |
| `^exec\.` | `^os/exec$` | the whole `os/exec` package: `exec.Command`, `CommandContext`, `exec.Cmd` (type and methods), `exec.ExitError`, `LookPath` and the rest |
| `^os\.StartProcess$` | `^os$` | `os.StartProcess` |
| `^syscall\.(ForkExec\|Exec\|StartProcess)$` | `^syscall$` | REQ-256's two, plus `syscall.StartProcess` (the same call under another name) |
| `^unix\.Exec$` | `^golang\.org/x/sys/unix$` | the PD-41 module's `execve` wrapper (otherwise a way round the rule) |

The `net.FileListener` rule keeps its pattern. Its message now reads "…; only the sdsock listener adopts the systemd socket (TS §2.2, §3.7).", and it still contains "no listening socket", so the existing `_test.go` lift still covers it.

New exclusion rules, each scoped to one linter and one message or rule id:

1. gosec `G204` only in `^internal/(runner/spawn|capread/serve)_linux\.go$`. The existing `internal/inventory/command.go` rule is unchanged.
2. forbidigo "processes start only in" lifted in `^internal/(inventory/command(_linux)?|runner/spawn_linux|capread/serve_linux)\.go$`.
3. forbidigo "processes start only in" lifted in `_test\.go$`. The existing M4 tests run `exec.Command` as oracles (`dpkg_test.go`, `osinfo_test.go`), and TP-M10-10 needs a child process given fd 3.
4. forbidigo "only the sdsock listener adopts" lifted in `^internal/sdsock/listen_linux\.go$` only.

Every other rule stays as written: the listeners, `unix.Socket`/`Bind`/`Listen`, `FileConn`/`FilePacketConn`, `fcgi.Serve`, `InsecureSkipVerify`, and the nolint and linkname grep (the CI step, unchanged).

### Two places where the build goes past REQ-256's literal text (for the reviewer)

- **`internal/inventory/command_linux.go` is also exempted from the exec rule.** It is the Linux half of the TASK-094 inventory command runner. It names `*exec.Cmd` (sets `SysProcAttr` and `Cancel`, kills the process group) but starts nothing. Without the exemption, G8 goes red on the unchanged M4 tree, and that file isn't mine to change. The process start itself (`exec.CommandContext`) stays in `command.go`, which REQ-256 names.
- **`syscall.StartProcess` and `unix.Exec` are also forbidden**, beside REQ-256's `syscall.ForkExec`/`Exec`. Without them, both are an unlisted way to start a process.

### For the runner side (impl-agent-m10)

- Outside `spawn_linux.go`, no `os/exec` identifier may appear, types included: no `*exec.Cmd` or `*exec.ExitError` in `capture.go`, `result.go` or `job.go`. Hand `*os.Process`, `*os.ProcessState` or `syscall.WaitStatus` across file boundaries instead.
- `net.FileListener` is allowed in `internal/sdsock/listen_linux.go` only.

## Gates run (from `agent/`, Windows dev box, golangci-lint 2.14.0, go 1.27.2)

| Command | Result |
| --- | --- |
| `gofmt -l .` | nothing |
| `golangci-lint config verify` | ok |
| `golangci-lint run ./...` | 0 issues |
| `GOOS=linux golangci-lint run ./...` | 0 issues |
| `go vet ./...`, `GOOS=linux go vet ./...` | ok |
| `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...` | ok |
| `go mod verify` | all modules verified |

Note: impl-agent-m10's in-progress `internal/runner/proto` showed transient findings (unused, G115) during one run while that file was being edited. A re-run a minute later was 0 issues on both GOOS. They aren't from this task.

## Plants I ran (throwaway copy under `$TMP`, removed afterwards), all with `GOOS=linux`

Run with `--uniq-by-line=false --max-same-issues=0`. Without these flags, golangci-lint shows one issue per line, so a forbidigo finding can hide behind a G204 or `unused` finding on the same line. Exit 1 either way.

| Plant | Result |
| --- | --- |
| `exec.Command("/bin/sh","-c",s).Run()` in `internal/agent/loops/compliance_plant.go` | red: forbidigo `exec.Command`, `exec.Command(...).Run`, and G204 |
| `func f(c *exec.Cmd)` (type only) in the same file | red: forbidigo `exec.Cmd` |
| `os.StartProcess`; `syscall.ForkExec`; `syscall.Exec` there | red, one finding each |
| `net.FileListener` in `internal/runner/serve_plant_linux.go` | red |
| `unix.Exec` in the same file | red |
| `net.FileListener` in `internal/sdsock/peer_linux.go` | red (only `listen_linux.go` is exempt) |
| `net.FileListener` in `internal/sdsock/listen_linux.go` | green |
| `exec.Command("/bin/sh","-c",execute).Start()` in `internal/runner/spawn_linux.go` | green (no forbidigo, no G204) |
| `exec.Command(path, args...).Run()` in `internal/capread/serve_linux.go` | green |
| Existing M4 tests with `exec.Command` | green (real tree, 0 issues) |

### `go.sum` plant (G9), a fact the tester should know

With one character changed in the `golang.org/x/sys v0.49.0 h1:` line:
- `go mod verify` with a **warm** module cache prints "all modules verified" and exits 0. It checks the cache against its own hashes, not against `go.sum`.
- `go mod download` with a **cold** cache (a fresh `GOMODCACHE`, which is what `agent.yml` does with `cache: false`) exits 1 with `SECURITY ERROR … checksum mismatch`.
- With the clean `go.sum`, cold `go mod download` exits 0 and `go mod verify` prints "all modules verified".

So the red step for REQ-256 (3) is the CI's `go mod download` with a cold cache, the step `agent.yml` already places first for this reason. `go mod verify` on a warm cache can't show it.

## For the tester (tester-m10)

- TP-M10-04: re-run the plants above on Linux, the authoritative G8 run, and add `exec.Command` in `internal/agent/loops/compliance.go` as REQ-256 (1) names it. Make the `go.sum` plant against a cold `GOMODCACHE`.
- No VM is needed for this task.
