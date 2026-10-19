# Round 3, implementer: apply confirmed fixes, hygiene, slice hunt

Single writer of `.claude/**`, `README.md`, `.gitignore`, `.gitattributes` and `docs/agent-teams-reference.md` for this task (work/decisions.md, 2026-10-19). Nothing committed.

**Tooling.** I have **no SendMessage tool**. I could not send or receive messages. I took the teammates' `APPLY`/`CONFIRMED`/`REJECTED` lines from their report files (round3-planner.md §E–§F, round3-reviewer.md §0/§3/§4b, round3-tester.md §4, round2-tester.md) and from main's two relayed messages. This file is my `APPLIED:` and `IMPLEMENTER-DONE` channel. main relays it.

Format: `R3-I-## | class | file:line or spec § | what | spec quote (§, line) | patch | status`

## 1. My findings (slice TS §1, §2, §3.1, §3.2, §8.5–§8.7, plus hygiene)

R3-I-01 (rules on R2-I-13) | FIX | packaging-and-units.md:46 | Install runbook lacks the cloned-image fix | TS §3.2 step 9, L192 "The fix is to regenerate `/etc/machine-id` on the clone" | reviewer's trimmed text | APPLIED (confirmed by reviewer §4; tester §2 quote CONFIRMED)
R3-I-02 (rules on R2-I-14) | FIX | packaging-and-units.md:46 | Runbook lacks the pinning recommendation | TS §3.2 L194 "Pinning is optional but recommended" | reviewer's text | APPLIED (reviewer §4)
R3-I-03 (rules on R2-I-17) | FIX | config-and-cli.md:14 | Vault token file can hold an AppRole secret | TS §8.6 L1312 "File holding the manager's vault token (or AppRole secret)" | "`%d/vault_token`; the manager's vault token or AppRole secret" | APPLIED (reviewer §4)
R3-I-04 (leftover site of R2-P-05) | FIX | docs/agent-teams-reference.md:219 | The spawn-prompt checklist still said "send findings to `lead`", an address that does not exist (§15 of the same file says `main`) | not a spec item; agent-teams-reference.md §15 | "send findings to the lead, addressed as `main`" | APPLIED (author planner R2-P-05, confirmed by me in round 2); tester to VERIFY (M6 scanned `.claude/` only)
R3-I-05 | FIX (nit) | packaging-and-units.md:51 | The migrate unit has no `[Install]` and the manager unit only orders after it (`Before=`), so nothing starts it unless the runbook does. The rule omits "the upgrade runbook starts it first" | TS §8.7 L1346 "(`systemctl start bitscan-manager-migrate`) … `bitscan-manager-migrate.service` is ordered before the manager service; the upgrade runbook starts it first." | append to :51: "The upgrade runbook starts it first (`systemctl start bitscan-manager-migrate`) (TS §8.7)." | UNVERIFIED (reviewer to rule)
R3-I-06 | FIX (nit) | agent.md:25 | Step 3 says "log that the host must be re-enrolled"; the spec adds "with a new enrolment token" | TS §3.2 step 8, L191 "logs that the host must be re-enrolled with a new enrolment token" | append " with a new enrolment token (TS §3.2 step 8)" | UNVERIFIED (reviewer to rule)
R3-I-07 (rules on R2-I-02) | hygiene | .gitignore:9–29 | Build and test outputs. Applied the layout-independent subset only: `coverage.xml`, `*.egg-info/`, `web/coverage/`, `*.tsbuildinfo`, `npm-debug.log*`, `*.buildinfo`, `*.changes`, `*.test`, `coverage.out`, `*.coverprofile`, plus a comment that the OpenAPI client stays committed. The debhelper and wheel paths depend on PD-9 and are held | none | — | APPLIED; reviewer §0 VERIFIED ("`*.test` does not match `*.test.ts`, and the OpenAPI client stays tracked"). Self-check: `git check-ignore` hits no tracked file; `web/src/api/generated/client.ts`, `*.test.ts(x)`, `*_test.go`, `bits/tests/*.bit`, `*.gz` are not ignored
R3-I-08 (rules on R2-I-19/R2-R-19) | report | auto-memory `bitscan-project-decisions.md` (outside the repo) | (a) "User installs Python 3.12, Go 1.22, Docker natively" is stale: CLAUDE.md:83 and TS §2.1 L107 say "a currently supported release" (= PD-11). (b) "Agent token: 1-year lifetime, self-rotation in last 30 days (the 19 Oct spec now says the same)" is true only for the default TTL; TS §3.2 L190 rotates at `issued_at + max(TTL − 30 days, TTL ÷ 2)` with TTL 60–730. MEMORY.md's index line is now correct ("not src/") | TS §2.1 L107; §3.2 L190 | user or main edits the memory file; I did not | reported to main
R3-I-09 (rules on R2-I-11) | DECIDE | `.claude/settings.local.json` (ignored, on disk) | Repeats the `env` flag of `settings.json` and would override it | — | = PD-10 | report only
R3-I-10 | DUP | TS §3.1 State row / §3.6 `state_dir` comment omit `issued_at`/`expires_at` | spec-internal | = S-11 (reviewer) | — | in open-questions §5

