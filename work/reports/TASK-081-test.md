# TASK-081 TEST report: web client regeneration

**Verdict: PASS** (2026-10-23, tester-f). REQ-089 (1)–(3); TS §6, §6.3, §8.2; #5, #70; PD-20. Plan checks CHK-M3-298, CHK-M3-299. Code: `web/src/api/schema.d.ts` (generated), `web/src/api/client.ts` (comment only) (`work/reports/TASK-081-impl.md`). Source: `manager/openapi.json` `4a02bb08…f31547`, unchanged by TASK-083.

## Commands (L, from `web/`)
- `npm run gen:api` with a before/after hash compare: identical, nothing added.
- `npm run typecheck`, `lint`, `format:check`: exit 0. `npm test`: 13 passed.
- Plants in a throwaway copy: 5 of 6 red; 1 harmless survivor (noted).

## Acceptance criteria
- G16 green at the M3 head (no diff after regeneration): CHK-M3-298 PASS; the `git diff --exit-code` form is CI only (the branch is uncommitted).
- The `UserPathsArePrefixed` guard passes, and fails on a planted unprefixed path: CHK-M3-299 PASS.
- `npm run typecheck` passes with a type-level call to `GET /api/v1/agents`: CHK-M3-299 PASS.

## Test changes
- `web/src/api/client.test.ts`: a new block "M3 generated paths (CHK-M3-299)" with 5 tests.

## Notes
- `AgentItem.status` is generated as `string`, not an enum of the six statuses, because the OpenAPI document does not enumerate it. That is not a TASK-081 defect (the file is generated); it is a possible contract nit for impl-manager if the UI (M5) needs the enum.
- If `manager/openapi.json` is re-exported again before the gate, `schema.d.ts` must be regenerated; G16 at the gate re-checks this.
