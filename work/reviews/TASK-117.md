# TASK-117 REVIEW: shared display components

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-117-impl.md`), all new files:
- `web/src/components/Pager.tsx`
- `web/src/components/ProblemBanner.tsx`
- `web/src/components/Confirm.tsx`
- `web/src/format.ts`

Sources: REQ-126, REQ-127 (1) and (4), REQ-132, TS §6.3, #85 (b), `.claude/rules/web-ui.md`.

TEST: PASS (tester-m5, 2026-10-25). 29/29 tests pass, and all of the task's plants are red, including CHK-M5-348.

## Checks
1. **Pager.** The cursor stack gives back and forward over the opaque `next_cursor` (TS §6.3) with no client-built cursor. Next is disabled on the last page and Previous on the first, and `reset` is available for when the filters change.
2. **ProblemBanner.** It shows the fixed `messageFor()` text, then `detail` as a separate text node. The only actions are "Sign in again" (`signOut()`) and a hash link to TOTP set-up. Nothing asks for an API token (#85 (b), CHK-M5-347).
3. **Confirm.** The first click only opens an inline `alertdialog`. `onConfirm` runs once, on the confirm button only, and Cancel calls nothing. There is no `window.confirm`.
4. **formatTime.** `null` shows as "never" (REQ-127 (4)). A value that does not parse is shown as text, unchanged.
5. **Security (REQ-132).** No `dangerouslySetInnerHTML`, `innerHTML`, `style=`, `fetch`, storage or `console`.
6. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
7. **Scope.** 4 files, about 170 lines.

## Findings
1. nit (for main), `format.ts`. Times are shown in UTC (`YYYY-MM-DD HH:MM:SS UTC`), not in the browser's time zone. The spec is silent on how times are displayed. UTC matches the API and the audit log, so I accept it. main may want the user to confirm it at the M5 walk-through. No change.
