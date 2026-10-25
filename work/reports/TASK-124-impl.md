# TASK-124 IMPL: regenerate the client (package routes) and the package search screen

Owner: impl-web. REQ-129, REQ-136, REQ-132; TS §7.1, §7.3 (L1223); #86. Depends on TASK-113, 114, 117 and 122. Worktree `Bitscan-m5`.

## Files

| File | Change |
| --- | --- |
| `web/src/api/schema.d.ts` | `npm run gen:api` re-run: **no change** since TASK-122. The package routes were already in that regeneration, because TASK-113 and 114 had re-exported first. |
| `web/src/screens/PackageSearch.tsx` (new) | 315 code lines (with the drill-down ruling) |

The size is over the planned 190, mostly the form's controlled selects and the three result tables under Prettier. TASK-125 adds the type-ahead and CSV export to this same file.

## REQ-136

- `/api/v1/packages/search` and `/api/v1/packages/search.csv` are in `paths`.
- `UserPathsArePrefixed` type-checks.
- The screen calls the search route with the generated query type (`operations["search_packages_api_v1_packages_search_get"]["parameters"]["query"]`), so a parameter rename in the document fails `npm run typecheck`.

## Behaviour (props `{ navigate: (route: Route) => void }`)

- **Form** (`<form aria-label="Search packages">`). Text fields, by label:

  | Label | Parameter |
  | --- | --- |
  | Name contains (q, 3 or more characters) | `q` |
  | Exact name | `name` |
  | Version | `version` |
  | Architecture | `arch` |
  | OS (for example ubuntu:24.04) | `os` |
  | Host tag | `tag` |
  | Hostname contains | `host` |
  | Agent id | `agent_id` |

  Selects:
  - "Version comparison": "exact version" (none), or `lt`, `le`, `eq`, `ge`, `gt`. **Disabled while Version is empty**, and `version_op` is never sent without `version`.
  - "Status": installed (default) or any.
  - "View": "by package and version" (`group_by=package`, the default) or "by host" (`group_by=host`).
- **What is sent** (REQ-129 (1)): `group_by`, plus only the text fields that are filled, plus `version_op` (when chosen and a version is set), plus `status=any` only when chosen (`installed` is the server default, so it is not sent), plus `limit=50` and the page `cursor`. Text is sent as typed. The server validates and answers 400 for a 2-character `q` and similar; a 400 shows its `detail` through `ProblemBanner`.
- **`q` and `name` together** show "Use either “Name contains” or “Exact name”, not both." and nothing is sent.
- **`group_by=package` answer** (#86 (b)): the rows are nested by name in response order. Each name is a `<section aria-label={name}>` with an `<h2>` and a table of Version (a button), Architecture and Hosts (`host_count`).
- **Version click** (#86 (a), plus the lead's ruling below) requests `name`, `version`, `arch`, plus whichever of the search's `status`, `os`, `tag`, `host` and `agent_id` were sent (+ `limit`), **without `group_by`**. The search's `q` and `version_op` are not carried, because the exact `name` and `version` replace them. The answer shows as a table "Hosts with this version" (Host link, Name, Version, Architecture, Status), and a "Back to results" button re-runs the last search from page 1.
- **Host click**: every hostname is a link to `#/hosts/<agent_id>`; a click calls `navigate({name: "host", agentId})`.
- **`group_by=host` answer**: table "Hosts" (Host link, Matching packages = `package_count`).
- **Paging**: `useCursorPages` and `Pager` for whichever query is on screen. A new search or drill-down starts at page 1.
- Empty results show "No packages found.". A network failure shows "The manager is unavailable. Try again later.". Answers that arrive after a newer request or after unmount are ignored.
- The three item shapes are told apart by their keys (`host_count`, `package_count`, or neither) with type guards; there are no casts.
- Every API value is a text node (REQ-129 (4)).

## Lead ruling (2026-10-25): the drill-down keeps the active filters (#86 (a))

REQ-129 (3) says a version click requests `name`, `version`, `arch`. With only those three, a search with `status=any`, or one filtered by `os`, `tag` or `host`, could give a host list that disagrees with the group's `host_count`. **The lead ruled that the active filters `status`, `os`, `tag` and `host` are carried into the drill-down** (same route, same filters), so the list always matches the count.

**`agent_id` is carried too.** The ruling's list did not name it, but it narrows `host_count` the same way, and the ruling's stated aim ("the host list always matches the group's `host_count`") needs it. I told the lead; dropping it is one entry in `CARRIED`.

The tester's REQ-129 (3) check is affected:
- A version click after a plain search sends exactly `name`, `version`, `arch` (+ `limit`).
- After a filtered search, it also sends the filters that search sent.

Implementation: `drillQuery(search, group)`, about 20 lines.

## Checks run (Windows, Node 24.22.0)

- `npm run gen:api` (no diff), `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No HTML rendering, no `style=`, no `fetch`, no storage. Field state uses a typed variable key (`filters[key]` and `{ ...filters, [key]: value }` with `key: TextKey`), not a built key.

## Notes for the tester (TP-M5-17)

- Nothing is requested until "Search" is pressed.
- A version button's accessible name is the version string, inside the section named after the package.
- G16: `npm run gen:api`, then `git diff --exit-code -- web/src/api/` is empty against the current `manager/openapi.json`.
