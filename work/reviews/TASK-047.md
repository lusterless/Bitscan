# TASK-047 REVIEW: web client regenerated, `baseUrl` rechecked

Reviewer: reviewer. Date: 2026-10-22. REQ-059. Spec: TS §6 (one API at `/api/v1`), TS §6.3 (same origin, no CORS, CSP `'self'`), TS §8.2 (OpenAPI client regenerated with no diff, G16). Decisions: PD-20 (G16 checked at the M2 gate), #5 (health routes are unauthenticated and outside `/api/v1`), decisions 2026-10-20 (the TASK-006 row on the `baseUrl` assumption). Inputs:
- `work/reports/TASK-047-impl.md`;
- `work/reports/TASK-047-test.md`: PASS, rows CHK-M2-280 to -282 in `tests/m2/report.md`, 3 of 3 `baseUrl` mutants red.

Files reviewed:
- `web/src/api/schema.d.ts` (generated);
- `web/src/api/client.ts`;
- the tester's new `web/src/api/client.test.ts`.

Verdict: APPROVED

TASK-047 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **G16 (REQ-059 (1)).** My run: `manager/openapi.json` matches a fresh export byte for byte, and `npm run gen:api` reproduces `schema.d.ts` byte for byte. The CI form (`git diff --exit-code` plus the untracked-file check) cannot run on an uncommitted branch, so it moves to the M2 gate in CI, as PD-20 says.
- **Paths (REQ-059 (2)).** The eight M2 user paths are all under `/api/v1/`: `api-tokens`, `api-tokens/{token_id}`, `auth/login`, `auth/logout`, `auth/password`, `auth/totp/enrol`, `users` and `users/{user_id}`. Only `/healthz` and `/readyz` sit outside, per #5. The generated types have no 422 and no `HTTPValidationError`, which matches the TASK-038 error contract.
- **`baseUrl` (REQ-059 (3), TS §6.3).** `client.ts` keeps `baseUrl: ""`, with no absolute or protocol-relative origin. The new type-only guard `UserPathsArePrefixed` makes `npm run typecheck` fail (TS2344) if a later path is added without the `/api/v1/` prefix and is not listed as a health path. That turns the decisions-2026-10-20 recheck into a standing gate. It adds no runtime code and no dependency.
- **Tests.** `client.test.ts` stubs `Request`, records the URLs the product `api` builds (`/api/v1/auth/login`, `/api/v1/users/7`, `/healthz` at the root), and has type-level `@ts-expect-error` negatives: a wrong path, a missing `password`, a `GET` on login. The planted `baseUrl` values `/api/v1`, `https://manager.example` and `//manager.example` are red.
- **Web invariants.** No `fetch` outside `client.ts`, no storage and no HTML injection were added; the lint rules from TASK-005 and TASK-009 still pass.
- **Gates (my run, Windows, from `web/`).** `npm run typecheck`, `npm run lint` and `npm run format:check` exit 0, and `npm test` passes 8 of 8. `package.json` and `package-lock.json` are unchanged.
- **Scope.** 2 impl files: the generated schema plus about 10 hand-written lines in `client.ts`. Small.

## Findings

None block approval.

1. **note for M3.** M3 adds the agent routes under `/api/v1/agent/`, which keep the guard green, and possibly a metrics route (#5). If the metrics route sits at the root, it must be added to `HealthPath` deliberately, which is the point of the guard. The CI G16 run at the M2 gate is the remaining check.
2. **nit.** `UserPathsArePrefixed` is exported only to silence the unused-type lint. A `// eslint-disable-next-line` would avoid exporting it, but the export is harmless.
