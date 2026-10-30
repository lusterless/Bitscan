# TASK-198 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor; lead's second look (PD-39). REQ-209, REQ-211, REQ-212, REQ-227, REQ-229 (2); TS §2.3 L133, §3.3 L213, §3.5 L248, §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L547, L550, §6.5 L1165–L1182, §8.4 L1290; #3, #18, #122 (c)–(f), #125 (a)–(h), #129 (a), (b); SR §1.1. Code under test: `bm/services/jobs/queue.py`, `bm/services/audit/alerts.py` (`M9_ALERT_KINDS`) (impl-manager-m9, `work/reports/TASK-198-impl.md`), on TASK-188/189 (tester-m9) and TASK-193. Test files: `manager/tests/test_queue_scan_pg.py`, `manager/tests/test_queue_scan_race_pg.py` (new); `manager/tests/test_alerts.py` (the alert-kind oracle gains the TS §8.4 L1290 kind: old CHK-M7 "34 kinds" → **CHK-M9-232** "35 kinds", every other assertion unchanged). Plan rows: CHK-M9-150 to -161.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own databases) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_queue_scan_pg.py tests/test_queue_scan_race_pg.py` (8-file batch) | **8/8** and **5/5 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| r1 | `pytest tests/test_alerts.py` (with the M3 batch) | passed (inside 346/347; the one failure there was a metrics oracle, TASK-204) |
| plants | 8 service plants + 353/381 repo plants run on these files | all red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-150 | PASS | The scan parks after its snapshot (gate). M7's delete, started then, **waits** (pg_locks probe); after the scan commits, the delete cancels all 3 of the scan's queued jobs. A delete committed first → `PolicyDeleted`, counts unchanged. 20 unforced rounds at a barrier: the scan either refused (`PolicyDeleted`) or its jobs were cancelled; never a queued job of a deleted policy |
| CHK-M9-151 | PASS | An import (Execute and ExpectedResult changed, version +1) started while the scan is parked waits. The scan's recorded version, its job's command and its `eval_spec` expected are all the old version's. A scan after the import has the new ones |
| CHK-M9-152 | PASS | 20 rounds of two concurrent scans of one policy and agent: both succeed, `["cancelled", "queued"]` |
| CHK-M9-153 | PASS | version 3 (two re-imports); tag target over decommissioned, awaiting, offline, online → `("queued", 3, 2)`; scan row: version, `manual`, no schedule, `requested_by` 11, target `{tags, resolved_agents}` sorted, `queued`, `created_at` = now (µs); jobs for the offline and online agents with the scan's `created_at`; counts +1 scan, +2 jobs, +1 audit |
| CHK-M9-154 | PASS | `PolicyDisabled`, `PolicyDeleted`, `PolicyNotFound`, `NoTargetAgents` (decommissioned-only list; an unused tag), `PolicyHasNoPlugins` (its only plugin retired): scan, job, result and audit counts unchanged |
| CHK-M9-155 | PASS | scan 2 for {a, b} cancels scan 1's queued job for a and an older scan's queued retry for b (`finished_at` = now); byte-identical: scan 1's dispatched job (c) and its job for d, another policy's queued job for a, the original of b's retry, both inventory jobs; `cancelled_older: 2` in the entry; scan 2's two jobs queued |
| CHK-M9-156 | PASS | queued before an import → the old Execute; after → the new one and version +1; disabling the policy afterwards leaves both queued (#18) |
| CHK-M9-157 | PASS | the six keys; `ComplianceJob`; equals the test's TS §6.5 body (agent id given upper case, stored lowercase; `pickup_by` `YYYY-MM-DDTHH:MM:SSZ` without the µs; patterns = the setting at queue time, in order; plugins in sort order with `timeout_s` 600 kept); no `operator`/`expected`/`expected_result`/`eval_spec`/`name` at any depth; `eval_spec` parses, matches the payload in order, SR §1.1 name/operator/expected |
| CHK-M9-158 | PASS | a snapshot with U+0000 in execute, a lone surrogate in the name, U+0000 in expected → `build.UnstorableText` (fixed message, no input), counts unchanged |
| CHK-M9-159 / -160 | PASS | M8 `host_counts` on an M9 scan of 4 plugins and 3 agents → `(0, 0, 0, 4)` each; every `execute` of every job = an active plugin's execute of that policy |
| CHK-M9-161 | PASS | all + API token → the `scan.create` entry is the alert (`alert` true, `alert_kind` `all_hosts_scan_api_token`), `bitscan_alerts_total{kind}` +1; session, tags + token and a scheduled all-hosts scan by `system` → no alert, exactly the 7 #129 (a) detail keys; a queue rolled back by its caller leaves no entry and no count |
| CHK-M9-351 | PASS (red) | patterns `()` → the payload row |
| CHK-M9-352 | PASS (red) | disabled not refused → the refusal row (and repo plant: retired included) |
| CHK-M9-353 | PASS (red) | (repo) no `FOR SHARE` → the delete race row |
| CHK-M9-357 | PASS (red) | zero agents not refused → the refusal row |
| CHK-M9-366 | PASS (red) | alert for a session (`kind == all`) / for tags with a token (`via_api_token` only) → the alert row, each |
| CHK-M9-381 | PASS (red) | (repo plant, all three guards) → this file's newer-scan row too |

## Acceptance (TASK-198 row)

REQ-211 (1)–(6) → CHK-M9-150 to -156; REQ-209 (5) → -159; REQ-212 (2) → -160; REQ-227 (1), (2) → -161 (the sink half through the route: TASK-205, CHK-M9-242).
