# Round 3, planner: spec slice SR §1–§4 and TS §4, rulings, open-questions rework

What I read, in full and from disk:
- `docs/spec/bit_Schema_Reference.md` (SR §1–§4).
- `docs/spec/Technical_Specification.md` §4.1–§4.6, plus the lines my rules cite from §2.1, §2.3, §3.3, §3.4, §3.7, §5.2, §5.3, §6.2, §6.5, §7.1, §7.3, §8.4 and §8.5.
- The rules that cite my slice: `bit-format.md`, `importer.md`, `evaluator.md`, `jobs-and-scans.md`, `api.md`, `web-ui.md`, `database.md` and `security-invariants.md`.
- The round-2 reports, `work/audit/planner.md` and `work/open-questions.md`.

**Tooling limits in this session.** I have no Bash tool, so I could not run `git diff`. I compared the working-tree files with the spec directly. I have no SendMessage tool either. As the brief allows, every request and APPLY batch is written in section E and in my final text output, for `main` to relay.

**The tree changed while I read it.** The implementer applied several edits during my session, and I checked those against the spec:
- R2-R-05 at `jobs-and-scans.md:30`
- R2-R-09 at `bit-format.md:59`
- R2-I-12 at `bit-format.md:16` and `evaluator.md:13`
- the `bits/samples/` change at `bit-format.md:48`, `:50` and `:57`
- R2-I-10 at `CLAUDE.md:78–79`

Line numbers below are as of my last read.

Format: `R3-P-## | class | file:line or spec § | what is wrong or missing | spec quote (§, line) | exact wording or patch | status`

## A. Rulings on my round-2 items (R2-P-01 to R2-P-26)

R3-P-01 (rules on R2-P-01) | FIX | SKILL.md:26, implementer.md:8 | `bits/` should be `bits/samples/` | Not a spec item. The source is the layout at CLAUDE.md:73 "`bits/samples/` # sample .bit policies (owned by impl-bits)" | Already in the tree: SKILL.md:26 "`bits/samples/`", implementer.md:8 "`bits/samples/` or `deploy/`" | APPLIED (uncommitted; planner checked with grep; tester to verify)

R3-P-02 (rules on R2-P-02) | FIX | testing.md:8; bit-format.md:48, :50 | `bits/tests/**` glob; fixture caveat | Layout source CLAUDE.md:74 | In the tree: testing.md:8 `- "bits/tests/**"`; bit-format.md:48 "Authoring rules for `bits/samples/`", :50 "Fixtures in `bits/tests/` … break these rules on purpose." | APPLIED (planner checked with grep)

R3-P-03 (rules on R2-P-03) | FIX | rules | Markers for #2–#8 | — | Present at bit-format.md:33 (#2), jobs-and-scans.md:37 (#3), agent.md:17 (#4), api.md:64 (#5), packaging-and-units.md:60 (#6), auth-and-users.md:39 (#7) and api.md:38 (#8). What is left: the #1 and #9 markers have no pointer, and the #7 pointer in config-and-cli.md is missing. See R3-P-42 | APPLIED for #2–#8; the rest is R3-P-42

R3-P-04 (rules on R2-P-04) | DUP of R2-R-01 | api.md:38 | — | — | The reviewer's version kept #8 as a marker, and that is in the tree. I withdraw my "remove #8" proposal | APPLIED (as R2-R-01)

R3-P-05 (rules on R2-P-05) | FIX | `.claude/**` | `lead` vs `main` | — | grep for `` `lead` `` and "message lead" finds only CLAUDE.md:112 "message the lead (teammates address it as `main`)" | APPLIED

R3-P-06 (rules on R2-P-06) | DECIDE | SKILL.md, CLAUDE.md | P-05, P-06, P-07, P-09, P-36, P-37 | — | Logged as PD-1, PD-2, PD-3, PD-5, PD-6 and PD-7 in `work/open-questions.md` §4 | logged

R3-P-07 (rules on R2-P-07) | ASK #12 | evaluator.md:10, :24–25 | The `evaluate()` signature has no input for the runner `error` or for stderr size, which two of its own ERROR cases need | TS §4.5 L593 "runner error (`spool_overflow`, `runner_unavailable`); output over the caps"; L600 "one pure function `evaluate(operator, expected, stdout, exit_code, timed_out, truncated) -> 0 \| 1 \| 2`, with unit tests for every operator and every ERROR case" | Marker: see APPLY batch A3 | agreed (reviewer, round 2), ready to apply

R3-P-08 (rules on R2-P-08) | ASK #13 | evaluator.md:17; bit-format.md:21 | The number grammar does not settle exponents, `nan`/`inf`, `_`, `.5` or `5.` | SR §2.4 L153 "**Numbers** are decimal integers or floats with an optional sign; the whole trimmed stdout must be one number." | Marker after confirmation: "**Open spec question:** whether exponents (`1e3`), `nan`/`inf`, `_` separators, `.5` and `5.` count as numbers, for stdout and for BIT012 (`work/open-questions.md` #13)." | proposed (reviewer to confirm)

R3-P-09 (rules on R2-P-09) | ASK #14 | importer.md:50 | Revival version: TS and SR conflict | TS §4.3 L550 "Uploading a policy with the same name later brings it back as a new version."; SR §3.6 L240 "if the file hash differs from `source_sha256`, add 1 to `version`; clear `deleted_at` if the policy had been deleted" | Marker: see A3 | agreed (reviewer, round 2), ready to apply

R3-P-10 (rules on R2-P-10) | ASK #15 | bit-format.md:30 | The BIT007 winner depends on processing order | SR §4.1 L261 "`PolicyName` already imported from a different file in the server folder that still exists"; TS §4.1 and §4.2 give no order | Marker after confirmation (append to bit-format.md:30): "**Open spec question:** when two server-folder files with the same `PolicyName` are both new, no processing order is given, so which one gets BIT007 is undefined (`work/open-questions.md` #15)." | proposed (reviewer to confirm)

