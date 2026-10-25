# TASK-126 IMPL: app shell (routes, navigation by role, gating, sign-out)

Owner: impl-web. REQ-133, REQ-120, REQ-122; TS §6.2 (L1089, L1093–L1127); #85 (a), (c). Builds on TASK-116 to TASK-125 and the screen contract in `work/plans/TASK-116.md`. Worktree `Bitscan-m5`, branch `m5-ui`.

## Files

| File | Change | Code lines |
| --- | --- | --- |
| `web/src/main.tsx` | renders `<App />` inside `StrictMode` (was a placeholder `<p>`) | 11 |
| `web/src/app/App.tsx` (new) | the shell: sign-in / TOTP gates, header with navigation and Sign out | 126 |
| `web/src/app/routes.tsx` (new) | `ROUTE_ROLES`, `isAllowed`, `navFor`, `RouteView` (exhaustive switch), the role page | 95 |

About 232 code lines against the planned 160, mostly Prettier's JSX layout. No other file changed. No screen, `session.ts` or `router.ts` was edited, and no dependency was added.

## Interfaces

```ts
// routes.tsx
export const ROUTE_ROLES: Readonly<Record<RouteName, readonly Role[]>>;
export function isAllowed(name: RouteName, role: Role): boolean;
export interface NavEntry { readonly route: Route; readonly label: string }
export function navFor(role: Role): readonly NavEntry[];
export function RouteView(props: { route: Route; role: Role; onPasswordChanged: () => void }): JSX.Element;
// App.tsx
export function App(): JSX.Element;
```

A new `Route` member fails `npm run typecheck` twice: the `Record<RouteName, …>` needs its entry, and the `RouteView` switch has a `never` default.

## Behaviour

What `App` renders, decided in this order on every render:

