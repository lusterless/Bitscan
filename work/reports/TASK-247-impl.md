# TASK-247 IMPL: Scan detail screen

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W3 batch.
REQ: REQ-280, REQ-284. Open items: #149, #145 (b), #147, #122 (g). Spec: TS §4.4 L581–L585, §4.5 L603–L604, §6.2 L1086, L1122, L1124–L1125.
Uses TASK-239 (`Score`) and TASK-256 (`ScanStateBadge`, `ScanLinks`, `describeTarget`).

## File

`web/src/screens/ScanDetail.tsx` (new): `ScanDetail({ scanId, role, links })`. Mount it with `key={scanId}`.

## Behaviour

**Load.** `GET /api/v1/scans/{id}`. A 404 shows "Scan not found."; any other refusal shows the banner; a network failure shows "The manager is unavailable…".

**Header:**
- The profile name with the state badge (`scan.state` as returned, never re-derived).
- "Scan <id> · created <time>".
- A "Results" link (`links.resultsHref`) and a "Back to scans" link (`links.scansHref`).

**Scan fields:** Profile, Profile version, Trigger, Schedule (id or "none"), Requested by (user id or "system"), Target (`describeTarget`, as requested), Hosts targeted (`resolved_count`), Created, and Finished ("not finished" while null).

**Hosts table**, one row per `hosts[]` entry in API order:

| Column | Content |
| --- | --- |
| Host | the hostname, linked to the existing host route |
| Jobs | the job states; the retry is written "retry <state>" |
| Passed | count |
| Failed | count |
| Not run | count |
| Score | `<Score score errors>`: "75.0 %" or "n/a", with "N errors" beside it |

- There is no separate Errors column: the count is beside the score (TS §4.5 L604, #149).
- No hosts shows "No host has a job in this scan.".

**Buttons**, each behind `Confirm`:
- **Cancel scan**: operators and admins only, and only while `finished_at` is null. A finished scan has no queued or running job to cancel (TS §4.4 L582, §6.2 L1124).
  - 200 shows "Scan cancelled: N jobs cancelled." and reloads.
- **Re-evaluate**: admins only. Sends `POST /api/v1/scans/{id}/reevaluate` with no body.
  - 200 shows "Re-evaluated against version V: N verdicts added." (`rows_added`) and reloads the summary.
- A viewer sees neither button.

**Refusals:**
- They show `ProblemBanner` and **send no other request**: there is no reload after a refusal.
- 403 `totp_session_required` shows the fixed text and the "Sign in again" button, which signs out. There is never an API-token field or fallback.
- 503 `audit_sink_unavailable` shows its fixed text. Its action is null in M5's `messageFor`, so it has no sign-in button.
- 409 `conflict` (deleted policy) shows the detail "The policy is deleted.".
- 404 shows "Scan not found.".

**Calls.** Only through the generated client; no `fetch`. All values are text nodes.

**TOTP.** The UI does not check `totpVerified` itself. An admin's session is TOTP-verified at sign-in (admins must have TOTP), and the server's 403 is the authority.

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. No vitest run.
