# TASK-009 REVIEW: CI workflows for manager gates, web gates and the OpenAPI regeneration diff

Reviewer: reviewer. Date: 2026-10-20. REQ-017, REQ-002, REQ-005, REQ-007, REQ-015. Spec: TS §8.1 (hashed dependencies), §8.2 L1264-1266, §8.3 L1275/L1278. Inputs: `work/reports/TASK-009-impl.md`, `work/reports/TASK-009-test.md` (PASS round 2), `tests/m0/report.md` CHK-M0-130 to -137 and -137-r2, the M0 gate table (G1 to G6, G11 to G16); carry-overs from my reviews of TASK-001, TASK-003 and TASK-006.

Verdict: APPROVED

Round 2. One approval is enough here (TS §8.2 L1268): this is manager and web CI, not importer, auth, agent or runner code. G1 to G6 and G11 to G16 count as passed only after the first live PR run is green (note 3).

## Round 2 re-review

- **The change:** both diff steps now fail on any `git status --porcelain` line after the existing `git diff --exit-code`:
  - `manager.yml:55-63` covers `manager/openapi.json`;
  - `web.yml:67-73` covers `manager/openapi.json` and `web/src/api/`.

  Both use the `if [ -n "$changed" ]` form, with no `|| true`.
- **The extracted G16 script**, run with `bash -eo pipefail` in a scratch git repo:

  | Case | Exit |
  | --- | --- |
  | clean | 0 |
  | committed deletion of `schema.d.ts`, then regenerated | 1 (prints `?? web/src/api/`) |
  | content change | 1 |

- **actionlint v1.7.12:** 0 findings on all four workflows.
- **Unchanged from round 1:**
  - the setup-node v7.1.0 SHA and the Ryuk 0.8.1 digest are verified;
  - `contents: read` only, `persist-credentials: false`, no secrets or skips;
  - locks are installed as committed in fresh venvs;
  - `npm ci --ignore-scripts`, `gen:api` before the diff, `CI: "true"`, Ryuk pinned.

## Findings (round 2)

1. **Closed.** Round-1 should-fix: deleting a committed generated file bypassed G6 and G16.
2. **nit (info, for `main`, not this task).** TASK-005's `fetch` exemption covers every file under `web/src/api/`, so a hand-written non-generated file there could call `fetch` and pass lint and G16. Either narrow the exemption to `src/api/client.ts`, or check that `web/src/api/` holds only `client.ts` and `schema.d.ts`.
3. **note.** These must be green on the first PR:
   - the live runs (CHK-M0-136);
   - the pg tests with Docker (CHK-M0-050 to -052, -057);
   - the Ryuk digest pull.

   The fallback for Ryuk is `testcontainers/ryuk@sha256:…`. Never disable Ryuk.

## History

Round 1 was CHANGES_REQUESTED: a committed deletion of `manager/openapi.json`, `schema.d.ts` or `client.ts` was regenerated as an untracked file, and `git diff --exit-code` ignores untracked files, so G6 and G16 passed. Round 2 fixed it with the porcelain check.
