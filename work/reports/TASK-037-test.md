# TASK-037 TEST report: auth dependencies

Verdict: **PASS**. Tester, 2026-10-21. REQ-044, REQ-045, REQ-046, REQ-047 (3); #48, #53 (i); decisions 2026-10-21 (answers (1), (3) as corrected). Impl report: `work/reports/TASK-037-impl.md`. Two-approval task. G25.

## Commands run
- W: `tester2_w4mut.sh`, alone: `pytest tests/test_auth_dependencies.py` (the matrix on PostgreSQL as bitscan_app, through a `create_app(runtime)` test app with one route per factory), then 19 TASK-037 mutations plus control, each pytest under `timeout 180`; 0 leftover containers.
- L: the route-walk tests; ruff, ruff format, mypy --strict.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-044 (1) wrong scheme, missing, unknown, bsa_/bse_ (planted hashes): 401, one body | PASS | CHK-M2-150, -151 |
| REQ-040 (4) prefix must match the row kind | PASS | CHK-M2-152 |
| REQ-044 (2)–(4) 8 h idle, 24 h max, expiry, revocation, disabled user | PASS | CHK-M2-153 to -155 |
| REQ-044 (5), (6), REQ-045 (3) role per request; last_used_at | PASS | CHK-M2-156, -157 |
| REQ-045 (1), (2) role order; route walk | PASS (the walk is vacuous until user routes land) | CHK-M2-158, -159 |
| REQ-046 (a)–(d) session-only, TOTP-session, sink gate, restricted admin | PASS | CHK-M2-160 to -163 |
| #53 (i) admin API token without TOTP | PASS | CHK-M2-164 |
| REQ-047 (2), (3) failed-check limit, valid tokens checked first, per-user limit | PASS | CHK-M2-165, -166 |
| REQ-039 no token in logs | PASS | CHK-M2-167 |

Mutations: 19/19 red, control green, including the requested plant (a limited IP's valid token answered 429). Test file added: `test_auth_dependencies.py`.

## Notes
- The route walk descends the whole dependency tree, so a factory wrapped in another dependency is still found.
- Resolution runs in its own short transaction before the route's own transaction (lead-accepted). A role change committed between the two takes effect on the next request.
