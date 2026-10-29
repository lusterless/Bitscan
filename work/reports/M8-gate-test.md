# M8 gate (TP-M8-14): PASS

**Final (2026-10-29, after the CHK-M2-232 ruling):** G18 re-run on the final tree, `-n 0`, web build present: **10,228/10,228 passed, 0 failed, 0 errors, 0 skipped**, services coverage **98.50 %**. See "CHK-M2-232 fix" and "Environment note" at the end. The first run's results are kept below as the record.

Tester: tester-m8, 2026-10-29. Tree: worktree `Bitscan-m8`, branch `m8-evaluator` = main `67a6dfa` plus the uncommitted M8 files. Product: `bm/services/evaluator/{__init__,model,normalise,operators,evaluate,verdict,eval_spec,score,scores,reevaluate}.py`, `bm/repositories/results.py`, `bm/repositories/reeval.py` (r1). Tester: 14 test files plus `tests/m8/test-plan.md`. W runs use my own copy `/root/bstest-m8-base`, venv `/root/venv-m8` (hashed locks plus `-e` of the copy), `PYTHONPATH` pinned to the copy, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0` (free memory 2,294–2,808 MB, below the 3,000 MB `-n 2` floor). All of my containers were removed after each run (0 `m8t` containers left).

## Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check manager` (whole tree, L) | PASS | "All checks passed!" (S608 and the `re` ban included). Plants: CHK-M8-320 (`TID251 re is banned`), -349 and -350 (`S608`), each exit 1 |
| G2 | `ruff format --check manager` (L) | PASS | 337 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager`, plus the same with `--platform linux` (L) | PASS | "Success: no issues found in 337 source files", both. Plant: an untyped `def _untyped(x)` in `evaluate.py` → `no-untyped-def`, exit 1 (W) |
| G4 | fresh `/root/venv-m8` from `pip install --require-hashes -r manager/requirements-dev.txt` (W) | PASS | install ok. `git diff 67a6dfa -- manager/requirements.txt manager/requirements-dev.txt manager/pyproject.toml` is empty (no new dependency) |
| G5 | services coverage in the G18 run (W) | PASS | **98.46 %** (4,853/4,929 lines) of `bm/services`, including `services/evaluator` at 99.42 % (340/342; only `eval_spec.py` L92–93 missed). Plant: 800 untested statements in `reevaluate.py` (sized from the clean report: ≥ 781 needed) → 4,853/5,732 = **84.67 %** < 85 %, and `--cov` itself reports "FAIL Required test coverage of 85.0% not reached" |
| G6 | `tests/test_openapi.py` in G18, and `git diff 67a6dfa -- manager/openapi.json` | PASS | green in G18; the diff is empty. Plant: a `POST /scans/{scan_id}/reevaluate` stub on the rebuild router → `test_committed_file_matches_a_fresh_export` and `test_module_command_writes_the_same_bytes` red |
| G34 | `tests/test_invariants_m3.py` in G18 | PASS | green. **G6 red, G34 green by design** (decisions row "M8 gate row G34: the planted violation corrected"): `POST /scans/{id}/reevaluate` is a TS §6.2 route, so the route walk allows it; with the stub planted, `test_invariants_m3.py` + `test_openapi.py` gave 37 passed, 2 failed (both G6). No route is proven by G6 plus the empty diffs `git diff 67a6dfa -- manager/openapi.json manager/bitscan_manager/api manager/bitscan_manager/db/migrations` |
| G18 | full manager suite, `pytest -n 0 --cov` (W) | **10,222 passed, 2 failed, 3 errors**, 0 skipped (`-rs` lists none), 41 min 59 s. See "G18 findings": the 3 errors and 1 failure are an environment gap (no web build in my copy), now fixed and re-run 7/7. The other failure is pre-existing and order-dependent, outside M8 |
| G62 | evaluator unit suite (7 files) | PASS | inside 1,345/1,345 (all M8 files) and inside G18 |
| G63 | `test_evaluator_property.py` | PASS | inside 1,345 and G18; at the gate I added `test_verdict_constructs_exactly_when_valid` (CHK-M8-364's G63 half): plant code set `(0,1,2,3)` → red `(3, None)` |
| G64 | `test_results_repo_pg.py`, `test_reeval_repo_pg.py`, `test_scores_pg.py`, `test_reevaluate_pg.py`, `test_reevaluate_race_pg.py` | PASS | 15 + 40 + 5 + 31 + 7 = 98/98 (W), and inside G18 |
| G65 | `test_security_m8.py` | PASS | inside 1,345 and G18 |

All M8 files together (W, `-n 0`, before G18): **1,345/1,345 passed**, 0 failed, 0 errors, 0 skipped.

## G18 findings

| Test | Result | Diagnosis | Re-run |
| --- | --- | --- | --- |
| `test_security_m5.py` (3 tests, ERROR at setup: `live` fixture) and `test_readme_m5_walk_linux.py::test_the_m5_readme_sections_behave_as_written` (FAILED) | environment | "the web UI build is missing: run `npm run build` in web/". `manager/bitscan_manager/webui/` is git-ignored and built by CI (`manager.yml` "npm run build"); my copy had none. Not M8 (`git diff 67a6dfa -- web` is empty) | Built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`, never in the worktree), copied into `/root/bstest-m8-base` only: **7/7 passed** (both files) |
| `test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes` (CHK-M2-232) | FAILED, pre-existing, order-dependent | In G18 it failed at L425 (`shipper.refusing()` still True after 5 `run_once` on recovery). The log shows the shipper draining the session database's ~3,000 audit entries 500 at a time: 5 cycles can't drain a database the whole suite wrote to, so the outage never clears. Run alone it fails earlier (L417: 200 instead of 503); inside its own file it passes (31/31). **On a clean main `67a6dfa` copy it fails alone the same way (2/2 runs, L417, `assert 200 == 503`).** M8 adds audit rows (re-evaluation entries) to the shared session database, which likely pushes the full-suite volume past what 5 cycles drain. M8 does not touch the shipper, the users routes or this test | Not fixed: it's an M2 test (owner tester) whose fixture shares the session database. **Needs a ruling** (below) |

