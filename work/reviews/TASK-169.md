# TASK-169 REVIEW: Profiles list screen

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-181 (list half); PD-34; #9, #98 (a); TS §4.3, §6.2, §6.3. Low risk; one round.

Scope: frozen worktree `81d81e9`, `web/src/screens/Profiles.tsx` (new, 180 lines; the estimate was 120). The extra is Prettier layout, and it stays within the ~200 limit.

TEST: PASS (`work/reports/TASK-169-test.md`; together with TASK-168, 19/19 plants red). My re-run: lint, typecheck and format are clean, and vitest gives 401/401 (see TASK-168.md).

## Checks
1. **Plain text (TS §6.3; security invariants "Render all stored text as plain text").**
   - Every API value is a JSX text child.
   - There is no `dangerouslySetInnerHTML`, `innerHTML` or Markdown (grep: 0).
   - The hostile `<script>`, `<img onerror>` and `<b>` values render literally (tested; the `dangerouslySetInnerHTML` plant is red).
2. **The filter never sends `deleted` (#9).**
   - The options are `all`, `enabled` and `disabled`. `toFilter` maps any other value, including a forged `deleted`, to `all`, which sends no `status`.
   - The query type is the generated `policy_status` enum, so `deleted` cannot be typed in.
   - A change of filter resets paging. Tests and a plant cover it.
3. **Paging (REQ-181 (4)).**
   - It follows the Hosts pattern (`useCursorPages`, `Pager`, `limit=50`), and sends `cursor` only after page 1.
   - A stale answer is dropped through the `active` flag.
4. **Roles and API.**
   - There is one `GET /api/v1/policies` call through the generated client, with no role gating, as TS §6.2 says (every role).
   - Problems go to `ProblemBanner`, and a network failure gets the fixed callout.
   - The status labels are a `Record` over the generated enum.
5. **Scope.** No routes or navigation are touched; TASK-173 wires them through the `onOpen` prop.

## Findings
None blocking or should-fix.

1. nit, `Profiles.tsx:98-101`: after the filter changes, the previous filter's rows stay on screen until the new page arrives. Clearing `page` when the filter changes would show "Loading." instead. This is cosmetic.
