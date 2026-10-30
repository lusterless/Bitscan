# TASK-200 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-219, REQ-220, REQ-227; TS §4.4 L573, L579–L581, §6.2 L1122; #122 (g), #127 (d), (e), #129 (a); decisions "M9 builder rulings" (one `scan.cancel` entry per call, including `cancelled_jobs: 0`). Code under test: `bm/services/jobs/cancel.py` (impl-manager-m9, `work/reports/TASK-200-impl.md`). Test file: `manager/tests/test_cancel_pg.py` (new). Plan rows: CHK-M9-182 to -185.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_cancel_pg.py` | 6/7 passed, 1 failed: **test bug** (the race used a 1-plugin policy, so a stored result completed the job before the cancel) |
| re-run | the file after the fix (2-plugin policy) | **7/7 passed**, 0 skipped; 0 containers left |
| plants | 4 | 4/4 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-182 | PASS | one job per state plus a queued retry: queued, dispatched, running and the retry → `cancelled`, `finished_at` = now; answer `cancelled_jobs: 4`; the 5 ended jobs, another scan's queued job and 3 inventory jobs byte-identical |
| CHK-M9-183 | PASS | no result → scan `cancelled` with `finished_at` = now in the cancel's own transaction; a completed unit + a running unit with a result → `partial` (never `cancelled`, #127 (d)); an original completed by late results with its retry still queued → `completed` |
| CHK-M9-184 | PASS | repeat → `cancelled_jobs: 0`, same state, `finished_at` not moved; two `scan.cancel` entries (`user:41` `{1}`, `user:42` `{0}`), target `scan:<id>`; unknown scan → `ScanNotFound`, no entry; `verify_chain` ok |
| CHK-M9-185 / REQ-220 (2) | PASS | after the cancel a pull returns only the agent's inventory job (state unchanged by the cancel); posts for the cancelled dispatched and running jobs → `Refused("job_not_acceptable", own_cancelled=True)`, nothing stored |
| race | PASS | 20 rounds, cancel and a post to one running job at a barrier: no error or deadlock; the job ends cancelled; the result is stored iff the post was accepted |
| CHK-M9-359 | PASS (red) | (repo plant) dispatched/running left → cancel rows red |
| CHK-M9-360 | PASS (red) | through `derive()` (tester-m9, G66) |
| derive step dropped | PASS (red) | 3 failed (the scan stays running/queued) |
| detail leaks job ids | PASS (red) | 1 failed (exact detail `{cancelled_jobs}`) |

## Acceptance (TASK-200 row)

REQ-220 (1), (3)–(5) → CHK-M9-182 to -184. REQ-220 (2) is checked through the routes in TASK-205 too.
