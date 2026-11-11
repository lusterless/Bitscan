# W3 web batch REVIEW: TASK-246, 247, 248, 249, 250, 256, and TASK-251

Reviewer: reviewer-m11, 2026-11-08. Round 1. Low risk; one review round for the batch (PD-47). This file is the review for every task listed. TASK-247.md through TASK-251.md and TASK-256.md each point here.

Verdict: APPROVED (all seven tasks)

## Scope reviewed

| Task | Files |
| --- | --- |
| TASK-246 | `web/src/screens/Scans.tsx`, `web/src/screens/RunScan.tsx` |
| TASK-247 | `web/src/screens/ScanDetail.tsx` |
| TASK-248 | `web/src/screens/ScanResults.tsx` |
| TASK-249 | `web/src/screens/Schedules.tsx`, `web/src/screens/ScheduleForm.tsx` |
| TASK-250 | `web/src/screens/HostScans.tsx`, `web/src/screens/HostDetail.tsx` (+8/−1) |
| TASK-256 | `web/src/components/ScanTable.tsx`, `web/src/components/TargetPicker.tsx` |
| TASK-251 | `web/src/app/router.ts`, `web/src/app/routes.tsx`, `web/src/components/Icon.tsx`, `web/src/screens/ProfileDetail.tsx` |

**Checked against:**
- TS §4.4 L557–L585, §4.5 L603–L604, §6.2 L1083, L1086, L1113, L1120–L1126, §6.3 L1137, L1142–L1144, §8.2 L1268.
- REQ-279 to REQ-284; #149, #154.
- `.claude/rules/web-ui.md`.
- Decisions 2026-11-08 (TASK-256 split; REQ-280's 503 without a sign-in button).

**Reports:** `work/reports/TASK-{246,247,248,249,250,251,256}-impl.md` and `-test.md` (PASS: full web suite 741/741, G12 to G14 green, G16 no diff, all plants red).

## Checks

**Plain text (TS §6.3, REQ-284):**
- No `dangerouslySetInnerHTML`, `innerHTML`, Markdown renderer or `fetch(` appears in any batch file.
- Every API value is a React text node. stdout and stderr go in `<pre>` text.
- The `<script>` and `onerror` plants are red across the detail, table, picker and results screens.

**Generated client only, session in memory:**
- Every call is `api.GET/POST/PATCH/DELETE` on generated paths.
- There is no `localStorage`, `sessionStorage` or cookie.
- The CSV export uses TASK-239's `downloadResultsCsv`.

**Output only when present (TS §6.2 L1123, web-ui.md):**
- `ScanResults` shows the Output column only when an item has the `stdout` key, by checking `"stdout" in item`.
- Viewer items carry no such key, as TASK-233 and TASK-241 guarantee.

**Both verdicts (web-ui.md):** `ResultBadge` is given `reevaluated = reevaluated_at !== null`. The original detail is shown as "Original: …".

**TOTP-session action (security invariant, web-ui.md):**
- Re-evaluate is offered to admins only.
- A 403 `totp_session_required` refusal goes through M5's `ProblemBanner`, which offers "Sign in again" (sign out, then password and code). It never offers an API-token field.
- A 503 `audit_sink_unavailable` refusal shows its own fixed message with no sign-in button. This follows the lead's 2026-11-08 reading of REQ-126: signing in can't fix a sink outage.
- Neither refusal sends another request: `act` reloads only after a success.

**Role gating:**
- `ROUTE_ROLES` gives `run-scan` and `schedules` operator and admin only. These are TS §6.2 operator routes (#122 (i)).
- `RouteView` renders "Not available" for a disallowed route, and `navFor` filters the nav.
- On the scan detail, a viewer gets neither button, an operator gets Cancel only, and an admin gets both. The Profile page shows Run scan to operators and admins for an enabled profile.

**Cancel only while unfinished (lead's point a):**
- M9 sets `scan.finished_at` only when no unit is open (`scan_state.derive`, `scan_progress.set_scan_state`).
- On a finished scan, `POST /scans/{id}/cancel` answers 200 with `cancelled_jobs: 0` (`services/jobs/cancel.py`, idempotent).
- So hiding Cancel once `finished_at` is set hides only a no-op. The server stays authoritative.

**Error count beside the score (lead's point b):** REQ-280 asks for "the score … with the error count beside it" (TS §4.5 L604, #149). `Score` renders the count beside the score, so a separate Errors column is not required.

**Run scan (#154):**
- One `crypto.randomUUID()` `Idempotency-Key` per submission. It is kept only across a network-error retry and cleared on any answer or form edit.
- An in-flight ref blocks a second submit, so a double click sends one request.
- After 202 the new scan opens.

**Router:**
- Scan ids are validated as UUIDs and lower-cased. Policy ids must be 1–20 digits.
- A malformed hash falls back to the host list.
- Hrefs are built only through `formatHash` from validated ids.

**Scope:**
- TASK-246's growth was moved into TASK-256 under the plan's rule (decision 2026-11-08).
- `HostDetail.tsx` is touched only by TASK-250 (+8/−1, optional `scanLinks`). `ProfileDetail.tsx` is touched only by TASK-251.
- `package.json`, `package-lock.json` and `schema.d.ts` are unchanged (no dependency; the client is as committed in TASK-239).

**Re-run (Windows):**
- The 12 batch test files pass: 358 tests, including the HostDetail, ProfileDetail, router and App suites.
- `npm run lint`, `npm run typecheck` and `prettier --check src` all exit 0.

## Findings

1. **nit, `web/src/components/TargetPicker.tsx:82–89` with `web/src/screens/ScheduleForm.tsx` (the `!same(body, schedule.target)` line in `save`).**
   - **Problem:** `fromTarget` maps any stored target it does not recognise to "All hosts". Editing another field of such a schedule then sends `target: {all: true}`, which widens the schedule to every host. That is the fail-open direction.
   - **Why only a nit:** with real data this can't happen. The server validates every schedule target on write (#122 (h)), and `{"all": true}` itself maps correctly. The picker also visibly shows "All hosts" before saving. Operators may scan all hosts anyway, so no security invariant is broken.
   - **Suggested fix, cheap, for a later web round:** give `fromTarget` an "unknown" kind that `describeTarget` already names ("Unknown target"). Never send `target` for it unless the user picks one, or block saving with a fixed note.
2. **nit, `web/src/screens/RunScan.tsx:39–41`:** the profile list is one `GET /policies?status=enabled&limit=500` with no paging. A fleet with more than 500 enabled profiles could not choose the rest.
3. **nit, `web/src/app/router.ts` `isPolicyId`:** `#/scans/run/007` is accepted, but `"007"` never equals `String(policy_id)` (`"7"`), so the profile is not preselected. The user picks it, which is harmless. Normalising with `String(Number(id))` would preselect it.
