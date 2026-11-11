# M11 gate REVIEW: M11 as a whole

Reviewer: reviewer-m11. Round 2 (gate r1, TASK-261), 2026-11-11. Round 1 was on 2026-11-09. This file supersedes `work/reviews/M11-closing.md`.

Verdict: CHANGES_REQUESTED. Only one condition is left: tester-m11t's CHK-M11-387 re-measurement on the real `m0006` migration with `SCAN_CHUNK = 12`. I will turn this verdict to APPROVED as soon as that re-measurement shows every retention chunk inside the 300 s `statement_timeout` at fleet size. Everything else in the gate is approved, and no code change is requested.

## Round 2 (gate r1, TASK-261)

The user decided on 2026-11-11: (1) add the three #151 indexes, as an owner-approved TS §5.2 change (`68d3881`) with migration `m0006` and `SCAN_CHUNK` 12; (2) accept the PR's CI `package.yml` "Double build is byte-identical" job as G39's evidence.

- **Finding 1 (CHK-M11-387):** fixed in the tree as the user chose. TASK-261 is approved (`work/reviews/TASK-261.md`). `m0006` reproduces the three spec lines exactly: it adds no grant, follows `m0005`, and its downgrade only raises. G19 matches the new DDL, and its 6/6 plants are red, the "`m0006` removed" before-state included.
  - **Open, the last condition:** the decision asks for CHK-M11-387 to be re-run on the real migration, and that `SCAN_CHUNK` 12 be confirmed by it. At round 1 the indexes existed only on the throwaway database and the chunk was 100. The gate r1 report says this re-measurement "is tester-m11t's and is not part of this verdict", and `work/reports/CHK-M11-387-test.md` has not been updated since 2026-11-09.
  - **What the re-measurement must show, for APPROVED:** on the real migration, at the CHK-M11-387 fleet sizes, both of the following:
    - every scans chunk, including a backlog of 12 fleet-wide scans, and every 1,000-job inventory chunk finishes inside 300 s;
    - a full `run_retention` pass deletes everything due, with no step `failed`.
