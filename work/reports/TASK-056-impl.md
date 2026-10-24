# TASK-056 IMPL report: M3 alert kinds, threshold windows, metric definitions

REQ: REQ-065, REQ-070, REQ-073, REQ-075, REQ-079, REQ-086. Spec: TS §8.4 L1288–L1291, §2.1 L103; #61, #65, #66, #71.

## Files (4)

- `manager/bitscan_manager/services/audit/alerts.py`: 28 lines added.
  - `M2_ALERT_KINDS` holds the ten #50 kinds.
  - `M3_ALERT_KINDS` holds the **18 #71 kinds**: `enrolment_token_risky`, `enrolments_per_hour`, `reenrolment_approved`, `machine_id_mismatch`, `token_reuse`, `rotation_outside_window`, `rotation_new_ip`, `runner_helper_changed`, `settings_changed`, `redaction_default_removed`, `clock_skew`, `agents_offline`, `job_queue_age`, `inventory_stale`, `new_packages_burst`, `result_409_flood`, `agent_auth_failures`, `default_partition_rows`.
  - `ALERT_KINDS` is their union, 28 kinds. `raise_alert` accepts every one, and each is exported from zero (the existing loop).
- `manager/bitscan_manager/services/audit/thresholds.py`: new, 134 lines.
- `manager/bitscan_manager/services/audit/metrics.py`: about 45 lines added.
- `manager/bitscan_manager/services/audit/__init__.py`: re-exports the new names.

## Threshold windows (in memory, one manager instance, reset on restart, #65; every time from the Clock; thread-safe)

| Class | Behaviour | Used for |
| --- | --- | --- |
| `SlidingCount(clock, window, period, threshold)` | `.add(key, weight=1, threshold=None) -> bool` counts `weight` events now. It is True when the key's count inside the sliding `window` **exceeds** the threshold and the key has had no alert within `period`; then it records the alert. `threshold` overrides the constructor value per call, for a runtime setting. `.count(key)`, `.size()`. Idle keys and old alert times are pruned once per window. | #61 enrolments per token (60 min, setting); #65 (d) 401s per agent (1 min, > 20, 1 h); #65 (e) new packages (24 h, > 1,000, weight = new rows, 24 h); #65 (f) 409 flood (10 min, > 20, 1 h) |
| `OncePerPeriod(clock, period)` | `.fire(key) -> bool` is True at most once per key per period. | #65 (a) clock skew (1 h per agent); #66 queue age (1 h) |
| `ReArm()` | `.update(key, above) -> bool` is True when the condition has just become true, and again only after an `update(key, False)`. `.sync(above_keys) -> list` takes every key that holds now and re-arms the others. | #65 (b) offline share; #65 (c) stale inventory (until the next upload); #65 (g) default-partition rows |

The callers (TASK-064, 067, 068, 072, 073) build these with the #65 numbers and write the alert with `raise_alert`. Nothing in this module writes to the database.

## Metrics (in the existing `REGISTRY`; bounded labels only)

| Metric | Type | Labels |
| --- | --- | --- |
| `bitscan_alerts_total` | counter (unchanged) | `kind`, 28 fixed values |
| `bitscan_agents` | gauge, set at scrape time by TASK-079 | `status`, the 6 `agent_status` values, all pre-created at 0 |
| `bitscan_heartbeat_latency_seconds` | histogram, buckets 5 ms … 5 s; observed by TASK-072 | none |
| `bitscan_jobs_queued` | gauge, set at scrape time by TASK-079 | none |
| `bitscan_jobs_expired_total` | counter, increased by TASK-065 after commit | none |

No label holds a hostname, token, agent id or other unbounded value (REQ-086 (3)). prometheus_client also exports its default `*_created` series for the counter and the histogram, as `bitscan_alerts_created` already did.

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass. `mypy --strict`: pass for `bitscan_manager`.
- `pytest -q`: 1198 passed, 451 skipped and **2 failed, as intended**:
  - `tests/test_alerts.py::test_kinds_are_exactly_the_50_list` asserts `ALERT_KINDS` == the ten M2 kinds; it is now the #71 union.
  - `tests/test_alerts.py::test_every_kind_is_exported_from_zero_in_its_own_registry` asserts the registry holds only `bitscan_alerts`; it now holds the REQ-086 metrics too (REQ-055 (3) is superseded by REQ-086).

  Both are test-file updates (tester).
- Scratch probe with a fake clock:

  | Check | Result |
  | --- | --- |
  | 20 events in 10 min | did not fire |
  | the 21st | fired |
  | the 22nd | did not fire |
  | another key | did not fire |
  | 59 min later, 21 more | did not fire (inside the period) |
  | at 60 min | fired on the first add |
  | after a 3 h idle gap | `size()` dropped to the one live key |
  | 1,000 weighted | did not fire |
  | 1,001 weighted | fired |
  | `OncePerPeriod` | True, False, then True after 1 h |
  | `ReArm.update` sequence True, True, False, True | gave True, False, False, True |
  | `ReArm.sync` | gave `['a','b']`, `[]`, `[]`, `['a']` |
  | `generate_latest` | listed all 28 kinds and the five metric families |

## Deviations

None.