1. **No session** (never signed in, signed out, any 401 that cleared it, or a page reload, #85 (c)): only `<SignIn>` inside `<main>`, whatever the hash. No header, no navigation and no other screen is mounted. After a password change, it shows `notice="password-changed"`. A successful sign-in clears that notice and navigates to `#/hosts`. The hash is set synchronously before React re-renders, so a stale hash from the previous session (for example `#/enrolment/tokens`) never mounts its screen.
2. **`nextScreen(view) === "totp-required"`** (admin with `totp_enrolled: false`, TS §6.2 L1089): a header with **Sign out** only (no navigation) and `<TotpEnrol mode="required">`, for **every** hash. No other screen is mounted, so no other route is requested (REQ-122 (1), CHK-M5-282, CHK-M5-349). The confirm answer replaces the session (TASK-119) with `totp_enrolled: true`, and `onDone` navigates to `#/hosts`.
3. **`"totp-offer"`** (non-admin with `totp_enrolled: false`, #85 (a)), unless the user already chose "Not now" for this session: a header with **Sign out** only and `<TotpEnrol mode="offer">`. **Not now** records the current `SessionView` object as skipped and navigates to `#/hosts`. Each sign-in creates a new view object, so the offer comes back after every sign-in. A confirm replaces the session (now enrolled) and goes to `#/hosts`. Because the offer is derived from the session rather than set in `onSignedIn`, no screen renders in between.
4. **Otherwise**: the header (`<nav aria-label="Main">` with the role's entries, plus **Sign out**) and `RouteView` for the current hash route.

`RouteView`: if `ROUTE_ROLES[route.name]` does not include the role, it renders only the role page: heading "Not available", text "This page is not available for your role.". The route's screen is not mounted, so no request is sent to it (REQ-133 (2), CHK-M5-281). Otherwise it renders the screen with the contract props. **`HostDetail` is mounted with `key={route.agentId}`** (TASK-123), so a different host starts again from its first package page.

### Navigation per role (REQ-133 (1), CHK-M5-280)

| Entry (link text) | Hash | viewer | operator | admin |
| --- | --- | --- | --- | --- |
| Hosts | `#/hosts` | yes | yes | yes |
| Package search | `#/packages` | yes | yes | yes |
| Enrolment requests | `#/enrolment/requests` | no | no | yes |
| Enrolment tokens | `#/enrolment/tokens` | no | no | yes |
| TOTP | `#/account/totp` | yes | yes | yes |
| Password | `#/account/password` | yes | yes | yes |

The host detail route (`#/hosts/<uuid>`) is open to every role but has no entry of its own. The **Hosts** link carries `aria-current="page"` on both `hosts` and `host`, and each other entry carries it on its own route. The links are plain `href` hash links: `useRoute` follows `hashchange`. **Sign out** is a `<button>` in every signed-in layout (normal, required, offer).

### Choices where the spec is silent (reviewer may change)

- After a sign-in, the shell always goes to `#/hosts`, as REQ-121 (5) and REQ-133 name, rather than back to the hash in the address bar.
- After a successful TOTP replacement from the **TOTP** entry (`mode="manage"`), `onDone` goes to `#/hosts`. Staying would show the replacement start form again.
- The shell shows no username or role text (the `LoginResponse` has no username, and nothing required it).

## Token handling (REQ-120)

- `App` and `routes.tsx` import only `useSession`, `nextScreen`, `signOut` and the `Role`/`SessionView` types from `session.ts`. `SessionView` has no token field. The shell keeps no token in state, props, context, storage, the URL or hash, or `console` (there is no `console` call). The only `useState` values are a boolean (`passwordChanged`) and a token-free `SessionView` reference (`offerSkipped`).
- **Sign out** calls `signOut()`, which clears the session in `finally` even when logout fails (TASK-116). The shell then shows sign-in. A 401 on any screen clears the session in the TASK-116 middleware, and `useSession()` returning `null` switches the shell to sign-in (CHK-M5-284).
- `StrictMode` stays in `main.tsx`. In development it mounts effects twice, so a dev server may show duplicate GETs. The production build has no such effect.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- `npm run build`: pass. `../manager/bitscan_manager/webui/index.html` (0.31 kB; one external module script, no inline script or style) and `assets/index-Kw1P0Mv1.js` (282.75 kB). All screens are now in the bundle.
- Builder checklist items 11 and 12 (no token or response text in logs or messages): hold. The others are manager-only.
- No `dangerouslySetInnerHTML`, `innerHTML`, `style=`, `fetch`, storage or built keys (`ROUTE_ROLES[route.name]` indexes with a typed variable).

## Notes for the tester (TP-M5-19, `src/app/App.test.tsx`)

- Render `<App />` (named export from `src/app/App.tsx`). Stub `fetch` before the first dynamic import, as for the screens. A sign-in through the real `SignIn` form posts `/api/v1/auth/login`. After it, the shell immediately requests the host list (`GET /api/v1/agents?limit=50`) unless a TOTP gate applies.
- Navigation: `getByRole("navigation", { name: "Main" })`, whose links have the texts in the table above. In the TOTP-required and offer layouts there is no `navigation` element, only the "Sign out" button.
- Role page text: "This page is not available for your role.". Set `location.hash` before the render (or dispatch `hashchange` after it).
- Sign-in always navigates to `#/hosts`. To test a viewer on an admin hash, sign in first, then set the hash.
- Offer: after "Not now", the host list renders. A second sign-in (a new session) shows the offer again.
- Reload: `vi.resetModules()` plus a fresh dynamic import of `App.tsx` gives a module state with no session, so sign-in renders.

## Revision 1 (optional reviewer nit, `work/reviews/TASK-126.md`: nested `<main>`)

- `web/src/app/App.tsx`: the shell's content wrapper is now a `<div>` (was `<main>`), and the sign-in branch renders `<SignIn>` without a wrapper. Every screen already renders its own `<main>`, so the page now has exactly one `main` landmark.
- `web/src/app/routes.tsx`: the role page's outer element is now `<main aria-label="Not available">` (was `<section>`), so it too has one `main`. Its heading and text are unchanged.
- No behaviour change. `App.test.tsx` does not query `main` or the role page's region; it finds the role page by its text. `npm run typecheck`, `npm run lint`, `npm run format:check` and `npm run build` pass.
