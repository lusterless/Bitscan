# TASK-116 REVIEW: web session core, problem messages, hash router

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). **The user's second look applies (PD-30 (2)), because this task holds the `bsu_` token.**

Scope reviewed: `web/src/app/session.ts`, `web/src/app/problems.ts` and `web/src/app/router.ts`, all new (`work/reports/TASK-116-impl.md`). Sources:
- REQ-120, REQ-126;
- TS §6.2 L1080 and L1084, §6.3, §8.1;
- `.claude/rules/web-ui.md`;
- #85 (a), (b), (c); PD-28 (d); PD-29;
- decisions 2026-10-25 (TASK-116 stays one task at 285 lines).

TEST: PASS (tester-m5, 2026-10-25, 141 tests).
- The token is never found in storage, a cookie, IndexedDB, the console, history or the URL.
- The 401 rule holds, including the older-token case.
- `signOut` clears the session on every answer, and a reload starts signed out.
- Plants CHK-M5-342, -343, -344, -347 and -354, and 4 extras, are red.

## Where the token lives, and when it is cleared (for the user's second look)
- **Where.** The token lives in one variable in the browser tab's memory: `current` in `session.ts:28`.
  - It is never stored in the browser (local or session storage, cookies or IndexedDB). It never goes into the address bar, the console or React state.
  - Screens can read only a frozen view: role, TOTP flags and expiry, with no token in it.
  - Nothing exports the token.
- **Sent.** One request hook adds `Authorization: Bearer …` to every call made through the generated API client, and only while someone is signed in.
- **Replaced.** A new sign-in or the TOTP confirm replaces the old token outright.
- **Cleared:**
  1. on any 401 to a request that carried the *current* token. A late 401 for an older token cannot end the newer session;
  2. on sign-out, which clears the session in `finally`, even when the logout call fails or is refused;
  3. on a page reload or a closed tab, because nothing restores it;
  4. JavaScript cannot wipe a string from memory. "Cleared" means the last reference is dropped.

## Checks
1. Spec:
   - REQ-120 (1)–(4) are met by the design above. There is no API-token path anywhere.
   - #85 (a): `nextScreen` sends an admin without TOTP to `totp-required` and offers TOTP to others.
   - PD-29: an unknown role string becomes `viewer`.
2. REQ-126:
   - `messageFor` maps `totp_session_required` to "sign in again with your password and code", never an API token (#85 (b)).
   - It maps `audit_sink_unavailable` to the paused message, `forbidden` to the role message, and `totp_enrolment_required` to the TOTP screen.
   - Unknown types get a generic message with the status.
   - Every message is fixed text. `detail` is returned separately, for display as a text node only.
   - `Retry-After` counts only as 1–9 ASCII digits.
3. Router:
   - The hash routes match the plan.
   - The UUID check uses no regular expression.
   - Anything malformed falls back to the host list.
   - `formatHash` has an exhaustive switch.
   - Only route names and host ids enter the URL.
4. Security: there is no `console`, storage, `innerHTML` or raw `fetch` in these files. The G12 lint rules apply to them.
5. Re-run by the reviewer (Windows): `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
6. Scope: 3 files, 285 lines, over the ~200 guide. Most of the size is Prettier layout, and the lead accepted it as one task (decisions 2026-10-25).

## Findings
1. nit, `session.ts:107-126`. The bearer header covers only calls made through `api`. A later screen that downloads a file with its own `fetch` (the CSV, `app/download.ts`) must add the header and the 401 rule itself, or call through `api`. I will check this in that screen's review (TASK-124/125). There is no change for TASK-116.
