# TASK-047 TEST report: web client regeneration and baseUrl recheck

Verdict: **PASS**. Tester, 2026-10-22. REQ-059 (1)–(3), G16; TS §6, §6.3; #5. Impl report: `work/reports/TASK-047-impl.md`.

## Commands run
- L (Windows 11, Node 24.22.0), from `web/`: `npm run typecheck`, `npm run lint`, `npm run format:check`, `npm test`. All exit 0; 1 file, 8 tests.
- L: `%TEMP%\m2webmut\run.sh`: 3 `baseUrl` mutants plus a control, and the G16 byte check (the real case plus 2 planted), in throwaway copies of `web/` with `node_modules` linked by a junction.

## Criteria
| REQ-059 | Result | Rows |
| --- | --- | --- |
| (1), G16 regeneration leaves no diff | PASS (L); CI form NOT RUN (branch uncommitted, M2 gate) | CHK-M2-280 |
| (2), #5 user paths under `/api/v1/`, health routes outside | PASS | CHK-M2-281 |
| (3) `baseUrl` `""`, same origin, typed sign-in | PASS | CHK-M2-282 |

Mutations: 3 of 3 red, control green; the G16 check detects both stale cases. Test file added: `web/src/api/client.test.ts`.
