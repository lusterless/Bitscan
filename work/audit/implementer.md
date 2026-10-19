# Implementer audit: workspace hygiene (round 1)

Lens: workspace hygiene, then apply CONFIRMED minimal doc fixes. Read-only so far.

## Inventory (2026-10-19)

`git status --short`: ` D .CLAUDE.md`, `?? .claude/CLAUDE.md`, `?? .claude/agents/`, `?? .claude/rules/`, `?? .claude/skills/`, `?? docs/spec/`.
`git ls-files` (tracked): `.CLAUDE.md` (deleted in tree), `.claude/settings.local.json`, `README.md`, `docs/agent-teams-reference.md`.
Files on disk (bytes): `.claude/CLAUDE.md` 8316; 4 agent files (2962-3293); 17 rule files (2725-7821); `.claude/skills/bitscan-team/SKILL.md` 7076; `.claude/settings.local.json` 67; `README.md` **0**; `docs/agent-teams-reference.md` 18318; `docs/spec/Technical_Specification.md` 111345; `docs/spec/bit_Schema_Reference.md` 19045. `work/` empty (only `work/audit/` created by this run).
No `.gitignore`, no `.gitattributes`. `core.autocrlf=false` (user gitconfig). All in-scope files are LF, no trailing blanks, end with a newline.
`docs/spec/*` are byte-identical to `~/Downloads/Technical_Specification.md` and `~/Downloads/bit_Schema_Reference.md` (`cmp`).
Every `rules/...md` cross-reference in `.claude/**` resolves to an existing file. No `src/`, `.CLAUDE.md`, `docs/specs/` or `docs/schema/` reference remains in `.claude/**` except the deliberate "superseded" note in SKILL.md:17; the one `src/auth/` (agent-teams-reference.md:208) is a generic upstream example.
History: `.clinerules` -> `.CLAUDE.md` (a template with `src/web`, `src/api`, `docs/specs/`, `docs/schema/`, `make test` placeholders) -> deleted in the working tree, replaced by `.claude/CLAUDE.md`.

## Findings

