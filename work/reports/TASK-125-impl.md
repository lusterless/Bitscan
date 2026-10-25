# TASK-125 IMPL: package name type-ahead and CSV download

Owner: impl-web. REQ-130 (per #32), REQ-131; TS §7.3 (L1223–L1224), §6.3; #84. Depends on TASK-124. Worktree `Bitscan-m5`.

## Files

| File | Change |
| --- | --- |
| `web/src/components/TypeAhead.tsx` (new) | 86 code lines |
| `web/src/app/download.ts` (new) | 32 code lines |
| `web/src/screens/PackageSearch.tsx` | about 40 lines added: the `q` field becomes a `TypeAhead`, plus an "Export CSV" button and its handler |

## TypeAhead (REQ-130, #32 as approved)

- Props: `{ label: string; value: string; onChange: (value: string) => void; onChoose: (name: string) => void }`. It renders the labelled input ("Name contains (q, 3 or more characters)" on the search screen) and, when there are suggestions, `<ul aria-label="Suggestions">` with one button per name.
- **Below 3 characters** (counted as code points, as the server's `q` rule does), nothing is sent and the suggestions are cleared.
- **From 3 characters, 300 ms after the last change**, it sends one `GET /api/v1/packages/search?q=<input>&group_by=package&limit=500`. Each keystroke clears the pending timer, so a quick burst sends one request.
- It offers **at most 10 distinct names** in response order (the server's name order, #83 (b)).
- **Stale answers.** Every change of the input takes a new ticket, and an answer is applied only if its ticket is still the latest. A slower earlier answer that arrives after a later one is ignored. A refusal or network error just clears the suggestions; nothing is shown.
- **Choosing a name** sets `name` to it and clears `q` (PackageSearch's `onChoose`), and closes the list. The user then presses Search.

## CSV download (REQ-131)

- `downloadCsv(query: CsvQuery): Promise<ProblemInfo | null>` calls `GET /api/v1/packages/search.csv` **through the generated client** (`parseAs: "blob"`), so the session middleware adds the bearer header (CHK-M5-351: it is never a plain link).
- On 200 it passes the response Blob, **unchanged**, to `saveBlob(blob, "packages.csv")`. `saveBlob`:
  1. creates an object URL;
  2. creates an `<a download="packages.csv">`, appends it to `document.body`, calls `click()`, and removes it;
  3. **revokes the URL with `setTimeout(…, 0)`**, on the next task, because some browsers read the URL just after `click()`.
- On a refusal it returns the `ProblemInfo`. PackageSearch shows it in `ProblemBanner` with `detail` as text, for example the 400 over the #84 cap (REQ-131 (4)).
- **What is exported:** the query currently on screen, i.e. the last search or the version drill-down, which already carries no `limit` or `cursor`. `limit` and `cursor` are added only to the paged JSON request, never to the stored query, so the CSV request has exactly the visible search's parameters, `group_by` included (REQ-131 (1)).
- The "Export CSV" button appears once a search has run and is disabled while an export is in flight. A network failure shows "The manager is unavailable. Try again later."

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No `fetch` outside the client (G12 CHK plant `fetch(` in `download.ts` would turn lint red), no storage, no HTML rendering, no `style=`.

## Notes for the tester (TP-M5-18)

- Fake timers: the request goes out 300 ms after the last change. For the URL revoke, advance timers by 0 ms (or run pending timers) after the export resolves.
- jsdom has no `URL.createObjectURL` or `URL.revokeObjectURL`; stub both. `HTMLAnchorElement.prototype.click` in jsdom tries to navigate and logs "not implemented"; spy on or stub it.
- `saveBlob` and `CSV_FILE_NAME` are exported for a direct unit test.
