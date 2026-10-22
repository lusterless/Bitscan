# TASK-045 TEST report: `bitscan-manager serve`

Verdict: **PASS**. Tester, 2026-10-22. REQ-057, REQ-039, REQ-047 (4), REQ-053 (4)–(6); #55, #58; decisions 2026-10-21/22 (database time bounds; SIGTERM exits 0; no uvicorn loggers; flusher retry and cap). Impl report: `work/reports/TASK-045-impl.md`. G27.

## Commands run
- W: `pytest tests/test_serve_linux.py` (the real serve process over TLS against the migrated database, a fake HTTPS sink and a test PKI made at test time) inside the wave 5 run; 12 serve and flusher Linux mutants red against a green control; full suite 1367 passed, 0 skipped; 0 leftover serve processes.
- L: `pytest tests/test_serve_flusher.py` (5) and the updated `tests/test_cli.py`; ruff, ruff format, mypy --strict.

## Criteria
| REQ-057 / check | Result | Rows |
| --- | --- | --- |
| (1) missing or invalid variables exit before binding | PASS | CHK-M2-250, -261 |
| (2) TLS 1.2/1.3 only; plain HTTP gets nothing (G27) | PASS | CHK-M2-251, -252 |
| (3) SIGHUP reload in place; a broken pair is kept out (G27) | PASS | CHK-M2-253, -254 |
| (4) headers over TLS | PASS | CHK-M2-255 |
| (5) proxy headers ignored | PASS | CHK-M2-256 |
| (6) SIGTERM exits 0, final flush, queue intact | PASS | CHK-M2-257 |
| (7) runs with an unreadable migrate DSN; vault down | PASS | CHK-M2-258, -260 |
| (8) REQ-008 narrowed: serve is real | PASS | CHK-M2-259 |
| REQ-053 (5), (6) delivery while serve runs | PASS | CHK-M2-262 |
| REQ-039 output: JSON only, no secrets; no uvicorn access log | PASS | CHK-M2-263, -263a |
| CHK-M2-263b flusher retry, order, cap | PASS | CHK-M2-263b |

Mutations: 12/12 Linux red, including both G27 plants (TLS minimum 1.0; SIGHUP handler removed) and the two you asked for (uvicorn access log on; default log_config). Test files added: `test_serve_linux.py`, `test_serve_flusher.py`; updated: `test_cli.py`.
