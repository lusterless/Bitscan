# TASK-251 IMPL: routing, navigation, role gating, Run scan on the profile page

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W4; I started it early at the lead's request, before the W3 test and review.
REQ: REQ-279, REQ-280, REQ-281, REQ-282, REQ-283. Open items: #122 (i), #154 (c). Spec: TS §6.2 L1113, L1120–L1126.
It builds on the W3 screens and TASK-256's `ScanLinks`. If W3's test or review changes those, I carry the change here.

## Files (all existing)

| File | Change |
| --- | --- |
| `web/src/app/router.ts` | Five new `Route` variants with `parseHash` / `formatHash` |
| `web/src/app/routes.tsx` | Role table, nav entries, `entryFor` parents, `SCAN_LINKS`, the five `RouteView` cases, and `scanLinks` passed to HostDetail |
| `web/src/components/Icon.tsx` | Icons `scans` and `schedules` |
| `web/src/screens/ProfileDetail.tsx` | A Run scan link |

## Hashes

| Route | Hash | Notes |
| --- | --- | --- |
| `{name: "scans"}` | `#/scans` | |
| `{name: "scan", scanId}` | `#/scans/<uuid>` | the id is lower-cased on parse, as for hosts |
| `{name: "scan-results", scanId}` | `#/scans/<uuid>/results` | |
| `{name: "run-scan", policyId: null}` | `#/scans/run` | |
| `{name: "run-scan", policyId: "<1–20 digits>"}` | `#/scans/run/<id>` | the profile is preselected |
| `{name: "schedules"}` | `#/schedules` | |

Malformed input falls back to the host list (`{name: "hosts"}`):
- A scan id that isn't a hyphenated UUID, including the 32-hex form.
- `#/scans/run/` with an empty, non-digit or over-20-digit id.
- `#/scans/<uuid>/other` and any extra segment.
- `#/scans/`.

Every route round-trips through `formatHash` and `parseHash`.

## Roles and navigation

**Role table (`ROUTE_ROLES`):**
- `scans`, `scan`, `scan-results`: every role (the reads are viewer, TS §6.2).
- `run-scan`, `schedules`: operator and admin (`POST /scans` and every `/scan-schedules` route are operator, #122 (i)).
- A viewer reaching `#/scans/run…` or `#/schedules` by URL gets the existing "Not available" page. The screen never mounts and sends no request.

**Navigation (Compliance group), after Profiles:**
- "Scans" (`#/scans`, icon `scans`) for every role.
- "Schedules" (`#/schedules`, icon `schedules`) for operators and admins.
- Run scan has no nav entry. It is reached from Scans (operator and admin) and from a profile's page.
- `entryFor`: `scan`, `scan-results` and `run-scan` highlight "Scans". The crumb shows the entry label ("Scans"), because `App.tsx`'s `crumbLabel` is not in this task.

**Nav lists after this change:**
- Viewer: Hosts, Package search, Profiles, Scans, TOTP, Password.
- Operator: as viewer, plus Schedules.
- Admin: Hosts, Package search, Profiles, Scans, Schedules, Upload policy, Import history, Rebuild catalog, Enrolment requests, Enrolment tokens, TOTP, Password.

**Existing tests that pin the old nav.** `App.test.tsx` CHK-M5-280 pins the old per-role lists, so it needs the two new entries. This change is intended (REQ-279, REQ-282). Every other existing assertion I checked still holds:
- ProfileDetail "viewer/operator sees no action" uses a disabled profile and counts buttons. Run scan is a link and only appears for enabled profiles.
- HostDetail tests render it without `scanLinks`.

## `SCAN_LINKS` (routes.tsx, exported)

- `scansHref`: `#/scans`.
- `runScanHref`: `#/scans/run`.
- `scanHref(id)`: `#/scans/<id>`.
- `resultsHref(id)`: `#/scans/<id>/results`.
- `openScan(id)`: `navigate({name: "scan", scanId: id})`.

These are passed to Scans, ScanDetail, ScanResults and RunScan, and to HostDetail as `scanLinks`, so the host page now shows its scan history (REQ-283). Each screen mounts with `key` set to its id; RunScan's key is the profile id.

## Profile page

- Operators and admins see a "Run scan" link (`btn btn-primary`) to `#/scans/run/<policyId>`, with the profile preselected, when the profile is enabled and not deleted (#154 (c)).
- Viewers never see it.
- A disabled profile has no link, because `POST /scans` refuses it with 409.
- The admin status and delete actions are unchanged.

## Checks run (from `web/`)

- `npm run typecheck` and `npm run lint` pass.
- `prettier --check` passes on the four files.
- `npm run format:check` currently flags only `src/test/m11.ts`, the tester's in-progress file, not mine.
- No vitest run.