- **Finding 2 (G39):** closed by the user's decision (2). G39 stays NOT RUN locally, and the merge waits for the PR's double-build job to be green (decisions 2026-11-11 (2)).
- **Finding 3 (process: no full suite at the wave ends):** unchanged, a should-fix for M12. The gate ran G18 twice: 11,908 tests, then 11,909 in r1.
- **Finding 4 (the `ruff()` encoding nit):** fixed in `fe0bd24`. The S608 and `re`-ban rows now pass on Windows too; I re-ran the CODE rows, 89 passed.
- **Finding 5 (the REQ-088 edit missing from the PD-51 list):** fixed. It is now in the r1 PD-51 table.
- **r1 re-runs:**
  - G18: 11,909/11,909 (two M7 timing bounds failed under shared load and pass alone; they are in code TASK-261 doesn't touch).
  - G5: 98.5920 %.
  - G83: 46/46.
  - Retention suites green.
  - README walks: 4/4.
  - G41, the nightly and N / N−1 rows and the web gates were not re-run. They take any migration head, and there is no web change. The PR's CI and the next nightly cover them.
- **Spec placement:** the lead applied the owner's spec text in its own commit (`68d3881`), as the decision authorised. Only those three lines and the decision row changed. No reviewer action is needed on the spec, and the migration matches it.
- **REQ-275 and REQ-290** move from "open" to "fixed, pending the re-measurement".
- No other change to the round 1 analysis below.

## Round 1 (2026-11-09)

### Read

- `work/reports/M11-gate-test.md` (tester-m11g, tree `c090303`, docs re-runs on `c62da73`, committed in `d25538c`).
- `work/reports/CHK-M11-387-test.md` (tester-m11t).
- `tests/m11/report.md`, with the gate folded in, and `work/reports/M11-e2e-test.md`.
- `work/decisions.md`, the rows of 2026-11-08 and 2026-11-09.
- The 29 task reviews in this folder (TASK-232 to TASK-260), all APPROVED, with no open blocking or should-fix finding.
- The gate test changes: `manager/tests/test_security_m11.py` (new), the CHK-M9-276 (M11) rewrite in `manager/tests/test_security_m9.py`, and `tests/m11/test-plan.md`.

### REQ-264 to REQ-292: coverage

| REQ | Covered by (task, check rows) | Status |
| --- | --- | --- |
| 264 scan list | TASK-232, 234, 240, 244; CHK-M11-105 to -112, -155 to -162, -213 to -217, -455 to -457 | covered |
| 265 scan detail and score | TASK-240, 244; CHK-M11-155 to -160, -218 | covered |
| 266 host history | TASK-234, 240, 244; CHK-M11-112, -161, -219 | covered |
| 267 results | TASK-233, 235, 241, 244; CHK-M11-118 to -131, -082, -165 to -169, -220, -221 | covered |
| 268 raw output for operator and admin only | TASK-233, 235, 241, 244; CHK-M11-001, -002, -007, -125, -165, -222 to -224, the G83 viewer row | covered |
| 269 results CSV | TASK-233, 241, 244; CHK-M11-006 to -011, -126, -167, -168, -225, -226 | covered |
| 270 re-evaluate route | TASK-232, 243; CHK-M11-200 to -209, the G83 refusal and sink rows | covered |
| 271 the only verdict changer | TASK-243; CHK-M11-206, -413, the G83 one-writer row (CHK-M11-242) | covered |
| 272 layering, SQL, grants, logs, frozen files | every manager task; G1 plants -344, -345; CHK-M11-243 to -245, -248, -459 | covered (38 frozen pins verified, below) |
| 273 contract and client | TASK-232, 239; G6, G16, G34, CHK-M11-230 to -235, -246 | covered |
| 274 retention rules | TASK-236; CHK-M11-040 to -048, -080 | covered |
| 275 retention deletes | TASK-237, 242, 245; CHK-M11-135 to -144, -175 to -181, -192, -451 | covered at test size; **FAIL at fleet size (CHK-M11-387)**; round 2: fixed by TASK-261, pending the re-measurement |
| 276 audit retention and checkpoints | TASK-236, 238, 242; CHK-M11-141, -182 to -187, -194 | covered (at fleet size the audit step fits: 0.12 s per chunk in CHK-M11-387) |
| 277 retention scheduling | TASK-245; CHK-M11-196 to -199, -450 to -454 | covered |
| 278 retention safety | TASK-236, 237, 242; CHK-M11-150 to -154, -188 to -191, -193 | covered |
| 279 to 283 screens | TASK-239, 246 to 251, 256, 258; the TP-M11-14 rows, G84 | covered |
| 284 web rules | the same tasks; G12 to G16, plants -360 to -362, -375 | covered |
| 285 nightly chain | TP-M11-18, TASK-254; G85, hosted run 42488215323 (19/19); plants -370, -371 | covered |
| 286 nightly schedule and report | TASK-254; G87 (a plain push is skipped; plants -373, -374 red on throwaway branches) | covered; `actionlint` NOT RUN (REQ-286 (3) allows that) |
| 287 manager N with agents N and N−1 | TP-M11-19; G86 compat-a 10/10, upgrade walk CHK-M11-307 16/16, plant -372 | covered |
| 288 agent N with manager N−1 | built on the user's "both ways" (decisions 2026-11-08 (1)); G86 compat-b 8/8 | covered |
| 289 README and runbook | TASK-252, 253, 259, 260; CHK-M11-380 to -386 | covered |
| 290 release readiness | TASK-253; CHK-M11-384 | **not yet.** The changelog and checklist are done. "Every M11 gate green on the M11 head" waits on findings 1 and 2 (round 2: on the re-measurement and the PR's double build) |
| 291 harness carries | TP-M11-17; CHK-M11-290 (r2: 72/76, the 4 NOT RUN as planned) | covered |
| 292 M11 tests | G80 to G87, G5 98.5920 %, the mutation table | covered |

No REQ is uncovered. REQ-275 at fleet size and REQ-290 are the two open ones.

### Security invariants

All hold, and none was weakened in M11:
- **No ad-hoc command route:** checked by the route walk and the request schemas; plant -346 is red.
- **Nothing that disables inventory:** CHK-M11-450. There is no push channel, no signing and no client certificate.
- **Viewers never receive stdout or stderr:** the viewer SQL variant selects NULL, the viewer model omits the keys and the CSV omits the columns. The canary is absent in every layer.
- **Sensitive action:** `POST /scans/{id}/reevaluate` uses `require_totp_session()`: admin only, API tokens refused, and refused at 15 minutes or more of sink outage.
- **CSV:** every cell goes through `escape_cell`.
- **Code checks:** SQL is parameterised (S608 plants red), and RE2 replaces `re` (TID251 plants red).
- **Token prefixes per router:** G83's token-group row stores cross-group hashes in the other group's table, so only the prefix check can refuse them.
- **Retention:** it runs only as `bitscan_retention`, deletes only the nine TS §5.2 retention tables, runs no DDL, and its only INSERT is the checkpoint.
- **Dependencies and logs:** there was no migration at round 1 (round 2 adds `m0006` under the owner's decision) and no new dependency (the lock diff is empty). Logs carry counts and types only.

### No gate lowered

- `fail_under` stays 85, and `precision` went from 2 to 4 (TASK-255), which is stricter.
- `vite.config.ts` gained only `testTimeout` (TASK-257). The assertions are the same and the timeout is still a bound.
- The only workflow change is the new `e2e.yml`.
- The two NOT RUN rows carry their reasons:
  - G39;
  - the TS §8.3 load, Debian 12 and arm64 rows.
- G7 to G11, G17, G35 and G36 are left to CI by the gate plan, because no agent or unit file changed. Since `6efe0fb`, `agent`, `deploy/systemd` and `deploy/dbus` are unchanged, and `deploy/debian` changed only its changelog.

### PD-51 old → new list

These rows are complete:
- CHK-M3-233 / CHK-M9-219 (stop record), changed by TASK-245.
- CHK-M9-218 (job set): unchanged for the three-argument runner; the four-job row is new (TASK-245).
- CHK-M9-285 → CHK-M11-386 (README text, TASK-252).
- CHK-M5-280 → CHK-M5-280 (M11) (nav entries, TASK-251).
- **CHK-M9-276 → CHK-M9-276 (M11)** (this gate).

I checked the CHK-M9-276 rewrite myself:
- It is still an equality: M9's seven operations plus exactly M11's five under `/scans`.
- The five are asserted to take no body.
- Every body and parameter check is kept for all twelve.
- The sixth-operation plant is red.

Finding 5 covers the one REQ-088 edit that was not in the table.

### Mutation table

- **Planned rows:** every planned row from CHK-M11-320 to -374 is present (I checked the ids; none is missing). Each is red where the table names it.
- **G87 plants:** -373 and -374 are red on hosted runs 42594910837 and 42594935136.
- **Extras:** the tester extras -375 to -440 and -455 to -458, and the three gate plants (SEC-tok-user, SEC-tok-agent, SEC-reads-operator-only), are present.
- **Unused and non-plant ids:** -441 to -449 are declared unused. -450 to -454 and -459 are declared checks, not plants.
- **-322 surviving G83:** accepted.
  - The planted `stdout: null` in the service mapping is dropped by the route's viewer model (`ScanResultItem`, pydantic `extra="ignore"`) before any byte reaches a viewer. G83 tests what a viewer can observe, so it cannot see the plant.
  - The table places -322 in G80 and G82, and it is red in both.
  - Two independent layers stand between that fault and a viewer, as plan TASK-235 §3 intended. This is not a gap.
- **The G30 and G33 plant notes are accurate:**
  - the request-schema form of the G30 plant is caught by G6, and the response form by G30;
  - -341 cannot be observed in G33's sweep suites, and is red in G81 and G83.

  The planner can fix the gate-table wording.

### Verified myself

- **Frozen-file pins:** all 38 pins in `test_security_m11.py` equal `git show 6efe0fb:<path> | sha256sum`, with 0 mismatches.
- **Lint:** `ruff check` and `ruff format --check` are clean on both gate test files.
- **Local G83 run:** 35 CODE rows passed. The 16 failures are the S608 and `re`-ban rows, caused by a Windows-only encoding problem (finding 4). They are green in WSL, 45/45.
- **CHK-M11-387 `EXPLAIN (ANALYZE)`:** the time is entirely in the `scan_job_retry_of_fkey` and `scan_result_reeval_job_id_fkey` RI triggers, about 0.41 to 0.50 s per deleted job. The delete itself takes 4 ms. With the three indexes, the same 1,022-job scan takes 940 ms. This confirms the tester's diagnosis.

### Findings (round 1)

1. **blocking: CHK-M11-387. REQ-275 is not met at fleet size (TS §5.3 L1049; #151). It is a merge blocker.** *(Round 2: fixed by TASK-261, pending the re-measurement.)*
   - **What fails:** as built, at 10,000 hosts, the scans step and the inventory-jobs step each fail on their first chunk every night (`QueryCanceled` at 300 s), and delete nothing.
     - `scan_job` grows by about 40,000 rows a day, which makes each later attempt slower.
     - The oldest fleet scan blocks the scans step for good.
   - **Why the earlier acceptance doesn't cover it:** the user accepted slow but working retention for v1 (decisions 2026-11-08 (2), #151 (a)), on the premise that "retention runs once a day, in the background". This retention does not work at all, and TS §5.3 L1049 cannot be met as built.
   - **It points to option (b), the three #151 indexes:** `scan_job (retry_of)`, `scan_job (scan_id)` and `scan_result_reeval (job_id)`. It is the only measured option that fits: 25 to 33 s a night, 0.9 ms per job. It needs an owner-approved edit of TS §5.2 and one migration, outside M11's "no migration" scope, so the decision is the user's.
   - **Why the other options don't fit:**
     - (a1), halving `SCAN_CHUNK` (decisions 2026-11-09 (3)), cannot fix it. One scan of more than about 600 hosts is a single statement over 300 s even at `SCAN_CHUNK` = 1, because the cost is per job, not per scan.
     - (a2), a smaller `JOB_CHUNK`, helps inventory only, and only while `scan_job` stays small. Scans stay blocked.
     - (c), a longer timeout for the retention session, means chunks of 1.5 h or more that hold locks, a nightly run of 4.5 to 7 h, and growth with the fleet. It only delays the failure.
   - **If (b) is chosen:** a backlog chunk of 100 fleet scans would still take 20 to 27 min (the tester's table). So the fix round also needs `SCAN_CHUNK` at about 12 or less, or a chunk bounded by job count, with G80, G81, G83's retention rows and G5 re-run, as decisions 2026-11-09 (3) already provides.
2. **should-fix (merge rule): G39 NOT RUN after a safety-check refusal.** *(Round 2: closed by the user's decision 2026-11-11 (2).)*
   - The tester stopped and did not work around the refusal, which is correct.
   - The M11 gate rule (`work/tasks.md`, "M11 gate": "M11 does not merge with such a row until the user decides whether it is a gate exception") needed the user's decision.
   - The offered cover, which I consider sound:
     - the PR's `package.yml` "Double build is byte-identical" job;
     - the agent is unchanged since M10's identical builds;
     - 95/95 other build checks passed.
3. **should-fix (process, for M12): no full manager suite at the wave ends.**
   - The speed rules ask for the full suite per wave. Only targeted runs were recorded, so CHK-M9-276, stale since TASK-232 in W1, first surfaced at the gate.
   - It is resolved in the tree: the PD-51 rewrite, then G18 at 11,908/11,908.
   - M12 should run G18 at each wave end.
4. **nit: `manager/tests/test_security_m11.py:331` `ruff()` runs `subprocess.run(text=True)` without `encoding="utf-8"`.** *(Round 2: fixed in `fe0bd24`.)*
   - On Windows, a module with non-ASCII text reaches ruff as invalid UTF-8, so the S608 and `re`-ban rows fail locally.
   - They are green in WSL and CI.
5. **nit: the gate's PD-51 table omits the REQ-088 edit of `manager/tests/test_invariants_m3.py`.** *(Round 2: added to the r1 PD-51 table.)*
   - The edit is the M3 query-parameter allow-list, now with the M11 paths pinned to exact sets (`M11_QUERY`), made in TASK-232's TEST.
   - It is an earlier check changed by requirement (REQ-088 as changed in M11). It is recorded in TASK-232's report and approved in `TASK-232.md`, so it is not lost, but it belongs in the old → new list.
