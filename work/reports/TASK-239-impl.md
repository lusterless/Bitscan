# TASK-239 IMPL: web client regeneration, `Score`, `ResultBadge`, results CSV download

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`, on `69baeaa` (TASK-232). Not committed.
REQ: REQ-273, REQ-280 (1), REQ-281 (1), (3), REQ-284. Open items: #149 (score display), #146 (d) (file name). Spec: TS §4.5 L603–L604, TS §4.4 L585, TS §6.3.

## What changed

| File | Change |
| --- | --- |
| `web/src/api/schema.d.ts` | Regenerated with `npm run gen:api` from the committed `manager/openapi.json` (TASK-232). Adds the six M11 operations and `ScanItem`, `ScanDetailItem`, `HostSummary`, `ScanResultItem`, `ScanResultItemWithOutput`, `ReevalItem`. Not hand-edited. Regenerating a second time gives a byte-identical file (G16). |
| `web/src/format.ts` | `formatScore(score: number \| null): string` and `formatErrorCount(errors: number): string`. |
| `web/src/components/Score.tsx` (new) | `<Score score={number \| null} errors={number} />`. |
| `web/src/components/ResultBadge.tsx` (new) | `<ResultBadge result={Verdict \| null} originalResult={Verdict \| null} reevaluated={boolean} />`, plus exports `Verdict` and `NOT_RUN_LABEL`. |
| `web/src/app/download.ts` | Adds a shared `saveCsv` step (private), `downloadResultsCsv(scanId, query)`, `resultsCsvFileName(scanId)` and the `ResultsCsvQuery` type. The M5 exports `downloadCsv`, `saveBlob`, `CSV_FILE_NAME` and `CsvQuery` keep their signatures and behaviour; `downloadCsv` now goes through `saveCsv` too. |

No file outside the task's list was changed. No new dependency; `npm ci --ignore-scripts` from the lockfile.

## Behaviour (what the tests should expect)

**`formatScore`** (#149): a percentage with one decimal, **rounded down**, with a space before `%`. The tenths are built from integers (`Math.floor(score * 1000)`), never `toFixed`, which would round up.
- `0.75` → `"75.0 %"`, `0.9996` → `"99.9 %"`, `1` → `"100.0 %"`, `0` → `"0.0 %"`, `1/3` → `"33.3 %"`.
- `null` (and a non-finite number) → `"n/a"`.
- The plain floor matched the exact integer floor for every `k / n` with `n` up to 5,000, and on a sample up to 40,000, so the code adds no epsilon.

**`formatErrorCount`**: `0` → `"0 errors"`, `1` → `"1 error"`, `5` → `"5 errors"`.

**`Score`**:
- Renders `<span class="score"><span class="score-value">75.0 %</span> <span class="score-errors muted">5 errors</span></span>`.
- The error count is always shown beside the score, including next to "n/a" (TS §4.5 L604).
- *Not run* counts are not part of this component (#149: they get their own column, TASK-247).

**`ResultBadge`**:
- PASS is shown as `badge badge-success`, FAIL as `badge badge-danger` and ERROR as `badge badge-warning`.
- A null `result` is the text `Not run` (`badge badge-neutral`).
- When `reevaluated` is true and `originalResult` is not null, the original verdict appears beside the current one as `original <badge>` inside `span.result-original`. This happens **even when the two verdicts are equal**: `.claude/rules/web-ui.md` says "Show both the current verdict and `original_result` when a result has been re-evaluated". CHK-M11-262's wording "when it differs" is narrower than that rule. The screens pass `reevaluated={item.reevaluated_at !== null}`.
- When `reevaluated` is false, only one badge appears.

**`downloadResultsCsv(scanId, { status?, agent_id? })`**:
- Calls `api.GET("/api/v1/scans/{id}/results.csv", { params: { path: { id }, query }, parseAs: "blob" })`, so the bearer header goes through the client middleware.
- The query is passed through unchanged (openapi-fetch drops `undefined` and `null` values), with no `limit` or `cursor`.
- On success it saves the body unchanged through `saveBlob` as `scan-<id lower-cased>-results.csv` (the #146 (d) name) and returns `null`.
- On a refusal it saves nothing and returns `toProblem(...)`: for example the 400 "narrow the filters" detail, or a 401, which ends the session through the existing middleware.
- The file name is built from the scan id rather than parsed from `Content-Disposition`. This is the same approach as M5's `packages.csv`, and it means a header value never becomes a file name.

All values render as React text nodes; there is no `dangerouslySetInnerHTML` or `innerHTML`.

## How to run (from `web/`, Node 24)

```sh
NODE_EXTRA_CA_CERTS=<CA bundle that trusts Zscaler> npm ci --ignore-scripts
npm run gen:api && git diff --exit-code -- src/api/schema.d.ts   # G16
npm run lint          # G12: passed, 0 warnings
npm run typecheck     # G13: passed
npm run format:check  # G14: passed (whole tree)
```

I ran none of the vitest suites (tester's job). The existing `src/app/download.test.ts` (M5) imports only the unchanged exports and should still pass. Still to test: TP-M11-07, which is `Score.test.tsx`, `ResultBadge.test.tsx` and `download.test.ts` (extended), CHK-M11-260 to -263.

## Builder checklist

- Items 1–22 are manager, agent, SQL or build items and do not apply to this web-only change.
- Item 11 (no output in logs): the change adds no logging.
- Item 12 (no client input in problem text): problem text comes only from `toProblem`.
- Item 13 (OpenAPI): not touched; the client is regenerated from the committed document.
