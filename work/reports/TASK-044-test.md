# TASK-044 TEST report: health routes

Verdict: **PASS**. Tester, 2026-10-21. REQ-056, REQ-036; #5; decisions 2026-10-21 (readyz bound). Impl report: `work/reports/TASK-044-impl.md`.

## Commands run
- L: `pytest tests/test_health.py` (22) with a fake database, plus the updated M0 `tests/test_app.py` and `tests/test_openapi.py`; 8 mutations plus control; ruff, ruff format, mypy --strict; OpenAPI export identical to the committed file.
- W: `pytest tests/test_health_pg.py` on the migrated database, with the pausable TCP proxy for CHK-M2-249; the `readyz-stall-unbounded` mutant in `tester2_w4mut.sh`.

## Criteria
| REQ-056 | Result | Rows |
| --- | --- | --- |
| (1) `/healthz` 200 with the database down | PASS | CHK-M2-240 |
| (2) `/readyz` 200 on a migrated database | PASS | CHK-M2-241 |
| (3) 503 for database, revision and each of the three schedule rows | PASS | CHK-M2-242 |
| (4) 503 body names only the check | PASS | CHK-M2-243 |
| (5) no writes | PASS | CHK-M2-244 |
| (6) headers; no token; no rate limit; outside /api/v1 | PASS | CHK-M2-245, -246 |
| lifespan; export without runtime; G6 | PASS | CHK-M2-247, -248 |
| bounded with the database paused (CHK-M2-249) | PASS | CHK-M2-249 |

Mutations: 8/8 unit red and the Linux unbounded-stall mutant red (it hit the 180 s timeout instead of answering 503). Control green. Two unit mutants survived my first run (driver message in the detail; ping skipped); I added two tests and both are red now. Test files added: `test_health.py`, `test_health_pg.py`. M0 tests updated for the superseded REQ-006 (1) and REQ-007 (3): `test_app.py`, `test_openapi.py`.
