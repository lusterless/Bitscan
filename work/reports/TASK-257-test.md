# TASK-257 TEST: vitest `testTimeout` 20000 (web flake fix)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11`, uncommitted IMPL (`work/reports/TASK-257-impl.md`). L (Windows 11, Node v24.22.0, 14 workers), from `web/`.

**Why.** The W3 batch's first full run had two M5 paging tests time out at vitest's default 5 s:
- `Hosts.test.tsx` CHK-M5-240 (51 hosts);
- `Profiles.test.tsx` CHK-M7-312 (c) (121 policies).

They take 2.0–2.5 s alone. Main chose option (a), a suite-wide timeout ([TASK-246-test.md](TASK-246-test.md), "Flake").

**Change.** `web/vite.config.ts` adds `test.testTimeout: 20000` plus a comment. No assertion or test changes.

## Runs (full web suite, `npx vitest run --reporter=json`)

| Run | Timeout | Result | Slowest tests (ms) |
| --- | --- | --- | --- |
| 1 | 20000 (TASK-257) | **741/741**, 0 failed, 0 skipped | Hosts 51 at 3673, Profiles 121 at 3373, Rebuild confirm at 3321, Scans 51 at 3112, TargetPicker hosts at 2882 |
| 2 | 20000 (TASK-257) | **741/741**, 0 failed, 0 skipped | Hosts 51 at 3089, EnrolmentRequests paging at 2847, ScanDetail summary at 2777, Account TOTP at 2506, ScanResults verdicts at 2457 |
| Gates | n/a | `npm run lint` 0, `npm run typecheck` 0, `prettier --check vite.config.ts` clean | n/a |

Across both runs, no test comes near the new limit: the slowest is 3.67 s, 18 % of 20 s.

## Plant: timeout back to 5000 under the same load

The plant was made in a throwaway copy (`%TEMP%\m11w-mut-257`, node_modules by junction), and the copy was removed afterwards. The worktree still reads 20000.

| Run | Result | Hosts CHK-M5-240 | Profiles CHK-M7-312 (c) | Margin to 5000 |
| --- | --- | --- | --- | --- |
| plant 1 | 741/741 | 4697 | 3126 | 303 ms |
| plant 2 | 741/741 | 2851 | 4529 | 471 ms |
| plant 3 | 741/741 | **4939** | **4784** | **61 ms** |
| default 5000, before TASK-257 (2 runs, the same tree) | 741/741 each | 3521 / 2837 | 3963 / 2337 | 954 ms (App nav 4046) |
| W3 batch run 1, default 5000 (observed earlier) | **2 timeouts** | **timed out** | **timed out** | none |

**Reading.**
- At 5000, the same two M5 paging tests come within 61 ms of the limit, and in one earlier observed run both went over. The setting matters.
- At 20000, the heaviest test keeps more than 16 s of headroom.
- The 5000 plant was not red in these three runs. Main said it need not be red every time, and I did not re-run until red.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-257 run 1 | `npx vitest run` (testTimeout 20000) | PASS | 741/741; slowest 3673 ms |
| TASK-257 run 2 | `npx vitest run` (testTimeout 20000) | PASS | 741/741; slowest 3089 ms |
| TASK-257 gates | lint, typecheck, prettier on `vite.config.ts` | PASS | all exit 0 |
| TASK-257 plant (5000) | 3 full runs in a throwaway copy | PASS (the setting shown to matter) | the M5 paging tests reached 4939 and 4784 ms of 5000; observed timing out in the earlier W3 run |
