# TASK-240 TEST: PASS

Tester: tester-m11c, 2026-11-08. Medium risk, standard rigor: one plant per acceptance criterion, plus the boundaries and the snapshot race. REQ-264, REQ-265, REQ-266 at service level. Spec: TS §4.5 L603–L604, §4.4 L577–L585, §4.3 L552, §6.2 L1113, L1120 and L1122. Answers: #119, #120, #145 (a)–(d), and the M9 interface note (the state is `scan.state`). Code under test: `bm/services/jobs/scan_views.py` (sha256 `487352138d6af9c2…`), by impl-manager-a, `work/reports/TASK-240-impl.md`. It is built on TASK-234's `scan_reads`, M8's `results.host_counts` and `score.host_score`, and TASK-235's `read_only_snapshot`.

Test file (new): `manager/tests/test_scan_views_pg.py`, 18 items. CHK-M11-155 to -162. It runs as `bitscan_app` through `AppDatabase`. Inputs are owner-written through `m11_pg_fixtures`, which was not edited. Expected values come from each world's description: the oracle is in the test, and M8's `scores.scan_host_scores()` is the REQ-265 (2) reference.

## Runs (W: WSL Ubuntu 24.04, `/root/m11c`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 4 tests/test_scan_views_pg.py` | 18/18 passed, 0 failed, 0 errors, 0 skipped. Lint then showed one S311 and nine mypy errors in the test: a reused loop name, and `scan_reads` reached through the service module. Fixed in the test. |
| 2 | `pytest -n 4 tests/test_scan_views_pg.py tests/test_scan_reads_pg.py`, after the fix (test_scan_reads_pg.py is TASK-234's suite, which this service depends on) | **39/39 passed** (18 + 21), 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on the file, from the repository root | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-155 | `test_scan_views_pg.py::test_counts_and_score_per_host` | PASS | Host A has PASS, a FAIL re-evaluated to PASS, a FAIL and an ERROR in the original, and PASS plus Not run in its retry: (3, 1, 1, 1, 0.75). An all-ERROR host gives (0, 0, 6, 0, None), a queued host (0, 0, 0, 6, None), and a host whose higher `reeval_id` is FAIL (its later-dated row PASS) gives (0, 6, 0, 0, 0.0). There are 4 hosts: the retry joins A, with its jobs listed original first. |
| CHK-M11-156 | `::test_fifty_random_scans_agree_with_m8` (seed 24311) | PASS | Over 50 `random_scan`s, every host's `HostScore` equals M8's `scores.scan_host_scores()`, with the same agent set. At least 50 hosts were compared. |
| CHK-M11-157 | `::test_hosts_by_hostname_then_agent_id_and_jobs_original_first` | PASS | Hostnames `aa`, 3× `mm`, `zz` come back in hostname order, ties by `agent_id`. Two retries were created a day *before* their originals and are still listed second, with `retry_of` = the original. Job state and times equal the stored row. |
| CHK-M11-158 | `::test_state_is_scan_state_as_stored[*]` (4) | PASS | Stored `running` with every job completed; `completed` with a running and a queued job; `queued` with failed and expired jobs; `partial` with completed jobs. In each case the detail and the list return the stored state. |
| CHK-M11-159 | `::test_scan_of_a_deleted_policy_is_returned`, `::test_late_result_then_reevaluation_change_the_next_answer` | PASS | A soft-deleted policy's scan is returned by the detail (with the policy name and counts) and by the list. A late result changes the next answer from (0, 1, 0, 1, 0.0) to (1, 1, 0, 0, 0.5), and a re-evaluation then gives (2, 0, 0, 0, 1.0). |
| CHK-M11-160 | `::test_detail_reads_one_read_only_snapshot`, `::test_service_runs_select_only` | PASS | A hook inside the service's transaction, after the jobs read, commits a result and a re-evaluation from another session. The counts read still gives the pre-commit (0, 1, 0, 1, 0.0), and the next call sees both. The first statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`. Across detail, list and history, every statement comes from `bitscan_app` and is SELECT, WITH or SET only. |
| CHK-M11-161 | `::test_unknown_scan_and_unknown_agent`, `::test_agent_history_three_of_five_newest_first[online,decommissioned]` | PASS | An unknown scan raises `ScanNotFound` and an unknown agent `AgentNotFound`. An agent in 3 of 5 scans gets exactly those, newest first. `limit=1` visits each once. A scan whose request names the agent but whose resolved target does not hold it is not listed. A decommissioned agent gets the same history. |
| CHK-M11-162 | `::test_list_scans_filters_keyset_and_anchor_gone`, `::test_detail_target_is_the_request_without_resolved_agents[agents,tags,all]` | PASS | Each filter alone and all together (policy, agent, state, `created_after` inclusive, `created_before` exclusive) equal the oracle, newest first with the `scan_id` tie. A `limit=2` keyset walk visits every scan once. A deleted anchor raises `AnchorGone`, re-exported by the service. The detail target equals the request, has no `resolved_agents`, and `resolved_count` and `target_kind` are right. |

## Plants (throwaway copies, each deleted after its row; plants file `/root/m11c/plants-240.json`, log `/root/m11c/plants-240.out.jsonl`)

9 plants: 9 red, 0 survived. Each one ran the whole file (`-n 4`), and every expected test failed for the planted reason.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-332 | the score counts ERROR as FAIL | counts and score; 50-scan agreement: 2 |
| CHK-M11-333 | the detail re-derives the state from the jobs | `state[running-…]`, `state[partial-…]`: 2 |
| CHK-M11-415 | `read_only_snapshot` removed from `scan_detail` | snapshot row (the late commit was seen): 1 |
| CHK-M11-416 | `agent_exists` leaves out decommissioned agents (in `scan_reads`) | `history[decommissioned]`: 1 |
| CHK-M11-417 | the `AgentNotFound` check removed | unknown agent: 1 |
| CHK-M11-418 | hosts ordered by `agent_id` only | host order: 1 |
| CHK-M11-419 | hosts grouped by job, so a retry is not joined to its host | host order; counts and score: 2 |
| CHK-M11-420 | the detail read filters out deleted policies (in `scan_reads`) | deleted policy: 1 |
| CHK-M11-421 | the detail target carries `resolved_agents` | target rows ×3: 3 |

## Acceptance (TASK-240: "REQ-265 (1), (2), (4), (5) and REQ-266 (1), (3) hold, and the scan state returned equals `scan.state` even when a derivation would differ")

- REQ-265 (1): CHK-M11-155.
- REQ-265 (2): CHK-M11-156.
- REQ-265 (4) and (5): CHK-M11-159.
- REQ-266 (1) and (3): CHK-M11-161.
- Stored state: CHK-M11-158.
- Also covered: the one-snapshot read (CHK-M11-160), SELECT only (REQ-264 (5) at service level), host and job order (CHK-M11-157), and the list filters, keyset, `AnchorGone` and target (CHK-M11-162).

## Notes

- `_hosts` skips a unit made only of retries. Under M9's invariants every retry has an original for the same agent, so that branch cannot occur in a valid database. No test reaches it, and none is needed.
- REQ-265 (3) (the 404 and the non-hyphenated 400), REQ-265 (6) and REQ-266 (2) and (4) are route rows, for TASK-244 (TP-M11-12).
