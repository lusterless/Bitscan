# TASK-168 IMPL (first pass): regenerate `schema.d.ts`, map the M7 problem answers

Owner: impl-web-m7. REQ-183; PD-20; #98 (e), #102 (d); lead ruling on the start-up 503 (option (a), `work/decisions.md` last row, commit b2e1351). TS §6.3 L1133 (problem details), §4.1 L522.

**This is the first pass.** At this head `manager/openapi.json` holds the profile routes (TASK-161: `GET /policies`, `GET` and `PATCH /policies/{id}`) and `GET /imports` (TASK-165). The upload, delete and rebuild routes (TASK-162, 163, 164: `POST /policies/import`, `DELETE /policies/{id}`, `POST /policies/rebuild`, `GET /tasks/{id}`) do not exist yet. TASK-168 must be run again (`npm run gen:api`, then G16) once they land. That second pass changes only `schema.d.ts`; `problems.ts` already covers their answers.

## Files

| File | Change |
| --- | --- |
| `web/src/api/schema.d.ts` | Regenerated with `npm run gen:api` (never hand-edited); +558 lines. The lead snapshotted it in commit 481e39a. |
| `web/src/app/problems.ts` | +20 lines (code and comments). |

No other file changed. `web/src/api/client.ts` is unchanged: its `UserPathsArePrefixed` check already covers the new paths.

## Acceptance items

- **G16 shows no diff.** I ran `npm run gen:api` three times (before the edits, after them and after the gates). Each output was byte-identical to the first (`cmp`).
- **Every new path starts with `/api/v1/`.** The new paths are `/api/v1/imports`, `/api/v1/policies` and `/api/v1/policies/{id}` (`schema.d.ts` L414, L487, L504). `npm run typecheck` passes the `UserPathsArePrefixed` assertion in `client.ts`.
- **`policy_managed_on_server`** (`problems.ts` L96). It is in the type switch, so it wins over any status. The fixed text is "This policy is managed in the server folder; change its file there." with action `null`. The wording comes from the plan TASK-162 L78 detail; the UI never reads the detail.
- **#102 start-up answer** (`problems.ts` L106-L118, helper `notReadyText` L69). The answer has no type of its own (503 `about:blank`), so per the lead's ruling only the `Retry-After` header decides:
  - 503 with a valid Retry-After (1 to 9 ASCII digits, parsed by the existing `retryAfterSeconds`): "The manager is not ready yet. Try again in N seconds." with action `"wait"`. For exactly 1 the text is "Try again in 1 second." (singular), to match the existing 429 text. Tell me if the singular form should go.
  - 503 with no Retry-After, or an invalid or HTTP-date one: the existing "The manager is unavailable. Try again later." with action `null`, so CHK-M5-185 is unchanged.
  - `detail` is never read.
- **An unknown type still maps to the generic text.** The type switch falls through to the status switch, as before.

## Gates (Linux container, Node 22, from `web/`)

`npm run lint`, `npm run typecheck`, `npm run format:check` and `npm test` (345/345, existing tests) all pass, and `npm run gen:api` is byte-stable. Builder checklist: items 11 and 12 hold (no message is built from response text). The other items are manager-only.

## Cases for the tester (`problems.test.ts`)

1. `info(409, "policy_managed_on_server")` gives the server-folder text with action `null`. So does any status with that type (for example 403 or 400).
2. 503 `about:blank` with `retryAfterS` 10 gives "The manager is not ready yet. Try again in 10 seconds." and `"wait"`. 1 gives "... in 1 second.". 0 gives "... in 0 seconds.".
3. 503 `about:blank` with `retryAfterS` null gives the generic 503 text and `null`. Through `toProblem`, a header of `Wed, 21 Oct 2026 07:28:00 GMT`, `-1`, `1.5` or `abc` also gives the generic text.
4. 503 `about:blank` with Retry-After and a hostile `detail` such as `CANARY-<b>x</b>`: the text contains no detail.
5. `audit_sink_unavailable` 503 with Retry-After still gives the PAUSED text, because the type wins.
6. An unknown type `something_new` on 503 with Retry-After gets the not-ready text. That is by design (the header decides); on other statuses it still gets the generic text.
7. G16 again after the second pass.