## M8 mutation table (CHK-M8-320 to -364)

Every row was planted in a throwaway copy (`/root/bstest-m8-mut-<id>`, removed after each) and went red on its named gate. Per-task evidence is in the TASK reports; rows run at the gate are marked **gate**.

| CHK | Red in | Source |
| --- | --- | --- |
| 320 S | G1 (TID251) and G62 (`(?=x)` rows; the full file hangs on `re` backtracking, timeout exit 124) | TASK-177 |
| 321, 322 | G62 (multiline, `foo`/`xfoo`) | TASK-177 |
| 323 S | G62 (18 `not_regex` rows) | TASK-177 |
| 324, 325 | G62 (CRLF rows; U+00A0 and Unicode-space rows) | TASK-176 |
| 326, 327, 328, 329 S | G62 | TASK-177 |
| 330, 331, 332, 333, 334 S, 335 S, 336 | G62 (and G63 for 330, 333) | TASK-178 |
| 337 | G62 (11 rows) | TASK-176 |
| 338 S | G63 (`test_classify_and_evaluate_are_total`), G62 (`KeyError` rows) | TASK-177, 178 |
| 339 S, 340, 341 S, 342 S, 343 | G62 | TASK-179 |
| 344 S, 345 S | G62 | TASK-180 |
| 346, 347 | G62 (G63 property too) | TASK-181 |
| 348 S | G62 (unit, 9 rows), G64 (SQL rows and the 200-set property) | TASK-181, 182, 184 |
| 349 S, 350 S | G1 (S608) | TASK-182, 183 |
| 351 | G64 (EXPLAIN `Actual Loops` row) | TASK-182 |
| 352 | G64 (host B, duplicate and retry rows) | TASK-182 |
| 353 S | G64 and G65 (34 tests see `InsufficientPrivilege`) | TASK-185 |
| 354 S | G64 (one-statement spy, TASK-183) and the race row `test_import_inside_the_definitions_read_never_mixes_versions` (TASK-185) | TASK-183, 185 |
| 355 S, 356, 357 | G64 | TASK-185 |
| 358 S | G64 (TASK-183 lock row; TASK-185 race row "B is not waiting on the lock") | TASK-183, 185 |
| 359 S | G64 (missing: 3 rows; own transaction: 5 rows, including the fault row) | TASK-185 |
| 360 | G64 (chunk rows; 20,000-result row) | TASK-183, 185 |
| 361 S | G65 (static and runtime import graphs) | TASK-178 |
| 362 S | G62 (no-log row) and G65 (canary, no-logging rows) | TASK-178, 185 |
| 363 S | G62 and G65 (canary detail rows, 69 failed) | TASK-178 |
| 364 | G62 (`Verdict(3, None)`), **gate**: G63 (`test_verdict_constructs_exactly_when_valid`) | TASK-176; gate |

Gate-only plants: G3 untyped function (red), G5 800-statement plant (red, 84.67 %), G6 route stub (red), G34 route stub (green by design, see G34).

45/45 table rows red; 22/22 security rows red.

## NOT RUN at the M8 gate (by design)

