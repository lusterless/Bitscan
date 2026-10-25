# TASK-123 REVIEW: host detail

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed: `web/src/screens/HostDetail.tsx` (new and the only file; `work/reports/TASK-123-impl.md`). Sources: REQ-128, REQ-132, TS §6.2 L1109–L1110, §7.3 L1225, §3.7 L484, #69.

TEST: PASS (tester-m5, 2026-10-25). The HostDetail tests pass 9/9, and all 6 plants are red.

## Checks
1. **Spec (REQ-128).**
   - Identity, status, enrolment time, last seen IP, and the token issue, expiry and revocation times are all shown. The token itself is never shown; the item has no token field.
   - Tags and runner helpers are shown.
   - Every `os_info` field is shown:
     - IP addresses as a list;
     - `raw` as indented JSON inside `<pre>`, as one text node, so a hostile key or value shows literally (3);
     - `collected_at`.
   - A null `os_info` shows "No inventory yet.", and a null `last_snapshot` shows no change list (1).
   - "Added / removed since last snapshot" shows the snapshot time, the package count, and the added and removed lines in the order the API gives (2).
   - A 404 shows "Host not found." (4).
   - The packages list is paged with the returned cursors (5).
2. **REQ-132.** Every value is a text node. There is no raw-HTML insertion, `style=`, `fetch` or storage.
3. **Stale answers.** Both requests ignore an answer that arrives after a newer request or after the screen unmounts.
4. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
5. **Scope.** 1 file, 238 lines, over the 190 estimate. The excess is the field rows and table JSX, and I accept it for UI.

## Findings
1. Carry-over to the TASK-126 review, not a finding against this task: the impl report asks for `<HostDetail key={agentId} …/>`, so that a different host starts on its first package page with a fresh detail state. I will check this in the App shell (TASK-126).
