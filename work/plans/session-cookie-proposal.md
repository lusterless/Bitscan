# Proposal: stay signed in across a page refresh, and a "My sessions" page

Status: **draft, waiting for owner approval of the spec wording (section 3)**. No code until the TS is amended in its own PR.

## 1. Request and owner decisions (2026-11-12)

- Problem: refreshing the web UI signs the user out. This is the specified behaviour, not a bug:
  - TS §6.2 L1085: the session token is "held in memory, never in `localStorage`";
  - TS §8.1 L1259 lists "session token in memory only" as an XSS defence;
  - `.claude/rules/web-ui.md` forbids `localStorage`, `sessionStorage` and cookies;
  - open question #85 (c): "Accepted: a reload starts signed out";
  - README: "Reloading the page … signs you out".
- **Owner decision A:** keep the session in a **secure, HttpOnly cookie** so it survives a refresh and new tabs. Rejected alternatives:
  - tab storage (`sessionStorage`), because an injected script can read it;
  - keeping memory-only with a warning.
- **Owner decision B:** add a **"My sessions" page**. Each user lists their own active web sessions and can end any of them. There is no admin view of other users' sessions; admins still revoke a user's tokens through `/users` as today.

## 2. Design

### 2.1 Cookie

| Property | Value | Why |
|---|---|---|
| Name | `__Host-bitscan_session` | The `__Host-` prefix makes the browser refuse it unless it is `Secure`, `Path=/` and has no `Domain`, so a sibling subdomain cannot set or overwrite it |
| Value | the existing `bsu_` session token | No new token type; the DB still stores only its SHA-256 (`user_token`, unchanged) |
| `HttpOnly` | yes | Page scripts, including injected ones, cannot read it |
| `Secure` | yes | Sent over HTTPS only (the manager is HTTPS-only) |
| `SameSite` | `Strict` | Never sent on requests started by another site |
| `Path` | `/` | Required by `__Host-` |
| Lifetime | browser-session cookie (no `Max-Age`) | Survives refresh and new tabs. Closing the browser ends it. The server still enforces 8 h idle and 24 h maximum (TS §2 L122). |

### 2.2 How the manager reads it

- **User routes only** (`/api/v1/*` except `/api/v1/agent/*`). Agent routes never read the cookie; they still accept only `bsa_`/`bse_` (per-router rule, TS §6).
- **Order:** an `Authorization: Bearer` header wins. The cookie is used only when there is no `Authorization` header, so scripts and API tokens (`bsk_`) work exactly as today.
- **Anti-forgery (CSRF):** a request authenticated by the cookie must carry `X-Bitscan-Request: 1`, otherwise 403 `csrf_required`. This applies to every method, including the CSV `GET` downloads, which the UI already fetches with `fetch`.
  - A browser cannot add a custom header to a cross-site request without a CORS preflight, and the manager answers no CORS (TS §6.3). Together with `SameSite=Strict`, that makes two independent defences.
  - If an `Origin` header is present, it must equal the manager's own origin.
- A cookie whose token is invalid, expired or revoked gets the same 401 as a bad bearer token. It is counted by the same failed-check limit, and the response also clears the cookie.
- **The cookie value is never logged.** The request logger already drops headers; a test will assert that `Cookie` and `Set-Cookie` never reach the logs or the audit log.

### 2.3 Routes

| Method | Path | Change |
|---|---|---|
| POST | `/auth/login` | Also sets the cookie. The body is unchanged (`token` is still returned, for compatibility). The UI ignores the token. |
| POST | `/auth/totp/enrol` (confirm) | Also sets the cookie for the re-issued, TOTP-verified session |
| POST | `/auth/logout` | Revokes the session (as today) and clears the cookie (`Max-Age=0`) |
| POST | `/auth/password` | Ends all of the user's sessions (as today) and clears the cookie |
| **GET** | **`/auth/session`** | New. Session only, any signed-in user. Returns `{role, totp_enrolled, totp_verified, expires_at}` for the current session, so the UI can restore itself after a refresh. Counts as use (touches `last_used_at`). |
| **GET** | **`/auth/sessions`** | New. Session only, any signed-in user. Lists the caller's own active web sessions: `{session_id, created_at, last_used_at, expires_at, totp_verified, current}`. API tokens are not listed; they keep their own page. |
| **DELETE** | **`/auth/sessions/{session_id}`** | New. Session only. Ends one of the caller's own sessions (404 if it is not theirs or not a session). Audit-logged as `auth.session_revoke`. Ending the current one also clears the cookie. Not a TOTP-session action, because it only removes access. |

