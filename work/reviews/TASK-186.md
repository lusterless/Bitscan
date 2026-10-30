# TASK-186 REVIEW: job state rules (pure)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-206, REQ-217 (rule level). High risk, full rigor. Not a PD-39 task (no second approval or second look).

Scope reviewed, per `work/reports/TASK-186-impl.md`: one new file, `manager/bitscan_manager/services/jobs/states.py` (121 lines). Within the task's file and size limits.

TEST: PASS (`work/reports/TASK-186-test.md`, tester-m9). 240/240, and all 9 plants red (CHK-M9-325, -326, -334, -335 a/b, -336, -337, -338, -390), plus CHK-M9-383 (`re` ban) red in ruff.

Spec read: TS §4.4 L562–L582, §3.3 L222, §6.1 L1071; #124 (a), (d); #127 (a)–(c).

My re-run (Windows, venv): `test_job_states.py`, `test_scan_state.py` and `test_jobs_property.py` give 298/298 passed. `ruff check` and `ruff format --check` are clean on the file.

## Checks
1. **Transitions (REQ-206).** `TRANSITIONS` is exactly the REQ-206 list, and the three final states map to the empty set (TS §4.4 L582). `failed | partial` reach only `completed | partial`. `running` is never re-entered. The property walk (CHK-M9-080) and the 64-pair table (CHK-M9-002) pin this.
2. **Deadline (TS §4.4 L575).** It uses integer ceiling division, the 10-minute slack and the 1–8 bound on `max_parallel_plugins`, and refuses an empty plugin list. The three REQ-206 (2) rows are exact. Floor division, an ignored `mpp` and a 10 s slack are each red.
3. **Acceptance (#124 (a), TS §6.1 L1071).** Only `compliance` jobs in `ACCEPTING` are accepted, with `now <= dispatched_at + 7 d` inclusive. `queued`, `expired`, `cancelled` and inventory jobs are refused at any time, and so is a job with no `dispatched_at`. Cancelled jobs are refused, which is the 409 the TS §4.4 L581 invariant needs.
4. **Batch outcome (#127 (a), #124 (d), TS §3.3 L222).** `start` is True only from `dispatched`, so a second start notice cannot reset `started_at` or `deadline_at`. TASK-195's `WHERE started_at IS NULL` is the second guard. An empty batch, or a batch of duplicates only, on `failed` or `partial` changes nothing. `completed` stays `completed`.
5. **Purity.** The source imports only the stdlib. There is no clock, I/O or logging (CHK-M9-013, -014).

## Findings
None blocking or should-fix.

1. nit, `states.py:97-113`: from `dispatched`, `after_batch` can return `completed` or `partial`. `allowed("dispatched", "completed")` is False, because the move goes through `running` (start, then end). That is correct, but the docstring could say so, so that a later caller using `allowed()` as a guard on the stored transition doesn't refuse it. No change required.
2. Observation, carried to TASK-204 (not a TASK-186 defect): tester note 1. `services/jobs/__init__.py` now imports `intake`, so importing `states` in a fresh interpreter pulls in the repositories and psycopg. The module source is still pure, so REQ-206 (5) as written (what the module imports) holds. I'll weigh the package-init change in the TASK-204 review.
