# TASK-249 IMPL: Schedules screens

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W3 batch.
REQ: REQ-282, REQ-284. Open items: #122 (h), (i), #128, #154 (d). Spec: TS §4.4 L557, §6.2 L1126.
Uses TASK-256 (`TargetPicker`, `fromTarget`, `toTarget`, `describeTarget`).

## Files

- `web/src/screens/Schedules.tsx` (new): `Schedules()`, with no props.
- `web/src/screens/ScheduleForm.tsx` (new): `ScheduleForm({ schedule, policies, onSaved, onCancel })`.

Schedules has no route of its own for the form: the form opens inline. Role gating is TASK-251's: the screen mounts only for operators and admins, since every `/scan-schedules` route is operator (#122 (i)).

## Schedules

**Loads:**
- `GET /api/v1/policies?limit=500`, for the profile names and the create form's choices.
- `GET /api/v1/scan-schedules?limit=50` with the cursor (paged).

**Columns:**

| Column | Content |
| --- | --- |
| Name | name |
| Profile | the name, or "Profile <id>" if it is not in the list |
| Target | `describeTarget` |
| Cron | cron expression |
| Time zone | time zone |
| Enabled | yes / no |
| Last run | `formatTime`; null is "never" |
| Next run | `formatTime`; null is "never" |
| (actions) | Edit, Delete |

**Actions:**
- "New schedule" opens the create form; "Edit" opens the edit form for that row.
- "Delete" goes through `Confirm`, then `DELETE /api/v1/scan-schedules/{id}`. A 204 reloads the list; a refusal shows the banner.
- An empty list shows "No schedules.".

## ScheduleForm

**Fields:** Name (max 128), Profile, Target (`TargetPicker`), Cron (max 64), Time zone (default "UTC", max 64) and Enabled (default on).
- Profile can be enabled or disabled (#122 (h)). It is disabled when editing, since `policy_id` cannot change.

**Create.** `POST /api/v1/scan-schedules` with `{name, policy_id, target, cron, timezone, enabled}` (#122 (h)).

**Edit.** `PATCH /api/v1/scan-schedules/{id}` with **only the changed fields** among `name`, `target`, `cron`, `timezone` and `enabled`:
- The target counts as changed when the built target's JSON differs from the stored one.
- No change shows "Nothing has changed." and sends nothing.

**Checks before sending:**
- An invalid target shows the TASK-256 text.
- Create without a profile shows "Choose a profile.".
- Cron and time zone are checked by the server only (#128).

**Answers:**
- 201 or 200 → `onSaved()`: the form closes and the list reloads.
- 400 or 409 → `ProblemBanner` inside the form, with the fixed text plus the server's detail as text.
- Network error → "The manager is unavailable…".

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. No vitest run.
