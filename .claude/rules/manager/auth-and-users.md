---
paths:
  - "manager/**/auth/**"
  - "manager/**/services/users/**"
  - "manager/**/api/user/**"
---

# User auth, sessions, API tokens and users

Spec: TS §2.3 (tokens), §6.2 (auth rules and route table) and §8.1 (controls). Columns: `app_user`, `user_token` in TS §5.2.

## Tokens

- `bsu_` session: issued by `POST /auth/login` (username, password and, for admins, a TOTP code); ended by `POST /auth/logout`; 8 h idle, 24 h maximum.
- `bsk_` API token: default 90 days, maximum 365, revocable; acts with the owner's current role at each request; never allowed for sensitive actions. Created only from a web session (TOTP-verified for admins) with `POST /api-tokens`, or on the server with `bitscan-manager users create-api-token <user>`; shown once. Creating one alerts.
- All tokens are 256 random bits, base64url, prefixed; store only the SHA-256 hash. API tokens are never `totp_verified`.

## Sensitive actions

- Need a TOTP-verified session and refuse API tokens: approving or rejecting enrolment requests, revoking agents, rebuild, re-evaluation, and managing users, enrolment tokens and settings (TS §6.2). Refuse them after 15 minutes of audit-sink outage until the queue drains (TS §5.3).
- `DELETE /policies/{id}` needs an admin TOTP session too (TS §4.3, route table).
- **Open spec question:** `DELETE /policies/{id}` is not in the TS §6.2 sensitive-action list; ask whether it is also refused during an audit-sink outage (`work/open-questions.md` #1).
- Policy upload is not sensitive: an admin's `bsk_` token may upload, with no TOTP.
- An API token can never create API tokens or enrol or replace TOTP; those need a web session. Replacing TOTP also needs the current password and a current code.

## Passwords, TOTP and login

- Passwords: Argon2id, at least 12 characters. `POST /auth/password` needs the current password.
- Admins must use TOTP. TOTP seeds are encrypted with the vault key (`BITSCAN_TOTP_KEY_REF`); each code is accepted once (`totp_last_step`).
- Failed logins back off per account (1 s doubling to 15 min), plus the per-IP limit. Admins are never hard-locked. The response is the same whether or not the user exists.
- **Open spec question:** "repeated failures alert" (TS §6.2) gives no threshold; ask before choosing one.
- Every new user is offered TOTP enrolment at first sign-in; admins must complete it. An admin without TOTP gets a session that can call only `/auth/totp/enrol` and `/auth/logout`; after enrolling, re-issue the session as TOTP-verified.

## Users

- First admin: `bitscan-manager users create-admin <name>`. Promoting a user to admin requires TOTP to be enrolled already.
- A lost TOTP device is reset by another admin or with `bitscan-manager users reset-totp <user>`; both alert and are audit-logged.
- A password change, role change or TOTP reset ends the user's sessions. Disabling or demoting a user, or revoking their tokens, revokes every API token they created. Admins can revoke any user's tokens; disabling a user revokes all of their tokens at once, sessions included.
- The last active admin cannot be disabled or demoted.
- **Open spec question:** how the initial password is set for `users create-admin <name>` and for users created with `POST /users` (TS §6.2 gives no source); ask before choosing (`work/open-questions.md` #7).
- Users are never deleted, only disabled (`DELETE /users` disables); `*_by` columns hold `app_user` ids without foreign keys.
- Roles are `viewer`, `operator`, `admin` (default `viewer`); every change is recorded in the hash-chained audit log.
- Alerts: API token created; TOTP enrolled, replaced or reset; user created, role granted or admin created.

Tests (TS §8.3): Security (API tokens refused for sensitive actions, `DELETE /policies/{id}`, token creation and TOTP changes; non-admins refused for policy upload and delete), Integration (every auth and user route), Unit (back-off, TOTP single use; TS §6.2).
