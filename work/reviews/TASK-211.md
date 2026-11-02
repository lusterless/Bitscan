# TASK-211 REVIEW: lint exceptions and the PD-41 module

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-256 (and REQ-251 (2), REQ-235 (6) through G8). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-211-impl.md`: `agent/.golangci.yml` (+41/−2, sha256 `cc61e7aa…`), `agent/go.mod` (`b2c34773…`) and `agent/go.sum` (`857f9cc9…`, two new lines). It stays within its three files.

TEST: PASS (`work/reports/TASK-211-test.md`). Linux G8 is clean, 18/18 plants are red, 4/4 allowed-spot controls are green, and G9 is red through a cold-cache `go mod download`.

Spec read: TS §2.2 L111, §3.3 L210–L213, §3.7 L281–L283, §8.2 L1265; REQ-256; PD-41 (a); decisions "TASK-211 lint rules accepted as built".

My re-run (Windows, golangci-lint 2.14.0, go1.27.2): `golangci-lint config verify` is ok. `golangci-lint run ./...` gives 0 issues on Windows and with `GOOS=linux`. `go mod verify` prints "all modules verified". The `CGO_ENABLED=0 GOOS=linux` runner build is ok, and the hashes match the test report.

## Checks
1. **No ad-hoc command path (security invariant, TS §3.3 L213).** The whole `os/exec` package is forbidden, types included (`^exec\.` with `analyze-types`), along with `os.StartProcess`, `syscall.ForkExec|Exec|StartProcess` and `unix.Exec`. The lifts are scoped by path and by message text, so lifting one rule never lifts another. Each is anchored to an exact file:
   - G204: `spawn_linux.go` and `capread/serve_linux.go` only;
   - "processes start only in": `inventory/command(_linux)?.go`, `spawn_linux.go`, `capread/serve_linux.go` and `_test.go`;
   - "only the sdsock listener adopts": `sdsock/listen_linux.go` only.

   Near-miss names (`command_extra.go`, `command_windows.go`, `peer_linux.go`) are red, which proves the anchoring.
2. **The lead's question: where does the `command.go` exemption come from?** It's new in M10, because the `os/exec` forbid rule is new. It isn't extra scope: REQ-256's own statement names `internal/inventory/command.go` as one of the three places allowed to start processes. That file is the M4 TASK-094 inventory runner. It calls `exec.CommandContext` (`command.go:100`) with the fixed #35 list only, and its G204-only lift has been in place since M4 (`328b097:.golangci.yml` L77–L80). The only exemption beyond REQ-256's text is `command_linux.go`, as the lead ruled. It names `*exec.Cmd` (`command_linux.go:16-27`) and starts nothing. Keep both.
3. **No listening socket (TS §2.2, §3.3 L210).** Every M4 listener rule is unchanged. `unix.Socket|Bind|Listen` stays forbidden in every non-test file (plant f is red). `net.FileListener` is allowed only in `listen_linux.go`. Its message still contains "no listening socket", so the existing `_test.go` lift covers it in tests only.
4. **PD-41 pin.** `golang.org/x/sys v0.49.0` is a direct require with a comment, and `go.sum` has both lines. `cmd/bitscan-agent` doesn't link the module (only the standard library's vendored `x/sys/cpu`). G9 is red through the cold-cache `go mod download`, the first step in `agent.yml`. The acceptance text says "`go mod verify` fails", but the lead's ruling recorded that `verify` checks the cache, not `go.sum`, so the red step is `download`. I agree that is the meaningful gate.

## NOT RUN rows and cover
None. Every row ran on Linux (W), and plant j' also ran on Windows.

## Findings
None blocking or should-fix.

1. nit, `.golangci.yml:65-79`: a raw system call can still start a process without tripping any rule, for example `unix.Syscall(unix.SYS_EXECVE, …)`, `syscall.RawSyscall(syscall.SYS_CLONE, …)`, or `SYS_FORK`, `SYS_VFORK`, `SYS_CLONE3`, `SYS_EXECVEAT`. There are none in the tree today (I grepped non-test files). TASK-221 needs raw `unix.Syscall` for `ioprio_set`, so `Syscall` itself can't be forbidden. Consider a forbidigo rule `^(unix|syscall)\.SYS_(EXECVE|EXECVEAT|FORK|VFORK|CLONE|CLONE3)$` with the same message and the same lifts. REQ-256 doesn't require it; review covers it until then.
2. nit, PD-41 says the module is used "only by `internal/runner`, `internal/sdsock` and `internal/capread`". Nothing enforces that for other packages, such as `internal/agent/**`, which could import `x/sys/unix` and call, say, `unix.Connect`. REQ-251 (1) checks `cmd/bitscan-agent`'s deps only for runner and redact packages. Consider a `depguard` rule, or adding `golang.org/x/sys/unix` to the TP-M10-19 boundary test for `cmd/bitscan-agent`. Not required.
