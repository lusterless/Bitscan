# TASK-132 REVIEW: agent lint forbids fcgi.Serve, net.FileConn, net.FilePacketConn

Verdict: APPROVED

Reviewer: reviewer, 2026-10-26. Round 1. High risk (agent): TS §8.2 L1268 needs two approvals. This is the first one; the user's second approval follows under the overnight rule (decisions 2026-10-26 (3)). No blocking or should-fix finding is open.

Scope reviewed: `agent/.golangci.yml`, the only file in the diff (`git diff 8ad50eb -- agent/`: +10 / −1; `work/reports/TASK-132-impl.md`). Sources:
- REQ-144;
- TS §2.2 L111 and §3.3 L210 (pull only, no listening port);
- security invariants "Never add" (listening port, push channel);
- `.claude/rules/agent/agent.md` "Never";
- reviewer TASK-004 residuals (decisions 2026-10-20).

TEST: PASS, round 1, full rigor (tester-m6, `TASK-132-test.md`):
- 16/16 plants red: 3 mutation rows, 9 variants and 4 old rules re-planted;
- 4/4 controls as expected;
- G36 63/63; G35 385/389, the 4 skips being the named M4 lone-surrogate ones.

## Checks
1. **Spec conformance.**
   - Both new rules use the existing style: `analyze-types: true` and a `pkg:` regex anchored on the import path (`^net$`, `^net/http/fcgi$`). Aliases, dot imports and function values are therefore caught too, which the tester's variants confirm.
   - Each message cites TS §2.2.
   - `net.FileListener` stays a separate rule, so M10 can scope its socket-activation exceptions to it alone. The comment's "M6" → "M10" correction matches REQ-144.
2. **Security invariants.**
   - Nothing is removed or narrowed, and `exclusions` is unchanged.
   - Both new messages contain "no listening socket", so the existing `_test.go` exclusion lifts them in test files and nowhere else.
   - `InsecureSkipVerify` stays forbidden in tests. The tester's control and the implementer's C3 control both show this.
3. **Scope.** One file, 10 lines, as the task row states. No Go source changed.
4. **Tests, re-run by me** on the worktree:
   - `gofmt -l .` prints nothing.
   - `GOOS=linux golangci-lint run ./...` (2.14.0) reports 0 issues.
   - The CI nolint/linkname grep is empty.
   - The three calls planted in a throwaway copy of `agent/` under `/tmp` (`internal/agent/loops`, exported function) gave 3 forbidigo issues with the configured messages and rc 1. The copy was deleted.
5. **Correctness.** The `^net\.(FileConn|FilePacketConn)$` and `^fcgi\.Serve$` patterns match only those functions. `net.Dial` stays green (tester control), and `fcgi.ProcessEnv` is not forbidden.

## Findings
None blocking, none should-fix, no nits.

## Follow-up (not a finding; outside REQ-144; main queues it for a later milestone)
- **Gap:** forbidigo does not see the composite-literal key form `&tls.Config{InsecureSkipVerify: true}`.
  - gosec G402 catches it in every file.
  - In a `_test.go`, an explicit `//nolint:gosec // reason` lets the literal through, because the CI grep in `.github/workflows/agent.yml` L54–L58 excludes `*_test.go`.
  - Today no agent `_test.go` contains `nolint`. Both `InsecureSkipVerify` mentions in tests are assertions that the field is not set (`transport/client_test.go:820`, `transport/tls_test.go:409`).
- **Suggested fix (impl-deploy, CI owner):** extend the nolint grep to test files, with a reviewed allow-list (empty today), or at least fail on `nolint:gosec` or `nolint:all` on any line that mentions `InsecureSkipVerify`.
- **Not closable by lint**, unchanged from TASK-004: `go:linkname` (covered by the grep) and third-party packages that wrap a listener. These stay with code review.
