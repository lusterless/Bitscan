# Agent Teams: Workspace Audit Summary and Patterns

Date: 2026-10-19. Goal given to the team: clean up the workspace, apply the round-2 fixes that are right, and make sure every document is accurate and has no holes. The audit ran in three rounds with the four roles in `.claude/agents/`. Each role's merged report is `work/audit/<role>.md` (sections Done, Open items, Decisions); the per-round originals are `work/audit/archive/round1-<role>.md`, `round2-<role>.md` and `round3-<role>.md`, plus `round3-brief.md`; that folder is history and is ignored unless someone asks for it. Spec questions and process decisions live in `work/open-questions.md`. Nothing is committed.

## 1. Result in one table

| Item | Outcome |
| --- | --- |
| Round 1 | Independent audit, about 100 findings, large overlap between agents. All confirmed fixes applied after your approval and committed as 01748b2 |
| Round 2 | Cross-check of the applied fixes plus each agent's spec slice. Tester stopped to wait for the user and delivered nothing |
| Round 3 | Tester's missing report delivered, every UNVERIFIED round-2 claim ruled on, confirmed fixes applied (not committed), spec-silent items logged as questions |
| Applied in round 3 | 50 fix ids in 27 files (about 80 hunks); 44 `**Open spec question:**` markers and 35 pointers in `.claude/`; `git diff --stat` 33 files, +656/-662 on the final tree (includes the merged reports and `work/open-questions.md`) |
| Verification | 328 citations in the first scope and 469 in the full scope, none missing; front matter valid in 21 of 21 files; fences balanced; all files LF; no stale `lead` addressing; every pointer resolves to an agreed entry; the reviewer found no applied line stricter than the spec |
| Left for you | 33 numbered spec-owner questions (#19 withdrawn), 12 process decisions PD-1 to PD-12, spec-internal inconsistencies S-01 to S-16, the stale memory file, `settings.local.json`, and the commit. See section 8 |

## 2. How the team ran (lead)

- **Team:** `planner`, `reviewer`, `tester`, `implementer`, now registered as real agent types (the restart fixed the round-1 problem). The lead is addressed as `main`.
- **Lenses:** planner = coverage and holes in SR and TS §4; reviewer = accuracy against the spec in TS §3.3 to §3.7 and §8.1 to §8.4; tester = TS §5 to §7 and everything mechanical; implementer = TS §1, §2, §3.1, §3.2, §8.5 to §8.7, hygiene, and the only writer of the documents.
- **Shared brief:** `work/audit/archive/round3-brief.md` fixed five things: the classes FIX / ASK / DECIDE / REJECT / DUP; a single writer per file; "nothing is applied until a second agent confirms it against a quoted spec line"; the message protocol; one finding format.
- **No SendMessage tool:** none of the four role types had it. Every agent said so and wrote its rulings into a "Rulings for implementer" table in its own report. The lead relayed requests (it has SendMessage), resumed finished agents with new instructions, and the implementer polled the report files. A confirmed line in a teammate's file counted as the second confirmation. This worked, but the planner's patch batches only reached the implementer after the lead read its report and relayed them.
- **Cost:** about 280k (planner), 320k (reviewer), 282k (tester) and 339k (implementer) subagent tokens by the end of verification; the first pass of each took 14 to 58 minutes. The implementer was the long pole.
- **Resumes:** a completed agent resumes when it gets a message, with its transcript. The lead used that for the planner's second pass, for post-apply verification, and for the merge task.
- **Harness note:** one tool result (the implementer's last report) was tagged as matching an instruction-shaped pattern ("settings-json"). It only quoted `settings.local.json` text; nothing was acted on.

## 3. Planner (coverage and holes)

- **Round 3:** ruled on all 26 round-2 items and the round-1 leftovers; 18 FIX (5 already in the tree, the rest applied after confirmation), 18 new ASK entries #10 to #27, 11 process decisions, 4 REJECT, 10 DUP. After the other rulings came in: #19 withdrawn, #13, #15 to #17, #20 to #23, #25, #27 to #33 agreed.
- **Owns `work/open-questions.md`:** reworked into numbered questions with a status column, a table of all 44 marker lines in the rules, the TS §8.5 questions, PD-1 to PD-12 and the spec-internal list. A fresh grep matched the table exactly.
- **Findings worth knowing:** `bit-format.md` said the display name "is never stored" although `scan_result.plugin_name_snap` stores it (fixed). The start-up steps in `importer.md` were numbered in an order TS §4.2 never gives (fixed; order is question #27). Rules were missing: cancel also cancels dispatched and running jobs, the "≤ `job_pull_seconds` + 30 s" pickup bound, re-evaluation needs a TOTP session and is audit-logged, `eval_detail`, list filters and the package click-through (all added).
- **Own mistakes corrected:** it told the implementer to append markers mid-bullet (tester caught it, R3-T-01); it first kept `nan`/`inf` in question #13 against the reviewer's trim (both versions choose no behaviour).

## 4. Reviewer (accuracy against the spec)

- **Diff review:** every changed hunk of the uncommitted round-2 edits was checked against the spec. Three new marker lines overclaimed and were rewritten: `bit-format.md` #2 (only BIT010's "missing" half is unreachable), `agent.md` #4 (wrong section for the spool limit; no invented `log_level` clash), `api.md` #5 (TS §8.4 does name `/healthz` and `/readyz`).
- **Rulings:** R2-R-08, R2-R-12 and R2-R-13 became questions #29 to #31; R2-R-07 split (the spec's `error` field is a FIX, "resend to a restarted runner" is a question #28); the second approver and the test commands are process decisions because TS §8.2 and §8.3 name no test runner. Its own round-2 command text was therefore withdrawn.
- **Fixes it authored (12):** a `serve` subcommand fix, the cgroup v2 statement, the OS matrix, the plugin-socket accepted risk, viewers never receive `stdout` or `stderr`, the job-state transitions, and similar.
- **Last pass:** all applied lines VERIFIED; the invariants in `security-invariants.md` were restated more exactly, not weakened. It narrowed one implementer line: "with a new enrolment token" applies only to `token_revoked` and `token_expired` (TS §3.2 step 8), not to `enrollment_rejected`.
- **Spec-internal inconsistencies for the owner:** S-01 to S-16 (six new in round 3, for example TS §4.3 vs SR §3.6 on a revived policy's version, and the `evaluate()` signature vs its own ERROR cases).

## 5. Tester (mechanical verification)

- **Round 2 delivered late:** hole-hunt of TS §5 to §7 and every "Tests" line against TS §8.3: eight fixes (error `type` values on agent routes, schema owner and `USAGE` grants, enrolment-token create and revoke, ten "Tests" lines with sources, and others) and two questions (#32 package type-ahead has no route; #33 whether the manager recomputes `list_sha256`).
- **Mechanical results (final tree):** 79 of 79 round-3 spec quotes and all round-2 quotes exist at their cited lines (three are close paraphrases); no `lead` or `implementer-<area>` addressing left; markers each on their own line; `*.preseed`, `install.env` and `settings.local.json` ignored with no tracked file newly ignored.
- **Experiments:** in a throwaway repo, `* text=auto eol=lf` turned CRLF into LF in committed CSV and stdout fixtures, while a file with a lone CR was treated as binary and kept. That settled the implementer's round-2 question: CRLF normaliser inputs must be built in code or the fixture paths marked `-text` (the choice is PD-8).
- **Found:** four markers embedded mid-bullet (R3-T-01), stale line numbers in the marker table (R3-T-02), missing TS/SR prefixes on some citations (R3-T-03). All fixed and re-verified.
- **Lesson on itself:** in round 2 it paused for the user and blocked the exchange. The brief's "never stop for the user" fixed that.

## 6. Implementer (applier and hygiene)

- **Authorised exception:** `work/decisions.md` records that for this task the implementer is the single writer of `.claude/**`, `README.md`, `.gitignore`, `.gitattributes` and `docs/agent-teams-reference.md`. Round 1 showed it declines such edits otherwise.
- **Applied:** the 9 ready-list fixes (offline_sweep timeouts, NTP prerequisite, token rotation replacement, purge and no deregistration call, TS §8.5 caveats, Sandbox gate, `bits/samples/` vs `bits/tests/`, CRLF fixtures, audit statuses); 14 planner, 12 reviewer and 7 tester ids; 5 hygiene items (build outputs in `.gitignore`, README pointer to the open questions, layout block with `docs/spec/` and `work/`, glossary terms in CLAUDE.md, a stray `lead` in the reference guide); 32 marker lines and pointers; later the last three appends.
- **Reverted on a ruling:** `agent.md:34` ("in the results `error` field") was applied, then reverted because it would pre-answer question #28.
- **Hygiene:** no stale paths, no empty or CRLF files, balanced fences, every rule reference resolves.
- **Outside the repo:** it did not edit the user's memory file (stale "Go 1.22"; the rotation line is right only for the default token lifetime). That is PD-11.

## 7. Where the agents agreed and where a peer corrected another

| Issue | Outcome |
| --- | --- |
| offline_sweep also applies the 24 h never-started and 30 min inventory timeouts | reviewer and planner found it independently; applied |
| NTP prerequisite, rotation replaces `token`/`issued_at`/`expires_at`, purge has no deregistration call | confirmed by two or three agents; applied |
| `api.md` stated the API-token revoke question as fact | reviewer and planner converged on a marker (#8) instead |
| Run-time rule `agent.md:34` | planner rejected, reviewer accepted, implementer reverted |
| Planner's mid-bullet markers | tester caught, implementer split, planner owned the error |
| Reviewer's overclaiming markers (#2, #4, #5) | reviewer corrected its own round-2 text during the diff review |
| Tester's "all values agree" in round 1 missed invented rule text | planner flagged in round 2; round 3 added the "does the spec say this?" check for words like "never", "only", "must" |

## 8. Decisions and work that need you

1. **Commit:** everything since 01748b2 is uncommitted (`.claude/**`, README, `.gitignore`, `.gitattributes`, `docs/agent-teams-reference.md`, `work/`).2. **Spec owner:** 33 numbered questions (#19 withdrawn). The ones that block the most behaviour: #12 (`evaluate()` has no input for runner errors or oversize output), #14 (TS and SR disagree on a revived policy's version), #18 (does disabling a policy cancel its queued jobs), #28 and #29 (the agent-runner contract), #33 (`list_sha256`).
3. **Process decisions PD-1 to PD-12:** re-test after CHANGES_REQUESTED, review baseline, second approver, who updates markers, test commands in CLAUDE.md, a PLAN task, loader fallback, CRLF fixture mechanism, build output paths, `settings.local.json`, the memory file, and the build files with no loading rule.
4. **Spec-internal inconsistencies S-01 to S-16:** reported to the owner, never edited.
5. **Outside the repo:** the memory file `bitscan-project-decisions.md` is stale (PD-11).

## 9. Patterns for running agent teams (lessons, updated)

1. **Start in a fresh session after creating `.claude/agents/`.** Mid-session definitions do not load. If it happens, use general-purpose agents and tell each to read its role file first.
2. **Address the lead as `main`** in every spawn prompt and role file.
3. **Do not assume teammates can message each other.** The role types here had no SendMessage tool. Design for it up front: a shared brief file, one "Rulings for implementer" table per report that others poll, and the lead as relay and resumer. Check the tool list before promising a protocol.
4. **A completion notice is not a FINAL, and a finished agent is not gone.** Messages resume it with its transcript, so late rulings can be routed to it. Require an explicit FINAL text and wait for all of them.
5. **One writer per file.** The implementer as the only writer of docs, the planner of the question list, each agent of its own reports, avoided every edit conflict across about 80 hunks.
6. **Two-key rule for edits.** "Nothing is applied until a second agent confirms against a quoted spec line" caught real errors (overclaiming markers, an invented sentence about recomputing a hash, a result-field rule that pre-answered an open question).
7. **Default spec-silent behaviour to a question, not a rule.** Most round-2 proposals chose behaviour the spec leaves open. Marker lines (`**Open spec question:**` with a pointer) keep implementers from building it.
8. **Split mechanical from semantic checking.** The tester's greps, node checks and throwaway-repo experiments found structure problems the reviewer's reading missed, and the reviewer found overclaims no grep can.
9. **Never let an agent stop for the user.** The tester's round-2 pause cost a round. Tell agents the user is unreachable and to route needs through the lead.
10. **Keep decisions apart from fixes.** About half the findings needed a decision. A numbered list with a status (agreed, withdrawn) and a table of marker lines keeps the two from drifting; regenerate the table by grep after every batch.
11. **Merge after the run.** Per-round reports are useful while the run is live and noise afterwards. Merge them into one report per role with Done, Open items and Decisions, and move the per-round originals to `work/audit/archive/`, which agents ignore unless asked.
12. **Audit the workflow as well as the content.** Many should-fix findings were about process (naming, ownership, review baseline, re-test and approval rules).

## 10. Report index

- `work/audit/planner.md`, `reviewer.md`, `tester.md`, `implementer.md`: merged reports (Done, Open items, Decisions).
- `work/open-questions.md`: numbered spec questions, marker table, TS §8.5 questions, PD-1 to PD-12, spec-internal inconsistencies.
- `work/decisions.md`, `work/status.md`: the lead's decisions and status.
- `work/audit/archive/`: history only (`round1-<role>.md`, `round2-<role>.md`, `round3-<role>.md` and `round3-brief.md`). Do not read it unless asked.