Slice checked, no further gap: G1–G6 and §1.2 out of scope; §1.3/§1.4 terms (now in CLAUDE.md:12); §2.1 components; §2.2 principles; §2.3 token table and both flow tables; §3 intro (cgroup v2, now R3-R-06); §3.1 every row and the postinst steps; §3.2 steps 1–9 and Transport; §8.5 (all three questions now carried: #10, #11, CIS own question); §8.6 variables, settings and patterns; §8.7 service, folders, credentials, CLI, units, upgrade order (apart from R3-I-05).

## 2. Applied changes (one line each; line numbers after the last edit)

READY list (two confirmers from round 2):
- R2-R-05/R2-P-26: jobs-and-scans.md:31 offline_sweep also fails never-started (24 h) and inventory (30 min) jobs. "atomically"-style additions avoided.
- R2-R-06/R2-I-20: packaging-and-units.md:46 NTP prerequisite in the runbook bullet; agent.md:33 "Hosts must be NTP-synced; the manager alerts on clock skew over 5 minutes (TS §3.3)". Reviewer's "the install runbook checks it" trimmed.
- R2-R-10/R2-I-16: agent.md:18 state list adds `issued_at`/`expires_at`; agent.md:26 replace `token`, `issued_at`, `expires_at` on rotate. "atomically" dropped (not in the spec).
- R2-I-15: packaging-and-units.md:44 host goes `offline`, decommissioned under TS §3.3; "None of the agent endpoints in TS §6.1 deregisters a host". My own draft "so maintainer scripts call no manager endpoint" was trimmed as inference.
- R2-I-12: bit-format.md:16 (one Family, TS §8.5 quote), evaluator.md:13 (normalisation caveat).
- R2-R-09: bit-format.md:63 Sandbox on the Tests line.
- R2-P-02(b)/R2-R-03: bit-format.md:52–54 heading `bits/samples/` and the fixtures sentence; :61 `bits/samples/`.
- R2-P-25/R2-I-04: testing.md:18 CRLF in-code literals or `-text`; .gitattributes:3 `*.gz binary`. The `-text` paths are not chosen (PD-8).
- R2-R-17/-18/-19: implementer.md statuses fixed and a status note added; round2-implementer.md statuses appended with "-> round 3: …".

Lead-listed hygiene (reviewer §4 FIX "accurate"):
- R2-I-10/P-32: CLAUDE.md:78–79 `docs/spec/` and `work/` in the layout block.
- R2-I-19/P-40: CLAUDE.md:12 TS §1.3/§1.4 terms (Policy/profile, Family, Plugin, display name).
- R2-I-06: README.md:19 row for `work/open-questions.md`.
- R2-I-02: .gitignore (R3-I-07).
- R3-I-04: docs/agent-teams-reference.md:219.

Planner batches:
- A1 (= R3-R-05): auth-and-users.md:22 #1; api.md:45 #9. A1 #7 cross-reference (tester and reviewer confirmed): config-and-cli.md:40.
- A2: bit-format.md:16 #10; evaluator.md:13, :14 #11.
- A3: evaluator.md #12 (merged planner and reviewer NEW-E wording); importer.md:54 #14; jobs-and-scans.md:17 #18; config-and-cli.md:15 #24 plus audit-and-alerts.md:19 cross-reference; enrolment-and-tokens.md:25 #26.
- A4 (R3-P-15 + R3-P-41, reviewer §0/§4b): importer.md:36–40 start-up split into the ordered TS §4.1 steps and the unordered TS §4.2 steps, plus the #27 marker.
- A5: R3-P-14 evaluator.md "Host compliance score"; R3-P-16 jobs-and-scans.md:18 pickup bound; R3-P-17 evaluator.md re-evaluation route, TOTP, audit-logged, `policy_version`, `reevaluated_by`; R3-P-20 jobs-and-scans.md cancel of dispatched/running; R3-P-21 evaluator.md `eval_detail` (**reviewer's trimmed text**, replacing the planner text I had first applied); R3-P-22 api.md:40 list filters (tester); R3-P-23(b) web-ui.md:26 click-through (tester, reviewer); R3-P-40 bit-format.md:24 display name / `plugin_name_snap`; R3-P-12a bit-format.md:18 "Lengths are in characters"; R3-P-50 jobs-and-scans.md scan never takes `dispatched`/`expired`.
- Markers (§F texts): #13 evaluator.md (placed after the Operators list, not inside it, so the sub-list stays intact); #15, #16, #17 bit-format.md; #20, #21, #23 importer.md; #22 jobs-and-scans.md; #25 enrolment-and-tokens.md.

Reviewer batch:
- REJECTED lines fixed: R3-R-01 bit-format.md #2; R3-R-02 agent.md:17 #4; R3-R-03 api.md #5.
- R3-R-04 api.md:38/:39 marker on its own line. R3-R-06 runner-sandbox.md:33 the agent reports `runner_unavailable`. R3-R-07 runner-sandbox.md:57 OS matrix. R3-R-08 enrolment-and-tokens.md:47 Load. R3-R-09 packaging-and-units.md:60 `serve`. R3-R-10 security-invariants.md:27 "viewers never receive `stdout` or `stderr`" (tester and planner: not a weakening). R3-R-11 security-invariants.md:10 and agents/implementer.md:28 "owner decisions"/"forbidden by TS §3.3 and §6.2" (every "Never add" kept). R3-R-12 jobs-and-scans.md:23 job-state transitions, reviewer's text exactly.
- R2-R-07 FIX half: agent.md:43 `spool_overflow` in the results `error` field. R2-R-11 web-ui.md:29 runner helpers. R2-R-16 security-invariants.md:21 plugin-socket accepted risk.
- Markers #28, #30 agent.md; #29, #31 runner-sandbox.md (reviewer §3 texts).

Tester batch (planner §F confirmed):
- R2-T-01 api.md:31 agent-route error types plus 409 `policy_managed_on_server`. R2-T-02 database.md:28 schema owner and `USAGE`. R2-T-03 enrolment-and-tokens.md:14 creates and revokes. R2-T-04 web-ui.md:27 #32. R2-T-05 inventory-and-packages.md:17 (invented "Recompute … same as the agent" removed), :18 #33, agent.md:48 "the manager computes it identically" removed. R2-T-06 (a)–(j) sources on ten Tests lines (api, database, audit, config, jobs ×2, auth, evaluator, importer, inventory ×2, testing ×3). R3-T-01 four embedded markers split (auth-and-users, bit-format, enrolment-and-tokens as a sub-bullet, importer).

Reverted after a ruling:
- R2-R-07 agent.md:34 "(in the results `error` field, TS §6.5)": applied, then **reverted** after the planner REJECTED it (§F: it chooses the answer #28 asks for).
- An inventory-transition clause I had merged into R3-R-12 was **removed**: it is R3-P-51, which waits for the reviewer (main's instruction).

## 3. Held (not applied)

- R3-P-51 (jobs-and-scans.md:23 inventory transitions): waits for the reviewer; main routes it.
- R3-I-05, R3-I-06: mine, UNVERIFIED.
- #19: withdrawn, no marker.
- PD-1 to PD-12: DECIDE items for the user (includes PD-8 `-text` paths, PD-9 build paths, PD-10 settings.local.json, PD-11 memory file).
- R2-I-09: REJECTED (agent-teams-patterns.md is the lead's file).

## 4. Hygiene results

- Stale paths: no `.CLAUDE.md`, `~/Downloads`, `~/.claude/plans`, `docs/specs`, `docs/schema` or bare `rules/` in scope. `src/` appears only as `web/src/` (layout) and the upstream example at agent-teams-reference.md:208 (kept, I-13).
- Addressing: no `` `lead` `` and no "message lead" left in `.claude/`, README or agent-teams-reference.md (CLAUDE.md:114 says "message the lead (teammates address it as `main`)", on purpose).
- Links: every `.claude/rules/…md` reference resolves; no relative Markdown links in scope.
- Files: no empty files; no CRLF in tracked files; fences balanced; every rule, agent and skill file starts with front matter.
- Untracked: only `work/` files owned by the team (round-2/3 reports, status.md, decisions.md). Ignored: only `.claude/settings.local.json` (PD-10).
- Markers: 44 `**Open spec question:**` lines in `.claude/`, each on its own line. Pointers: #1–#18 and #20–#33 each appear and resolve to an entry marked **agreed** in work/open-questions.md. No pointer to #19 and no `#NEW` left.
- `git diff --stat`: 32 files changed, 408 insertions(+), 190 deletions(-) (includes the teammates' files under `work/`).
- Consistency: CLAUDE.md, README.md, SKILL.md and the four role files agree on ownership (`bits/samples/` vs `bits/tests/`), `impl-<area>` naming, `main` addressing and the settings location. Remaining process gaps are PD-1 to PD-7.

## 5. Exchange log (no SendMessage tool; file-based)

- ← main (spawn): READY list, hygiene list, slice. Done (§2).
- ← main (relay 1): apply A1, A2 and A3; hold the #7 pointer, A4 and A5 until rulings appear; treat a CONFIRMED line in a report file as the second confirmation. Done; A4/A5 applied only after reviewer §0/§4b and tester §4 confirmed them.
- ← main (relay 2): apply every confirmed item, except the agent.md:34 part of R2-R-07, #19 and R3-P-51. Done; agent.md:34 reverted and the R3-P-51 clause removed.
- ← planner (round3-planner.md §E, §F): A1–A5, the marker texts and the rejection of agent.md:34. All applied as listed; the #13 placement was adjusted to keep the Operators sub-list intact.
- ← reviewer (round3-reviewer.md §0, §3, §4, §4b): rulings on R2-I-02/-06/-10/-13/-14/-17/-19 (FIX or VERIFIED), R2-I-09 REJECT, R3-R-01..12, marker texts #28–#31, the trimmed R3-P-21. All applied.
- ← tester (round3-tester.md §4, round2-tester.md): confirmed R3-P-22, R3-P-23(b), the #7 pointer, R3-R-04/-05/-07/-08/-09/-10; R2-T-01..06 and R3-T-01 authored. All applied after the planner confirmed.
- → reviewer: `APPLIED:` everything in §2. Please VERIFY, rule on R3-I-05 and R3-I-06, rule on R3-P-51, and check R3-R-12 (reviewer's exact text) and the R2-R-11 placement (after the policy-states bullet, not directly after package search).
- → tester: `APPLIED:` everything in §2. Please VERIFY mechanically, including docs/agent-teams-reference.md:219 (outside your M6 scope) and the 44 markers and 32 pointers.
- → planner: the part-2 marker table in work/open-questions.md needs a fresh grep (44 markers now). PD-8: `*.gz binary` is applied; the `-text` choice is open.
- → main: R3-I-08 (memory file), PD-10, and `IMPLEMENTER-DONE` to relay. No further APPLY is queued from my side apart from R3-P-51 and R3-I-05/-06.

**IMPLEMENTER-DONE**: my queue is empty apart from the items in §3, which wait for rulings. Final VERIFIED replies from the reviewer and tester can only come through their files after this one.

## 6. Counts

- FIX applied: 80 lines or hunks across 27 files (9 READY ids, 5 hygiene ids, 14 planner FIX ids, 12 reviewer ids, 7 tester ids, 3 of mine). 32 ASK markers or pointers added or fixed (#1, #7 cross-ref, #9–#18, #20–#33).
- ASK logged by me: 0 new (my slice questions were already #6, #24, #26).
- DECIDE: 2 of mine (= PD-9, PD-10).
- REJECT: 1 accepted against me (R2-I-09); 1 of my applied lines reverted (R2-R-07 agent.md:34, a reviewer patch).
- DUP: R3-I-10 (= S-11), R3-I-08(a) (= PD-11).
- UNVERIFIED (mine): R3-I-05, R3-I-06.
