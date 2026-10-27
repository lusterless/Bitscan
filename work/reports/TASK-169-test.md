# TASK-169 TEST: PASS

Tester: tester-m7-web, 2026-10-27. REQ-181 (1) and (4) for the list; #9; PD-34 (a); TS §4.3 L546-L548, §6.2 (`GET /policies`, every role), §6.3 L1134 (cursor pages) and L1141 (plain text); REQ-126 with the 503 rule. File under test: `web/src/screens/Profiles.tsx`. New test file: `web/src/screens/Profiles.test.tsx`, 25 tests, using the M5 harness (every request is recorded and none leaves the test).

## Coverage

- **REQ-181 (1), columns.** The headers are exactly Name, Description, Status, Family, Version, Plugins and Updated. Each cell matches the fixture, and the time shows as `YYYY-MM-DD HH:MM:SS UTC`. "(set by an admin)" follows `status_overridden` only, not `file_status`. The empty state says "No profiles." and Next is disabled. "Loading." shows until the answer arrives.
- **Hostile text.** These values render literally, with and without `onOpen`:
  - name `<script>alert(1)</script>`, description `<img src=x onerror=alert(1)>`, family `<b>x</b>`;
  - an RTL override (U+202E) in the name and family;
  - a 16,384-character name and description.

  The container has no `script`, `img`, `b`, `iframe`, `[onerror]` or `[dir]` element. The HTML holds `&lt;script&gt;`. A hostile problem `detail` shows as text in the banner.
- **REQ-181 (4), paging.**
  - With 51 policies: page 1 is one GET with `{limit: 50}`, and Next sends `cursor` from `next_cursor`. Each policy shows once (51 distinct). Next is disabled on the last page. Previous sends a request with no cursor and shows page 1 again.
  - With a server page size of 2: three pages, the cursors are null, `p-2` and `p-4`, and there are exactly 3 requests.
  - A stale answer that arrives after the filter changed is dropped.
- **#9 filter.**
  - The options are exactly `all`, `enabled` and `disabled`.
  - From page 2, `disabled` sends `{limit: 50, status: disabled}` with no cursor and shows "Page 1". Paging inside the filter keeps the status.
  - `enabled` resets paging the same way. `all` sends no `status`.
  - `deleted` is never sent, even when a forged `<option value="deleted">` is injected and chosen (it maps to `all`).
  - Only `GET /api/v1/policies` is ever called.
- **Every role.** Viewer, operator and admin each send exactly one request, `GET /api/v1/policies?limit=50`, with `Bearer <their bsu_>`, and see the list.
- **Errors through `problems.ts`.**
  - The banner shows the fixed text for a 401, a 403 `forbidden`, a 503 with `Retry-After: 10` ("not ready ... 10 seconds"), a 503 without the header (the generic text) and a 500. No table is shown.
  - A rejected fetch shows the "unavailable" callout.
  - A later success clears the banner.
- **`onOpen`.** Without it, the name is plain text in a `TD` and there is no button. With it, a click calls `onOpen(102)` once and sends no request.

## Runs (Linux container, Node 22, from `web/`)

| Run | Command | Count |
| --- | --- | --- |
| r1 | `npx vitest run src/screens/Profiles.test.tsx` | 25/25 passed, 0 failed, 0 skipped |
| r2 | `npx vitest run src/app/problems.test.ts src/api/client.test.ts src/screens/Profiles.test.tsx` (scratch copy, control) | 115/115 passed |
| gates | `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm test` | clean; full suite 401/401 passed, 0 failed, 0 skipped |

## Report rows (for `tests/m7/report.md`)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-310 (REQ-181 (1) list) | CODE | L | r1 | PASS | columns, labels, override note, empty and loading states, hostile text (see Coverage) | 2026-10-27 |
| CHK-M7-310 (REQ-181 (4) list) | CODE | L | r1 | PASS | 51 at 50 and 5 at 2 each show every policy once; one GET per page; stale answer dropped | 2026-10-27 |
| CHK-M7-310 (#9, PD-34 (a)) | CODE | L | r1 | PASS | the filter resets to page 1 and never sends `deleted`; three roles each send one identical request | 2026-10-27 |
| CHK-M7-319 (G12-G15) | CODE | L | gates | PASS | lint, typecheck, Prettier and vitest are clean; 401/401 | 2026-10-27 |

## Plants (scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/tweb/web`): 11/11 red

| Plant in `Profiles.tsx` | Result |
| --- | --- |
| The description is rendered with `dangerouslySetInnerHTML` | red, 2 failed |
| The filter passes any value through (a forged `deleted` is sent) | red, 1 failed |
| `pages.reset()` is removed from the filter change | red, 1 failed |
| `all` sends `status=all` | red, 13 failed |
| The stale-answer `active` guard is removed | red, 1 failed |
| The override label is removed | red, 2 failed |
| The family is shown in the description column | red, 3 failed |
| The cursor is never sent | red, 3 failed |
| The network-failure callout is removed | red, 1 failed |
| `ProblemBanner` is removed | red, 7 failed |
| The problem is not cleared after a later success | red, 1 failed |

## Findings

None.
- The *Deleted* state, the plugin order and the admin actions (REQ-181 (1) detail half, (2) and (3)) belong to TASK-170 and are not tested here.
- I did not edit `tests/m7/report.md`, because it is owned by tester-m7. The rows above are ready to paste.
