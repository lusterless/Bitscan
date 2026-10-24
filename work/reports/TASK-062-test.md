# TASK-062 TEST report: GET and PATCH /api/v1/settings

**Verdict: PASS** (2026-10-23, tester). REQ-083 (1) to (6) and REQ-088 (2). Plan checks: CHK-M3-150 to -156. Code tested: `bm/api/user/settings.py`, `bm/services/settings/store.py` (`apply_patch`), `bm/api/user/__init__.py`, `manager/openapi.json` (`work/reports/TASK-062-impl.md`).

## Tests added
- `manager/tests/test_settings_api_pg.py`: 75 tests (marker `pg`). It reuses the M2 users-API environment (real `AppDatabase`, a Shipper with a switchable sink, the fake clock), and every test restores the seeded rows as owner.

## Commands
- W (`CI=true`): 90 passed with `test_settings_pg.py`, 0 skipped, no container left. L: export identical; ruff, format and mypy clean.
- Plants (WSL copies; control 75 passed): 9 of 10 red:
  - CHK-M3-331, -328, -354, -352;
  - no audit or alert entry;
  - `old` missing;
  - no row lock;
  - the interval written to a setting row;
  - GET for any role.

  The survivor, "nulls accepted" at the route, is equivalent: the service refuses null as well.

## Acceptance criteria
- "GET returns the defaults": CHK-M3-150 PASS.
- "a PATCH of every key at its bounds succeeds with one audit and one alert entry": CHK-M3-151, -153 PASS. Per #71 the audit entry and the alert entry are one row.
- "out-of-range, wrong-type, unknown-key (`inventory_enabled`) and mixed bodies change nothing": CHK-M3-152 PASS.
- "an admin `bsk_`, an unverified session and a session during a sink outage are refused on PATCH": CHK-M3-154 PASS. The unverified admin session gets `totp_enrolment_required`, per the M2 restricted-session rule.
