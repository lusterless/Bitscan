# TASK-120 IMPL: enrolment tokens screen

Owner: impl-web. REQ-124, REQ-126, REQ-132; TS §3.2 (L181), §8.4; #68. Builds on TASK-116 and TASK-117. Worktree `Bitscan-m5`.

## Files

| File | Code lines |
| --- | --- |
| `web/src/screens/EnrolmentTokens.tsx` (new) | about 263 |

Nothing else changed. The size is over the planned 180, mostly the create form's and the table's JSX (one attribute per line under Prettier). Props are `{}` (screen contract).

## Behaviour

- **Create form** (`<form aria-label="Create enrolment token">`):
  - "Max uses (1 to 10,000)", number input, default `1`.
  - "Expires in hours (1 to 720)", number input, default `24`.
  - "Allowed CIDRs (optional, one per line)", textarea. Entries split on whitespace and commas; an empty textarea sends `null`.
  - "Auto-approve new hosts", checkbox, default off.
  - **An untouched form posts exactly `{max_uses: 1, expires_in_hours: 24, allowed_cidrs: null, auto_approve: false}`** (REQ-124 (1)) with `POST /api/v1/enrollment-tokens`.
  - If max uses or hours is not a whole number in range, the form shows "Max uses must be 1 to 10,000 and the expiry 1 to 720 hours." and sends nothing. The server checks again (CIDRs are left to the server; a 400 shows its `detail`).
- **Hint and alert note** (REQ-124 (2), TS §3.2 L181): "A multi-use token should set max uses to the expected number of hosts and set allowed CIDRs." and "Creating a token with auto-approve or more than 100 uses raises an alert."
- **Creation result** (`<section aria-label="New enrolment token">`): "Copy this token now. It is shown only once.", the token in a `<code>` text node, a **Copy** button (`navigator.clipboard.writeText`; "Copied." on success; a missing or refused Clipboard API is caught and nothing is shown), the token id, max uses and expiry, and **Done**. While the result is shown, it replaces the form.
- **List**: `GET /api/v1/enrollment-tokens?limit=50[&cursor=…]`, with paging through `useCursorPages` and `Pager` (TASK-117). Columns: ID, Uses (`uses / max_uses`), Auto-approve, Allowed CIDRs (`any` when null), Expires, Created, Created by (user id), Revoked (`not revoked` or the time). The list items carry no token (`TokenItem` has none).
- **Revoke**: only for rows not yet revoked. `Confirm` ("Revoke", then "Confirm"), then `DELETE /api/v1/enrollment-tokens/{token_id}` **once**. Then the list is re-read, and the row shows its `revoked_at` (REQ-124 (4)).
- **Problems**: action refusals (create, revoke) and list refusals each show in a `ProblemBanner`. `403 totp_session_required` shows the TASK-116 message and a **Sign in again** button. No field ever asks for an API token (REQ-126 (2), CHK-M5-347). `503 audit_sink_unavailable` shows the paused message. A 400 shows its `detail` as text (REQ-124 (5)). A network failure shows "The manager is unavailable. Try again later."
- The list is re-read after every create or revoke attempt. A list answer that arrives after the screen unmounted, or after a newer list request, is ignored.

## Where the created token lives (CHK-M5-346)

- The `bse_` token from the 201 answer is held only in the `created` state. **Done** sets it to `null`. Unmounting the screen drops it too. Its only DOM presence is the `<code>` node in the result section. The Copy handler copies it into a local for the length of the clipboard promise. It is never written to storage, the URL or `console`. The clipboard copy is the user's explicit action (REQ-124).
- The list state (`Page_TokenItem_`) holds no token.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No HTML rendering, no `style=`, no `fetch`, no storage, no built keys (React keys are `item.token_id`), no `console`.
- `split(/[\s,]+/)` runs only on the admin's own typed CIDR text in their browser, not on stored or server data.

## Notes for the tester (TP-M5-13, `src/screens/EnrolmentTokens.test.tsx`)

- On mount, the screen sends `GET /api/v1/enrollment-tokens?limit=50`. After each create or revoke, it sends one more list request.
- Revoke row buttons are named "Revoke". After a click, the alertdialog's "Confirm" button sends the `DELETE`.
- jsdom has no `navigator.clipboard`. Stub it (for example `Object.defineProperty(navigator, "clipboard", …)`) to test Copy.
