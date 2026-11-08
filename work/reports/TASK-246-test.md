# TASK-246 TEST: Scans screen and Run scan form (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11`, branch `m11-results` on `42d0692`, uncommitted IMPL (`work/reports/TASK-246-impl.md`). L (Windows 11, Git Bash, Node v24.22.0), from `web/`.
REQ: REQ-279 (1)–(3), REQ-284. Spec: TS §4.4 L555–L558, §6.2 L1120–L1121, §6.3 L1136–L1137, L1143; #154 (a)–(c), #123, #122 (a), (b), (f).
This file also holds the **batch evidence** for W3 (TASK-246, 247, 248, 249, 250, 256) and TASK-251 (W4, tested with the batch at main's request). The other reports link here.

## Batch evidence (shared)

| Run | Command (from `web/`) | Result |
| --- | --- | --- |
| Full web suite after every W3/W4 test was written (the shared `src/test/harness.ts` changed) | `npx vitest run --reporter=json` | **741/741 passed**, 0 failed, 0 errors, 0 skipped (182 suites, 31 files) |
| Earlier full run, before CHK-M5-280 was updated | `npx vitest run` | 689/694 passed. 3 failures were the expected CHK-M5-280 nav rows (changed by requirement, below). 2 were 5 s timeouts in the M5 paging tests (`Hosts.test.tsx` CHK-M5-240 51 hosts, `Profiles.test.tsx` CHK-M7-312 (c) 121 policies), not assertion failures. Re-run alone they take 2.5 s and 2.0 s. See "Flake" below. |
| G12 | `npm run lint` | exit 0 (0 warnings) |
| G13 | `npm run typecheck` | exit 0 |
| G14 | `npm run format:check` | exit 0 |
| G16 | regenerate to a temp file, prettier with `--stdin-filepath src/api/schema.d.ts`, `cmp` | no diff |
| Clean throwaway copy (`%TEMP%\m11w-mut-w3`, node_modules by junction) | the 10 W3/W4 test files | 324/324 before any plant; the copy was compared with the worktree file by file after the plants (identical) and removed |

**Flake (reported to main, not hidden; no test was retried until green).** With 31 files on 14 workers, the heaviest render tests run 2.2–3.2 s even when green. The slowest are Scans 51-scan paging at 3.2 s, Hosts 51 at 3.0 s, EnrolmentTokens 51 at 2.5 s, App nav at 2.3 s and Profiles 121 at 2.2 s, against vitest's default 5 s `testTimeout`. A loaded machine pushes the M5 paging tests over it. The fix is one config line (`test.testTimeout`) in `web/vite.config.ts`, which belongs to impl-web, or per-test timeouts. I'm asking main which.

**Tester infrastructure changed:**
- `web/src/test/harness.ts`: `Call.headers` added, so the `Idempotency-Key` header can be read.
- `web/src/test/m11.ts` (new): builders, `mockLinks()` for the `links: ScanLinks` prop until TASK-251, and `at()`.

## This task's tests

| File | Tests | Result |
| --- | --- | --- |
| `web/src/screens/Scans.test.tsx` (new) | 15 | 15/15 |
| `web/src/screens/RunScan.test.tsx` (new) | 17 | 17/17 |

## Acceptance criteria

**REQ-279 (1): CHK-M11-265 and -266 PASS.**
- The filters send exactly `policy_id`, `agent_id` (trimmed, lower-cased), `state`, `created_after` and `created_before` at `T00:00:00Z`, only on Apply. A malformed host id refuses the filter and sends nothing. Clearing a filter drops its parameter.
- Paging works forward and back: 51 scans show each one once, and a filter change returns to page 1.
- A viewer has no Run scan; an operator and an admin link to it.
- A submission sends `{policy_id, target}` with one UUID `Idempotency-Key` from `crypto.randomUUID`. A double click sends one request, and the button is disabled while in flight.
- The key is kept after a network error and replaced after an answer. A new key also comes with the next submission or a profile change.
- After the 202, the new scan's detail opens through `openScan`.
- No profile, a profile that isn't enabled, a bad tag, or no host chosen is each refused before anything is sent.

**REQ-279 (2): PASS.** 409 "The policy is disabled." and the 422 detail are shown as text.

**REQ-279 (3): CHK-M11-272 PASS.** `<script>` and `onerror` policy names in the list, the filter and the Run scan profile list, and `<script>` host names in the picker, all render as text: no `script` or `img` element.

## Plants (all red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-366 (screen) | Scans shows Run scan for every role | `a viewer sees no Run scan` |
| CHK-M11-432 | in-flight guard removed | double-click row |
| CHK-M11-433 | new key on every send | retry-keeps-key row |
| CHK-M11-438 | host-id filter untrimmed and in its typed case | REQ-264 query row |
| CHK-M11-375c | `dangerouslySetInnerHTML` host name in the picker | lint exit 1, plus the RunScan `<script>` host row and the TargetPicker row |

## Notes (not findings)

- RunScan clears the key on any answer, refusals included. #154 (b) replaces the key "for the next submission", and an answered request ends its submission.
- `#/scans/run/007` gives `policyId` "007", which matches no option ("7"), so the form asks for an enabled profile. The profile page formats only canonical ids. Recorded only.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-265 | `npx vitest run src/screens/Scans.test.tsx` | PASS | 15/15 |
| CHK-M11-266 | `npx vitest run src/screens/RunScan.test.tsx` | PASS | 17/17 |
| CHK-M11-272 (Scans, Run scan) | the same files | PASS | plain-text rows green; no `script`/`img` nodes |
| CHK-M11-366 (screen half) | plant in a throwaway copy | PASS (red as required) | 1 failed / 15 |
| CHK-M11-432, -433, -438 | plants in a throwaway copy | PASS (red as required) | 1 failed / 17; 1 failed / 17; 1 failed / 15 |
| W3+W4 batch full run | `npx vitest run` | PASS | 741/741, 0 skipped |
| W3+W4 G12–G14, G16 | lint, typecheck, format:check, regen `cmp` | PASS | all exit 0; no diff |
| Flake observation | full run under load | NOT RUN as a gate (observation) | 2 M5 paging tests hit the 5 s default timeout once; 2.0–3.2 s alone; sent to main |
