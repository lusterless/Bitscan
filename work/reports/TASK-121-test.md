# TASK-121 TEST: enrolment approval screen

Verdict: **PASS** (r0 and r1). Tests: web/src/screens/EnrolmentRequests.test.tsx (12), from REQ-125 (1)-(4), REQ-126, REQ-132, TS §3.2 L185/L192, §6.2 L1114-L1115. Command (L): `npx vitest run src/screens/EnrolmentRequests.test.tsx`: 12/12 passed, 0 failed, 0 skipped. AC: (1) fields and every match CHK-M5-230, -231 + plants 401, 403; (2) plain text CHK-M5-232; (3) one decision after confirmation, item leaves pending CHK-M5-233 + plants 399, 400, 402; (4) 409 and the REQ-126 refusals CHK-M5-234 + plant 404. All plants red. Note for review: match statuses were shown as the raw enum value, not the StatusBadge labels of TASK-122; REQ-125 does not ask for labels.

## Revision 1: PASS
The match status is rendered through StatusBadge (reviewer nit and tester observation). Test change: CHK-M5-231's expected match lines now end "status Online" / "status Decommissioned". `npx vitest run src/screens/EnrolmentRequests.test.tsx`: 12/12 passed. Plants CHK-M5-399..404 re-run on r1: all red.
