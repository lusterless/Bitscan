# TASK-027 TEST report: JSON logs, request_id, access records

Verdict: **PASS**. Tester, 2026-10-21. REQ-039 (1)–(4). Impl report: `work/reports/TASK-027-impl.md`.

## Commands run (L)
- `cd manager && .venv/Scripts/python.exe -m pytest tests/test_request_log.py` → 15 passed.
- 11 mutations plus control in throwaway copies (`%TEMP%\m2-mutate.py`).
- `ruff check`, `ruff format --check`, `mypy --strict` (78 files); full suite 782 passed, 229 skipped, G5 93.09 %.

## Criteria
| REQ-039 | Result | Rows |
| --- | --- | --- |
| (1) JSON lines with request_id, agent_id, job_id; one id per request | PASS | CHK-M2-050, -055 |
| (2) no secret in logs, stdout or stderr (canary sweep; G28) | PASS | CHK-M2-051, -054 |
| (3) access record: method, path without query, status, duration; no headers | PASS | CHK-M2-051, -053 |
| (4) unhandled exception: type and request_id, no body or locals | PASS | CHK-M2-052 |

Mutations: 11/11 red, control green. The first run left one mutant alive (request id not reset): TestClient gives each request its own context. I added a raw-ASGI test in one context, and that mutant is now red. Rows are in [tests/m2/report.md](../../tests/m2/report.md).

## Notes
- The full-run canary sweep (sign-in, TOTP, tokens, `serve`, CLI) is CHK-M2-056 and CHK-M2-293, at TASK-045/046 and the M2 gate.
- Test files added: `manager/tests/test_request_log.py`, `manager/tests/canary.py` (shared sweep helper).
