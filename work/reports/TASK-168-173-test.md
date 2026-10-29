# TASK-168 to TASK-173 TEST: M7 web batch (TP-M7-29)

**Verdict: PASS**

Tester: tester-m7w. Worktree `Bitscan-m7`, branch `m7-catalog`, uncommitted. Windows 11 + Git Bash, from `web/`, after impl-web's message that the start-up-mapping tweak is in. Low risk: one test run and one review for the batch, with planted faults for the security rows only (decisions 2026-10-28 "Speed-up").
REQ-181, REQ-182, REQ-183; PD-34 (a); #98, #99 (d), #102 (d), #110. Spec: TS §1.4 L41, §2.1 L101, §4.3 L546–L551, §6.2 L1084, L1100–L1107, §6.3 L1133–L1141.

## Totals

| Run | Command (from `web/`) | Result |
| --- | --- | --- |
| Baseline, before any test change | `npx vitest run` | 342/345 passed, 3 failed (CHK-M5-280, expected; REQ-183 (3) adds nav entries), 0 errors, 0 skipped |
| **Final**, after the batch tests | `npx vitest run` | **516/516 passed**, 0 failed, 0 errors, 0 skipped, 0 todo (21 files) |
| M7 rows only (incl. updated CHK-M5-280) | same run, JSON reporter | 169/169 passed |
| Plants | `python -I plants.py <throwaway copy>` | 11/11 plants red; the restored copy runs 516/516 |

Per new or changed test file: `App.test.tsx` 36/36, `problems.test.ts` 68/68, `router.test.ts` 109/109, `sources.test.ts` 15/15 (new), `Profiles.test.tsx` 14/14, `ProfileDetail.test.tsx` 25/25, `PolicyUpload.test.tsx` 15/15, `Imports.test.tsx` 8/8, `Rebuild.test.tsx` 11/11 (all new). No re-runs were needed for product bugs. Test bugs fixed on the way, in my files only: a `FileList` stand-in, a page-3 count, a glob key form, and `setImmediate` typing.

## Gates

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-319 G12 | `npm run lint` | PASS | exit 0, `--max-warnings 0` |
| CHK-M7-319 G13 | `npm run typecheck` | PASS | exit 0; this includes `UserPathsArePrefixed` in `src/api/client.ts` (REQ-183 (2)) |
| CHK-M7-319 G14 | `npm run format:check` | PASS | "All matched files use Prettier code style!" |
| CHK-M7-319 G15 | `npx vitest run` | PASS | 516/516 |
| CHK-M7-317 G16 | `npm run gen:api` twice, then `cmp` and `sha256sum` against the tree's file | PASS | before = gen1 = gen2 = `9c9eac70…d7a51e`; both `cmp` silent |
| REQ-183 (2) | `node` over `manager/openapi.json` | PASS | exactly 8 M7 operations (GET/PATCH/DELETE `/policies/{id}`, GET `/policies`, POST `/policies/import`, POST `/policies/rebuild`, GET `/imports`, GET `/tasks/{id}`), all under `/api/v1/`; 0 unprefixed paths besides `/healthz`, `/readyz` |

## Per task

### TASK-168 `problems.ts` and the client (CHK-M7-311): PASS
`src/app/problems.test.ts` "CHK-M7-311", 33 cases:
- `policy_managed_on_server` gives the server-folder text at 409, 400, 403, 500 and 503.
- The start-up 503 maps only with 503, `about:blank`, the exact detail "The catalog is starting; retry shortly." and a numeric Retry-After (10, 0, 1).
- Each single change falls through to the generic text: status 500 or 502, another type, no Retry-After, no detail, another detail, a trailing space, no final full stop, other case, a prefix. So does an HTTP-date, `1.5`, `-1` or empty Retry-After, checked through `toProblem` with real `Response` headers.
- `audit_sink_unavailable` still wins by type, and unknown types stay generic.
- No message carries response text or an API-token hint.

G16 and REQ-183 (2) are above.

