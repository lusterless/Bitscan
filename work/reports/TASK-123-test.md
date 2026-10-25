# TASK-123 TEST: host detail

Verdict: **PASS**. Tests: web/src/screens/HostDetail.test.tsx (9), from REQ-128 (1)-(5), REQ-132, TS §6.2 L1109-L1110, §7.3 L1225. Command (L): `npx vitest run src/screens/HostDetail.test.tsx` 9/9 passed, 0 failed, 0 skipped. AC:
- (1) every field, no token: CHK-M5-250; plant 413.
- No inventory or snapshot: CHK-M5-251; plant 414.
- (2) added and removed lists: CHK-M5-252; plant 411.
- (3) raw as indented text, hostile text: CHK-M5-253; plant 409.
- (4) 404 "Host not found": CHK-M5-254; plant 410.
- (5) package paging and columns: CHK-M5-255; plant 412.
All plants red.