R3-P-11 (rules on R2-P-11) | ASK #16 | bit-format.md:29 | No code is given for zero `Plugin` elements or a non-integer `@timeout` | SR §2.1 L103 "Must contain ≥ 1 `Plugin`"; SR §2.3 L120 "`Execute/@timeout` … integer … 1–600 seconds"; SR §4.1 L270 BIT017 "`Execute/@timeout` outside 1–600, or more than 5,000 plugins" | Marker after confirmation: "**Open spec question:** which code an empty `<PluginsGroups/>` (BIT002 or BIT017) and a non-integer `@timeout` such as `30s` get (`work/open-questions.md` #16)." | proposed (reviewer to confirm)

R3-P-12 (rules on R2-P-12) | ASK #17 | bit-format.md:18 | Trimming of the other text elements; whether lengths count characters or bytes | SR §2.1 L99 "1–128 chars, trimmed" (PolicyName only); SR §2.2 L109 "`FamilyName` … 1–128 chars" (no "trimmed") | Marker after confirmation: "**Open spec question:** SR §2 says "trimmed" only for `PolicyName`, `Execute` and `ExpectedResult`; ask whether the other text elements are trimmed before the length and empty checks, and whether "chars" are code points (`work/open-questions.md` #17)." | proposed (reviewer to confirm)

R3-P-13 (rules on R2-P-13) | ASK #18 | jobs-and-scans.md:16 | Whether disabling a policy cancels its queued jobs. The reviewer's round-2 caveat ("'Running scans finish' literally covers only running scans") makes this inferred, so it is ASK, not FIX | TS §4.3 L547 "`policy_status = disabled` hides the profile from selection and blocks new scans with it. Running scans finish." | Marker: see A3 | agreed (reviewer, round 2), ready to apply

R3-P-14 (rules on R2-P-14) | FIX + ASK #19 | evaluator.md:27 | The spec calls it the "host" score. Whether a scan-level score exists is open | TS §4.5 L602 "**Score:** host compliance score = PASS ÷ (PASS + FAIL)" | Before: "- Score = PASS ÷ (PASS + FAIL)," After: "- Host compliance score = PASS ÷ (PASS + FAIL)," (the rest of the line is unchanged). Marker #19 only after confirmation | FIX UNVERIFIED (reviewer to confirm); #19 proposed

R3-P-15 (rules on R2-P-15) | FIX | importer.md:34–36 | "before anything else" was dropped. My round-2 wording ("before the API and scheduler start") went further than the spec, so it is trimmed to the spec's words | TS §4.1 L528 "At start-up, before anything else, it finishes interrupted uploads … It then reconciles both folders with the catalog" | Merged with R3-P-41; see A4 | UNVERIFIED (reviewer to confirm)

R3-P-16 (rules on R2-P-16) | FIX | jobs-and-scans.md:17 | The pickup bound is missing | TS §4.4 L556 "Jobs are picked up at each agent's next job pull (≤ `job_pull_seconds` + 30 s). There is no way to push a job to an agent sooner." | Before: "- Manual scans are picked up at each agent's next pull; there is no way to push sooner." After: "- Manual scans are picked up at each agent's next job pull (≤ `job_pull_seconds` + 30 s); there is no way to push a job sooner (TS §4.4)." | UNVERIFIED (reviewer to confirm)

