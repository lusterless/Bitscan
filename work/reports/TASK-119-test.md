# TASK-119 TEST: TOTP enrolment and replacement, offer, password change

Verdict: **PASS**. Tests: web/src/screens/Account.test.tsx (24), from REQ-122, REQ-123, TS §6.2 L1085-L1089/L1097, #53 (a), #85 (a) and the lead's REQ-122 (3) reading (2026-10-25). Command (L): `npx vitest run src/screens/Account.test.tsx`: 24/24 passed, 0 failed, 0 skipped.

For the user's second look:
- The TOTP secret and URI appear only as two <code> texts and the SVG path while the confirm step is shown.
- They are gone from the DOM after a successful confirm, after a 403 or 409 to the confirm, and after unmount. The svg element goes with them.
- The secret watch never sees the secret, the passwords, or the old or new token.
- The confirm answer replaces the token in memory, and the next request carries the new one.
- Every password field is cleared before sending. A local check failure sends nothing.

AC coverage:
- REQ-122 (2): CHK-M5-210, -211; plants 386, 387.
- REQ-122 (3): CHK-M5-212; plant 385.
- REQ-122 (4): CHK-M5-213; plant 384.
- REQ-122 (5): CHK-M5-214; plant 348.
- Offer, "Not now": CHK-M5-215.
- REQ-123 (1)-(3): CHK-M5-216; plants 388-391.
REQ-122 (1) and (6) are the App shell's (TASK-126, CHK-M5-282/283). All plants red.
