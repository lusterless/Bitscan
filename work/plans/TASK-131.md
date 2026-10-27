# TASK-131: host-list cursors carry only ids (#89)

REQ-143. Answer used: #89 (recommended in M5 planning, accepted with the M5 breakdown: "cursors carry the row's id and the route looks the sort values up, as the search does"; lead to schedule it, M5 or M6). Files: `bm/api/user/agents.py`, `bm/services/agents/fleet.py`, `bm/repositories/agents.py`, `bm/repositories/inventory.py`. No migration, no index, no OpenAPI change.

## Problem

`GET /api/v1/agents` puts `[hostname, agent_id]` in its cursor and `GET /api/v1/agents/{id}/packages` puts `[name, architecture, version]` in its cursor (`api/user/agents.py` L182, L236). The M2 machinery caps a cursor at 512 characters and writes JSON with `ensure_ascii`, and the M3 decoder allows 255 characters of any storable text in each of those fields. A long or non-ASCII value on a page boundary (one hostile agent is enough) makes the next page answer 400, so later hosts or packages can no longer be paged to.

## Approach

Keep the order and the page shapes exactly (#68: hosts by `hostname`, `agent_id`; packages by `name`, `architecture`, `version::debversion`, `version`). Change only what the cursor holds and how the anchor is found.

| Route | Cursor key (inside the existing signed, scoped cursor) | Anchor lookup |
| --- | --- | --- |
| `/agents` | `[agent_id]` (lowercase hyphenated UUID string) | `SELECT hostname, agent_id FROM agent WHERE agent_id = %s` |
| `/agents/{id}/packages` | `[package_id]` (JSON integer) | `SELECT name, architecture, version FROM package WHERE package_id = %s` |

- The anchor is looked up in the same transaction as the page query (one statement with a CTE, or two statements in the route's existing transaction). If the anchor row does not exist, the repository raises the existing M5 `AnchorGone` (`bm/repositories/packages.py`), and the route answers 400 `invalid_request` with `detail` "Invalid request: query.cursor", as `/packages/search` does.
- The package anchor comes from `package`, not from `agent_package`: if the agent no longer has that package (a new inventory between two page loads) the sort values still exist and paging continues past them; only a `package` row pruned by retention (M11) makes it 400.
- The scope strings stay `SCOPE` and `agent_packages:{agent_id}`, so a package cursor from another agent's list still fails the scope check (400).
- The cursor is built from the last **row** (which has `agent_id` and `package_id`), not from the response item, so no field is added to `AgentItem` or `AgentPackageItem`.
- `_cursor()` in the route accepts exactly one element of the right JSON type (string UUID for hosts, non-negative integer for packages); anything else is 400.
- SQL: fixed text with `%s` placeholders only (ruff S608). The comparison keeps the M3 form, for example `(p.name, p.architecture, p.version::debversion, p.version) > (a.name, a.architecture, a.version::debversion, a.version)` against the anchor row.

## Signatures (indicative)

```python
# repositories/agents.py
def list_page(self, limit: int, after_id: UUID | None) -> list[AgentRow]: ...
# repositories/inventory.py
def package_page(self, agent_id: UUID, limit: int | None, after_package_id: int | None) -> list[AgentPackageRow]: ...
# services/agents/fleet.py (Protocols updated to match)
def list_agents(store: AgentStore, limit: int, after_id: UUID | None) -> list[AgentRow]: ...
def agent_packages(agents: AgentStore, inventory: InventoryStore, agent_id: UUID, limit: int, after_package_id: int | None) -> list[AgentPackageRow] | None: ...
```

## Edge cases the tests must cover (TP-M6-07)

- A 255-character non-ASCII hostname and a 255-character non-ASCII package name, each the last row of a page.
- Two hosts with the same hostname (the `agent_id` tie-break) on a page boundary.
- `1.0` and `1.0-0` (equal in Debian order, different as text) on a page boundary.
- A package removed from the agent between two page loads (paging continues), and a `package` row deleted (as `bitscan_retention`, simulating the M11 prune): 400.
- A cursor with two elements (the old form), a string package id, a negative id: 400.
- Every returned cursor at most 512 characters.

## Not changed

Every other cursor already carries an id (`audit_id`, `token_id`, `request_id`, `user_id`) or, for the package search, id anchors (M5). The `next_cursor: null` rule on the last page is unchanged.
