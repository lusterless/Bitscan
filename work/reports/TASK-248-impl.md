# TASK-248 IMPL: Results screen

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed. W3 batch.
REQ: REQ-281, REQ-284. Open items: #144, #146. Spec: TS §4.5 L603, §4.4 L585, §6.2 L1123, §6.3 L1143.
Uses TASK-239 (`ResultBadge`, `downloadResultsCsv`) and TASK-256 (`ScanLinks`).

## File

`web/src/screens/ScanResults.tsx` (new): `ScanResults({ scanId, links })`. Mount it with `key={scanId}`.

## Behaviour

**Host choices.** `GET /api/v1/scans/{id}` is used only to fill the Host filter (`hosts[]`: hostname as the label, `agent_id` as the value). If it fails, the filter offers just "All".

**Results.** `GET /api/v1/scans/{id}/results` with `limit=50`, the cursor, and the filters.

**Filters.** Two selects, applied on change; each change resets paging:
- Status: All / PASS / FAIL / ERROR / Not run, sending `status=PASS|FAIL|ERROR|NOT_RUN`.
- Host: All, or `agent_id`.
- "All" sends no parameter.

**Columns:**

| Column | Content |
| --- | --- |
| Host | hostname |
| Plugin | `plugin_name` |
| Result | `ResultBadge`, see below |
| Detail | `eval_detail`, plus "Original: <original_eval_detail>" when re-evaluated |
| Exit code | exit code |
| Flags | retry / timed out / truncated, or "none" |
| Finished | finish time |
| Output | only when shown, see below |

**Result column.** `ResultBadge` with `result`, `original_result` and `reevaluated = reevaluated_at !== null`:
- Both verdicts show when the result was re-evaluated.
- A null result shows "Not run".

**Output column:**
- It is present only when at least one item on the page has a `stdout` key (`"stdout" in item`).
- Viewers' items have no such key, so they get no column and no output.
- Each row's cell is a `<details>` with stdout and stderr, each as a text node in a `<pre>`.
- A null value shows as empty.

**Export CSV.** `downloadResultsCsv(scanId, <current filters>)` from TASK-239:
- It calls `/api/v1/scans/{id}/results.csv` through the generated client with the same `status` / `agent_id`, and no cursor.
- It saves the file as `scan-<id>-results.csv`.
- A refusal shows in the banner, for example the 400 "narrow the filters".

**States.** "Loading.", "No results.", the banner, and "The manager is unavailable…".

All values are text nodes; there is no `dangerouslySetInnerHTML` or `innerHTML`.

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. No vitest run.
