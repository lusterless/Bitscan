# TASK-122 REVIEW: regenerated client (status enums) and the host list

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-122-impl.md`):
- `web/src/api/schema.d.ts` (regenerated);
- `web/src/components/StatusBadge.tsx` (new);
- `web/src/screens/Hosts.tsx` (new).

Sources: REQ-117, REQ-127, REQ-132, REQ-136, TS §6.2 L1108, §6.3 L1134, #68.

TEST: PASS (tester-m5, 2026-10-25).
- The Hosts tests pass 10/10.
- G16: regenerating the client gives no diff.
- Plant CHK-M5-242 (a status label removed) is red at typecheck.
- Plant CHK-M5-345 is red in both lint and test.

## Checks
1. **Regeneration.** `schema.d.ts` matches the current `manager/openapi.json`, which already includes TASK-108's enums and TASK-113/114's package routes. `UserPathsArePrefixed` still holds.
2. **StatusBadge.** The label map is a `Record` over the generated six-value status, so a missing label or a new enum value fails `npm run typecheck` (REQ-127 (2)).
3. **Hosts (REQ-127).**
   - Every column REQ-127 lists is shown. A missing time shows "never", and empty tags or helpers show "none".
   - Paging uses the returned cursors.
   - A row links to `#/hosts/<id>`. The `href` always starts with `#`, so it cannot become a `javascript:` URL.
   - Every value is a text node (REQ-132).
   - An answer that arrives after a newer request, or after the screen unmounts, is ignored.
4. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
5. **Scope.** 2 hand-written files, about 116 lines, plus the generated file.

## Findings
None. My TASK-121 nit (show match status through the labels) was closed in TASK-121 r1.