### TASK-169 Profiles list (CHK-M7-312): PASS
`src/screens/Profiles.test.tsx`:
- **Request and fixture:** `GET /api/v1/policies` with only `limit=50` and Bearer `bsu_`. Column headers and every row match the fixture: name, description, status (Enabled, Disabled, "Disabled (override)"), family, version, plugin count, updated. Server order is kept.
- **Link:** each name links to `#/profiles/<id>` and navigates there.
- **Status filter:** offers exactly All, Enabled and Disabled (no Deleted, #9). Enabled and Disabled send `status=`; All sends none. Changing the filter on page 2 starts again with no cursor.
- **REQ-181 (4):** 121 policies over 3 pages are shown each exactly once, with cursors `null`, `c50`, `c100`; Previous goes back.
- **Hostile text:** a hostile name, description and family render literally and create no `script` or `img`.
- **Refusals:** a 503 shows the banner; a network failure shows unavailable. The list has no admin control.

### TASK-170 Profile detail (CHK-M7-313): PASS
`src/screens/ProfileDetail.test.tsx`:
- **REQ-181 (1):**
  - Exactly one `GET /api/v1/policies/7`, and all 10 profile fields as listed.
  - Plugins given out of order (sort_order 2, 0, 1) are shown 0, 1, 2. Each heading is exactly `CIS Ubuntu 24.04 - 1.1.n - …` (TS §1.4).
  - Each card shows its description, control, operator, expected result, timeout, plugin id and `Execute` (in `<pre>`, as text). A null `control_ref` shows "none", and a retired plugin shows Retired.
  - "Disabled (override)" shows as such; a 404 shows "Profile not found."
- **REQ-181 (2):** a deleted policy shows Deleted and no button at all, for admin, operator and viewer.
- **REQ-181 (3):**
  - The buttons per state are exact (Disable or Enable, plus Clear override when overridden, plus Delete).
  - Disable sends exactly `{"policy_status":"disabled"}`, Enable `{"policy_status":"enabled"}` and Clear override `{"status_overridden":false}` (`toStrictEqual`), each as one PATCH, `application/json`, Bearer `bsu_`, then a reload. A 409 `conflict` gives "This profile is deleted."
  - Viewer and operator get zero buttons, even with an override set.
- **REQ-182 (2):**
  - Delete opens a confirmation; Cancel sends nothing, and Confirm sends exactly one `DELETE`, with no body, then reloads to Deleted.
  - A 409 `policy_managed_on_server` shows the server-folder text. A 403 `totp_session_required` shows "Sign in again", no `input`, `textarea` or `select`, no "api token" or `bsk_` text, and no retry with another credential.
  - A 503 `audit_sink_unavailable` shows the paused text, and a DELETE 404 shows "Profile not found."
- **Hostile text:** hostile values in every stored text field, including `display_name`, `execute`, `operator` and the delete question, create no element.

### TASK-171 Upload (CHK-M7-314): PASS
`src/screens/PolicyUpload.test.tsx`:
- **REQ-182 (1), the request:** exactly one `POST /api/v1/policies/import`, Bearer `bsu_`, and a `multipart/form-data; boundary=` type, so no JSON type was set.
  - The `FormData` holds exactly one entry, `["file", "cis.bit", <the chosen bytes>]`; the content has CRLF, a tab and `é`, compared exactly. The file's own name is sent unchanged.
  - With no file there is a note and no request. The form holds one file input (`accept=".bit"`) and no token field.
- **Success and rejection:**
  - Success shows "Imported", "Import 41" and "CIS Ubuntu 24.04 Level 1 - Server, version 3: 2 plugins added, 5 updated, 1 retired.", with a link to `#/profiles/7`. Its warnings are listed (#110).
  - A rejection shows "Rejected" and "the catalog is unchanged", with no link, and every finding's line, element, code and message (null line → "none", null element → "file").
  - A second upload replaces the first outcome.
- **Refusals:** 413 gives the 5 MiB text, 409 `policy_managed_on_server` its text, and the start-up 503 the catalog-starting text. A 403 gives the role text and a network failure gives unavailable.
- **REQ-182 (5):** a hostile policy name, finding element, code and message, and a hostile server detail, render literally.
- **Harness note:** `src/test/harness.ts` now records `contentType` and the `FormData` given to `new Request`. In this test environment, undici serialises a jsdom `FormData` with the filename `blob` and an empty part (probed). The bytes are therefore checked on the `FormData` itself, not on the serialised body; a browser does not do this.

### TASK-172 Import history (CHK-M7-388) and Rebuild (CHK-M7-389): PASS
`src/screens/Imports.test.tsx`:
- **Request:** `GET /api/v1/imports` with only `limit=50`.
- **Columns:** id, file, mode, outcome, version ("none" when null), "1 / 2 / 3", by ("user 4" or "server"), and time. The server's order is kept (10, 30, 20 stays 10, 30, 20).
- **Findings:** a table of line, element, code and message, or "none".
- **REQ-182 (4):** 120 rows newest first over 3 pages are shown each once.
- **REQ-182 (5):** hostile file names and messages render literally.
- **Refusals:** a 403 shows the role text; a network failure shows unavailable.

`src/screens/Rebuild.test.tsx` (fake `setTimeout`, imported `POLL_MS`):
- **Start:** Cancel sends nothing; Confirm sends one `POST /api/v1/policies/rebuild` with an empty body.
- **REQ-182 (3) polling:**
  - For running, running, succeeded: the first `GET /tasks/{id}` comes at once, none at `POLL_MS - 1`, the second at `POLL_MS` and the third at `2 × POLL_MS`. Then nothing for 10 × `POLL_MS`, the timer count is 0, and the button is enabled again (disabled while running).
  - For running then failed: 2 GETs, then none, and the error text is shown.
  - A refusal while polling, or leaving the screen, stops the polling.
- **Result:** succeeded shows the files table and all five result fields.
- **Start refusals:** a 403 `totp_session_required` shows "Sign in again", no input, no API-token text, exactly one POST with the `bsu_` and no poll. `audit_sink_unavailable` and the start-up 503 show their texts.
- **Hostile text:** hostile `source_file`, leftovers, `not_imported` and failure text render literally.

### TASK-173 routes, roles, navigation (CHK-M7-390): PASS
- `src/app/router.test.ts`: `#/profiles`, `#/profiles/<id>`, `#/catalog/upload`, `#/catalog/imports` and `#/catalog/rebuild` parse and print back to the same hash. This covers ids 0, `007` (not normalised), 20 digits and 9007199254740993 (above 2^53, kept as a string). 25 malformed hashes give the host list, and `isPolicyId` boundaries hold (21 digits, Arabic-Indic, full-width and superscript digits, a space). The existing ROUTES and formatHash tables now include the new routes.
- `src/app/App.test.tsx` **CHK-M5-280 updated** (REQ-183 (3), checked against TS §6.2 L1100–L1107; Profiles and the profile route are viewer, and upload, `/imports` and rebuild are admin):
  - viewer and operator: Hosts, Package search, **Profiles**, TOTP, Password;
  - admin: Hosts, Package search, **Profiles, Upload policy, Import history, Rebuild catalog**, Enrolment requests, Enrolment tokens, TOTP, Password.
- **CHK-M7-390 (shell part):**
  - Viewer and operator on the three catalog hashes get "This page is not available for your role." and send **no request** to `/policies/import`, `/imports`, `/policies/rebuild` or `/tasks/` (REQ-183 (3)).
  - On Profiles and a profile they see no Enable, Disable, Clear override or Delete, and send no PATCH or DELETE. The detail page marks Profiles as current, with the "Profile detail" crumb.
  - An admin gets the three screens and the actions, and no rebuild is sent until the admin acts. Each M7 nav entry's href is its hash and is marked current there.

## Security rows

| Check | What | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-392 | Hostile `<script>…<img onerror=…>` in every stored text, rendered inside the shell on Profiles, a profile, Import history, an upload's findings and a rebuild's files | PASS | `container.textContent` holds the literal string; `querySelectorAll("script, img")` is 0 in the container and the document |
| CHK-M7-391 | No `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `createContextualFragment`, `DOMParser`, `document.write`, `srcdoc`, storage, `fetch`, `XMLHttpRequest` or `createClient` outside `src/api/client.ts` | PASS | `src/app/sources.test.ts` scans every product source with comments stripped (the M7 files are asserted present). Also `grep` of the new files: none |
| CHK-M7-393 | The token is never in a URL, a body or storage across Profiles, a PATCH, an upload, Import history and a rebuild with its poll | PASS | every non-login call carries `Bearer bsu_…`; no call URL or body holds it; `watchSecrets` (storage, cookie, IndexedDB, console, history, `location.href`) is empty |
| CHK-M7-390, -313 | Admin-only actions are hidden from viewer and operator | PASS | as above |

### Plants (each in a throwaway copy, one at a time, file restored after; copy then 516/516)

| Plant | Fault | Red tests (vitest) | Lint (G12) |
| --- | --- | --- | --- |
| CHK-M7-370 | `dangerouslySetInnerHTML` for the description in `ProfileDetail.tsx` | 3 red: CHK-M7-313 (e), CHK-M7-391 "no source uses dangerouslySetInnerHTML", CHK-M7-392 `#/profiles/7` | red (exit 1) |
| CHK-M7-394 | `Findings` writes the message with `Object.assign(el, {innerHTML})` | 4 red: CHK-M7-314 (d), CHK-M7-388 (c), CHK-M7-391 innerHTML, CHK-M7-392 imports | green (exit 0): a form the lint misses, caught by the tests |
| CHK-M7-371a | Rebuild shows an "API token (bsk_)" input on `totp_session_required` | 1 red: CHK-M7-389 (c) 403 | green |
| CHK-M7-371b | Rebuild retries the POST with a `bsk_` Bearer on a 403 | 1 red: CHK-M7-389 (c) 403 | green |
| CHK-M7-395 | Rebuild writes the token (read off a sent request) to `sessionStorage` | 4 red, including CHK-M7-393 and CHK-M7-391 sessionStorage | red |
| CHK-M7-396 | Profile detail puts the token in the page URL (`history.replaceState`) | 9 red; CHK-M7-393 fails on `expect(window.location.href).not.toContain(TOKEN)`, the others on the afterEach leak check | green |
| CHK-M7-397 | Import history sends the token in its query | 1 red: CHK-M7-393 | green |
| CHK-M7-398 | Detail actions for operators (`role !== "viewer"`) | 2 red: CHK-M7-313 (c) operator, CHK-M7-390 operator | green |
| CHK-M7-399 | Detail actions for every role | 4 red: viewer and operator in CHK-M7-313 (c) and CHK-M7-390 | green |
| CHK-M7-400 | `ROUTE_ROLES.rebuild` set to every role | 4 red: CHK-M5-280 viewer and operator, CHK-M7-390 viewer and operator | green |
| CHK-M7-401 | `RouteView` mounts Imports without the role check | 2 red: CHK-M7-390 viewer and operator (a GET `/imports` was sent) | green |

The first runs of CHK-M7-395 to -397 read the token through `currentSession()`, which never exposes it. That planted nothing, and -397 stayed green. The plants were redone to read the real `Authorization` header in an `openapi-fetch` middleware, which is how hostile screen code would get it; all three then went red, as above. Driver: `%TEMP%\m7w-scripts\plants.py` (outside the tree). Copy: `%TEMP%\m7w-plant\web`.

## Acceptance coverage

| Criterion | Rows |
| --- | --- |
| REQ-181 (1) list and detail render, `sort_order`, hostile text literal | CHK-M7-312 (a), (d); CHK-M7-313 (a), (e); CHK-M7-392 |
| REQ-181 (2) deleted: *Deleted*, no actions | CHK-M7-313 (b) |
| REQ-181 (3) exact REQ-168 bodies; other roles none | CHK-M7-313 (c); CHK-M7-390; plants -398, -399 |
| REQ-181 (4) paging, each once | CHK-M7-312 (c) |
| REQ-182 (1) one `file` part with the bytes; success and rejection display | CHK-M7-314 (a), (b) |
| REQ-182 (2) confirm, one DELETE, 409 text, TOTP prompt | CHK-M7-313 (d); plant -371a/b (same banner path) |
| REQ-182 (3) polling to `succeeded` or `failed` (fake timers), then files | CHK-M7-389 (b) |
| REQ-182 (4) import history each once, newest first | CHK-M7-388 (a), (b) |
| REQ-182 (5) hostile file names and messages | CHK-M7-314 (d), CHK-M7-388 (c), CHK-M7-389 (d), CHK-M7-392 |
| REQ-183 (1) G16 | Gates table |
| REQ-183 (2) `UserPathsArePrefixed` for the 8 operations | Gates table |
| REQ-183 (3) nav per role; admin route as viewer sends no request | CHK-M5-280, CHK-M7-390; plants -400, -401 |
| TASK-168: both types map; unknown generic | CHK-M7-311 |
| TASK-171: 413 and 409 messages | CHK-M7-314 (c) |
| TASK-172: 403 TOTP on rebuild shows sign-in-again | CHK-M7-389 (c) |
| TASK-173: hashes round-trip; exhaustive switch typechecks | CHK-M7-390; G13 |

## Observations (no change requested)
- `ProfileDetail` shows the API's `display_name` rather than composing `<family_name> - <plugin_name>`. The test asserts the visible heading equals family + " - " + plugin name, so either way would pass. A wrong `v_plugin` would show up there only if the fixture's `display_name` were also wrong; that is manager-side (TASK-161).
- `toProblem` treats a body with no `type` as `about:blank` (M5 behaviour), so a typeless 503 with the exact detail and a Retry-After also maps to the start-up text. This matches RFC 9457's default type.

## Files (tester-owned)
`web/src/app/App.test.tsx` (CHK-M5-280 updated, M7 rows added), `web/src/app/problems.test.ts`, `web/src/app/router.test.ts`, `web/src/app/sources.test.ts` (new), `web/src/screens/{Profiles,ProfileDetail,PolicyUpload,Imports,Rebuild}.test.tsx` (new), `web/src/test/harness.ts` (`contentType`, `form`), `tests/m7/test-plan.md` (rows CHK-M7-306 to -314, -388 to -401). The `tests/m7/report.md` rows are this file's tables; main folds them in, because the harness blocks my write there.
