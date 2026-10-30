# M9 gate (TP-M9-20): PASS

Tester: tester-m9b, 2026-10-30. Tree: worktree `Bitscan-m9`, branch `m9-scan-engine` = main `d09c537` plus the uncommitted M9 files (all 23 tasks APPROVED). W runs: copy `/root/bstest-m9b-g18` (G18) and `/root/bstest-m9b-base` (plants and re-runs). Venv `/root/venv-m9b` was built with `pip install --require-hashes -r manager/requirements-dev.txt`, then `-e` of the copy. `PYTHONPATH` was pinned to the copy, with `CI=true` and PostgreSQL 16 by Testcontainers. Free memory was checked before each run (≥ 3,000 MB for `-n 2`). The web UI was built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`) and copied into the WSL copy only, never into the worktree. All my containers were removed after each run.

## Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check manager` (whole tree, L) | PASS | "All checks passed!" after one fix: an E501 in my `test_queue_scan_race_pg.py` that reviewer-m9 found. Plants CHK-M9-376: an f-string query in each of the 5 new repositories → `S608`, exit 1 (5/5 red) |
| G2 | `ruff format --check manager` (L) | PASS | 385 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager`, and the same with `--platform linux` (L) | PASS | "Success: no issues found in 385 source files", both forms. Plant: an untyped `def _untyped(x)` in `services/jobs/intake.py` → `no-untyped-def`, exit 1 (W) |
| G4 | the venv built with `--require-hashes` (W); `git diff --stat d09c537 -- manager/requirements.txt manager/requirements-dev.txt manager/pyproject.toml manager/bitscan_manager/db/migrations agent deploy bits/samples .github` | PASS | install ok; the diff is empty (no dependency, no migration, no agent/unit/package/workflow change) |
| G5 | services coverage in the G18 run | PASS (plant red: 83.99 %, exit 1) | **98.53 %** (5,692/5,777) of `bm/services`. `services/jobs/*` 100 % each; scheduler `cron` 94.55 %, `runner` 98.86 %, `scan_schedules` 98.80 %, `schedules_admin` 98.13 %, `sweep` 98.22 %. Plant: 920 untested statements in `intake.py` (sized from the clean report: 5,692 / 6,697 = 84.99 %); result in "G5 plant" below |
| G6 | `tests/test_openapi.py` in G18; `git diff d09c537 -- manager/openapi.json` | PASS | green. The added operations are exactly the seven M9 ones: `POST /scans`, `POST /scans/{id}/cancel`, `POST`/`GET /scan-schedules`, and `GET`/`PATCH`/`DELETE /scan-schedules/{id}`. Plant: a `GET /scans/{id}/planted` route without re-export → 2 failed (byte check, module command) |
| G16 | in a temp copy (`web/` + `manager/openapi.json`): `npm run gen:api`, then `cmp` with the worktree `web/src/api/schema.d.ts` (L) | PASS | byte-identical. Every M9 path starts with `/api/v1/` (`/scans`, `/scans/{id}/cancel`, `/scan-schedules`, `/scan-schedules/{id}`). Plant: a hand edit to `schema.d.ts` makes the regenerated file differ (red); regeneration restores the committed bytes |
| G18 | full manager suite, `pytest -n 2 -rfEs --cov` (W, web build present, `CI=true`) | PASS after test-only fixes | First run: **11,160 passed, 6 failed, 0 errors, 0 skipped of 11,166** (25 min 13 s). All 6 were M3/M2 oracles that an M9 requirement supersedes and that I had not yet updated (below). After the fixes, the 6 node ids re-ran **6/6 passed**. Final: **11,166/11,166**, 0 skipped |
| G19 | `tests/test_schema_diff.py` in G18 | PASS | green with no migration. Plant: a throwaway `m0006` creating `ix_job_scan ON scan_job(scan_id)` → `test_migrated_schema_equals_the_spec` red (1 failed) |
| G30 | `tests/test_contract_agent.py`, `test_contract_fixtures.py` in G18; component schemas against `git show d09c537:manager/openapi.json` | PASS | green. `ComplianceJob`, `ResultsRequest`, `ResultsResponse`, `ResultItem`, `InventoryJob`, `JobsResponse` and `PluginSpec` are identical to `d09c537`. Plants: `operator` added to `ComplianceJob` → 2 failed; the NUL fixture made invalid (stdout pattern refusing U+0000) → 2 failed |
| G31, G33 | M3 agent-auth, sweep and inventory suites in G18 | PASS | green (`test_agent_auth_pg`, `test_security_m3`, `test_sweep_pg`, `test_inventory_*`, `test_jobs_api_pg` with the PD-40 rewrite). CHK-M9-365 (the scan route accepting any caller, incl. `bsa_`) → 7 failed in G70 |
| G34 | `tests/test_invariants_m3.py` in G18 | PASS | green with the seven M9 operations. Plant: `POST /scans/{id}/run` taking an `execute` body → 2 failed (the M3 route walk, and the M9 route-set and command-property check in `test_security_m9.py`) |
| G66 | M9 unit suite (7 files) | PASS | **674/674** in G18 (job_states 238, scan_state 52, scan_targets 72, job_build 62, intake_plan 107, cron 109, idempotency 34; tester-m9) |
| G67 | `test_jobs_property.py` | PASS | **8/8** in G18 (tester-m9) |
| G68 | M9 integration on PostgreSQL (12 files) | PASS | **157/157** in G18 (fixtures 5, scan_queue 10, scan_progress 6, job_intake 20, job_sweep 9, schedules repo 9, queue 8, intake 28, cancel 7, schedules admin 26, scheduled runs 11, sweep 18) |
| G69 | races and security | PASS | **20/20** in G18 (first-result-wins race 1, 200 rounds; queue races 5; `test_security_m9.py` 14) |
| G70 | API suites | PASS | **54/54** in G18 (agent job routes 20, scan routes 12, schedule routes 22) |

## G18 findings (all test-only; no product change)

Each failure was a pre-M9 oracle whose expected value an approved M9 requirement changes. Each was updated under PD-40's rule (decisions "M9 builder rulings"): every other assertion is kept, and old → new is listed here and in the TASK reports.

| Test (first run) | Was | Now | Requirement |
| --- | --- | --- | --- |
| `test_jobs_repo_pg.py::test_pull_ten_oldest_then_the_rest` | REQ-072 (4): the planted compliance job not pulled (CHK-M3-081 kind half, plant CHK-M3-351) | **CHK-M9-235**: the compliance job (oldest) is pulled first as its stored payload and dispatched; the 12 inventory jobs follow 9 + 3; every other assertion unchanged | REQ-213 (PD-40 (a)) |
| `test_jobs_repo_pg.py::test_pull_never_returns_eval_spec_or_compliance` → `test_pull_returns_compliance_but_never_eval_spec` | pull returns `[]` | **CHK-M9-236**: returns `[stored payload]`; still no `eval_spec`/`operator`/`expected` | REQ-213 (2) (PD-40 (a)) |
| `test_login.py::test_openapi_error_contract[committed]`, `[fresh]` | the only operation listing 422 is the inventory upload | **CHK-M9-237**: inventory upload and `POST /scans` (422 `about:blank` for a target with no host), compared as a set; still problem+json | REQ-221 (2), #3, #122 (f) |
| `test_thresholds.py::test_metric_families_and_labels` | six families | **CHK-M9-238**: + `bitscan_plugin_results` (counter, label `result`) | REQ-226 |
| `test_thresholds.py::test_no_unbounded_label_names_anywhere` | label names kind/status/le/mode | **CHK-M9-239**: + `result` ∈ {PASS, FAIL, ERROR} | REQ-226 (3) |

Re-run by node id after the fixes: **6/6 passed** (`test_login` counts twice, from its parametrization).

Earlier during the tasks, the same kind of oracle updates (listed in their TASK reports):
- CHK-M3-247 → CHK-M9-221 and CHK-M3-249 → CHK-M9-225 (PD-40 (a), `test_jobs_api_pg.py`);
- CHK-M3-185 → CHK-M9-217 (`test_sweep.py`, 7 steps);
- CHK-M3-230 → CHK-M9-218 (`test_scheduler_runner.py`);
- CHK-M3-233-r1 → CHK-M9-219 (`test_serve_scheduler_linux.py`);
- CHK-M9-232 (35 alert kinds);
- CHK-M9-233 and -234 (`test_alerts.py`, `test_metrics_api_pg.py`).

## G2: inventory cannot be disabled (REQ-229)

- **Diff:** `git diff --stat d09c537` over `services/settings`, `auth`, `services/scheduler/inventory.py`, `services/inventory` and `api/agent/inventory.py` is empty. M9 adds no setting, role, schedule kind or inventory code path. In `repositories/jobs.py`, the only change is that the pull no longer filters `kind`.
- **Route checks:** the route walk (G34) and `test_security_m9.py::test_no_m9_route_takes_command_text_or_names_inventory` find no M9 path, parameter or body property naming inventory, disable or skip. Every M9 body is closed.
- **Behaviour:**
  - a compliance scan, a newer scan and a cancel leave each agent's inventory job state unchanged (CHK-M9-155, -185);
  - inventory jobs still fail after 30 min and are never retried (CHK-M9-211);
  - the results route refuses an inventory job id, and the inventory route refuses a compliance job id (CHK-M9-229);
  - the M3 inventory suites (G33) are green.

## REQ-228 (2), compliance-present run

`test_sweep_compliance_pg.py::test_offline_share_and_stale_inventory_with_compliance_rows_present` (in G68, green; added at the reviewer's request): 10 eligible agents with compliance jobs and results, 1 offline. `agents_offline` fires once with offline 1, eligible 10. `inventory_stale` names exactly the online agent whose `last_inventory_at` is older than twice the interval. Compliance results do not count as inventory.

## M9 mutation table (CHK-M9-320 to -382)

Each row was planted in a throwaway copy and went red on its gate. Evidence is in the TASK report named; rows run at the gate are marked **gate**. tm9 = tester-m9 (pure modules, G66/G67).

| CHK | Red in | Source |
| --- | --- | --- |
| 320 S, 321 S | G68 repo lock probes, G69 race (double rows, M8 double count) | TASK-195, 199 |
| 322 S | G68 (sibling rows, original↔retry rows; also the restriction-to-failed/partial variant) | TASK-195, 199 |
| 323 | G66 | tm9 TASK-190 |
| 324 S | G66 (tm9), G68 | TASK-190, 199 |
| 325 S | G66 (tm9), G68, G70 | TASK-186, 199, 204 |
| 326 | G66 | tm9 TASK-186 |
| 327 | G68 | TASK-199 |
| 328 S | G68, G70 | TASK-199, 204 |
| 329 S | G68 (catalog-change and snapshot rows) | TASK-199 |
| 330 S | G66 (tm9), G68 | TASK-190, 199 |
| 331, 332 | G66 (tm9), G68 | TASK-190, 199 |
| 333 | G68 | TASK-199 |
| 334 | G66 (tm9), G68 (repo `start` guard) | TASK-186, 195 |
| 335, 336, 337 | G66 | tm9 TASK-186 |
| 338 | G66, G67 | tm9 TASK-186 |
| 339, 340 | G68 (repo and sweep) | TASK-196, 202 |
| 341 S, 342, 345 | G68 | TASK-202 |
| 343 | G66 (tm9), G68 | TASK-189, 202 |
| 344 S | G68 (CHK-M9-209 end to end; the tm9 hand-over) | TASK-202 |
| 346 | G68 (repo and two-sweep race) | TASK-196, 202 |
| 347 S | G66 (tm9); **gate**: operator/expected added to the built plugins → 10 failed (G70 agent routes, G68 queue); G30 `operator` in `ComplianceJob` → 2 failed | TASK-189; gate |
| 348, 349 S, 350 | G66 | tm9 TASK-189 |
| 351 S | G66 (tm9), G68 | TASK-189, 198 |
| 352 S, 353 S | G68, G69 (delete race) | TASK-193, 198 |
| 354, 355, 356 | G68 | TASK-193 |
| 357 | G68 | TASK-198 |
| 358 | G68 | TASK-193 |
| 359 | G68 | TASK-194, 200 |
| 360 | G66 (tm9), G68 (cancel derive) | TASK-187, 200 |
| 361 | G68 (repo grouped by `job_id`; the tm9 hand-over) | TASK-194 |
| 362 | G66, G67 | tm9 TASK-187 |
| 363 | G68 | TASK-194, 202 |
| 364 S, 365 S | G70 | TASK-205 |
| 366 S | G68, G70 | TASK-198, 205 |
| 367 | G66 (tm9), G70 (store bypassed) | TASK-192, 205 |
| 368, 369 | G66 | tm9 TASK-191 |
| 370 | G66 (tm9), G68 (5 Kolkata rows) | TASK-191, 201, 203 |
| 371, 372 | G68 | TASK-203 |
| 373 | G68 (repo `SKIP LOCKED` row) | TASK-197, 203 |
| 374 | G68 (commit-failure row; duplicates-counted variant) | TASK-199 |
| 375 S | G68 canary row | TASK-199 |
| 376 S | G1 (5 repositories) | TASK-193 to 197 |
| 377 S | G68 (`InsufficientPrivilege` surfaces) | TASK-196 |
| 378, 379 S, 380 | G70 | TASK-204 |
| 381 S | G68 (all three guards dropped) | TASK-193, 198 |
| 382 S | G70; **gate**: G69 (the route-schema check sees an open body) → 2 failed | TASK-205; gate |

**63/63 rows red** (the 24 security rows included), plus the tester extras CHK-M9-383 to -393 (tm9) and my per-task extras. The extras include, for example:
- 322-fp;
- 197r1 share/skip;
- 201 share/enable/nul/deleted;
- 202 deleted/decommissioned/unchanged/per-job savepoint;
- 203r1 (`DeadlockDetected` with a plain `FOR SHARE`);
- 206 role/extra keys.

All red.

Plants that stayed green, and why (no defect):
- 334s: the service only calls `start` for a dispatched job, so the guard is defence in depth; the repo plant is red.
- 374, first try: my fault test raised before the counter step, so the commit-failure test was added and went red.
- 381 as first written: a third guard, `scan_id <>`, still held.
- 373 at service level: the waiting tick re-checks the row, so the repo row shows it.

## G5 plant

Throwaway copy `/root/bstest-m9b-mut-G5` (removed after the run), web build present, `CI=true`, `-n 2`, `pytest --cov --cov-report=term --cov-fail-under=85` (the CI command's floor):

| Run | Plant | Result |
| --- | --- | --- |
| p1 | 920 never-called statements in `services/jobs/intake.py` (`_untested_g5_plant`) | 11,166/11,166 passed. `intake.py` 1,002 statements, 920 missed (8.18 %). **TOTAL 6,698 / 1,005 missed = 85.00 % as printed**: the raw value is 5,693 / 6,698 = 84.99 %. pytest-cov printed "FAIL Required test coverage of 85% not reached. Total coverage: 85.00%", but **the process exited 0** |
| control | `--cov-fail-under=85` on one file (1.07 %) | exit 1 with `-n 0` and `-n 2`: the floor does fail the run normally |
| p2 | 1,000 never-called statements in `intake.py` (5,692 / 6,777 = 83.99 %), clear of the rounding boundary | **RED**: 11,166/11,166 passed. `intake.py` 1,082 statements, 1,000 missed (7.58 %); **TOTAL 6,778 / 1,085 missed = 83.99 %**; "FAIL Required test coverage of 85% not reached. Total coverage: 83.99%"; **exit 1** (25 min 57 s). The copy was removed and no containers were left |

**Observation for `main`** (tooling, not M9 code; no gate lowered): at a coverage of 84.99 %, which prints as 85.00 % at two decimals, pytest-cov 7.1.0 prints FAIL but exits 0. So the CI floor (`.github/workflows/manager.yml` L140) passes a run that is under 85 % by less than 0.005 points. p1 was sized at the boundary on purpose; it found this. The M9 tree itself is at 98.53 %, far from it.

## NOT RUN at the M9 gate (by design)

- A real runner executing plugins and redacting: **M10**.
- The nightly end-to-end scan → results on VMs, the read views, CSV, the re-evaluation route and scan retention: **M11**.
- Load tests: deferred by the user. CI (GitHub Actions): not run here (no push).
- G7 to G15, G17, G35 to G41: not re-run; M9 changes no agent, unit, package or web source file other than the generated `schema.d.ts`, which G16 covers.
- `tests/m9/report.md`: the harness refused my write of a file named `report.md`. Its content (the per-task table, the old → new list, the security rows) is in this file and the TASK reports, for `main` to fold.
