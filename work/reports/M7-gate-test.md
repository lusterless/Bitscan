# M7 gate TEST: PASS (TASK-146 r2 deferred; its rows run on r1)

Tester: tester-m7, 2026-10-28. Gate section "### M7 gate" and mutation table CHK-M7-320 to -371 of `work/tasks.md`; plan `tests/m7/test-plan.md`. Tree: the worktree `Bitscan-m7` (branch `m7-catalog`, HEAD `25d41ec` plus the uncommitted M7 work), every M7 task APPROVED; TASK-146 r2 was deferred by the user (decisions "TASK-146 r2 deferred", 2026-10-29) and `bit102.py` is back to r1.

W runs used fresh copies (`/root/bstest-m7-gate`) with `CI=true`, `PYTHONPATH` pinned to the copy's tree, and memory checked before each run. Runs were `-n 0` while tester-m7d ran PostgreSQL, and `-n 2` afterwards with at least 3,000 MB free. The web UI was built (`npm run build`, the gitignored `manager/bitscan_manager/webui/`) as CI does. No containers were left.

## Verdict

**PASS.** Every gate below is green on the final tree, and every mutation row is red (from the per-task reports, or run here). Three test bugs found by G18 were fixed and re-run, and G54's timing rows got a measurement fix under the lead's ruling, with the bound unchanged. **TASK-146 r2 deferred:** its rows ran on the restored r1 tree (see "r1 re-run" below), all green. Also NOT RUN, per the gate section: the TS §8.3 Sandbox half (no runner until M10), the VM end-to-end import (M11 nightly) and the load tests (deferred by the user).

## Gate rows

