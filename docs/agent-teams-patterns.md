# Agent Teams: Workspace Audit Summary and Patterns

Date: 2026-10-19. Goal given to the team: clean up the workspace and make sure every document is accurate and has no holes. Full reports are in `work/audit/` (`planner.md`, `reviewer.md`, `tester.md`, `implementer.md`). Finding ids (P-, R-, T-, I-, S-) refer to those reports.

**Status: the team itself changed no workspace document.** Every confirmed fix was a proposal, because all of them touch `.claude/**` instruction files and the implementer declined to edit them without your approval. After the audit you approved them and the lead applied them; see section 11. Sections 2 to 8 describe the state at audit time.

## 1. How the team ran (lead)

| Item | What happened |
| --- | --- |
| Team | `planner`, `reviewer`, `tester`, `implementer`, plus one unnamed helper (`claude-code-guide`) that fact-checked Claude Code feature claims |
| Deviation | The four custom agent types from `.claude/agents/` were not registered in the running session, so each was started as a general-purpose agent that first read its own role file. The helper confirmed the cause: `.claude/agents/` was created mid-session, and that case needs a restart (or a trusted folder) before the types load |
| Lenses | planner = coverage and holes; reviewer = accuracy against the spec; tester = mechanical verification; implementer = workspace hygiene and applying confirmed fixes |
| Protocol | Round 1 independent audit; round 2 mandatory cross-check (each teammate messages the other three and answers requests); round 3 status update; each ends with one `FINAL:` message |
| Result | 4 reports, about 100 findings in total (41 + 22 + 23 + 14), large overlap between agents, no peer claim refuted except one half of P-20 |
| Cost | Roughly 196k (planner), 239k (reviewer), 232k (tester), 102k (implementer) and 79k (helper) subagent tokens; 11 to 22 minutes each |

Lead's own check of `docs/agent-teams-reference.md` against the official page (no changes made):
- Lines 12, 51 and 338 call `.claude/settings.local.json` "uncommitted / local, not shared", but it is tracked in git (commit `8d6f42f`). The helper adds that Claude Code only adds the file to git excludes when Claude Code creates it, not when it is made by hand.
- The "n/a per docs" cells in the section 5 table (`disallowedTools`, `effort` for split-pane teammates) should read "not stated in docs".
- The guide does not mention that agent definitions created mid-session are not loaded until restart, or that the lead is addressed as `main` by teammates (see section 7).
- Everything else matched the source page, and the helper found no wrong Claude Code claims in the agent, skill, rules and settings files.

## 2. Planner: coverage and holes

41 findings (1 blocker, about 20 should-fix, the rest nits); 20 CONFIRMED by peers, 1 split, the rest are judgement calls left UNVERIFIED.

**Good news:** goals G1 to G6 each trace to at least one rule file, and every TS and SR section is cited by at least one rule or by CLAUDE.md. The holes are at the level of individual requirements.

| Area | Findings |
| --- | --- |
| Workflow holes | P-01 implementer has three names (blocker). P-02 no `impl-bits` or `impl-deploy`. P-03 `bits/` co-owned by implementer and tester. P-04 nobody owns `work/reports/`. P-05 no re-test step after CHANGES_REQUESTED. P-06 with no commits, the reviewer's working-tree diff cannot isolate one task. P-07 the two-approval rule cannot be met with one reviewer. P-08 nobody updates rules after an Open spec question is answered. P-09 CLAUDE.md commands lack test, coverage, Prettier and OpenAPI commands, and Linux-only suites have no stated place to run on Windows |
| New spec ambiguities | P-10 BIT010 and BIT011 "missing" can never fire (BIT002 shadows them) (confirmed). P-11 a scan whose target resolves to zero agents (confirmed). P-13 `agent.yaml` keys vs values fixed elsewhere (confirmed). P-14 no auth defined for `/healthz`, `/readyz` and metrics (confirmed). P-15 manager install and web UI serving. P-16 initial passwords. P-17 to P-19, P-38, P-39 smaller gaps |
| Rules vs spec | P-20 `api.md:40` "GET /policies omits deleted policies" is unsupported by the spec (confirmed); the `web-ui.md:27` "Deleted" state is supported (refuted). P-34 the rotation-window question is answerable: it ends at `expires_at` |
| Uncovered requirements | P-21 `GET`/`DELETE /api-tokens`. P-22 list and filter parameters. P-23 cancel of dispatched and running jobs. P-24 `eval_detail`. P-25 hostname trigram index. P-26 UI items (runner helpers, host click-through, import history). P-27 NTP prerequisite. P-28 coverage gate path `manager/services` does not exist in the layout (confirmed) |
| Cleanup | P-29 fixture lists differ. P-30 no `.gitignore`. P-31 empty README. P-32 layout block omits `work/` and `docs/`. P-33 out-of-scope heading cites too few sections. P-35 duplicated open questions |