- TS §8.3 Integration "verdict uses the queued `eval_spec` after a catalog change" end to end through intake: **M9**. M8 proves the API-level half: the pure modules take a `PluginSpec`, and the import graph shows no catalog access (CHK-M8-220).
- End to end scan → results: **M11** nightly. Load tests: deferred by the user.
- CI (GitHub Actions): not run here (no push).

## Ruling needed

`test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes` fails in the full single-worker run, and alone (also on clean main `67a6dfa`). It passes in its own file. Options:
- (a) Accept it as a pre-existing M2 test-isolation defect, outside M8, and open a test task. For example, give the `env` fixture its own migrated server, or drain until `refusing()` is False with a bound, rather than exactly 5 cycles.
- (b) Fix it now as a test-only change. I own test files, but this is M2's test, so I'd want your word first.
- (c) Re-run G18 with `-n 2` once memory allows, to see whether a different worker split avoids it. That would hide rather than fix it, so not recommended.

The gate verdict for the M8 gates themselves is PASS: G1–G6, G34, G62–G65, the mutation table, 0 skipped.

## CHK-M2-232 fix (ruling: option (b), `work/decisions.md` "CHK-M2-232 test isolation fix")

Test-only change to `manager/tests/test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes`. No product file changed.

**Cause, found by probe in a throwaway copy:**
- *Alone on a fresh database:* `audit_log` was empty when the test began. `env.admin()` and `env.user()` insert rows directly and write no audit entry, so the shipper had nothing to deliver, `run_once()` never failed, and `outage_since` stayed None. Every call then returned 200, not 503 (L417). That is why it also failed alone on clean `67a6dfa`.
- *Full suite:* the shared session database held about 3,000 entries, and each cycle reads at most `BATCH` (500). Five fixed recovery cycles could not drain it, so `refusing()` stayed True (L425).

**Fix (assertions kept exactly):**
- Before the outage, the test makes one audited change through the API (`POST /users`, 201), so there is always something to deliver.
- After the outage, it asserts `refusing()` is still False before 15 minutes.
- The recovery step now drains until `refusing()` is False, bounded by `count(audit_log) // BATCH + 5` cycles. Hitting the bound fails the test with "not drained in N cycles".
- Kept unchanged: 200 at 14:59; 503 `audit_sink_unavailable` for every method at 15:00 with unchanged state; `/api-tokens` still 200 during the outage; cleared only once drained, then 200.

| Check | Command (W) | Result |
| --- | --- | --- |
| alone | `pytest "tests/test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes"`, 3 runs | 3/3 passed (1/1 each) |
| its file | `pytest tests/test_users_api_pg.py` | 31/31 passed |
| full suite, single worker | G18 re-run, `-n 0` | passed (inside 10,228/10,228) |
| `-n 2` | `pytest -n 2 tests/test_users_api_pg.py tests/test_audit_append_pg.py tests/test_shipper_pg.py tests/test_reevaluate_pg.py tests/test_results_repo_pg.py` (3,425 MB free) | 97/97 passed |
| plant: outage refusal disabled (`refusing()` returns False) | the test alone | red: 200 where 503 expected |
| plant: refusal never clears (the drained branch disabled) | the test alone | red: "not drained in 5 cycles" (the bound) |
| static | ruff, ruff format, mypy --strict on the file | clean |

Note: the full `-n 2` G18 was not run. Free memory was 2,405 MB when G18 started, below the 3,000 MB floor, so G18 ran single-worker as you agreed. The `-n 2` row above runs the fixed file with the heaviest audit and PostgreSQL neighbours.

## Environment note (web build)

`manager/bitscan_manager/webui/` is git-ignored and built by CI (`manager.yml`: `npm ci --ignore-scripts`, `npm run build`). The M5 web tests (`test_security_m5.py`, `test_readme_m5_walk_linux.py`) fail closed under `CI=true` without it. For the gate I built it outside the worktree: a temp copy of `web/` (`C:\Users\kaiquan.koh\AppData\Local\Temp\m8t-web`), `npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`. I copied the result into my WSL copy only. M8 changes no web file (`git diff 67a6dfa -- web` is empty).

## G18 final row

| Gate | Command | Result |
| --- | --- | --- |
| G18 | full manager suite, `pytest -n 0 -rs --cov` on the final tree (with the CHK-M2-232 fix), web build present, `CI=true` | **10,228/10,228 passed, 0 failed, 0 errors, 0 skipped** (1 h 20 min); G5 98.50 % (4,855/4,929); 0 containers left |

The tail of the M8 test-file list is also updated: `test_eval_spec.py` gained the 36-character non-hex uuid row (102/102; `eval_spec.py` 100 %).
