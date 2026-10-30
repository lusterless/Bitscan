# TASK-204 TEST: PASS (r1)

Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-213 to REQ-216, REQ-229 (3), REQ-066, REQ-226 (metrics oracle); TS §6.1 L1064, L1065, L1071, L1072, §3.3 L203, L214, L222, L224, §6.5 L1165–L1190, §4.4 L567, L578, L581, §8.4 L1287, L1291; #54 (c), #121, #124 (a)–(h); PD-40. Code under test: `bm/repositories/jobs.py`, `bm/services/jobs/pull.py`, `bm/services/jobs/__init__.py` (r1: back to its M3 content), `bm/api/agent/jobs.py` (impl-manager-m9b, `work/reports/TASK-204-impl.md`); `manager/openapi.json` unchanged. Test files: `manager/tests/test_agent_jobs_api_pg.py` (new, the simulated agent end to end); `manager/tests/test_jobs_api_pg.py` (PD-40 rewrite, below); `manager/tests/test_metrics_api_pg.py` and `manager/tests/test_alerts.py` (REQ-226's counter added to two M3/M7 oracles, below). Plan rows: CHK-M9-220 to -231.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_agent_jobs_api_pg.py tests/test_jobs_api_pg.py tests/test_alerts.py tests/test_inventory_api_pg.py tests/test_sweep_pg.py tests/test_metrics_api_pg.py` (+1 sweep row) | 345/347 passed. 2 failed, both **test bugs**: pull equality ignored the ruling-2026-10-23 `pickup_by` re-serialisation; the accept-line check read a `data` key that the JSON formatter flattens. Then 1 failed after the fixes: the metrics label oracle (the `_created` sample) |
| re-runs | each failing node id after its fix | 1/1 passed each |
| r2 | `tests/test_agent_jobs_api_pg.py` in the W4 plant control | **20/20 passed** (19 + the planted row green on the clean tree) |
| security | `pytest tests/test_security_m9.py tests/test_invariants_m3.py tests/test_openapi.py tests/test_contract_agent.py` | **622/622 passed** (r1: pure modules load no psycopg/repository, CHK-M9-271) |
| plants | 6 route plants + 325/328 at route level | 8/8 red |

## PD-40 (a) rewrite (TP-M9-19, CHK-M9-231): old → new

| Old check | Old assertion | New check | New assertion |
| --- | --- | --- | --- |
| CHK-M3-247 (compliance half; plant CHK-M3-351) `test_a_compliance_job_is_never_returned_in_m3` | REQ-072 (4): a queued compliance job is not returned | **CHK-M9-221** `test_a_compliance_job_is_returned_with_the_inventory_job` | REQ-213 (1), (2): returned with the inventory job, oldest first, equal to its stored payload (`pickup_by` the same instant), dispatched at the clock; still no `eval_spec`/`operator`/`expected` (CHK-M3-346 kept) |
| CHK-M3-249 own-compliance case (plant CHK-M3-359) `test_every_well_formed_batch_is_409_with_one_entry_and_nothing_stored` | REQ-073 (1): every well-formed batch is 409 | **CHK-M9-225** `test_well_formed_batches_for_jobs_that_cannot_take_them_are_409` | REQ-214 (2): the agent's own dispatched compliance job answers 200 `{1, 0}` with one stored row and no refusal entry. The inventory (dispatched, queued), unknown, foreign and start-notice cases keep their 409 and entry assertions **unchanged** |

Every other M3 assertion in `test_jobs_api_pg.py` (refusal entry, flood alert, 400, 413, gzip, no stdout in logs, the token matrix, rate limits) is unchanged and green.

