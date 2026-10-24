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
