# TASK-125 REVIEW: package name type-ahead and CSV download

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-125-impl.md`):
- `web/src/components/TypeAhead.tsx` (new)
- `web/src/app/download.ts` (new)
- the type-ahead and Export CSV additions to `web/src/screens/PackageSearch.tsx`

Sources: REQ-130 (per #32 as approved), REQ-131, TS §7.3 L1223–L1224, §6.3 L1142, #84.

TEST: PASS (tester-m5, 2026-10-25).
- 15/15 tests, plus 3 screen export tests.
- The plants are red, including CHK-M5-351 (a plain link instead of a call through the client).

## Checks
1. **Type-ahead (REQ-130).**
   - Nothing is sent below 3 code points.
   - At 3 or more, one `q=…&group_by=package&limit=500` request is sent 300 ms after the last keystroke. Each change resets the timer.
   - At most 10 distinct names are shown, in response order.
   - A ticket counter drops a slower, older answer. A refusal clears the suggestions and shows nothing.
   - Choosing a name sets `name` and clears `q`.
2. **CSV (REQ-131).**
   - The download goes through the generated client (`parseAs: "blob"`), so the bearer header and the 401 rule apply. That also settles my TASK-116 nit.
   - The Blob is saved unchanged; the server already escaped it (TS §6.3).
   - The object URL is revoked on the next task.
   - The CSV query is the query on screen, with no `limit` or `cursor`.
   - A 400, such as the #84 cap, shows its `detail`.
3. **Security.**
   - No raw `fetch`; the G12 plant on `download.ts` is red.
   - No storage and no raw-HTML insertion.
   - The temporary `<a>` gets only an object URL and a fixed file name.
4. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
5. **Scope.** 2 new files of about 118 lines, plus about 40 lines in the screen.

## Findings
None.
