# M11 gate REVIEW: M11 as a whole

Reviewer: reviewer-m11, 2026-11-09. Round 1. This supersedes `work/reviews/M11-closing.md`, which reviewed the same gate before `CHK-M11-387-test.md` existed. Its findings are carried here.

Verdict: CHANGES_REQUESTED, merge blocked. The M11 code, tests and docs are approved. The merge waits on two user decisions: CHK-M11-387 (finding 1, blocking) and the G39 gate exception (finding 2).

## Read

- `work/reports/M11-gate-test.md` (tester-m11g, tree `c090303`, docs re-runs on `c62da73`, committed in `d25538c`).
- `work/reports/CHK-M11-387-test.md` (tester-m11t).
- `tests/m11/report.md` (with the gate folded in) and `work/reports/M11-e2e-test.md`.
- `work/decisions.md`, rows of 2026-11-08 and 2026-11-09.
- The 29 task reviews in this folder (TASK-232 to TASK-260), all APPROVED with no open blocking or should-fix finding.
- The gate test changes: `manager/tests/test_security_m11.py` (new), the CHK-M9-276 (M11) rewrite in `manager/tests/test_security_m9.py`, and `tests/m11/test-plan.md`.

## REQ-264 to REQ-292: coverage

| REQ | Covered by (task, check rows) | Status |
| --- | --- | --- |
| 264 scan list | TASK-232, 234, 240, 244; CHK-M11-105 to -112, -155 to -162, -213 to -217, -455 to -457 | covered |
| 265 scan detail and score | TASK-240, 244; CHK-M11-155 to -160, -218 | covered |
| 266 host history | TASK-234, 240, 244; CHK-M11-112, -161, -219 | covered |
| 267 results | TASK-233, 235, 241, 244; CHK-M11-118 to -131, -082, -165 to -169, -220, -221 | covered |
| 268 raw output for operator and admin only | TASK-233, 235, 241, 244; CHK-M11-001, -002, -007, -125, -165, -222 to -224, G83 viewer row | covered |
| 269 results CSV | TASK-233, 241, 244; CHK-M11-006 to -011, -126, -167, -168, -225, -226 | covered |
| 270 re-evaluate route | TASK-232, 243; CHK-M11-200 to -209, G83 refusal and sink rows | covered |
| 271 the only verdict changer | TASK-243; CHK-M11-206, -413, G83 one-writer row (CHK-M11-242) | covered |
| 272 layering, SQL, grants, logs, frozen files | every manager task; G1 plants -344, -345; CHK-M11-243 to -245, -248, -459 | covered (38 frozen pins verified, below) |
| 273 contract and client | TASK-232, 239; G6, G16, G34, CHK-M11-230 to -235, -246 | covered |
| 274 retention rules | TASK-236; CHK-M11-040 to -048, -080 | covered |
| 275 retention deletes | TASK-237, 242, 245; CHK-M11-135 to -144, -175 to -181, -192, -451 | **covered at test size; FAIL at fleet size (CHK-M11-387)** |
| 276 audit retention and checkpoints | TASK-236, 238, 242; CHK-M11-141, -182 to -187, -194 | covered (the audit step fits at fleet size: 0.12 s per chunk in CHK-M11-387) |
| 277 retention scheduling | TASK-245; CHK-M11-196 to -199, -450 to -454 | covered |
| 278 retention safety | TASK-236, 237, 242; CHK-M11-150 to -154, -188 to -191, -193 | covered |
| 279 to 283 screens | TASK-239, 246 to 251, 256, 258; TP-M11-14 rows, G84 | covered |
| 284 web rules | the same; G12 to G16, plants -360 to -362, -375 | covered |
| 285 nightly chain | TP-M11-18, TASK-254; G85 hosted run 42488215323 (19/19), plants -370, -371 | covered |
| 286 nightly schedule and report | TASK-254; G87 (plain push skipped; plants -373, -374 red on throwaway branches) | covered; `actionlint` NOT RUN (REQ-286 (3) allows that) |
| 287 manager N with agents N and N−1 | TP-M11-19; G86 compat-a 10/10, upgrade walk CHK-M11-307 16/16, plant -372 | covered |
| 288 agent N with manager N−1 | built on the user's "both ways" (decisions 2026-11-08 (1)); G86 compat-b 8/8 | covered |
| 289 README and runbook | TASK-252, 253, 259, 260; CHK-M11-380 to -386 | covered |
| 290 release readiness | TASK-253; CHK-M11-384 | **not yet.** The changelog and checklist are done, but "every M11 gate green on the M11 head" waits for findings 1 and 2 |
| 291 harness carries | TP-M11-17; CHK-M11-290 (r2 72/76, the 4 NOT RUN planned) | covered |
| 292 M11 tests | G80 to G87, G5 98.5920 %, the mutation table | covered |

