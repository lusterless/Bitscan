# TASK-062 IMPL report: `GET` and `PATCH /api/v1/settings`

REQ: REQ-083, REQ-088. Spec: TS §6.2 L1084, L1126 and L1129, §8.6 L1317–L1327, §5.3 L1051 (sink gate), §3.4 L237; #42, #48, #68, #71. Depends on TASK-055 and TASK-056, both approved. Recommended second look (`PATCH /settings` is a sensitive action). The TASK-055 review nit is folded in, as ruled.

## Files (4)

- `manager/bitscan_manager/api/user/settings.py`: new, 120 lines.
- `manager/bitscan_manager/services/settings/store.py`: about 70 lines added.
- `manager/bitscan_manager/api/user/__init__.py`: mounts the router (2 lines).
- `manager/openapi.json`: re-exported, 287 lines added (both operations, `SettingsBody` and `SettingsPatch`). A second export is byte-identical.

## Behaviour

**`GET /api/v1/settings`** uses `require_role("admin")`, so an admin session or an admin `bsk_` works.
- It answers 200 with all seven keys (#68), in TS §8.6 order, with `inventory_interval_s` read from `system_schedule`.
- If a seeded row is missing or a stored value has the wrong type, it answers 503 `about:blank` "The settings are unavailable.".

**`PATCH /api/v1/settings`** uses `require_totp_session()`. That means admin and TOTP-verified session only: an API token gets 403 `totp_session_required`, an unverified session likewise, and the sink gate answers 503 `audit_sink_unavailable` (the M2 marker, so the route walk sees it).

How the body is checked:
- `SettingsPatch` uses `extra="forbid"`. Each integer key is `StrictInt` with the range taken from `store.INT_RANGES`, so the document shows the ranges. `redaction_patterns` is a list of at most 50 strings.
- An unknown key, such as `inventory_enabled`, gets 400 "Invalid request: body: unknown field" from the M2 validation handler. The key is never echoed.
- An explicit `null` gets 400 naming the field.
- Then `store.apply_patch` validates the **whole** patch again with `validate_patch`. That covers types, ranges, RE2-compiled patterns, and an empty body (400 "Invalid request: body").

How a valid patch is applied, in **one transaction**:
1. `lock_settings()` locks the setting rows (`FOR UPDATE`), so concurrent patches apply one at a time.
2. The current values are read.
3. Each patched key is written: `inventory_interval_s` to `system_schedule`, the others to `setting`, with `updated_by` = the admin's user id and `updated_at` = the Clock.
4. The settings are read again.
5. **One** entry is written: action `settings.change`, actor `user:<id>`, target `settings`, alert kind `settings_changed`, and `detail = {"old": {…patched keys…}, "new": {…}}`. Following the #71 "one entry per event" ruling (decisions 2026-10-21, TASK-042), this single chained entry is both the audit entry and the alert entry. The alert counter rises on commit.

Any refusal rolls back the whole transaction: nothing is written, and no audit entry or alert is made. The answer is 200 with all seven keys.

**TTL:** changing `agent_token_ttl_days` touches only the setting. Existing `agent.token_expires_at` values are unchanged; new tokens use the setting when they are issued (TASK-067, TASK-075).

**No inventory switch:** the patch model has exactly the seven TS §8.6 keys, and `inventory_interval_s` stays 3,600–86,400 (the service check, then the database CHECK).

## TASK-055 nit (folded in)

`read_settings` now refuses a stored value that does not have its type: a non-`int` (or a `bool`) for an integer key, or a `redaction_patterns` value that is not a list of strings. It raises `SettingsUnavailable(key)` instead of coercing with `int()`.

## New service API (`services/settings/store.py`)

- `SettingsStore`: a `Protocol` with `lock_settings`, `write_value` and `write_schedule_interval`, satisfied by `SettingsRepo`.
- `Alerter`: a `Protocol` with `alert(...)`, satisfied by `services.users.TxAudit`.
- `apply_patch(repo, audit, *, patch, user_id, now) -> Settings`.

The package `__init__` was left unchanged, to stay within the task's listed files; the route imports `store` directly.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (146 files).
- `pytest -q`: 1914 passed, 611 skipped. The failures are TASK-048 r1 contract fixtures, which become 6 after the r1 addendum. They are model-only by design, as explained to you, and have nothing to do with this task.
- OpenAPI: re-exported and stable. The new path is `/api/v1/settings` (GET, PATCH). PATCH documents 200, 400, 401, 403, 429 and 503 as `application/problem+json`, with no 422.
- Scratch probe of `apply_patch` with fakes:
  - `{job_pull_seconds: 60, inventory_interval_s: 3600}` wrote one setting row and the schedule, under the lock, and made exactly one `settings_changed` alert with old 300/21600 and new 60/3600.
  - A mixed patch (one good key plus `inventory_enabled`), 3,599, and `{}` were each refused before the lock: no writes, no alert.
  - A stored `"300"` (a string) made `read_settings` raise `SettingsUnavailable`.
- Through the API on PostgreSQL: **NOT RUN locally** (Docker unavailable); this is TP-M3-16 in WSL.

## For the tester

- REQ-083 (4) "one audit entry and one `settings_changed` alert entry" is met by a single entry, per #71 and the M2 one-entry-per-event ruling. Expect exactly one new `audit_log` row per successful PATCH, with `detail.alert = true`.
- The JSON Schema shows the nullable `anyOf` for each `SettingsPatch` field (optional keys). The route refuses an explicit `null` with 400.

## Deviations

None.
