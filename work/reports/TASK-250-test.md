# TASK-250 TEST: Host page scan history (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-250-impl.md`). Shared batch evidence is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-283 (1), REQ-284. Spec: TS §6.2 L1113; #145 (c).

## Tests

| File | Result |
| --- | --- |
| `web/src/screens/HostScans.test.tsx` (new) | **8/8** |
| `web/src/screens/HostDetail.test.tsx` (existing, unchanged) | **9/9** |
| `web/src/app/App.test.tsx` "CHK-M11-270 the host page in the shell" (after TASK-251 wired `scanLinks`) | PASS |

## Acceptance criteria

**REQ-283 (1): CHK-M11-270 PASS.**
- Rows come from `GET /agents/{id}/scans` with the bearer, and each row links to `scanHref(scan_id)`.
- Paging is forward and back by the opaque cursor. The fake server pages by 2 whatever the limit, so paging is always exercised; the limit itself is checked to be 1–500.
- "No scans of this host yet." shows for an empty list, with no table.
- A 404 shows its banner with the detail. A network failure shows "The manager is unavailable. Try again later.".
- On HostDetail, `scanLinks` given shows the region with one request. Without it there is no region and no request, and the existing HostDetail tests pass unchanged. In the shell, the host page requests the history and links to `#/scans/<uuid>`.

**CHK-M11-272: PASS.** `<script>` and `onerror` policy names render as text.

## Plants

CHK-M11-375b, `dangerouslySetInnerHTML` for the policy name in the shared `ScanTable`: lint exit 1, plus red in `HostScans.test.tsx`, `Scans.test.tsx` and `ScanTable.test.tsx`.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-270 | `npx vitest run src/screens/HostScans.test.tsx src/screens/HostDetail.test.tsx` | PASS | 8/8 and 9/9 (existing HostDetail unchanged) |
| CHK-M11-272 (host scans) | the same | PASS | plain-text row green |
