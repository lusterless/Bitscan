# Implementer: workspace audit, rounds 1 to 3 (merged)

Scope: workspace hygiene, plus the spec slice TS §1, §2, §3.1, §3.2 and §8.5–§8.7 against `.claude/**`. In round 3 the implementer was the single writer of `.claude/**`, README.md, `.gitignore`, `.gitattributes` and `docs/agent-teams-reference.md`. Nothing is committed. Earlier versions of this report are `work/audit/archive/round1-implementer.md`, `round2-implementer.md` and `round3-implementer.md`.

## Done

Applied in commit 01748b2 (round 1 to 2, by the lead):
- Repo bootstrap: the shared `.claude/settings.json` holds the team flag and `settings.local.json` is ignored; `.gitignore`, `.gitattributes` (`eol=lf`) and README added; `.claude/**` and `docs/spec/` committed (I-01 to I-04, I-11).
- SKILL.md: the `~/Downloads` copy step and the stale `~/.claude/plans` pointer removed; milestone order inlined (I-05, I-06).
- Team naming and ownership: `impl-<area>`, five implementer areas, `work/reports/` owners, `bits/samples/` vs `bits/tests/` (I-07 to I-10).

Applied in round 3, verified by reviewer and tester (uncommitted working tree):
- Addressing: `main` instead of `lead` in the four role files, CLAUDE.md, SKILL.md and agent-teams-reference.md:219.
- `bits/` split carried through: implementer.md, SKILL.md, testing.md `paths:`, bit-format.md authoring heading and fixture note.
- CLAUDE.md: TS §1.3/§1.4 terms, `docs/spec/` and `work/` in the layout, README: `work/open-questions.md` row.
- `.gitignore`: preseed and `install.env` (they carry the `bse_` token, TS §3.1), plus build and coverage outputs that do not depend on the layout. The OpenAPI client stays tracked. `.gitattributes`: `*.gz binary`.
- Agent rules (agent.md, runner-sandbox.md): token `issued_at`/`expires_at` stored and replaced on rotate; NTP prerequisite; `spool_overflow` in the results `error` field; "with a new enrolment token" for `token_revoked`/`token_expired` only; the agent (not the runner) reports `runner_unavailable`; OS matrix on the Tests line; the invented "manager computes `list_sha256` identically" removed.
- Deploy rule (packaging-and-units.md): purge leads to offline, then decommission, with no deregistering endpoint; runbook gets NTP, cloned-image `machine-id` and pinning guidance; `ExecStart … serve`; "the upgrade runbook starts it first" for migrate (R3-I-05, which also covers R2-I-S2: the migrate unit has no `[Install]`, so only the runbook starts it).
- TS §8.5 caveats (R2-I-12, cited by open-questions #10 and #11): one Family per file and the normalisation rules are implemented as written, and the owner is asked before either is relaxed. The manager install constraint (R2-I-18) is merged into open question #6.
- Manager rules: offline_sweep timeouts (24 h never-started, 30 min inventory); full job-state transitions including inventory; pickup bound; cancel of dispatched or running jobs; scans never take `dispatched` or `expired`; host compliance score; re-evaluation route, TOTP, audit and recorded columns; `eval_detail` examples; display name vs `plugin_name_snap`; lengths in characters; start-up order split into TS §4.1 and §4.2 steps; list filters; agent-route error types; schema owner and `USAGE`; enrolment tokens created and revoked; vault token or AppRole secret; Load and Sandbox on Tests lines; sources added to ten Tests lines.
- Security invariants: "owner decisions" wording (every "Never add" kept); viewers never receive `stdout`/`stderr`; the plugin-socket accepted risk.
- Open-question markers: 44 `**Open spec question:**` lines in `.claude/`, each on its own line, with pointers to #1–#18 and #20–#33. Every pointer resolves to an entry marked agreed in `work/open-questions.md`.
- Hygiene check (round 3): no stale paths (`src/` only in `web/src/` and the upstream example), no broken rule references, no empty or CRLF files, fences balanced, front matter intact, and no ignore rule matches a tracked file.
- Checks to re-run after any rule edit:
  - (a) `grep -rn '\*\*Open spec question:\*\*' .claude | grep -vE ':[0-9]+:\s*- \*\*Open spec question:\*\*'` must print nothing.
  - (b) Every `open-questions.md` #N pointer in `.claude/` must match a row marked agreed.
  - (c) `git ls-files | git check-ignore --no-index --stdin` must print nothing.
  - (d) These paths must stay un-ignored: `web/src/**` (including the generated client), `*.test.ts(x)`, `*_test.go`, `bits/tests/*.bit`, `*.gz`.
  - (e) No CRLF in tracked files; fences balanced.

## Open items

- Verified (reviewer in `reviewer.md`, tester present at the cited lines): the last three appends, applied after their round-3 confirmations. They are R3-P-51 (jobs-and-scans.md:23, inventory transitions), R3-I-05 (packaging-and-units.md:51) and R3-I-06 narrowed (agent.md:25).
- PD-9 (R2-I-03): build output paths and the packaging tool. When it is decided, add the held `.gitignore` entries (R2-I-02): `deploy/debian/.debhelper/`, `debhelper-build-stamp`, `files`, `*.substvars`, the package staging directory, `manager/build/`, `.venv/`. Also check that `agent/bin/` and `dist/` match the chosen paths.
- PD-10 (R2-I-11): `.claude/settings.local.json` (ignored, on disk) duplicates the team flag and would override `settings.json`. The user deletes it or keeps it.
- PD-8 (R2-I-04): the `-text` fixture paths for CRLF inputs (normaliser stdout, CSV golden files) are not chosen; testing.md:18 lists both options.
- PD-7 (was I-14): the fallback for an agent type that fails to load is in agent-teams-reference.md §15 but not in SKILL.md. The user should also trust the exact repo folder so that `.claude/agents/` types load.
- PD-11, plus one more item: in the user's memory file `bitscan-project-decisions.md` (outside the repo), "Go 1.22" is stale (CLAUDE.md and TS §2.1 say "a currently supported release"). Its rotation line ("self-rotation in last 30 days") is right only for the default TTL (TS §3.2 step 7: `issued_at + max(TTL − 30 days, TTL ÷ 2)`). The user or main edits it.
- Spec-internal, owner only: the TS §3.1 State row and the §3.6 `state_dir` comment omit the stored `issued_at`/`expires_at` (S-11 in open-questions §5).
- All behaviour questions: `work/open-questions.md` #1–#18 and #20–#33. Do not implement the affected behaviour until they are answered.
- Commit: the round-3 working-tree changes are uncommitted and wait for the user.

## Decisions

- Single-writer exception (work/decisions.md, 2026-10-19): for this clean-up only, the implementer writes `.claude/**`, README.md, `.gitignore`, `.gitattributes` and `docs/agent-teams-reference.md`. Normal ownership (`manager/`, `agent/`, `web/`, `bits/samples/`, `deploy/`) applies again afterwards.
- Spec-silent behaviour goes in only as an `**Open spec question:**` line on its own line, with a pointer to an agreed entry in `work/open-questions.md`, and never as a rule. Rule wording is trimmed to what the spec says (for example, "atomically" and "maintainer scripts call no manager endpoint" were dropped).
- Rejected: the agent.md:34 "runner_unavailable in the results `error` field" (planner): it picks the answer that #28 asks for. It was reverted.
- Rejected: R2-I-09, a retitle of agent-teams-patterns.md §7–§8. That file belongs to the lead.
- Rejected: #19 (scan-level score). TS §4.5 defines only the host score, so there is nothing to ask. It is withdrawn and has no marker.
- Narrowed: "with a new enrolment token" applies only to `token_revoked` and `token_expired` (TS §3.2 step 8). For `enrollment_rejected` the spec says only that the agent stops.
- The generated OpenAPI client under `web/` is committed and never ignored: CI regenerates it and requires no diff (web-ui.md Tests).
- Reviewer withdrew R2-R-15 as a FIX: TS §8.2 names no test runner, so the test and coverage commands are PD-5, not rule text. The coverage gate stays.
- Kept as is: the `src/auth/` spawn-prompt example at agent-teams-reference.md:208 is an upstream quote (I-13).
- `.bit` files are not affected by `eol=lf`, because XML end-of-line handling turns CRLF into LF before the importer sees it. Only CRLF stdout and CSV golden fixtures are at risk (PD-8).
- The memory file is outside the repo. Its fixes are reported, never edited by the team.