No REQ is uncovered. REQ-275 at fleet size and REQ-290 are the two open ones.

## Security invariants

All hold, and none was weakened anywhere in M11:
- There is no ad-hoc command route. The route walk and request schemas were checked, and plant -346 is red.
- There is no push channel, no inventory switch (CHK-M11-450), no signing and no client certificates.
- Viewers never receive stdout or stderr. The viewer SQL variant selects NULL, the viewer model omits the keys, and the CSV omits the columns. The canary is absent in every layer.
- The sensitive action (`POST /scans/{id}/reevaluate`) is on `require_totp_session()`: admin only, API tokens refused, and refused while the audit sink has been down for 15 minutes or more.
- Every CSV cell goes through `escape_cell`.
- SQL is parameterised (S608 plants red), and RE2 is used, not `re` (the TID251 plants are red).
- Token prefixes are enforced per router. G83's token-group row stores the cross-group hashes in the other group's table, so only the prefix check can refuse them.
- Retention runs only as `bitscan_retention`, deletes only the nine TS §5.2 retention tables, runs no DDL, and its only INSERT is the checkpoint.
- There is no migration and no new dependency (the lock diff is empty).
- Logs carry counts and types only.

## No gate lowered

- `fail_under` stays at 85, and `precision` went from 2 to 4 (TASK-255), which is stricter.
- `vite.config.ts` gained only `testTimeout` (TASK-257): the same 741/755 assertions, and still a bound.
- The only workflow change is the new `e2e.yml`.
- The two NOT RUN rows (G39; the load, Debian 12 and arm64 rows of TS §8.3) carry their reasons. G7 to G11, G17, G35 and G36 are left to CI by the gate plan, because no agent or unit file changed. `git diff --stat 6efe0fb` over `agent`, `deploy/systemd` and `deploy/dbus` is empty; under `deploy/debian`, only `changelog` changed.

## PD-51 old → new list

These rows are complete:
- CHK-M3-233 / CHK-M9-219 (stop record), changed in TASK-245.
- CHK-M9-218 (job set): unchanged for the three-argument runner, and the four-job row is new (TASK-245).
- CHK-M9-285 to CHK-M11-386 (README text, TASK-252).
- CHK-M5-280 to CHK-M5-280 (M11) (nav entries, TASK-251).
- **CHK-M9-276 to CHK-M9-276 (M11)** (this gate).

I checked the CHK-M9-276 rewrite myself. It is still an equality: M9's seven operations plus exactly M11's five under `/scans`. It also asserts that the five take no body, and keeps every body and parameter check for all twelve. The sixth-operation plant is red. See finding 5 for one REQ-088 edit not in the table.

## Mutation table

- **Planned rows:** every planned row from CHK-M11-320 to -374 is present (I checked the ids, and none is missing). Each is red where the table names it.
- **G87 plants:** -373 and -374 are red on hosted runs 42594910837 and 42594935136.
- **Tester extras:** -375 to -440 and -455 to -458 are present, and so are the three gate plants (SEC-tok-user, SEC-tok-agent, SEC-reads-operator-only).
- **Unused and non-plant ids:** -441 to -449 are declared unused, and -450 to -454 and -459 are declared checks, not plants.
- **-322 surviving G83:** accepted. The planted `stdout: null` in the service mapping is dropped by the route's viewer model (`ScanResultItem`, pydantic `extra="ignore"`) before any byte reaches a viewer, so G83, which tests what a viewer can observe, cannot see it. The table places -322 in G80 and G82, and it is red in both. Two independent layers stand between that fault and a viewer, as plan TASK-235 §3 intended. It is not a gap.
- **G30 and G33 plant notes:**
  - The request-schema form of the G30 plant is caught by G6; the response form is caught by G30.
  - -341 is unobservable in G33's sweep suites and is red in G81 and G83.
  - Both notes are accurate. The planner can fix the gate-table wording.

## Verified myself

