# TASK-123 IMPL: host detail

Owner: impl-web. REQ-128, REQ-132; TS §6.2 (L1109–L1110), §7.3 (L1225), §3.7; #69. Depends on TASK-117 and TASK-122 (`StatusBadge`, regenerated types). Worktree `Bitscan-m5`.

## Files

| File | Code lines |
| --- | --- |
| `web/src/screens/HostDetail.tsx` (new) | 238 |

Nothing else changed. The size is over the planned 190, mostly field rows and table JSX. Props: `{ agentId: string; navigate: (route: Route) => void }`.

## Behaviour

- **Requests.** `GET /api/v1/agents/{id}` once per `agentId`, and `GET /api/v1/agents/{id}/packages?limit=50[&cursor=…]` with `useCursorPages` and `Pager`. **TASK-126 should mount it as `<HostDetail key={agentId} …/>`** so that a different host starts on its first package page.
- **States.**
  - Loading shows "Loading.".
  - **404 shows "Host not found."** (REQ-128 (4)).
  - Other refusals go to `ProblemBanner`.
  - A network failure shows "The manager is unavailable. Try again later.".
  - Every state has a "Back to hosts" link (`#/hosts`; a click calls `navigate({name: "hosts"})`).
- **Identity** (a `<dl>`): Hostname, Machine-id, Agent id, Agent version, Enrolled, Last seen IP, Last heartbeat, Last inventory, Token issued, Token expires, Token revoked ("never" when null), Tags, Runner helpers ("none" when empty). The status uses `StatusBadge`. The hostname is also the `<h1>`. **No token is ever shown**; the item has none.
- **Operating system.**
  - Null `os_info` shows **"No inventory yet."**.
  - Otherwise it shows OS, OS id, OS version id, Kernel release, Architecture, CPU count, Memory (MB), Uptime (s) and Collected, with "unknown" for null values.
  - IP addresses are a `<ul>`, one item per address.
  - **`raw` is shown as `JSON.stringify(raw, null, 2)` inside `<pre>`**, a single text node, so a hostile key or value shows literally (REQ-128 (3)).
- **"Added / removed since last snapshot"** (`<section aria-label="Added / removed since last snapshot">`) appears only when `last_snapshot` is not null; a null snapshot shows no change list. It holds the snapshot time, the package count, and two sub-sections, "Added (N)" and "Removed (N)". Each line is "`name version architecture (status)`", one `<li>` per item in the order the API gives (REQ-128 (2)).
- **Packages** table columns: Name, Version, Architecture, Status, Source ("unknown" when null), Size (KB), First seen, Last seen. Paging uses the returned cursors, so each package shows once (REQ-128 (5)).
- Every API value is a text node. Answers that arrive after unmount or after a newer request are ignored.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No HTML rendering, no `style=`, no `fetch`, no storage, no built keys (row keys are fixed labels or indices), no `console`.

## Notes for the tester (TP-M5-16)

- Mount sends both GETs at once: detail, and packages with `limit=50`. A test double must answer both.
- The snapshot lists are the sections named "Added" and "Removed" inside the region named "Added / removed since last snapshot".
