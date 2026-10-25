# TASK-126 TEST: app shell (routes, navigation by role, gating, sign-out)

Verdict: **PASS** (r0 and r1). Tests: web/src/app/App.test.tsx (25), from REQ-133 (1)-(3), REQ-120 (1)-(4), REQ-122 (1), (6), REQ-132 (1), TS §6.2 L1080/L1089/L1093-L1127 and #85 (a), (c). Command (L): `npx vitest run src/app/App.test.tsx`. The first run was 24/25: one test bug, re-run alone 4/4, then the file 25/25. Full web suite 345/345, plus build and G42 OK.

AC coverage:
- REQ-133 (1): CHK-M5-280; plant 434.
- REQ-133 (2): CHK-M5-281; plant 433.
- REQ-133 (3) and REQ-122 (1): CHK-M5-282; mutation row CHK-M5-349.
- REQ-122 (6): CHK-M5-283; plants 435, 436.
- REQ-120 (3), (4): CHK-M5-284; plants 437, 440.
- Reload, #85 (c): CHK-M5-285; plants 438, 439.
- REQ-120 (1): CHK-M5-286.
- REQ-132 (1): CHK-M5-287.
All plants red.

## Revision 1: PASS
The change is markup only (no nested <main>). App.test.tsx: 25/25. Full web suite: 345/345. Build and G42: OK. All 9 plants are red again on r1.
