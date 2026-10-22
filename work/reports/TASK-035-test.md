# TASK-035 TEST report: alerts and bitscan_alerts_total

Verdict: **PASS**. Tester, 2026-10-21. REQ-055 (1)–(3); #50 (c); #5. Impl report: `work/reports/TASK-035-impl.md`.

## Commands run
- L: `pytest tests/test_alerts.py` → 27 passed; 8 mutations plus control; ruff, ruff format, mypy --strict.
- W: `tests/test_alerts_pg.py` (PostgreSQL through `AppDatabase`) in `tester2_w3.sh`, alone: full suite 1131 passed, 0 skipped; `alerts.py` and `metrics.py` 100 %.

## Criteria
| REQ-055 | Result | Rows |
| --- | --- | --- |
| (1) one entry with `detail.alert = true` and the #50 kind | PASS | CHK-M2-135, -138 |
| (2) counter +1 after commit, +0 on rollback | PASS (unit and PostgreSQL) | CHK-M2-136 |
| (3) registry ready for a later route; no route in M2 | PASS | CHK-M2-137 |

Mutations: 8/8 red, control green. The first run left the pre-seeding mutant alive: earlier tests had already created the labels. A fresh-process test now catches it. Test files added: `test_alerts.py`, `test_alerts_pg.py`.
