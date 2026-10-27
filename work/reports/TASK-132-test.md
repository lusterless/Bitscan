# TASK-132 TEST: agent lint forbids fcgi.Serve, net.FileConn, net.FilePacketConn

**Verdict: PASS** (round 1). Tester: tester-m6, 2026-10-26. Risk: high (agent), so full rigor: every plant, plus variants, controls, G8 and G36. Written by `main` from the tester's text (the harness blocks the tester on report files).

REQ-144; TS §2.2 L111, §3.3 L210; security invariants "Never add" (listening port). Impl report: `work/reports/TASK-132-impl.md`. Rows: `tests/m6/report.md` CHK-M6-140 to -145 and CHK-M6-337 to -339.

## Commands

All runs in WSL2 Ubuntu 24.04 with go1.27.2 and golangci-lint 2.14.0 (the CI pin), `GOOS=linux GOARCH=amd64 CGO_ENABLED=0`. Each plant went into its own fresh copy of `agent/` under `/root/m6t/t132/<id>`. The tree was never touched.

- `golangci-lint run ./...`, `gofmt -l .`, the CI nolint/linkname grep and `go mod verify`, on an unmodified copy.
- One plant per check. Each was linted with `golangci-lint run ./...`. A plant counts as red only when all of these hold:
  - rc ≠ 0;
  - every planted use gets a forbidigo finding with the configured message;
  - there is no finding outside the plant file.
- G36: `go test -count=1 ./internal/agent/... -run 'Security|TLS|Job'`. G35: `go test -count=1 ./... -run Contract`.

## Results

| Criterion (REQ-144) | Result | Rows |
| --- | --- | --- |
| (1) G8 passes on the M6 tree | 0 issues; gofmt clean; nolint grep empty; modules verified | CHK-M6-140 |
| (2) each planted use in a non-test file under `agent/internal/agent/` turns G8 red with its message | 3/3 red: `fcgi.Serve` with "the agent opens no listening socket; …", and `net.FileConn` and `net.FilePacketConn` with "the agent opens or adopts no listening socket; …" | CHK-M6-337, -338, -339 |
| variants (full rigor) | 9/9 red: aliased imports, function values, dot imports, a function passed as an argument or held in a local variable; also in `cmd/bitscan-agent`, `internal/inventory`, `internal/agent/transport` and a new package | CHK-M6-142 |
| the new rules are what catch it | the HEAD (pre-change) config on the same plant: 0 issues | CHK-M6-142-ctl |
| test files | the three calls in a `_test.go`: lifted. `InsecureSkipVerify` in a `_test.go`: still red (exclusion not widened). `net.Dial`: green | CHK-M6-143 |
| (3) no existing rule removed or narrowed | diff: two rules and comments added, one comment reworded (M6 → M10), nothing else; 4 old rules re-planted, all red | CHK-M6-144 |
| (3) nolint grep still passes | empty | CHK-M6-140 |
| (3) G36 still passes | 63/63 passed, 0 failed, 0 skipped; G35 385/389 passed, 4 named lone-surrogate skips (M4 ruling) | CHK-M6-145 |

Totals: plants 16/16 red (3 mutation rows, 9 variants, 4 old rules); controls 4/4 as expected; G36 63/63; G35 385/389 (4 named skips).

## Notes

- The text output prints the selector as it is written in the source (`f.Serve`, `Serve`, `c.InsecureSkipVerify`). The configured messages match exactly.
- golangci-lint reports one issue per line. On `net.Listen(":0")` and `http.ListenAndServe` gosec (G102/G114) claims the line first, so the old-rule plants ran with forbidigo alone. In the full run those plants are red anyway, through gosec.
- The implementer's observation stands and is out of scope: forbidigo does not see the composite-literal form `&tls.Config{InsecureSkipVerify: true}`. gosec G402 catches it, but in a `_test.go` an explicit `//nolint:gosec` lets it through. The reviewer decides.
- Residuals that lint can't close, unchanged: `go:linkname` (covered by the grep) and third-party packages that wrap a listener.
