# TASK-187 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (scan state derivation, high risk). REQ-207 (and REQ-219's derivation rule); TS §4.4 L579–L580; #22, #127 (d), (e); #3. Code under test: `bm/services/jobs/scan_state.py` (impl-manager-m9, `work/reports/TASK-187-impl.md`; sha256 `6d78e8235b72af8e…`). Test files (new): `manager/tests/test_scan_state.py`, and `test_derivation_properties` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-015 to -021, -082. Written from #127 (d) before the code was read; the interface matched the plan (TASK-202 §2) unchanged.

## Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_state.py tests/test_jobs_property.py::test_derivation_properties` | **53/53 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 3 plants in `/root/bstest-m9-mut-<id>` (removed after each) | 3/3 red |
| static (L) | ruff, ruff format, mypy --strict on `scan_state.py` and the test files | clean |

## Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-015 | CODE | W | r1 | PASS | REQ-207 (1): 10 rows. A test helper builds each unit's facts from the job states of the original and its retry, and from the plugins with results. All queued → (queued, F); one dispatched → running (#22); expired + queued → running; all complete → (completed, T); original partial + retry completing it → completed; complete + failed with no results → partial; no results + cancelled → cancelled; expired + failed → failed; cancelled after results → partial; cancelled after every unit was complete → completed | 2026-10-30 |
| CHK-M9-016 | CODE | W | r1 | PASS | Unit rule: an original partial plus a completed retry is one complete unit (completed, not partial). failed + queued retry, and partial + running retry, are open (running, not finished). partial + partial still missing → partial; failed + failed → failed | 2026-10-30 |
| CHK-M9-017 | CODE | W | r1 | PASS | `queued` only when every unit is all-queued; one closed unit (expired, completed) makes it running; an ended original with a queued retry → running | 2026-10-30 |
| CHK-M9-018 | CODE | W | r1 | PASS | No results: a cancelled unit (alone, with expired, or as the retry of a failed original) → cancelled; nothing cancelled → failed. Results anywhere beat cancelled → partial | 2026-10-30 |
| CHK-M9-019 | CODE | W | r1 | PASS | `derive([])` and `derive(())` raise `ValueError` (#3); a list and a tuple of the same units agree | 2026-10-30 |
| CHK-M9-020 | CODE | W | r1 | PASS | Exhaustive: all 32 one-unit fact combinations and all 1,024 two-unit pairs give one of the 6 scan states (never dispatched or expired), finished exactly when no unit is open. Over every consistent closed pair the order completed > partial > cancelled > failed holds | 2026-10-30 |
| CHK-M9-021 | CODE | W | r1 | PASS | `Unit` is frozen; `derive` leaves its input unchanged | 2026-10-30 |
| CHK-M9-082 | CODE | W | r1 | PASS | 5,000 hypothesis sets of 1–20 consistent units (complete ⇒ has_results; all_queued ⇒ open ∧ no results ∧ not cancelled). Finished ⇔ no unit open; never dispatched/expired; independent of unit order. Adding a result to one unit never turns partial/completed into failed/cancelled, and an unfinished scan stays queued/running | 2026-10-30 |
| CHK-M9-360 | CODE | W | plant: the `any_cancelled` check moved above `has_results` | PASS (red) | 3 failed: `test_req_207_table` (cancelled after some results), `test_cancelled_failed_overlap`, `test_closed_scan_states_follow_the_order_of_the_rule` | 2026-10-30 |
| CHK-M9-362 | CODE | W | plant: the open branch returns `dispatched` instead of `running` | PASS (red) | 14 failed, in G66 (`test_req_207_table`, `test_one_unit_any_facts`, `test_two_units_any_facts`, `test_queued_only_when_every_job_is_queued`, `test_failed_original_with_a_queued_retry_is_open`) and G67 (`test_derivation_properties`) | 2026-10-30 |
| CHK-M9-391 | CODE | W | plant: `all(u.open …)` instead of `any` (finished too early) | PASS (red) | 4 failed: `test_req_207_table` (expired + queued), `test_queued_only_when_every_job_is_queued`, `test_two_units_any_facts`, `test_derivation_properties` | 2026-10-30 |
| CHK-M9-361 | CODE | W | plant: "derivation per job, not per unit" | NOT RUN here (reason) | `derive()` receives `Unit` facts, so a per-job derivation cannot be planted in this module alone. The per-unit grouping lives in TASK-194's `unit_facts` (`COALESCE(retry_of, job_id)`). The plant there is "group by `job_id`", which must turn CHK-M9-114/-212 red. **Handed to tester-m9b.** At this level CHK-M9-016 pins the unit rule (an original `partial` + completing retry = complete) | 2026-10-30 |

## Acceptance (TASK-187 row: "REQ-207 (1)–(3) hold")

- (1) the table → CHK-M9-015 to -018.
- (2) property over random unit sets → CHK-M9-082 (and the exhaustive CHK-M9-020).
- (3) empty unit list raises `ValueError` → CHK-M9-019.

## Notes

- `derive()` reads only the five facts and does not check that they are consistent (for example `all_queued` without `open`). CHK-M9-020 shows that for every combination, consistent or not, it still never returns dispatched/expired and finished ⇔ no unit open. Whether the facts are consistent is TASK-194's SQL (CHK-M9-114).
