# TASK-208 IMPL: README, scans and schedules

Implementer: impl-manager-m9b, 2026-10-30. REQ-233. Spec: TS §4.4, §6.2 L1119, L1122, L1124, §6.4, §8.4 L1288, L1290. Low risk (docs). Written after TASK-205 and TASK-206.

## Files

- `README.md`: +78 / −4 lines. No other file changed.

## What changed

| Place | Change |
| --- | --- |
| Intro, "The manager runs" | adds `/api/v1/scans`, `/api/v1/scan-schedules` and scheduled scans to the scheduler |
| `## API` | bullets for Scans and Scan schedules (operator, session or API token) linking the new sections; metrics list adds `bitscan_plugin_results_total{result}` and the ERROR-rate expression (#129 (c)) |
| New `## Scans` (before `## Users`) | `POST /scans` with a `curl` example (`Idempotency-Key` header); the three target forms and limits (#122 (b)); resolution at queue time (offline hosts included, unknown ids dropped, recorded version); the 202 body; refusals 400/404/409/422/413 (#122 (f), #3, #125 (h)); one job per host and profile (#125 (e)); commands fixed at queue time, disable blocks new scans only (#18); `Idempotency-Key` rules (#123); the all-hosts API-token alert and `scan.create`; cancel (`{scan_id, state, cancelled_jobs}`, idempotent, results of cancelled jobs refused); job states, deadline formula, 24 h never-started, single retry (#126), 7-day late results, first result wins; scan states and the up-to-a-minute lag (#127 (d), (f)); results views not in this version |
| New `### Schedules` | CRUD with a `curl` example; item shape; PATCH subset, `policy_id` fixed; deleted vs disabled profile (#122 (h)); cron syntax (five fields, Sunday 0 or 7, both day fields refused, no `@`, never-firing refused; #128 (a), (c)); IANA time zones (#128 (b)); `next_run_at` / `last_run_at` (#128 (d)); audit entries; 30 s tick, no back-fill after 2 minutes, the skip rules and the logged words (#128 (e), (f)); the every-minute schedule caveat (plan TASK-203 §6) |
| `## Agent API` | the results row now describes `{accepted, duplicates}`; new "Compliance jobs and results" bullets: pull of both kinds, start notice, accepting states and the 7-day window, the 409 cases (whole batch for a foreign check), the flood alert and the cancelled-job exclusion (#124 (f)), oversize stored empty (65,536 / 16,384 UTF-8 bytes, #116 (d)), U+0000 and lone surrogates stored as U+FFFD (#121) |
| `## Scheduler` | three jobs; `offline_sweep` gains the compliance deadline, never-started and retry steps and the scan state refresh; the 30 s scan-schedule tick |

DST behaviour is deliberately not described: #128 (b) is "to confirm in test" (decisions 2026-10-30), so the README states only that the cron is read in the schedule's zone.

## Checks

- No token, password, internal id or process note: the examples use `<token>` and a placeholder key; no milestone, task or team wording.
- Every `#scans` / `#schedules` link matches a heading.

## For the tester (tester-m9)

Follow `## Scans`, `### Schedules` and the new Agent API bullets against a WSL manager with a simulated agent. Points that depend on other tasks: the all-hosts API-token alert needs TASK-198's alert-kind registration; scan state updates need TASK-202's sweep steps.

## Revision 1 (2026-10-30, lead's request and reviewer-m9's should-fix in work/reviews/TASK-208.md)

Two README lines changed (`README.md` only):
- `### Schedules`, `timezone` bullet: one sentence on daylight-saving changes, as the user decided (decisions 2026-10-30, "DST behaviour for scheduled scans", TASK-191 r1). A run whose local time is skipped in spring runs just after the jump. A run in the hour repeated in autumn runs once, at its first occurrence, so a schedule firing more often than hourly makes no runs during the repeated hour. This replaces the earlier note that DST was left out until #128 (b) was confirmed.
- `**How a scan proceeds.**`, deadline bullet: a job past its deadline ends `partial` or `failed`, or `completed` if every check already has a result (#127 (b)). Only a `partial` or `failed` one gets the single retry.

For tester-m9: re-run the README walk rows for the `timezone` bullet and the deadline bullet.
