# TASK-247 TEST: Scan detail screen (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-247-impl.md`). Shared batch evidence (full run 741/741, G12–G16, the throwaway copy, the flake note) is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-280 (1)–(3), REQ-284. Spec: TS §4.4 L581–L585, §4.5 L603–L604, §6.2 L1086, L1122, L1124, L1125; #145 (b), #147 (c), #149. **Main's ruling 2026-11-08 on REQ-280 (3):** reading (a). 403 `totp_session_required` offers Sign in again; 503 `audit_sink_unavailable` shows its fixed text with **no** sign-in button; neither has an API-token field or sends another request.

## Tests

`web/src/screens/ScanDetail.test.tsx` (new): **19/19**.

## Acceptance criteria

**REQ-280 (1): CHK-M11-267 PASS.**
- The summary fields are read by label: profile, version, trigger, schedule, requested by ("system" when null), target as requested, hosts targeted, created and "not finished".
- The state shown is `scan.state` as returned: a `cancelled` scan with completed jobs shows Cancelled.
- Host rows follow the API order. Jobs read as "expired, retry running". Passed, failed and not-run counts are shown, and the score has the errors beside it: "75.0 % 5 errors", "n/a 1 error", "99.9 % 0 errors".
- The host name links to the host route; Results and Back link through `ScanLinks`. No hosts gives its empty text, 404 gives "Scan not found.", other refusals give the banner, and a network failure says the manager is unavailable.

**REQ-280 (2): PASS.** On an unfinished scan a viewer sees no button, an operator sees Cancel scan only, and an admin sees both. On a finished scan, Cancel is not offered (impl choice; a finished scan has nothing to cancel) and Re-evaluate still is.

**REQ-280 (3): PASS.**
- Each action asks to confirm, and Cancel inside the question sends nothing.
- A Re-evaluate 200 sends one POST with an empty body and the bearer, shows "Re-evaluated against version 4: 17 verdicts added.", and reloads: the requests are GET, POST, GET, and the profile version updates.
- A Cancel 200 shows the count and reloads.
- 403 `totp_session_required` shows its text and Sign in again. There is no `input` or `textarea`, no "API token" text, the session token never reaches storage, the console or the URL (`watchSecrets`), and the only requests are GET and POST.
- 503 shows its fixed text with no Sign in again, no input and no other request.
- A 409 for a deleted policy shows its detail. A 403 `forbidden` on Cancel shows the banner and sends no reload.

**REQ-284 (2), CHK-M11-272: PASS.** A `<script>` host name, an `onerror` profile name and a `<script>` tag render as text.

## Plants (red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-361 | `fetch(` for re-evaluate | **G12 lint exit 1**, plus 4 tests |
| CHK-M11-362 (a) | an API-token field after a 403 | the 403 row |
| CHK-M11-362 (b) | `sessionStorage.setItem` in the action | **G12 lint exit 1**. No test turned red: the screens cannot reach the token (`SessionView` has none), so the storage half is G12's, as the mutation table names |
| CHK-M11-375a | `dangerouslySetInnerHTML` host name | lint exit 1, plus the plain-text row |
| CHK-M11-434 | Cancel offered to viewers | the viewer row |
| CHK-M11-436 | a reload after a refusal | the 403, 503, 409 and forbidden rows (4) |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-267 | `npx vitest run src/screens/ScanDetail.test.tsx` | PASS | 19/19 |
| CHK-M11-272 (scan detail) | the same | PASS | plain-text row green |
| CHK-M11-361 | plant | PASS (red as required) | eslint exit 1 on the `fetch` line |
| CHK-M11-362 | plants (a) and (b) | PASS (red as required) | (a) 1 failed / 19; (b) eslint exit 1 (storage ban) |
| CHK-M11-375 (detail) | plant | PASS (red as required) | eslint exit 1; 1 failed / 19 |
| CHK-M11-434, -436 | plants | PASS (red as required) | 1 failed / 19; 4 failed / 19 |
