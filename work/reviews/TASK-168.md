# TASK-168 REVIEW (first pass): regenerated client and M7 problem messages

Verdict: APPROVED (first pass)

Reviewer: reviewer-m7, 2026-10-27. REQ-183; PD-20; #98 (e), #102 (d); decisions row "Web: how the UI shows the #102 start-up 503". Low risk; one round.

Scope: frozen worktree `81d81e9`. I ignored the TASK-155/156 test files there. Per `work/reports/TASK-168-impl.md`:
- `web/src/api/schema.d.ts`: generated, +558 lines;
- `web/src/app/problems.ts`: +20 lines.

TEST: PASS (`work/reports/TASK-168-test.md`).

Re-run by me in a scratch copy of the worktree's `web/` (lockfile identical to main's):
- `npm run gen:api`: `schema.d.ts` is byte-identical to the committed file (G16). So the generated client was not hand-edited.
- `npm run lint`, `typecheck` and `format:check`: clean. `vitest`: 16 files, 401/401.

## Checks
1. **Generated client.** It equals the generator's output from the worktree's `openapi.json`. The new paths are `/api/v1/imports`, `/api/v1/policies` and `/api/v1/policies/{id}`, and all are covered by the `UserPathsArePrefixed` type check in `client.ts`.
2. **`policy_managed_on_server`.** It sits in the type switch, so it wins over any status, with fixed text and no action.
3. **#102 start-up 503 (lead ruling).**
   - Only `Retry-After` decides, through the existing `retryAfterSeconds`, which takes 1–9 ASCII digits and nothing else. With a valid header the answer is the not-ready text with action `wait`. Without one it is the unchanged generic 503 text (CHK-M5-185). An HTTP date, `-1`, `1.5` or `abc` falls back to the generic text.
   - `detail` is never read; the canary test shows hostile detail never reaches the text.
   - `audit_sink_unavailable` still wins by type. The singular "1 second" is accepted (decisions row).
4. **Unknown types** still fall through to the status texts.
5. **Plain text.** No message is built from response text (checklist 11 and 12).

## Findings
None blocking or should-fix.

1. Note, not a finding: this is the first pass. TASK-168 must be re-run (`gen:api`, then G16) once TASK-162 to 164 add their routes. That second pass gets its own short review of `schema.d.ts` only.
