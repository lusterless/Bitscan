# TASK-169 IMPL: Profiles list screen

Owner: impl-web-m7. REQ-181 (list half); PD-34; #9; #98 (a); TS §4.3, §6.2 (`GET /policies`, every role), §6.3 (plain text, cursor paging). Depends on TASK-168 (first pass).

## Files

| File | Change |
| --- | --- |
| `web/src/screens/Profiles.tsx` | New file, 180 lines after Prettier (estimate 120). The extra lines are Prettier layout of the table and the filter form. There is no extra feature. |

No other file changed. Routes and navigation are **not** wired; that is TASK-173. The component is exported as `Profiles`, with props `{ onOpen?: (policyId: number) => void }`. When TASK-173 passes `onOpen`, the policy name becomes a `link-btn` button that calls it with `policy_id`. Without it, the name is plain text. This lets TASK-173 wire the detail route without editing this file.

## What it does / how each item is met

- **Every role.** One call, `api.GET("/api/v1/policies", …)`, through the generated client (L58), with no role check in the screen. The route serves every role (TS §6.2).
- **Status filter (#9)** (L29, L93-L105). A select with `all`, `enabled` and `disabled`. `all` sends no `status`; the others send `status=enabled` or `status=disabled` (L57). `deleted` is never offered or sent (the list never holds deleted policies, and `deleted` would be a 400). Changing the filter resets paging to the first page (L100). Any other select value maps to `all`.
- **Cursor paging (REQ-181 (4))** follows the Hosts pattern exactly: `useCursorPages` plus `Pager`, `limit=50`, and `cursor` sent only after the first page (L56). The effect depends on `[pages.cursor, status]`, and a stale answer is dropped through the `active` flag.
- **Columns (REQ-181).** `policy_name`, `policy_description`, status, `family_name`, `version`, `plugin_count` and `updated_at` (`formatTime`). The status badge comes from a `Record` over the generated `policy_status` enum (L19), so a new enum value fails typecheck. "(set by an admin)" follows it when `status_overridden` is true. *Deleted* cannot appear in the list (#9); it is TASK-170's job on the detail screen.
- **Plain text (TS §6.3).** Every API value is a JSX text child. There is no `dangerouslySetInnerHTML`, `innerHTML` or Markdown (grep: 0 matches).
- **Errors.** A problem answer goes to `ProblemBanner` (the fixed message plus `detail` as text). A network failure shows the fixed "The manager is unavailable" callout. There are also loading and "No profiles." states.

## Gates (from `web/`)

`npm run lint`, `npm run typecheck`, `npm run format:check` and `npm test` (345/345) pass; `npm run gen:api` is stable.

## Cases for the tester (`Profiles.test.tsx`)

1. **REQ-181 (1), list.** A fixture page renders each item's name, description, status label (Enabled / Disabled), family, version and plugin count. `status_overridden: true` shows "(set by an admin)".
2. **Hostile text.** Use `policy_name` `<script>alert(1)</script>`, `policy_description` `<img src=x onerror=alert(1)>` and `family_name` `<b>x</b>`. Each renders literally as text, with no `script`, `img` or `b` element in the container.
3. **REQ-181 (4), paging.** With page 1 (`next_cursor` "c1") and page 2 (`next_cursor` null) and distinct ids, Next sends `cursor=c1` and each policy shows once across pages. Previous goes back to the first request (no cursor).
4. **Filter.** Picking `disabled` sends `status=disabled` with no cursor, even from page 2 (paging resets). Picking `all` sends no `status` param. No request ever has `status=deleted`.
5. **Requests.** Only `GET /api/v1/policies` is called, with `limit=50`, for each of viewer, operator and admin (no role gating in the screen).
6. **Errors.** A 401 or 503 problem shows the `ProblemBanner` text; a rejected fetch shows the unavailable callout.
7. **`onOpen`.** Without it the name is plain text with no button. With it, clicking the name calls `onOpen(policy_id)` once.
