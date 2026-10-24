# TASK-056 REVIEW: M3 alert kinds, threshold windows, metric definitions

Reviewer: reviewer. Date: 2026-10-23. REQ-065, REQ-070, REQ-073, REQ-075, REQ-079, REQ-086. Spec: TS §8.4 L1288–L1291 (metrics, alert delivery, immediate and threshold alerts), §2.1 L103 (one manager instance); #61 (enrolments per token: sliding 60 min, setting, once per hour), #65 (threshold windows, denominators and repeats), #66 (queue age once per hour), #71 (alert kinds). Inputs:
- `work/reports/TASK-056-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-100 to -105, `manager/tests/test_thresholds.py`, `test_alerts.py` updated for #71 and REQ-086; rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/services/audit/alerts.py` (+28);
- `manager/bitscan_manager/services/audit/thresholds.py` (new, 134 lines);
- `manager/bitscan_manager/services/audit/metrics.py` (+45);
- `manager/bitscan_manager/services/audit/__init__.py` (re-exports);
- the tester's two test files.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Decision conformance.**
  - `M3_ALERT_KINDS` is exactly the 18 #71 kinds. The union with the ten #50 kinds is 28, and every kind is exported from zero, so an alert always counts (REQ-079 (5)). `raise_alert` is unchanged: one audit entry with `detail.alert = true` and `alert_kind`, and the counter rises only on commit.
  - `SlidingCount` fires when the count inside the sliding window first exceeds the threshold, and then at most once per period per key. That fits #61, #65 (d), (e) (weighted by new package rows) and (f).
  - `OncePerPeriod` fits #65 (a) and #66.
  - `ReArm` fires again only after the condition was false in between, which fits #65 (b), (c) and (g).
  - Every time comes from the Clock. State is in memory behind a lock and resets on restart, which #65 accepts.
- **Metrics (REQ-086).** `bitscan_agents{status}` takes its values from the `agent_status` enum, all six pre-created. `bitscan_heartbeat_latency_seconds` (histogram), `bitscan_jobs_queued` and `bitscan_jobs_expired_total` have no labels. No label can hold a hostname, agent id or token (REQ-086 (3)). The module writes nothing to the database or the logs.
- **Scope.** Four files, as the task row lists. REQ-055 (3) ("only `bitscan_alerts` in its registry") is superseded by REQ-086 as recorded in the requirements, and `test_alerts.py` was updated for it.
- **Tests (my run, Windows).** `test_thresholds.py` and `test_alerts.py`: 64 passed. ruff, format and `mypy --strict` are clean on the 11 files. The tests cover:
  - exact threshold and threshold + 1 edges for the four #65 window shapes;
  - the window edge (59 s counts, 60 s does not) and a repeat exactly one period later;
  - 1,000 versus 1,001 weighted;
  - the per-call threshold override for the #61 setting;
  - a 20-thread race with exactly one alert;
  - pruning of 10,000 keys;
  - label names on the wire limited to `kind`, `status` and `le`;
  - the status values read from the spec DDL.

## Findings

None.

## Carry-overs (for the consuming tasks)

- **TASK-065.** Increase `JOBS_EXPIRED` in the transaction's `on_commit` hook, like `ALERTS_TOTAL`, so a rolled-back sweep step does not count.
- **TASK-064, 067, 068, 072, 073.** Pass the #65 numbers at construction, and for #61 pass `enrolment_alert_per_hour` per call through `threshold=`. Build each window once per process (in the runtime or the service module), not per request, or the counts reset on every call.
