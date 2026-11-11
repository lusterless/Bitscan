# TASK-257 REVIEW: vitest test timeout

Reviewer: reviewer-m11, 2026-11-08. Round 1. Low risk, one approval.

Verdict: APPROVED

**Scope reviewed:** `web/vite.config.ts` (+3 lines: `test.testTimeout: 20000` and a comment).
**Checked against:** `.claude/rules/testing.md` (no gate lowered, no test skipped or marked expected-to-fail) and the decision row of 2026-11-08.
**Reports:** `work/reports/TASK-257-impl.md` and `work/reports/TASK-257-test.md` (PASS: 741/741 twice, slowest test 3,673 ms; the 5000 plant puts the M5 paging tests at 4,939 and 4,784 ms).

## Checks

- **Only the timeout changed.** `git diff` on `vite.config.ts` adds only `testTimeout` under `test`. `environment: "jsdom"` and the rest of the config are unchanged. No test file, assertion, `retry` or `bail` setting is touched, and there is no `.skip` or `.fails`.
- **No gate lowered.** G15 still runs the same 741 tests with the same assertions. A per-test timeout bounds a hang; it is not an acceptance threshold. 20 s is about 5.4 times the slowest observed test, so a real hang still fails.
- **The reason is shown.** One W3 full run timed out two M5 paging tests at the 5 s default. The plant reproduces runs within 61 ms of that limit. Under the old setting this was a load-dependent flake, not a product fault.

## Findings

None.
