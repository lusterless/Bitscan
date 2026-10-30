# TASK-195 REVIEW: result intake repository

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-215, REQ-216, REQ-217, REQ-230. High risk, full rigor. **PD-39: the TS §8.2 second approval is due after this review** (applied under the pre-authorisation on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-195-impl.md` (with r1): one new file, `manager/bitscan_manager/repositories/job_intake.py` (201 lines, about a third of it the INSERT text). The interface differs from plan §3 in three ways: `sibling()` returns the pair, `start` and `set_state` return `bool`, and both have stricter guards. All three are justified in the impl report and are tested.

TEST: PASS on r1 (`work/reports/TASK-195-test.md`). Round 1 failed on the sibling of a `completed` original, a real defect, fixed in r1. r2 is 20/20 with 0 skipped. All 7 plants are red: CHK-M9-320, -321, -322 (repo), the extra completed-original plant, -334 and -376.

Spec read: TS §4.4 L568–L570, L575, L577, L578, L582, §4.5 L587, §5.2 L892–L913, L1005–L1013; #124 (c), #127 (a), (f).

My re-run: `ruff check` on `repositories/` and `mypy --strict` on the file are clean on Windows. The PostgreSQL suite is Linux-only (W); I rely on tester-m9b's r2 run.

## Checks
1. **Lock order, first result wins (TS §4.4 L578, #124 (c)).**
   - The function reads the root with no lock (stable, because `bitscan_app` has no UPDATE grant on `retry_of`).
   - For a retry, it then takes the root `FOR UPDATE`, and then the posted job `FOR UPDATE`. For an original, the job lock is the root lock.
   - Every post to a unit therefore serialises on the root. Under READ COMMITTED, the statements after the wait see the first post's rows.
   - The two-session `pg_locks` probes cover all four (posted, other) pairs (CHK-M9-117). Removing either lock is red (CHK-M9-320, -321).
2. **The sibling (r1).** A retry's original is read by primary key. An original's retry is searched for whenever the original is `failed`, `partial` or `completed`. r1 correctly adds `completed`: a late batch can complete an original whose retry already exists (TS §4.4 L577, L582). Without it, the original could store a second result for a plugin its retry already holds. The round-1 FAIL showed exactly that, and the plant that restores the old set is red.
3. **One INSERT per batch (TS §4.5 L587).**
   - It inserts `FROM unnest(…)` of typed arrays.
   - `job_created_at` is the job's own `created_at`, and the TS §5.2 trigger refuses a 1 µs shift (CHK-M9-118).
   - `received_at` comes from the caller's manager clock (#124 (e)).
   - `result` is never written.
4. **Progress columns only (TS §5.2 L1011, REQ-230).**
   - `start` writes `state`, `started_at` and `deadline_at` only while `dispatched` and `started_at IS NULL`. `set_state` writes `state` and `finished_at`.
   - Neither can leave a final state, and `set_state` refuses any target other than `running`, `completed` or `partial`.
   - There is no UPDATE or DELETE on `scan_result`.
5. **SQL safety.** Every statement is a literal with parameters, and an f-string plant is red in S608.

## Findings
None blocking or should-fix.

1. Process note (not a code finding): plan TASK-199 §3 and the #127 (f) note still say the sibling is looked up "only when the posted job is a `failed` or `partial` original". r1 makes that stale. The implementer has reported it to `main` (the planner owns those files).
