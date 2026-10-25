# TASK-119 IMPL: TOTP enrolment and replacement, first-sign-in offer, password change

Owner: impl-web. REQ-122, REQ-123, REQ-132; #85 (a); PD-28 (e); #53 (a), (b). Builds on TASK-116 and TASK-117. Worktree `Bitscan-m5`. **User second look (PD-30 (2))**: this task handles TOTP secrets and passwords. See "Where secrets live" below.

## Files (all new; nothing else changed)

| File | Code lines |
| --- | --- |
| `web/src/screens/TotpEnrol.tsx` | 178 |
| `web/src/screens/PasswordChange.tsx` | 95 |
| `web/src/components/QrCode.tsx` | 50 |

Total 323 code lines against the plan's 190, mostly Prettier's one-attribute-per-line JSX for the form fields. I flagged the size to `main`.

## Props (screen contract, `work/plans/TASK-116.md`)

- `TotpEnrol({ mode: "required" | "offer" | "manage"; onDone: () => void; onSkip?: () => void })`
- `PasswordChange({ onChanged: () => void })`
- `QrCode({ value: string; label: string })` (internal component)

## TotpEnrol behaviour

- **Enrol vs replace.** `mode="manage"` with `useSession().totpEnrolled === true` is a **replacement**. Every other case is a first enrolment (`required` = admin without TOTP; `offer` = non-admin without TOTP after sign-in; `manage` without TOTP).
- **Start.** A first enrolment posts `POST /api/v1/auth/totp/enrol` with `{}`. A replacement posts exactly `{ current_password, current_code }` first (REQ-122 (4)). Both fields are `required` inputs.
- **Start answer (`EnrolStartResponse`).** It shows a QR code (PD-28 (e)), then `Secret: <code>{secret}</code>` and `URI: <code>{otpauth_uri}</code>` as text nodes (REQ-122 (2)), then a code field and **Confirm** (disabled while the code is empty, so `{totp_code: ""}` or `null` is never sent).
- **Confirm.** Posts `{ totp_code }`. The answer is a `LoginResponse`, passed to `setSession()`, which **replaces the token in memory**; then `onDone()`. The next request carries the new token (REQ-122 (2)).
- **403 on confirm.** Shows "The code was not accepted. Start again to get a new secret." and goes back to the start step on the same screen, with the secret dropped. **Confirmed by the lead (2026-10-25):** "keeps the screen" in REQ-122 (3) means staying on the TOTP screen, not keeping the old secret. The manager **discards the pending secret on a wrong code** (`auth/totp_enrol.py` L139–141), so the old secret is useless after a 403.
- **409 on confirm** (no pending enrolment, for example after the 10-minute expiry or a restart) shows "The enrolment expired. Start again." and returns to the start step ("restarts enrolment"). The user presses Start again. Start is not re-sent automatically, because a replacement needs the password and code again.
- **403 `forbidden` on a replacement start** shows "The current password or code is not valid."
- Every other problem goes to `ProblemBanner` (for example 429 with the wait, or 503). A network failure shows "The manager is unavailable. Try again later."
- **Offer.** `mode="offer"` shows **Not now** (calls `onSkip`) next to Start (#85 (a)). `required` has no skip. Sign-out is the App shell's (TASK-126).

## PasswordChange behaviour

- Fields: current password, new password, repeat new password (all `type="password"`).
- Checked before sending: the new password has at least 12 characters, counted as code points (`Array.from`), matching the server's Python `len`. "The new password must be at least 12 characters." The two new fields must be equal: "The new passwords do not match." On either failure **nothing is sent** and the fields are kept so the user can correct them.
- A valid form posts exactly `{ current_password, new_password }` once.
- **204.** `clearSession()`, then `onChanged()`. App then shows sign-in with the "password changed" note (TASK-118 `notice`). The server has ended every session of the user (#53 (a)).
- **403 `forbidden`.** "The current password is not correct." The form stays.
- **400** (the server's password rules) goes to `ProblemBanner` with `detail` as text. Other problems also go to `ProblemBanner`. A network failure shows "The manager is unavailable."

## QrCode

`qrcode-generator` (TASK-115's PD-28 runtime dependency), with type number auto and error correction M. The URI from the manager is percent-encoded ASCII (`auth/totp.py` `provisioning_uri`), so the library's byte mode encodes it exactly. The dark modules become **one SVG `<path>`** (plus a white `<rect>`), with fill set by presentation attributes (no `style=` attribute, so the CSP holds). The library's `createSvgTag`, `createImgTag` and `createDataURL` (HTML strings or `data:` URLs) are never called. If the value were too long to encode, `QrCode` renders nothing, and the text form is still shown. The drawing is memoised on `value`. `<svg role="img" aria-label="QR code of the TOTP secret">`.

## Where secrets live and when they are cleared (for the second look)

- **TOTP secret and `otpauth_uri`.** Held only in `TotpEnrol`'s `step` state (`{kind: "confirm", secret, uri}`). They are dropped (step set back to `{kind: "start"}`): (1) on a successful confirm, before `onDone()`; (2) on a 403 or 409 to the confirm; (3) when the component unmounts (leaving the screen). They appear in the DOM only as the `<code>` text nodes and the QR path while the confirm step is on screen. **Clearing from memory and from the QR element:** setting the step back to `{kind: "start"}` replaces the only state object that holds the secret and URI. React then unmounts the confirm form, including the two `<code>` nodes and the `QrCode` component. `QrCode`'s memoised drawing (the SVG path derived from the URI, held in its `useMemo`) is discarded with it, and the `<svg>` element is removed from the DOM. After that, no component state, memo or DOM node references the secret or URI. The library's matrix object exists only inside `draw()` while it runs. JavaScript cannot zero strings, so "cleared" means every reference is dropped and the strings are left to garbage collection. They never go to storage, the URL or hash, `console`, or `ProblemBanner`. Nothing in these files calls `console`.
- **The current password and current code (replacement)** and **the new TOTP code (confirm).** Held in component state. Each is emptied **before** the request is sent, on every attempt. The request body object lives only for that call.
- **Password change.** All three password fields are emptied **before** the request is sent on every attempt that is sent. A local validation failure sends nothing and keeps the values in component state (they go when the component unmounts).
- **The session token.** The confirm answer's new `bsu_` token goes straight to `setSession()`, which replaces the old one in the session store (TASK-116). This screen keeps no copy. After a password change, `clearSession()` drops the token.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No `dangerouslySetInnerHTML` or `innerHTML`, no `style=`, no `fetch`, no storage, no built keys (the `INTRO[mode]` lookup uses a typed variable key, as the lint rule requires), no `console`.
- `npm run build` still passes. The screens are not yet in the bundle, because `main.tsx` is wired in TASK-126.

## Notes for the tester (TP-M5-12, `src/screens/Account.test.tsx`)

- Labels: "Current password", "Current code" (replacement start); "Code" plus the button "Confirm" (confirm step); "Start", "Not now"; password screen: "Current password", "New password", "Repeat new password", button "Change password".
- For a replacement, render `TotpEnrol mode="manage"` after `setSession({... totp_enrolled: true ...})`.
- The secret is found as the text of the `<code>` element after "Secret:". After a successful confirm or a 403 or 409, it is no longer in the DOM.
