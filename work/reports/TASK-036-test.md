# TASK-036 TEST report: rate limits and failed-check aggregator

Verdict: **PASS**. Tester, 2026-10-21. REQ-047 (1)–(4), (6), (7); #54 (b), #55 (c), (e); decisions 2026-10-21 "M2 test-plan answers" (3) and "Lead ruling on #54 (b)". Impl report: `work/reports/TASK-036-impl.md`.

## Commands run
- L: `pytest tests/test_ratelimit.py` → 27 passed with a fake clock; 12 mutations plus control; ruff, ruff format, mypy --strict.
- W: `tester2_w3.sh`, alone: full suite 1131 passed, 0 skipped.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-047 (1) sign-in 10/min per IP, every attempt counts | PASS | CHK-M2-140 |
| REQ-047 (2) 600/min per user over all tokens | PASS | CHK-M2-141 |
| REQ-047 (3) 20 failed checks per IP, failures only | PASS | CHK-M2-142 |
| REQ-047 (4) one aggregated entry per IP per minute; 429s counted; shutdown flush | PASS (entries returned by `drain`; the audit write is TASK-045) | CHK-M2-143 |
| REQ-047 (6), #54 (b) alert at 21, once per IP per hour | PASS | CHK-M2-144 |
| REQ-047 (7) keys dropped after their window | PASS | CHK-M2-145 |
| #55 (e) Retry-After 1–60 | PASS | CHK-M2-146 |

Mutations: 12/12 red (including alert at 20), control green. Test file added: `test_ratelimit.py`.
