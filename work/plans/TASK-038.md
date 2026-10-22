# TASK-038 plan: sessions and TOTP (sign-in, back-off, TOTP check, enrolment)

Covers TASK-029 (TOTP core), TASK-038 (sign-in and sign-out) and TASK-039 (TOTP enrolment and replacement). REQs: REQ-042, REQ-047, REQ-048, REQ-049, REQ-043. Owner: impl-manager. **Two approvals for all three (TS §8.2, auth).** Tests: TP-M2-07, TP-M2-16, TP-M2-17.

Files:
- TASK-029: `bm/auth/__init__.py`, `bm/auth/totp.py`.
- TASK-038: `bm/auth/login.py`, `bm/api/user/__init__.py`, `bm/api/user/auth.py`, `bm/app.py`, `manager/openapi.json`.
- TASK-039: `bm/auth/totp_enrol.py`, `bm/api/user/auth.py`, `manager/openapi.json`.

**Blocked on:** #49 (TOTP parameters, enrolment protocol, non-admin codes), #47 (bodies), #48 (statuses), #50 (audit actions), #54 (repeated-failure alert threshold), #55 (back-off details), #58 (vault down). Values marked "(#N default)" are the recommended defaults in `work/open-questions.md`; do not ship them until the lead confirms.

## Spec quotes

- TS §6.2 L1080: "`POST /auth/login` with username, password and, for admins, a TOTP code | 8 h idle, 24 h max; ended by `POST /auth/logout`".
- L1086: "A password change, role change or TOTP reset ends the user's sessions. Failed logins get the same response whether or not the user exists."
- L1087: "Admin accounts must use TOTP; each code is accepted once (`totp_last_step`)."
- L1088: "Failed logins: per-account back-off doubling from 1 s up to 15 min, plus the per-IP limit in §6.3. Admin accounts are slowed, never hard-locked. Repeated failures alert."
- L1089: "Every new user is offered TOTP enrolment at first sign-in; admins must complete it. … An admin with no TOTP yet … signs in with a password only and gets a session that can call only `/auth/totp/enrol` and `/auth/logout`; after enrolling, the session is re-issued as TOTP-verified."
- L1085 and L1096: enrol or replace "your own TOTP; session only; replacing needs the current password and code".
- TS §6.3 L1136: "unauthenticated routes (`/auth/login`, `/agent/enroll`) 10 req/min per source IP".
- TS §5.2 L957–L962: `totp_secret_enc` ("encrypted with a vault key"), `totp_last_step`, `failed_logins SMALLINT`, `next_login_at`.

## TASK-029: `bm/auth/totp.py` (pure, standard library only, PD-19 (f))

```python
SEED_BYTES = 20                 # (#49 default)
DIGITS = 6                      # (#49 default)
PERIOD_S = 30                   # (#49 default)
WINDOW_STEPS = 1                # current step ± 1 (#49 default)

def new_seed() -> bytes: ...                                   # secrets.token_bytes(SEED_BYTES)
def seed_to_base32(seed: bytes) -> str: ...                    # no padding, for the authenticator app
def provisioning_uri(seed: bytes, username: str, issuer: str = "Bitscan") -> str: ...
def code_at(seed: bytes, step: int) -> str: ...                # RFC 4226 HOTP with HMAC-SHA1, dynamic truncation
def match_step(seed: bytes, code: str, now: datetime) -> int | None: ...
```

`match_step` returns the newest step in `[s - WINDOW_STEPS, s + WINDOW_STEPS]` whose code equals `code` (`hmac.compare_digest` on every candidate, no early exit), or None. It rejects anything that is not exactly `DIGITS` ASCII digits before computing. Single use is enforced by the caller with the repository, not here (the function stays pure).

## TASK-038: sign-in (`bm/auth/login.py`)

```python
@dataclass(frozen=True)
class LoginResult:
    token: str                  # shown once
    expires_at: datetime
    role: str
    totp_enrolled: bool
    totp_verified: bool

class LoginFailed(Exception): ...            # one type for every failure; the route maps it to one 401 body

def login(tx: Tx, *, username: str, password: str, totp_code: str | None,
          now: datetime, cipher: TotpCipher) -> LoginResult: ...
```

