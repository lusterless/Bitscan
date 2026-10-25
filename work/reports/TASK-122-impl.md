# TASK-122 IMPL: regenerate the client (status enums) and the host list

Owner: impl-web. REQ-127, REQ-136, REQ-117, REQ-132. Depends on TASK-108 (enums) and TASK-117. Worktree `Bitscan-m5`.

## Files

| File | Change |
| --- | --- |
| `web/src/api/schema.d.ts` | regenerated with `npm run gen:api` from the current `manager/openapi.json` (generated; +299 / −9) |
| `web/src/components/StatusBadge.tsx` (new) | 16 code lines |
| `web/src/screens/Hosts.tsx` (new) | 100 code lines |

## The regeneration

- `AgentItem.status`, `AgentDetailItem.status` and `MatchItem.status` are now the six-value union (`awaiting_approval`, `enrolled`, `online`, `stale`, `offline`, `decommissioned`). `RequestItem.kind` and `RequestItem.decision` are now the PD-29 unions (TASK-108).
- **Also in this regeneration:** `/api/v1/packages/search` and `/api/v1/packages/search.csv` with their item types (for example `HostGroupItem`). TASK-113 and TASK-114 had already re-exported `openapi.json` when I regenerated, so G16 for this TEST is against the document as it stands now. TASK-124's regeneration will give no diff unless a manager fix round changes the document again.
- `UserPathsArePrefixed` in `client.ts` still type-checks with the two package paths.
- The existing screens still type-check with the narrower types. `EnrolmentRequests.tsx` takes `kind` as a string, and its fallback branch is now unreachable but harmless. No other file was changed.

## StatusBadge

`LABELS: Record<AgentStatus, string>`, with `AgentStatus = components["schemas"]["AgentItem"]["status"]`:

| Status | Label |
| --- | --- |
| `awaiting_approval` | Awaiting approval |
| `enrolled` | Enrolled |
| `online` | Online |
| `stale` | Stale |
| `offline` | Offline |
| `decommissioned` | Decommissioned |

Removing an entry, or a new enum value in the document, fails `npm run typecheck` (REQ-127 (2), G13 plant). The badge renders a `<span>` text node.

## Hosts (`{ navigate: (route: Route) => void }`)

- `GET /api/v1/agents?limit=50[&cursor=…]`, with paging through `useCursorPages` and `Pager`.
- The table columns are:

  | Column | Shown as |
  | --- | --- |
  | Hostname | a link to `#/hosts/<agent_id>`; a click calls `navigate({name: "host", agentId})` and prevents the default |
  | Status | `StatusBadge` |
  | OS | `os_pretty_name`, or "unknown" when null |
  | Agent version | text |
  | Last heartbeat | `formatTime`; "never" when null |
  | Last inventory | `formatTime`; "never" when null |
  | Tags | comma-joined, or "none" |
  | Runner helpers | comma-joined, or "none" |

- An empty first page shows "No hosts yet.". Refusals go to `ProblemBanner`. A network failure shows "The manager is unavailable. Try again later."
- All values are text nodes. The `href` always starts with `#`, so a hostile `agent_id` cannot turn it into a `javascript:` URL.
- A list answer that arrives after a newer request or after unmount is ignored.

## Checks run (Windows, Node 24.22.0)

- `npm run gen:api`, then `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.

## Notes for the tester (TP-M5-15)

- Mount sends `GET /api/v1/agents?limit=50`. The hostname link's accessible name is the hostname.
- G16: `npm run gen:api` followed by `git diff --exit-code -- web/src/api/` should be empty against the current `manager/openapi.json`.
