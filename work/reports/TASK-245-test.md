# TASK-245 TEST: PASS

Tester: tester-m11d, 2026-11-08 (taking over from tester-m11b, brief `work/plans/TASK-245-test-brief.md`). High risk with the user's second look (PD-47), so it was tested to full rigor: every security row, boundary and race planted.

- **Scope:** REQ-277 (1)–(4) and REQ-275 (2) at the wiring level: TS §2.1 L103, §5.2 L829–L835, §5.3 L1051, §8.6 L1309; #150 (d), (h); PD-51; the lead's rows (a)–(e) of the brief.
- **Code under test** (impl-manager-b, `work/reports/TASK-245-impl.md`): `bm/services/scheduler/runner.py` (sha256 `0d25476d2d88ddaa…`), `bm/cli/serve.py` (`e8f9c603a20d1695…`), `bm/services/audit/shipper.py` (`219f34c7df01d315…`), `bm/db/pool.py` (`11412b118e1776a2…`).

Test files:
- `manager/tests/test_retention_wiring.py` (new): 30 functions, 36 items. Unit rows with a fake scheduler and a real `BackgroundScheduler`; PostgreSQL rows on a module-owned server (retention tables emptied as owner per test, `m.retention_database`); serve's own `build_runtime` in-process.
- `manager/tests/test_serve_retention_linux.py` (new): 5 functions, 8 items, the real `bitscan-manager serve` through a tracing launcher.
- `manager/tests/test_serve_scheduler_linux.py` (PD-51 edit, L441–L451): one "pool closed" becomes two.
- `manager/tests/test_scheduler_runner.py` (PD-51 docstring only, L201–L206): the three-argument runner's job set is unchanged.

The tests were drafted from REQ-277, the brief and the CHK rows before the code was read, then bound to the names (`retention_db=`, `shipped_through=`, `RETENTION_DELAY`, `Shipper.shipped_through()`).

## Runs (WSL `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers, `--tb=short`, tokens masked)

| Run | Command | Result |
| --- | --- | --- |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on the four test files | clean |
| 1 | `pytest -n 3 tests/test_retention_wiring.py` | 36/36 passed, 0 failed, 0 errors, 0 skipped |
| 2 | `pytest -n 3 tests/test_serve_retention_linux.py` | 7/8 passed, 1 failed (a test bug, below), 0 errors, 0 skipped |
| 3 | the same, after the fix | 8/8 passed, 0 failed, 0 errors, 0 skipped |
| G41 | `e2e/agent_manager.sh /root/m11t/tree /root/m10vm/out … m4b-sysd-u24` (`m11t-scripts/g41.sh`, own venv `/root/m11t/venv-g41`; the M10 `.deb` `bitscan-agent_0.2.0~pre1-1`, sha256 `bb3a8785…0814`, agent unchanged in M11) | **OK 23/23 rows**, rc 0: real serve from the M11 tree, enrol held → approve → heartbeat → first inventory → package search → dpkg-change uploads and the hold-off → revoke → 401 stops the loops; no `bse_`/`bsa_` token in the journal or `serve.log`. Log `/root/m11t/g41/run.log` (masked), rows `rows.jsonl` beside it |
| 4 | affected files, `-n 3`: `test_scheduler_runner.py`, `test_serve_scheduler_linux.py`, `test_serve_linux.py`, `test_serve_catalog_linux.py`, `test_serve_flusher.py`, `test_webui_serving.py`, `test_shipper.py`, `test_shipper_pg.py`, `test_scan_schedules_pg.py`, `test_invariants_m3.py`, `test_security_m2.py`, `test_security_m3.py`, `test_retention_pg.py`, `test_retention_race_pg.py` | 304/304 passed, 0 failed, 0 errors, 0 skipped |

Run 2's failure was mine: `assert_pool_order` compared trace timestamps, and "scheduler stopped" and "pool closed bitscan_retention" were written in the same 0.1 ms tick (`10307.0231 < 10307.0231`). The check now compares trace order (one writer, appended under a lock). No product bug found.

## Report rows (for tests/m11/report.md)

