# TASK-118 TEST: sign-in screen

Verdict: **PASS**. Tests: web/src/screens/SignIn.test.tsx (24), from REQ-121, TS §6.2 L1080/L1086-L1089, §6.3 L1136, #48, #85 (a), (e). Command (L): `npx vitest run src/screens/SignIn.test.tsx`: 24/24 passed, 0 failed, 0 skipped.

For the user's second look: the password and the TOTP code are emptied on every attempt, before the request is sent, so they are already empty while it is in flight. The bsu_ token goes only to the session store: the next request carries it, it never appears in the DOM, and the secret watch (Web Storage, cookie, IndexedDB, console, history, URL) never sees the password or the token.

AC: (1) CHK-M5-200 + plant 377; (2) CHK-M5-201 + plant 378; (3) CHK-M5-202 + plant 379; (4) CHK-M5-203 + plants 380, 381; (5) CHK-M5-204 + plant 383; storage and console CHK-M5-205 + plant 382. All plants red.
