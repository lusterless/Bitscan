# TASK-211 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (lint and dependency rules, TS §8.2 second approval). REQ-256, plus REQ-251 (2) and REQ-235 (6) through G8. TS §2.2 L111, §3.3, §3.7, §8.2 L1265; PD-41 (a). The lead's notes (decisions row "TASK-211 lint rules accepted as built"): the G9 plant uses a cold module cache; the `os/exec` exemption covers `internal/inventory/command_linux.go` and nothing else; `syscall.StartProcess` and `unix.Exec` each need a red plant.

Code under test (impl-agent-m10b, `work/reports/TASK-211-impl.md`): `agent/.golangci.yml` (sha256 `cc61e7aade335898…`), `agent/go.mod` (`b2c347739ad6d07d…`), `agent/go.sum` (`857f9cc9c0a345d8…`). There is no test file in the tree: the evidence is these runs (TP-M10-04). Plan rows: TP-M10-04, CHK-M10-300 to -304, CHK-M10-378, -379.

## Runs

All runs are on W (WSL Ubuntu 24.04, `/root/bstest-m10-base`, go1.27.2 linux/amd64). golangci-lint v2.14.0 linux/amd64 was installed at `/root/go-m10/bin` from the GitHub release, and its `sha256sum -c` against the release's `checksums.txt` was OK. The flags were `golangci-lint run --uniq-by-line=false --max-same-issues=0 --max-issues-per-linter=0 ./...` from `agent/`. Each plant ran in its own `/root/bstest-m10-mut-<id>`, which was removed afterwards.

