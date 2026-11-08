# TASK-248 TEST: Results screen (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-248-impl.md`). Shared batch evidence is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-281 (1)–(3), REQ-284. Spec: TS §4.5 L603, §4.4 L585, §6.2 L1083, L1123, §6.3 L1143; #144 (b), (d), (e), #146 (d); `.claude/rules/web-ui.md` (output only when the API returns it; both verdicts when re-evaluated).

## Tests

`web/src/screens/ScanResults.test.tsx` (new): **14/14**.

## Acceptance criteria

**REQ-281 (1): CHK-M11-268 PASS.**
- A re-evaluated row shows PASS and then the original FAIL, with "original".
- A row re-evaluated to the same verdict still shows both, and its detail shows "Original: …".
- A row that was never re-evaluated shows one badge, and a null result shows "Not run".

**REQ-281 (2): PASS.**
- Viewer items, which have no `stdout` key, give exactly 7 columns with no Output header and no `pre` or `details` element.
- Operator items add an Output column. stdout and stderr are each a single text node in a `<pre>`, LF and CRLF kept. A null shows an empty `<pre>`, not "null".
- A stdout `<img src=x onerror=alert(1)>` and a `<script>` stderr render as text.

**REQ-281 (3): PASS.**
- Export calls `/api/v1/scans/{id}/results.csv` through the client, with the bearer and exactly the current `status` and `agent_id`. It saves one Blob as `scan-<id>-results.csv`.
- Without filters it sends no query.
- The 100,000-row 400 shows its detail and saves nothing.

**Filters and paging: PASS.**
- Status sends PASS, FAIL, ERROR or NOT_RUN, and "All" sends nothing.
- Host choices come from the detail's hosts (a `<script>` host name shows as an option label in text).
- 51 results page with `cursor`, and a filter change returns to page 1.
- The empty state and the 404 banner both appear.

**REQ-284 (2), CHK-M11-272: PASS.** A `<script>` host name, an `onerror` plugin name and an eval detail render as text.

## Plants (red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-360 | `dangerouslySetInnerHTML` for stdout | **G12 lint exit 1**, plus the `onerror` stdout row |
| CHK-M11-365 (screen) | `reevaluated` always false | 2 verdict rows |
| CHK-M11-376 | Output column for every page | the viewer no-output row |
| CHK-M11-375d | `dangerouslySetInnerHTML` plugin name | lint exit 1, plus the plain-text row |
| CHK-M11-437 | export without the filters | the export row |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-268 | `npx vitest run src/screens/ScanResults.test.tsx` | PASS | 14/14 |
| CHK-M11-272 (results) | the same | PASS | plain-text rows green |
| CHK-M11-360 | plant | PASS (red as required) | eslint exit 1; 1 failed / 14 |
| CHK-M11-365 (screen half) | plant | PASS (red as required) | 2 failed / 14 |
| CHK-M11-375 (results), -376, -437 | plants | PASS (red as required) | eslint exit 1 + 1 failed; 1 failed; 1 failed (each / 14) |