There is **no DDL change**: everything comes from existing `user_token` columns (`kind = 'session'`, `revoked_at IS NULL`, `expires_at > now`, not idle). Device or IP is not shown, because no column stores it, and adding one would change TS §5.2.

### 2.4 Web UI

- `session.ts`:
  - drops the in-memory token;
  - every API call sends `X-Bitscan-Request: 1` and relies on the cookie (`credentials: "same-origin"`);
  - on start-up the app calls `GET /auth/session`: 200 restores the signed-in view, 401 shows the sign-in page;
  - a 401 still signs the UI out.
- New **"My sessions"** page under Account:
  - a table of the user's sessions, with created, last used, expires, TOTP-verified, and "This session" marked;
  - an **End** button on each row;
  - **End all other sessions** (calls DELETE for each other row).
- No other screen changes.

### 2.5 Security assessment (for TS §8.1)

- **Better than today:** an injected script can no longer read and copy the session token to use elsewhere.
- **Same as today:** an injected script can still make requests from inside the page while it runs. The CSP and plain-text rendering remain the defence against that.
- **New exposure:** the session now lasts across reloads for the 8 h idle / 24 h maximum, instead of ending at reload. Someone with access to an unlocked browser stays signed in until the browser closes, the session goes idle, or the user ends it on "My sessions" or signs out.
- **CSRF:** a cookie is sent automatically, so forged requests become possible in principle. They are blocked by `SameSite=Strict`, the required `X-Bitscan-Request` header (no CORS), and the `Origin` check.

## 3. Spec amendment to approve (separate PR, docs only)

1. **TS §6.2 L1085**, the `bsu_` row's last cell:
   - From: "Web UI; held in memory, never in `localStorage`"
   - To: "Web UI; kept in the `__Host-bitscan_session` cookie (`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, no `Max-Age`), never readable by page scripts and never in `localStorage` or `sessionStorage`. A bearer header is also accepted."
2. **TS §6.2 route table:** add the rows `GET /auth/session`, `GET /auth/sessions` and `DELETE /auth/sessions/{id}` (section 2.3; session only; min role "any signed-in user").
3. **TS §6.2 bullets:**
   - add: "Logout, password change and ending a session on `/auth/sessions` clear the cookie. A user can list and end only their own web sessions."
   - add: "User routes read the session cookie only when there is no `Authorization` header. Agent routes never read it."
4. **TS §6.3:** add the convention "A request authenticated by the session cookie must send `X-Bitscan-Request: 1` and, when an `Origin` header is present, the manager's own origin; otherwise 403 `csrf_required`."
5. **TS §8.1 L1259**, Stolen web session (XSS):
   - From: "…; session token in memory only; no CORS (§6.3)"
   - To: "…; session token in an `HttpOnly` cookie that scripts cannot read; `SameSite=Strict` plus a required `X-Bitscan-Request` header and `Origin` check against CSRF; no CORS (§6.3)"
6. **TS §8.1:** add a threat row "Cross-site request forgery" with the mitigations from item 5. Add an **accepted risk**: the session survives a reload until idle (8 h), maximum (24 h), sign-out or browser close.

**Follow-ups after the TS PR merges (code PRs):**
- `.claude/rules/web-ui.md` token line;
- `.claude/rules/manager/auth-and-users.md` and `api.md`;
- open question #85 (c) marked superseded;
- a `work/decisions.md` row;
- the README "Web UI" section.

## 4. Build tasks (after the TS PR)

Auth changes need **two approvals** (CLAUDE.md, TS §8.2).

| Task | Area | What | Tests (TS §8.3 security) |
|---|---|---|---|
| T1 | manager `auth/`, `api/user/auth.py` | Cookie set/clear on login, TOTP confirm, logout, password change; read the cookie in `current_principal` when there is no bearer; CSRF header and `Origin` check | Cookie flags exact; bearer wins; agent routes ignore the cookie; missing header → 403 `csrf_required`; foreign `Origin` → 403; bad cookie → 401, counted and cleared; cookie never in logs or audit |
| T2 | manager | `GET /auth/session`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}`; repository query; audit entry | Only own sessions listed; another user's id → 404; API tokens refused (session only); revoked, expired and idle sessions hidden; ending the current one clears the cookie |
| T3 | web | `session.ts` cookie mode + header + restore on load; regenerate the OpenAPI client | Reload restores the session; a 401 signs out; the token never appears in JS state or storage |
| T4 | web | "My sessions" page and menu entry | Lists, ends one, ends all others; plain-text rendering |
| T5 | docs | README, rules files, decisions, #85 (c) | Docs CI (`docs.yml`) |

Release: a manager-only change (no agent change). It ships in the next minor version, `0.3.0`, following `manager-operations.md` §7.