| Run | Count |
| --- | --- |
| G8 on the unmodified tree (Linux) | 0 issues, exit 0 |
| Red plants | **18/18 red**, each with the planted file's own finding (the forbidigo message named below) |
| Green controls (allowed spots) | **4/4 green** (exit 0) |
| G9 | clean cold cache: `go mod download` 0, `go mod verify` "all modules verified". Altered `go.sum` with a cold cache: `go mod download` **exit 1** "verifying golang.org/x/sys@v0.49.0: checksum mismatch" |
| G7, G10, G11 | `gofmt -l .` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...` gives three ELF 64-bit statically linked binaries; the CI nolint grep has 0 hits |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command / plant | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-301 | CODE | W | G8 on the TASK-211 tree | PASS | 0 issues, exit 0 (Linux, authoritative) |
| CHK-M10-379 | CODE | W | `exec.Command("/bin/sh","-c",s).Run()` in `internal/agent/loops/compliance.go` | PASS (red) | forbidigo "processes start only in …" on `exec.Command` and `.Run`, plus G204 |
| CHK-M10-378 | CODE | W | `net.FileListener` in `internal/runner/serve.go` | PASS (red) | forbidigo "only the sdsock listener adopts the systemd socket" |
| TP-M10-04 a | CODE | W | `os.StartProcess` in `internal/redact/plant.go` | PASS (red) | forbidigo `os.StartProcess` |
| TP-M10-04 b | CODE | W | `syscall.ForkExec` in `internal/runner/job.go` | PASS (red) | forbidigo `syscall.ForkExec` |
| TP-M10-04 c | CODE | W | `syscall.Exec` in `cmd/bitscan-agent/main.go` | PASS (red) | forbidigo `syscall.Exec` |
| TP-M10-04 d | CODE | W | type-only `*exec.Cmd` parameter in `internal/spool/plant.go` | PASS (red) | forbidigo `exec.Cmd` |
| TP-M10-04 e | CODE | W | `net.Listen("unix", …)` in `internal/runner/plant_listen.go` | PASS (red) | forbidigo `net.Listen` |
| TP-M10-04 f | CODE | W | `unix.Socket` in `internal/sdsock/peer_linux.go` | PASS (red) | forbidigo `unix.Socket` (REQ-235 (6)) |
| TP-M10-04 g | CODE | W | `syscall.StartProcess` in `internal/agent/loops/plant.go` (lead's note 3) | PASS (red) | forbidigo `syscall.StartProcess` |
| TP-M10-04 h | CODE | W | `unix.Exec` in `internal/capread/client.go` (lead's note 3) | PASS (red) | forbidigo `unix.Exec` |
| TP-M10-04 i | CODE | W | `os/exec` in `internal/inventory/plant.go` (lead's note 2) | PASS (red) | forbidigo `exec.Command` |
| TP-M10-04 j | CODE | W | `os/exec` in `internal/inventory/command_extra.go` (lead's note 2: a name close to the exempt one) | PASS (red) | forbidigo `exec.Command` |
| TP-M10-04 j' | CODE | L | `os/exec` in `internal/inventory/command_windows.go`, Windows golangci-lint (on Linux the file is not built) | PASS (red) | 2 forbidigo findings, exit 1 |
| TP-M10-04 k | CODE | W | `net.FileListener` in `internal/sdsock/peer_linux.go` | PASS (red) | only `listen_linux.go` is exempt |
| TP-M10-04 l | CODE | W | `exec.Command(s)` in `internal/runner/plant_g204.go` | PASS (red) | forbidigo `exec.Command`, `exec.Cmd` |
| TP-M10-04 q | CODE | W | `exec.Command(s)` in `internal/runner/job.go` (G204 exemption is spawn-only) | PASS (red) | forbidigo |
| TP-M10-04 r | CODE | W | a bare `// nolint` in `internal/runner/checks_extra.go` | PASS (red) | nolintlint (unused, no specific linter, no explanation) |
| CHK-M10-304 | CODE | W | G11 grep (`agent.yml` step) on the tree; plant `//nolint:unused // planted` in `internal/runner/plant_nl.go` | PASS | tree 0 hits; plant 1 hit (red) |
| control m | CODE | W | `net.FileListener` in `internal/sdsock/listen_linux.go` | PASS (green) | exit 0 |
| control n | CODE | W | `exec.Command("/bin/sh","-c",execute)` in `internal/runner/spawn_linux.go` | PASS (green) | exit 0 (neither forbidigo nor G204) |
| control o | CODE | W | `exec.Command(path, args...)` in `internal/capread/serve_linux.go` | PASS (green) | exit 0 |
| control p | CODE | W | `*exec.Cmd` in `internal/inventory/command_linux.go` | PASS (green) | exit 0 (the M4 exemption the lead accepted) |
| CHK-M10-302 | CODE | W | G9: cold `GOMODCACHE`, one character changed in the `golang.org/x/sys v0.49.0 h1:` line | PASS (red) | `go mod download` exit 1 "checksum mismatch"; clean cold run exit 0. Recorded: `go mod verify` stays green on a warm or cold cache once the module is present (it checks the cache, not `go.sum`), so the red step is `go mod download`, which `agent.yml` runs first |
| CHK-M10-300 | CODE | W | G7 `gofmt -l .` | PASS | nothing printed |
| CHK-M10-303 | CODE | W | G10 `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...` | PASS | `bitscan-agent`, `bitscan-runner`, `bitscan-capread`: ELF 64-bit LSB executable, statically linked. (The `import "C"` plant runs at the gate on the runner code) |
| PD-41 | CODE | W | `go.mod`, `go.sum`, `go list -deps` | PASS | `golang.org/x/sys v0.49.0` is a direct require with the PD-41 comment; 2 `go.sum` lines; the only module importer so far is `internal/runner`; `go list -deps ./cmd/bitscan-agent` holds only the standard library's `vendor/golang.org/x/sys/cpu`, not the module |

## Acceptance (TASK-211: "On Linux G8 and G9 are green, each REQ-256 (1) plant in a throwaway copy turns G8 red, and `go mod verify` fails on an altered `go.sum` line")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| G8 green on Linux | CHK-M10-301 | PASS |
| REQ-256 (1): each forbidden call planted elsewhere turns G8 red (including `exec.Command` in `compliance.go` and `net.FileListener` in `internal/runner/serve.go`) | CHK-M10-378, -379, TP-M10-04 a–l, q, r | PASS (18/18 red, 4/4 controls green) |
| REQ-256 (2): no `//nolint` in non-test agent code | CHK-M10-304 | PASS |
| REQ-256 (3) / G9: altered `go.sum` fails | CHK-M10-302 (cold cache, per the lead's note) | PASS |
| PD-41 pinned | PD-41 row | PASS |

## Notes (no finding)

1. As the lead ruled, the exemption reaches past REQ-256's literal list to `internal/inventory/command_linux.go`, and the exempt pattern is exact (`command(_linux)?\.go`): `command_extra.go` and `command_windows.go` are both red.
2. `_test.go` files may use `os/exec` and listeners (exclusion rules). That is needed for the oracles and the fd-3 child process tests.
