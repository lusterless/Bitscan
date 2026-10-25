# TASK-116 IMPL: web session core, problem messages, hash router

Owner: impl-web. REQ-120, REQ-126; plan `work/plans/TASK-116.md` (followed as written); #85 (a), (b), (c); PD-29 (role stays a string). Worktree `Bitscan-m5`, branch `m5-ui`. **User second look (PD-30 (2))**: this task holds the `bsu_` token. The "Where the token lives" section below is written for that review.

## Files (all new; nothing else changed)

| File | Code lines (without comments and blanks) |
| --- | --- |
| `web/src/app/session.ts` | 97 |
| `web/src/app/problems.ts` | 87 |
| `web/src/app/router.ts` | 101 |

The plan estimated 170 lines. These three files come to 285 code lines, mostly because Prettier puts each switch case and each frozen route constant on its own line. Nothing beyond the plan's API was added. I flagged the size to `main` and suggested `router.ts` as the split point if a split is wanted. `web/src/api/client.ts` was **not** edited: the middleware is registered with `api.use(...)`.

## Where the token lives and when it is cleared (for the second look)

- **Single holder.** `session.ts` has one module-level variable, `let current: { token, view } | null`. It is the only reference the UI keeps to the `bsu_` token. The token is not put in React state, context, `localStorage`, `sessionStorage`, cookies, IndexedDB, the URL or hash, `console`, or any error text. `SessionView` (what screens get from `useSession()` and `currentSession()`) is a frozen `{ role, totpEnrolled, totpVerified, expiresAt }` with **no token field**. The token is not exported in any form.
- **Set.** `setSession(loginResponse)` is called on a successful sign-in (TASK-118) and on the TOTP confirm (TASK-119, whose answer is a new `LoginResponse`). Each call replaces the old `{token, view}` outright, so the next request carries the new token.
- **Sent.** The middleware's `onRequest` sets `Authorization: Bearer <token>` on every request made through the generated client while a session exists. With no session it sets no header, so sign-in goes out without one.
- **Cleared.**
  1. `clearSession()` drops the reference (`current = null`) and notifies subscribers.
  2. Any **401** whose request carried the *current* token clears the session (`onResponse`). It compares the request's `Authorization` header with the current bearer value, so a late 401 for a request sent with an older token (for example one in flight during the TOTP-confirm swap) cannot end the new session (CHK-M5-354). A 401 to sign-in itself (sent with no session) changes nothing.
  3. `signOut()` calls `POST /api/v1/auth/logout` and clears the session in `finally`. A network error is caught and ignored (nothing is logged), and a 401 or any other refusal still ends the UI session (REQ-120 (4)). `signOut()` never rejects. It is also the "sign in again" action for `totp_session_required`.
  4. A page reload loses module memory, so the UI starts signed out (#85 (c)). There is no restore, refresh or remember-me code.
- JavaScript cannot zero a string. "Cleared" means the last reference is dropped and the string is left for garbage collection.
- No `console` call exists in any of the three files.

## What each file does

### `session.ts`
Exports `Role`, `SessionView`, `NextScreen`, `toRole`, `setSession`, `clearSession`, `currentSession`, `useSession`, `nextScreen`, `signOut`, as in the plan.
- `toRole`: `"admin" | "operator" | "viewer"` pass through. Any other string becomes `"viewer"` (PD-29, least privilege).
- `nextScreen`: an admin with `totpEnrolled: false` gets `"totp-required"`, a non-admin with `totpEnrolled: false` gets `"totp-offer"`, everyone else gets `"hosts"` (#85 (a)).
- `useSession` uses `useSyncExternalStore`. The snapshot is the same frozen view object until the next `setSession` or `clearSession`. `clearSession()` with no session does not notify.
- The middleware is registered once, when the module is first evaluated. Anything that imports `session.ts` gets it.

### `problems.ts`
- `toProblem(error, response)`: `status` comes from the response. `type` and `detail` are read only if they are strings in the parsed body; otherwise they become `"about:blank"` and `null`. `Retry-After` counts only as 1 to 9 ASCII digits (checked with plain character tests); anything else, including an HTTP date, gives `null`.
- `messageFor(problem)`: first it switches on `type` (`totp_session_required` gives `sign-in-again`, `audit_sink_unavailable` gives no action, `forbidden` gives no action, `totp_enrolment_required` gives `totp-enrol`). Then it switches on `status` (401, 429 with `wait`, 503, and the default `Request failed (status N).`). The texts are word for word from the plan table, with one addition: for 429, `Retry-After: 1` says "Wait 1 second." (singular). Other values say "Wait N seconds.", and a missing value says "Wait a moment.". No message contains response text. `detail` is returned separately for `ProblemBanner` (TASK-117) to show as text.
- No message ever asks for an API token (CHK-M5-347).

### `router.ts`
- `Route` and `RouteName` are as in the plan. `parseHash` follows the plan's table exactly. `""`, `#`, `#/` and `#/hosts` give `hosts`. `#/hosts/<uuid>` gives `host`, with the id lower-cased. Anything else (an unknown path, extra segments, a trailing slash, a query part, a non-UUID id) gives `hosts`.
- `isUuid`: length 36, hyphens at 8, 13, 18 and 23, hex digits (either case) elsewhere. It uses character comparisons, with no regular expression.
- `formatHash` is an exhaustive switch (a `never` default), so a new `Route` member fails `npm run typecheck`. `navigate` sets `location.hash`. `useRoute` subscribes to `hashchange` with the hash string as the snapshot and memoises `parseHash`.
- Only route names and a host id ever go into the hash. Nothing secret or typed by the user does.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`: pass.
- `npm run lint`: pass. The G12 storage, `innerHTML` and `fetch` rules apply to these files; none uses `fetch`, storage or a built key.
- `npm run format:check`: pass.
- Builder checklist: items 11 and 12 (no token or response text in logs or messages) hold. The other items are manager-only.

## Notes for the tester (TP-M5-09)

- Test doubles: stub `globalThis.fetch` before the first dynamic import of `src/api/client.ts` / `src/app/session.ts` (the plan's tester note). `openapi-fetch` calls `fetch(request, init)` with the `Request` after middleware, so the stub sees the `Authorization` header on `request.headers`. A test middleware that returns a `Response` from `onRequest` skips the `onResponse` of every middleware, including the 401 rule.
- Each fresh module instance (`vi.resetModules()` plus a dynamic import) registers the middleware once on that instance's `api`.
- `signOut()` resolves, never rejects, even when the stubbed `fetch` throws.
- The 429 text is singular for exactly 1 second (see above).
