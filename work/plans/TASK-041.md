# TASK-041 plan: user tokens (primitives and API tokens)

Covers TASK-028 (token and password primitives) and TASK-041 (API tokens: create, list, revoke), plus how TASK-046 (`users create-api-token`) reuses them. REQs: REQ-040, REQ-041, REQ-046, REQ-051. Owner: impl-manager. **Two approvals (TS §8.2, auth).** Tests: TP-M2-06, TP-M2-19, TP-M2-23.

Files:
- TASK-028: `bm/auth/tokens.py`, `bm/auth/passwords.py`.
- TASK-041: `bm/auth/api_tokens.py`, `bm/api/user/api_tokens.py`, `bm/api/user/__init__.py`, `manager/openapi.json`.

**Blocked on:** #56 (padding, password limits, Argon2id parameters), #47 (bodies and the `DELETE` shape), #48 (statuses), #8 (`DELETE` with an API token), #50 (actions, alert kind), #52 (id form), #53 (i).

## Spec quotes

- TS §6.2 L1083: "All tokens are 256 random bits, base64url, with a type prefix (`bsu_`, `bsk_`, `bsa_`, `bse_`). The manager stores only their SHA-256 hashes."
- L1081: API token "Created only in the web UI (session token; TOTP-verified for admins) or directly on the server with `bitscan-manager users create-api-token <user>`, which writes to the database; shown once | Default 90 days, max 365; revocable | … the owner's current role at each request, but never for sensitive actions".
- L1085: "An API token can never create API tokens … Disabling or demoting a user, or revoking their tokens, revokes every API token they created."
- L1098–L1099: `POST /api-tokens` "Create an API token; web session only, refused for API tokens | viewer"; `GET, DELETE /api-tokens` "List and revoke your own API tokens | viewer".
- TS §8.4 L1290: "API token created" alerts.
- TS §5.2 L966–L979: `user_token (token_id BIGSERIAL, user_id, kind ('session','api'), name VARCHAR(64), token_hash CHAR(64) NOT NULL UNIQUE, totp_verified, expires_at NOT NULL, last_used_at, revoked_at, created_at)`.
- TS §8.6 L1334: the default redaction pattern `\bbs[aeku]_[A-Za-z0-9_-]{20,}` must match every token (it is how a token in plugin output is removed).

## TASK-028 interface

```python
# bm/auth/tokens.py
SESSION_PREFIX = "bsu_"
API_PREFIX = "bsk_"
TOKEN_BYTES = 32
BODY_LEN = 43                                   # base64url of 32 bytes, no padding (#56 (a) default)

def new_token(prefix: str) -> str: ...          # prefix + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=")
def token_hash(token: str) -> str: ...          # hashlib.sha256(token.encode("ascii")).hexdigest()
def parse_user_token(raw: str) -> TokenKind | None: ...   # bsu_ / bsk_ with a 43-char [A-Za-z0-9_-] body, else None

# bm/auth/passwords.py
MIN_LEN = 12
MAX_LEN = 1024                                  # (#56 (b) default)
class PasswordRejected(ValueError): ...         # message names the rule, never the value
def check_new_password(password: str) -> None: ...   # len() counts code points
def hash_password(password: str) -> str: ...    # argon2-cffi PasswordHasher (RFC 9106 low-memory, #56 (c) default)
def verify_password(stored: str, password: str) -> bool: ...   # False on mismatch or a malformed hash; never raises on bad input
def dummy_verify(password: str) -> None: ...    # same cost; for unknown users and back-off (TASK-038 plan)
```

Only `tokens.py` defines token prefixes for user tokens. M3 adds `bsa_` and `bse_` there for the agent router; the user-route parser keeps accepting only `bsu_` and `bsk_`. Every token generated must match the TS §8.6 pattern above (REQ-040 (1) checks it with RE2).

## TASK-041 interface

```python
# bm/auth/api_tokens.py
DEFAULT_DAYS = 90
MAX_DAYS = 365

@dataclass(frozen=True)
class CreatedToken:
    token_id: int
    token: str               # shown once
    name: str | None
    expires_at: datetime

def create_api_token(tx: Tx, *, user_id: int, name: str | None, days: int | None,
                     now: datetime, actor: str) -> CreatedToken: ...
def list_own(tx: Tx, *, user_id: int, limit: int, after_id: int | None) -> list[ApiTokenInfo]: ...
def revoke_own(tx: Tx, *, user_id: int, token_id: int, now: datetime, actor: str) -> bool: ...
```

- `create_api_token` checks `1 <= days <= 365` (default 90) and `name` ≤ 64 characters, inserts `kind = 'api'`, `totp_verified = false`, writes audit `api_token.create` and `raise_alert(kind="api_token_created")` in the same transaction (#50 defaults). The audit `detail` holds `token_id`, `name`, `expires_at`, never the token or its hash.
- Route `POST /api/v1/api-tokens`: `require_session("viewer")`; if `principal.role == "admin"` the session must also be TOTP-verified (L1081 "TOTP-verified for admins"), refused otherwise with the #48 status. It is not a sensitive action, so the sink gate does not apply. `actor = user:<id>`.
- `GET /api/v1/api-tokens`: `require_role("viewer")` (API tokens allowed), only `kind = 'api'` rows of the caller, paginated `{items, next_cursor}` by `token_id`; items never include `token_hash`.
- `DELETE /api/v1/api-tokens/{token_id}` (#47 (b) default): `require_role("viewer")`, with an API token allowed if #8 is answered "allowed"; `UPDATE user_token SET revoked_at = %s WHERE token_id = %s AND user_id = %s AND kind = 'api' AND revoked_at IS NULL`. Zero rows → 404 (#48), the same answer whether the id does not exist or belongs to someone else (REQ-051 (3)).
- CLI (TASK-046) calls `create_api_token(..., actor="cli:root")` (#50 (b) default) through its own connection; the token is written to stdout only.

## Edge cases

- `secrets.token_bytes` only; no `random`. Ruff bans `re`; any pattern checks use RE2.
- The token is in the response body once and nowhere else: not in the audit `detail`, not in logs (the request log never logs bodies, REQ-039), not in an exception.
- An API token never becomes `totp_verified` (the DB CHECK also forbids it).
- A revoked or expired token row stays (retention deletes expired `user_token` rows after 90 days, M11), so `GET` shows revoked tokens with `revoked_at`.
- Demotion, disabling and "revoke a user's tokens" call the TASK-031 repository `revoke_user_tokens(user_id, kind="api")` from TASK-042; this module does not handle other users' tokens.
- Admin API tokens while the admin has no TOTP: handled in TASK-037 (#53 (i)).