`W` = `manager/tests/test_retention_wiring.py`, `L` = `manager/tests/test_serve_retention_linux.py`.

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-196 | `W::test_four_jobs_and_retention_ten_minutes_after_start_on_its_row`, `::test_a_changed_retention_row_is_the_interval[60,43200,86400]`, `::test_a_missing_retention_row_gives_86400`, `::test_an_unreadable_database_gives_86400_and_logs_the_type_only`, `::test_the_real_scheduler_holds_the_retention_job`, `::test_the_retention_row_is_read_at_start_up_from_the_database` | PASS | The job set is exactly `{inventory, offline_sweep, scan_schedules, retention}`, four jobs. Retention runs `run_retention`; its interval is the row (3,600; 60, 43,200 and 86,400 at both CHECK ends) and `misfire_grace_time` equals it; `max_instances` 1, `coalesce` true; next run start + 10 min, while the other three run at start. The row is read once, at start-up, on the app pool, and the retention pool is untouched. Missing row → 86,400; read failure → 86,400 with the seeded 21,600, 60 and 30, logged as `{exc_type: ConnectionError}` only, no canary. The real `BackgroundScheduler` holds the same job. On PostgreSQL: seeded row 86,400, owner-changed row 43,200, deleted row 86,400. |
| CHK-M11-196 (later steps) | `W::test_a_failing_step_leaves_the_later_steps_run_through_the_runner` | PASS | REQ-277 (1), (4) through `SchedulerRunner.run_retention()` on PostgreSQL: the snapshots step raises. Its rows stay; scans, inventory jobs, requests (2), tokens (3) and packages (2) are deleted. One `retention step failed` record `{step: snapshots, exc_type: RuntimeError}`, no `scheduler run failed`, no canary. |
| CHK-M11-196 (serve, lead's row (a)) | `L::test_serve_schedules_four_jobs_with_retention_from_its_row[plain]` | PASS | The real serve: after `start()` the scheduler holds exactly the four jobs, each `max_instances` 1. Retention: the interval is the owner-changed row (43,200, misfire 43,200), `coalesce` true, next run start + 600 to 630 s; no retention run during the test. |
| CHK-M11-196 (runner wiring) | `W::test_run_retention_gets_the_retention_pool_the_clock_cursor_and_wake`, `::test_a_failing_retention_run_is_logged_by_type_and_the_next_run_happens`, `::test_unconfigured_run_retention_does_nothing` | PASS | The run's transaction opens on the retention pool (retention 1, app 0); `now` is the clock's; `shipped_through` is the given function itself; `wake` is the shipper's. A run that raises gives one `{job: retention, exc_type: ValueError}`, `exc_info` none, no canary, and the next run happens. |
| CHK-M11-197 | `W::test_stop_during_a_retention_run_gives_up_at_its_next_transaction`, `W::test_stop_during_a_real_retention_run_gives_up_at_the_next_transaction`, `L::test_sigterm_during_a_retention_run_waits_then_closes_the_retention_pool` | PASS | **Unit, real scheduler:** stop() between two transactions sets the flag and waits; the next transaction raises `SchedulerStopping` without reaching the retention pool (opened 1); stop() returns after the run ended; one `{job: retention, exc_type: SchedulerStopping}`; no run after. **PostgreSQL, real `run_retention`:** stop() during the scans step's first chunk. That chunk commits (2 scans); each of the six later steps logs `{step, exc_type: SchedulerStopping}` once; no `bitscan_retention` statement after the flag; every other row stays; stop() returns in under 10 s. **Serve:** SIGTERM during a run → the run ends after the signal, then `pool closed bitscan_retention`, then the app pool; exit 0. Exactly one retention failure, `SchedulerStopping`, with only job and type; no step ran; no run started after the signal; no `PoolClosed`. |
| CHK-M11-198 | `L::test_serve_runs_retention_as_bitscan_retention`, `L::test_an_unusable_retention_dsn_file_fails_start_up[missing,directory,empty]` | PASS | Serve's retention run gets the pool named `bitscan_retention`. Its transaction's `current_user` is `bitscan_retention`, and while serve runs, `pg_stat_activity` shows a `bitscan_retention` session, gone after stop. The run deletes the `old` row and keeps the `inside` row for each of scans, inventory jobs, snapshots, requests and tokens, and prunes the unreferenced package. The aged audit prefix (3 entries) is deleted under one checkpoint with `last_deleted_id` = its last id, so the cap is the live shipper's cursor. All seven steps have `skipped` none. Seven retention log lines, each with only step, deleted, chunks, skipped and exc_type; no canary in the output (REQ-277 (4)). Pools open app, then retention, before the job set; close retention, then app, after `scheduler stopped`, with nothing after. An unusable file exits 2 before binding, with `serve: BITSCAN_RETENTION_DSN_FILE: cannot read the file it points to` (missing, a directory) or `…: file is empty`. The output has no DSN or password of either role and no traceback. |
| CHK-M11-199 | `W::test_shipped_through_is_none_before_anything_is_queued`, `::…_is_the_last_id_written_to_the_disk_queue`, `::…_moves_one_batch_at_a_time`, `::…_stays_when_the_disk_queue_refuses`, `::…_after_a_restart_is_the_saved_cursor`, `::…_is_read_only`, `W::test_the_shippers_cursor_caps_the_audit_delete` | PASS | None when fresh, after an empty read and while the database is down. 3 once 1–3 are queued with the sink down (nothing delivered); still 3 after delivery; 5 after 4–5. 500, then 600, for a 600-entry backlog. None while the disk queue refuses, 2 after. 3 after a restart, before any cycle. Five calls change nothing: queue folder bytes and mtimes, depth, tail reads, sink sends, gate, wake. **As the cap, on PostgreSQL through the real shipper and runner:** the shipper has queued 3 expired entries, and 2 more expired entries lie above its cursor. The run deletes exactly the 3, with checkpoint `last_deleted_id` = the cursor and `deleted` 3. After the shipper queues the rest, the next run deletes the 2; `verify_chain` OK. |
| CHK-M11-450 | `W::test_build_runtime_always_gives_the_runner_the_retention_pool_and_cursor`, `::test_no_variable_toggles_the_retention_job`, `::test_no_setting_toggles_the_retention_job[4 bodies]`, `::test_no_route_touches_retention_or_the_scheduler`, `::test_patch_settings_refuses_a_retention_field`, `L::test_serve_schedules_four_jobs_with_retention_from_its_row[toggles]` | PASS | **Lead's row (b).** `build_runtime` has no `if`, conditional or `try`. Its one `SchedulerRunner` gets `retention_db` (the `AppDatabase(bounded_dsn(config.retention_dsn), …, name='bitscan_retention')`) and `shipper.shipped_through`, and `ServeLifecycle` gets the same pool. Neither module reads `os.environ` or `getenv`. `load_serve_config` reads exactly the ten TS §8.6 names. `SettingsBody` and `SettingsPatch` have no retention field, and the patch refuses `retention_interval_s`, `retention_enabled`, `retention` and `scheduler_jobs`. No `openapi.json` path or operation names retention or the scheduler. Through the API, PATCH with a retention field is 400 `invalid_request`, settings unchanged. The real serve with four made-up switches (`BITSCAN_RETENTION_DISABLED=1`, etc.) still has the four jobs. |
| CHK-M11-451 | `W::test_serve_build_runtime_runs_retention_on_a_bitscan_retention_pool`, `W::test_every_statement_of_a_runner_run_is_bitscan_retention` | PASS | **Lead's row (d).** Serve's own `build_runtime`, in-process: the retention pool is not the app pool. It is named `bitscan_retention`, with min 0 and max 1, and its DSN's user is `bitscan_retention` (asserted, never printed). The runner wraps exactly that pool, and the app pool separately. The runner's cursor equals the runtime shipper's `shipped_through`. `SELECT current_user` on it gives `bitscan_retention`. A statement spy over a whole run through that runner sees only `bitscan_retention` (more than 10 statements), and the expired rows go. |
| CHK-M11-452 | `W::test_one_retention_argument_without_the_other_raises[retention_db,shipped_through]` | PASS | **Lead's row (c).** Either one alone raises `ValueError` ("…go together"). |
| CHK-M11-453 | `W::test_slow_retention_runs_never_overlap` | PASS | **Lead's row (e), one at a time:** a real scheduler with a 1 s interval and 1.6 s runs (first run moved to start): peak 1 and at least 2 runs. |
| CHK-M11-454 | `L::test_a_refused_retention_login_is_logged_by_type_only` | PASS | The retention DSN carries a wrong password (a canary). Serve still starts; the run fails as `{job: retention, exc_type: DatabaseUnavailable}` with nothing else; SIGTERM exits 0; the output has neither the canary nor the DSN, and no traceback. |
| CHK-M11-342 | plants CHK-M11-342 and -342b below | PASS (plant red) | Retention through the app pool, in serve or in the runner, turns `W` and `L` red. |
| CHK-M11-356 | plants CHK-M11-356 and -356b below | PASS (plant red) | Retention not scheduled, in serve (the brief's plant) or in the runner, turns `L` (a) and `W` red. |

### PD-51: earlier checks replaced by requirement, old → new

| Old check | File and lines | New | Result |
| --- | --- | --- | --- |
| CHK-M3-233 / CHK-M9-219 (stop record: one "pool closed") | `test_serve_scheduler_linux.py` L441–L451 | Two "pool closed" events, both after the single "scheduler stopping" and after the running sweep ended; nothing after the last. The pool names and order (retention, then app) are CHK-M11-198 in `L`. | PASS in run 4 (`test_sigterm_waits_for_the_running_sweep_and_nothing_runs_after_close`) |
| CHK-M9-218 (job set, from CHK-M3-230) | `test_scheduler_runner.py` L210, L235 | Unchanged for the three-argument runner (docstring updated); the four-job row is CHK-M11-196, plus `W::test_without_the_retention_pool_three_jobs_and_no_retention_read` (and the retention row is not read). | PASS in runs 1 and 4 |
| CHK-M9-219 (failure job names) | `test_serve_scheduler_linux.py` L461, `traced` L395–L399 | Unchanged: retention first runs at + 10 min, after any of these serve runs end. | PASS in run 4 |
| TASK-232's M11 query-parameter sets | `test_invariants_m3.py` L114–L312 | Unchanged by this task. | PASS in run 4 |

## Plants (throwaway copies; plants `/root/m11t/plants-245.json` from `m11t-scripts/tmp/mk_plants_245.py`; log `/root/m11t/logs/plants-245.jsonl`)

21 of 21 red. None missing an expected test. No copy was left (`/root/m11t/mut-*`: 0), and the four product files' hashes are unchanged.

| Plant | Change | Red tests (all expected) |
| --- | --- | --- |
| CHK-M11-356 | serve: `SchedulerRunner(db, clock, shipper.wake)`, without the retention arguments (the brief's plant) | `L::…four_jobs…[plain,toggles]`, `W::test_build_runtime_always…`, `W::test_serve_build_runtime…` (4) |
| CHK-M11-356b | runner: the retention job never appended (`if False:`) | `W::four_jobs`, `W::real_scheduler`, `L::four_jobs` ×2 (4) |
| CHK-M11-342 | serve: `retention_db=db` (the app pool) | `W::build_runtime_always`, `W::serve_build_runtime`, `L::runs_retention_as_bitscan_retention` (3) |
| CHK-M11-342b | runner: `run_retention(self._db, …)` | `W::run_retention_gets…`, `W::every_statement…bitscan_retention`, `L::runs_retention…` (3) |
| P245-delay-0 | `RETENTION_DELAY = timedelta(0)` | four_jobs, changed_row ×3, unreadable, real_scheduler, `L::four_jobs` ×2 (8) |
| P245-delay-9min | `RETENTION_DELAY = timedelta(minutes=9)` (boundary) | four_jobs, real_scheduler (2) |
| P245-fallback-86399 | seeded fallback 86,399 | missing_row, unreadable, PG row read (3) |
| P245-row-ignored | retention interval forced to the seeded value | four_jobs, changed_row [60, 43200], real_scheduler, PG row read, `L::four_jobs` ×2 (7; changed_row[86400] rightly green) |
| P245-max-instances-2 | retention `max_instances=2` | four_jobs, real_scheduler, slow_never_overlap, `L::four_jobs` ×2 (5) |
| CHK-M11-197-unwrapped | retention pool not behind the stop flag | unit stop, PG real stop, build_runtime, `L::sigterm` (4) |
| P245-no-valueerror | the pair check removed | both `one_retention_argument…` (2) |
| P245-close-after-app | retention pool closed after the app pool | lifecycle, `L::four_jobs` ×2 (3) |
| P245-no-close | retention pool never closed | lifecycle, `L::four_jobs` ×2 (3) |
| P245-no-open | retention pool never opened | lifecycle, `L::runs_retention…` (2) |
| P245-name-app | pool named `bitscan_app` | build_runtime_always, serve_build_runtime, `L::four_jobs` ×2 (4) |
| P245-cap-not-shippers | serve passes `shipped_through=lambda: 2**62` (#150 (d) cap bypassed) | build_runtime_always, serve_build_runtime (2) |
| CHK-M11-199-zero | `shipped_through` returns 0 instead of None | none_before_queued, stays_when_disk_queue_refuses (2) |
| CHK-M11-199-writes | `shipped_through` saves the state file | read_only (1) |
| CHK-M11-199-wakes | `shipped_through` wakes the shipper | read_only (1) |
| P245-unguarded | `run_retention` without `_guarded` | failing_run_logged, unit stop, `L::sigterm` (3) |
| P245-wake-none | the run gets `wake=None` | run_retention_gets… (1) |

## Acceptance (TASK-245: "REQ-277 (1)-(4) hold with a clock-controlled scheduler and a real `serve` in WSL, and the M3 and M9 scheduler suites pass except the PD-51 job-set rows")

| Criterion | Met | Rows |
| --- | --- | --- |
| REQ-277 (1): four jobs; the interval is the row; an exception in one step leaves the later steps run | yes | CHK-M11-196 (all four rows), -453 |
| REQ-277 (2): stop() during a run gives up at its next transaction and returns | yes | CHK-M11-197 (unit, PostgreSQL, serve) |
| REQ-277 (3): serve opens the pool from `BITSCAN_RETENTION_DSN_FILE` and closes it at stop; a missing file fails start-up (M2) | yes | CHK-M11-198, -451, -454 |
| REQ-277 (4): retention log lines hold step names, counts and exception types only | yes | CHK-M11-196 (later steps), -198 (serve log lines), -454 |
| REQ-275 (2): every retention statement as `bitscan_retention`, never the app pool | yes | CHK-M11-451, -198; plants CHK-M11-342, -342b |
| #150 (d): the cap is the shipper's cursor, read-only | yes | CHK-M11-199; plant P245-cap-not-shippers |
| Lead's rows (a)-(e) | yes | (a) CHK-M11-196 serve, plant CHK-M11-356; (b) CHK-M11-450; (c) CHK-M11-452; (d) CHK-M11-451, -198; (e) CHK-M11-196, -453 |
| M3 and M9 scheduler suites pass, except the PD-51 rows | yes | run 4 (304/304), PD-51 table |
| G41 after the `serve` wiring change | yes | 23/23 rows |

## Notes

- **White-box reads, kept small:** `runner._stopping` (only to release a run once stop() set the flag), `runner._scheduler`, `lifecycle._scheduler` and `_retention_db`, `pool._pool` and `_dsn` (asserted, never printed), `shipper._queue` and `_wake` (the read-only row).
- **For the reviewer:** the interval read is all-or-nothing (`start()` reads the three rows in one try). One failing read gives the seeded values for all three, as M3 did for two. That matches REQ-277's "86,400 s if it cannot be read" and is tested.
- **Not in this task:** the README walks (`test_readme_*_walk_linux.py`) also start serve. They were not re-run here, because TASK-252 rewrites the README under PD-51 and they belong to that walk. The full suite runs at the wave end.
- `deploy/tests/check_manager_host.sh` and `e2e/m6/*` were already modified in the tree; I did not touch them.
