# TASK-041 IMPL report: API tokens (create, list, revoke)

REQ: REQ-051, REQ-040, REQ-046 (e), (2). Spec: TS §6.2 L1081, L1083, L1085, L1098–L1099; TS §8.4 L1290. Decisions:
- #8: an API token may revoke its own user's API tokens;
- #47: the shapes;
- #48: statuses;
- #50: `api_token.create` / `api_token.revoke` actions, kind `api_token_created`;
- #52: integer ids;
- #53 (i): an admin's `bsk_` with no TOTP is refused (TASK-037);
- lead: one alert entry per event, `UtcDatetime`, problem+json.

Plan: `work/plans/TASK-041.md`. **Two approvals (TS §8.2, auth).**

## Files (4)

- `manager/bitscan_manager/auth/api_tokens.py`: new, 82 non-blank lines. It is the service, reused by the CLI in TASK-046.
- `manager/bitscan_manager/api/user/api_tokens.py`: new, 104 lines. It holds the routes.
- `manager/bitscan_manager/api/user/__init__.py`: also mounts the `api_tokens` router.
- `manager/openapi.json`: regenerated. No 422; every error is problem+json; ASCII only.

`login._fail` was **not** renamed, although the lead allowed it as optional. The rename would touch `login.py`, `totp_enrol.py` and `password_change.py`, which is outside this task's files.

## Service (`auth/api_tokens.py`)

Every function takes the caller's `Tx` (`conn` and `on_commit`). The route passes its `runtime.db.transaction()`; the CLI will pass its own.

- **`create_api_token(tx, *, user_id, name, days, now, actor) -> CreatedToken(token_id, token, name, expires_at)`**
  - Checks: `days` defaults to 90 and must be 1–365, with bools refused; `name` may be `None` or at most 64 characters. A failure raises `ApiTokenInvalid`, whose message names the rule only.
  - Inserts a `kind = 'api'` row with `totp_verified = false` and `expires_at = now + days`; only the SHA-256 is stored.
  - Writes **one** alert entry, `raise_alert(kind="api_token_created", action="api_token.create", target="user:<id>", detail={"token_id", "name", "expires_at"})`. The detail never holds the token or its hash.
- **`list_own(tx, *, user_id, limit, after_id)`** returns the caller's `kind = 'api'` rows ordered by `token_id`. The rows carry no hash.
- **`revoke_own(tx, *, user_id, token_id, now, actor) -> bool`** revokes only the caller's own unrevoked API token. When it succeeds it writes `api_token.revoke` with `{"token_id"}`. It returns `False` alike for an unknown id, another user's token, a session id or a token already revoked.

## Routes (`/api/v1/api-tokens`)

| Route | Auth | Body / query | Answer |
| --- | --- | --- | --- |
| `POST /api/v1/api-tokens` | `require_session(allow_restricted=True)`, then: an admin whose session is not TOTP-verified gets 403 `totp_session_required`. That covers the restricted admin as well, and matches CHK-M2-216. A `bsk_` gets 403 `session_required`. There is no sink gate, because creating a token is not a sensitive action (REQ-054 (4)) | `{name?, expires_in_days?}`, `extra="forbid"`; `expires_in_days` is a `StrictInt` from 1 to 365, so `1.5`, `"30"`, `true`, 0, 366 and −1 all get 400; `name` is at most 64 characters | **201** `{token_id, token, name, expires_at}` |
| `GET /api/v1/api-tokens` | `require_role("viewer")`: sessions and API tokens; the TASK-037 rules refuse a restricted admin and an admin `bsk_` without TOTP | `limit` (1–500, default 50) and `cursor` (TASK-026, scope `api_tokens`, key `token_id`) | 200 `{items, next_cursor}`; items have exactly `{token_id, name, created_at, expires_at, last_used_at, revoked_at}`, all `UtcDatetime` |
| `DELETE /api/v1/api-tokens/{token_id}` | `require_role("viewer")`: a `bsk_` may revoke its user's own API tokens, itself included (#8) | `token_id` is an integer path parameter (#52) | **204**; **404** `not_found` for any id that `revoke_own` rejects (REQ-051 (3)) |

The shipper is woken on commit after a create and after a revoke.

**Choice to confirm:** `POST` answers **201** Created, the usual status for creating a resource; #47 names no status. Sign-in, by contrast, returns 200 because it creates a session rather than a listed resource.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 114 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1027 passed, 348 skipped (pg), 97.13 %. One failure on the first run, `test_openapi.py::test_export_bytes_are_utf8_lf_sorted_with_one_trailing_newline`: the export carried a `§` from a route docstring, which becomes the OpenAPI description. I moved it into a code comment, so the export is ASCII again and `test_openapi.py` gives 5 passed. If the test is meant to accept UTF-8 text, it may be comparing with a different encoding; tester, please check |
| OpenAPI | `GET` 200, 400, 401, 403, 429, 503; `POST` 201, 400, 401, 403, 429, 503; `DELETE` 204, 400, 401, 403, 404, 429, 503. No `422` anywhere |
| Scratch with fake repositories and a sink gate that refuses (deleted) | (1) |

(1) Scratch results:
- **Create:** a viewer session got 201 with the exact keys and `expires_at` 90 days later ending in `Z`. One `api_token_created` alert was written, without the token. The new token worked on its next request.
- **Bad bodies:** 366, 0, `1.5`, `"30"` and a 65-character name each got 400. 365 days with a 64-character name was accepted.
- **Who may create:** a `bsk_` got 403 `session_required`. A verified admin got 201. A restricted admin got 403 `totp_session_required`. Creation still worked while the sink gate was refusing.
- **Paging:** 53 tokens came back as 50 and then 3, with `next_cursor` null at the end. Items had the exact keys.
- **Other users:** user B saw none of A's tokens. B's delete of A's id got 404 `not_found`.
- **Revoke:** a `bsk_` revoking itself got 204, and its next request got 401. `api_token.revoke` was written.

## For the tester (TP-M2-19)

- The CLI reuse in TASK-046 calls `create_api_token(tx, …, actor="cli:root")`.
- CHK-M2-212: 404 covers every id that is not the caller's live API token, including revoked ones and session ids.

## Lead rulings (2026-10-22)

- **`POST /api-tokens` answers 201 Created**: confirmed.
- **No `login._fail` rename**: accepted. The rename was optional, and it would have touched three files outside this task.
