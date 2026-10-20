# TASK-004 REVIEW: Go module, golangci-lint config, three binary stubs

Reviewer: reviewer. Date: 2026-10-20. REQ-010 (as reworded), REQ-011, REQ-012. Spec: TS §2.2 L111, §3.1 L158, §3.7, §8.1 L1247, §8.2 L1265. Rules: `.claude/rules/agent/agent.md`, security invariants "Never add". Inputs: `work/plans/TASK-004.md`, `work/reports/TASK-004-impl.md` (round 3), `work/reports/TASK-004-test.md` (PASS, round 3), `tests/m0/report.md` CHK-M0-060 to -079, -076-r3, -076-r3-ctl, -076-r3-nolint and -070-r3, `work/decisions.md` 2026-10-20 (M6 carry-over).

Verdict: APPROVED

Round 3. This is the reviewer approval, the first of the two that TS §8.2 L1268 requires (the change touches the agent and runner). TASK-004 is approved pending the user's second approval, which `main` collects. It is not complete until that second approval is recorded.

## Round 3 re-review

Only `agent/.golangci.yml` (67 lines) and the impl report changed. The tree still gives `0 issues.` and `gofmt` is empty. In `mktemp -d` copies, deleted afterwards:

| Round-2 finding | Round-3 plant | Result |
| --- | --- | --- |
| 1. a "generated" header skips the file | `// Code generated … DO NOT EDIT.` + `net.Listen` | red (forbidigo); `exclusions.generated: disable` at L56 |
| 2. embedded or interface `http.Server` | `struct{ http.Server }` + `s.ListenAndServe()`; `var l L = &http.Server{}` | red; types forbidden at L33-38 |
| 3. assigning the `InsecureSkipVerify` field | `c.InsecureSkipVerify = true`, in a non-test file and in `_test.go` | red in both; L52, and the test exclusion is scoped by `text: no listening socket` (L63) |
| added by `main` | `syscall.Socket` + `Bind`, `net.FileListener`, `//nolint:all`, bare `//nolint` | red (forbidigo, nolintlint) |

- Green controls:
  - an `http.Client` with `http.Transport` and TLS 1.2;
  - a `_test.go` file that uses `httptest.NewServer`, `net.Listen` and `&http.Server{}`.
- The round-1 and round-2 plants are still red: method values, method expressions, aliases, dot imports, `InsecureSkipVerify` set from a variable or argument, errcheck and errorlint.
- My round-1 checks of builds, `go version -m`, the CgoFiles listing, `go mod verify` and the stubs still hold. The stubs and `go.mod` are unchanged.

## Findings (round 3)

1. **nit, for TASK-010.** A specific, explained `//nolint:forbidigo // reason` still suppresses the guard. nolintlint only rejects bare, unspecific or unexplained directives. The TASK-010 `agent.yml` grep step must close this.
   - It must fail when any non-test Go file under `agent/` contains a `//nolint` directive in any form.
   - Concretely: `grep -rnE '//[[:space:]]*nolint' --include='*.go' agent | grep -vE '_test\.go:'` must print nothing.
   - It should also fail on `//go:linkname` in non-test files.
2. **Residual risks for M6** (recorded in `work/decisions.md` 2026-10-20):
   - `go:linkname`, if the grep above does not cover it;
   - `net/http/fcgi.Serve(nil, …)`;
   - `net.FileConn` and `net.FilePacketConn`;
   - the narrowly scoped two-approval `net.FileListener` exceptions for the runner and capread.

   Also: lint must run on a Linux runner, because `_linux.go` files are not linted on the Windows dev box.

## Round 1 and 2 (history)

Round 2 was CHANGES_REQUESTED with three should-fix findings, all fixed in round 3:

1. `exclusions.generated` defaulted to lax, so a "generated" header skipped the file;
2. an embedded or interface-typed `http.Server` bypassed the method patterns;
3. assigning the `InsecureSkipVerify` field passed.

Its nits were the `//nolint` bypass (now partly closed by nolintlint, the rest is the TASK-010 grep), Linux-only files not being linted locally, and the M6 residual list.
