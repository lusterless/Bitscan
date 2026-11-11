# TASK-249 TEST: Schedules screens (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-249-impl.md`). Shared batch evidence is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-282 (1), (2) here. REQ-282 (3), the viewer gating, is TASK-251's and passes there ([TASK-251-test.md](TASK-251-test.md)). Spec: TS §4.4 L557, §6.2 L1126; #122 (h), (i), #128, #154 (d).

## Tests

`web/src/screens/Schedules.test.tsx` (new): **17/17**.

## Acceptance criteria

**List: PASS.**
- One GET with `limit=50` and the bearer.
- Each row shows name, profile name (or "Profile <id>" when it isn't in the list), target described, cron, time zone, yes/no, last run and next run (`formatTime`, null as its "never" text).
- The empty state and the refusal banner both appear.

**REQ-282 (1), create: CHK-M11-269 PASS.**
- POST sends exactly `{name, policy_id, target, cron, timezone: "UTC", enabled: true}`, with defaults pre-filled and a tags target. Then the form closes and the list reloads.
- A disabled profile is offered and accepted (#122 (h)), because the profiles call has no status filter.
- No profile, or a bad tag, is refused before sending. Cancel sends nothing.

**REQ-282 (1), edit: PASS.**
- An edit sends only the changed fields: `{cron}` only; `{name, enabled}` only; `{timezone}` only, with the stored chosen-hosts target loaded into the picker and not resent; `{target}` only.
- No change shows "Nothing has changed." and sends nothing. The profile select is disabled, because `policy_id` cannot change.

**REQ-282 (1), delete: PASS.** There is no DELETE before Confirm, and Cancel in the question sends nothing. Confirm sends `DELETE /api/v1/scan-schedules/3`, then reloads, and the row is gone. A refused delete shows the banner and keeps the row.

**REQ-282 (2): PASS.** A 400 on create keeps the form open with "Request failed (status 400)." and the detail, and sends no reload. A 409 on edit shows "The policy is deleted.".

**CHK-M11-272: PASS.** A `<script>` schedule name and an `onerror` tag render as text, including in the delete question.

## Plants (red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-435 | an edit always sends `cron` | 4 changed-fields rows |

## Note (not a finding)

`fromTarget` reads an unrecognised stored target as "All hosts". Editing such a schedule would then send `target: {all: true}`. The server validates every stored target (#122 (b)), so this cannot arise from API data; recorded for the reviewer.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-269 (screen half) | `npx vitest run src/screens/Schedules.test.tsx` | PASS | 17/17 |
| CHK-M11-272 (schedules) | the same | PASS | plain-text row green |
| CHK-M11-435 | plant | PASS (red as required) | 4 failed / 17 |
