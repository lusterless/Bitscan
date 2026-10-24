# TASK-066 TEST report: enrolment tokens API

**Verdict: PASS** (2026-10-23, tester-b), on revision 1. Two approvals are needed (TS §8.2). REQ-067 (1) to (6), REQ-063 (2), (3), (5) for enrolment tokens. Plan checks: CHK-M3-190 to -195; mutation rows CHK-M3-325, -328, -329, -336. Code tested: `bm/services/enrolment/enrolment_tokens.py`, `bm/api/user/enrolment.py`, `bm/api/user/__init__.py`, `bm/repositories/enrolment.py` (r1 `revoke_active_token`), `manager/openapi.json` (`work/reports/TASK-066-impl.md`).

## Tests added
- `manager/tests/test_enrolment_tokens_api_pg.py`: 69 tests (marker `pg`), the real app on PostgreSQL through the M2 users-API environment (fake clock, switchable sink).
- `manager/tests/test_auth_dependencies.py`: route walk for the four enrolment-token operations (admin `totp_session`, sink gate).
- `manager/tests/test_enrolment_repo_pg.py`: `revoke_active_token`.

## Commands
- W (`CI=true`): 152 passed, 0 skipped (with the repo, auth-dependency and M2 security suites), no container left.
- L: `test_openapi.py` + `test_contract_agent.py` 566 passed (G6: the committed document equals a fresh export); ruff, format, mypy clean.
- Plants (WSL copies, control 143 passed): 19 of 19 red (tests/m3/report.md CHK-M3-190-mut-r1).

## Acceptance criteria
- Defaults, ranges and CIDR validation: CHK-M3-190, -191-r1 PASS.
- Token shown once; list and read never hold it or its hash; only the hash at rest: CHK-M3-192 PASS.
- `auto_approve` or 101 uses writes one alert entry; 100 uses none: CHK-M3-193 PASS.
- Delete sets `revoked_at` and keeps the row: CHK-M3-195-r1 PASS (enrolling with it through the route is re-checked in TASK-067).
- Every method refuses an admin `bsk_`, an unverified session, operators, viewers and any session while the sink gate refuses: CHK-M3-194 PASS.

## Carry-overs
- A CIDR with host bits (and, from round 1, an IPv6 scope id) gets 400 before the database sees it: CHK-M3-191-r1 PASS.
- Token shown once, only its hash stored: CHK-M3-192 PASS.
- Admin TOTP session and sink gate on every method, admin `bsk_` refused: CHK-M3-194 PASS; route walk PASS.

## Round history
- Round 1 FAIL: `["fe80::%eth0/64"]` → 500 (Python accepts a scope id, PostgreSQL `cidr` does not); two concurrent DELETEs → two revoke entries. Both fixed in r1.

## Notes for TASK-067
- An operator's `bsk_` on these routes gets 403 `totp_session_required` (#48: an API token on a TOTP-session route), not `forbidden`.
- Enrolling with a revoked, expired, exhausted or out-of-CIDR token through `POST /agent/enroll` is TASK-067's check (CHK-M3-200).
