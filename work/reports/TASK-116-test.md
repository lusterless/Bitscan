# TASK-116 TEST: web session core, problem messages, hash router

Verdict: **PASS**. Tests: web/src/app/session.test.ts (36), problems.test.ts (46), router.test.ts (59), with the test double web/src/test/harness.ts; written from TS §6.2 L1076/L1080/L1089, §8.1, REQ-120, REQ-126, #85 (a)-(c), PD-29 and the plan TASK-116 tables before the code was read.

For the user's second look: the token is checked to reach no Web Storage call, cookie, IndexedDB, console method, history entry or URL across sign-in, swap, requests, a 401 and sign-out; the view screens read has no token; a 401 for the current token clears it, one for an older token does not; sign-out clears on any logout answer; a reload starts signed out.

Commands (L, from web/): `npx vitest run src/app/session.test.ts src/app/problems.test.ts src/app/router.test.ts`: first run 137/141 passed, 4 failed (test bugs: Retry-After cases the Fetch Headers object cannot carry as written), 0 skipped; re-run of problems.test.ts 46/46; full `npm test` 154/154; lint, typecheck and format clean.

AC coverage: REQ-120 (1) CHK-M5-183 + plant 342; (2) CHK-M5-180 + plant 343; (3) CHK-M5-181 + plants 344, 354; (4) CHK-M5-182 + plant 365; reload CHK-M5-183; REQ-126 (1) messages CHK-M5-185 + plant 347; toProblem CHK-M5-186 + plant 368; REQ-133 next screen CHK-M5-184 + plant 366; routes CHK-M5-187 + plant 367. All plants red, control green.
