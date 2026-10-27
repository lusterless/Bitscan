# Status (lead)

Docs audit (rounds 1 to 3): complete. Delivery plan approved by the user (M0 to M8, one phase at a time; the user approves each phase breakdown and exit gate). Nothing is committed.

## Roadmap (reordered 2026-10-20, see decisions.md)
M0 scaffolding (done, PR #1 green) → M1 DB and audit core → M2 auth core → M3 agent API and scheduler (inventory) → M4 Go agent and pre-release `.deb` → M5 minimal host UI and package search → M6 first-release gate (agent heartbeat and `os_info` end to end) → M7 compliance catalog → M8 evaluator → M9 scan engine → M10 agent runner and sandbox → M11 results, re-evaluation, end-to-end. Next: planner breaks down M1; the lead brings the breakdown to the user for approval before any code.

## M3 agent API and scheduler (inventory only): PLANNING (2026-10-22)

Branch `m3-agent-api` from main `6ff2b36`. Phase A: breakdown delivered by `planner` and checked by the lead (2026-10-23): REQ-060 to REQ-090, TASK-048 to TASK-081, TP-M3-00 to -35, 14 waves, no migration, gates G30 to G34 new, mutation table CHK-M3-320 to -374. **Approved by the user 2026-10-23** (all recommended answers; #62 10-minute grace, #70 viewer metrics, PD-24 one route task per wave; `work/decisions.md`). Phase B started: `impl-manager`, `tester`, `reviewer` spawned for W1.

| Wave | Tasks | State |
| --- | --- | --- |
| W1 | TASK-048 to 058; tester TP-M3-00, -01 | All 11 TEST PASS (053 after revision 1). REVIEW APPROVED: 049, 050, 052, 053 (round 2), 054, 055, 056, 057, 058. TASK-050 has the user's second approval. TASK-051 APPROVED after revision 1 (fresh heartbeat for `online`). TASK-048 APPROVED after revision 1 round 3 (plain `$ref` to `RawValue`, NaN/Infinity refused), with the user's second approval. **W1 complete (2026-10-23).** |
| W2 | TASK-059 to 062 | **Complete (2026-10-23)**: all four TEST PASS and REVIEW APPROVED; 060 (decoder) approved with one memory nit carried to M6. Earlier notes: | 061 TEST PASS, REVIEW APPROVED; 062 TEST PASS, REVIEW APPROVED (nit kept: a no-op PATCH still alerts, which errs toward more alerts); 059 APPROVED with revision 1 (old token capped at `last_rotation_at` + 30 days) and the user's second approval; 060 (decoder) started. Session restarted 2026-10-23 ~10:45; impl-manager, tester and reviewer resumed |
| W3 | TASK-063 to 066 | 063 APPROVED with the user's second approval. 064 APPROVED (revision 1: alert slot only on commit). 065 APPROVED. 066 APPROVED (revision 1) with the user's second approval. **W3 complete.** with `tester-b` (the first tester's context filled up; replaced 2026-10-23) |
| W4 | TASK-067 to 069 | **Complete**: 067 APPROVED after r1 (zone dropped, shared peer normaliser incl. two M2 auth files) with the user's second approval; 068, 069 APPROVED |
| W5 | TASK-070, 071 | 071 APPROVED after r1 (stop flag; SIGTERM 4 s with the DB down). 070 built with r1 (new/re-enrol twin case), in TEST queue |
| W5b | TASK-082 (new, user-ordered) | after 070: non-JSON bodies count toward the enrol and sign-in limits |
| W5/W5b/W6 | TASK-070 r1, TASK-082, TASK-072, TASK-048 r2 | **APPROVED** with the user's second approvals (2026-10-23) |
| W14 | TASK-080 README, TASK-083 (new, user-ordered: token before body on the heartbeat), TASK-081 web client | 080 built; 083 ordered; 081 after 079 approved |
| W7–W9 | TASK-073, 074, 075 | **APPROVED** with the user's second approvals (075 after revision 1) |
| W10–W13 | TASK-076 to 079 (078 with revision 1, `detail_text`) | **APPROVED** (077 with the user's second approval) |
| W9 | TASK-075 revision 2 (no false alert on simultaneous rotates; user-ordered) | being built; to `tester-f` |
| W14 | TASK-083 **APPROVED** with the user's second approval. TASK-080 r1 (README nits) awaiting the live walk-through and review; TASK-081 built, in TEST queue (tester-f). tester-e stopped (context full) after 073–083 | |
| — | Session restarted ~21:50; agents resumed | |
| All | TASK-048 to 083 | **All 36 APPROVED** (TASK-080 approved after the live walk-through, 107 requests, 0 deviations); every two-approval task has the user's second approval recorded; a one-sentence README edit (r2, rotation reuse) in progress |
| Gate | M3 exit gate | **PASS (2026-10-24, tester-h; closing review APPROVED, work/reviews/M3-gate.md).** G18 3959/3959, G5 99.52 % with `precision = 2` (gap found and fixed), all plants red. TASK-084 APPROVED. Gate fixes committed; PR to main authorised by the user. Earlier: tester-g stopped on a model rate-limit error at about 00:05 with G1–G4, G6, G16 green and most plants red; `tester-h` finishes it under the 2026-10-24 speed rules (xdist, Linux-only, targeted re-runs, one full run). TASK-084 awaits its TEST |
| M4 | Go agent and pre-release `.deb` | **Approved 2026-10-24** (REQ-091..112, TASK-085..107, 6 waves; amd64 only). M3 committed locally (4 commits, not pushed, `6fd593c`); `m4-agent` created from it in the worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m4`. W1 started: `impl-agent` (086–091), `impl-deploy` (092), `tester-m4` (TP-M4-00, -01). TASK-085 waits for the M3 gate. 2026-10-24 speed-up: Go 1.27.2 in WSL; `impl-agent-2` (094, 095, 104) and `tester-m4b` (091, 094, 095, deploy) added; W2/W3 released early; Debian 12 and the load/soak tests dropped or deferred (decisions). W1: 092 APPROVED, 086–091 built and in TEST; 096, 097 (r3) built; 093, 094, 095, 100 being built |
| M5 | Minimal host UI and package search | `planner-m5` planning in the M4 worktree (REQ-113, TASK-108 on), in parallel with M4 |
| M4 gate (2026-10-25) | **PASS (tester-m4, tester-m4b); M4 closing review APPROVED (Bitscan-m4/work/reviews/M4-gate.md).** All 23 tasks APPROVED, every two-approval task has the user's second approval. For the user before the M4 PR: (1) agent.yml and package.yml green on GitHub; (2) merge main properly at commit time (working-tree copies equal ff1fb4f) and re-run G18 on the merged head; (3) `.claude/CLAUDE.md` "Supported hosts" (user's edit; keep "with cgroup v2"); (4) the PR names the deviations: Debian 12 and arm64 dropped, #82 purge keeps a non-empty /etc/bitscan, the D-Bus lintian overrides; (5) idle cost CHK-M4-266: measure on the M6 VMs or with the deferred load tests? |
| M5 gate (2026-10-25) | **PASS (tester-m5); M5 closing review APPROVED (Bitscan-m5/work/reviews/M5-gate.md).** All 21 tasks APPROVED; the user's second look on 116, 118 and 119 is recorded. For the user before the M5 PR: (1) the browser walk-through CHK-M5-305 (checklist in Bitscan-m5/tests/m5/report.md); (2) web.yml green on GitHub; (3) UI times shown in UTC: confirm or ask for local time; (4) merge main properly, then re-run G18 on the merged head; (5) the PR names the trailing-slash change (M2/M3 307 → 404) and the #6 TS §2.3 deviation (static UI files served without a token); (6) the `.claude/CLAUDE.md` Supported hosts edit. Testing by risk applies from M6 on (decisions 2026-10-25). |
| Commit/PR run (2026-10-25, user out) | **Stopped: the auto-mode safety check began refusing git actions mid-run.** Done in Bitscan-m4: `f320e53` feat(agent) M4 product code; `7cf2c65` test M4 suites; `ef3539d` merge of origin/main (3ccf2b0) into m4-agent; the four M3 gate-fix files now come from main and equal ff1fb4f. **Left half-done:** the work/ and tests/ changes were stashed (`stash@{0}` "m4-work") for the merge and restored; the two conflicts (work/decisions.md, work/status.md) are resolved with the master copies, and every other stashed file was checked identical to the working tree. The stash is still kept as a safety copy (drop it with `git stash drop`). The M4 records (work/, tests/) are restored but not yet committed. **Not done:** the M4 records commit, M5 commits and merge, G18 on the merged heads, pushes, PRs, CI and merges. Nothing was pushed. Resume outside auto mode (default permission mode) or in a fresh session. |
| Drain 2 (2026-10-25) | User restarts the PC to enable Hyper-V | **State at drain:** M3 MERGED (PR #9, main `3ccf2b0`). M4 (worktree `Bitscan-m4`, branch `m4-agent`): fully approved 086–091, 098, 099 (incl. r1); reviewer-approved 092, 096, 097 (r4 tested); TEST PASS awaiting review 094 (r1), 095; in test: 085 (tester-m4, after 101 and 103), 093, 101, 103, 106 (tester-m4); 100 r1, 102, 104, 105, 107 (tester-m4b). TASK-100 needs the user's second approval. M5 (worktree `Bitscan-m5`, branch `m5-ui`, from 6fd593c): reviewer-approved 109, 110, 111 (110 r1 and 111 r1 re-test pending; TP-M5-03 re-run after TASK-114); in test 108, 112–124, 127 (tester-m5); 125 being built; 126 and 128 not started (128 after 085's approval). M5 second look for the user: 116, 118, 119. **On resume:** read each agent's resume note in decisions or status; respawn testers, reviewer and builders from the on-disk reports; merge main into m4-agent and m5-ui before their gates; create the two Ubuntu VMs (22.04, 24.04) on Hyper-V for M6. Open for the user: the Supported hosts line in `.claude/CLAUDE.md` (Debian 12, cgroup v2) |
| Drain | User paused the team 2026-10-24 ("drain") | Every agent was told to finish its current step, send its rows and notes, and take nothing new. On resume: (1) user enables Hyper-V and adds themselves to "Hyper-V Administrators", then restarts; (2) the lead re-reads status, decisions, reports and tests/m3 and tests/m4 report.md, then resumes or replaces the agents; (3) send the reviewer's TASK-100 pre-read nits to impl-deploy after tester-m4b's verdict: (E) track which keys appeared, so an empty `MANAGER_URL=` on upgrade is refused; refuse an existing `/etc/bitscan` that is not root-owned or is group- or other-writable; (4) TASK-099 built (to tester-m4); spec-silent point for the user and reviewer: rotate answers other than 429/403 (3xx, 400, 404, 409, 422) are retried at the next heartbeat with no extra wait. TASK-098 is next for impl-agent, after TASK-094's os-release reader is handed off. (5) impl-agent sent tester-m4 four golangci-lint findings in its test files (errcheck in `contract_test.go`, gosec G304 in `config_test.go`) with no reply yet; check they are fixed before the W1 verdicts. TASK-088 binds `token.json` to its token by SHA-256 (impl choice; reviewer to check). (6) impl-deploy drained: TASK-102 built (to tester-m4b); next TASK-105 (package.yml, Ubuntu 22.04 and 24.04, lintian overrides with reasons). TASK-105 must run the reproducibility double build on one pinned runner image (dpkg compression defaults differ between 22.04 and 24.04). TASK-106 must declare `var version string` in `cmd/bitscan-agent` for the build's `-X main.version` flag. (7) tester-m4 drained: its rows are written to tests/m4/report.md (CHK-M4-010..038). TASK-087 FAIL r1 (FIFO ca_file hangs `config.Load`); impl-agent fixes it first on resume, then tester-m4 re-runs that one subtest. TASK-086 and 088 have no verdict yet (plants pending; 088 has one re-run of a test bug). TASK-089, 090, 093 and 099 are queued. (8) impl-agent-2: TASK-094 and 095 are code-complete but IN PROGRESS (not handed off). Rulings needed: gosec G204 on `exec.CommandContext` in inventory/command.go (`//nolint` banned; a scoped exclusion in agent/.golangci.yml or the CI allow-list?); TASK-094 is ~430 lines vs 190 (keep it as one task, as for TASK-086, or split it?). (9) planner-m5: DRAFT saved (24 REQ, 21 TASK, 7 waves, #83–#86, PD-28–PD-30); what is left is in Bitscan-m4/work/plans/M5-progress.md. (10) tester-m4b drained: TASK-096 TEST PASS on 24.04 (rows and the test report written); on resume it runs 096 in an ubuntu:22.04 container, then TASK-091, 097 (r1–r3), 100 and 102. For TASK-100/107: check that a `string`-typed preseed of the token can't land in config.dat, and that the runbook preseed uses `password`. (11) tester-h drained: M3 gate rows and the TASK-084 report (PASS) written. Left on the M3 gate: the G5 plant proof (its run printed no coverage; harness issue; exact commands in tester-h's resume note: hg5c run, then the hm320 re-plant of CHK-M3-320, -321, -341 because `api/agent/dependencies.py` changed after their red). Then the reviewer's M3 closing review and TASK-084 review, the commit of gate fixes (test files: conftest, test_pg_harness, test_vault, test_serve_linux, test_readme_walk_linux), push and PR (ask the user). (12) open question to the user: `.claude/CLAUDE.md` still lists Debian 12 as supported, while the team builds for Ubuntu 22.04 and 24.04 only |
| W4–W14 | TASK-067 to 081 | not started | M3 carry-overs: contract fixtures, body caps on templated agent routes, metrics route in `HealthPath`, clock-skew alert, OpenAPI `/api/v1` paths and web client regeneration.

## M2 auth core and API plumbing: DONE (2026-10-22); exit gate PASS; committed (a70126f, e1e9ecb, 262288e, eb1d542, c473a85) and MERGED as PR #8 into main (merge commit `6ff2b36`, 2026-10-22). First CI run: manager/gates failed (9 errors in test_serve_linux.py: a test chmodded a shared key file to 0, hidden in WSL by root); fixed in tests only (c473a85, CHK-M2-305-ci8). Re-run: all five PR checks green; CI on main after the merge: manager, agent, web and units green. Branch `m2-auth-core` from main `5898951`

Brief: `work/m2-brief.md`. Breakdown approved by the user (decisions.md 2026-10-21): REQ-034 to REQ-059, TASK-023 to TASK-047, 10 waves, no schema change; all open questions answered as recommended, vault = OpenBao (Vault Transit API), sink = syslog+tls and https, `users reset-totp` kept. Second approval by the user for the auth tasks: TASK-028 to 031, 037 to 040 and 042 given 2026-10-22; TASK-041, 043 and 046 still to come.

| Wave | Tasks | Status |
| --- | --- | --- |
| W1 | TASK-023 deps, 024 create_app hardening, 029 TOTP core, 031 user repositories, 033 audit disk queue | all TEST PASS and APPROVED (2026-10-21) |
| W2 | TASK-025 runtime contract, 026 problem details, 028 passwords and tokens, 032 sink transport | all TEST PASS and APPROVED (2026-10-21) |
| W3 | TASK-027 request log, 030 OpenBao vault client, 035 alerts and metrics, 036 failed-token rate limit | all TEST PASS and APPROVED (2026-10-21) |
| W4 | TASK-034 audit shipper, 037 principal and auth dependencies, 042 user accounts, 044 health routes | all TEST PASS and APPROVED (2026-10-22; TASK-034 in round 2 after the fail-open fix) |
| W5 | TASK-038 sign-in and logout routes, 045 serve and README | all TEST PASS and APPROVED (2026-10-22; Linux 1367 passed, 0 skipped) |
| W6 | TASK-039 TOTP enrolment and replacement | TEST PASS (round 2) and APPROVED (round 2) (2026-10-22) |
| W7 | TASK-040 password change | TEST PASS and APPROVED (2026-10-22) |
| W8 | TASK-041 API tokens | TEST PASS and APPROVED (2026-10-22) |
| W9 | TASK-043 /users routes, 046 server CLI users commands | TEST PASS and APPROVED (2026-10-22; both on revision 1) |
| W10 | TASK-047 web client | TEST PASS and APPROVED (2026-10-22) |
| Gate | M2 exit gate (G1 to G6, G16, G18, G25 to G29) and the full security mutation table | PASS (2026-10-22): G18 1520 passed, 0 skipped, 99.32 %; every mutation-table row red; reviewer's closing review APPROVED (work/reviews/M2-gate.md) |

Test plan: tests/m2/test-plan.md, 260 checks (CHK-M2-001 to -349), written before the code.

Second approval by the user (TS §8.2, auth): complete: given 2026-10-22 for all twelve auth tasks (TASK-028 to 031, 037 to 043, 046).

## M1 database and audit core: DONE, merged to main 2026-10-21, branch `m1-db-audit-core`

M1 breakdown approved by the user; open questions #38 to #45 and PD-18 answered (decisions.md). Work is uncommitted after `ae6a6b4` (TASK-011 to TASK-015).

| Task | What | TEST | REVIEW |
| --- | --- | --- | --- |
| TASK-011 to TASK-015 | dependencies, config loader, `db migrate`, m0001, m0002, Debian version compare | PASS | APPROVED (committed `ae6a6b4`) |
| TASK-016 | m0003 scanning tables | PASS | APPROVED |
| TASK-017 | m0004 system tables | PASS | APPROVED |
| TASK-018 | m0005 privileges, view, seeds, partitions | PASS | APPROVED |
| TASK-019 | `db maintain` | PASS | APPROVED |
| TASK-019 | revisions 1 and 2: clock guard (a), (b) and partition gap check (c), both user-approved amendments to #44 | PASS (incl. mutations) | APPROVED |
| TP-M1-02 harness and follow-ups | PASS (tester-b re-run pending) | APPROVED |
| TASK-020 | audit append (hash chain) | PASS (unit, PostgreSQL, mutations) | APPROVED |
| TASK-021 | audit chain verifier | PASS (step 1 rev 1 and step 2, unit, PostgreSQL, mutations) | APPROVED |
| TASK-022 | CI forward-only, one-migration-per-PR gate | PASS (local; live GitHub check NOT RUN until the PRs are pushed) | APPROVED |

M1 lands as five stacked PRs, one migration each (user decision). When the PRs are opened, ask the user: merge method, making the `migrations` check required in branch protection (otherwise a red gate does not block a merge), and "require branches to be up to date". Clean full WSL run (CHK-M1-240-r2): 547 passed, 0 skipped, coverage 100 %, 0 leftover containers.

PR split (2026-10-20, plan `work/plans/M1-pr-split.md`): five local stacked branches built in the worktree `.claude/worktrees/m1-split`: m1-pr1 24bf548 (config, db migrate, m0001, harness, CI migration gate), m1-pr2 089eae0 (m0002, version compare), m1-pr3 7a40d67 (m0003), m1-pr4 17fe725 (m0004), m1-pr5 0b1a216 (m0005, db maintain, audit chain, README, records). Each head: static gates clean, Windows pytest 0 failed, local migration gate "1 added" against its own base. PR 5 tree equals the working tree. WSL run of each head with PostgreSQL (CHK-M1-242, 2026-10-21): PASS, 308/331/341/371/547 passed, 0 failed, 0 skipped, 0 leftover containers. Pushed 2026-10-21 and opened as stacked draft PRs: #2 (m1-pr1, base m0-scaffolding), #3 (m1-pr2), #4 (m1-pr3), #5 (m1-pr4), #6 (m1-pr5). 2026-10-21: live CI green on all five (5/5 checks each, incl. manager / migrations: CHK-M1-256 PASS). Merged in order with merge commits, each after its checks were green against main: #1 M0 (015c336), #2 (8b39ca5), #3 (c09034f), #4 (7bffd8b), #5 (25ea1c5), #6 (b1e99b8). main now equals the tested M1 tree (0 diff vs refs/m1-split/reference). Required checks are not available on this plan (decisions.md), so checks stay advisory.

Team restarted 2026-10-20 on claude-opus (all roles): tester (finish TASK-019 r1, TASK-020, TASK-021 tests; WSL PostgreSQL run), impl-manager (TASK-021 step 2 after TASK-020 PASS; README), impl-deploy (TASK-022), reviewer (verdicts after each PASS). The previous tester's new test files were on disk but unverified (lint, format and mypy errors in them; Windows unit run 355 passed, 158 PostgreSQL skipped).

Known gaps: coverage gate on `services/` waits for the TASK-020 unit tests; M1 exit gate CHK-M1-240 (G18 to G24) after TASK-019 revision 1, TASK-020 to TASK-022. Accepted residual risk: a forward clock skew under 3 months passes the `db maintain` guard (decisions.md). README usage docs are kept current by impl-manager.

## M0 scaffolding: ready for the user's exit-gate approval (2026-10-20)

All ten tasks: IMPL done, TEST PASS (locally runnable checks), REVIEW APPROVED. The user gave the second approval for TASK-004, TASK-007 and TASK-010 (decisions.md).

| Task | Rounds | TEST | REVIEW |
| --- | --- | --- | --- |
| TASK-001 manager config and locks | 1 + revisions 2, 3 | PASS | APPROVED |
| TASK-002 manager skeleton | 1 | PASS | APPROVED |
| TASK-003 PostgreSQL harness | 1 | PASS (tester-b); Docker checks NOT RUN | APPROVED |
| TASK-004 Go module, lint, stubs | 3 | PASS | APPROVED + user |
| TASK-005 web toolchain | 3 | PASS | APPROVED |
| TASK-006 generated API client | 1 | PASS | APPROVED |
| TASK-007 agent units | 1 | PASS | APPROVED + user |
| TASK-008 manager units | 1 | PASS | APPROVED |
| TASK-009 CI manager and web | 2 | PASS | APPROVED |
| TASK-010 CI agent and units | 3 | PASS | APPROVED + user |

Lead's own run of the M0 gates (2026-10-20, before TASK-005 revision 3): G1 ruff check, G2 ruff format, G3 mypy --strict (12 files), G5 pytest with coverage (55 passed, 3 skipped as not run: Docker unavailable; 100 %), G6 export byte-identical, G7 gofmt, G8 golangci-lint (0 issues), G9 go mod verify, G10 amd64 and arm64 builds, go test, cgo/asm listing empty, G12-G15 web lint, typecheck, format:check, test, units verbatim check (9 units): all green.

**Update 2026-10-20: PR #1 (https://github.com/lusterless/Bitscan/pull/1) first live runs: manager, web, agent and units all green** (58 pytest passed, 0 skipped, with Docker and the pinned Ryuk image on the runner; `systemd-analyze verify` clean; stubs run). Everything in the list below is now confirmed except arm64 stub execution (deferred to M6). Branch `m0-scaffolding`, not merged.

Previously NOT RUN locally (now confirmed in CI): the four workflows on GitHub Actions, the PostgreSQL tests under Docker (CHK-M0-050, 051, 052, 057), `systemd-analyze verify` (G17), the Linux ELF stub run, the Ryuk pull by digest. arm64 stub execution waits until M6.

Next: the user approves the M0 exit gate; then the planner breaks down M1 (open items for it: first-migration size rule PD-18, the audit hash chain core, harness switch to app roles, pytester test for the conftest hook).

Audit history: `work/audit/<role>.md` (merged), `work/audit/archive/` (history, ignore unless asked). Questions for the spec owner and process decisions: `work/open-questions.md`. Decisions: `work/decisions.md`. Tests: `tests/report.md`, `tests/m0/`.

**M6 (2026-10-26, branch `m6-release` in `Bitscan-m6`): all nine tasks (TASK-129 to 137) IMPL done, none tested or reviewed.** The M6 tester couldn't be started in the lead's session (auto-mode safety check), so TEST, REVIEW, the W0 VM network check, the end-to-end run and the gate wait for a tester started from a fresh session or in the default mode. Owner question open: #97 (remote database CA path). Tester fix list and rulings: `work/decisions.md` 2026-10-26 rows. Nothing committed or pushed.

**Drain 3 (2026-10-26): safe to pause.** No agent is running. Both VMs are off. All work is on disk, uncommitted: `Bitscan-m6` holds TASK-129 to 137 (10 modified, 3 new deliverables, plans and 9 impl reports); `Bitscan` holds the `.claude/` and `work/` edits from earlier. **To resume:** in a fresh session (or the default permission mode), run `/bitscan-team` to continue M6 in `Bitscan-m6`. Start tester-m6 with: (1) TP-M6-00, the test plan; (2) W0, the VM network check with a real listener on 8443; (3) the tester fix list in decisions 2026-10-26 (`check_debian_meta.py` L56; 4 old-tuple cursor calls; a lintian run); (4) the W1–W3 wave tests, with TASK-132 at full rigor. Then restart the reviewer. Owner question open: #97.

**M6 resumed (2026-10-26, fresh session).** `tester-m6` started: TP-M6-00, W0 network check (127.0.0.1:18443 behind the 172.31.0.1:8443 portproxy, per decisions), the tester fix list, then the W1 batch (129, 130, 131), TASK-132 at full rigor, W2, W3 and W4. `reviewer` started; it gives verdicts after each TEST PASS. #97 answered (remote DB CA `/etc/bitscan/postgres-ca.pem`). No builder is running; fixes go through the lead.

**M6 progress (2026-10-26).** W0 network check PASS. TASK-134 r1 (backups) built. `tester-m6`: fix list, then TASK-132 (second approval), W1 batch, W4, gate. `tester-m6b` (new): W2 then W3, TP-M6-03 first. `reviewer`: waits for each TEST PASS. Rough estimate if clean: TASK-132 approval in 1–2 h; M6 gate about 6–8 h after that.

**M6 at the user's 2-hour absence (2026-10-26).** TASK-132 COMPLETE (TEST PASS full rigor, APPROVED, the user's second approval). TASK-133 r1 TEST PASS (review with the W2 batch). TASK-134 r2 built; O2 being reproduced (r3 if real). TASK-135 r1 built, in re-test. W1 batch (129–131) with tester-m6. W3 after W2. W4 may start once tester-m6's W1 verdicts for 129 and 130 are in (memory freed by the user). Overnight rule applies while the user is away.

**M6 update (2026-10-26, user away).** Done: TASK-132 (incl. the user's second approval); W1 batch TASK-129, 130, 131 (TEST PASS, APPROVED). TASK-133 r1 TEST PASS (review with W2). TASK-134 r3 (PITR audit sequence, O2 reproduced) being built; r2 in re-test. TASK-135 r1 in re-test. W3 after W2. **W4 waits for the user: Windows has 1.67 GB free, about 4.5 GB is needed.**

**M6 tasks complete (2026-10-26):** TASK-129 to 137 all TEST PASS and APPROVED; TASK-132 has the user's second approval. W4 (end-to-end on both VMs) started with tester-m6; then the gate and the closing review. Owner notes waiting for the user: the TS §8.7 L1343 SIGHUP wording; a later-milestone product guard for the audit cursor after a restore; the web SBOM not byte-reproducible (nit).

**W4 waiting for the user (2026-10-26):** the preflight stopped twice on Windows free memory (needs ≥ 4500 MB to hold; it swings 2.9–4.6 GB). Resume: free memory, then tester-m6 runs `python -I e2e/m6/e2e_vms.py --work C:/Users/kaiquan.koh/Documents/m6-tester-scratch/w4 --walk-pki /root/m6t/w4walk/pki --phase A`, then B and C, then the gate.

## Drain 4 (2026-10-26, user leaving; "let them finish, then drain")

**Done in M6:** all ten tasks TASK-129 to 138 TEST PASS and REVIEW APPROVED; TASK-132 and TASK-138 have the user's second approval. W0 network check PASS. W1–W3 complete. W4 u2404 session 1 (37/41) and session 2 done; u2204 session finishing unattended. New release candidate `bitscan-agent_0.1.0-1_amd64.deb` sha256 d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf (TASK-138). Gate light rows 9/9 PASS. Nothing committed or pushed.

**Left running at drain start (18:05):** the W4 harness process (`e2e_vms.py --session u2204-cont`, started 17:14; output `Documents/m6-tester-scratch/w4/s3.txt`, rows `w4/rows.jsonl`), and tester-m6c's heavy gate steps (G41 on the new RC and its plant, CHK-M6-319-final fresh release run, G18 with G5, the G5 plant, wheel plants CHK-M6-320..322). The lead copies their rows into `tests/m6/report.md`, checks both VMs are off and restored and no m6c container is left, then stops.

**For the next session (start with `/bitscan-team` to continue M6 in `Bitscan-m6`):**
1. **VM gate plants CHK-M6-340..345** (work/tasks.md L1417–L1422): blocked in this session by the auto-mode safety check. Run them from a fresh session or the default permission mode (the user approves each step): each planted RC or manager built in a throwaway copy, run on u2404 restored to clean at 1 GB (`Set-VMMemory -StartupBytes 1GB` after every restore). About 1 h.
2. **CHK-M6-286 canary:** fix the harness check at `e2e/m6/e2e_vms.py` L418 and L1214 to `sudo grep -rlFf /var/lib/bitscan-agent/token …` (the token must not go on a command line, since sudo logs it), then re-check on a fresh host (install, enrol, approve, canary sweep). The FAIL was the harness's own sudo log, not the agent (`m6-tester-scratch/tokscan-findings.md`).
3. **CHK-M6-209 u2404 revoke row:** a harness bug (`systemctl show -p ActiveState,NRestarts --value` prints NRestarts first; the harness compared `["active","0"]`, L772–L773). Fix and re-check.
4. **tests/m6/test-plan.md:** add a TASK-138 block (CHK-M6-160..167); tester-owned.
5. **Gate TP-M6-14** (fold every row, including tester-m6c's and W4's), then the reviewer's closing review `work/reviews/M6-gate.md`.
6. **User:** update `.claude/rules/deploy/packaging-and-units.md` to note the TASK-138 `RemoveOnStop=yes` exception; then the commit split and PR (draft `work/m6-pr-draft.md`; fill in the TBDs; name the TASK-138 deviation and the owner notes), push, CI, merge, tag v0.1.0.

**Owner notes waiting (no M6 change):** TS §8.7 L1343 SIGHUP wording (a restart is needed for a replaced certificate); a product guard for the audit cursor after a restore; the #65 (b) re-arm state is in memory only, so a restart re-alerts; the web SBOM isn't byte-reproducible; O1 `/run/lock` accepted.

**M6 resumed after Drain 4 (2026-10-26, fresh session).** Lead check at resume: both VMs Off with `clean` checkpoints, no Docker containers, no harness process, 4,244 MB free. `tester-m6d` started on items 1–5 in this order: harness fixes and the TASK-138 plan block; G18 with G5, the G5 plant, wheel plants CHK-M6-320..322; one fresh-u2404 session for the re-checks of 286, 209 and 262; the VM plants CHK-M6-340..345; then the TP-M6-14 fold. Heavy steps run one at a time. The reviewer starts after the fold.

**Overnight 2026-10-27 (user asleep).** Running: tester-m6d, item 3 on a fresh u2404 (1 GB, 1,800 MB floor, switch 172.26.240.1), then the unit plants CHK-M6-342u/343u, then the fold. reviewer-m6 gives the verdict when the fold lands. planner-m7 is drafting M7 in `Bitscan-m7` (not approved). VM plants CHK-M6-340..345: NOT RUN under the user's sign-off; they run before any M7 code. Authorised only on gate PASS and APPROVED with no blocking or should-fix: commit (3 commits), push `m6-release`, open the PR; merge with a merge commit on all-green CI (test/CI-file fixes only); tag v0.1.0; publish the release if the `.deb` equals d98ef8c3… and SHA256SUMS verifies. Unit plants 342u/343u: NOT RUN if blocked. Not authorised: M7 approval, `.claude/`, any workaround of a safety-check refusal.

**Session restart (2026-10-27 ~09:59); all agents resumed from disk.** M6: PR #12 OPEN, 3 commits pushed, 17/17 green on 3e6b030, main still 8ad50eb. TASK-133 r2 (setup steps for OpenBao, the sink and the certificate; README L194; the check_md_links fix) is built but uncommitted. tester-m6e is re-running its walk (2,000 MB light floor), then one review, commit, push, CI, merge, tag, publish. M7 W1: TASK-139 locks modified; 148 `catalog.py` drafted; plans 141, 145 and 151 written, 154 and 162 pending; no tests, samples or reports yet. 2,135 MB free, both VMs off.

**M6 gate PASS with one named exception; closing review APPROVED (2026-10-27).** 0 blocking, 0 should-fix, 4 nits. The exception is the VM plants CHK-M6-340..345, NOT RUN under the user's sign-off, which run before any M7 code. Release candidate d98ef8c3…. The overnight chain has started: commit, push, PR, merge on green CI, tag v0.1.0, publish.

**Resumed by the user ("Continue M6", 2026-10-27):** commit 2 `e208c7b` done; commit 3, push, PR, merge, tag and publish follow.

**STOPPED (overnight): the safety check refused commit 2 of 3.** Done: `50816a9` (product commit, 15 files). To finish, from `Bitscan-m6`: (1) `git add manager/tests deploy/tests e2e/m6` and commit `test(manager,deploy,e2e): M6 suites, release checks and end-to-end harness`; (2) `git add work tests` and commit `docs: M6 plans, test and review records` (each with the Co-Authored-By line); (3) `git push -u origin m6-release`, then a PR to main using `work/m6-pr-draft.md`; (4) merge with a merge commit on all-green CI; (5) `git tag v0.1.0` on the merged main and `git push origin v0.1.0`; (6) publish the draft release once its `.deb` sha256 is d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf and SHA256SUMS verifies.

**M7 breakdown ready for the user (2026-10-27, planner-m7, `Bitscan-m7/work/plans/M7-breakdown.md`).** 36 REQ (150–185), 37 TASK (139–175; 25 high risk), 13 waves, gates G54–G61, mutation rows CHK-M7-320..371, no migration, "spec deviations: none", every open question with a recommendation (#98–#111, PD-33–PD-36). Lead's check: every task ≤ 200 LOC and ≤ 5 files. Not approved: approval is the user's (not pre-authorised). M7 code also waits for the VM plants CHK-M6-340..345.

**Environment notes:** WSL portproxy 172.31.0.1:8443 → 127.0.0.1:18443; the manager-host container `m6-e2e-mgr` (from the walked `m6b-host`) is removed by the W4 phase C manager sweep. If it's still there at resume, the next tester decides whether to reuse it for the plants. Keep a WSL keepalive running during VM work.
## M7 drain (2026-10-27, user pausing M7 to test v0.1.0)

**No agent is running.** Branch `m7-catalog` (worktree `Bitscan-m7`), nothing committed or pushed.

| State | Tasks |
| --- | --- |
| TEST PASS + REVIEW APPROVED, with the user's second approval | 139, 140, 147 (r1), 148, 149, 150 (W1) |
| TEST PASS + REVIEW APPROVED, **waiting for the user's W2 second approval** | 141 (r1), 142, 143, 147 (r2), 148 (r1), 151 (r3), 152, 153 (r4), 161 (161 also the PD-35 second look) |
| Tested PASS by tester-m7b, **reports not written**, not reviewed | 144 (687/687), 145 (173/173), 146 r1 (1160/1160); all plants red |
| IN PROGRESS review (wait for G59 after TASK-154) | 174, 175 |
| Not started | 154–160, 162–173 |

**On resume, in order:**
1. tester-m7b writes `work/reports/TASK-144-test.md`, `TASK-145-test.md` and `TASK-146-test.md` from its finished runs (the WSL copy `/root/bstest-m7b-base`, venv `/root/venv-m7b`, plant definitions `%TEMP%\m7b-plants`). Then reviewer-m7 reviews 144, 145 and 146.
2. **User decision already made, not yet built:** close the BIT102 gaps (external `time` and the wrappers nsenter, unshare, flock, setpriv, taskset, chrt, `su -c` and runuser, all looked through; `trap` treated like eval; brace expansion in `bash -c`). This amends #108 (k), as TASK-146 revision 2 (impl-manager-m7b), with must-reject tests (tester-m7b).
3. The `stdbuf -io L` dispute is closed: the builder was right, and the test now uses `stdbuf -i0 -oL`.
4. The W2 second-approval batch goes to the user.
5. Fold W2 into `tests/m7/report.md` from the per-task reports (lead).
6. Next tasks: 154 (pipeline, once 144/146 are approved), 155, 165; then 156–160 (the crash-window ruling is recorded in their rows), routes 162–164, CLI 166, README 167, web 168–173.
7. The VM plants CHK-M6-340..345 must PASS before the M7 gate.

Lead rulings and user decisions from this session are in `work/decisions.md` (2026-10-27 rows).

## Cloud session checks of the released core (2026-10-27, lead)

Run in the claude.ai cloud container (Docker, cgroup v1 host; Docker Hub via mirror.gcr.io; Debian/Ubuntu apt over a local HTTP→HTTPS relay in the scratchpad, signatures still checked). Not gate evidence for VM rows.

| Check | Result |
| --- | --- |
| Manager suite with PostgreSQL 16 (`pytest -n 8`, coverage on services) | 8141 passed, 0 skipped, 99.14 %; 2 timing-bound tests failed under load, fixed by tester-m7c (CPU time) |
| Web build, lint, typecheck, tests | 345/345 |
| Go: gofmt, `go mod verify`, `CGO_ENABLED=0` build, golangci-lint v2.14.0 | clean, 0 issues |
| Go tests `-race` | pass; 4 lone-surrogate contract skips by design; the 2 non-root skips PASS as user `bstester`; `TestJobSeenSevenDays` flaked once under load (second pull at 7 d + 59 s, past the boundary), 30/30 on re-runs — for the tester |
| `systemd-analyze verify deploy/systemd/*` | only "not executable" (allowed locally) |
| Package build suite (`test_build_deb.sh` repro contents static sbom sha256 flags lintian) | 107/107; both builds = released `d98ef8c3…` |
| Maintainer scripts (`test_maintainer_scripts.sh all`), u24 and u22 systemd containers | 548/548 each (run with umask 022: `docker exec` there has umask 0000, which made the test's `mkdir /etc/bitscan` world-writable and the agent rightly refused it) |
| Debconf (`test_debconf.sh`, disposable mode), u24 and u22 | 68/68 each, with the source `deploy/debian/config` given mode 755 as in the `.deb`. Owner note: git stores `deploy/debian/{config,postinst,postrm}` as 100644 (committed from Windows); the `.deb` has 0755 (dh_installdeb), so the package is right, but the test needs the source `config` executable on a Linux checkout |
| G41 end to end (`e2e/agent_manager.sh`, real serve + PostgreSQL + released `.deb`) | u24 23/23, u22 23/23 |
| Upgrade from `0.1.0~pre1-1` | NOT RUN: that package was never published; M6 CHK-M6-104 covers it |
| CHK-M6-340..345, cgroup v2 hosts, arm64, load test | NOT RUN here: no KVM / no arm64 / 4 shared CPUs |