REQ-226 also changes two oracles: the registry family set (`test_alerts.py`: + `bitscan_plugin_results`, **CHK-M9-233**) and the bounded-label oracle (`test_metrics_api_pg.py`: + `result` ∈ {PASS, FAIL, ERROR} on that family only, **CHK-M9-234**).

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-220 / -221 | PASS | 6 inventory + 6 compliance queued at interleaved times: the first pull returns the 10 oldest in creation order (mixed kinds), the second the other 2. Each job is dispatched once, at the clock. The answer validates against `JobsResponse` and the pull schema in `manager/openapi.json`. Each compliance job equals its stored payload (six keys, `ComplianceJob`). No answer contains `"eval_spec"`, `"operator"`, `"expected"` or `"expected_result"`. A third pull is `{"jobs": []}` |
| CHK-M9-222 | PASS | cancelled, expired, past-`pickup_by` and another agent's jobs are never returned (the other agent's stays queued); 1 µs before `pickup_by` is returned. Four concurrent pulls over 12 compliance jobs → each once, all 12 |
| CHK-M9-223 | PASS | the M3 pull checks for inventory (REQ-072 (1), (3), (5), (6)) green in `test_jobs_api_pg.py` |
| CHK-M9-224 | PASS | 10 refusals through the route: unknown, foreign, inventory, queued, expired, cancelled (dispatched, running), dispatched + 7 d + 1 s, 49 + 1 foreign, unreadable `eval_spec`. Each is 409 `job_not_acceptable` (problem keys only, no canary in the answer) with exactly one `agent.result_refused` entry (`agent:<id>`, `job:<id>`, reason `job_not_acceptable` or `eval_spec_invalid`, `results`, `final`, no canary) and no stored row; the `scan_job` checksum is unchanged |
| CHK-M9-225 | PASS | dispatched, running, failed, partial, completed → 200 `{1, 1}` validating `ResultsResponse`; dispatched + 7 d exactly → 200 |
| CHK-M9-226 | PASS | malformed → 400, no entry; 1.5 MiB + 1 as sent → 413 with one `too_large` entry; gzip → 200, stored; gzip inflating past the cap → 413 |
| CHK-M9-227 | PASS | 21 409s for agent B's own cancelled job → no flood alert (21 refusal entries); 21 counted 409s for agent A within 10 min → one `result_409_flood` for A, `bitscan_alerts_total` +1 |
| CHK-M9-228 | PASS | end to end with the SR §1.1 plugin: pull → the start-notice fixture (running, `started_at` = clock, `deadline_at` = + 615 s with `max_parallel_plugins` 2) → the one-final fixture (PASS, snapshots, `received_at` = clock) → completed; the repeat → `{0, 1}`; `host_counts` (1, 0, 0, 0). A 0.1.0 agent's `error_cases` fixture → three ERROR rows (`spool_overflow`, `runner_unavailable`). The NUL fixture bytes, plain and gzip → `a�b` / `�`, PASS. Catalog change after queue → the pulled command is the queued one; PASS on the queued expected. First result wins across original and retry, both orders |
| CHK-M9-229 | PASS | the results route refuses an inventory job id (409); the inventory route refuses a compliance job id (409); both jobs unchanged |
| CHK-M9-230 | PASS | `bsu_` and `bsk_` tokens on both routes → 401; another agent's `bsa_` on this agent's path → 403; nothing dispatched or stored |
| logs | PASS | a canary in stdout/stderr (plain, gzip, duplicate, refused) is in no log line; the accept line carries `agent_id`, `job_id`, `accepted`, `duplicates` only |
| CHK-M9-378 | PASS (red) | pull inventory-only → 9 failed |
| CHK-M9-379 | PASS (red) | `eval_spec` added to pulled payloads → 10 failed |
| CHK-M9-380 | PASS (red) | own cancelled counted / no 409 counted → 1 failed each (the flood row) |
| CHK-M9-325 / -328 (G70) | PASS (red) | cancelled accepted / kind ignored → 2 / 1 failed through the route |

## Acceptance (TASK-204 row)

REQ-213 (1)–(5), REQ-214 (1)–(6) (6: TASK-199), REQ-215 (3)–(5), REQ-216 (1)–(3) end to end, gzip/400/413 as REQ-066, REQ-229 (3) → the rows above. `manager/openapi.json` byte-identical (G6 green in the security run).
