# TASK-118 IMPL: sign-in screen

Owner: impl-web. REQ-121, REQ-120, REQ-132; #85 (e); #48. Builds on TASK-116 and TASK-117. Worktree `Bitscan-m5`. **User second look (PD-30 (2))**: this screen handles passwords and TOTP codes. See "Where secrets live" below.

## Files

| File | Code lines |
| --- | --- |
| `web/src/screens/SignIn.tsx` (new) | 144 |

Nothing else changed.

## Props (screen contract, `work/plans/TASK-116.md`)

`SignIn({ onSignedIn: (next: NextScreen) => void; notice?: "password-changed" })`

## Behaviour

- **Fields.** Username (`autocomplete="username"`, required); password (`type="password"`, `autocomplete="current-password"`, required); a TOTP code field shown to everyone and labelled "TOTP code (required for admins and accounts with TOTP)" (#85 (e)), with `inputmode="numeric"` and `autocomplete="one-time-code"`.
- **Request.** `POST /api/v1/auth/login` through the generated client. The body is exactly `{ username, password, totp_code }`, with `totp_code: null` when the field is empty. Values are sent as typed (not trimmed). No bearer header is sent, because there is no session yet.
- **Success (200).** `setSession(data)` (TASK-116), then `onSignedIn(nextScreen(view))`, which gives `"totp-required"` for an admin without TOTP, `"totp-offer"` for a non-admin without TOTP, and `"hosts"` otherwise (REQ-133 / #85 (a)).
- **401.** Always the same fixed text: "Sign-in failed. Check your username, password and TOTP code." The server's `detail` is **not** shown for a 401, so two different 401 problems render identically (REQ-121 (2), #48).
- **429.** `ProblemBanner` shows "Too many requests. Wait N seconds." (N from `Retry-After`, TASK-116 text), and the Sign in button stays disabled for N seconds (a `setTimeout`, cleared on unmount, capped at 2^31 − 1 ms). With no or a non-integer `Retry-After`, the message says "Wait a moment." and the button is not held.
- **503.** `ProblemBanner`: "The manager is unavailable. Try again later." plus `detail` as text.
- **Other problems (e.g. 400).** `ProblemBanner` with the generic text and `detail` as text.
- **Network failure** (the client rejects). "The manager is unavailable. Try again later."
- **While a request is in flight** the button is disabled.
- **Notice.** With `notice="password-changed"` it shows "Your password was changed. Sign in again." (`role="status"`), used after TASK-119's password change.

## Where secrets live and when they are cleared (for the second look)

- **Password and TOTP code.** Held only in this component's `useState`. When the form is submitted, the request body is built from them and **both fields are emptied immediately, before the request is sent**, on every attempt (success, 401, 429, 503 or network error; REQ-121 (4)). The username is kept so the user can retry. Nothing is written to storage, cookies, the URL or the console, and no error text includes them.
- **The `bsu_` token.** It arrives in the 200 body and is passed straight to `setSession()`. This screen keeps no copy (no state, no variable outside the handler). From then on the session store (TASK-116) is its only holder.
- **On unmount** (after success, App shows the next screen) the component state, including the username, is dropped.
- The request body object exists only for the length of the handler call.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No HTML rendering, no `style=`, no `fetch`, no storage, no built keys, no `console`.

## Notes for the tester (TP-M5-11, `src/screens/SignIn.test.tsx`)

- Inputs can be found by label: "Username", "Password", "TOTP code (required for admins and accounts with TOTP)". The button is "Sign in".
- Submit with `fireEvent.submit(form)` or a click on the button. `required` blocks native submit in a browser only.
- The 429 hold uses `setTimeout(…, N * 1000)`, so fake timers work. The button is re-enabled when the timer fires.
- The fields are emptied before the `await`, so they are empty while the request is pending, too.
