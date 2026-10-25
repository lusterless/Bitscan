# TASK-116 plan: web session core, problem messages, hash router and the screen contract

Covers TASK-116 (`web/src/app/session.ts`, `problems.ts`, `router.ts`) and fixes the interfaces TASK-117 to TASK-126 build on. REQs: REQ-120, REQ-126 (and the contracts behind REQ-121, REQ-122, REQ-133). Owner: impl-web. One review round; **PD-30 (2)** asks whether the user also gives this task (with TASK-118 and TASK-119) a second look, since it holds the `bsu_` token. Tests: TP-M5-09; mutation rows CHK-M5-342 to -344, -347.

**Blocked on #85** (a), (b), (c), (e) for the sign-in and TOTP flow it encodes; PD-29 for the role type. Nothing here needs a manager change: the routes are M2's, and `web/src/api/client.ts` is **not edited** (the middleware is registered with `api.use`).

In this file `w/` is `web/`.

## Spec and rule quotes

- TS §6.2 L1080: session `bsu_…` "Web UI; held in memory, never in `localStorage`". L1076: "every call sends `Authorization: Bearer <token>`".
- TS §6.2 L1089: "Every new user is offered TOTP enrolment at first sign-in; admins must complete it … An admin with no TOTP yet … gets a session that can call only `/auth/totp/enrol` and `/auth/logout`; after enrolling, the session is re-issued as TOTP-verified."
- TS §6.2 L1084: sensitive actions need a TOTP-verified session and are refused for API tokens. TS §5.3: refused after 15 minutes of audit-sink outage.
- TS §8.1 L1254 (stolen web session, XSS) and `.claude/rules/web-ui.md`: token in memory only; "The UI must prompt for TOTP rather than fall back to an API token"; render API data as plain text.
- `.claude/rules/security-invariants.md`: "Never write … any token, to application logs".

## Lint constraints that shape the code (`w/eslint.config.js`, unchanged)

- Outside `src/api/client.ts`, the identifiers `fetch` and `XMLHttpRequest` are errors: all HTTP goes through `api` from `src/api/client.ts`.
- `localStorage`, `sessionStorage`, `cookieStore` (identifiers) and `.cookie` / `.localStorage` … (static member keys) are errors, in product **and test** files. Tests spy through `Storage.prototype` and `Object.getOwnPropertyDescriptor(Document.prototype, "cookie")` instead (tester note).
- Built property keys (template literal or `"x" + y` as a member key) are errors (TASK-005 nit, kept): use a `Map`, a `switch` or a `Record` indexed by a typed variable.
- `noInlineConfig`: no `eslint-disable` comments.

## `src/app/session.ts`

```ts
import type { components } from "../api/schema";
type LoginResponse = components["schemas"]["LoginResponse"];

export type Role = "viewer" | "operator" | "admin";

/** What screens may read. The token is not part of it. */
export interface SessionView {
  readonly role: Role;
  readonly totpEnrolled: boolean;
  readonly totpVerified: boolean;
  readonly expiresAt: string; // RFC 3339, as sent
}

export type NextScreen = "totp-required" | "totp-offer" | "hosts";

export function setSession(response: LoginResponse): void; // sign-in and TOTP confirm
export function clearSession(): void;
export function currentSession(): SessionView | null;
export function useSession(): SessionView | null;            // useSyncExternalStore
export function nextScreen(view: SessionView): NextScreen;
export function signOut(): Promise<void>;
export function toRole(value: string): Role;                  // unknown -> "viewer" (PD-29)
```

Rules:
1. **One module-level variable** holds `{ token, view }` or `null`. Nothing else stores the token: no React state or context, no storage API, cookie, IndexedDB, URL, `console` call or error message (REQ-120 (1), CHK-M5-342). `view` is a new frozen object on each `setSession`, and the same object is returned until the next change, so `useSyncExternalStore` sees a stable snapshot.
2. `setSession(r)` keeps `r.token` and builds the view from `role` (through `toRole`), `totp_enrolled`, `totp_verified`, `expires_at`, then notifies subscribers. The TOTP confirm response is a new `LoginResponse` (`POST /api/v1/auth/totp/enrol` answers `EnrolStartResponse | LoginResponse`); passing it to `setSession` replaces the old token, so the next request carries the new one (REQ-122 (2)).
3. **Middleware**, registered once when the module is first evaluated, with `api.use(...)`:
   - `onRequest`: if a session exists, `request.headers.set("Authorization", "Bearer " + token)`. With no session no header is set (the only request then is sign-in, REQ-120 (2)).
   - `onResponse`: if `response.status === 401` **and** the request carried the current token, `clearSession()` (REQ-120 (3), CHK-M5-344). Comparing the token means a late 401 for a request sent with an older token (for example one in flight while the TOTP confirm swapped the session) cannot end the new session. A 401 to sign-in itself (no session) changes nothing.
