# TASK-115 REVIEW: web toolchain (Vite build, jsdom, Testing Library, QR library)

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-115-impl.md`): `web/package.json`, `web/package-lock.json`, `web/vite.config.ts` (new), `web/index.html` (new) and the one `.gitignore` line. Sources: REQ-119, PD-28 (a), (b), (c) and (e), TS §6.3 L1140 (CSP), and decisions 2026-10-24 (#6 M5 half).

TEST: PASS (tester-m5, 2026-10-25).
- The build succeeds, and G42 holds on the built HTML.
- The production dependencies are only React, openapi-fetch and qrcode-generator.
- The page loads nothing from another origin.

## Checks
1. PD-28:
   - Vite is a direct, pinned dev dependency at the version the lock already held. There is no plugin and no dev-server proxy.
   - The build goes straight into `manager/bitscan_manager/webui/`, which is gitignored (b).
   - jsdom and `@testing-library/react` are dev-only and pinned (c).
   - The one runtime addition is `qrcode-generator` (e). Its HTML-string helpers are not used.
2. CSP fit (TS §6.3):
   - `assetsInlineLimit: 0`, so there are no `data:` URLs.
   - `sourcemap: false`.
   - `index.html` has no inline script or style, and its one module script is same-origin.
3. Supply chain:
   - Every version is exact.
   - All 236 lock entries have an `integrity` hash (I checked).
   - CI keeps `npm ci --ignore-scripts`.
4. Re-run by the reviewer (Windows):
   - `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
   - `npm ls --omit=dev --all` lists only openapi-fetch (plus helpers), qrcode-generator, react and react-dom (plus scheduler).
5. Scope: 4 web files plus one `.gitignore` line, as planned.

## Findings
1. nit, `web/vite.config.ts`. The file is outside `tsconfig.json`'s `include`, so `npm run typecheck` does not cover it. ESLint and Prettier do, and the impl report's ad-hoc strict check passed. Optional: a `tsconfig.node.json` for config files.