R3-P-17 (rules on R2-P-17) | FIX (the ASK half goes into #12) | evaluator.md:28 | The re-evaluation route, TOTP, audit logging and the recorded columns are missing | TS §4.5 L601 "(`POST /api/v1/scans/{id}/reevaluate`, TOTP session, audit-logged)"; TS §5.2 L933 "`policy_version INTEGER NOT NULL, -- policy.version whose Operator and ExpectedResult were used`", L936 "`reevaluated_by BIGINT NOT NULL`" | Before: "- Re-evaluation adds `scan_result_reeval` rows against the policy's current version;" After: "- Re-evaluation (`POST /scans/{id}/reevaluate`, admin, TOTP session, audit-logged) adds `scan_result_reeval` rows against the policy's current version, each recording that `policy_version` and `reevaluated_by`;" (the rest of the line is unchanged) | UNVERIFIED (reviewer to confirm)

R3-P-18 (rules on R2-P-18) | ASK #20 | importer.md:42 | The `task.state` outcome of a rebuild with rejected files | TS §4.2 L540 "a rejected file keeps its existing catalog rows and is reported, and the rebuild commits as a whole"; TS §5.2 L944 "`CHECK (state IN ('running','succeeded','failed'))`" | Marker after confirmation: "**Open spec question:** whether a rebuild that rejected some files ends `succeeded` or `failed` in `task.state` (`work/open-questions.md` #20)." | proposed (reviewer to confirm)

R3-P-19 (rules on R2-P-19) | ASK #21 | importer.md:21 | The import counters are undefined | SR §3.5 L231 "`plugins_added`, `plugins_updated`, `plugins_retired` \| INTEGER \| Counts" | Marker after confirmation: "**Open spec question:** SR §3.5 does not define how `plugins_added`, `plugins_updated` and `plugins_retired` are counted (`work/open-questions.md` #21)." | proposed (reviewer to confirm)

R3-P-20 (rules on R2-P-20, the P-23 part) | FIX | jobs-and-scans.md:35 | Dispatched and running jobs also become `cancelled` | TS §4.4 L581 "Queued jobs become `cancelled` and are never returned by a pull; dispatched or running jobs become `cancelled`, and later result posts for them get 409 `job_not_acceptable` and are not stored." | Before: "- Cancel is manager-side only. Cancelled queued jobs are never returned by a pull. Later result posts for a cancelled job get 409 `job_not_acceptable` and are not stored." After: "- Cancel is manager-side only. Queued jobs become `cancelled` and are never returned by a pull; dispatched or running jobs become `cancelled`, and later result posts for them get 409 `job_not_acceptable` and are not stored (TS §4.4)." | UNVERIFIED (reviewer to confirm)

R3-P-21 (rules on R2-P-20, the P-24 part) | FIX (the vocabulary goes into #12) | evaluator.md, a new line after :25 | `eval_detail` is never mentioned, although viewers see it (web-ui.md:14) | TS §5.2 L901 "`eval_detail TEXT, -- e.g. 'stdout not numeric', 'spool_overflow'`"; TS §4.5 L599 "as ERROR `oversize`" | Insert: "- Store the reason for an ERROR in `eval_detail` (TS §5.2 examples: `stdout not numeric`, `spool_overflow`; TS §4.5: `oversize`)." | UNVERIFIED (reviewer to confirm)

R3-P-22 (rules on R2-P-21, the P-22 part) | FIX | api.md, a new line after :38 | No rule lists the list filters | TS §6.2 L1100 "List profiles (`?status=enabled`)"; L1118 "List scans (filter by policy, host, state, date)"; L1121 "Results, filterable by status and host"; L1108 "Hosts with status, OS, last heartbeat and inventory" | Insert: "- Lists (TS §6.2): `GET /policies` takes `?status=enabled`; `GET /scans` filters by policy, host, state and date; `GET /scans/{id}/results` and `/results.csv` filter by status and host; `GET /agents` returns hosts with status, OS, last heartbeat and inventory." | UNVERIFIED (tester to confirm; TS §6 is the tester's slice)

R3-P-23 (rules on R2-P-21, the P-26 part) | split | web-ui.md:26 | (a) Helpers on the host page: DUP of R2-R-11 (the reviewer drives it). (b) Package click-through: FIX. (c) Import history in the UI: REJECT, because TS §2.1 L101 gives the UI scope as "Profiles, hosts, scans, results, package search", and `/imports` is only an API route | TS §7.3 L1223 "results grouped by package → version → host count, click through to host list." | (b) Before: "and results grouped package → version → host count (TS §7.3)." After: "and results grouped package → version → host count, with click-through to the host list (TS §7.3)." | (b) UNVERIFIED (tester to confirm)

R3-P-24 (rules on R2-P-21, the P-27 part) | DUP of R2-R-06 | packaging-and-units.md:46; agent.md:32 | NTP prerequisite | TS §3.3 L212 "Hosts must be NTP-synced; the manager alerts on clock skew over 5 minutes, reported in the heartbeat." | In the tree: packaging:46 "states the prerequisite that hosts must be NTP-synced (TS §3.3)"; agent.md:32 "Hosts must be NTP-synced; the manager alerts on clock skew over 5 minutes (TS §3.3)." | APPLIED; matches the spec (planner)

R3-P-25 (rules on R2-P-22) | FIX (my own report) | work/audit/planner.md P-30 | The false claim "`.claude/` is currently untracked as a whole" | Tester T-06: `.claude/settings.local.json` was tracked | Corrected in planner.md P-30 | APPLIED (my file)

R3-P-26 (rules on R2-P-23) | FIX (the tester's file) | work/audit/tester.md statuses | Many CONFIRMED items have since been fixed | — | Sent to the tester (section E); the tester owns that file | UNVERIFIED (tester)

R3-P-27 (rules on R2-P-24) | REJECT | — | Advice on audit method, not a document defect. Superseded by round-3 brief hard rule 2: every finding and rule wording must carry a spec quote | — | none | REJECTED

R3-P-28 (rules on R2-P-25) | DECIDE | .gitattributes, testing.md:18 | Which mechanism keeps CRLF test inputs: in-code literals or `-text` | SR §2.4 L151 "CRLF becomes LF" (this is why the inputs matter) | Logged as PD-8 | logged

R3-P-29 (rules on R2-P-26) | DUP of R2-R-05 | jobs-and-scans.md:30 | The sweep's timeouts | TS §3.4 L244 "An inventory job that is dispatched but not uploaded within 30 minutes … becomes `failed`"; TS §4.4 L575 "A dispatched job that never starts fails 24 h after dispatch … The `offline_sweep` task (every 60 s) applies these timeouts" | In the tree: "fails, or marks `partial`, jobs past their deadline; fails compliance jobs dispatched more than 24 h ago that never started, and inventory jobs dispatched more than 30 min ago without an upload (TS §3.4, §4.4);" | APPLIED; matches the spec (planner)

## B. Rulings on round-1 leftovers

R3-P-30 (rules on P-05) | DECIDE | SKILL.md:47 | Re-test after CHANGES_REQUESTED | — | PD-1 | logged
R3-P-31 (rules on P-06) | DECIDE | SKILL.md, reviewer.md:16 | Review baseline | — | PD-2 | logged
R3-P-32 (rules on P-07) | DECIDE (merged with R2-R-14) | CLAUDE.md:100 | Second approver | TS §8.2 L1268 "changes to the importer, auth, agent or runner need two." | PD-3 | logged
R3-P-33 (rules on P-09) | DECIDE (merged with R2-R-15, T-17) | CLAUDE.md Commands | Test and coverage commands; Linux-only suites | — | PD-5 | logged
R3-P-34 (rules on P-22) | DUP of R3-P-22 | | | | | see R3-P-22
R3-P-35 (rules on P-23) | DUP of R3-P-20 | | | | | see R3-P-20
R3-P-36 (rules on P-24) | DUP of R3-P-21 and #12 | | | | | see R3-P-21
R3-P-37 (rules on P-25) | REJECT | inventory-and-packages.md | — | TS §7.1 L1208 gives `host` only as "Hostname substring" and never ties it to `ix_agent_hostname_trgm`. The DDL is already required exactly (database.md:12), and which index the planner uses is not a rule | none | REJECTED
R3-P-38 (rules on P-26) | split | web-ui.md | — | — | see R3-P-23 | see R3-P-23
R3-P-39 (rules on P-27) | DUP of R2-R-06 | | | | | APPLIED (R3-P-24)
R3-P-39a (rules on P-32) | DUP of R2-I-10 | CLAUDE.md:78–79 | `docs/spec/` and `work/` are in the layout | — | — | APPLIED (seen in the tree)
R3-P-39b (rules on P-36) | DECIDE | SKILL.md Phase A | PLAN task | — | PD-6 | logged
R3-P-39c (rules on P-37) | DECIDE | SKILL.md | Fallback when an agent type fails to load | — | PD-7 | logged
R3-P-39d (rules on P-40) | DUP of R2-I-19 | CLAUDE.md "Terms" | Glossary. TS §1.3 is in the implementer's slice; the acronym part goes with it | — | — | see R2-I-19
Also, P-12, P-17, P-18, P-19 and P-38 are now numbered entries #22, #24, #25, #26 and #23. P-39 is REJECTED as a question: TS §3.3 L224 "Only 429, 5xx and network errors are retried" already defines the behaviour. It is worth noting for the e2e load design (tester).

## C. New findings from the slice hunt

R3-P-40 | FIX | bit-format.md:22 | "it is never stored" is stronger than the spec. `scan_result.plugin_name_snap` does store the display name at run time | TS §5.2 L1035 "`display_name` … depends on another table, so it is not stored; the UI and API read it from this view"; L907 "`plugin_name_snap VARCHAR(400) NOT NULL, -- '<family> - <plugin name>' at run time`" | Before: "- Displayed plugin name: `<FamilyName> - <PluginName>`, from the `v_plugin` view; it is never stored." After: "- Displayed plugin name: `<FamilyName> - <PluginName>`, read from the `v_plugin` view (`display_name`, not stored in the catalog, TS §5.2); each `scan_result` keeps the run-time name in `plugin_name_snap` (TS §5.2)." | UNVERIFIED (reviewer to confirm)

R3-P-41 | FIX + ASK #27 | importer.md:34–38 | The numbered steps 3 and 4 give an order that TS §4.2 does not state. Whether the integrity check runs before or after the reconcile changes what it alerts on | TS §4.2 L540 "tasks still `running` when the manager starts are marked `failed`"; L542 "At start-up an integrity check compares row counts and a hash per policy with the files in both folders, and alerts if they differ." | See A4 | FIX UNVERIFIED (reviewer to confirm); #27 proposed

R3-P-42 | FIX (pointers) | auth-and-users.md:21 (#1); api.md:43 (#9); config-and-cli.md:39 (#7) | The markers answer numbered entries but have no pointer | The mapping of #1 to auth-and-users:21 and of #9 to api.md:43 was confirmed by the reviewer in round 2 (R2-R-02: "finds markers only for #1 (auth-and-users:21) and #9 (api.md:43)") | See A1 | #1 and #9 CONFIRMED (reviewer R2-R-02), ready to apply; the config-and-cli #7 pointer is UNVERIFIED (tester to confirm)

R3-P-43 | FIX (pointers) | bit-format.md:16 (#10); evaluator.md:13–14 (#11) | The TS §8.5 lines added by R2-I-12 have no entry to point at | TS §8.5 L1296 "Confirm the 14 operators and the output-normalisation rules with whoever writes the `.bit` content."; L1297 "Can one `.bit` file hold more than one `<Family>`? This spec assumes one." | See A2 | CONFIRMED (author implementer R2-I-12; planner confirmed), ready to apply

R3-P-44 | spec-internal | TS §4.4 L573 vs §4.3 L550 | The job-state table says `cancelled` is "Cancelled by an operator, or replaced by a newer job". Policy delete also cancels queued jobs ("its queued jobs are cancelled") | as quoted | Report only (open-questions §5). jobs-and-scans.md:16 already carries the delete case | logged

R3-P-45 | spec-internal | TS §6.2 L1122 vs §4.4 L581 | The route row says "Cancel queued or running jobs"; §4.4 also cancels dispatched jobs | as quoted | Report only (open-questions §5) | logged

R3-P-46 | checked, no finding | bit-format, importer, evaluator, jobs-and-scans | Rule sentences that I suspected had no source, but that do have one | `bit-format.md:53` "never plain `findmnt /tmp`" ← TS §3.7 L503; `:54` `/etc/nftables.conf`, `/etc/audit/rules.d/` ← TS §3.7 L501; `:15` spaced or mis-cased tags ← TS §1.4 L43; `:16` second Family = BIT002 ← SR §4.1 L257 "each required element present once"; `evaluator.md:8` "API process" ← TS §2.1 L105; `jobs-and-scans.md:13` "after a role check" ← TS §2.3 L133; `:25` "later start notices change nothing" ← TS §3.3 L222 "only the first start notice counts"; `bit-format.md:59` Sandbox ← TS §8.3 L1280 | — | VERIFIED (planner)

Also checked and complete in my slice:
- the element tree, order, occurrences and limits
- all BIT codes, severities and retired codes
- the BIT102 lists and the allowed uses
- the SR §3.6 steps 1–6
- the TS §4.1 pipeline, uploads, one folder per policy, locking and the watcher
- the §4.2 modes and the rebuild
- the §4.3 status override, rename and delete
- the §4.4 targets, schedules, job states, deadline, retry, late results, scan state and cancel (apart from R3-P-20)
- the §4.5 operators, normalisation, exit code, caps, re-evaluation (apart from R3-P-17) and score
- the §4.6 routes

## D. open-questions.md rework (done)

- Kept #1–#9 and their numbers. #6 now carries the R2-I-18 constraint, and #8 cites R2-R-01.
- Added #10–#27 from my slice and from P-12, P-17, P-18, P-19 and P-38. Reserved #28–#31 as **proposed** for the reviewer's R2-R-07, R2-R-08, R2-R-12 and R2-R-13, because I cannot receive the reviewer's request for numbers. If the reviewer rejects one, its entry is withdrawn and the number is not reused. The next free number is #32.
- Added a Status column. Only **agreed** entries may get a rule marker: #1–#12, #14, #18, #24 and #26.
- Added the marker table (23 lines: 9 numbered, 14 own questions), the TS §8.5 table, the process decisions PD-1 to PD-11, and the spec-internal inconsistencies, with 5 new ones.
- Rewrote the header. It no longer claims to be complete, and it describes the update path that actually exists.

## E. APPLY batches for `implementer`, and requests (not sent: no SendMessage tool; `main` to relay)

**A1 — APPLY: R3-P-42 (#1, #9). Confirmed by the reviewer in R2-R-02.**
- auth-and-users.md:21. Before: "ask whether it is also refused during an audit-sink outage." After: "ask whether it is also refused during an audit-sink outage (`work/open-questions.md` #1)."
- api.md:43. Before: "TS §4.3 says only that a deleted policy disappears from selection." After: "TS §4.3 says only that a deleted policy disappears from selection (`work/open-questions.md` #9)."
- Held until the tester confirms: config-and-cli.md:39. Before: "- `users create-admin <name>`: first admin; must enrol TOTP at first sign-in." After: "- `users create-admin <name>`: first admin; must enrol TOTP at first sign-in. How its initial password is set is open (`work/open-questions.md` #7)."

**A2 — APPLY: R3-P-43 (#10, #11). Authored by the implementer (R2-I-12), confirmed by the planner.** Spec: TS §8.5 L1296, L1297.
- bit-format.md:16. Before: "implement one and ask before relaxing it." After: "implement one and ask before relaxing it (`work/open-questions.md` #10)."
- evaluator.md:13. Before: "implement them as written and ask before changing them." After: "implement them as written and ask before changing them (`work/open-questions.md` #11)."
- evaluator.md:14. Before: "so implement them as written and add none):" After: "so implement them as written and add none; `work/open-questions.md` #11):"

**A3 — APPLY: ASK markers for agreed entries #12, #14, #18, #24 and #26.** Each marker states the gap only and chooses no behaviour.
- #12 (R3-P-07; reviewer confirmed R2-P-07). evaluator.md, insert after :26: "- **Open spec question:** `evaluate()` has no input for the runner `error` or for stderr size, yet TS §4.5 lists runner errors and output over the caps as ERROR cases with unit tests; ask where those two are decided, which `eval_detail` values are used and how such results re-evaluate (`work/open-questions.md` #12)." Spec: TS §4.5 L593, L600.
- #14 (R3-P-09; reviewer confirmed R2-P-09). importer.md:50, append after "Uploading the same name later brings it back as a new version.": " **Open spec question:** SR §3.6 adds 1 to `version` only when the file hash differs from `source_sha256`, so an identical re-upload would keep the old version; ask which applies and whether disabled schedules and `status_overridden` survive the revival (`work/open-questions.md` #14)." Spec: TS §4.3 L550; SR §3.6 L240.
- #18 (R3-P-13; reviewer confirmed R2-P-13 with a caveat). jobs-and-scans.md, insert after :16: "- **Open spec question:** whether disabling a policy cancels its jobs that are still `queued`; TS §4.3 says only "Running scans finish" (`work/open-questions.md` #18)." Spec: TS §4.3 L547.
- #24 (P-17; implementer confirmed in round 2). config-and-cli.md, insert after :14: "- **Open spec question:** the vault product and API, and the audit-sink wire format (syslog flavour, HTTPS body and authentication), are not specified (TS §8.6, §5.3) (`work/open-questions.md` #24)." audit-and-alerts.md:16: under the Sink heading, add "- Wire format: open, see `config-and-cli.md` (`work/open-questions.md` #24)." There is one marker only, to avoid the P-35 duplicate problem.
- #26 (P-19; implementer confirmed in round 2). enrolment-and-tokens.md:24, append to the Reject bullet: " **Open spec question:** TS §3.2 step 5 does not say what a rejected *re-enrolment* does to the existing agent row and its old token; the host has already replaced its token on disk (step 4) (`work/open-questions.md` #26)."

**A4 — APPLY after the reviewer confirms: R3-P-15 + R3-P-41 (importer.md:34–38).** Spec: TS §4.1 L528; §4.2 L540, L542.
Before:
```
- At start-up:
  1. Finish interrupted uploads: rename a temp file whose hash equals the policy's `source_sha256`, and delete any other temp file.
  2. Reconcile both folders with the catalog: import new or changed files, and delete (as below) policies whose files disappeared.
  3. Mark `running` tasks `failed`.
  4. Run the integrity check: compare row counts and a hash per policy with the files in both folders, and alert on any difference.
```
After:
```
- At start-up (TS §4.1):
  1. Before anything else, finish interrupted uploads: rename a temp file whose hash equals the policy's `source_sha256`, and delete any other temp file.
  2. Then reconcile both folders with the catalog: import new or changed files, and delete (as below) policies whose files disappeared.
- Also at start-up (TS §4.2, no order given): mark `running` tasks `failed`, and run the integrity check (compare row counts and a hash per policy with the files in both folders; alert on any difference).
```
The #27 marker is added only after a confirmer agrees: "**Open spec question:** whether the integrity check runs before or after the reconcile (`work/open-questions.md` #27)."

**A5 — APPLY after the reviewer confirms:** R3-P-14, R3-P-16, R3-P-17, R3-P-20, R3-P-21 and R3-P-40, using the before/after text in sections A and C. **After the tester confirms:** R3-P-22 and R3-P-23(b).

**Requests:**
- To `reviewer`: CONFIRM or REJECT the FIX calls R3-P-14, -15, -16, -17, -20, -21, -40 and -41, and the ASK calls #13, #15, #16, #17, #19, #20, #21, #22, #23 and #27. Challenge whether any of my ASKs is really answerable from the spec (FIX), especially #19 and #22, or not worth asking (REJECT). Rule on the reserved entries #28–#31 (your R2-R-07, -08, -12, -13).
- To `tester`: mechanically check every quoted spec line in sections A–C and the line numbers in `work/open-questions.md`; CONFIRM R3-P-22, R3-P-23(b), the config-and-cli #7 pointer, and #25 (P-18, your TS §6.5 slice); update your tester.md statuses per R2-P-23 (R3-P-26); note P-39 for the e2e load design.
- To `implementer`: apply A1–A3 now; apply A4 and A5 after their confirmers agree; use only numbers marked agreed. PD-9 and PD-10 come from your R2-I-03 and R2-I-11 and are logged as process decisions.

## F. Rulings for implementer (round 3, second pass; poll this table)

Source: `round3-reviewer.md` §0, §2–§4b, §6 and `round3-tester.md` §4–§5, `round2-tester.md`. "CONFIRMED (planner)" is the second-agent confirmation that brief rule 4 requires. Match the "Before" text in the author's report, not the line number.

**My own error, corrected:** batch A3 told you to append the #14 and #26 markers to existing bullets. That broke brief rule 3, which requires a line that starts with `**Open spec question:**`. R3-R-04 and R3-T-01 below fix it.

### Reviewer items

| Item | Ruling | Spec quote (line) | Action |
| --- | --- | --- | --- |
| R3-R-01 (bit-format:33, #2) | CONFIRMED (planner) | SR §4.1 L263 "`Operator` missing or not one of the 14 operators"; SR §4 L250 "if either fails, the content rules are not run" | none (already verified) |
| R3-R-02 (agent.md:17, #4) | CONFIRMED (planner). I fixed the #4 Sections column to "TS §3.6 vs TS §3.1, §3.3, §3.7" | TS §3.3 L226 "spooled on disk (max 50 MB, already redacted)" | none |
| R3-R-03 (api.md:65, #5) | CONFIRMED (planner) | TS §8.4 L1292 "Health endpoints: `/healthz` (liveness), `/readyz`"; L1288 (no route) | none |
| R3-R-04 (markers inside bullets) | CONFIRMED (planner) | brief rule 3 | apply. api.md is done; the rest is merged with R3-T-01 |
| R3-R-06 (runner-sandbox:31, the agent reports `runner_unavailable`) | CONFIRMED (planner). The text is already in the tree at :31 | TS §3 L152 "on any other setup the runner refuses to start and the agent reports `runner_unavailable`" | none (tester to verify) |
| R3-R-07 (runner-sandbox:55, OS matrix) | CONFIRMED (planner) | TS §8.3 L1279 "Runs in CI on Ubuntu 22.04, 24.04 and Debian 12, on amd64 and arm64" | none (verified) |
| R3-R-08 (enrolment-and-tokens:45, Load) | CONFIRMED (planner) | TS §8.3 L1282 "10,000 simulated agents heartbeating \| p95 heartbeat < 200 ms" | none (verified) |
| R3-R-09 (packaging:60, `serve`) | CONFIRMED (planner) | TS §8.7 L1359 "ExecStart=/usr/bin/bitscan-manager serve" | apply, if it is not already applied. The tree already reads "`ExecStart=/usr/bin/bitscan-manager serve`" at :60, so it may be done |
| R3-R-10 (security-invariants:26, viewers) | CONFIRMED (planner). It restates the spec's exact restriction and weakens nothing | TS §6.2 L1121 "`stdout` and `stderr` are included only for operator and admin"; TS §2.3 L138 "raw output only for operator and admin" | apply |
| R3-R-11 (security-invariants:10; implementer.md:28) | CONFIRMED (planner). The TS never says these items were "removed". Signing is absent and its risk is accepted (TS §8.1 L1246 "jobs are not signed"); the approval workflow is only a CLAUDE.md owner decision. The new wording keeps every "Never add" | TS §3.3 L210 "There is no push, wake-up or remote-shell channel"; L213 "There is no API to queue an ad-hoc command"; TS §6.2 L1129 "deliberately **no** endpoint to disable inventory collection or to run an ad-hoc command" | apply the reviewer's text |
| R3-R-12 (jobs-and-scans:23, state line) | CONFIRMED (planner) as written. I propose an extra amendment, R3-P-51 below, which waits for the reviewer | TS §4.4 L572, L575, L581, L582 | apply the reviewer's text |
| R2-R-07 FIX, agent.md:41 (`spool_overflow` in the results `error` field) | CONFIRMED (planner) | TS §3.3 L226 "each dropped plugin is reported as ERROR `spool_overflow`"; TS §6.5 L1184 `"error": null \| "spool_overflow" \| "runner_unavailable"` | apply |
| R2-R-07 FIX, agent.md:34 (`runner_unavailable` in the results `error` field) | **REJECTED** (planner). This is the case #28 asks about: TS §3 L152 says only "the agent reports `runner_unavailable`" for a runner that refused to start, and the heartbeat has only `last_error` (S-15). Writing "in the results `error` field" chooses an answer | TS §3 L152; TS §6.5 L1163, L1184 | do not apply; the #28 marker covers it |
| R2-R-11 (web-ui, runner helpers) | CONFIRMED (planner) | TS §3.7 L484 "The agent reports enabled helpers in every heartbeat, and the manager shows and audit-logs any change." | apply |
| R2-R-16 (security-invariants, accepted risk for plugin sockets) | CONFIRMED (planner). It adds an accepted risk and removes no rule | TS §3.7 L276 "Plugins **can** read any file and connect to local Unix sockets that accept any user, except those blocked in the unit."; L365 "plugins can therefore also reach abstract Unix sockets, which is accepted" | apply |
| R3-P-12a (#17 "chars" half → FIX, bit-format.md:18) | CONFIRMED (planner) | SR §2.1 L99 "1–128 chars"; SR §2.3 L119 "1–16,384 chars"; TS §5.2 L650, L656, L675 `VARCHAR(n)` | apply the reviewer's text: "Lengths are in characters, as `VARCHAR(n)` counts them (SR §2, TS §5.2)." |
| R3-P-50 (#22 dispatched/expired half → FIX, jobs-and-scans scan-state bullet) | CONFIRMED (planner) | TS §4.4 L580 "**Scan state** is derived from its jobs: `completed` … `partial` … `failed` … `cancelled` …; otherwise `queued` or `running`."; TS §5.2 L843, L867, L878 (shared enum) | apply the reviewer's text: "A scan never takes `dispatched` or `expired`; those `scan_state` values (TS §5.2) are for jobs." |
| R3-P-21 trimmed `eval_detail` text | CONFIRMED (planner, the author). I accept the reviewer's trim | TS §5.2 L901; TS §4.5 L599 | apply the reviewer's trimmed text |
| R3-P-14, -15+-41 (A4), -16, -17, -20, -40 | CONFIRMED by the reviewer (§4b) | as in sections A and C | apply |
| R3-P-22, R3-P-23(b), A1 config-and-cli #7 pointer | CONFIRMED by the tester (§4) | as in sections A and E | apply |

### Tester items

| Item | Ruling | Spec quote (line) | Action |
| --- | --- | --- | --- |
| R2-T-01 (api.md:31, agent-route error types) | CONFIRMED (planner) | TS §6.5 L1159 "These are the field-level contracts for the agent routes."; L1190 the eight values; TS §4.1 L522 "returns 409 `policy_managed_on_server`" | apply the tester's After text |
| R2-T-02 (database.md:28, schema owner and USAGE) | CONFIRMED (planner) | TS §5.2 L1027 "`ALTER SCHEMA public OWNER TO bitscan_owner;`"; L1028 "`GRANT USAGE ON SCHEMA public TO bitscan_app, bitscan_retention;`" | apply |
| R2-T-03 (enrolment-and-tokens:14, creates and revokes) | CONFIRMED (planner) | TS §6.2 L1116 "`/enrollment-tokens` \| Create / revoke enrolment tokens \| admin, TOTP session"; TS §5.2 L756 `revoked_at` | apply |
| R2-T-04 (web-ui type-ahead) | ASK, numbered **#32**, agreed (tester, planner) | TS §7.3 L1223 "Search box with type-ahead (top 10 names)"; TS §6.2 L1117 | apply the tester's marker with `#NEW-T1` → `#32` |
| R2-T-05 (`list_sha256` recompute) | ASK **#33**, agreed (tester, planner). The FIX half is CONFIRMED (planner): drop the invented "Recompute … same as the agent" (inventory-and-packages:17) and "the manager computes it identically" (agent.md:46) | TS §3.4 L241 "If `list_sha256` differs from the last snapshot it also upserts `agent_package` rows"; TS §6.1 L1072 "The manager re-checks every size cap itself" (caps, not the hash) | apply the tester's After text and marker, with `#NEW-T2` → `#33` |
| R2-T-06 (sources on Tests lines, a–j) | CONFIRMED (planner). I spot-checked every source: TS §3.4 L230 (`/readyz`), TS §5.3 L1051, TS §8.4 L1289, TS §4.4 L557 (cron timezone), TS §6.2 L1087–L1088, TS §4.5 L601, TS §4.1 L526, TS §6.3 L1142, TS §3.4 L241, TS §7.2 L1219 | as listed in round2-tester.md | apply |
| R2-T-07 | DECIDE → PD-12 (logged) | none | none |
| R2-T-08 | DUP of PD-8 (PD-8 extended) | none | none |
| R3-T-01 (4 embedded markers) | CONFIRMED (planner). It supersedes my A3 placement | brief rule 3 | apply the tester's split text for auth-and-users:21, bit-format:20, enrolment-and-tokens:24 (as a sub-bullet) and importer.md:50 |
| R3-T-02, R3-T-03, R3-T-04 (my file) | APPLIED (planner). Part 2 is rebuilt from a fresh grep: 28 markers, 14 numbered and 14 own. Every citation has its TS or SR prefix. PD-8 is extended and PD-12 added | none | none |

### New planner item

R3-P-51 | FIX | jobs-and-scans.md:23 (after R3-R-12) | The reviewer's line still leaves out the inventory transitions | TS §3.4 L230 "uploads it with `PUT /api/v1/agent/{id}/inventory?job_id=…`, which completes the job"; L244 "dispatched but not uploaded within 30 minutes, or whose upload is rejected (413 or 422), becomes `failed`"; TS §3.3 L222 (only compliance jobs send a start notice) | Append to the R3-R-12 line: "; inventory jobs: `dispatched → completed` (upload) or `dispatched → failed` (no upload within 30 min, or upload rejected) (TS §3.4)." | UNVERIFIED (reviewer to confirm)

### Marker texts for newly agreed entries (apply each as its own `- **Open spec question:**` line)

- **#13** evaluator.md, after the numeric-operators sub-bullet: the R3-P-08 text. The reviewer suggested listing only exponents, `.5` and `5.`; I keep `nan`/`inf`/`_` in the question, because "floats" can be read as IEEE floats. If the reviewer objects, list only the three forms, since either version chooses no behaviour.
- **#15** bit-format.md, after the BIT007 bullet: the R3-P-10 text.
- **#16** bit-format.md, after the Reject list: the R3-P-11 text.
- **#17** bit-format.md, after the Limits bullet: "- **Open spec question:** SR §2 says "trimmed" only for `PolicyName`, `Execute` and `ExpectedResult`; ask whether `FamilyName`, `PluginName` and the two descriptions are trimmed before the length and empty checks (`work/open-questions.md` #17)."
- **#20** importer.md, after the Rebuild bullet: the R3-P-18 text.
- **#21** importer.md, after the `bit_import` bullet: the R3-P-19 text.
- **#22** jobs-and-scans.md, after the scan-state bullet: "- **Open spec question:** TS §4.4 says only "otherwise `queued` or `running`"; ask when a scan moves from `queued` to `running` (`work/open-questions.md` #22)."
- **#23** importer.md, after the alerts bullet ("Every import is audit-logged and alerts …"): "- **Open spec question:** whether `skipped` automatic imports, and each file of a rebuild, raise the immediate "policy imported" alert (TS §4.1, §8.4) (`work/open-questions.md` #23)."
- **#25** enrolment-and-tokens.md, after the Heartbeat bullet: "- **Open spec question:** the TS §6.5 heartbeat fields `last_error`, `spool_bytes`, `current_job_id`, `last_pull_at` and `uptime_s` have no `agent` column, no writer is named for `agent_ip_seen`, and an `enrolled` agent that never heartbeats has no age for the TS §3.3 status thresholds (`work/open-questions.md` #25)."
- **#27** importer.md start-up: the A4 marker text.
- **#28–#31**: the reviewer's texts, `round3-reviewer.md` §3 (R2-R-07, -08, -12, -13).
- **#32**, **#33**: the tester's texts, `round2-tester.md` R2-T-04 and R2-T-05, with the numbers filled in.
- **#19**: withdrawn. Add no marker. R3-P-14's "Host compliance score" covers it.

## G. Post-IMPLEMENTER-DONE verification (planner, third pass)

The tree has **44** `- **Open spec question:**` markers, each on its own line (enrolment-and-tokens:25 is a sub-bullet). `.claude/**` holds **35** `(work/open-questions.md #N)` pointers. Every pointer resolves to an **agreed** entry. None points at #19 (withdrawn) or above #33. Every agreed entry has at least one marker or pointer.

**Marker wording vs §F**

All match, word for word:
- #13 evaluator:19 (the R3-P-08 text, nan/inf/_ kept)
- #15 bit-format:34
- #16 bit-format:32
- #17 bit-format:19
- #20 importer:45
- #21 importer:22
- #22 jobs-and-scans:38
- #23 importer:27
- #25 enrolment-and-tokens:33
- #27 importer:40
- #28 agent:36, #29 runner-sandbox:18, #30 agent:31 and #31 runner-sandbox:27, all in the reviewer's §3 text
- #32 web-ui:27 and #33 inventory-and-packages:18, in the tester's text with numbers filled in

**Confirmed FIX lines in my slice: present and correct against the spec**

| Item | Where |
| --- | --- |
| R3-P-12a | bit-format:18 |
| R3-P-14 | evaluator:30, "Host compliance score" |
| R3-P-15 + R3-P-41 | importer:36–39 |
| R3-P-16 | jobs-and-scans:18 |
| R3-P-17 | evaluator:31 |
| R3-P-20 | jobs-and-scans:36 |
| R3-P-21, trimmed | evaluator:27 |
| R3-P-22 | api.md:40 |
| R3-P-23(b) | web-ui:26 |
| R3-P-40 | bit-format:24 |
| R3-P-50 | jobs-and-scans:37 |
| R3-R-10 | security-invariants:27 |
| R3-R-11 | security-invariants:10, implementer.md:28 |
| R3-R-12 | jobs-and-scans:23 |
| R2-R-11 | web-ui:29 |
| R2-R-16 | security-invariants:21 |
| R2-T-05 FIX half | inventory-and-packages:17, agent.md:48 |
| R2-T-01, -02, -03, -06 | grep hits in api.md, database.md, enrolment-and-tokens.md, jobs-and-scans.md, testing.md |

agent.md:35 is unchanged ("report `runner_unavailable`" without "results `error` field"). That is correct: I rejected that part of R2-R-07.

**Mismatches for the implementer:** none in wording.

**One item not applied:** R3-P-51 (append the inventory transitions to jobs-and-scans:23). This is expected: it never had a confirmer, so it stays UNVERIFIED. It goes to `main` as an open FIX item; it is not a defect.

**Not checked by me:** whether the implementer's own slice and its hygiene edits match the spec. The reviewer and tester own those checks.

## Exchange log

- No SendMessage tool was available in this session, so no message was sent or received. The requests above are written here for `main` to relay. The brief's mandatory exchanges (at least one message to each teammate) could not be done by message. They are recorded here instead: one request each to the reviewer, the tester and the implementer (section E).
- Evidence used in place of replies: the round-2 confirmations recorded in `round2-planner.md` §D (reviewer: R2-P-07, R2-P-09, R2-P-13; implementer: P-15, P-17, P-19, R2-I-12) and `round2-reviewer.md` R2-R-02 (the #1 and #9 marker mapping).
- I observed the implementer's concurrent edits in the tree and checked them against the spec: R2-R-05 (jobs:30), R2-R-09 (bit-format:59), R2-I-12 (bit-format:16, evaluator:13), the `bits/samples/` split (bit-format:48, :50, :57) and R2-I-10 (CLAUDE.md:78–79). All match the spec, or the layout for the non-spec items.

- Second pass (resumed by `main`):
  - I read `round3-reviewer.md` (§0, §2–§4b, §6, §7), `round3-tester.md` (§4, §5) and `round2-tester.md`.
  - Reviewer → planner: #28–#31 agreed with the reviewer's wording. #17 and #22 are split, #19 is rejected, and the #4 Sections column is fixed. S-14 and S-15 are added to §5. Confirmations were requested for R3-R-04, R3-R-06..12, R2-R-11, R2-R-16 and the halves of #17 and #22. All of that is done in §F. I REJECTED one item: the agent.md:34 part of R2-R-07.
  - Tester → planner: the tester confirmed R3-P-22, R3-P-23(b), the #7 pointer and #25 (now agreed). It asked me to apply R3-T-02..04, number its two ASKs (#32, #33) and add PD-12. All done.
  - The rulings for the implementer are in §F above and in the "Numbers assigned" list in `work/open-questions.md`.
  - The marker table was rebuilt from a fresh grep: 28 markers. It needs one more refresh after the implementer's last batch.

## Counts

- FIX: 18.
  - Applied in the tree: 5 (R3-P-01, -02, -03, -05, -25).
  - Confirmed and ready to apply: 2 (R3-P-42 for #1 and #9, R3-P-43).
  - Waiting for a confirmer: 11 (R3-P-14, -15, -16, -17, -20, -21, -22, -23(b), -26, -40, -41).
- ASK: 18 new numbered entries (#10–#27).
  - Agreed: 7 (#10, #11, #12, #14, #18, #24, #26). #10 and #11 get pointers through A2, and the other 5 get markers in A3.
  - 4 more are reserved for the reviewer (#28–#31).
- DECIDE: 11 (PD-1 to PD-11).
- REJECT: 4 (R3-P-27, R3-P-37, R3-P-23(c) import history, P-39 as a question).
- DUP: 10 (R3-P-04, -23(a), -24, -29, -34, -35, -36, -39, -39a, -39d).
- Second pass:
  - Confirmed 26 teammate FIX items and rejected 1:
    - Confirmed, reviewer's: R3-R-01..04, R3-R-06..12, the agent.md:41 part of R2-R-07, R2-R-11, R2-R-16, R3-P-12a and R3-P-50.
    - Confirmed, tester's: R2-T-01, -02, -03, the FIX half of -05, -06, and R3-T-01.
    - Applied to my own file: R3-T-02..04.
    - Rejected: the agent.md:34 part of R2-R-07, because it chooses the #28 answer.
  - One new FIX: R3-P-51 (inventory transitions).
  - ASK status:
    - 28 entries are agreed (#1–#18, #20–#33).
    - #19 is withdrawn.
    - #32 and #33 are newly numbered.
  - DECIDE: PD-12 added and PD-8 extended, so 12 in total.
  - Spec-internal: S-11..S-16 and two tester notes added.