## 3. Reviewer: accuracy against the spec

12 findings on workspace documents (R-01 to R-12) and 10 inconsistencies inside the spec (S-01 to S-10). No blockers. The reviewer read both specs and every in-scope file in full and found every number, enum, table and grant, route, status and error code, BIT code, token rule, file mode, unit setting, alert list and test gate consistent with the spec.

| Id | Severity | Finding | Status |
| --- | --- | --- | --- |
| R-01 | should-fix | `jobs-and-scans.md:27-30` says `offline_sweep` does three things; TS §3.3 adds "creates retries" | confirmed |
| R-03 | should-fix | Implementer named three ways; no implementer for `bits/` or `deploy/` | confirmed |
| R-04 | should-fix | `config-and-cli.md:35` says every CLI command reads `app.dsn`; `db migrate` and `db maintain` use the migrate credential from their own units | confirmed |
| R-05 | should-fix | No rule for `GET`/`DELETE /api-tokens`. The spec does not forbid an API token revoking tokens, so the faithful wording is "viewer, own tokens (session or API token)" | confirmed |
| R-06, R-07, R-09, R-10 | nit | Citation scope fixes: jitter is TS §3.3 not §1.1; remediation is TS §1.2; journald is TS §3.1 and §8.1; "Tests (TS §8.3)" lines include items from §3.1, §6.3, §7.2, §8.2 | confirmed |
| R-12 | nit | `work/reports/` ownership incomplete | confirmed |
| R-02, R-08, R-11 | nit | State-line wording; "removed by the owner" overstates for ad-hoc commands and push channels (those are spec prohibitions); viewers "verdicts only" vs web-ui wording | unverified |

Spec-internal items (report to the owner; never edited): S-01 policy delete missing from the TS §6.2 sensitive-action list although the route table and §4.3 require a TOTP session (already an Open spec question). S-02 §5.1 table map omits `agent_ip_seen` and `task`. S-03 §2.1 omits `pgcrypto`. S-04 heartbeat response described as only `job_pull_seconds` in §2.3. S-05 `spool_overflow` called a runner error though the spool is the agent's. S-06 "deadline" used for `pickup_by` in §2.3 and §8.1. S-07 `failed` definition omits the 24 h never-started and inventory cases. S-08 "group" in G6 but only tags exist. S-09 `/agent/enroll` called unauthenticated but needs a `bse_` token. S-10 BIT102 listed after BIT103.

## 4. Tester: mechanical verification

23 findings, all mechanically CONFIRMED, no blockers. The tester treated the docs as code and ran read-only grep and node checks.

**Passed with no finding:**
- All 209 `TS §` and `SR §` citations resolve to real spec headings.
- 54 numeric and enum facts agree with the spec.
- Front matter, names and tool lists in all 21 front-matter files are valid; code fences are balanced; `settings.local.json` is valid JSON; all files are LF.
- Identical across docs and spec: the error `type` values, the 14 operators, the 18 BIT codes, G1 to G6, the agent status values, the 11 D-Bus methods, the CSP header and milestones M0 to M8.
- Every layout directory is covered by a rule `paths:` glob.

**Findings worth acting on:** T-01 out-of-scope heading citation. T-02 coverage gate path. T-03 and T-04 implementer naming and missing areas. T-05 `work/reports/` owner. T-06 `settings.local.json` is tracked and there is no `.gitignore`. T-07 redaction fixture lists differ between `testing.md` and `runner-sandbox.md`. T-09 nine references write `rules/...` without the `.claude/` prefix. T-10 CLI DSN. T-14 `/api-tokens`. T-15 `bits/` ownership. T-16 a few build files (`pyproject.toml`, `requirements.txt`, `go.mod`) fall under no path-scoped rule. T-19 `testing.md` test locations omit web tests and `bits/` fixtures. T-20 the upstream `src/auth/` example contradicts this project. T-21 two pointers outside the repo in `SKILL.md`.

## 5. Implementer: workspace hygiene

14 findings. The implementer made **no edits** and wrote before/after patches instead.

