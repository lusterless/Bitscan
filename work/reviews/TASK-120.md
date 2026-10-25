# TASK-120 REVIEW: enrolment tokens screen

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed: `web/src/screens/EnrolmentTokens.tsx`, new and the only file (`work/reports/TASK-120-impl.md`). Sources: REQ-124, REQ-126, REQ-132, TS §3.2 L181, §6.2 L1084 and L1116, §8.4 L1290, #68, and the owner decision on `bse_` tokens (max_uses 1–10,000, a required expiry, optional CIDRs, auto_approve off by default).

TEST: PASS (tester-m5, 2026-10-25). 23/23 tests pass, and the plants are red, including CHK-M5-346 (the token is left in the DOM or memory after Done).

## Checks
1. **Spec (REQ-124).**
   - (1) An untouched form posts exactly `{max_uses: 1, expires_in_hours: 24, allowed_cidrs: null, auto_approve: false}`. The bounds 1–10,000 and 1–720 are checked before sending, and the server checks them again.
   - (2) The TS §3.2 hint and the alert note are both shown.
   - (4) Revoke goes through `Confirm`, then sends `DELETE /enrollment-tokens/{token_id}` once, and the list is re-read.
   - (5) A 400 shows its `detail` as text.
   - (6) A TOTP-session refusal offers only "Sign in again", never an API-token field. An audit-sink outage shows the paused message.
2. **The created `bse_` token (REQ-124 (3)).**
   - It is held only in `created` and appears in the DOM once, as a `<code>` text node.
   - Done clears it, and leaving the screen drops it.
   - Copy is an explicit user action, and a missing Clipboard API is handled.
   - The list items hold no token.
   - Nothing goes to storage, the URL or the console.
3. **REQ-132.** Every value is a text node. No raw-HTML insertion, `style=`, `fetch` or storage.
4. **Regex.** The CIDR split is a browser-side split of the admin's own typed text, so the RE2 rule for untrusted input on the manager does not apply.
5. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
6. **Scope.** 1 file, about 263 lines, over the 180 estimate. The excess is form and table JSX laid out by Prettier, and I accept it for UI.

## Findings
None.
