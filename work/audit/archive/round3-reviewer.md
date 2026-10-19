# Reviewer round 3: semantic review against the spec

Scope (per `round3-brief.md` and `main`'s two mid-round requests): (1) line-by-line review of the uncommitted `git diff`; (2) hunting for holes in my slice, TS §3.3–§3.7 and §8.1–§8.4, which I re-read in full from `docs/spec/`; (3) rulings on R2-R-01..19 and my open round-1 items; (4) rulings on the planner (rounds 2 and 3), implementer and tester items; (5)–(6) APPLY, VERIFIED and REJECTED messages; (7) status updates; (8) final verification after `IMPLEMENTER-DONE` (section 9).

Tooling: I have **no SendMessage tool**. Section 0 is the hand-off table the implementer and tester poll. I verified every applied batch from the working tree (`git diff`). I did not review the prose of `work/open-questions.md` beyond the entries I rule on.

Format: `R3-R-## | class | file:line or spec § | what is wrong or missing | spec quote (§, line) | exact wording or patch | status`. Line numbers are as of the final tree.

## 0. Rulings for implementer (final; poll this table)

State: `IMPLEMENTER-DONE` seen (`work/audit/round3-implementer.md`). Every applied line in `.claude/**` is VERIFIED (section 9). Three items remain, all one-line appends:

| Item | Ruling | Action for implementer |
| --- | --- | --- |
| R3-P-51 inventory transitions (jobs-and-scans.md:23) | CONFIRMED with one wording change: say "rejected (413 or 422)", as the spec does | append to the state line: "; inventory jobs: `dispatched → completed` (upload) or `dispatched → failed` (not uploaded within 30 min, or upload rejected with 413 or 422) (TS §3.4)." |
| R3-I-05 migrate unit started by the runbook (packaging-and-units.md:51) | CONFIRMED, verbatim TS §8.7 L1346 | append: "The upgrade runbook starts it first (`systemctl start bitscan-manager-migrate`) (TS §8.7)." |
| R3-I-06 "with a new enrolment token" (agent.md:25) | CONFIRMED **narrowed**. TS §3.2 step 8 (L191) says it only for `token_revoked` and `token_expired`. For `enrollment_rejected` the spec says only "the agent receives 401 `enrollment_rejected` and stops" (L188), so applying it to all three would be stricter than the spec | append to step 3: " For `token_revoked` or `token_expired` the log says the host must be re-enrolled with a new enrolment token (TS §3.2 step 8)." |

Everything else in my earlier section 0 (A1–A5, R3-R-01..12, R2-R-07 FIX part, R2-R-11, R2-R-16, the #28–#31 markers, R3-P-12a, R3-P-50) is applied and VERIFIED.

## 1. Diff review (one line per changed hunk; final tree)

| Hunk | Verdict |
| --- | --- |
| CLAUDE.md:12 Terms | OK: TS §1.3 L33–38, §1.4 L42; SR §3.2 L186 |
| CLAUDE.md:78–79 layout `docs/spec/`, `work/`; :114 `main` | OK (hygiene) |
| agents/*.md `lead` → `main`; implementer.md:8 `bits/samples/` | OK |
| implementer.md:28 signing vs forbidden items (R3-R-11) | OK, verbatim; every "Never add" item kept |
| SKILL.md:26, :38, :41, :42 | OK |
| agent.md:17 #4 (R3-R-02) | OK |
| agent.md:18 State `issued_at`/`expires_at`; :26 replace on rotate | OK (TS §3.2 L183, §6.5 L1188) |
| agent.md:31 #30 | OK (TS §3.7 L484, L493) |
| agent.md:33 NTP | OK, verbatim TS L212 |
| agent.md:34 (R2-R-07 FIX half) reverted | OK. I accept the planner's rejection: naming the field for a down runner pre-answers #28 |
| agent.md:36 #28 | OK (TS §3 L152, §3.7 L283, §6.5 L1184) |
| agent.md:43 `spool_overflow` "(results `error` field, TS §6.5)" | OK (TS L226, L1184) |
| agent.md:48 "the manager computes it identically" removed | OK: it removed a claim the spec does not make (#33) |
| runner-sandbox.md:18 #29; :27 #31 | OK (TS L282, L249) |
| runner-sandbox.md:33 the agent reports `runner_unavailable` (R3-R-06) | OK, TS L152 |
| runner-sandbox.md:57 OS matrix (R3-R-07) | OK, TS L1279 |
| security-invariants.md:10 (R3-R-11) | OK; not weakened |
| security-invariants.md:21 plugin-socket accepted risk (R2-R-16) | OK (TS L276, L365); this records an accepted risk and adds no new control |
| security-invariants.md:27 viewers (R3-R-10) | OK, TS L1121; the restriction is unchanged |
| packaging:44 purge → offline; no deregistration | OK (TS L166, L220, §6.1) |
| packaging:46 NTP, cloned image, pinning | OK (TS L212, L192, L194). "Recommends" is the spec's word ("optional but recommended") |
| packaging:60 #6 with `serve` (R3-R-09) | OK, TS L1359 |
| api.md:31 agent error types + 409 `policy_managed_on_server` | OK (TS L1190; §4.1 L522; §4.3 L550) |
| api.md:38–39 #8 on its own line (R3-R-04) | OK |
| api.md:40 list filters (R3-P-22) | OK (TS L1100, L1108, L1118, L1121) |
| api.md:45 #9; :66 #5 (R3-R-03) | OK |
| api.md Tests line "TS §3.4" | OK (TS L230 `/readyz`) |
| audit-and-alerts:19 #24 cross-reference; Tests sources | OK |
| auth-and-users:21–22 #1 split; :40 #7; Tests source | OK (TS L1084, L1104, L1089) |
| bit-format:16 #10 | OK (SR L257; TS L1297) |
| bit-format:18 "Lengths are in characters" (R3-P-12a) | OK (SR §2 "chars"). Nit: the description and `Execute` columns are `TEXT`, not `VARCHAR(n)`; "characters" holds either way |
| bit-format:19 #17; :21–22 PluginId marker split; :24 display name (R3-P-40) | OK (SR L99, L109; TS L1035, L907) |
| bit-format:32 #16; :34 #15; :37 #2 (R3-R-01) | OK (SR L115, L120, L257, L261, L263, L270) |
| bit-format:52–54, :61 `bits/samples/`; :63 Sandbox | OK (TS L1280) |
| config-and-cli:14 AppRole; :15 #24; :40 #7; Tests sources | OK (TS §8.6 L1312; L1089) |
| database.md:28 schema `public` owner and `USAGE` | OK, TS L1027–1028 |
| database.md Tests sources | OK |
| enrolment-and-tokens:14 creates and revokes | OK, TS L1116 |
| enrolment-and-tokens:25 #26 sub-bullet; :33 #25; :47 Load (R3-R-08) | OK (TS L184, L188; DDL `agent` has no such columns; L1282) |
| evaluator:13–14 #11; :19 #13 | OK. Nit: #13 still lists `nan`/`inf`/`_`, which I called answerable; asking about them is harmless |
| evaluator:27 `eval_detail` (trimmed R3-P-21); :28 #12 | OK (TS L901, L599, L593, L600) |
| evaluator:29 "Host compliance score"; :30 re-evaluation route | OK (TS L602, L601, L933, L936) |
| importer:22 #21; :27 #23; :36–40 start-up split + #27; :45 #20; :54 #14 | OK (SR L231; TS L530, L532, L1290, L528, L540, L542, L944, L550; SR L240) |
| inventory-and-packages:17 `list_sha256`; :18 #33; Tests sources | OK (TS L241, L1186, L1072) |
| jobs-and-scans:17 #18; :18 pickup bound | OK (TS L547, L556) |
| jobs-and-scans:23 state line (R3-R-12) | OK, my exact text. Inventory part pending: R3-P-51 |
| jobs-and-scans:31 sweep timeouts | OK (TS L575, L244) |
| jobs-and-scans:36 cancel (R3-P-20); :37 never `dispatched`/`expired` (R3-P-50); :38 #22; :39 #3 | OK (TS L581, L580, L843) |
| testing.md:8 glob; :18 CRLF note and sources; :25 TS §3.4 | OK |
| web-ui:26 click-through; :27 #32; :29 runner helpers (R2-R-11) | OK (TS L1223, §7.1 row shapes, L484) |
| README.md row; agent-teams-reference.md:219; .gitignore; .gitattributes | OK (hygiene; TS L164–165 for the preseed) |

**Stricter-than-spec check:** none found. Every new imperative restates a spec sentence. Each removal took out an unsupported claim (agent.md:48; inventory "Recompute … same as the agent"). Each new marker asks; none decides. The one case where an addition would have been stricter than the spec is R3-I-06 as proposed, and I narrowed it (section 0). No line weakens `security-invariants.md`: lines :10 and :27 are restatements, and :21 records a spec-accepted risk.

## 2. Findings from the diff review and hole-hunting

| Id | Class | Target | Problem and spec quote | Status |
| --- | --- | --- | --- | --- |
| R3-R-01 | FIX | bit-format.md:37 (#2) | Overstated BIT010; SR §4.1 L263 "`Operator` missing or not one of the 14 operators" | APPLIED; VERIFIED |
| R3-R-02 | FIX | agent.md:17 (#4) | Wrong §3.5; `log_level` has no fixed value (TS L226, L266, L382, L202) | APPLIED; VERIFIED (the Sections column of #4 is fixed too) |
| R3-R-03 | FIX | api.md:66 (#5) | TS §8.4 L1292 does name `/healthz`, `/readyz` | APPLIED; VERIFIED |
| R3-R-04 | FIX (structure) | api.md:39, importer.md:54, auth-and-users:22, enrolment-and-tokens:25 | The markers sat mid-bullet (brief rule 3) | APPLIED; VERIFIED |
| R3-R-05 | DUP | #1, #9 pointers | = planner A1 | VERIFIED |
| R3-R-06 | FIX | runner-sandbox.md:33 | TS §3 L152 "the agent reports `runner_unavailable`" | APPLIED; VERIFIED |
| R3-R-07 | FIX | runner-sandbox.md:57 | TS §8.3 L1279 OS matrix | APPLIED; VERIFIED |
| R3-R-08 | FIX | enrolment-and-tokens.md:47 | TS §8.3 L1282 Load | APPLIED; VERIFIED |
| R3-R-09 | FIX (nit) | packaging:60 | TS L1359 `serve` | APPLIED; VERIFIED |
| R3-R-10 | FIX | security-invariants.md:27 | TS §6.2 L1121 | APPLIED; VERIFIED |
| R3-R-11 | FIX | security-invariants.md:10; implementer.md:28 | TS L210, L213, L1129 | APPLIED; VERIFIED |
| R3-R-12 | FIX | jobs-and-scans.md:23 | TS §4.4 L572, L575, L581, L582 | APPLIED; VERIFIED |

Hole-hunt result, TS §3.3–§3.7 and §8.1–§8.4: apart from R3-R-06..08 and the ASK items #28–#31, everything checks out. That covers intervals, clamps, the 10-job cap, the job checks, NTP, status thresholds, decommission, the start notice, response codes, back-off, the spool, inventory, the plugin environment, cgroup cleanup, redaction, batches, units, sockets, modes, D-Bus, capread, and the §8.1–§8.4 lists. The §8.1 L1251 "size and node limits" is covered by TS §4.1 L517.

## 3. Rulings on my round-2 items (R2-R-01..19), final

| Id | Class | Status |
| --- | --- | --- |
| R2-R-01 | FIX | APPLIED (api.md:38–39, marker split); VERIFIED |
| R2-R-02 | FIX | APPLIED; the three bad lines were corrected (R3-R-01..03); VERIFIED |
| R2-R-03, -04, -05, -06, -09, -10 | FIX | VERIFIED |
| R2-R-07 | FIX + ASK | FIX half APPLIED at agent.md:43 (spool) and VERIFIED; the agent.md:34 half was REJECTED by the planner and reverted, and I accept that; ASK = #28, marker at agent.md:36, VERIFIED |
| R2-R-08 | ASK | #29, marker at runner-sandbox.md:18; VERIFIED |
| R2-R-11 | FIX | APPLIED (web-ui.md:29); VERIFIED |
| R2-R-12 | ASK | #30, marker at agent.md:31; VERIFIED |
| R2-R-13 | ASK | #31, marker at runner-sandbox.md:27; VERIFIED |
| R2-R-14 | DECIDE | PD-3 |
| R2-R-15 | DECIDE | PD-5 (REJECTED as FIX: TS §8.2 names no test runner) |
| R2-R-16 | FIX | APPLIED (security-invariants.md:21); VERIFIED |
| R2-R-17, -18 | FIX | VERIFIED in implementer.md |
| R2-R-19 | DUP | = P-41 / PD-11 |

## 4. Rulings on teammates' items

Round 2, planner: R2-P-01/-02/-03/-05 DUP; R2-P-04 withdrawn (#8 stays ASK); R2-P-06 DECIDE; R2-P-07..13, -18, -19 ASK (#12–#18, #20, #21); R2-P-14..17, -20, -21 FIX; R2-P-25/-26 VERIFIED. All applied items are VERIFIED (section 1).

Round 2, implementer: R2-I-01, -02, -04, -06, -07, -08, -10, -12..17, -19, -20 applied, VERIFIED (R2-I-13 with my trim: "before installing" was dropped). R2-I-03 and R2-I-11 DECIDE (PD-9, PD-10). R2-I-05 FIX, done. R2-I-09 REJECT. R2-I-18 ASK (in #6).

Round 3, planner (round3-planner.md §E):
- FIX: R3-P-14, -15/-41, -16, -17, -20, -40 CONFIRMED; R3-P-21 CONFIRMED trimmed; R3-P-12a and R3-P-50 (my splits of #17 and #22). All applied and VERIFIED.
- ASK: #13, #15, #16, #20, #21, #23 and #27 CONFIRMED; the trimming half of #17 and the queued→running half of #22 CONFIRMED.
- REJECT: #19, withdrawn by the planner.
- R3-P-51: CONFIRMED with the wording change in section 0. Basis: TS §3.4 L230 "uploads it with `PUT /api/v1/agent/{id}/inventory?job_id=…`, which completes the job"; L244 "dispatched but not uploaded within 30 minutes, or whose upload is rejected (413 or 422), becomes `failed`". I did not add "no `running` state" or "a late upload does not change the job": both are inference. jobs-and-scans:44 already restates the late-upload sentence of L244.

Round 3, implementer: R3-I-01..04 and R3-I-07 VERIFIED. R3-I-05 CONFIRMED. R3-I-06 CONFIRMED narrowed (section 0). R3-I-08 report only (memory file, PD-11). R3-I-09 = PD-10. R3-I-10 DUP of S-11.

Tester (R2-T-01..06, R3-T-01): every applied hunk VERIFIED (section 1).

Reserved entries #28–#31: agreed, none withdrawn; the rows in open-questions.md now carry my wording.

## 5. Role files and SKILL.md vs CLAUDE.md

No contradictions in ownership, `main` addressing or the TEST/REVIEW completion rules. One gap: reviewer.md:30 has the reviewer re-review directly, while SKILL.md:47 has the tester re-run first. = PD-1.

## 6. Spec-internal inconsistencies for the owner (never edit the spec)

S-01..S-10 from work/audit/reviewer.md still stand. S-11..S-15 are now in open-questions.md §5:
- S-11: TS §3.1 L162 and §3.6 L261 omit `issued_at`/`expires_at` (TS §3.2 L183).
- S-12: TS §4.5 L600 `evaluate()` vs L593, L599 (#12).
- S-13: TS §4.3 L550 vs SR §3.6 L240 (#14).
- S-14: TS §3.5 L249 `max_parallel_plugins` vs the §6.5 Job (#29).
- S-15: TS §3 L152 vs the heartbeat L1163 and the results `error` L1184 (#28).
- S-16: SR §4.1 L263–264 (#2).

## 7. Exchange log (no SendMessage tool; file-based)

- ← main (mid-round 1): rulings on the R3-P calls, #28–#31, and A1–A3. Done (section 4).
- ← main (mid-round 2): `IMPLEMENTER-DONE`; verify all applied lines, rule on R3-P-51, R3-I-05 and R3-I-06, and check strictness. Done (sections 0, 1, 9).
- → implementer: `VERIFIED:` every applied item in round3-implementer.md §2, including the agent.md:34 revert. `APPLY:` R3-P-51, R3-I-05 and R3-I-06 (narrowed), as in section 0. No `REJECTED` outstanding.
- → planner: thanks for #28–#31 and S-14/S-15; nothing further.
- → tester: please check the three section-0 appends mechanically once they are applied.
- ← planner via round3-planner.md §E–§F; ← implementer via round3-implementer.md; no direct messages.

## 8. Counts (final)

- FIX: 12 authored (R3-R-01..12; -05 is a DUP), all APPLIED and VERIFIED. 3 round-2 FIXes of mine applied and VERIFIED (R2-R-07 part, -11, -16). Confirmed for others: R3-P-14..17, -20, -21, -40, -41, -12a, -50, -51, and R3-I-05, -06.
- VERIFIED: every applied hunk in `.claude/**` (section 1), plus README.md, agent-teams-reference.md, .gitignore and .gitattributes.
- ASK: 4 of mine (#28–#31, markers verified); 11 planner ASKs confirmed (#13, #15, #16, #17 part, #20, #21, #22 part, #23, #27, plus #12, #14, #18 from round 2).
- DECIDE: R2-R-14 and R2-R-15 (PD-3, PD-5).
- REJECT: #19, the "chars" half of #17, R2-I-09, R3-P-23(c), and 3 first-version lines (since corrected). R3-I-06 was narrowed, not rejected.
- DUP: R3-R-05, R2-R-19, R3-I-10.

## 9. Final verification after IMPLEMENTER-DONE

Method: `git diff -U0 -- .claude README.md docs/agent-teams-reference.md .gitignore .gitattributes`. I read every hunk and checked each against the cited TS/SR line. Results:
- 23 `.claude/` files changed, plus README, agent-teams-reference, .gitignore and .gitattributes. All OK (section 1).
- 44 `**Open spec question:**` lines in `.claude/`, each on its own line. No `#NEW` or `#19` pointer remains. Pointers #28–#33 resolve to entries marked **agreed** in work/open-questions.md.
- Nothing stricter than the spec (see the check under section 1). R3-I-06 was narrowed before applying.
- Still to apply: R3-P-51, R3-I-05 and R3-I-06 (section 0). These are three one-line appends, each restating a spec sentence.