| Id | Finding | Needs your decision |
| --- | --- | --- |
| I-04 | `.claude/**` and `docs/spec/` are untracked while the stale `.CLAUDE.md` template is still in HEAD; a fresh clone gets the template and none of the real rules | yes (commit) |
| I-01 | `settings.local.json` is tracked, but docs call it local. Recommended: move the flag to a shared `.claude/settings.json`, untrack and ignore the local file, reword the three doc lines | yes |
| I-02 | No `.gitignore` (entries listed in the report); decide whether `work/` is committed | yes |
| I-03 | `README.md` is 0 bytes | yes (content) |
| I-05 | Drop the "copy specs from `~/Downloads`" step in `SKILL.md` after specs are committed | depends on I-04 |
| I-06 | `SKILL.md:17` points at a machine-local plan file that also contains stale schema and token-lifecycle content; inline the M0 to M8 order instead | no |
| I-07, I-08, I-09 | Implementer naming, missing `impl-bits` and `impl-deploy`, `work/reports/` ownership | no |
| I-10 | `bits/` split, e.g. `bits/samples/` and `bits/tests/` | yes |
| I-11 | Add `.gitattributes` with `eol=lf` | yes |
| I-12 | Memory index says "layout under src/" | fixed by lead |
| I-13 | `src/auth/` upstream example in the reference guide | leave as upstream quote |
| I-14 | Trust the exact repo folder so custom agent types load | yes |

## 6. Where the agents agreed

| Issue | Found by |
| --- | --- |
| Implementer has three names (`implementer-<area>`, `impl-*`, `implementer`) | planner P-01, reviewer R-03, tester T-03, implementer I-07 |
| No implementer for `bits/` or `deploy/` | P-02, T-04, I-08 |
| `work/reports/` ownership gap | P-04, R-12, T-05, I-09 |
| `bits/` co-owned, no subfolders | P-03, T-15, I-10 |
| `settings.local.json` tracked but documented as local | T-06, I-01, lead and helper |
| `GET`/`DELETE /api-tokens` uncovered | P-21, R-05, T-14 |
| Coverage gate path does not exist | P-28, T-02 |
| No `.gitignore` or README | P-30, P-31, T-22, I-02, I-03 |
| Old plan pointer is stale and machine-local | I-06, T-21 |
| `offline_sweep` omits retries | R-01, T-13 |
| CLI DSN heading wrong | R-04, T-10 |
| Redaction fixture lists differ | P-29, T-07 |
| "Tests (TS §8.3)" lines mislabelled | R-10, T-08 |
| Stale memory index | P-41, I-12, reviewer |

## 7. Decisions needed from you

1. **Teammate names:** approve `impl-<area>` everywhere and add `impl-bits` and `impl-deploy` (patches P-I07a-e, P-I08, P-I09a-b in `work/audit/implementer.md`).
2. **`bits/` layout:** choose subfolder names (suggested `bits/samples/` for implementers and `bits/tests/` for tester fixtures) before M0.
3. **Settings file:** shared `.claude/settings.json` plus untracked, ignored `settings.local.json` (recommended), or keep it local and untrack it, or reword the docs to "committed".
4. **Repo files:** `.gitignore` contents, whether `work/` or `work/audit/` is committed, `.gitattributes`, and README content.
5. **Commit:** `.claude/**`, `docs/spec/`, the `.CLAUDE.md` deletion and whichever fixes you approve, as one change. The lead has not committed anything.
6. **Open spec questions for the owner:** policy delete as a sensitive action and during an audit-sink outage (S-01); BIT010 and BIT011 "missing" (P-10); scan with zero resolved agents (P-11); `agent.yaml` keys vs fixed values (P-13); auth for health and metrics routes (P-14); manager install and web UI serving (P-15); initial passwords (P-16); whether an API token may revoke its own tokens (R-05); whether `GET /policies` lists deleted policies (P-20). Close the rotation-window question as "ends at `expires_at`" (P-34).
7. **Review workflow rules** the planner left open: a baseline for per-task diffs (one commit per approved task, or saved per-task patches) (P-06); a re-test step after CHANGES_REQUESTED (P-05); who is the second approver (P-07); who updates rules once a question is answered (P-08); a fallback when custom agent types do not load (P-37).

## 8. Confirmed fixes ready to apply once you approve

All have exact before/after text in `work/audit/implementer.md` or the reporting agent's file.
- Naming and ownership: `CLAUDE.md:110`, `SKILL.md:26`, `SKILL.md:38`, `tester.md:17` and `:24`, `reviewer.md:30`.
- `SKILL.md:17`: replace the plan pointer with the inline milestone order.
- Rules: `jobs-and-scans.md:27` (add retries), `config-and-cli.md:35` and `:41` (DSN), `api.md:38` (`/api-tokens`, login and logout), `testing.md:21` and `evaluator.md:30` (coverage path annotation), `testing.md:18-19` (fixture superset), `testing.md:15` (test locations), `security-invariants.md:13` and `:25` (citations), `CLAUDE.md:16` (jitter citation), `CLAUDE.md:23` (out-of-scope citations), `.claude/rules` bare `rules/` references (T-09), duplicated open questions (P-35), and the "Tests (TS §8.3)" citations (R-10).
- Guide: `docs/agent-teams-reference.md` lines 12, 51 and 338 once the settings decision is made, and the "n/a per docs" cells.

