# M5 GATE REVIEW: minimal host UI and package search (closing check)

Reviewer: reviewer. Date: 2026-10-25. Scope: TASK-108 to TASK-128, REQ-113 to REQ-136 (`work/tasks.md` "M5 gate": G1 to G6, G12 to G16, G18, G42 to G46, and the M5 mutation table CHK-M5-320 onwards).

Inputs:
- every `work/reviews/TASK-1{08..28}.md`;
- `work/decisions.md`, the 2026-10-24 and 2026-10-25 rows;
- `tests/m5/report.md`, the "M5 exit gate (TP-M5-22)" rows and "M5 closing";
- the working-tree diff against `6fd593c`.

Verdict: APPROVED (M5 exit gate). Two steps remain before the M5 PR: the user's browser walk-through, and the points in §6.

## 1. Task reviews

All 21 M5 reviews are APPROVED (TASK-108 to TASK-128). The ones that took more than one round were each re-tested and re-reviewed:

| Task | Extra round |
| --- | --- |
| TASK-110 | r1: `deinstall ok installed` counts as installed |
| TASK-111 | r1: the literal TS §6.3 escaping, so whitespace followed by a tab or CR is prefixed |
| TASK-112 | r1: `redirect_slashes` off app-wide (user ruling) |
| TASK-121 | r1: match status shown through the labels |
| TASK-126 | r1: one `<main>` landmark per page |
| TASK-127 | round 2: the meta-refresh `//` gap |
| TASK-128 | r1: README line 3 |

**No blocking or should-fix finding is open in any M5 review.** The optional nits the lead left as built change no behaviour. They are listed in decisions 2026-10-25 under "Optional reviewer nits left as built" (TASK-115 among them).

**The user's second look (PD-30 (2))** is recorded for:
- TASK-116: accepted by the user (decisions 2026-10-25).
- TASK-118 and TASK-119: under the overnight pre-authorisation, applied on TEST PASS plus "APPROVED, no open blocking or should-fix findings (and no nits)" (decisions 2026-10-25, "Pre-authorised approvals applied").

M5 has no TS §8.2 two-approval task.

## 2. Changes outside the task file lists (working tree against `6fd593c`)

| File | Change | Checked |
| --- | --- | --- |
| `manager/pyproject.toml`, `manager/tests/test_serve_linux.py`, `test_readme_walk_linux.py`, `test_serve_scheduler_linux.py` | The M3 gate fixes, applied in place of a merge (decisions 2026-10-25). `precision = 2` came with TASK-110 r1; the three test fixes were applied by main. | All four files are byte-identical to `ff1fb4f` (sha256 compared), and equal to the M4 tree's copies. They are the changes approved in `M3-gate.md` §2. |
| `manager/tests/test_invariants_m3.py` | The route walk (G34) allows exactly `GET /` and `GET /assets/{name}` beyond the spec routes. It requires both package routes. Its document check now excludes only the two static routes. | Matches REQ-118 (6) and #6. It is not widened beyond the two routes, and G46's walk checks the same thing again independently. |
| `manager/tests/test_security_m5.py`, `test_readme_m5_walk_linux.py` | New gate suites (G46, the README walk). Each now has its own database. | See §5. |
| `.gitignore` | `manager/bitscan_manager/webui/` (TASK-115) | No product effect. |
| `README.md` | TASK-128 and r1 (line 3). TASK-085's two sentences are word for word the same. | Line 3 is byte-identical to M4's. |

**My own checks on the final tree (Windows):**
- `ruff check` and `ruff format --check` are clean (232 files).
- `mypy --strict` reports no issues (232 files).
- A fresh OpenAPI export is byte-identical to `manager/openapi.json` (G6).
- In `web/`, `npm run lint`, `npm run typecheck` and `npm run format:check` are clean.

## 3. Decisions applied or carried over

| Decision | Status |
| --- | --- |
| #6 M5 half: `/` and `/assets/<file>` served with no token, no catch-all, no CORS, not in the document (a recorded deviation from TS §2.3 L118) | TASK-112; G45 and G46 |
| Trailing-slash redirects off app-wide (user, 2026-10-25). This changes approved M2/M3 behaviour: a slashed API path was a 307 and is now a 404. | TASK-112 r1. The M2/M3 route suites were re-run, and the README states it. |
| PD-28: Vite into `bitscan_manager/webui/`, jsdom and Testing Library dev-only, `qrcode-generator` drawn as SVG, no router library, no browser automation | TASK-115, 116, 119, 127 |
| PD-29 (a): status, kind and decision enums in the contract; roles stay strings | TASK-108, 122 |
| #83, #84 (incl. the literal TS §6.3 escaping), #85, #86 (drill-down carries the active filters, plus `agent_id`), #32 type-ahead, #87 (debversion never raises; regression check CHK-M5-059) | TASK-109..114, 124, 125 |
| G42 tightened: no `on<event>=` or `srcdoc=`, and the meta-refresh target checked | TASK-127 |
| UI times shown in UTC | TASK-117 nit. The spec is silent; see §6 (3). |

**Carried forward (not M5 defects):**
- **TS §7 "1 s at 20 M rows" search target:** no gate exists (testing.md open question). It is measured in the post-M6 load test (decisions 2026-10-25).
- **CSV export memory:** two in-memory copies of a body of up to 100,000 rows. Check it with the same load test (TASK-114 nit).
- **TASK-060 64 MiB copy and the TASK-064 snapshot lookup:** these also move to the post-M6 load test, as `M3-gate.md` §3 says.

