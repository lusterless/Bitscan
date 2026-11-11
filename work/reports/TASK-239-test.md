# TASK-239 TEST: web client regeneration, `Score`, `ResultBadge`, results CSV download (TP-M11-07, W2 web batch)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11`, branch `m11-results` (on `69baeaa`), uncommitted IMPL as handed off in `work/reports/TASK-239-impl.md`. Where: L (Windows 11, Git Bash, Node v24.22.0), from `web/`. `node_modules` installed in the worktree with `npm ci --offline` (its lock is byte-identical to main's).
REQ: REQ-273, REQ-280 (1), REQ-281 (1) and (3), REQ-284. Spec: TS §4.5 L603–L604, §4.4 L585, §6.3 L1143–L1144, §8.2 L1268; #149, #146 (d); `.claude/rules/web-ui.md` L15. The tests were derived from the criteria and the plan rows (CHK-M11-261 to -264, refined before any web code was read). The code was read only to bind the prop names.

## Tests written (tester-owned)

| File | Tests | Covers |
| --- | --- | --- |
| `web/src/components/Score.test.tsx` (new) | 26 | CHK-M11-261 |
| `web/src/components/ResultBadge.test.tsx` (new) | 10 | CHK-M11-262 |
| `web/src/app/download.test.ts` (extended; the 5 M5 tests kept unchanged) | 15 (5 M5 + 10 M11) | CHK-M11-263, -264 |

## Runs

| Run | Command (from `web/`) | Result |
| --- | --- | --- |
| New tests | `npx vitest run src/components/Score.test.tsx src/components/ResultBadge.test.tsx src/app/download.test.ts` | **51/51 passed**, 0 failed, 0 errors, 0 skipped |
| Affected existing tests (importers of `format.ts` / `download.ts`, plus `App.test.tsx`) | `npx vitest run src/components/components.test.tsx src/screens/{EnrolmentRequests,EnrolmentTokens,HostDetail,Hosts,Imports,PackageSearch,ProfileDetail,Profiles,Rebuild}.test.tsx src/app/App.test.tsx` | **197/197 passed**, 0 failed, 0 errors, 0 skipped |
| G12 | `npm run lint` | exit 0, 0 warnings (test files included) |
| G13 | `npm run typecheck` | exit 0 |
| G14 | `npm run format:check` | exit 0, "All matched files use Prettier code style!" |
| G16 | `openapi-typescript ../manager/openapi.json` to a temp file, then `prettier --stdin-filepath src/api/schema.d.ts`, then `cmp` with `src/api/schema.d.ts` (the tree is never written) | identical: sha256 `e7ffd8c4…c30a` both; `openapi.json` sha256 `126c5429…a9a2` |
| REQ-273 | grep of the six paths in `schema.d.ts` | `/scans`, `/scans/{id}`, `/scans/{id}/results`, `/scans/{id}/results.csv`, `/agents/{id}/scans`, `/scans/{id}/reevaluate`: 1 each |
| Pre-change baseline (for comparison) | `npx vitest run` (whole suite, before my files) | 516/516 passed on two warm runs. The first cold run straight after `npm ci` reported "2 files, 28 passed, 19 errors", and the second hit one `App.test.tsx` 5 s timeout. Both were cold-cache or machine-load effects that did not recur. Recorded as a flake risk for the wave-end full run, not hidden. |

## Plants (throwaway copy `%TEMP%\m11w-mut-239`, node_modules by junction; clean copy 51/51 first; copy removed afterwards, worktree unchanged)

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M11-363 | `formatScore(null)` returns `"0.0 %"` | **red**: 3 failed / 26 (incl. "null shows n/a, never a percentage") |
| CHK-M11-364 | `Math.round(score * 1000)` (round to nearest) | **red**: 6 failed / 26 (0.9996, 2/3, 0.99999, the k/n sweep) |
| CHK-M11-377 | `Math.floor(score * 100 * 10)` | **red**: 7 failed / 26 (29/100, 57/100, 58/100, 23/40, 29/50, 46/80, sweep) |
| CHK-M11-365 (W2 half) | `ResultBadge` never shows the original | **red**: 4 failed / 10 |
| CHK-M11-365 variant | original shown only when it differs | **red**: 2 failed / 10 (the equal-verdicts row, as main confirmed on 2026-11-08) |
| CHK-M11-378 | results export with `parseAs: "text"` | **red**: 1 failed / 15, "expected '…' to be an instance of Blob" |
| G16 | hand edit to `schema.d.ts` in the copy | **red**: `cmp` exit 1 |

## Acceptance criteria coverage

- **G16 green, typecheck passes:** CHK-M11-260 PASS.
- **REQ-280 (1) for `Score`:** CHK-M11-261 PASS. The test checks 0.75 + 5 → "75.0 % 5 errors", null → "n/a", 0.9996 → "99.9 %", 1.0 → "100.0 %", and "1 error" / "0 errors". It also checks the rounded-down boundaries and the exact-k/n sweep up to n = 400.
- **REQ-281 (1) for `ResultBadge`:** CHK-M11-262 PASS. A verdict that was never re-evaluated shows once. null shows "Not run". A re-evaluated result shows both verdicts, current first, including when they are equal.
- **CSV download through the generated client with `parseAs: "blob"`:** CHK-M11-263 and -264 PASS. The test checks one GET with the bearer and exactly the filters, and the body saved as a Blob byte for byte as `scan-<id lower-case>-results.csv`. It also checks that a hostile `Content-Disposition` is ignored, and that 400, 404 and 401 save nothing, with the 401 ending the session.

## Notes (no finding blocks)

- The file name is built from the scan id, not parsed from `Content-Disposition`. It equals the #146 (d) name, and REQ-281 (3) asks only that the blob be saved as `scan-<id>-results.csv`. I consider the build-locally approach the safer one, and a test pins that a header value never becomes the file name.
- CHK-M11-263's plan wording "saved under the server-given name" was written before the code. It is satisfied by name equality with #146 (d), not by parsing.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-260 | G16 regen-to-temp + `cmp`; `npm run typecheck`; `npm run lint`; `npm run format:check` (from `web/`, L) | PASS | identical sha256 `e7ffd8c4…c30a`; tsc, eslint (0 warnings) and prettier exit 0; six M11 paths present |
| CHK-M11-261 | `npx vitest run src/components/Score.test.tsx` | PASS | 26/26 (part of 51/51) |
| CHK-M11-262 | `npx vitest run src/components/ResultBadge.test.tsx` | PASS | 10/10 (part of 51/51) |
| CHK-M11-263 | `npx vitest run src/app/download.test.ts` | PASS | 7 M11 tests + 5 M5 kept (15/15 with -264) |
| CHK-M11-264 | `npx vitest run src/app/download.test.ts` | PASS | 3/3 refusal tests (400 cap detail, 404, 401 ends session) |
| TASK-239 affected | `npx vitest run` on the 11 importer test files | PASS | 197/197 |
| CHK-M11-363 | plant in throwaway copy | PASS (red as required) | 3 failed / 26 |
| CHK-M11-364 | plant in throwaway copy | PASS (red as required) | 6 failed / 26 |
| CHK-M11-365 (W2 half) | plant in throwaway copy, two variants | PASS (red as required) | 4 failed / 10; variant "only when differs" 2 failed / 10 |
| CHK-M11-377 | plant in throwaway copy | PASS (red as required) | 7 failed / 26 |
| CHK-M11-378 | plant in throwaway copy | PASS (red as required) | 1 failed / 15, not a Blob |
| G16 plant | hand edit to `schema.d.ts` in the copy | PASS (red as required) | `cmp` exit 1 |
