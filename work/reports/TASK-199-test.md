# TASK-199 TEST: PASS (on TASK-195 r1; round 1 FAIL through TASK-195)

Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-214 to REQ-217, REQ-226, REQ-227; TS §6.1 L1071, §4.4 L568–L570, L575, L577, L578, L581, L582, §4.5 L587, L596, L599, L603, §3.3 L222, §8.4 L1288, §8.3 Security (first result wins under concurrent retries); #12, #116 (d), #121, #124, #127 (a)–(c), #129 (c); SR §1.1. Code under test: `bm/services/jobs/intake.py`, `bm/services/audit/metrics.py` (impl-manager-m9b, `work/reports/TASK-199-impl.md`), on `intake_plan.py`, `states.py` (TASK-186/190, tester-m9) and `job_intake.py` (TASK-195 r1). Test files: `manager/tests/test_intake_pg.py`, `manager/tests/test_first_result_wins_race_pg.py` (new). Plan rows: CHK-M9-163 to -175.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own databases) | Count |
| --- | --- | --- |
| r1 (round 1) | `pytest tests/test_intake_pg.py` | 26/27 passed, **1 failed** (`test_a_completed_original_still_sees_its_retrys_results`: p2 stored twice in the unit). Cause: TASK-195 `sibling()`; see `TASK-195-test.md` |
| re-run after TASK-195 r1 | that node id | **1/1 passed** |
| r2 | `pytest tests/test_intake_pg.py tests/test_first_result_wins_race_pg.py` (with the 8-file batch; +1 commit-failure test) | **28/28** and **1/1** passed (200 race rounds), 0 errors, 0 skipped; 0 containers left |
| plants | 17 (service and plan side, plus 320/321/322 run on the race and intake files) | 17/17 red (two variants dropped, see notes) |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-163 | PASS | 12 refusals → `Refused("job_not_acceptable", own)`, no row, job byte-identical: another agent; queued; expired; cancelled while dispatched and while running (`own_cancelled` True only for the agent's own job, False for another agent posting to it); 7 d + 1 s and 7 d + 1 µs; 49 + 1 foreign uuid (the 49 not stored); a plugin of the policy that is not in the job; an unknown job; an inventory job. An unreadable `eval_spec` → `Refused("eval_spec_invalid", False)` |
| CHK-M9-164 | PASS | dispatched, running, failed, partial, completed → `Accepted(1, 1)` (accepted + duplicates = items); `dispatched_at + 7 d` exactly accepted; a job created 10 days ago but dispatched 6 days ago accepted (window from dispatch) |
| CHK-M9-165 | PASS | a fault in `set_state` or `start` after the INSERT: the exception propagates; no row, the job unchanged, no counter move. A transaction that fails after the body (as a failed COMMIT): no row, no counter move |
| CHK-M9-166 | PASS | **one** INSERT per batch (spy); each row's verdict = `result_verdict(entry, item)` and the hand verdict (PASS for `yes\r\n` vs `yes` with exit 3; FAIL; ERROR truncated); `plugin_name_snap`/`operator_snap`/`expected_snap` from the job's `eval_spec` and `execute_snap` from its payload, both deliberately different from the catalog; `job_created_at` = the job's; `received_at` = the manager's now, not the item's `finished_at`; exit code, flags and item times as sent |
| CHK-M9-167 | PASS | stdout 65,536 UTF-8 bytes (32,768 × é) stored as sent; 65,537 → ERROR `oversize` with stdout and stderr `''`; stderr 16,384 kept, 16,385 → `oversize`. The `error_cases` fixture → ERROR, details "timed out", `spool_overflow`, `runner_unavailable`. The NUL fixture → stdout `a�b`, stderr `�`, PASS against expected `a�b` (the stored text is evaluated); a lone surrogate from `json.loads` → `x�y`, PASS. SR §1.1: `install ok installed`/exit 0 → PASS, `""`/exit 1 → FAIL, SR name and snapshots |
| CHK-M9-168 | PASS | queued with expected `before`; an import changes Execute and ExpectedResult (the catalog row shows the new values); `before` posted → PASS, snapshots `before` and the queued Execute |
| CHK-M9-169 | PASS | same plugin twice to one job → `{1, 0}` then `{0, 1}`, first row unchanged; two items in one batch → first stored; original then retry and the reverse → stored once, from the first post; **a completed original still sees its retry's results** (round-1 bug) |
| CHK-M9-170 | PASS | 200 rounds, barrier, two pooled sessions posting one plugin to the original and to its retry: every round exactly one row, answers `{1,0}` and `{0,1}`, M8 `host_counts` (1 PASS, 1 not run), no deadlock or error |
| CHK-M9-171 | PASS | posting to a retry: both `FOR UPDATE` statements (root, then job) precede the INSERT (spy) |
| CHK-M9-172 | PASS | canary in stdout, stderr, execute and expected through accepted, duplicate, oversize, refused and unreadable-spec batches: in no log record (DEBUG) and no audit `detail`; the `eval_spec` refusal is logged by exception type only |
| CHK-M9-173 | PASS | empty batch on dispatched → running, `started_at` = now, `deadline_at` = now + 648 s (Σ 95 s, `max_parallel_plugins` 2 set for that call); a second notice with the setting at 8 changes nothing; a first non-empty batch also starts (12 + 600 s with 8). Non-final with plugins missing → running; final → partial (`finished_at`); all → completed |
| CHK-M9-174 | PASS | failed + non-final 1 of 3 → partial (`finished_at` t1); the other 2 → completed (`finished_at` moves to t2); empty batch on failed → unchanged; completed takes only duplicates; expired and cancelled refused and unchanged |
| CHK-M9-175 | PASS | the family exports exactly `result` ∈ {PASS, FAIL, ERROR}; 2 PASS + 1 FAIL + 3 ERROR add exactly those; a duplicate batch and a refused batch add nothing |
| CHK-M9-320 / -321 | PASS (red) | root lock removed / posted job locked instead → the race goes red (double rows, M8 double count) together with the repo rows |
| CHK-M9-322 | PASS (red) | sibling always None → 10 failed incl. the original↔retry rows |
| CHK-M9-324 | PASS (red) | members of a mixed batch stored → 2 failed |
| CHK-M9-325 | PASS (red) | `cancelled` accepted → 3 failed (intake refusals, cancel rows) |
| CHK-M9-327 | PASS (red) | window from `created_at` → 1 failed |
| CHK-M9-328 | PASS (red) | the kind ignored → 2 failed (inventory job: wrong reason) |
| CHK-M9-329 | PASS (red) | verdict from the current catalog → 2 failed (catalog-change and snapshot rows) |
| CHK-M9-330 / -331 / -332 / -333 | PASS (red) | streams kept on oversize / NUL replaced after evaluation / execute from the catalog / `received_at` from `finished_at` → 1, 1, 2, 1 failed |
| CHK-M9-374 | PASS (red) | counter before commit → the commit-failure row; duplicates counted → the counter row |
| CHK-M9-375 | PASS (red) | stdout logged at DEBUG → the canary row |

## Acceptance (TASK-199 row)

REQ-214 (1)–(3), (5) (flood: TASK-204), (6); REQ-215 (1)–(6); REQ-216 (1)–(5); REQ-217 (1)–(6); REQ-226 (1)–(3) → the rows above.

## Notes

- Two plant variants were dropped as not defects. 334s (relax `start`'s guard; the service still calls it only for a dispatched job, so behaviour is unchanged) is covered at the repository level, `TASK-195` 334r red. 374a (the counter before commit, with my first fault test) stayed green because the faults ran before the counting. The commit-failure test added for it is red as expected.
