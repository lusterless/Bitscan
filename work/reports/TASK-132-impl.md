# TASK-132 IMPL: agent lint forbids fcgi.Serve, net.FileConn, net.FilePacketConn

Implementer: impl-agent. Date: 2026-10-26. Round 1. REQ-144. Spec: TS §2.2 (L111 "Pull, not push"), §3.3 (L210 "the agent has no listening port"); security invariants "Never add" (listening port). Source: reviewer TASK-004 round 3 residuals (`work/reviews/TASK-004.md` finding 2; `work/decisions.md` 2026-10-20). Risk: high (agent); TS §8.2 needs two approvals.

## What changed

Only `agent/.golangci.yml`. No other file changed: no Go source, no test, no `go.mod`.

1. New forbidigo rule `^net\.(FileConn|FilePacketConn)$`, `pkg: ^net$`, message "the agent opens or adopts no listening socket; it pulls, never listens (TS §2.2)."
2. New forbidigo rule `^fcgi\.Serve$`, `pkg: ^net/http/fcgi$`, message "the agent opens no listening socket; it pulls, never listens (TS §2.2)."
3. Comment above `net.FileListener` changed from "M6 adds narrow exceptions…" to "M10 adds…". REQ-144 says those exceptions stay with M10, so the old comment was wrong. The rule itself is unchanged.

No existing rule was removed or narrowed. I added nothing to `exclusions`. Both new messages contain the text "no listening socket", so the existing `_test.go` exclusion (`text: no listening socket`) lifts them in test files, exactly as it does the listener rules. `InsecureSkipVerify` is still forbidden in tests (see control C3 below).

I kept the new rules in the existing style: `analyze-types: true` with a `pkg:` regex anchored on the import path, so aliased imports, dot imports and function values are caught. `FileListener` stays a separate rule so that M10 can scope its exceptions to that one rule.

## How to run (Windows, Git Bash, from `agent/`)

```
gofmt -l .                          # prints nothing
GOOS=linux golangci-lint run ./...  # 0 issues (golangci-lint 2.14.0)
golangci-lint run ./...             # 0 issues (Windows GOOS)
grep -rnE --include='*.go' --exclude='*_test.go' '//[[:space:]]*(nolint|go:linkname)' .   # prints nothing
go mod verify                       # all modules verified
```

Baseline before the edit: `gofmt` clean, `GOOS=linux golangci-lint run ./...` gave 0 issues.

## Local plants (throwaway files in `agent/internal/agent/loops/`, all deleted afterwards)

Each command was `GOOS=linux golangci-lint run ./internal/agent/loops/...`.

| Plant | File | Result |
|---|---|---|
| P1 `fcgi.Serve(nil, nil)` | `zz_task132_plant.go` (alone) | red, rc 1: ``use of `fcgi.Serve` forbidden because "the agent opens no listening socket; it pulls, never listens (TS §2.2)." (forbidigo)`` |
| P2 `net.FileConn(os.Stdin)` | `zz_task132_plant.go` (alone) | red, rc 1: ``use of `net.FileConn` forbidden because "the agent opens or adopts no listening socket; it pulls, never listens (TS §2.2)." (forbidigo)`` |
| P3 `net.FilePacketConn(os.Stdin)` | `zz_task132_plant.go` (alone) | red, rc 1: ``use of `net.FilePacketConn` forbidden because "the agent opens or adopts no listening socket; …" (forbidigo)`` |
| V1 aliased imports `fc.Serve`, `n.FilePacketConn`; function value `var _ = n.FileConn` | `zz_task132_plant.go` | 3 forbidigo hits, the same messages |
| V2 dot imports in a Linux-only file: `Serve`, `FileConn`, `FilePacketConn` as values | `zz_task132_plant2_linux.go` | 3 forbidigo hits, the same messages (plus 2 staticcheck ST1001 for the dot imports) |
| C1 control: all three calls in a `_test.go` | `zz_task132_plant_test.go` | 0 issues (lifted by the existing test exclusion) |
| C3 control: the same `_test.go` plus `c.InsecureSkipVerify = true` | `zz_task132_plant_test.go` | red, 1 forbidigo hit on `InsecureSkipVerify` only (the test exclusion is not widened) |

After the plants: no `zz_` files are left, and `git status` shows only `agent/.golangci.yml` changed under `agent/`.

## Notes for the tester and reviewer

- TP-M6-08 / CHK-M6-337, -338, -339: put the plant in a non-test file under `agent/internal/agent/` (I used the `loops` package). Use an exported function, or the `unused` linter adds a second finding.
- G36 (agent security subset) runs in WSL or CI. I did not run it (no WSL for implementers). No Go source changed, so only the lint gate can move.
- Pre-existing observation, not in scope and unchanged: forbidigo does not match the composite-literal key form `&tls.Config{InsecureSkipVerify: true}`. gosec G402 catches that form in both non-test and `_test.go` files (checked with a throwaway plant pair, since deleted). So in a test file, only an explicit `//nolint:gosec // reason` lets the literal form through, and the CI nolint grep covers non-test files only. I noticed this because my first C3 control used the literal form with `//nolint:gosec` and showed 0 issues. For the reviewer to decide whether it needs a follow-up; I did not change it.
- Residuals the lint still cannot close, unchanged from TASK-004: `go:linkname` (covered by the CI grep), and other packages that wrap a listener. These stay with code review.
