# TASK-037 plan: auth dependencies (token resolution, RBAC, session-only and TOTP-session checks)

REQs: REQ-044, REQ-045, REQ-046, REQ-047. Owner: impl-manager. **Two approvals (TS §8.2 L1268, auth).** Depends on: TASK-025 (runtime contract), TASK-026 (problem types), TASK-028 (token parsing and hashing), TASK-031 (repositories), TASK-036 (rate limits). Files: `bm/auth/principal.py`, `bm/auth/dependencies.py`. Tests: TP-M2-15, and the M2 Security suite TP-M2-25 (gate G25).

**Blocked on #48** for the exact status and problem `type` of each refusal, and on **#53 (i)** for admin API tokens while the admin has no TOTP. Where a value depends on them it is marked below.

## Spec quotes

- TS §2.3 L118: "Every call into the manager carries a bearer token over HTTPS (TLS 1.2+). User tokens work only on user routes and agent tokens only on `/api/v1/agent/` routes."
- TS §6 L1056: "all other routes are user routes and accept only `bsu_` or `bsk_` tokens. Each route group is a separate router with its own token check."
- TS §6.2 L1080: session "8 h idle, 24 h max; ended by `POST /auth/logout`". L1081: API token "the owner's current role at each request, but never for sensitive actions".
- TS §6.2 L1084: "**Sensitive actions** need a TOTP-verified session and are refused for API tokens: approving enrolment requests, revoking agents, rebuild, re-evaluation, and managing users, enrolment tokens and settings."
- TS §6.2 L1085: "An API token can never create API tokens or enrol or replace TOTP; those need a web session."
- TS §6.2 L1089: "An admin with no TOTP yet … gets a session that can call only `/auth/totp/enrol` and `/auth/logout`."
- TS §5.3 L1051: "sensitive actions (§6.2) are refused after 15 minutes of outage until the queue drains."
- TS §6.3 L1136: "Failed token checks on any route are limited to 20 per minute per source IP (the limit counts and blocks only failed attempts; requests with valid tokens from the same address are never throttled)." User routes: 600 req/min per user.
- TS §5.2 L972, L977: `totp_verified` "always false for API tokens"; `CHECK (kind = 'session' OR NOT totp_verified)`.

## Interface

```python
# bm/auth/principal.py
class TokenKind(StrEnum):
    SESSION = "session"     # bsu_
    API = "api"             # bsk_

ROLE_ORDER: Mapping[str, int] = {"viewer": 0, "operator": 1, "admin": 2}

@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str                 # current app_user.role, read in this request
    kind: TokenKind
    token_id: int
    totp_verified: bool       # always False for API
    totp_enrolled: bool       # app_user.totp_secret_enc IS NOT NULL

    @property
    def restricted(self) -> bool:
        # REQ-046 (d): an admin session that is not TOTP-verified
        return self.role == "admin" and self.kind is TokenKind.SESSION and not self.totp_verified

def resolve(tx: Tx, raw_token: str, now: datetime) -> Principal | None: ...   # pure decision + repo reads

# bm/auth/dependencies.py   (FastAPI dependencies; thin; logic stays in resolve())
def current_principal(request: Request, runtime: Runtime = Depends(get_runtime)) -> Principal: ...
def require_role(minimum: str, *, allow_restricted: bool = False) -> Callable[..., Principal]: ...
def require_session(minimum: str = "viewer", *, allow_restricted: bool = False) -> Callable[..., Principal]: ...
def require_totp_session(minimum: str = "admin", *, sink_gate: bool = True) -> Callable[..., Principal]: ...
```

`allow_restricted=True` is used by exactly two routes: `POST /auth/totp/enrol` and `POST /auth/logout`. `sink_gate=False` exists only so M7 can follow the answer to #1 for `DELETE /policies/{id}`; every M2 use keeps the default.

## Resolution order (one path for every failure, so no check is skipped)

1. Client IP = the ASGI `client` host (TCP peer; proxy headers off, #55). If `limits.failed_check_blocked(ip)` and the request's token turns out invalid, answer 429 (step 9); do **not** block before checking, because valid tokens from that IP must pass (L1136).
2. `Authorization` header present, scheme `Bearer` (case-insensitive), exactly one space, non-empty token, no other credentials. Otherwise: failed check.
3. Prefix: `bsu_` → SESSION, `bsk_` → API. Any other prefix, including `bsa_` and `bse_`: failed check. Never look at the agent or enrolment tables.
4. Length and alphabet check of the body (43 base64url characters, #56) before hashing; otherwise failed check. This bounds work on garbage input.
5. `token_hash = sha256(token).hexdigest()`; one query by `token_hash` joining `app_user` (TASK-031 `find_active_token`).
6. Reject (failed check) when: no row; `row.kind` ≠ prefix kind; `revoked_at` is set; `expires_at <= now`; SESSION and `coalesce(last_used_at, created_at) + 8 h <= now`; user `disabled`.
7. #53 (i), if answered as recommended: an API token of an admin with `totp_secret_enc IS NULL` is a failed check (403 rather than 401 is for #48).
8. Success: `touch_token(token_id, now)` sets `last_used_at` (skip the UPDATE when the stored value is less than 60 s old, so a burst does not write every request; the idle rule then has at most 60 s of slack, which the test in REQ-044 (2) allows). Then `limits.allow_user(user_id)` or 429. Return the `Principal`.
9. Failed check: `limits.record_failed_check(ip)`; if `failed_check_blocked(ip)` now holds, 429 (#48 `rate_limited`), else 401 (#48 `unauthorized`). The body is identical for every 401 cause.

Role and session checks run after resolution:
- `restricted` and the route is not `allow_restricted` → 403 (#48 `totp_enrolment_required`).
- Role below the minimum → 403 (#48 `forbidden`).
- `require_session`: API token → 403 (#48 `session_required`). For admins, `POST /api-tokens` uses `require_session(..., )` plus a verified-session check: TASK-041 calls `require_totp_session(minimum="viewer", sink_gate=False)` only when the caller is an admin (see TASK-041 plan).
- `require_totp_session`: API token, or session without `totp_verified`, → 403 (#48 `totp_session_required`); then `runtime.sink_gate.refusing()` → 503 (#48 `audit_sink_unavailable`). The sink check comes last so that an API token is told the more basic reason first; either way nothing runs.

## Edge cases

- Two headers (`Authorization` twice) → failed check, not "use the first".
- A `bsk_` token that the hash finds as a `session` row (or the reverse) is a failed check even though the hash is valid (REQ-040 (4)).
- Token in a query string or cookie is never read; there is no fallback (web-ui rule: memory only, `Authorization: Bearer`).
- The resolution reads the role in the same transaction as the route's work, so a role change committed before the request is always seen (REQ-044 (5)).
- Timing: the lookup is by a SHA-256 hash with a unique index, so no constant-time compare of the token is needed; the response body does not depend on which check failed.
- Logging: the dependency logs only `user_id` and `token_id` (never the token, its hash or the header) and the failure reason as an enum, at DEBUG.
- Route-walk test (REQ-045 (2), REQ-046 (6)): each dependency factory sets a marker attribute on the returned callable, so the tester can list routes and the dependency each has without reading code.
- The per-user 600/min check happens after authentication, so it cannot be used to probe which tokens are valid.
