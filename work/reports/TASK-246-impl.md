# TASK-246 IMPL: Scans screen and Run scan form

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W3 batch.
REQ: REQ-279, REQ-284. Open items: #154 (a)–(c), #123, #122 (a), (f). Spec: TS §4.4 L555–L558, §6.2 L1120–L1121, §6.3 L1135, §6.4.
Uses TASK-256 (`ScanTable`, `TargetPicker`) and TASK-239 (client). See `work/reports/TASK-256-impl.md` for the `ScanLinks` prop TASK-251 builds.

## Files

- `web/src/screens/Scans.tsx` (new): `Scans({ role, links })`.
- `web/src/screens/RunScan.tsx` (new): `RunScan({ policyId, links })`.

## Scans

**Profile choices.** On mount the screen sends `GET /api/v1/policies?limit=500`, used only for the Profile filter's choices. If it fails, the filter offers just "All".

**List.** `GET /api/v1/scans` with `limit=50`, plus `cursor` from `useCursorPages` and the applied filters only.

**Filters** (form "Filter scans", button "Apply"):

| Field | Query parameter | What is sent |
| --- | --- | --- |
| Profile (select) | `policy_id` | an integer |
| Host id (text) | `agent_id` | must be a hyphenated UUID (`isUuid`); trimmed and lower-cased |
| State (select of the six states) | `state` | the state name |
| Created on or after (UTC) (date) | `created_after` | `YYYY-MM-DDT00:00:00Z` |
| Created before (UTC) (date) | `created_before` | `YYYY-MM-DDT00:00:00Z`, exclusive |

- Empty fields are not sent.
- A malformed host id or date shows "The host id must be a UUID and the dates must be valid." and sends nothing.
- Applying the filters resets paging to page 1.

**Paging.** Previous and Next through `Pager`. Previous re-requests the earlier cursor.

**Run scan link.** Operators and admins see a "Run scan" link (`links.runScanHref`); viewers don't.

**States.** "Loading.", "No scans.", the problem banner, and "The manager is unavailable…" on a network failure.

## Run scan (#154)

**Profiles.** `GET /api/v1/policies?status=enabled&limit=500`. `policyId` (from a profile's page, TASK-251) preselects the profile.

**Target.** `TargetPicker` (TASK-256).

**Submit.** Sends `POST /api/v1/scans` with body `{policy_id: <integer>, target}` and header `Idempotency-Key`.

**The key (#154 (b)):**
- It is `crypto.randomUUID()`, made at the first send of a submission.
- After a network error (no answer) it is kept, so pressing Run scan again resends the same key.
- Any answer (202 or a refusal) clears it, so the next submission gets a new key.
- Changing the profile or the target also clears it.

**Double click.** An in-flight ref plus `disabled={busy}`, so a double click sends one request.

**Answers:**
- 202 → `links.openScan(scan_id)` (#154 (c)).
- A refusal → `ProblemBanner`: the fixed text, then the server `detail` as text. For example, 409 "The policy is disabled." and 422's detail.
- Network error → "The manager could not be reached. Submit again to retry.".

**Checked before anything is sent:**
- No profile chosen, or the chosen one isn't enabled → "Choose an enabled profile.".
- An invalid target → the TASK-256 text.

**Role.** Role gating is TASK-251's: RunScan mounts only for operators and admins.

All values are text nodes; there is no HTML sink.

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. No vitest run.
