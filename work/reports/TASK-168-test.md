# TASK-168 TEST (first pass): PASS

Tester: tester-m7-web, 2026-10-27. REQ-183 (1), (2) and the problem-mapping half; #98 (e), TS §4.1 L522 (`policy_managed_on_server`); #102 (d) and the lead's 503 rule (`work/decisions.md` 2026-10-27, "Web: how the UI shows the #102 start-up 503"); TS §6.3 L1133. Files under test: `web/src/api/schema.d.ts` (generated), `web/src/app/problems.ts`. Tests were written from the decision row, the task row and REQ-183 first. The code was read afterwards only to find the Retry-After parse bounds. **First pass only:** the TASK-162 to TASK-164 routes are not in `manager/openapi.json` yet, so G16 and the path checks must run again at the second pass.

## Tests added

- `web/src/app/problems.test.ts`: 28 new cases in two `CHK-M7-310 (TASK-168)` blocks.
  - `policy_managed_on_server` gives the server-folder text with action `null` for statuses 409, 400, 403, 404, 500 and 503. The text holds no detail and does not mention a token. A 409 without the type keeps the generic text.
  - 503 start-up answer:
    - Retry-After 10, 1 ("1 second", singular), 2, 0 and 999999999 give the not-ready text with action `wait`.
    - No Retry-After gives the generic text (CHK-M5-185).
    - The same through `toProblem` with real headers: `10`, `1` and `999999999` give not-ready; an HTTP date, `-1`, `1.5`, `abc`, an empty value and `1e3` give the generic text. A missing header and a non-problem body are covered too.
    - The detail is never read: five detail texts (one says "Retry-After: 99", one says "starting") do not change the result.
    - `audit_sink_unavailable` with Retry-After keeps the PAUSED text.
    - An unknown type on 503 is decided by the header. On 400, 404, 409, 500 and 502 it gets the generic text even with Retry-After. Retry-After does not change 500, 502 or 401.
- `web/src/api/client.test.ts`: 3 new cases ("M7 generated paths, first pass").
  - `/api/v1/policies`, `/api/v1/policies/{id}` and `/api/v1/imports` are paths; `/policies` and `/imports` are not.
  - The only paths outside `/api/v1` are still `/healthz` and `/readyz`.
  - The list `status` query type is exactly `"enabled" | "disabled"` (#9).
  - A GET goes out as `/api/v1/policies?limit=50&status=disabled`.

## Runs (Linux container, Node 22, from `web/`)

| Run | Command | Count |
| --- | --- | --- |
| r1 | `npx vitest run src/app/problems.test.ts` | 74/74 passed, 0 failed, 0 skipped |
| r2 | `npx vitest run src/api/client.test.ts` | 16/16 passed, 0 failed, 0 skipped |
| G16 | `npm run gen:api` twice in a scratch copy (`tweb/web` with `tweb/manager/openapi.json` = HEAD), `cmp` against `web/src/api/schema.d.ts` | byte-identical both times; `manager/openapi.json` is unchanged from HEAD |
| paths | `git diff b2e1351 HEAD -- web/src/api/schema.d.ts` | new paths are exactly `/api/v1/imports`, `/api/v1/policies` and `/api/v1/policies/{id}` |
| gates | `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm test` | clean; full suite 401/401 passed, 0 failed, 0 skipped (16 files) |

## Report rows (for `tests/m7/report.md`)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-317 (G16, web half) | CODE | L | G16 | PASS (first pass) | regeneration byte-identical twice; a hand edit in the copy is undone by regeneration (the plant shows a diff) | 2026-10-27 |
| CHK-M7-310 (REQ-183 (2), first pass) | CODE | L | r2, typecheck | PASS | the three new paths are under `/api/v1/`; `UserPathsArePrefixed` holds; the plant of an unprefixed `/imports` gives 6 `tsc` errors | 2026-10-27 |
| CHK-M7-310 (problem mapping) | CODE | L | r1 | PASS | the cases listed above | 2026-10-27 |
| CHK-M5-185 (regression) | CODE | L | r1 | PASS | every row in the existing table is unchanged, including 503 `about:blank` with no header giving the generic text | 2026-10-27 |

## Plants (scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/tweb/web`): 8/8 red

The unchanged copy passed 115/115 first, as a control.

| Plant | Result |
| --- | --- |
| The 503 not-ready text is also chosen when the detail contains "start" (the detail is read) | red, 1 failed |
| The 503 branch ignores Retry-After | red, 12 failed |
| The singular is dropped ("1 seconds") | red, 2 failed |
| The `policy_managed_on_server` case is missing | red, 6 failed |
| The detail is appended to the not-ready text | red, 12 failed |
| Retry-After also changes the 401 text | red, 1 failed |
| An unprefixed path in `schema.d.ts` | red in `npm run typecheck` (6 errors) |
| `schema.d.ts` is hand-edited | red in G16 (regeneration differs) |

## Findings

None blocking.
- The singular "1 second" is in place and tested, as the lead allowed.
- `0` gives "Try again in 0 seconds." with `wait`, which matches the 429 behaviour. Retry-After values over 9 digits are treated as invalid and give the generic text.
- An unknown type on 503 with Retry-After gets the not-ready text. This follows from the ruling (the header decides) and is tested as such.