4. `signOut()`: `await api.POST("/api/v1/auth/logout")` inside `try`, `clearSession()` in `finally`, so a failing or rejected logout still ends the UI session (REQ-120 (4)). It is also the "sign in again" action of REQ-126.
5. `nextScreen(view)` (#85 (a)): admin with `totpEnrolled: false` → `"totp-required"` (TS §6.2 L1089: only TOTP and sign-out); non-admin with `totpEnrolled: false` → `"totp-offer"` (offered after every sign-in, "Not now" allowed); otherwise `"hosts"`.
6. A reload starts signed out (#85 (c)): the variable is lost with the page. No refresh or restore code exists.
7. The UI never asks for, accepts or stores an API token (`bsk_`); nothing here reads one.

Registering at module evaluation means every screen that imports `useSession` (or anything importing `session.ts`) gets the middleware, and `main.tsx` (TASK-126) needs no setup call. **Tester note:** test doubles answer requests by stubbing `globalThis.fetch` (`vi.stubGlobal("fetch", …)`, a string, not the banned identifier) before the first dynamic import of `src/api/client.ts`, as `client.test.ts` does for `Request`; `openapi-fetch` reads `globalThis.fetch` when the client is created. Answering from a test middleware's `onRequest` instead may skip later `onResponse` middlewares, which would hide the 401 rule.

## `src/app/problems.ts`

```ts
export interface ProblemInfo {
  readonly status: number;
  readonly type: string;            // "about:blank" when the body is not a problem
  readonly detail: string | null;   // shown as text only
  readonly retryAfterS: number | null;
}

export type ProblemAction = "sign-in-again" | "totp-enrol" | "wait" | null;

export interface ProblemMessage {
  readonly text: string;            // fixed text, never built from the response
  readonly action: ProblemAction;
}

export function toProblem(error: unknown, response: Response): ProblemInfo;
export function messageFor(problem: ProblemInfo): ProblemMessage;
```

`toProblem` reads `type` and `detail` from the parsed body only if they are strings (anything else gives `"about:blank"` and `null`), takes `status` from the response, and reads `Retry-After` as a non-negative integer of seconds (anything else, including an HTTP date, gives `null`).

`messageFor` (REQ-126 (1)), a `switch` on `type` with a default:

| Status and `type` (from the M2 dependencies) | Message | Action |
| --- | --- | --- |
| 403 `totp_session_required` | This action needs a sign-in with your TOTP code. Sign in again with your password and code. | `sign-in-again` (calls `signOut()`; #85 (b): there is no step-up route). Never a prompt for an API token (CHK-M5-347) |
| 503 `audit_sink_unavailable` | Sensitive actions are paused while the audit log cannot be shipped. Try again later. | none |
| 403 `forbidden` | Your role does not allow this. | none |
| 403 `totp_enrolment_required` | Set up TOTP to continue. | `totp-enrol` |
| 401 (any type) | Your session has ended. Sign in again. | none (the middleware already cleared the session) |
| 429 (any type) | Too many requests. Wait N seconds. (N from `retryAfterS`; "a moment" if null) | `wait` |
| 503 other | The manager is unavailable. Try again later. | none |
| anything else | Request failed (status N). | none |

`detail`, when present, is shown below the message as text by `ProblemBanner` (TASK-117); the message itself never includes response text. Sign-in uses its own generic 401 text (REQ-121 (2), TASK-118); screen-specific texts (`409` "already decided", `404` "Host not found") belong to the screens.

## `src/app/router.ts`

```ts
export type Route =
  | { readonly name: "hosts" }
  | { readonly name: "host"; readonly agentId: string }   // lowercase hyphenated UUID
  | { readonly name: "packages" }
  | { readonly name: "enrolment-requests" }
  | { readonly name: "enrolment-tokens" }
  | { readonly name: "totp" }
  | { readonly name: "password" };

export type RouteName = Route["name"];

export function parseHash(hash: string): Route;
export function formatHash(route: Route): string;
export function navigate(route: Route): void;   // sets location.hash
export function useRoute(): Route;              // hashchange via useSyncExternalStore
export function isUuid(value: string): boolean;
```

| Hash | Route |
| --- | --- |
| `#/hosts`, `""`, `#`, `#/` | `hosts` |
| `#/hosts/<uuid>` | `host` (the id lower-cased) |
| `#/packages` | `packages` |
| `#/enrolment/requests` | `enrolment-requests` |
| `#/enrolment/tokens` | `enrolment-tokens` |
| `#/account/totp` | `totp` |
| `#/account/password` | `password` |
| anything else (unknown path, extra segments, a non-UUID host id, a query part) | `hosts` |

`formatHash(parseHash(formatHash(r)))` equals `formatHash(r)` for every route (TP-M5-09). `isUuid` checks length 36, hyphens at 8, 13, 18 and 23, and hex digits elsewhere with plain character checks; no regular expression touches the hash. Search filters are not put in the hash (the hash then never holds anything a user typed except a host id), and nothing secret ever goes into the URL. Sign-in is not a route: `App` (TASK-126) shows it whenever there is no session, whatever the hash.

## Screen contract (TASK-117 to TASK-126)

Every screen is a named export in `src/screens/<Name>.tsx`, a function component with exactly these props, so TASK-126 wires them without changing them and no two screen tasks share a file:

| Screen (task) | Props |
| --- | --- |
| `SignIn` (TASK-118) | `{ onSignedIn: (next: NextScreen) => void; notice?: "password-changed" }` |
| `TotpEnrol` (TASK-119) | `{ mode: "required" \| "offer" \| "manage"; onDone: () => void; onSkip?: () => void }` (`onSkip` only for `"offer"`) |
| `PasswordChange` (TASK-119) | `{ onChanged: () => void }` (on 204 it calls `clearSession()`, then `onChanged()`; `App` then shows sign-in with the "password changed" note, so `SignIn`'s full props are `{ onSignedIn: (next: NextScreen) => void; notice?: "password-changed" }`) |
| `EnrolmentTokens` (TASK-120) | `{}` |
| `EnrolmentRequests` (TASK-121) | `{}` |
| `Hosts` (TASK-122) | `{ navigate: (route: Route) => void }` |
| `HostDetail` (TASK-123) | `{ agentId: string; navigate: (route: Route) => void }` |
| `PackageSearch` (TASK-124, TASK-125) | `{ navigate: (route: Route) => void }` |

Conventions every screen follows:
- It calls the API only through `api` and shows failures with `ProblemBanner` (TASK-117), which uses `toProblem` and `messageFor`.
- It reads the role with `useSession()` only for its own controls; route-level role gating is TASK-126's (`routes.tsx`: a `Record<RouteName, readonly Role[]>` and an exhaustive `switch`, so a new `Route` member fails `npm run typecheck` until it is wired).
- Secrets it receives (a TOTP secret, a created `bse_` token, passwords) live only in that component's state and are dropped when it unmounts or the result is closed; they are never logged or put in the URL.
- API values render as React text nodes only (REQ-132).

## Edge cases

- Two tabs: each has its own in-memory session (no shared storage); signing out in one does not sign out the other until its next 401.
- Session expiry (8 h idle, 24 h max) is the server's: the first 401 after it clears the session. No client timer.
- `toRole` treats any role string other than the three (PD-29 keeps `role` a string in the contract) as `viewer`, the least privilege; the server enforces roles anyway.
- A 401 from `POST /api/v1/auth/logout` still ends the session (`finally`).
- The middleware never logs; `console` is never called with a request, a response body or a header.

## Tests the plan expects (tester owns them)

TP-M5-09: `session.test.ts` (header present after `setSession` and absent before; the token swap on a second `setSession`; a 401 clearing the session only when it carries the current token; `signOut` with logout answering 200, 401 and a network error; spies on `Storage.prototype`, the `Document.prototype` cookie setter, `indexedDB.open` and every `console` method never receiving the token; `location.href` never containing it; `nextScreen` for each role and enrolment state; `toRole` on an unknown value); `problems.test.ts` (every table row, an unknown `type`, a non-problem body, `Retry-After` forms); `router.test.ts` (every hash row, the round trip, `isUuid` boundaries).