| Gate | Command | Result | Evidence | Plant (red) |
| --- | --- | --- | --- | --- |
| G1 | `ruff check manager` | PASS | All checks passed (312 files) | CHK-M7-336, -337 (TASK-148/150 reports), -347, -348 (TASK-141/144) |
| G2 | `ruff format --check manager` | PASS | 312 files already formatted | — |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | PASS | no issues in 312 source files | an untyped function appended to `store.py` (throwaway copy) → `no-untyped-def`, red |
| G4 | `pip install --dry-run --require-hashes --no-deps -r manager/requirements.txt` and `-dev.txt` | PASS | exit 0 for both (35 and 71 lines resolved). A dry run into the existing venv checks every pin and hash without changing the venv that the WSL runs and tester-m7d share; CI does the real `--require-hashes` install | — |
| G5 | `pytest --cov=bitscan_manager/services --cov-fail-under=85` (CI form, full suite, `-n 2`) | PASS | **95.34 %** (4,845 statements, 226 missed; `services/importer` included, every importer module ≥ 91.11 %) | an untested 600-statement function in `folders.py`, sized from the clean report (more than 589 needed): see "G5 plant" below |
| G6 | `tests/test_openapi.py` | PASS | 39/39 with G34; the export is byte-identical to `manager/openapi.json` | a route added in `policies.py` without re-export → 3 failed (committed file, module command, route walk), red |
| G12 | `npm run lint` (web) | PASS | exit 0, no warnings | CHK-M7-370 (`TASK-168-173-test.md`) |
| G13 | `npm run typecheck` | PASS | exit 0 | — |
| G14 | `npm run format:check` | PASS | All matched files use Prettier code style | — |
| G15 | `npm run test` (vitest) | PASS | 21 files, 516/516 passed | CHK-M7-370, -371 (`TASK-168-173-test.md`) |
| G16 | `npm run gen:api` | PASS | `src/api/schema.d.ts` byte-identical after regeneration (sha256 unchanged) | `openapi.json` changed (a planted property) without regeneration → the generated client differs, red |
| G18 | full manager suite (`-n 2`, with G5) | PASS | Run 1: **8,862 passed, 3 failed, 0 skipped**; the 3 were test bugs (below), fixed, then 14/14 by node id and 237/237 for the three files. Run 2 (the G5-planted copy, every fix in): **8,866 passed, 0 failed, 0 errors, 0 skipped**; see "G5 plant" | any of G54–G61 |
| G34 | `tests/test_invariants_m3.py` | PASS | in 39/39 above; the route walk has the eight M7 operations | CHK-M7-361 (TASK-161); the G6 plant's extra route → red |
| G54 | importer unit suite (`test_bit_model`, `_parse`, `_values`, `_structure`, `_validate`, `test_bit102_lexer`, `test_bit102`, `test_import_alerts`, `test_bit_fixtures`) | PASS (re-run) | 3,049/3,050; `test_pathological_inputs_bounded[seps]` failed the 100 ms bound at 0.103 s. Lead ruling (b): a measurement fix, below. Then `test_bit102_lexer.py` 173/173, and 237/237 with the G18 fixes | the G54 rows (TASK-140–146 reports); quadratic lexer → red under the new timing |
| G55 | `test_bit_fuzz.py`, `test_import_fuzz_pg.py` | PASS | 5/5 | CHK-M7-340 (TASK-154) |
| G56 | importer integration (13 files: lock, repos, store, delete, pipeline, uploads, folders, rebuild, start-up, `test_catalog_service_pg.py` (the table's `test_catalog_service.py`), import alerts) | PASS | 507/507 | the G56 rows (per-task reports) |
| G57 | catalog API and security (`test_policies_api_pg`, `_imports_api_`, `_policy_import_api_`, `_policy_delete_api_`, `_rebuild_api_`, `test_security_m7.py`) | PASS | 341/341, including TP-M7-30's 38 cases | the G57 rows (TASK-161–165, TP-M7-30: 24/24 red) |
| G58 | `test_cli_bits_pg.py` | PASS | 12/12 | CHK-M7-362 (TASK-166 c1) |
| G59 | `test_bits_samples_pg.py` | PASS | 50/50 on the current tree (TASK-146 r2 code included) | CHK-M7-366 (TASK-174/175) |
| G60 | `test_catalog_alerts_pg.py` (new, below) | PASS | 7/7 | CHK-M7-349–355 (below) |
| G61 | `test_watcher_linux_pg.py` (the table's `test_watcher_linux.py`), `test_serve_catalog_linux.py` | PASS | 22/22 | CHK-M7-367, -368 (below) |
| CHK-M7-305 | `test_readme_m7_walk_linux.py` (new, below) | PASS | 1/1, every row as the README says | — |

## G5 plant

- **Plant.** A never-called function of 600 assignments appended to the end of `bm/services/importer/folders.py` (`_planted_untested`; 602 statements with its `def` and `return`). It was sized from the clean report: 4,845 statements and 226 missed, so more than 589 uncovered statements take the total under 85 %. It ran in a throwaway copy (`/root/bstest-m7-mut-g5`, removed afterwards).
- **Run.** The CI form, `pytest -n 2 --cov=bitscan_manager/services --cov-fail-under=85`, on the whole suite with every G18 fix in. This is G18 Run 2.
- **Result: red.** Coverage **84.84 %** (5,447 statements, 826 missed; `folders.py` 769 / 610 / 20.68 %) against the 85 % floor: "Coverage failure: total of 84.84 is less than fail-under=85.00", pytest exit 1, while all **8,866 tests passed** (0 failed, 0 errors, 0 skipped).
- **Clean.** 95.34 % (4,845 / 226) in Run 1.

## G18 findings: three test bugs, no product defect

| Test | Expected vs actual | Diagnosis | Fix and re-run |
| --- | --- | --- | --- |
| `test_bit102_lexer.py::test_long_inputs_up_to_16384_chars` | < 0.1 s, got 2.78 s | Under the G5 coverage tracer the in-process timing measures the tracer. This is the same issue as the G54 row | The same ruling (b): the functional check in process, then the timing in a clean `python -I` subprocess when the in-process time exceeds 100 ms. 1/1, and 1/1 under `--cov` |
| `test_cli.py::test_refused_commands_touch_no_env_socket_or_db[bits rebuild]` | no `BITSCAN_*` read, got `['BITSCAN_BITS_DIR']` | Stale. `bits rebuild` was still listed as an unimplemented stub, but TASK-166 implemented it, and #107 (a) lets it read the non-secret `BITSCAN_BITS_DIR` | `["bits"]` stays a stub. New row `test_bits_rebuild_without_its_folder_reads_only_bits_dir`: exit 2, no database module loaded, only `BITSCAN_BITS_DIR` read. 1/1 |
| `test_login.py::test_documented_400_matches_what_the_app_returns` | 400, got 503 for `POST /policies/import` | Its `Runtime` has `catalog=None`, the state "in tests and the OpenAPI export", where the route answers 503 first. In `serve` the catalog is present, and a bad body is 400 even during start-up (the body is parsed before the catalog is called) | The test's `Runtime` gets a stub catalog that the bad body never reaches. 1/1 |

## G54 measurement fix (lead ruling (b), 2026-10-28)

- **Cause.** In a pytest test, `sys.gettrace()` and `sys.getprofile()` are None, `sys.monitoring` has no tool, and the flags show no dev mode. The same `"a;" * 8192` lexing measured 55–59 ms in one pytest run and 103.5 ms in another, against 56 ms in a plain script. Thread CPU time still scales with core speed and contention on this shared WSL machine, so the in-process best of five had no headroom.
- **Change.** In `test_pathological_inputs_bounded` (all ten parameters), the functional assertions stay in process, and the timing runs in a clean `python -I` subprocess, best of 10, asserted < 100 ms. The bound is unchanged. `test_long_inputs_up_to_16384_chars` follows the same rule (see G18).
- **Plant.** A quadratic lexer (`len(list(src[:pos]))` per token) → 6 of 10 parameters red.
- Recorded in `work/reports/TASK-145-test.md`.

## New gate files

- `manager/tests/test_catalog_alerts_pg.py` (G60). It raises each of the six M7 alert kinds through its real path:
  - `policy_imported` (pipeline; the changed Execute with its `shadow` flag);
  - `policy_import_rejected` (an auto import of `rm x`, with `fail:auto` +1);
  - `policy_deleted` (the delete service);
  - `policy_reenabled` (PATCH service and file);
  - `policy_rebuilt` (the rebuild);
  - `catalog_integrity_failed` (the start-up).

  Each test checks the one audit entry (action, target, actor, `alert` true, kind), the counter +1 exactly, and delivery of that entry to a recording sink through `Shipper.run_once`; a clean start-up raises none.
- `manager/tests/test_readme_m7_walk_linux.py` (CHK-M7-305). A real `serve` over HTTPS with a temporary bits folder, fake OpenBao and sink, an admin with a TOTP session and a `bsk_` token. One row per README "Policies" step:
  - start-up import; the watcher importing a copied file; ignored names;
  - rename in place; BIT007; the `auto` skip; version +1;
  - upload (keys, `policy-<id>.bit`, the client name only in the history, `bsk_` allowed, a rejection with every finding, 413 over 5 MiB, 409 for a server policy); the server file taking over an upload (move audited);
  - list and detail keys; PATCH (override, `?status`, clear + `policy_reenabled`);
  - DELETE (`bsk_` refused, 204, the alert, 409 `conflict`, 404, 409 `policy_managed_on_server`, PATCH of a deleted policy 409, revival with the same id); import history (keys, newest first, modes and outcomes);
  - rebuild (`bsk_` refused, 202, the task result shape, `policy_rebuilt`); `bits rebuild` (lines, summary, exit 0);
  - removing a file deletes it; `catalog_integrity_failed` at a restart with a damaged catalog; the 503 with `Retry-After: 10` while the start-up can't finish;
  - the hard-link warning and the 8 KiB sink note present.

  `sudo` and the fixed `/etc/bitscan/secrets/app.dsn` are replaced by `bits_main` with a temporary DSN file (the fixed path is TASK-166's row).

## Mutation table CHK-M7-320 to -371

| Row | Plant | Result | Evidence |
| --- | --- | --- | --- |
| 320–323 | XXE, DTD, entities, oversize cap in the parser | red | `TASK-141-test.md`; TP-M7-30 (320, 321, 323) |
| 324 | import route cap removed or raised | red | `TASK-162-test.md`; TP-M7-30 |
| 325 | BIT013 with Python `re` | red | `TASK-142-test.md` |
| 326 | BIT013 skipped for `not_regex` | red | `TASK-144-test.md` |
| 327–331 | BIT102 substring, path names, nested scripts, wrappers, redirects | red | `TASK-146-test.md` (r1, the rules now in the tree; r2 deferred) |
| 332 | lexer errors pass (fail open) | red | `TASK-145-test.md`, `TASK-146-test.md` |
| 333 | BIT102 skipped in rebuild or upload | red | `TASK-154-test.md` (333a, 333b) |
| 334 | BIT001/BIT002 still run content rules | red | `TASK-143-test.md` |
| 335 | BIT015 removed | red | `TASK-151-test.md`; TP-M7-30 |
| 336, 337 | f-string SQL | red | `TASK-148-test.md`, `TASK-150-test.md` |
| 338 | a commit per plugin | red | `TASK-151-test.md` |
| 339 | `bit_import` in the catalog transaction | red | `TASK-149-test.md`, `TASK-154-test.md` |
| 340 | late exception swallowed and committed | red | `TASK-154-test.md` (340a, 340b; the fuzz) |
| 341–346 | API token on DELETE and rebuild; sink gate off; operator upload and delete | red | `TASK-162/163/164-test.md` (tester-m7d); TP-M7-30 (341, 343, 345, 346) |
| 347, 348 | `xml.etree` in `parse.py`, `re` in `validate.py` | red | `TASK-141-test.md`, `TASK-144-test.md` |
| 349 | no `policy_imported` | red | `TASK-154-test.md`; TP-M7-30 |
| 350 | no `policy_import_rejected` or failure count | red | `TASK-154-test.md` (350a, 350b) |
| 351 | no `policy_deleted` | red | `TASK-152-test.md` |
| 352 | no `policy_rebuilt` | red | `TASK-157-test.md` (plant b8: 6 failed) |
| 353 | no `policy_reenabled` on PATCH | red | `TASK-161-test.md` |
| 354 | import alert drops Executes or flags | red | `TASK-153-test.md`; TP-M7-30 |
| 355 | no `catalog_integrity_failed` | **red, run here** | the integrity alert's emit removed → 4 failed (`test_catalog_alerts_pg` integrity row and three start-up rows); also `TASK-158-test.md` s7, s8 |
| 356 | the catalog lock removed | red | `TASK-147-test.md`, `TASK-152-test.md` |
| 357 | `O_EXCL` or `O_NOFOLLOW` removed | red | `TASK-155-test.md` (u1–u4, u13+u4); TP-M7-30 |
| 358 | client name in the stored path | red | `TASK-155-test.md` (u11), `TASK-162-test.md`; TP-M7-30 |
| 359 | rejected upload replaces the file, or rollback leaves the temp | red | `TASK-155-test.md` (u5, u9, u12) |
| 360 | upload of a server-folder policy accepted | **red, run here** | the `PolicyManagedOnServer` decision removed → 2 failed (`test_uploads_pg` server-folder row, `test_policy_import_api_pg` 409 row) |
| 361 | PATCH accepts `execute` | red | `TASK-161-test.md` |
| 362 | CLI DSN from env or argv | red | `TASK-166-test.md` (c1) |
| 363 | symlinks in the server folder followed | red | `TASK-156-test.md` (f4, f5, f13); TP-M7-30 |
| 364 | rebuild changes `agent` (or `scan_result`, `audit_log`) | **red, run here** | `UPDATE agent SET hostname = hostname \|\| 'x'` inside the rebuild → 1 failed (`test_untouched_tables_stay_untouched`) |
| 365 | hard DELETE or no job cancel | red | `TASK-150-test.md`, `TASK-152-test.md` |
| 366 | sample with `rm`, or a shared id | red | `TASK-174-test.md`, `TASK-175-test.md` |
| 367 | watcher follows non-`.bit` files (or subfolders) | **red, run here** | the `.bit` name test removed → 1 failed (`test_ignored_names_and_kinds`); hidden names `TASK-159-test.md` w2. Subfolders give no inotify event in a non-recursive watch; the subfolder row stays green by construction |
| 368 | integrity check before the reconcile | red | `TASK-158-test.md` (s1: 5 failed) |
| 369 | override ignored; +1 on identical hash; auto/manual skip | red | `TASK-148/151/154-test.md` |
| 370, 371 | `dangerouslySetInnerHTML`; API token on the rebuild screen | red | `TASK-168-173-test.md` |

## r1 re-run (TASK-146 r2 deferred, 2026-10-29)

The r2 rows that were NOT RUN are replaced by this run on the restored r1 tree:
- `bit102.py` is byte-identical to c6b7e13 (sha256 `279291cf…`);
- `bit102_wrappers.py` and `bit102_braces.py` are gone, and nothing in `manager/` imports them;
- the BIT102 tests and the `bits/tests` corpora are unchanged since r1.

The run used a fresh copy `/root/bstest-m7-r1`, `CI=true`, `PYTHONPATH` pinned and `-n 2` (5,135 MB free). The `R2_PENDING` exclusion was dropped from `test_import_pipeline_pg.py`.

| Row | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-191 (all fixtures) | `test_import_pipeline_pg.py::test_each_rejecting_fixture_writes_its_rejected_row_and_alert` | PASS | 150/150, including the six BIT102 fixtures `rm`, `redirect`, `systemctl-stop`, `sed-i`, `bash-c-subst` and `unlexable`: each gives a `rejected` row with exactly its manifest codes, one rejected alert, the failure count, and no catalog change |
| G59 re-run | `test_bits_samples_pg.py` | PASS | 50/50 on r1 |
| r1 BIT102 suites | `test_bit102.py`, `test_bit102_lexer.py`, `test_bit_validate.py`, `test_bit_fixtures.py` | PASS | 1,160/1,160 (as the r1 record), 173/173, 687/687, 227/227 |
| total | the six items above | PASS | **2,447/2,447 passed**, 0 failed, 0 errors, 0 skipped |
| gates | whole-tree `ruff check`, `ruff format --check`, `mypy --strict` (CI form) | PASS | clean, 310 files; no import of the removed modules |

## NOT RUN

| Row | Reason |
| --- | --- |
| TS §8.3 Sandbox "full CIS plugin set under the sandbox" | no runner until M10 (gate section) |
| End-to-end import on VMs; load tests | M11 nightly; deferred by the user (gate section) |
