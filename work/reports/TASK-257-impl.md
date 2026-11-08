# TASK-257 IMPL: vitest test timeout

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed.
Asked for by the lead on 2026-11-08, after tester-m11w's W3 run.

## Change

`web/vite.config.ts` (+3 lines): `test.testTimeout: 20000`, with a one-line comment giving the reason. Nothing else in the config changed.

## Why

- With M11's tests the web suite has 31 files on 14 workers.
- Two M5 paging tests timed out once at vitest's default of 5 s.
- Heavy screen renders take 2.2–3.2 s even on green runs.

The change touches no assertion and no test file.

## Checks run (from `web/`)

`npx prettier --check vite.config.ts`, `npm run lint` and `npm run typecheck` pass. I ran no vitest suite (tester's job).

## For the tester

Run the full suite twice.

To plant: set the timeout back to `5000` and expect the earlier flaky timeouts to be possible again under full load.
