# TASK-181 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-196 (1)–(3), REQ-197 (1), (2); TS §4.5 L601–L602, §4.4 L583; #119, #120. Code under test: `bm/services/evaluator/score.py` (impl-manager-m8b, `work/reports/TASK-181-impl.md`). New test file: `manager/tests/test_evaluator_score.py`. Plan rows: CHK-M8-120 to -124, -134.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | **205/205 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 8 plants (four files, 210 tests each) | 8/8 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-120 | CODE | W | r1 | PASS | REQ-196 (1): (3,1,5,7) → `HostScore(3,1,5,7,0.75)`; (0,0,4,2) → None; (0,3,0,0) → 0.0 (not None); (1,0,0,0) → 1.0; (1,2,0,0) → exactly 1/3; (0,0,0,0) → None. The score is an unrounded `float` | 2026-10-29 |
| CHK-M8-121 | CODE | W | r1 | PASS | REQ-196 (2): each count negative → `ValueError`; a bool count is refused | 2026-10-29 |
| CHK-M8-134 | CODE | W | r1 | PASS | REQ-196 (3): 3,000 hypothesis count sets up to 10⁹: None iff passed + failed = 0, else in [0, 1] and equal to p/(p+f); other errors and not-run values never change it | 2026-10-29 |
| CHK-M8-122 | CODE | W | r1 | PASS | REQ-197 (1): no rows → the original, provenance None (also from an empty iterator). Ids 5, 9, 7 in all 6 orders, with `reevaluated_at` against id order → id 9's code, detail, version, user and time, and the original unchanged beside it. Equal timestamps → the highest id; a one-shot iterator works | 2026-10-29 |
| CHK-M8-123 | CODE | W | r1 | PASS | REQ-197 (2): rows of another plugin, another job or both (ids 100–102) are ignored; adding a matching id 4 then wins | 2026-10-29 |
| CHK-M8-124 | CODE | W | r1 | PASS | ERROR → PASS gives detail None; PASS → ERROR carries the re-evaluation's detail. 2,000 hypothesis row sets match a max-id oracle | 2026-10-29 |
| CHK-M8-346 | CODE | W | plant: ERROR in the denominator | PASS (red) | 3 failed: the REQ-196 rows, counts carried, the independence property | 2026-10-29 |
| CHK-M8-347 | CODE | W | plant: 0 ÷ 0 → 0.0 | PASS (red) | 2 failed: `(0,0,4,2)` row, the property | 2026-10-29 |
| CHK-M8-348 (unit) | CODE | W | plants: lowest id; `reevaluated_at`; "always the later row" | PASS (red) | 9 / 9 / 7 failed: the permutation rows, the equal-time row, the iterator row, the oracle | 2026-10-29 |
| extra x181-filter | CODE | W | plant: plugin not filtered | PASS (red) | 2 failed | 2026-10-29 |
| extra x181-neg | CODE | W | plant: `count < -1` | PASS (red) | 4 failed | 2026-10-29 |

## Acceptance (TASK-181 row)

REQ-196 (1) → -120; (2) → -121; (3) → -134; REQ-197 (1) → -122; (2) → -123. The PostgreSQL half of CHK-M8-348 (the SQL) is in TASK-182 and TASK-184.
