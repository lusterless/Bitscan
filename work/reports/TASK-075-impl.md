# TASK-075 IMPL report: agent token rotation

REQ: REQ-071. Spec: TS §6.1 L1067, §3.2 L190–L191, §6.5 L1188, §8.4 L1290; #60, #62. Plan: `work/plans/TASK-059.md` ("Rotation"); decisions 2026-10-23 (#62 confirmed; the TASK-059 r1 30-day cap). Depends on TASK-051, 055, 056, 059 and 063, all approved. **Two approvals** (TS §8.2).

Carry-overs applied:
- the window `issued_at + max(TTL − 30 d, TTL ÷ 2)` to `expires_at`;
- outside the window: 403 `forbidden` plus a `rotation_outside_window` alert;
- a second rotation within 24 h of a used one: 429 with `Retry-After`;
- the lost-response retry uses `replace_unused_token` and keeps `last_rotation_at`;
- the old token after the new one was used is reuse: both revoked, plus a `token_reuse` alert;
- the new-IP alert uses the dependency's previous last-seen time (more than 7 days, or never);
- the TTL comes from the current setting;
- the response holds exactly three keys;
- only the hash is stored.

## Files (4)

- `manager/bitscan_manager/services/enrolment/rotation.py`: new, 150 lines.
- `manager/bitscan_manager/api/agent/rotate.py`: new, about 75 lines.
- `manager/bitscan_manager/api/agent/__init__.py`: the rotate router is included, and `RotateRequest` is added to `documented_request_bodies()`.
- `manager/openapi.json`: re-exported and byte-stable.
  - `POST /api/v1/agent/{id}/token/rotate` documents an optional `requestBody` → `RotateRequest` (an empty object, `additionalProperties: false`).
  - The 200 response is `RotateResponse`, with exactly `agent_token`, `issued_at` and `expires_at` and `additionalProperties: false`.
  - Refusals 400, 401, 403, 429 and 503 are problem+json.
  - **All six TS §6.1 agent operations are now in the document.**

## Route

