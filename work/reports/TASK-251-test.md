# TASK-251 TEST: routing, navigation, role gating, Run scan on the profile page (W4, tested with the W3 batch)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-251-impl.md`). Shared batch evidence is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-279 to REQ-283 (routing parts). Spec: TS §6.2 L1113, L1120–L1126; #122 (i), #154 (c); PD-28 (d).

## Tests

| File | Result |
| --- | --- |
| `web/src/app/router.test.ts` (extended: 39 M11 rows) | **148/148** |
| `web/src/app/App.test.tsx` (CHK-M5-280 updated; 8 M11 rows added) | **44/44** |
| `web/src/screens/ProfileDetail.test.tsx` (existing, unchanged) | **25/25** |

## Acceptance criteria

**CHK-M11-271, router: PASS.**
- `#/scans`, `#/scans/<uuid>`, `#/scans/<uuid>/results`, `#/scans/run`, `#/scans/run/<id>` (up to 20 digits) and `#/schedules` each parse and format back. Upper-case scan ids are lower-cased.
- 30 malformed hashes fall back to the host list. They include:
  - `#/scans/` and ids that are short, long, unhyphenated, non-hex, %-encoded or `..`;
  - trailing `/`, `/other`, `/results/`, `/results/x`, `/Results`, `/results.csv` and `?x=1`;
  - run ids that are empty, non-digit, negative, decimal, 21 digits, full-width, a UUID, or followed by `/x`;
  - wrong case, `#/scan/<id>`, `#/schedules/` or `#/schedules/1`, and `#/run-scan`.

**CHK-M11-271, role gating in the shell: PASS.**
- A viewer opening `#/scans/run`, `#/scans/run/7` or `#/schedules` gets "This page is not available for your role.". No Run scan form or heading appears, **zero requests** are sent per hash, and there is no `scan-schedules` request and no `POST /scans`.
- An operator and an admin get both screens.
- A viewer gets Scans, the detail and the results, with no Run scan, Cancel or Re-evaluate.
- Scans links to `#/scans/run` and `#/scans/<id>`.

**CHK-M11-271, profile page: PASS.** An operator sees Run scan linking to `#/scans/run/7`. The form opens with profile 7 chosen, submits `{policy_id: 7, target: {all: true}}`, and lands on `#/scans/<new id>` showing the detail. A viewer's profile page has no Run scan.

**CHK-M11-272, session in memory on the M11 screens: PASS.** The App test's `afterEach` leak check (storage, cookie, IndexedDB, console, history, URL) runs after every M11 shell row, and nothing leaked.

## Earlier check changed by requirement (PD-51, old → new)

| Old | New | Why |
| --- | --- | --- |
| CHK-M5-280: viewer and operator nav = Hosts, Package search, Profiles, TOTP, Password; admin adds the catalog and enrolment entries | CHK-M5-280 (M11): Scans after Profiles for every role; Schedules after Scans for operator and admin; every other entry, its order, the host-list landing, `aria-current` and Sign out unchanged | REQ-279 (Scans, every role) and REQ-282 (Schedules, operator, #122 (i)) |

## Plants (red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-366 (b) (main's role-gating plant) | `run-scan` open to every role | the "Not available, never mounts" row |
| CHK-M11-366 (c) | `schedules` open to every role | the same row, plus CHK-M5-280 viewer nav |
| CHK-M11-366 (d) | the profile page's Run scan for viewers | the viewer profile row |
| CHK-M11-430 (main's malformed-id plant) | any non-empty scan id accepted | 15 fallback rows |
| CHK-M11-431 | any Run scan profile id accepted | 8 fallback rows |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-271 | `npx vitest run src/app/router.test.ts src/app/App.test.tsx src/screens/ProfileDetail.test.tsx` | PASS | 148/148, 44/44, 25/25 |
| CHK-M11-269 (viewer half), REQ-282 (3) | the App gating row | PASS | 0 requests per hash; no `scan-schedules` |
| CHK-M11-272 (session) | App `afterEach` leak check | PASS | no leak |
| CHK-M5-280 → CHK-M5-280 (M11) | PD-51 replacement | PASS | old → new above |
| CHK-M11-366 (shell, profile) | plants (b), (c), (d) | PASS (red as required) | 1, 2 and 1 failed |
| CHK-M11-430, -431 | plants | PASS (red as required) | 15 and 8 failed / 148 |
