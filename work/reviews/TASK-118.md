# TASK-118 REVIEW: sign-in screen

Verdict: APPROVED, no open blocking or should-fix findings (and no nits).

Reviewer: reviewer, 2026-10-25. One review round (UI). **The user's second look applies (PD-30 (2)); the user pre-authorised it on a clean TEST PASS plus this verdict.**

Scope reviewed: `web/src/screens/SignIn.tsx`, new and the only file (`work/reports/TASK-118-impl.md`). Sources: REQ-121, REQ-120, REQ-132, REQ-133, TS §6.2 L1080 and L1086–L1089, §6.3 L1136, #48, #85 (a) and (e).

TEST: PASS (tester-m5, 2026-10-25). 24/24 tests pass and every plant is red.
- The password and the TOTP code are emptied before the request is sent.
- The token and passwords never reach Web Storage, cookies, IndexedDB, the console, history or the URL.

## Where the secrets live (for the user's second look)
- **Password and TOTP code.** They live only in this screen's form state. When the form is submitted, the request body is built and both fields are emptied at once, before the request leaves, on every attempt. The username is kept so the user can retry.
- **The `bsu_` token.** It is passed from the 200 answer straight to the session store (TASK-116). This screen keeps no copy.
- Nothing is logged, stored or put in the URL.

## Checks
1. Spec (REQ-121):
   - (1) The body is exactly `{username, password, totp_code}`, with `null` for an empty code. The code field is shown to everyone (#85 (e)).
   - (2) Every 401 shows one fixed message, and the server's `detail` is not shown (#48), so different 401s look identical.
   - (3) A 429 shows the `Retry-After` wait, and the button stays disabled for that long. The timer is capped at 2^31 − 1 ms and cleared on unmount.
   - 503 and network failures say the manager is unavailable.
   - (4) The password field is `type="password"`, and both fields are cleared before each request.
   - (5) On success, `nextScreen()` picks the next screen (#85 (a)).
2. Sign-in is sent with no bearer header (there is no session yet), so a 401 here never clears anything.
3. REQ-132: every value is rendered as text, and other problems go through `ProblemBanner` with `detail` as text.
4. No `dangerouslySetInnerHTML`, `innerHTML`, `style=`, `fetch`, storage or `console`.
5. Re-run by the reviewer (Windows): `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
6. Scope: 1 file, 144 code lines.

## Findings
None.