- `current_agent` (TASK-063) handles the token check, `{id}`, the 30-per-minute limit and IP recording, and returns `ip_last_seen` (the IP's `last_seen_at` before this call). The token check already refuses an expired token with 401 `token_expired`, and an old token past the 30-day unused-rotation cap.
- **Body (#60):** "no body, or `{}` only". FastAPI turns both an empty body and a JSON `null` into `None`, so the route reads its small body itself. Empty is accepted. Otherwise the body must be a JSON object that validates as `RotateRequest`, which takes no keys. `null`, `[]`, `{"a": 1}`, a string or non-JSON get 400 `invalid_request`. The 1 MiB cap is applied by `BodyLimit` before the route. This matches the contract fixture `rotate/request_invalid_null`.
- The service runs in the threadpool, in one transaction. `RotationRefused` is caught inside the transaction, so its revoke or alert commits before the answer.

## Service `rotate_token` (agent row locked)

| Called with | Condition | Result |
| --- | --- | --- |
| previous token | new token already used (`prev_token_expires_at` set, even inside the overlap) | **reuse**: `revoke` (both tokens end), one `token_reuse` alert, **401 `token_revoked`** |
| previous token | new token unused | **lost-response retry**: `replace_unused_token(fresh hash, now, now + TTL)`, **`last_rotation_at` kept**, one `agent.token_rotate` entry `{retry: true}`, 200 |
| current token | `now < window_opens(token_issued_at, token_expires_at)` | one `rotation_outside_window` alert with `{window_opens}`, **403 `forbidden`** |
| current token | `last_rotation_at` within 24 h **and** that rotation's token was used | **429 `rate_limited`**, `Retry-After` = whole seconds to `last_rotation_at + 24 h` |
| current token | otherwise | `rotate(new hash, now, now + TTL)` (old hash → `prev_token_hash`, `last_rotation_at = now`), one `agent.token_rotate` entry `{retry: false}`, 200 |

- The window: TTL is the presented token's own `expires_at − issued_at`; the window opens at `issued_at + max(TTL − 30 d, TTL ÷ 2)`.
- TTL for the new token is the **current** `agent_token_ttl_days`, so a setting change affects only tokens issued or rotated afterwards.
- **New-IP alert:** after a successful current-token rotation, if `ip_last_seen` is None or older than 7 days, one `rotation_new_ip` alert is written.
- All entries have actor and target `agent:<id>`. No entry holds a token or a hash.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (98 files).
- `pytest -q`: 2182 passed, 1067 skipped. The 9 failures are the known test-file updates from TASK-074, `test_login` ×2 and `test_body_caps` ×7.
- The contract suites (`test_contract_agent.py`, `test_contract_fixtures.py`): **665 passed**, including `rotate/request_invalid_null`.
- **Service probe** (fakes, against the REQ-071 criteria):

  | Case | Result |
  | --- | --- |
  | TTL 365, day 334 | 403 plus `rotation_outside_window` |
  | TTL 365, day 335 | 200; a new `bsa_`; lifetime = the current TTL |
  | TTL 60, day 30 − 1 s | 403 |
  | TTL 60, day 30 | 200 |
  | lost-response retry (new token unused) | 200 via `replace_unused_token`, `{retry: true}` |
  | old token after the new one was used, inside the overlap | 401 `token_revoked`, revoke, `token_reuse` |
  | second rotation 23 h after a used one | 429, `Retry-After` 3600 |
  | second rotation at 24 h | 200 |
  | second rotation 1 h after an unused one | 200 |
  | new IP, never seen | `rotation_new_ip` |
  | new IP, seen 6 days ago | nothing |
  | new IP, seen 8 days ago | `rotation_new_ip` |
  | TTL setting 90 | new token lives 90 days |

- Through the API on PostgreSQL with clock control (TP-M3-29): **NOT RUN locally**; WSL.

## Deviations

None. The route reads its own (empty) body, so it can refuse a JSON `null` as #60 and the fixtures require.

## Revision 1

This revision follows the lead's ruling of 2026-10-23, "TASK-075 rotation rulings", in `work/decisions.md`, made on tester-e's questions. Only `manager/bitscan_manager/services/enrolment/rotation.py` changed; there is no route, schema or OpenAPI change.

1. **The 24 h rule comes before the window check.** With the current token, a rotation within 24 h of a rotation whose new token was then used now answers 429 `rate_limited`, with `Retry-After` to the end of those 24 h. It writes no `rotation_outside_window` alert. The window check (403 `forbidden` plus the alert) runs only after that. This matches #62 and REQ-071 (5). Before, the rule could never fire through the API: after a rotation the presented token is the new one, and its window opens at least 30 days later.
2. **The lost-response retry now applies the new-IP rule.** A rotation retried with the previous token, while the new one is still unused, writes `rotation_new_ip` when the source IP has not been seen for this agent in the last 7 days (or ever). The check is in one helper, `_new_ip_alert`, shared by both paths. The retry is otherwise unchanged: a fresh token, `last_rotation_at` kept, and the audit entry `{"retry": true}`.

Gates (Windows):
- ruff, format and `mypy --strict` are green;
- `openapi.json` was re-exported and is byte-identical;
- the rotation-related files pass: 94 passed, 201 skipped (the PostgreSQL tests skip without Docker).

**Not run:** the PostgreSQL suites. Only the tester runs them, in WSL.

Expected test updates:
- any TP-M3-29 check that expects 403 plus `rotation_outside_window` for a second rotation within 24 h of a used one now sees 429;
- a lost-response retry from an IP unseen for 7 days now also writes a `rotation_new_ip` entry.

## Revision 2

This revision follows the user's ruling of 2026-10-23 in `work/decisions.md`, "TASK-075 revision 2 ordered", which came from the reviewer's concurrent-rotate nit. Only `manager/bitscan_manager/services/enrolment/rotation.py` changed.

- **The case:** two rotate calls arrive at the same moment with the same current token. Both pass the token check before taking the row lock. The second gets the lock after the first has rotated, so it used to run the window check against the new token's `issued_at` and write a false `rotation_outside_window` alert with a 403.
- **The fix:** after taking the lock, `rotate_token` checks whether the token the caller presented, which the token check saw as current, has just become the previous one with the new token still unused. That means the locked row has a different `token_hash`, its `prev_token_hash` equals the presented token's hash, and `prev_token_expires_at` is null. If so, the call goes down the lost-response retry path:
  - a fresh token replaces the unused one (`replace_unused_token`, whose `WHERE` clause already guards this state);
  - the audit entry is `{"retry": true}`;
  - there is no window alert and no 24 h check;
  - `last_rotation_at` is kept;
  - the 7-day new-IP rule still applies (`rotation_new_ip`).
- **What it compares:** only stored SHA-256 hashes, never tokens.
- **If the concurrent rotation's new token was already used** (`prev_token_expires_at` set) before this call got the lock: r2 does not redirect it. The call stays on the current-token path, where the 24 h rule answers 429 with no window alert (revision 1), as before r2.

## Revision 2: gates (Windows)

- ruff, format and `mypy --strict` are green. There is no OpenAPI change.
- `tests/test_rotation_api_pg.py`, `test_token_check.py` and `test_alerts.py`: 94 passed, 45 skipped (the PostgreSQL tests skip without Docker).
- A local probe with stub stores called the service with a stale "current" caller against the rotated row. Result: only `replace_unused_token` ran; there was no `rotation_outside_window`; a `{"retry": true}` audit entry was written; and with `ip_last_seen=None` it also wrote `rotation_new_ip`.
- **Not run:** the PostgreSQL suites (the tester runs them in WSL). A concurrency test needs two connections, with the second rotate blocked on the row lock until the first commits.
