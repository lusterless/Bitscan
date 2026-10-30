# TASK-202 REVIEW: `offline_sweep` compliance steps and the scan state refresh (design note D3)

Verdict: APPROVED (round 2)

Reviewer: reviewer-m9, 2026-10-30. REQ-218, REQ-219, REQ-228, REQ-229. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-202-impl.md` (with r1): `manager/bitscan_manager/services/scheduler/sweep.py` (the M3 file, now +238/−7). That's above the ~200-line guide by the r1 savepoint (about 50 lines), which this review asked for. The rest is the plan-requested `ComplianceRepos` adapter and the three steps. One file only. I accept the size: the overrun is the review fix, not scope growth.

TEST: PASS on r1 (`work/reports/TASK-202-test.md`). 33/33 on the r1 tree (18 compliance tests, 10 in `test_sweep.py`, 5 in the queue race). The new rows are the poison `eval_spec` and missing-`plugins` jobs, and the REQ-228 (2) compliance-present threshold run. 11 plants are red, plus the r1 plant (savepoint dropped, 2 failed). In `test_sweep.py`, CHK-M3-185 is replaced by CHK-M9-217 under PD-40 rule (3).

Spec read: TS §3.3 L218, §4.4 L571–L582, §4.1 L530, §3.4 L244, §8.4 L1291; #18, #124 (h), #126, #127 (a)–(f); REQ-078 (5).

My re-run (Windows): `ruff check manager` and `ruff format --check manager` are clean on the whole tree (385 files). `mypy --strict` is clean on `manager/bitscan_manager`.

## Checks (pass)
1. **Lock order and re-check (#124 (c), builder checklist item 9).** The root is locked first, then the job, `SKIP LOCKED`. The state, the deadline or the 24 h rule is re-checked on the locked row with strict `<` (#127 (b)). The sweep never waits (CHK-M9-207).
2. **Exactly one retry (#126).** `end_job` is conditional, and the retry is built in the same savepoint as the end (CHK-M9-210). There is no retry of a retry and none for a deleted policy or a decommissioned agent, but a disabled policy does get one (#18). The retry keeps the original's commands and patterns (CHK-M9-209).
3. **r1, per-job failure isolation.** `_each_job` runs each candidate's lock, end and retry in its own savepoint. A bad job rolls back alone and is logged with `{step, job_id, exc_type}` only, while the other jobs end and retry in the same sweep. That fails closed per job, as intake does (#124 (h)). The counters now count only rows that `end_job` changed.
4. **Scan refresh (#127 (d)–(f)).** One `scan_job` read per run, writes only on change, `finished_at` kept, never `dispatched` or `expired`. The scan row lock guards against a racing cancel.
5. **M3 steps, inventory and payload (REQ-218 (7), (8), REQ-229, REQ-230).** The M3 steps are unchanged, no new query touches inventory jobs, and earlier jobs' non-progress columns are byte-identical (CHK-M9-216).
6. **REQ-228 (2).** With compliance jobs and results present, `agents_offline` and `inventory_stale` give the M3 answers (new row).

## Findings
1. should-fix, round 1, **resolved in r1**: one bad job rolled back the deadline or never-started step for the whole fleet on every sweep. Each job now has its own savepoint. Verified in code (`sweep.py:278-309`) and by the poison rows and their plant.
2. nit, round 1, **resolved**: `deadline_ended` and `never_started_failed` count only the jobs `end_job` changed.
3. Gate carry, round 1, **resolved**: the REQ-228 (2) compliance-present run was added.
