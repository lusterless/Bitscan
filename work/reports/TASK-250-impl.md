# TASK-250 IMPL: Host page scan history

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W3 batch.
REQ: REQ-283, REQ-284. Open items: #145 (c). Spec: TS §6.2 L1113.
Uses TASK-256 (`ScanTable`, `ScanLinks`).

## Files

- `web/src/screens/HostScans.tsx` (new): `HostScans({ agentId, links })`.
- `web/src/screens/HostDetail.tsx` (changed, +8 / −1): a new optional prop `scanLinks?: ScanLinks`. When it is given, `<HostScans key={agentId} agentId links={scanLinks} />` renders between the snapshot card and the Packages card. When it is absent, nothing changes and no extra request is sent.

## Behaviour

**Load.** `GET /api/v1/agents/{id}/scans` with `limit=20` and the cursor, paged through `Pager`.

**Rows.** `ScanTable`: each row's creation time links to `links.scanHref(scan_id)`.

**States:**
- An empty list shows "No scans of this host yet.".
- A refusal shows `ProblemBanner`. For example, a 404 for an unknown host is "Request failed (status 404).".
- A network failure shows "The manager is unavailable…".

## For TASK-251 and the tester

- `routes.tsx` (TASK-251, W4) does not pass `scanLinks` yet. Until it does, the app's host page shows no scan history.
- The existing `HostDetail.test.tsx` renders HostDetail without the prop, so its requests and output are unchanged.
- Test REQ-283 on `HostScans` directly, or on `HostDetail` with `scanLinks` given.

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. No vitest run.
