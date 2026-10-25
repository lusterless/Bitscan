# TASK-119 REVIEW: TOTP enrolment and replacement, first-sign-in offer, password change

Verdict: APPROVED, no open blocking or should-fix findings (and no nits).

Reviewer: reviewer, 2026-10-25. One review round (UI). **The user's second look applies (PD-30 (2)); the user pre-authorised it on a clean TEST PASS plus this verdict.**

Scope reviewed (`work/reports/TASK-119-impl.md`), all new files:
- `web/src/screens/TotpEnrol.tsx`
- `web/src/screens/PasswordChange.tsx`
- `web/src/components/QrCode.tsx`

Sources: REQ-122, REQ-123, REQ-132, TS §6.2 L1085–L1097, #53 (a), #85 (a), PD-28 (e), and decisions 2026-10-25 (the REQ-122 (3) reading; one task at 323 lines).

TEST: PASS (tester-m5, 2026-10-25). 24/24 tests pass and every plant is red.
- The TOTP secret, the URI and the QR svg leave the DOM after a successful confirm, after a 403 or 409, and on unmount.
- The secret, passwords and token never reach storage, cookies, IndexedDB, the console, history or the URL.
- The confirm swaps the token.

## Where the secrets live (for the user's second look)
- **TOTP secret and `otpauth_uri`.**
  - They are held only in the screen's `step` state while the confirm step is shown. On the page they appear as two text nodes and the QR drawing.
  - They are dropped when the confirm succeeds, when the server refuses the code (403) or the enrolment has expired (409), and when the user leaves the screen.
  - The QR drawing is memoised with them and goes too.
  - Nothing writes them to storage, the URL, the console or an error banner.
- **Current password and code (replacement), and the new code (confirm).** They are held in form state and emptied before each request is sent.
- **Password change.** All three password fields are emptied before the request is sent.
  - A local check (fewer than 12 characters, or the two new passwords differ) sends nothing and keeps the fields so the user can correct them.
  - On 204 the session is cleared and the user signs in again.
- **The token.** The confirm's new `bsu_` token goes straight to the session store, replacing the old one. The screen keeps no copy.
- JavaScript cannot wipe strings, so "dropped" means the last reference is gone.

## Checks
1. REQ-122:
   - A first enrolment starts with `{}`. A replacement starts with exactly `{current_password, current_code}`.
   - The secret and URI are shown as text, with the QR code beside them.
   - Confirm sends `{totp_code}`, and it is disabled while the code is empty. The confirm answer replaces the session (2).
   - A 403 on confirm shows the wrong-code message, stays on the TOTP screen and drops the secret. The server has already discarded it (lead reading of 2026-10-25).
   - A 409 goes back to the start step (3).
   - "Not now" appears only in the offer mode (#85 (a)).
   - The rule "an admin without TOTP reaches only this screen and sign-out" belongs to the App shell (TASK-126), and I will check it there.
2. REQ-123:
   - The 12-character minimum is counted in code points, and the two new passwords must be equal before anything is sent.
   - The documented body is sent once.
   - 204 clears the session and calls `onChanged`. 403 `forbidden` shows the wrong-password message and keeps the form, with the fields emptied.
3. QrCode (PD-28 (e)):
   - It reads only the library's module matrix and draws one SVG `<path>`, with presentation attributes and no `style=`.
   - The library's HTML-string and `data:` helpers are never called, so the TS §6.3 CSP and G42 hold.
   - If the value is too long to encode, no QR code is drawn and the text form stays.
4. REQ-132: every value is a text node. There is no `dangerouslySetInnerHTML`, `innerHTML`, `style=`, `fetch`, storage or `console`.
5. Re-run by the reviewer (Windows): `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
6. Scope: 3 files, 323 lines. The lead accepted that as one task (decisions 2026-10-25).

## Findings
None.
