# TASK-184 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor. REQ-197 (3), REQ-199 (1)–(4); TS §2.1 L105, §4.5 L602, §4.4 L579, L583; #119, #120. Code under test: `bm/services/evaluator/scores.py` (impl-manager-m8b, `work/reports/TASK-184-impl.md`) over `repositories/results.py` (TASK-182). New test file: `manager/tests/test_scores_pg.py`. Plan rows: CHK-M8-180 to -184.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scores_pg.py` | **5/5 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 5 plants | 5/5 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-180 | APP | W | r1 | PASS | REQ-199 (1), on the REQ-198 fixture: A `HostScore(2,1,1,1,2/3)`, B (2,1,0,0,2/3), C (0,0,0,3,None) queued, D (2,0,0,0,1.0) re-evaluated FAIL→PASS, E (0,0,2,0,None) all ERROR; ordered by agent | 2026-10-29 |
| CHK-M8-181 | APP | W | r1 | PASS | REQ-199 (2): a late result → C (1,0,0,2,1.0); a re-evaluation → (0,1,0,2,0.0); another → ERROR, (0,0,1,2,None). Each next call reflects the change at once | 2026-10-29 |
| CHK-M8-182 | APP | W | r1 | PASS | REQ-199 (3): an unknown scan → `[]` | 2026-10-29 |
| CHK-M8-183 | APP | W | r1 | PASS | REQ-199 (4): the statement spy sees only `WITH … SELECT`, with no write word | 2026-10-29 |
| CHK-M8-184 | APP | W | r1 | PASS | REQ-197 (3): 200 random sets (seeded; 1–4 plugins, 1–3 hosts, random results, retries for missing plugins, up to 60 re-evaluation rows with random ids and times, some on pairs without results). `effective_results` and `effective()` (fed every row of those jobs plus unrelated rows from other scans) agree on code, detail, id, version, user and the original for every result | 2026-10-29 |
| extra x184-cache | APP | W | plant: scores memoised per scan | PASS (red) | 1 failed: "computed when read" | 2026-10-29 |
| extra x184-swap / x184-errors | APP | W | plants: passed and failed swapped; errors added to failed | PASS (red) | 2 / 2 failed | 2026-10-29 |
| CHK-M8-348 (property) | APP | W | plants in `results.py`: `reeval_id ASC`; `reevaluated_at DESC` | PASS (red) | 3 / 2 failed, including `test_sql_and_effective_agree_on_200_random_sets` (e.g. `(2,'cannot evaluate',3024) == (1,None,3091)`) | 2026-10-29 |

## Acceptance (TASK-184 row)

REQ-199 (1)–(4) → -180 to -183; the REQ-197 (3) property on 200 random sets → -184, which goes red on both ordering plants.