I-01 | severity: should-fix | docs/agent-teams-reference.md:12, :51, :338; .claude/skills/bitscan-team/SKILL.md:10 | Docs say `.claude/settings.local.json` is "local, not shared" / "uncommitted", but it is tracked in git (committed in 8d6f42f; `git ls-files -s` shows it; no ignore rule). | `git ls-files` lists it; `git check-ignore -v .claude/settings.local.json` prints nothing; no `.gitignore`, no global excludes file. | Decide where the flag lives. Recommended: move `{"env":{"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS":"1"}}` to a shared `.claude/settings.json` (the `/bitscan-team` skill depends on it, so every clone needs it), `git rm --cached .claude/settings.local.json`, add it to `.gitignore`, then update agent-teams-reference.md:12/:338 and SKILL.md:10 to name `.claude/settings.json`. Alternative: keep it local and untrack it (docs then already correct). | needs-user-decision: yes | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-02 | severity: should-fix | (repo root) | No `.gitignore`. The documented workflow will create `manager/.venv`, Python caches, `node_modules`, web build output, Go/deb build output. | `ls -la` shows none; CLAUDE.md:104 (venv at `manager/.venv`), :91 (npm in `web/`), :90 (Go build). | Create `.gitignore` with at least: `manager/.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `node_modules/`, `web/dist/`, `web/build/`, `agent/bin/`, `dist/`, `*.deb`, `.env`, `.claude/settings.local.json` (if I-01 goes the recommended way), `.claude/worktrees/`, `Thumbs.db`, `.DS_Store`. Decide whether `work/audit/` (and `work/` in general) is committed. | needs-user-decision: yes | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-03 | severity: should-fix | README.md (0 bytes) | Empty README; nothing tells a human what the repo is or where the rules/specs live. | `file README.md` -> empty; created in a5624b8 and never filled. | Write a short README: one-paragraph summary (copy CLAUDE.md:3), links to `docs/spec/` (TS, SR), `.claude/CLAUDE.md`, `.claude/rules/`, `docs/agent-teams-reference.md`, the top-level layout, local-dev prerequisites (Python 3.12 venv at `manager/.venv`, Go, Node, Docker for Testcontainers), how to run `/bitscan-team`, and "no code yet" status. Content is the owner's call. | needs-user-decision: yes | status: UNVERIFIED

I-04 | severity: blocker (for a shared repo) | .claude/CLAUDE.md, .claude/agents/, .claude/rules/, .claude/skills/, docs/spec/ (untracked); .CLAUDE.md (deleted, unstaged) | All project rules and both specs are untracked, while the stale `.CLAUDE.md` template is still in HEAD. A fresh clone gets the template and none of the real rules. | `git status --short`. | Commit as one change: `git rm .CLAUDE.md` + `git add .claude/CLAUDE.md .claude/agents .claude/rules .claude/skills docs/spec` (plus I-01/I-02 outcome). Committing is the user's call. | needs-user-decision: yes | status: UNVERIFIED

I-05 | severity: nit | .claude/skills/bitscan-team/SKILL.md:16 | "If the files are missing, copy them from `~/Downloads/` before anything else." Machine-specific bootstrap step; the specs are already in `docs/spec/` (identical to the Downloads copies). Becomes stale once I-04 commits `docs/spec/`. | `cmp` identical; untracked `docs/spec/`. | After I-04, drop the sentence (or replace with "If they are missing, stop and ask the user"). | needs-user-decision: yes (depends on I-04) | status: UNVERIFIED

I-06 | severity: should-fix | .claude/skills/bitscan-team/SKILL.md:17 | References `~/.claude/plans/*cozy-music.md`, a file outside the repo that only exists on this machine (`~/.claude/plans/c-users-kaiquan-koh-downloads-aic-bitsc-cozy-music.md`), and that the line itself says is stale. The only thing used from it (milestone order M0-M8) is already inlined here and in planner.md:30. | `ls ~/.claude/plans/`; planner.md:30 repeats the M0-M8 list. | Replace the line with a self-contained milestone order, e.g. "Milestone order: M0 scaffolding, M1 DB + Debian version compare, ... M8 end-to-end/load/observability. Older plans outside this repo predate the 19 Oct spec; ignore them." Minimal, no behaviour change. | needs-user-decision: no | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-07 | severity: should-fix | .claude/CLAUDE.md:110; .claude/skills/bitscan-team/SKILL.md:26 vs SKILL.md:38; .claude/agents/tester.md:24; .claude/agents/reviewer.md:30 | Implementer teammate name is inconsistent: CLAUDE.md and SKILL.md:26 say `implementer-<area>`, SKILL.md:38 spawns `impl-manager`/`impl-agent`/`impl-web` and says "Name teammates exactly as above so messages are predictable"; tester.md:24 and reviewer.md:30 say "message `implementer`", a name no teammate has. Messages to `implementer` would fail. | Quoted lines. | Use `impl-<area>` everywhere: CLAUDE.md:110 and SKILL.md:26 `implementer-<area>` -> `impl-<area>`; tester.md:24 and reviewer.md:30 "message `implementer` and `lead`" -> "message the task's implementer (`impl-<area>`) and `lead`". | needs-user-decision: no | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-08 | severity: should-fix | .claude/skills/bitscan-team/SKILL.md:38 | Only `impl-manager`, `impl-agent`, `impl-web` are defined, but the implementer role and CLAUDE.md:110 cover five areas (`manager/`, `agent/`, `web/`, `bits/`, `deploy/`). No teammate name exists for `bits/` or `deploy/` work (M0 scaffolding, M6 `.deb`). | implementer.md:3, :8; CLAUDE.md:110. | Change to "`impl-manager`, `impl-agent`, `impl-web`, `impl-bits`, `impl-deploy` (agent type `implementer`; only the areas the current wave needs; Sonnet)". | needs-user-decision: no | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-09 | severity: should-fix | .claude/CLAUDE.md:110; .claude/skills/bitscan-team/SKILL.md:26 | Ownership lists have a hole for `work/reports/`: CLAUDE.md:110 gives no owner for `work/reports/` at all; SKILL.md:26 gives tester `work/reports/*-test.md` but not the implementer's `work/reports/TASK-###-impl.md` (implementer.md:18). | Quoted lines; implementer.md:18, tester.md:16. | CLAUDE.md:110: add "plus `work/reports/TASK-###-impl.md`" to the implementer clause and "plus `work/reports/TASK-###-test.md`" to the tester clause. SKILL.md:26: add "plus `work/reports/*-impl.md`" to the implementer clause. | needs-user-decision: no | status: CONFIRMED (tester; reviewer for I-07..I-09)

I-10 | severity: should-fix | .claude/CLAUDE.md:73, :110; .claude/agents/tester.md:16; .claude/agents/implementer.md:8; SKILL.md:26 | `bits/` is co-owned: implementers own non-test files in `bits/` (samples), the tester owns "test fixtures under `bits/`", and the layout line is "sample and test .bit files" with no sub-path. SKILL.md:26 says "Two teammates never own the same file", but nothing says which `bits/` file is which. | Quoted lines. | Pick a convention, e.g. `bits/samples/` (implementer) and `bits/fixtures/` (tester), and write it into CLAUDE.md layout and the ownership lines. Layout change -> owner decision. | needs-user-decision: yes | status: UNVERIFIED

I-11 | severity: nit | (repo root) | No `.gitattributes`. Files are LF today and `core.autocrlf=false` here, but the repo will hold shell maintainer scripts, systemd units and D-Bus XML that must stay LF on a Windows dev box. | `tr -cd '\r' | wc -c` = 0 for all files; no `.gitattributes`. | Add `.gitattributes` with `* text=auto eol=lf` (or at least for `deploy/**`, `*.sh`, `*.service`, `*.socket`). | needs-user-decision: yes | status: UNVERIFIED

I-12 | severity: nit | (outside repo) ~/.claude/projects/.../memory/MEMORY.md | The auto-memory index line reads "layout under src/", which contradicts the memory file it points to (that says top-level layout, `src/` superseded) and `.claude/CLAUDE.md`. Can mislead a future session. | MEMORY.md index line vs bitscan-project-decisions.md body. | User (or lead) updates the index line to "top-level layout (manager/ agent/ web/ bits/ deploy/ e2e/)". Out of my edit scope. | needs-user-decision: yes | status: UNVERIFIED

I-13 | severity: nit | docs/agent-teams-reference.md:208 | The spawn-prompt example says "at src/auth/". It is a generic upstream example, but it is the only `src/` path left in the repo docs and this repo's layout is `manager/bitscan_manager/auth/`. | Grep. | Optional: replace with `manager/bitscan_manager/auth/` and "bsu_ session tokens held in memory" to match web-ui.md; or leave as an upstream quote. | needs-user-decision: no | status: CLOSED (reviewer: leave as upstream quote)

I-14 | severity: nit | (session) | This run reports "the custom agent type could not be loaded", although `.claude/agents/*.md` have valid frontmatter. Likely cause per agent-teams-reference.md:170: project agent definitions only apply when that exact folder is trusted. | Spawn prompt note; reference line 170. | No doc change; tell the user to trust `C:\Users\kaiquan.koh\Documents\Bitscan` itself before `/bitscan-team`. Optionally add that to reference section 15. | needs-user-decision: yes | status: UNVERIFIED

## Duplication between docs/agent-teams-reference.md and .claude/CLAUDE.md / rules / SKILL.md

- Section 15 (project notes) partly repeats SKILL.md:10 (flag location, in-process mode). Consistent apart from I-01. Keep both; low risk.
- Team size "3-5 teammates" (ref :14, :281) matches SKILL.md:37. "5-6 tasks per teammate" (ref :14, :184) is generic guidance; SKILL.md uses waves instead. Not a contradiction.
- No contradiction found with CLAUDE.md owner decisions or the rules; the reference is about Claude Code mechanics, not Bitscan behaviour.

## Cross-check (round 2)

- reviewer: I-07 CONFIRMED (= R-03), I-08 CONFIRMED, I-09 CONFIRMED (= R-12), I-13 leave as upstream quote, I-10 agrees needs-user-decision (suggested `bits/tests/` for fixtures). I pointed out that R-03's text proposes `implementer-<area>` while its I-07 confirmation uses `impl-<area>`; the spawn names in SKILL.md:38/:41 are `impl-*`, so `impl-<area>` is the scheme to use.
- planner: supports I-06 (old plan contains "Schema additions beyond the spec DDL", "Agent token lifecycle (changed from the spec)" and M7 "src/web", so keeping the pointer is a risk); I-10 = P-03 (proposes `bits/samples/` + `bits/tests/`, user decision); I-02 = P-30, I-03 = P-31, I-07 = P-01, I-09 = P-04.
- tester: I-01, I-06, I-07, I-08, I-09 CONFIRMED (its T-06, T-21, T-03, T-04, T-05). It also confirmed that no `.gitignore` exists, that every file is LF, and that the Downloads spec copies are byte-identical. It found one more I-07 site: tester.md:17 ("goes back to the `implementer` as a message"), patch P-I07e below. I-01 is confirmed as a fact. I did not reword agent-teams-reference.md:12/:51/:338, because the right wording depends on the user's settings decision (shared settings.json, or keep it local and untrack it).

## Why I applied nothing

Every confirmed fix is in `.claude/CLAUDE.md`, `.claude/rules/`, `.claude/agents/` or `.claude/skills/`. Those are Claude instruction and configuration files. The session's safety rules say a teammate request can't authorise changes to CLAUDE.md or configuration. Only the user can, so I made no edits. The only in-scope file outside `.claude/` is `docs/agent-teams-reference.md`, and no confirmed fix touches it (I-13: leave). Below are exact patches for `lead` to apply once the user approves.

### Ready-to-apply patches (confirmed wording)

P-I07a (I-07, CONFIRMED by reviewer) `.claude/CLAUDE.md:110`
- before: `` `implementer-<area>` owns non-test files in `manager/`, `agent/`, `web/`, `bits/` or `deploy/`; ``
- after: `` `impl-<area>` (agent type `implementer`) owns non-test files in `manager/`, `agent/`, `web/`, `bits/` or `deploy/`, plus `work/reports/TASK-###-impl.md`; `` (the last clause also covers I-09)

P-I09a (I-09, CONFIRMED by reviewer) `.claude/CLAUDE.md:110`, tester clause
- before: `` `e2e/`, `bits/` test fixtures); ``
- after: `` `e2e/`, `bits/` test fixtures) plus `work/reports/TASK-###-test.md`; ``

P-I07b + P-I09b (I-07, I-09, CONFIRMED by reviewer) `.claude/skills/bitscan-team/SKILL.md:26`
- before: `implementer-<area> -> non-test files in its top-level `<area>/` (`manager/`, `agent/`, `web/`, `bits/`, `deploy/`).`
- after: `` `impl-<area>` -> non-test files in its top-level `<area>/` (`manager/`, `agent/`, `web/`, `bits/`, `deploy/`) plus `work/reports/*-impl.md`. ``

P-I08 (I-08, CONFIRMED by reviewer) `.claude/skills/bitscan-team/SKILL.md:38`
- before: `` - `impl-manager`, `impl-agent`, `impl-web` (agent type `implementer`; only the areas the current wave needs; Sonnet), ``
- after: `` - `impl-manager`, `impl-agent`, `impl-web`, `impl-bits`, `impl-deploy` (agent type `implementer`; only the areas the current wave needs; Sonnet), ``

P-I07c (I-07, CONFIRMED by reviewer) `.claude/agents/tester.md:24`
- before: `` On FAIL leave it in progress, message `implementer` and `lead` with the report path ``
- after: `` On FAIL leave it in progress, message the task's implementer (`impl-<area>`) and `lead` with the report path ``

P-I07d (I-07, CONFIRMED by reviewer) `.claude/agents/reviewer.md:30`
- before: `` On CHANGES_REQUESTED message `implementer` and `lead` with the path ``
- after: `` On CHANGES_REQUESTED message the task's implementer (`impl-<area>`) and `lead` with the path ``

P-I07e (I-07, found by tester) `.claude/agents/tester.md:17`
- before: `` A product bug goes back to the `implementer` as a message with evidence; ``
- after: `` A product bug goes back to the task's implementer (`impl-<area>`) as a message with evidence; ``

P-I06 (I-06, CONFIRMED by tester, supported by planner) `.claude/skills/bitscan-team/SKILL.md:17`
- before: `` - The old plan `~/.claude/plans/*cozy-music.md` predates the 19 Oct spec (...). Use it only for milestone ordering (...): milestones M0 scaffolding, ..., M8 end-to-end/load/observability. ``
- after: `- Milestone order: M0 scaffolding, M1 DB + Debian version compare, M2 importer/validator/evaluator, M3 auth/RBAC/API plumbing, M4 agent API + scheduler, M5 user API, M6 Go agent + .deb, M7 web UI, M8 end-to-end/load/observability. Older plans outside this repo predate the 19 Oct spec; ignore them.`

Reviewer findings that tester CONFIRMED, as reported by reviewer after my FINAL message. Exact wording is in work/audit/reviewer.md. Same restriction applies: these are proposed, not applied.
- R-01 `.claude/rules/manager/jobs-and-scans.md:27`: "three things" -> "four things", plus a bullet: "creates the single retry for a job that ended `failed` or `partial` because its deadline passed (TS §3.3, §4.4)".
- R-04 `.claude/rules/manager/config-and-cli.md:35`: the heading's DSN note covers only `users …` and `bits rebuild`. Line 41 -> "`db migrate` and `db maintain`: run by `bitscan-manager-migrate.service` / `bitscan-manager-maintain.timer`, reading `BITSCAN_MIGRATE_DSN_FILE`, as `bitscan_migrate` with `SET ROLE bitscan_owner`".
- R-05 `.claude/rules/manager/api.md:38`: add "`GET`/`DELETE /api-tokens`: viewer, own tokens (session or API token)" and "No role: `POST /auth/login`, `/auth/logout`".
- R-06 `.claude/CLAUDE.md:16`: append "(TS §3.3)" after "300 s ± 30 s".
- R-07 `.claude/rules/security-invariants.md:13`: citation -> "(TS §1.2; SR §4.2)".
- R-09 `.claude/rules/security-invariants.md:25`: citation -> "(TS §3.1, §5.3, §8.1, §8.4)".
- R-10: citations on the "Tests (TS §8.3)" lines. packaging-and-units.md:61 and testing.md:47 -> TS §3.1; web-ui.md:29 -> TS §8.2, §6.3. Align testing.md:18-19 with the runner-sandbox.md fixture list, adding "AKIA/ASIA key ids (TS §8.6 pattern 4)".
- R-03 = I-07/I-08 and R-12 = I-09 (patches above). R-02, R-08 and R-11 are not confirmed and not included.

Fixes other teammates proposed in rules files (R-01, R-04, R-05, R-06, R-07, R-09; P-21, P-23, P-28, P-29, P-32, P-33, P-35) fall under the same restriction. They are in work/audit/reviewer.md and work/audit/planner.md for the lead.

## Changes made

None. No file other than this report was created or edited.

## Needs user decision

- I-01: settings flag. Recommended: shared `.claude/settings.json` + untrack and ignore `settings.local.json`, then reword ref :12/:51/:338 and SKILL.md:10.
- I-02: create `.gitignore` (entries listed in I-02); decide whether `work/` is committed.
- I-03: README content (outline in I-03, same as planner P-31).
- I-04: commit `.claude/**` and `docs/spec/`, and stage the `.CLAUDE.md` deletion, as one change.
- I-05: drop the `~/Downloads` copy step in SKILL.md:16 after I-04.
- I-10: `bits/` sub-paths. Planner suggests `bits/samples/` + `bits/tests/`, reviewer suggests `bits/tests/`.
- I-11: `.gitattributes` with `eol=lf`.
- I-12: fix the stale "layout under src/" line in the auto-memory index. Reviewer noticed it too.
- I-14: trust the exact repo folder so `.claude/agents/` types load. Planner P-37 proposes a fallback line in SKILL.md.
- All patches above (P-I06, P-I07a-e, P-I08, P-I09a-b): approve, then lead applies them. They are confirmed but not applied.
