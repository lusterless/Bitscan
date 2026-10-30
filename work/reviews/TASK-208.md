# TASK-208 REVIEW: README, scans and schedules

Verdict: APPROVED (round 2)

Reviewer: reviewer-m9, 2026-10-30. REQ-233. Low risk (docs).

Scope reviewed, per `work/reports/TASK-208-impl.md` (with r1): `README.md` (+78/−4 in r0, plus two sentences in r1).

TEST: PASS on r0 (`work/reports/TASK-208-test.md`): 88/88 README rows matched on a real `serve`, and CHK-M9-286 found no secret or process note. tester-m9 is re-checking the r1 rows. This approval assumes that re-check stays PASS. r1 changes only prose that the walk does not drive by clock (the DST sentence; the deadline wording).

Spec read: TS §4.4, §6.2 L1119, L1122, L1124, §6.4, §8.4 L1288, L1290; #122, #123, #124 (f), #127 (b), (d), (f), #128; decisions 2026-10-30 "DST behaviour for scheduled scans".

## Checks
1. **Accuracy against the approved answers.**
   - Targets and limits (#122 (b)), refusal statuses (#122 (f), #3, #125 (h)) and the 202 body (TS §6.4) match.
   - So do one job per host and profile (#125 (e)), disable versus delete (#18, #122 (h)), `Idempotency-Key` (#123) and cancel (#122 (g)).
   - The job and scan states, the deadline formula and the `completed`-at-deadline edge (#127 (b), r1), the single retry, the 7-day window and first-result-wins (TS §4.4) match.
   - So do the 409 cases with the cancelled-job flood exclusion (#124 (f)), oversize and U+FFFD (#116 (d), #121), and the metric and ERROR-rate expression (#129 (c)).
2. **DST (r1).** `README.md:488` now states the user's ruling: a skipped spring time runs just after the jump, a repeated autumn time runs once, at its first occurrence, and so a schedule that fires more often than hourly makes no runs in the repeated hour.
3. **Security wording.** It says nothing is pushed, there is no route for any other command, the expected values never leave the manager, and inventory jobs are never touched by scans.
4. **No secret or process note** (CHK-M9-286).

## Findings
1. should-fix, round 1, **resolved**: DST was not described (`### Schedules`, `timezone` bullet). It is fixed in r1 at `README.md:488`.
2. nit, round 1, **resolved**: the deadline bullet now also names `completed` (`README.md:466`).
