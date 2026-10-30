# TASK-207 IMPL: web client regenerated from the M9 `openapi.json`

Implementer: impl-manager-m9 (main assigned it to me in place of impl-web). REQ-232. Risk low. PD-20. Depends on TASK-204 (no export change), 205 and 206 (both re-exported `manager/openapi.json`).

## Files

| File | Change |
| --- | --- |
| `web/src/api/schema.d.ts` | regenerated with `npm run gen:api` (openapi-typescript 7.13.0, then prettier); +813 lines, insertions only; no hand edit |

No other file changed. `web/node_modules` was installed with `npm ci --ignore-scripts` from the lockfile (git-ignored).

## Checks (from `web/`)

- `npm run gen:api` run twice: byte-identical output (G16).
- The new paths are `/api/v1/scans`, `/api/v1/scans/{id}/cancel`, `/api/v1/scan-schedules` and `/api/v1/scan-schedules/{id}`, all under `/api/v1/`.
- `npm run typecheck`: pass. `npm run lint`: pass (0 warnings).
- `manager/openapi.json` is byte-identical to a fresh `python -m bitscan_manager.app` export at this tree (G6).
