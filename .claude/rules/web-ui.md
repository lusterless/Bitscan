---
paths:
  - "web/**"
---

# Web UI

Spec: TS §6.2 (routes and roles), §6.3 (conventions), §4.3 (profiles), §4.5 (results) and §7.3 (package search UI).

- TypeScript strict mode, ESLint and Prettier. Call the API only through the client generated from the OpenAPI document; never hand-write fetch calls for API routes.
- Keep the session token (`bsu_`) in memory only and send it as `Authorization: Bearer`. Never store it in `localStorage`, `sessionStorage` or any cookie.
- Render every stored value as plain text: hostnames, stdout, package names, `.bit` names and descriptions, usernames and audit details. Never use `dangerouslySetInnerHTML`, `innerHTML` or a Markdown or HTML renderer on API data.
- Do not load scripts, styles or fonts from other origins; the Content-Security-Policy allows only `'self'`. There is no CORS.
- Show raw stdout and stderr only when the API returns them (operator and admin). Viewers see verdicts, `eval_detail` and scores.
- Show both the current verdict and `original_result` when a result has been re-evaluated. Plugins with no result show as *Not run*. Show the score with the error count beside it, and "n/a" when the score is NULL.
- Profiles list `policy_name` and `policy_description`; plugins appear as `<family name> - <plugin name>` in `.bit` order (TS §4.3).
- There is no policy editor: policies change only by uploading a new `.bit` file.
- TOTP-session actions:
  - enrolment approve and reject, agent revoke, rebuild, re-evaluate, policy delete;
  - managing users, enrolment tokens and settings.

  The UI must prompt for TOTP rather than fall back to an API token.
- Creating API tokens and enrolling or replacing TOTP happen only in the UI, from a session. Replacing TOTP asks for the current password and a current code. Offer TOTP enrolment to every new user at first sign-in.
- An admin without TOTP sees only the TOTP enrolment screen and sign-out.
- The enrolment approval screen shows hostname, source IP, OS, and any agent with the same hostname or machine-id. The enrolment-token form hints that a multi-use token should set `max_uses` to the expected host count and set `allowed_cidrs`.
- Package search uses the TS §7.1 parameters, with type-ahead (top 10 names) and results grouped package → version → host count, with click-through to the host list (TS §7.3). The CSV export comes from `/packages/search.csv`; the server already escapes formula cells. The host page shows added / removed packages since the last snapshot.
- **Decided** (`work/open-questions.md` #32, owner-approved): no new route. From 3 characters, the UI calls `/packages/search` with `q`, `group_by=package` and `limit=500` and offers at most 10 distinct names; choosing one fills the exact-name filter.
- A policy can show the states *Disabled* and *Deleted*. There are no approval states.
- Show changes to a host's enabled runner helpers (`runner_helpers`); the manager shows and audit-logs any change (TS §3.7).

Tests: CI gates on `web/` (TS §8.2: strict typecheck, ESLint, Prettier, OpenAPI client regenerated with no diff); UI tests that a `<script>` hostname renders as text (TS §6.3).
