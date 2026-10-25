# TASK-126 REVIEW: app shell (routes, navigation by role, gating, sign-out)

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-126-impl.md`): `web/src/main.tsx`, `web/src/app/App.tsx` (new) and `web/src/app/routes.tsx` (new). Sources: REQ-133, REQ-120, REQ-122 (1), TS §6.2 L1089 and L1093–L1127, #85 (a) and (c).

TEST: PASS (tester-m5, 2026-10-25).
- App tests: 25/25. One test bug was fixed and re-run on its own, 4/4.
- 9 plants are red, including CHK-M5-349 (the admin TOTP gate).
- The web suite passes 345/345, and the build passes G42.

## Checks
1. **REQ-133 (1).** The navigation entries match the role table:
   - viewer and operator see Hosts, Package search, TOTP and Password;
   - admin also sees Enrolment requests and Enrolment tokens.
   - `ROUTE_ROLES` is a `Record<RouteName, …>`, and `RouteView` switches with a `never` default, so adding a route without handling it fails `npm run typecheck`.
2. **REQ-133 (2).** A route the role may not open renders only "This page is not available for your role." The screen is never mounted, so its route is never requested. The server still enforces every rule.
3. **REQ-133 (3) and REQ-122 (1) (carried from my TASK-119 review).** An admin without TOTP gets only `TotpEnrol mode="required"` and Sign out, whatever the hash says. There is no navigation, and no other screen mounts, so no other route is requested (CHK-M5-349). This item is closed.
4. **#85 (a).** A non-admin without TOTP gets the offer after every sign-in. "Not now" is recorded against that session's view object, so the next sign-in offers again, and it leads to the host list.
5. **REQ-120 and #85 (c).**
   - With no session (never signed in, signed out, after a 401 or a reload), only sign-in renders, whatever the hash says.
   - The shell holds no token, only the token-free `SessionView` and a boolean.
   - Sign out uses `signOut()`, which clears the session even when logout fails.
6. **The TASK-123 carry-over.** `HostDetail` is mounted with `key={route.agentId}` (`routes.tsx:88`). This item is closed.
7. **Choices where the spec is silent.** After sign-in and after a TOTP replacement, the shell goes to `#/hosts`. That matches REQ-121 (5) and REQ-133, and I accept it.
8. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
9. **Scope.** 3 files, about 232 lines, over the 160 estimate because of JSX layout. I accept that for UI.

## Findings
1. nit, `App.tsx:75` and `App.tsx:98`. The shell wraps each screen in `<main>`, and every screen also renders its own `<main>`, so the page has nested `<main>` elements. HTML allows only one visible `<main>`, so screen readers may announce the landmark twice. Behaviour is not affected. Optional: use a `<div>` in the shell, or drop the screens' `<main>`.
   - **Revision 1 (impl-web):** the shell wrapper is now a `<div>`, the sign-in branch has no wrapper, and the role page is `<main aria-label="Not available">`. Every page now has exactly one `<main>`, with no behaviour change. I read the code and it needs no change. r1 TEST PASS (tester-m5): App 25/25, web suite 345/345, build and G42 OK, all 9 plants red. The nit is closed.