## 4. Accepted residual risks (M5 additions; the earlier residuals stand)

1. **JavaScript cannot wipe the `bsu_` token, the TOTP secret or the passwords from memory.** Clearing drops the last reference, and the user accepted this with TASK-116.
2. **The static UI routes need no token.** The files hold no data, and every API call still needs one (#6 (f), the recorded TS §2.3 deviation).
3. **Every operator and admin can see every host's raw `os_info`** (TS §8.1, unchanged). The UI shows it as text only.
4. **The bundle check scans built HTML only, not the JS bundle,** because React DOM holds handler names as strings. The CSP `default-src 'self'` is still the runtime control.

## 5. Gate results

The tester's rows are in `tests/m5/report.md` under "M5 exit gate (TP-M5-22)". Each gate is green on the clean tree and red on its planted violation:

| Gate | Row | Clean | Plant → red |
| --- | --- | --- | --- |
| G1 ruff | CHK-M5-306 | clean | S608 in `repositories/packages.py`; `import re` in `query.py` |
| G2 format | CHK-M5-307 | 231 files | a misformatted line in `webui.py` |
| G3 mypy | CHK-M5-308 | 231 files | an untyped function in `csv_export.py` |
| G4 hashed locks | CHK-M5-309 | both locks install | both alembic hashes altered |
| G5 coverage | CHK-M5-310 | 99.40 % | an untested 346-statement function → 84.84 %, exit 1 |
| G6 OpenAPI | CHK-M5-302 | byte-identical (also my export) | see G16 |
| G12 lint | CHK-M5-311 | 0 warnings | `dangerouslySetInnerHTML`, `sessionStorage.setItem`, `fetch(` |
| G13 typecheck | CHK-M5-312 | clean | a status label removed |
| G14 format | CHK-M5-313 | clean | a misformatted line |
| G15 web tests | CHK-M5-314 | 345/345 | the 11 web mutation rows against the whole suite |
| G16 client | CHK-M5-315 | no diff | `openapi.json` changed without regeneration |
| G18 full manager | CHK-M5-316 | 4748/4748, 0 skipped | the G43 to G46 rows |
| G42 bundle | CHK-M5-317 | `G42 OK` | 36/36 cases (every rule red, controls green) |
| G43–G45 | mutation table | control 813/813 | 46/46 red |
| G46 security | CHK-M5-300..304 | 6/6 | CHK-M5-445..448 red |
| README walk | CHK-M5-295/296 (r1) | 103 rows, 0 deviations | CHK-M5-441..444 red |

**No gate was lowered.** I checked the three test-side changes made at the gate:
1. **Re-anchored plants (CHK-M5-327, 327b, 332).**
   - 327 and 327b target `repositories/packages.py`, which TASK-114 restructured into `_SHAPES`. 332 targets `csv_export.py`, which TASK-111 r1 changed.
   - The plant text was moved to the new lines with the same mutation (the order tie-breaker dropped; the escaping condition). Both are red again.
   - This is what the targeted-run rule requires when a plant's target changes, and it lowers nothing.
2. **Own database for the two new gate suites.** The first G18 run had one test-isolation failure (a host was not on the first page of a shared database). The fix gives each suite its own migrated server, as the M3 gate pattern does. No assertion was weakened, and the full G18 passed afterwards.
3. **The G46 content-type check.**
   - It had compared served types with the code's own `CONTENT_TYPES` map, so plant 447 (`.js` served as `text/plain`) stayed green.
   - It now compares with the test plan's fixed table (`TYPES` in `test_security_m5.py`, the same six types as REQ-118 (1)), and 447 is red.
   - This makes the test stricter. A test that checks the code against itself cannot fail.

**Not run:**
- CHK-M5-291, the CI half: the `web.yml` job, and every workflow, on the PR. It waits for the push.
- CHK-M5-305: the user's browser walk-through. The checklist is in `tests/m5/report.md`, and this is the user's step.
- The TS §7 performance target: no gate, deferred with the load tests.

## 6. For the user before the M5 PR is opened

1. **The browser walk-through (CHK-M5-305)** is the M5 exit-gate approval step for the user (PD-28 (f)). Its 10 items include the devtools checks: no CSP errors, no other-origin request, and empty storage.
2. **CI must be fully green before merge.** `web.yml` with the G42 step has not run on GitHub. G16 and G6 in their `git diff` form, and G18 on runners, have not run on the committed head either.
3. **UI times are shown in UTC** (`YYYY-MM-DD HH:MM:SS UTC`), not in the browser's time zone. The spec is silent. Confirm this during the walk-through, or ask for local time.
4. **Merge order and history.**
   - The M5 worktree is cut from `6fd593c`. It carries main's M3 gate fixes as working-tree copies, byte-identical to `ff1fb4f`, so merging main should apply cleanly for those files.
   - M5 and M4 both touch `README.md`. The shared lines (line 3, TASK-085's two sentences) are identical, so whichever lands second should merge without conflict.
   - Re-run G18 on the merged head. Nothing is committed; no commit is authorised overnight.
5. **The trailing-slash change (user ruling 2026-10-25)** changes approved M2/M3 behaviour: a slashed API path is now a 404, not a 307. The PR should name it, together with the #6 TS §2.3 deviation.
6. **`.claude/CLAUDE.md` "Supported hosts"**: still pending the user's edit, as noted in `M4-gate.md` §6 (3).
