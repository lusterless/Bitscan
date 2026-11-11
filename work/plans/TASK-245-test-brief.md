# TASK-245 TEST brief (from tester-m11b's handback, 2026-11-08)

TP-M11-13, CHK-M11-196 to -199; impl report `work/reports/TASK-245-impl.md`. Files changed: `bm/db/pool.py`, `bm/services/audit/shipper.py`, `bm/services/scheduler/runner.py`, `bm/cli/serve.py`.

## The lead's rows
- (a) Through the real `serve` (`test_serve_retention_linux.py`), the started scheduler has exactly four jobs, including `retention`.
- (b) No environment variable, setting or route can drop the retention job.
- (c) Passing only one of `retention_db` and `shipped_through` raises `ValueError`.
- (d) The retention pool's `current_user` is `bitscan_retention`, never `bitscan_app`.
- (e) `max_instances` is 1, and the first run is start + 10 min. The interval comes from the `retention` row, or 86,400 when the row can't be read.
- Plant: `serve` building the runner without the retention arguments must turn (a) red.

## Also
- CHK-M11-197: `stop()` during a run (the stop flag, `SchedulerStopping`).
- CHK-M11-199: `shipped_through()` is None while the cursor is 0, then the id of the last entry written to the disk queue; calling it changes no state.
- G41 re-run against the real manager in WSL.

## PD-51 rows, old → new
- CHK-M3-233 / CHK-M9-219 (`test_serve_scheduler_linux.py` L441–L445): one "pool closed" becomes two (retention, then app), both after "scheduler stopping", with nothing after the last.
- CHK-M9-218 (`test_scheduler_runner.py`) stays as it is for the three-argument runner; add a new four-job row for REQ-277 (1).
- The M11 query-parameter sets added to `test_invariants_m3.py` (from TASK-232).

## Setup to reuse
- `/root/m11t` (tester-m11's and tester-m11b's): `tree/`, `venv/`, `logs/`, and plant files `plants-2*.json`.
- Scripts: `C:\Users\kaiquan.koh\Documents\m11t-scripts\` (`sync.sh`, `lint.sh`, `run.sh`, `plant.py`), with generators in `tmp\`.
