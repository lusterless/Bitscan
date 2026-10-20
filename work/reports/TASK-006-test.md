# TASK-006 TEST report: generated API client from `manager/openapi.json`

Tester: tester. REQ-015, REQ-007. Date 2026-10-20. Impl report: `work/reports/TASK-006-impl.md`. Node 24.22.0, npm 11.19.1, openapi-typescript 7.13.0, TypeScript 5.9.3.

## Verdict: PASS

## Method

`web/` and `manager/openapi.json` are untracked, so `git diff --exit-code` is vacuous in the tree. I copied `web/` (without `node_modules`) and `manager/openapi.json` to a `mktemp -d` directory and ran a fresh `npm ci --ignore-scripts` there. `src/api/` was compared byte for byte with a snapshot of the committed files (`diff -r`), with no commits anywhere. The copy was deleted afterwards. The `git diff` form itself is checked in CI (TASK-009, CHK-M0-132).

## Commands and counts

- Tree, from `web/`: lint, typecheck, format:check and test all exit 0.
- Copy: 3 regenerations with no network (offline npm, dead proxy), 2 plants (a hand edit and an `openapi.json` path), 2 typed-client probes.
- TASK-005 regression under TypeScript 5.9.3: 2 typecheck plants, 1 format plant and 30 lint probes, 0 mismatches.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-015 (1): `gen:api` with no network, run twice, leaves `src/api/` unchanged | CHK-M0-110 | PASS |
| REQ-015 (2): a hand edit to the generated file is reverted by `gen:api` | CHK-M0-111 | PASS |
| REQ-015 (3): an `openapi.json` change makes the regenerated output differ | CHK-M0-112 | PASS (CI must regenerate before diffing) |
| REQ-015 (4): no absolute origin in `client.ts`; typecheck passes; client typed by the generated paths | CHK-M0-113 | PASS |
| `gen:api` reads the committed `manager/openapi.json`; generator header present | CHK-M0-114 | PASS |
| TypeScript 6.0.3 to 5.9.3 does not weaken the TASK-005 gates | CHK-M0-093-r3 | PASS |

## Notes

- `baseUrl: ""` assumes the OpenAPI paths carry the `/api/v1` prefix. The first M3 route should confirm this (impl report).
- For TASK-009: run `npm ci --ignore-scripts`, then `npm run gen:api`, then `git diff --exit-code -- manager/openapi.json web/src/api/`.