- **Frozen-file pins:** all 38 pins in `test_security_m11.py` equal `git show 6efe0fb:<path> | sha256sum`, with 0 mismatches.
- **Lint:** `ruff check` and `ruff format --check` are clean on both gate test files.
- **Local run of the G83 CODE rows (Windows):** 35 passed. The 16 failures are all the S608 and `re`-ban rows, from a Windows-only encoding issue (finding 4). In WSL they are green: 45/45.
- **CHK-M11-387:** I read the `EXPLAIN (ANALYZE)` output. The time is entirely in the `scan_job_retry_of_fkey` and `scan_result_reeval_job_id_fkey` RI triggers, about 0.41 to 0.50 s per deleted job. The delete itself takes 4 ms. With the three indexes, the same 1,022-job scan takes 940 ms. This confirms the tester's diagnosis.

## Findings

1. **Blocking: CHK-M11-387, REQ-275 not met at fleet size (TS §5.3 L1049; #151).** **It is a merge blocker.**
   - **What fails:** as built, at 10,000 hosts, the scans step and the inventory-jobs step each fail on their first chunk every night (`QueryCanceled` at 300 s). They delete nothing.
     - `scan_job` grows by about 40,000 rows a day, which makes each later attempt slower.
     - The oldest fleet scan blocks the scans step for good.
   - **Why this is not the accepted limit:** the user accepted slow but working retention for v1 (decisions 2026-11-08 (2), #151 (a)), on the premise that "retention runs once a day, in the background". This measurement shows it does not work at all. TS §5.3 L1049's retention cannot be met as built, so the earlier acceptance no longer covers it.
   - **Which option it points to:** **option (b), the three #151 indexes**: `scan_job (retry_of)`, `scan_job (scan_id)` and `scan_result_reeval (job_id)`.
     - It is the only measured option that fits: 25 to 33 s a night, 0.9 ms per job.
     - It needs an owner-approved edit of TS §5.2 and one migration. That is outside M11's "no migration" scope, so it is the user's decision.
   - **Why the other options don't fit:**
     - (a1), halving `SCAN_CHUNK` (decisions 2026-11-09 (3)), cannot fix it. One scan of more than about 600 hosts is a single statement over 300 s even at `SCAN_CHUNK` = 1, because the cost is per job, not per scan.
     - (a2), a smaller `JOB_CHUNK`, helps inventory only, and only while `scan_job` stays small. Scans stay blocked.
     - (c), a longer timeout for the retention session, means chunks of 1.5 h or more that hold locks, a nightly run of 4.5 to 7 h, and growth with the fleet. It only delays the failure.
   - **If (b) is chosen:** the tester's table shows that a backlog chunk of 100 fleet scans would still take 20 to 27 min. So the fix round also needs `SCAN_CHUNK` at about 12 or less (or a chunk bounded by job count), with G80, G81, G83's retention rows and G5 re-run, as decisions 2026-11-09 (3) already provides.
2. **Should-fix, merge rule: G39 NOT RUN after a safety-check refusal.**
   - The tester stopped and did not work around it, which is correct.
   - The M11 gate rule (`work/tasks.md`, "M11 gate": "M11 does not merge with such a row until the user decides whether it is a gate exception") needs the user's decision. The cover offered is the PR's `package.yml` "Double build is byte-identical" job, with the agent unchanged since M10's identical builds and 95/95 other build checks. That cover is sound in my view.
3. **Should-fix, process, for M12: no full manager suite at the wave ends.**
   - The speed rules ask for the full suite per wave. Only targeted runs were recorded, so CHK-M9-276, stale since TASK-232 in W1, surfaced first at the gate.
   - It is resolved in the tree: the PD-51 rewrite, then G18 at 11,908/11,908.
   - M12 should run G18 at each wave end.
4. **Nit: `manager/tests/test_security_m11.py:331` `ruff()` runs `subprocess.run(text=True)` with no `encoding="utf-8"`.**
   - On Windows, a module with non-ASCII text reaches ruff as invalid UTF-8, so the S608 and `re`-ban rows fail locally. They are green in WSL and CI.
   - The tester has noted it as a one-line follow-up for the CHK-M11-387 fix round.
5. **Nit: the gate's PD-51 table omits the REQ-088 edit of `manager/tests/test_invariants_m3.py`.**
   - That edit is the M3 query-parameter allow-list, now with the M11 paths pinned to exact sets (`M11_QUERY`), in TASK-232's TEST.
   - It is an earlier check changed by requirement (REQ-088 as changed in M11). It is recorded in TASK-232's report and approved in `TASK-232.md`, so it is not lost.
   - It belongs in the old → new list for completeness.

## For re-review

Once the user decides findings 1 and 2, I will re-review the CHK-M11-387 fix round (a TS §5.2 edit with a migration, or whatever the user chooses) and the G39 decision. I will then turn this verdict to APPROVED for the merge (decisions 2026-11-09 (4)).
