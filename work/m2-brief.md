# M2 team brief

Written by the lead (`main`). Read `work/m0-brief.md` and `work/m1-brief.md` first; they still apply unless changed here. Date: 2026-10-21.

## What we are doing
Milestone M2, auth core and API plumbing (old M3; see the reorder in `work/decisions.md`, 2026-10-20). Branch: `m2-auth-core`, from `main` at `5898951` (M0 and M1 merged). The lead commits; nobody else commits or pushes.

## Decisions since M1 (work/decisions.md)
- All agent roles run on `provider-1/claude-opus` (frontmatter in `.claude/agents/*.md`).
- Docs: the lead keeps `work/status.md` current; impl-manager owns the README user guide and updates it in the same task as the behaviour; README holds only user-guide content.
- Milestones land as stacked PRs, one migration per PR (TASK-022 gate on every PR); merge commits, in order. Required checks are not available on this GitHub plan, so merge only when every check is green.
- WSL: only the tester runs WSL, one run at a time, with scripts named `%TEMP%\tester2_*.sh` (allow rule in `.claude/settings.json`). The lead does not run WSL.
- Accepted residual risks carried into M2: the audit chain needs the external sink (M2) to catch a full rewrite, tail deletion or retention-role pruning; the `db maintain` clock skew below the window plus one month needs the TS §8.4 clock-skew alert.

## Scope
Carry-overs assigned to M2 by the reorder: OpenTelemetry explicitly off in `create_app()`, the web `baseUrl` (`""` vs `/api/v1`) recheck, and security-header middleware with the first routes. Open spec questions flagged for M2: #5, #7, #24 and the alert thresholds. Agent routes, enrolment and the scheduler are M3; do not build them.