## 9. Patterns for running agent teams (lessons from this run)

1. **Start in a fresh session after creating `.claude/agents/`.** Definitions created mid-session did not load. If it happens, spawn general-purpose agents and tell each to read `.claude/agents/<role>.md` first. Role tool limits are then honour-system only; Claude Code has no path restriction for subagent definitions anyway.
2. **Tell teammates to address the lead as `main`.** Two teammates could not reach `lead` and sent their FINAL message to `main`. Put the exact address in every spawn prompt.
3. **A completion notification is not a FINAL message.** Teammates that stop to wait for replies still trigger one. Require an explicit `FINAL:` message from each teammate and wait for all of them before synthesizing.
4. **Distinct lenses plus a mandatory cross-check give confidence quickly.** Four agents independently reported the same naming defect; the tester mechanically confirmed 20 or more peer claims; the reviewer split one planner finding (P-20), which a single-agent audit would have missed.
5. **Split mechanical from semantic checking.** Citations, paths, globs, counts and front matter were verified by grep and node (tester); wording against the spec was judged by the reviewer. Neither lens alone would have found everything.
6. **Use one finding format with ids and statuses** (UNVERIFIED, CONFIRMED, REFUTED, APPLIED), and one report file per agent. The synthesis then becomes a merge.
7. **Plan an "apply approved patches" step.** The implementer correctly refused to edit instruction and configuration files on a teammate's request. Ask teammates for exact before/after patches up front, and have the lead apply them after the user approves.
8. **Keep an owner-decisions list separate from fixes.** Roughly half the findings needed a decision (layout, settings, commits, spec questions), not an edit.
9. **Audit the workflow as well as the content.** Most should-fix findings were about the team's own process: naming, ownership, review baseline, re-test and approval rules. Check these before the first real run.

## 10. Report index

- `work/audit/planner.md`: coverage, holes, open questions (P-01 to P-41)
- `work/audit/reviewer.md`: accuracy and spec-internal inconsistencies (R-01 to R-12, S-01 to S-10)
- `work/audit/tester.md`: mechanical checks, appendices of 54 fact checks and a glob test (T-01 to T-23)
- `work/audit/implementer.md`: hygiene, patch list, decisions (I-01 to I-14)

## 11. Applied after your approval (lead)

Decisions taken: `impl-<area>` names; `bits/samples/` and `bits/tests/`; shared `.claude/settings.json`; `.gitignore`, `.gitattributes` and README created; all confirmed fixes applied; open spec questions logged unanswered; one local commit.

| Area | Change |
| --- | --- |
| Names and ownership | `impl-<area>` (agent type `implementer`) in `CLAUDE.md`, `SKILL.md`, `tester.md`, `reviewer.md`; `impl-bits` and `impl-deploy` added; `work/reports/` ownership added for implementer and tester (P-01, P-02, P-04) |
| `bits/` | Split into `bits/samples/` (impl-bits) and `bits/tests/` (tester) in the layout, ownership lines, role files and `testing.md` (P-03) |
| Settings | New shared `.claude/settings.json` with the agent-teams flag; `settings.local.json` untracked and gitignored; wording fixed in `agent-teams-reference.md` and `SKILL.md` (I-01) |
| Rules | `jobs-and-scans.md` retries; `config-and-cli.md` DSN split; `api.md` `/api-tokens`, login and logout, unsupported "omits deleted" sentence replaced by an Open spec question; `testing.md` and `evaluator.md` coverage path, fixture list and test locations; citations in `security-invariants.md`, `packaging-and-units.md`, `web-ui.md`, `runner-sandbox.md`; rotation window question closed; two duplicate open questions turned into pointers; bare `rules/...` paths now `.claude/rules/...` |
| CLAUDE.md and SKILL.md | Heartbeat and out-of-scope citations; plan pointer replaced by the inline milestone order; the `~/Downloads` copy step removed |
| Repo files | `.gitignore`, `.gitattributes` (`eol=lf`), `README.md`, `work/open-questions.md` (nine owner questions, unanswered) |
| Reference guide | "n/a per docs" cells reworded; the three gotchas from this run added to section 15 |

Not applied (unverified judgement calls, left for you): P-05 re-test step, P-06 review baseline, P-07 second approver, P-08 who updates rules after a decision, P-37 loader fallback, R-02, R-08, R-11, P-22 to P-27, P-32, P-40, T-16, T-20. The nine spec-owner questions in `work/open-questions.md` remain open.
