# TASK-168 to TASK-173 IMPL: M7 web (profiles, catalog admin screens, client, navigation)

Implementer: impl-web. Worktree `Bitscan-m7`, branch `m7-catalog`, not committed.
REQ-181, REQ-182, REQ-183; PD-34 (a); #98, #99, #102 (d), #110; decisions row "Speed-up" (2026-10-28).
Spec: TS §1.4 L41, §2.1 L101, §4.2, §4.3 L546–L551, §6.2 L1084, L1100–L1107, §6.3 L1137–L1141.

The final M7 `manager/openapi.json` (impl-manager-m7, W8) arrived during the build. So TASK-168 was done in the same pass, and every screen typechecks against the real generated client; nothing is coded against guessed shapes.

## Gates (from `web/`, Windows + Git Bash)

| Gate | Result |
| --- | --- |
| `npm run typecheck` | clean, including `UserPathsArePrefixed` in `src/api/client.ts` |
| `npm run lint` | clean (0 warnings) |
| `npm run format:check` | clean |
| G16: `npm run gen:api` run twice | `schema.d.ts` byte-identical (`cmp`); 35 `/api/v1/` paths, plus `/healthz` and `/readyz` only |

`npx vitest run` (tests are the tester's; run only to report): 342/345 pass. The 3 failures are `App.test.tsx` CHK-M5-280 "navigation per role", which lists the exact M5 nav entries. REQ-183 (3) adds the new entries, so the expected lists need updating (see "For the tester"). Router and problems tests still pass.

## TASK-168: client regeneration and problem mapping

- `web/src/api/schema.d.ts`: regenerated with `npm run gen:api` from the final `manager/openapi.json`. Generated only; no hand edits.
- `web/src/app/problems.ts` `messageFor`:
  - `policy_managed_on_server` (any status) gives "This policy is managed in the server folder. Change or remove its file on the server." (action null).
  - The #102 (d) start-up answer gives "The catalog is starting; retry shortly." **Revision 1 (lead ruling (3), 2026-10-28):** `isCatalogStarting` needs all four of: status 503, type `about:blank`, `detail` exactly "The catalog is starting; retry shortly.", and a numeric `Retry-After`. Any other 503 (another detail, no or non-numeric `Retry-After`, another type) still gives "The manager is unavailable. Try again later."
  - The detail is only compared; the text shown is the fixed constant `CATALOG_STARTING` in `problems.ts`, never the response text. (Revision 0 matched on 503 + `about:blank` + `Retry-After` alone.) Gates re-run after r1: typecheck, lint and format:check clean; `problems.test.ts` 46/46.
  - An unknown type still falls through to the generic status messages, unchanged.
- ProblemBanner still shows the server `detail` as a text node below the fixed message. So these two answers show their fixed text, then the server's own sentence.

## TASK-169: `web/src/screens/Profiles.tsx` (166 non-blank lines)

- `GET /api/v1/policies` with `limit=50`, cursor paging (`useCursorPages`, `Pager`).
- A status filter (All / Enabled / Disabled): All sends no `status`, and the list never holds deleted policies (#9). Changing the filter resets paging.
- Columns: name (link to `#/profiles/<id>`), description, status, family, version, plugin count, updated.
- `PolicyStatusBadge` shows Enabled or Disabled, with " (override)" when `status_overridden`. It is exported and reused by the detail screen.
- Every value is a JSX text node.

## TASK-170: `web/src/screens/ProfileDetail.tsx` (262 non-blank lines, over the 190 estimate; see "Size")

- `GET /api/v1/policies/{id}`; the id stays a digit string (route and API path pattern `^[0-9]{1,20}$`).
- Fields: family, status, file status, override, version, format version, source file, imported, updated, deleted.
- A deleted policy (`deleted_at` set) shows a **Deleted** badge in place of the status badge, and **no actions** (REQ-181 (2)).
- Plugins are sorted by `sort_order`, each a card titled with the API's `display_name` (`<family name> - <plugin name>`, from `v_plugin`, TS §1.4). Each card holds the description, control ref, operator, expected result, timeout, plugin id and a **Retired** badge where it applies. `Execute` is in a `<pre>` as a text node.
- Admin only (`role === "admin"`), not deleted:
  - Status buttons send exactly the REQ-168 bodies: "Enable" `{"policy_status":"enabled"}` (shown when disabled); "Disable" `{"policy_status":"disabled"}` (shown when enabled); "Clear override" `{"status_overridden":false}` (shown when overridden).
  - **Delete** goes through `Confirm` (danger tone), then exactly one `DELETE /api/v1/policies/{id}`.
- Answers:
  - 2xx gives a status note, then a reload.
  - 409 `conflict` gives "This profile is deleted."; 404 gives "Profile not found."
  - Any other refusal goes to ProblemBanner: 409 `policy_managed_on_server` gets its TASK-168 message; 403 `totp_session_required` gets the "Sign in again" button (no API-token field anywhere).
- Viewer and operator see no buttons. The server still enforces every rule.

## TASK-171: `web/src/screens/PolicyUpload.tsx` (148) + `web/src/components/Findings.tsx` (40, new)

- A file input (`accept=".bit"`) and an Upload button.
- The body is a `FormData` with one part, `file`, holding the chosen `File` (and its name). It is sent through the generated client: `api.POST("/api/v1/policies/import", { body: { file: "" }, bodySerializer: () => form })`.
  - The `body` value is a typed placeholder; the generated type models the binary part as `string`.
  - openapi-fetch sets no `Content-Type` for a `FormData` body, so the browser adds the multipart boundary. No hand-written `fetch`.
- 200 `success` shows "Imported", the policy name, version, added, updated and retired counts, a link to the profile, and the findings (warnings, #110).
- 200 `rejected` shows "Rejected", "the catalog is unchanged" and the findings table.
- 413 gives "The file is too large. A .bit file may be at most 5 MiB." Other refusals go to ProblemBanner (409 `policy_managed_on_server`, 503 start-up).
- No file chosen gives a note and sends no request.
- `Findings` is a table of line ("none" if null), element ("file" if null), code and message, all text nodes. It is shared with Imports.

## TASK-172: `web/src/screens/Imports.tsx` (135) and `web/src/screens/Rebuild.tsx` (189)

**Imports**
- `GET /api/v1/imports`, cursor paging, in server order (newest first, #98 (h)), no filters.
- Columns: id, file name, mode, outcome badge, version ("none" if null), added / updated / retired, by ("server" if `imported_by` is null, else "user N"), imported time, findings.
- Findings sit in a native `<details>` with the `Findings` table.

**Rebuild**
- `Confirm`, then `POST /api/v1/policies/rebuild` with no body. A 202 gives the `task_id`.
- Then `GET /api/v1/tasks/{id}` at once, and again every `POLL_MS` (2000 ms, exported for fake-timer tests) via `window.setTimeout` while `state === "running"`. Polling stops at `succeeded` or `failed`, on any refusal (ProblemBanner) or on a network failure (a note). The timer is cleared on unmount.
- Shows `Task <id>` and a status line (Running. / Succeeded. / Failed.), started and finished times, and then:
  - a `TaskFailure` gives `result.error` as text;
  - a `TaskResult` gives a files table (source file, outcome, import id, policy id, version), then not imported, deleted policy ids, plugins retired and leftovers removed.
- While a task runs, the Rebuild button is disabled.
- 403 `totp_session_required` shows the sign-in-again prompt through ProblemBanner.

## TASK-173: routes, role table, navigation

- `web/src/app/router.ts`: new routes and their hashes.

  | Route | Hash |
  | --- | --- |
  | `profiles` | `#/profiles` |
  | `profile` (`policyId`) | `#/profiles/<1–20 ASCII digits>` (new `isPolicyId`, no regular expression; not normalised, so it prints back as parsed) |
  | `policy-upload` | `#/catalog/upload` |
  | `imports` | `#/catalog/imports` |
  | `rebuild` | `#/catalog/rebuild` |

  Anything else is still the host list. Both exhaustive switches cover the new routes.
- `web/src/app/routes.tsx`:
  - `ROUTE_ROLES`: profiles and profile go to every role; policy-upload, imports and rebuild to admin.
  - A new nav group, "Compliance", between Fleet and Enrolment: Profiles (every role); Upload policy, Import history and Rebuild catalog (admin).
  - `entryFor` maps profile to Profiles. `RouteView` renders the five screens; ProfileDetail is keyed by `policyId` and gets `role`.
  - A route the role may not open still renders only "Not available", so its screen never mounts and sends no request (REQ-183 (3)).
- `web/src/app/App.tsx` (lead ruling: navigation lives in the shell): `isActive` now uses `entryFor`, so a detail page marks its list's entry; the breadcrumb says "Profile detail" on a profile.
- `web/src/components/Icon.tsx`: four nav icons (`profiles`, `upload`, `imports`, `rebuild`), inline SVG paths only.

## Files

| Task | Files |
| --- | --- |
| 168 | `web/src/api/schema.d.ts` (generated), `web/src/app/problems.ts` |
| 169 | `web/src/screens/Profiles.tsx` (new) |
| 170 | `web/src/screens/ProfileDetail.tsx` (new) |
| 171 | `web/src/screens/PolicyUpload.tsx` (new), `web/src/components/Findings.tsx` (new) |
| 172 | `web/src/screens/Imports.tsx` (new), `web/src/screens/Rebuild.tsx` (new) |
| 173 | `web/src/app/router.ts`, `web/src/app/routes.tsx`, `web/src/app/App.tsx`, `web/src/components/Icon.tsx` |

**Outside the task rows' file lists:** `App.tsx` (lead ruling), `Icon.tsx` (nav icons) and `components/Findings.tsx` (shared by 171 and 172). Nothing outside `web/` was touched. `npm ci` was run in `web/` to install `node_modules`; `package.json` and `package-lock.json` are unchanged.

## Size

- **TASK-170 (262 non-blank lines vs 190)** and **TASK-172 (324 vs 190)** are over the estimate. Cause: Prettier's JSX layout, and the loading / not-found / failed / unavailable branches each screen repeats from the existing pattern (`HostDetail`, `Hosts`).
  - In TASK-170 the three status buttons are already folded into one list.
  - In TASK-172 the rebuild result shows every `TaskResult` field the contract returns.
  - The logic in each screen is small: one GET, one or two mutations, one poll loop.
- Each task is still at most 4 files. The lead decides whether to split; nothing is split now.

## Security checks (builder checklist and web rules)

- No `dangerouslySetInnerHTML`, `innerHTML`, Markdown or HTML renderer (grep of the new files: none). Every API value is a text node or an attribute value (`aria-label`, `href` built only from a digit id).
- No hand-written `fetch`; every call goes through `api` from `src/api/client.ts`. The token is untouched (session.ts unchanged, in memory only).
- No message is built from response text. The problem messages are fixed. The server `detail` is shown only as a text node by the existing ProblemBanner.
- No API-token prompt anywhere; a TOTP-session refusal offers only "Sign in again".
- No editor or plugin edit; the only mutations are the TS §6.2 routes (PATCH status, DELETE, import, rebuild).

## For the tester (TP-M7-29)

- Lead rulings (2026-10-28): tester-m7w takes TP-M7-29 and updates CHK-M5-280 (its file). The sizes for 170 and 172, and the extra files (`App.tsx`, `Icon.tsx`, `Findings.tsx`), are accepted.
- Start-up mapping (r1): to show the start-up message, the answer needs all four of 503, `about:blank`, the exact detail and a numeric `Retry-After`. Change any one of them and the generic 503 text shows.

- **CHK-M5-280** (`App.test.tsx`, "navigation per role") must be updated for REQ-183 (3).
  - viewer and operator: Hosts, Package search, **Profiles**, TOTP, Password.
  - admin: Hosts, Package search, **Profiles, Upload policy, Import history, Rebuild catalog**, Enrolment requests, Enrolment tokens, TOTP, Password.
  - Hashes as in the TASK-173 table.
- Hostile text: names, descriptions, plugin fields, `execute`, file names, finding messages and task `source_file` all render through JSX text.
- Upload: inspect the `Request` body as `FormData` (`file` part). openapi-fetch passes the `FormData` through, so no JSON `Content-Type` is set.
- Rebuild polling: import `POLL_MS` and use fake timers. The first `GET /tasks/{id}` runs right after the 202; each next one runs after `POLL_MS` while `running`.
- Detail: the id in the path is the route's digit string.
