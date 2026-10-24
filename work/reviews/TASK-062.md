# TASK-062 REVIEW: `GET` and `PATCH /api/v1/settings`

Reviewer: reviewer. Date: 2026-10-23. REQ-083, REQ-088. Spec: TS §6.2 L1084 (settings management is a sensitive action: TOTP session, API tokens refused), L1126 (`GET, PATCH /settings`, admin, PATCH TOTP session), L1129 (no inventory switch), §8.6 L1317–L1327 (keys, ranges, `inventory_interval_s` in `system_schedule`), §5.3 L1051 (sink-outage refusal), §8.4 L1290 (settings changed alerts); #42, #48, #68, #71; decisions 2026-10-21 (TASK-042 ruling: one entry per event). Inputs:
- `work/reports/TASK-062-impl.md`;
- `work/reports/TASK-062-test.md` (PASS: CHK-M3-150 to -156; 75 PostgreSQL tests in WSL; 9 of 10 plants red, the survivor an equivalent mutant).

Files reviewed:
- `manager/bitscan_manager/api/user/settings.py` (new, 120 lines);
- `manager/bitscan_manager/services/settings/store.py` (`apply_patch`, the typed read; about 70 lines);
- `manager/bitscan_manager/api/user/__init__.py` (router mount);
- `manager/openapi.json` (re-export);
- the tester's `test_settings_api_pg.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. The M3 owner notes recommend a second look, because PATCH is a sensitive action.

## What was checked

- **Authorisation (security invariants "Authorisation").**
  - GET uses `require_role("admin")`, so an admin session or an admin `bsk_` is allowed.
  - PATCH uses `require_totp_session()` (admin, TOTP-verified session, `sink_gate=True`). So:
    - an admin `bsk_` gets 403 `totp_session_required`;
    - an unverified session is refused;
    - during the 15-minute sink outage the answer is 503 `audit_sink_unavailable`.
  - The dependency marker is visible to the route walk. The plants CHK-M3-328 and -331 are red.
- **Spec conformance.**
  - `SettingsPatch` has exactly the seven keys, `extra="forbid"`, `StrictInt` with the `INT_RANGES` bounds and at most 50 patterns. An explicit `null` gets 400.
  - `apply_patch` then re-validates the whole patch (RE2 compile included). It locks the setting rows and writes `inventory_interval_s` to `system_schedule` and the rest to `setting` with `updated_by` and the Clock.
  - It writes one `settings.change` entry with alert kind `settings_changed` and `{"old", "new"}` for the patched keys, all in one transaction. Any refusal rolls back everything: no write, no entry, no alert.
  - One row serving as both audit entry and alert entry is the #71 and M2 one-entry-per-event rule, so REQ-083 (4) is met.
  - `inventory_interval_s` 3,599 answers 400, not 500 (CHK-M3-354).
  - A TTL change leaves existing tokens' `token_expires_at` untouched (REQ-083 (6)).
  - The TASK-055 nit is folded in: a stored value of the wrong type now gives `SettingsUnavailable` (503 `about:blank`) instead of being coerced.
- **REQ-088.** No key, field or parameter disables inventory. `inventory_enabled` is an unknown key and gets 400, with the key never echoed (CHK-M3-352 red).
- **OpenAPI (G6).** I re-exported the document and it is byte-identical to `manager/openapi.json`. `/api/v1/settings` lists GET and PATCH with problem+json refusals and no 422.
- **Scope.** Four files, as the task row lists. The service package `__init__` was deliberately left unchanged.
- **Tests (my run, Windows).** `test_settings_api_pg.py`, `test_settings_service.py` and `test_openapi.py`: 117 passed, 75 skipped (PostgreSQL; run in WSL by the tester). ruff and format are clean on the touched files, and `mypy --strict` is clean on the whole tree (151 files). The tests cover:
  - every key at both bounds;
  - every key at once;
  - mixed and invalid bodies changing nothing;
  - the old and new values in the single entry;
  - API token, unverified session, lower roles and the sink outage refused;
  - concurrent patches applied in turn.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/settings/store.py` (`apply_patch`). A PATCH that sets every key to its current value still writes a `settings_changed` alert with equal old and new values. It is defensible ("every change audit-logged"), but noisy. Optionally, skip writing the rows and the entry when nothing changes, and still answer 200.
