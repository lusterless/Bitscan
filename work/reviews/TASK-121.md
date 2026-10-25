# TASK-121 REVIEW: enrolment approval screen

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed: `web/src/screens/EnrolmentRequests.tsx` (new, the only file; `work/reports/TASK-121-impl.md`). Sources: REQ-125, REQ-126, REQ-132, TS §3.2 L185, L192, §6.2 L1114–L1115, §6.3 L1141, #68.

TEST: PASS (tester-m5, 2026-10-25): 12/12. Plants red.

## Checks
1. **Spec (REQ-125).**
   - The list shows pending requests by default and decided ones through `state=decided`. Changing the filter resets paging.
   - Each request shows its hostname, source IP, OS (or "unknown"), kind, agent version and request time.
   - Every match is listed with its hostname, the reason it matched (machine-id, hostname or both), its machine-id and its status, under a warning that a cloned image shares the machine-id (TS §3.2 L192).
   - (3) Approve and reject each go through `Confirm` and call the route once, then re-read the list.
   - (4) A 409 shows "already decided" and refreshes the list.
   - (5) REQ-126 is met through `ProblemBanner`: a TOTP-session refusal offers only "Sign in again", and no field ever asks for a token.
2. **REQ-132.** Every API value is a text node or an `aria-label` value, and the `Confirm` messages are plain text props. A hostile hostname renders literally (REQ-125 (2)).
3. **Stale answers.** A list answer that arrives after the screen unmounts, or after a newer request, is ignored.
4. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
5. **Scope.** 1 file, 175 code lines.

## Findings
1. nit, `EnrolmentRequests.tsx:155`. A match's status is shown as the raw enum value (for example `awaiting_approval`), not through the `StatusBadge` labels. REQ-125 does not require labels, and the impl report defers them to TASK-122. Check it in TASK-122's review: use the label map here once it exists.
   - **Revision 1 (impl-web):** the match status now renders through `StatusBadge` (one import and one JSX line, `EnrolmentRequests.tsx:157`). The label map is a `Record` over the generated enum, so the type checker catches an unhandled status. I read the r1 code and it needs no change. r1 TEST PASS (tester-m5, 12/12, plants still red), so r1 is APPROVED.
