# TASK-256 IMPL: shared scan pieces (`ScanTable`, `TargetPicker`)

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`, on `42d0692`. Not committed. W3 batch with TASK-246 to 250.
REQ: REQ-279, REQ-282. Open items: #154 (a), (d), #68, #122 (b).
This task was split out of TASK-246 for size, approved by the lead on 2026-11-08, under the tasks.md L2598 growth rule. TASK-247, 249 and 250 depend on it.

## Files (both new)

| File | Exports |
| --- | --- |
| `web/src/components/ScanTable.tsx` | `ScanLinks` (type), `ScanState` (type), `SCAN_STATES`, `scanStateLabel(state)`, `ScanStateBadge`, `ScanTable` |
| `web/src/components/TargetPicker.tsx` | `Target`, `TargetValue` (types), `ALL_HOSTS`, `toTarget(value)`, `fromTarget(stored)`, `describeTarget(stored)`, `TargetPicker` |

## `ScanLinks` (TASK-251 must build this)

The hash routes are TASK-251's (W4), so the W3 screens can't name the new `Route` variants. Each one takes `links: ScanLinks` instead:

```ts
interface ScanLinks {
  scansHref: string;                       // the Scans list
  runScanHref: string;                     // Run scan, no profile chosen
  scanHref: (scanId: string) => string;    // a scan's detail
  resultsHref: (scanId: string) => string; // a scan's results
  openScan: (scanId: string) => void;      // go to a scan's detail (after Run scan's 202)
}
```

TASK-251 builds each href with `formatHash` on its new routes, and `openScan` with `navigate`. The links are plain `<a href>` hash links, with no `onClick`.

## Behaviour

**`ScanTable`**:
- Columns: Created (links to `scanHref(scan_id)`), Profile, Version, Trigger, Target, State, Finished.
- Target is shown as "All hosts / Tags / Chosen hosts (N hosts)", where N is `resolved_count`.
- Every value is a text node.

**`ScanStateBadge`**: a `Record` over the generated six-state enum, so a new state without a label fails typecheck.

**`toTarget(value)`** returns the #122 (b) body, or a fixed error text:
- `all` → `{all: true}`.
- `tags` → `{tags}`. The typed text is split on commas and white space without a regular expression, each tag is kept once in typed order, and the #68 rule applies (1–32 tags, each 1–64 characters from `A-Za-z0-9._:-`). Otherwise the text is "Tags are 1 to 32 names …".
- `agents` → `{agents}` for 1–10,000 chosen ids. Otherwise "Choose at least one host." or "Choose at most 10,000 hosts.".

**`fromTarget` / `describeTarget`** read a stored target object (`{[key]: unknown}`) defensively:
- They check for string arrays only.
- `describeTarget` gives "All hosts", "Hosts with any of the tags: a, b", "N chosen hosts", or "Unknown target".

**`TargetPicker`**:
- Three radios: "All hosts", "Hosts with any of these tags", "These hosts".
- "Tags" shows a text field.
- "These hosts" shows a host chooser: `GET /api/v1/agents?limit=50`, paged with `Pager`, a checkbox per host showing its hostname and status badge. The choice survives paging, and the legend shows "Hosts (N chosen)".

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` all pass. I ran no vitest suites (tester's job).
