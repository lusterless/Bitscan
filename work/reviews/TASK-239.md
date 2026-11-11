# TASK-239 REVIEW: web client regeneration, `Score`, `ResultBadge`, results CSV download (W2 web batch)

Reviewer: reviewer-m11, 2026-11-08. Round 1. Low risk: one approval, batched per wave.

Verdict: APPROVED

Scope reviewed: `web/src/api/schema.d.ts` (generated), `web/src/format.ts`, `web/src/components/Score.tsx` (new), `web/src/components/ResultBadge.tsx` (new) and `web/src/app/download.ts`. Checked against TS §4.5 L603–L604, §4.4 L585, §6.3 L1143–L1144, §8.2 L1268, REQ-273, REQ-280 (1), REQ-281 (1), (3), REQ-284, #146 (d), #149 and `.claude/rules/web-ui.md`. Reports: `work/reports/TASK-239-impl.md` and `work/reports/TASK-239-test.md` (PASS, 51/51 new tests, 197/197 affected, all plants red).

## Checks

- **Generated client (G16):** I regenerated `openapi-typescript ../manager/openapi.json` into a private temp directory, ran it through Prettier and compared it with `cmp`. It is byte-identical to the tree, so the file was not hand-edited. All six M11 paths are present.
- **Plain text (TS §6.3, REQ-284):** there is no `dangerouslySetInnerHTML`, no `innerHTML` and no `fetch(` in the changed files. Every value renders as a React text node.
- **#149 score:** `Math.floor(score * 1000)`, built from integers with no `toFixed`. Values are rounded down: 0.9996 shows as "99.9 %" and only 1 shows as "100.0 %". Null shows as "n/a", and the error count is always shown beside it (TS §4.5 L604). The plants for null shown as 0 %, rounding to nearest and the `*100*10` under-rounding were all red.
- **`ResultBadge` (web-ui.md: "Show both the current verdict and `original_result` when a result has been re-evaluated"):** both verdicts appear whenever the result was re-evaluated, even when they are equal. A null result shows "Not run". The labels and tones are a `Record` over the generated verdict enum, so a new verdict fails typecheck.
- **CSV download (REQ-281 (3), #146 (d)):** the download goes through the generated client with `parseAs: "blob"`, so the bearer token is sent by the middleware. The query is passed through and there is no cursor. The file name `scan-<id>-results.csv` is built locally, as M5's `packages.csv` is, so a `Content-Disposition` value never becomes a file name. A refusal saves nothing and returns the problem. The M5 `downloadCsv` keeps its signature and behaviour through the shared `saveCsv`, and the five M5 tests are unchanged and pass.
- **No dependency:** `package.json` and `package-lock.json` are unchanged from `6efe0fb`.
- **Re-run (Windows, Node from the worktree):** the three test files pass 51/51 in vitest. `npm run lint` and `npm run typecheck` both exit 0, and Prettier is clean on the four hand-written files.

## Findings

None.