Steps (the route first checks `limits.allow_login(ip)` and answers 429 if not, #48; that limit counts every attempt, #55 (c) default):

1. `user = users.find_by_username(tx, username)` (exact, case-sensitive, #56 (d) default).
2. If no user, or `user.disabled`: `passwords.dummy_verify(password)`; raise `LoginFailed`.
3. If `user.next_login_at` is set and `now < next_login_at`: `dummy_verify`; raise `LoginFailed`. The attempt does not raise the counter (#55 (a) default).
4. If `passwords.verify(user.password_hash, password)` is false: `record_failure` (below); raise `LoginFailed`.
5. TOTP: if the user has TOTP (`totp_secret_enc` not NULL) and (the user is an admin, or #49 (c) says every enrolled user):
   - missing code → `record_failure`; raise `LoginFailed`;
   - `seed = cipher.decrypt(user.totp_secret_enc)` (vault down → 503, #58, not a failure count);
   - `step = totp.match_step(seed, code, now)`; None → `record_failure`; raise;
   - `users.claim_totp_step(tx, user_id, step)` (`UPDATE app_user SET totp_last_step = %s WHERE user_id = %s AND (totp_last_step IS NULL OR totp_last_step < %s) RETURNING user_id`); no row → the code was already used → `record_failure`; raise. This UPDATE is the single-use guarantee under concurrency (REQ-042 (3)).
   - `totp_verified = True`.
   - An admin with no TOTP gets `totp_verified = False` and so the restricted session (TASK-037 `Principal.restricted`).
6. `users.reset_failures(tx, user_id)` (`failed_logins = 0, next_login_at = NULL`).
7. `token = tokens.new_token("bsu_")`; `user_tokens.insert_session(tx, user_id, sha256(token), totp_verified, expires_at = now + 24 h)`.
8. Audit `auth.login` (#50 default) with `target = user:<id>`, `detail = {"totp_verified": …}`; never the username typed by an unknown caller.

`record_failure` runs in its own short transaction (so step 4's failure is committed even though the request ends in an error): `UPDATE app_user SET failed_logins = LEAST(failed_logins + 1, 1000), next_login_at = now + make_interval(secs => LEAST(900, 2 ^ (LEAST(failed_logins + 1, 11) - 1))) WHERE user_id = %s RETURNING failed_logins` (the cap keeps the SMALLINT safe and the exponent finite; values from REQ-048 (3)). The fake clock's `now` is passed as a parameter, not `now()`, so tests control it. If the returned count hits the #54 threshold, `alerts.raise_alert(kind="login_failures", target=user:<id>)` in that same short transaction.

Equal responses: every `LoginFailed` maps to one constant problem body (status 401, #48 `unauthorized`, fixed `title` and `detail`, `instance` = the path). The test compares bodies byte for byte across the seven failure cases (REQ-048 (1)).

Timing: `dummy_verify` checks the password against a hash made once at import with the same Argon2id parameters, so the no-user and back-off paths cost one verification like a wrong password (REQ-048 (2)).

Logout (`POST /auth/logout`, `require_session(allow_restricted=True)`): `revoke_token(token_id, now)`, audit `auth.logout`, 204. A `bsk_` token is refused by `require_session` (REQ-048 (6)); it is not revoked.

Router: `bm/api/user/__init__.py` creates `user_router = APIRouter(prefix="/api/v1")` and includes `auth.router`; `create_app()` includes `user_router` (REQ-035 (5)). Login is the only user route without `current_principal`.

## TASK-039: TOTP enrolment (`bm/auth/totp_enrol.py`, #49 (b) default protocol)

```python
@dataclass(frozen=True)
class EnrolStart:
    secret_base32: str
    otpauth_uri: str
    expires_at: datetime        # pending seed lifetime: 10 min (#49 default)

@dataclass(frozen=True)
class EnrolDone:
    token: str                  # re-issued session, totp_verified = True
    expires_at: datetime

class PendingEnrolments:        # in memory, keyed by the caller's session token_id; one manager instance (TS §2.1)
    def put(self, token_id: int, seed: bytes, now: datetime) -> None: ...
    def take(self, token_id: int, now: datetime) -> bytes | None: ...   # removes it; None if absent or expired

def start(tx, principal, *, current_password: str | None, current_code: str | None,
          now, pending: PendingEnrolments) -> EnrolStart: ...
def confirm(tx, principal, *, code: str, now, pending, cipher: TotpCipher) -> EnrolDone: ...
```

- `start`: if the user already has TOTP (a replacement), require `current_password` (verify) and `current_code` (decrypt, `match_step`, `claim_totp_step`); any failure is refused (#48) and nothing changes. Then `seed = totp.new_seed()`, `pending.put(...)`, return the seed and URI. Nothing is written to the database (REQ-049 (4)).
- `confirm`: `seed = pending.take(...)`; None → refused. `step = match_step(seed, code, now)`; None → refused and the pending seed is discarded (the user starts again). Then, in one transaction: `users.set_totp(tx, user_id, cipher.encrypt(seed), last_step=step)`; revoke the presenting session; per #53 (b) revoke the user's other sessions; insert a new session with `totp_verified = True` and the **same** `expires_at` as the old one (re-issuing must not extend the 24 h maximum); audit `auth.totp_enrol` or `auth.totp_replace`; `raise_alert` `totp_enrolled` or `totp_replaced`. Return the new token.
- The route keeps one path, `POST /auth/totp/enrol`, and tells the two calls apart by the body (#47): `{}` or `{current_password, current_code}` starts; `{totp_code}` confirms.
- The pending seed never goes to the database, a log or the vault before confirmation. It is dropped on expiry, on `take`, and on logout of that session.

## Edge cases

- A user disabled between `start` and `confirm`: `confirm` runs through `current_principal`, which refuses a disabled user, so nothing is stored.
- Two `confirm` calls racing on one session: `take` is atomic (a lock in `PendingEnrolments`), so one wins.
- A replacement's `current_code` consumes that step (`claim_totp_step`), so the same code cannot be replayed at sign-in.
- Vault failures during `confirm` (#58): refused with 503, the pending seed is kept until it expires so the user can retry.
- Clock steps backwards: `claim_totp_step` still refuses a step not newer than the stored one; `match_step` uses the fake clock in tests.
- The restricted admin session calls both `start` and `confirm`; after `confirm` the old (restricted) token is refused (REQ-049 (2)).
