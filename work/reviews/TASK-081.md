# TASK-081 REVIEW: web client regenerated from the M3 `openapi.json`; `baseUrl` and `HealthPath` rechecked

Reviewer: reviewer. Date: 2026-10-23. REQ-089. Spec: TS §6 L1056 (one API at `/api/v1`), §6.3 (same origin, no CORS, CSP `'self'`), §8.2 L1266 (OpenAPI client regenerated with no diff, G16); decisions PD-20 (one regeneration at the end of the milestone), #5 (health routes outside `/api/v1`), #70 (metrics is `GET /api/v1/metrics`, so `HealthPath` is unchanged). Inputs:
- `work/reports/TASK-081-impl.md`;
- tester-f's TEST PASS (message 2026-10-23: CHK-M3-298 and -299; `web/src/api/client.test.ts` block "M3 generated paths"; plants red: an unprefixed path, `/api/v1/agents` removed, a seventh agent path, `limit` as a string, and `openapi.json` changed without regenerating; the survivor, `HealthPath` widened with a path that does not exist, is harmless).

Files reviewed:
- `web/src/api/schema.d.ts` (generated);
- `web/src/api/client.ts` (comment only);
- the tester's additions to `web/src/api/client.test.ts`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **G16 (REQ-089 (1)).** I generated the client from the current `manager/openapi.json` into a temporary directory outside the tree, with the same `openapi-typescript` plus `prettier` steps as `npm run gen:api`. It is **byte-identical** to `web/src/api/schema.d.ts`. The CI form (`git diff --exit-code` plus the untracked check) runs once the branch is committed (PD-20).
- **Paths (REQ-089 (2)).** 29 paths: 27 under `/api/v1/` and only `/healthz` and `/readyz` outside it. The six TS §6.1 agent operations are exactly the `/api/v1/agent/` paths (type-level equality test). The metrics route is `/api/v1/metrics`, so `HealthPath = "/healthz" | "/readyz"` and `baseUrl: ""` stay correct. The `UserPathsArePrefixed` guard still passes and fails on a planted unprefixed path.
- **Typed call (REQ-089 (3)).** `api.GET("/api/v1/agents", { params: { query: { limit: 2, cursor: null } } })` builds `/api/v1/agents?limit=2` and is typed `{ items: AgentItem[]; next_cursor: string | null }`. A body, the unprefixed `/agents`, and `limit: "2"` are compile errors (`@ts-expect-error`).
- **Component renames.** `TotpEnrolRequest` is the TOTP body and `EnrolRequest` is now the agent enrol body. No web code referenced either name.
- **Web invariants (`.claude/rules/web-ui.md`, TS §6.3).** `client.ts` changed in a comment only. There is no `fetch` outside the client, no storage of tokens, and no HTML injection. `package.json` and `package-lock.json` are unchanged.
- **Gates (my run, Windows, from `web/`).** `npm run typecheck`, `npm run lint` and `npm run format:check` exit 0, and `npm test` passes 13 of 13.

## Findings

None.

## Note

The document types `AgentItem.status` (and the other status fields) as a plain `string` rather than the six-value enum, because the response models use `str`. This is not a contract defect, since user routes are not in the TS §6.5 frozen contract. The M5 UI would benefit from a `Literal` of the `agent_status` values in `api/user/agents.py`, regenerated with M5's first route task.
