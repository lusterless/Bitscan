# TASK-186 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (job state rules, high risk). REQ-206, REQ-217 at rule level; TS §4.4 L562–L582, §3.3 L222, §6.1 L1071; #124 (a), (d), #127 (a)–(c). Code under test: `bm/services/jobs/states.py` (impl-manager-m9, `work/reports/TASK-186-impl.md`; sha256 `57d2f6ed1463afee…`). Test files (new): `manager/tests/test_job_states.py`, and in `manager/tests/test_jobs_property.py` `test_state_machine_walks` and `test_deadline_is_the_integer_ceiling`. Plan rows: CHK-M9-001 to -014, -080, -081 (`tests/m9/test-plan.md`). The tests were written from the plan's expected values before the code was read. Then they were bound to the interface: `allowed(old, new)` is the transition check, and the module also has `TRANSITIONS`, `NEVER_STARTED_AFTER` and `MAX_PARALLEL_MIN/MAX`.

## Runs

| Run | Command (W: `/root/bstest-m9-base`, venv `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned to the copy, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_job_states.py tests/test_jobs_property.py::test_state_machine_walks tests/test_jobs_property.py::test_deadline_is_the_integer_ceiling` | **240/240 passed**, 0 failed, 0 errors, 0 skipped |
| r0 (all M9 unit and property files, for context) | `pytest` over the 8 M9 unit and property files | 672/674 passed, 2 failed (both TASK-191 DST rows), 0 errors, 0 skipped |
| plants | 9 plants, each in its own `/root/bstest-m9-mut-<id>` (removed after each; the import path was checked to be the copy) | 9/9 red |
| CHK-M9-383 (L) | `import re` prepended to each of the 7 W1 pure modules in `$TEMP/m9t-mut-383`, then `ruff check --config manager/pyproject.toml` | red: 7 × TID251 |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on `states.py` and the test files | clean |

## Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-001 | CODE | W | r1 | PASS | `FINAL` = {completed, expired, cancelled} and `ACCEPTING` = {dispatched, running, failed, partial, completed}, both frozensets. `get_args(JobState)` is the eight TS §4.4 states | 2026-10-30 |
| CHK-M9-002 | CODE | W | r1 | PASS | All 64 ordered pairs of the eight states: `allowed()` is True for exactly the 14 REQ-206 pairs (p→p included, r→r refused). `TRANSITIONS` equals that set and is read-only (`TypeError` on assignment). No pair leaves a final state. Unknown names → False | 2026-10-30 |
| CHK-M9-003 | CODE | W | r1 | PASS | A hand-written (state × event) table: 8 states × 13 events (pull, 6 batch shapes, deadline none/some/all, 24 h, cancel, pickup) = 104 pairs. 97 are asserted and the table has exactly 7 n/a rows. Those are running × 24 h, and failed/partial × the three deadline events. The sweep's candidate filter applies them (CHK-M9-120, tester-m9b). Every batch move is an allowed transition | 2026-10-30 |
| CHK-M9-004 | CODE | W | r1 | PASS | From `dispatched`, an empty batch and a non-empty one both give `start=True`. The state is running / partial (final) / completed (all, even when not final) | 2026-10-30 |
| CHK-M9-005 | CODE | W | r1 | PASS | From `running`, `start` is never True (0/1/50 stored × all × final). A non-final batch with plugins missing stays running | 2026-10-30 |
| CHK-M9-006 | CODE | W | r1 | PASS | From `failed` and `partial`, `stored=0` leaves the state unchanged whatever the flags say. `stored>0` gives partial, or completed when all have results. The REQ-217 (4) rows hold | 2026-10-30 |
| CHK-M9-007 | CODE | W | r1 | PASS | `completed` → completed for all 8 flag combinations. `queued`, `expired`, `cancelled` and `bogus` raise `ValueError`. `BatchOutcome` is frozen | 2026-10-30 |
| CHK-M9-008 | CODE | W | r1 | PASS | `after_deadline`: (F,F) → failed, (T,F) → partial, (T,T) → completed | 2026-10-30 |
| CHK-M9-009 | CODE | W | r1 | PASS | REQ-206 (2): Σ95/2 → +648 s, Σ30/8 → +604 s, Σ3,000,000/1 → +3,000,600 s exactly (microsecond 0). Ceiling boundaries 4/2, 5/2, 1/8, 8/8, 9/8, 3,000,000/8 and 600/7 hold. The start's microseconds are kept. A `+08:00` start gives the same instant. A tuple is accepted | 2026-10-30 |
| CHK-M9-010 | CODE | W | r1 | PASS | `max_parallel_plugins` 0, −1, 9 and 100 raise `ValueError`; 1 and 8 are accepted; `[]` and `()` raise. **Recorded, not asserted:** `True` is taken as 1 (+630 s); timeouts 0 and −5 are accepted (+600 s, +598 s). The inputs come from the validated payload (`ComplianceJob` timeout 1–600) and the 1–8 setting | 2026-10-30 |
| CHK-M9-011 | CODE | W | r1 | PASS | For each accepting state: `D`, `D+7d−1µs` and `D+7d` accepted; `D+7d+1µs` and `D+7d+1s` refused. `queued`/`expired`/`cancelled` refused at D, D+1 s and D+1 d. `inventory` refused in all 8 states. Kind `bogus` and `dispatched_at=None` refused. **Recorded:** `now` before `dispatched_at` is accepted | 2026-10-30 |
| CHK-M9-012 | CODE | W | r1 | PASS | `LATE_WINDOW` 7 d, `DEADLINE_SLACK` 10 min, `NEVER_STARTED_AFTER` 24 h, `MAX_PARALLEL_MIN/MAX` (1, 8) | 2026-10-30 |
| CHK-M9-013 | CODE | W | r1 | PASS | AST import closure of each of the 7 W1 pure modules (explicit imports and their parent package inits) reaches no `db`, `repositories`, `api`, `app`, `cli`, `runtime`, `psycopg`, `fastapi`, `re`, `logging`, `socket` or `subprocess`. No system-clock call (`datetime.now`, `time.time` …; the idempotency store reads only its injected clock) and no `open`/`print`/`eval`. See note 1 | 2026-10-30 |
| CHK-M9-014 | CODE | W | r1 | PASS | Under a `sys.addaudithook` probe, 20 × (64 transition checks, acceptance, all batch shapes, deadline outcomes, `deadline_at`) see no `open`, socket, `subprocess.Popen` or `os.system` event | 2026-10-30 |
| CHK-M9-080 | CODE | W | r1 | PASS | 5,000 hypothesis walks of up to 20 events over 1–6 plugin jobs. No event leaves a final state. `failed`/`partial` reach only completed/partial. `running` is never re-entered. Every move is allowed. `start` comes only from dispatched and only once | 2026-10-30 |
| CHK-M9-081 | CODE | W | r1 | PASS | 3,000 cases (1–5,000 timeouts of 1–600, mpp 1–8): deadline − start − 600 s = `(Σ + mpp − 1) // mpp` exactly | 2026-10-30 |
| CHK-M9-325 | CODE | W | plant: `cancelled` added to `ACCEPTING` | PASS (red) | 9 failed: `test_final_and_accepting_sets`, the 6 cancelled × batch table rows, `test_non_accepting_states_are_refused_at_any_time[cancelled]`, `test_state_functions_do_no_io` | 2026-10-30 |
| CHK-M9-326 | CODE | W | plant: `now < dispatched_at + LATE_WINDOW` | PASS (red) | 5 failed: `test_acceptance_window_boundary[*]` (the +7 d exactly row) | 2026-10-30 |
| CHK-M9-334 | CODE | W | plant: `start = True` | PASS (red) | 8 failed: `test_running_never_restarts`, `test_running_outcomes`, the 6 running × batch table rows | 2026-10-30 |
| CHK-M9-335 | CODE | W | plants: (a) `sum // mpp` (floor); (b) `mpp` ignored (`// 1`) | PASS (red) | (a) 8 failed and (b) 10 failed: `test_deadline_rows` (Σ95/2, Σ5/2, Σ1/8 …), `test_deadline_keeps_the_start_microseconds_and_instant`, `test_deadline_accepts_a_tuple` | 2026-10-30 |
| CHK-M9-336 | CODE | W | plant: `DEADLINE_SLACK = timedelta(seconds=10)` | PASS (red) | 14 failed: every deadline row, `test_deadline_is_exact_for_large_sums`, `test_window_and_slack_constants` | 2026-10-30 |
| CHK-M9-337 | CODE | W | plant: `partial` on any batch with plugins missing | PASS (red) | 6 failed: `test_dispatched_batch_starts_the_job`, `test_running_outcomes`, 4 table rows | 2026-10-30 |
| CHK-M9-338 | CODE | W | plant: the `completed` branch returns `partial` | PASS (red) | 8 failed: `test_completed_job_never_changes`, the 6 completed × batch table rows and the G67 walk `test_state_machine_walks` | 2026-10-30 |
| CHK-M9-390 | CODE | W | plant: `accepts_results` ignores `kind` | PASS (red) | 6 failed: `test_inventory_jobs_are_never_accepted[5 accepting states]`, `test_unknown_kind_and_missing_dispatch_are_refused` | 2026-10-30 |
| CHK-M9-383 | CODE | L | plant: `import re` in each pure module | PASS (red) | ruff TID251 "`re` is banned" × 7 (G1); CHK-M9-013 also lists `re` in `FORBIDDEN_EXACT` | 2026-10-30 |

## Acceptance (TASK-186 row: "REQ-206 (1)–(5) hold")

- (1) table of every (state, event) pair, with the pairs the table does not allow refused → CHK-M9-002, -003 (and -004 to -008).
- (2) deadline rows, exact integer arithmetic, `ValueError` → CHK-M9-009, -010, -081.
- (3) property: final states are kept, failed/partial reach only completed/partial, running is not re-entered → CHK-M9-080.
- (4) acceptance window, exactly 7 d accepted, + 1 µs refused, queued/expired/cancelled/inventory refused, completed accepted → CHK-M9-011.
- (5) import graph → CHK-M9-013.

## Notes

1. **For the reviewer (not a TASK-186 defect).** `states.py` itself imports only the stdlib. But TASK-204's in-progress `services/jobs/__init__.py` now imports `services/jobs/intake.py`, so `import bitscan_manager.services.jobs.states` in a fresh interpreter also loads `repositories.job_intake`, `repositories.settings`, `repositories.audit_log` and psycopg. `test_package_init_effect_is_recorded` records this. The impl report's line "`pull.py`, which is pure" no longer describes the package init. The pure modules stay pure as source, but they are not import-light. Whether the package init should re-export the intake service is TASK-204's call.
2. The mutation row CHK-M9-338 names G66 and G67; both are red.
