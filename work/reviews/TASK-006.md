# TASK-006 REVIEW: generated API client from `manager/openapi.json`

Reviewer: reviewer. Date: 2026-10-20. REQ-015, REQ-007. Spec: TS §6 L1056 (one API at `/api/v1`, OpenAPI 3.1 from code), TS §6.3 L1140 (no CORS, CSP `'self'`), TS §8.2 L1266 (generated client); `.claude/rules/web-ui.md` line 10; decisions PD-14 and 2026-10-20 (TypeScript 5.9.3, `baseUrl ""`). Inputs: `work/reports/TASK-006-impl.md`, `work/reports/TASK-006-test.md` (PASS), `tests/m0/report.md` CHK-M0-110 to -114 and CHK-M0-093-r3.

Verdict: APPROVED

One approval is enough for this task (TS §8.2 L1268).

## What was checked

- **Scope:**
  - `web/package.json` gains `gen:api`, `openapi-fetch` 0.17.0 (runtime) and `openapi-typescript` 7.13.0 (dev), both exact, and moves `typescript` to 5.9.3;
  - `web/src/api/schema.d.ts` is generated (17 lines);
  - `web/src/api/client.ts` is 6 lines;
  - the lock is regenerated.

  `eslint.config.js`, `tsconfig.json` and `main.tsx` are byte-identical to what I approved in TASK-005.
- **Lock:**
  - 190 entries, all `resolved` on registry.npmjs.org, all with `sha512-` integrity;
  - the only `hasInstallScript` is still darwin-only `fsevents`;
  - the runtime (non-dev) set is just `openapi-fetch`, `openapi-typescript-helpers`, `react`, `react-dom` and `scheduler`;
  - `npm ls` shows a single `typescript@5.9.3`.
- **Regeneration, in a throwaway copy of `web/` plus `manager/openapi.json`, after a fresh `npm ci --ignore-scripts` (exit 0, 165 packages):**

  | Step | Result |
  | --- | --- |
  | `gen:api` twice, offline (`npm_config_offline=true` and a dead proxy) | exit 0 both times; byte-identical to the committed `schema.d.ts` |
  | hand edit appended to `schema.d.ts`, then `gen:api` | reverted |
  | one path added to `openapi.json`, then `gen:api` | output differs |
  | typed `api.GET("/api/v1/agent/x")` on that path | `tsc` exit 0 |
  | the same call on an unknown path | `tsc` exit 2 |
  | lint and format on the generated output with a path | exit 0 |

- **No absolute origin:**
  - `client.ts` contains no `http:`, `https:` or `//host`;
  - openapi-fetch builds `` `${baseUrl}${pathname}` `` and sets no `credentials` override, so with `baseUrl: ""` every call is a same-origin relative URL (TS §6.3);
  - the `src/api/` lint exemption lifts only the `fetch` guard (TASK-005).
- **Generator network and telemetry:** neither openapi-typescript nor `@redocly/openapi-core` calls a telemetry endpoint. Redocly's `registry-api.js` is used only by the Redocly CLI, which is not imported. The resolver fetches only absolute remote `$ref`s, and our generated document has none.
- **TypeScript 5.9.3:** justified. It is the only version inside both `openapi-typescript`'s `^5.x` and `typescript-eslint`'s `<6.1.0`, and it is recorded in `work/decisions.md`. Under 5.9.3 the TASK-005 implicit-`any` plant still gives exit 2.

## Findings

1. **nit, M3 recheck (decision 2026-10-20). `baseUrl: ""` assumes the OpenAPI paths carry `/api/v1`.**
   - Where: `web/src/api/client.ts:6`.
   - This matches TS §6, where every route is `/api/v1/...`, and FastAPI routers mounted with `prefix="/api/v1"` emit full paths. If M3 instead uses `root_path` or a mounted sub-app, the paths lose the prefix and `baseUrl` must become `"/api/v1"` (still same-origin). This is tied to question #6, how the UI is served.
2. **nit, for TASK-009.** The diff check must regenerate before it diffs: `npm ci --ignore-scripts`, then `npm run gen:api`, then `git diff --exit-code -- web/src/api/`. A changed `openapi.json` without regeneration leaves `src/api/` unchanged, so diffing first would pass. Running `gen:api` under a dead proxy in CI would also catch any future remote `$ref`.
