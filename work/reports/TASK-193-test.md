# TASK-193 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-208 (3), REQ-211, REQ-230; TS §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L550, §6.5 L1165–L1182, §5.2 L1011–L1012; #122 (c), #125 (a)–(f). Code under test: `bm/repositories/scan_queue.py` (impl-manager-m9b, `work/reports/TASK-193-impl.md`). Test files: `manager/tests/test_scan_queue_repo_pg.py` (new); the TP-M9-01 builder `manager/tests/scan_pg_fixtures.py` and its self-test `manager/tests/test_m9_fixtures_pg.py`. Plan rows: CHK-M9-100 to -104, -110 to -113, -123.

## Runs

| Run | Command (W: `/root/bstest-m9b-base`, venv `/root/venv-m9b`, `PYTHONPATH` pinned, `CI=true`, PG16 by Testcontainers, `-n 0`, a database of the module's own) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_m9_fixtures_pg.py tests/test_scan_queue_repo_pg.py` (W1 batch) | **15/15 passed** (5 + 10), 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 9 (8 pytest, 1 ruff), throwaway copies | 9/9 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`; `mypy --strict` on the test files | clean |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-100 to -104 | PASS | Builder self-test 5/5. Catalog through M7's real upload/delete: document order → `sort_order`, `v_plugin` name `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`, version bumps on re-import, disabled upload, soft delete. The six statuses exactly as the `agent_status` enum, with tags and real `bsa_` tokens (hash stored only). Owner-written jobs validate as `ComplianceJob`, `eval_spec` parses (#117), the trigger accepts the job's `created_at` and refuses +1 s, jobs in two months land in two partitions (none in default), the `scan_job` CHECK refuses a compliance job without a scan. The clock moves only when told; the canary is unique; a checksum changes on a one-byte change. The simulated agent pulls through the real route with its token (another agent's path → 403); fixture mapping keeps every other field |
| CHK-M9-110 | PASS | With every earlier agent decommissioned: `all` = exactly the enrolled, online, stale and offline agents (+ the other eligible ones), sorted, in **one** statement; `tags [a, b]` = eligible holders of a **or** b, an agent holding both once; `tags [c]` → the stale holder; an unused tag → `[]`; `agents [offline x, unknown, decommissioned, awaiting]` → `[x]`; input order does not matter (sorted); an unknown kind → `ValueError` |
| CHK-M9-111 | PASS | After the `FOR SHARE`, version, status, deleted flag and the active plugins come from **one** statement (spy: exactly 2 statements, the first `FOR SHARE`). A re-import that reverses document order reverses the snapshot (SR §2.3). A listed plugin made `retired` is left out. Display name, execute, `timeout_s`, operator and expected are each correct. Disabled, deleted (M7 delete), unknown (None) and "no active plugin" (`[]`) are reported. A second session's `UPDATE policy` waits on the share lock until commit (pg_locks probe). The advisory queue lock makes a second scan of the same policy wait; another policy does not |
| CHK-M9-112 | PASS | 3 jobs in **one** INSERT. Each SQL-composed payload equals the test's own TS §6.5 body (six keys, `job_id` = row id, lowercase ids, `pickup_by` text, plugins in order, patterns) and the pure builder's `payload()` for the same ids; it validates as `ComplianceJob`. `eval_spec` is stored as given; every job has the scan's `created_at` (with µs); state `queued`. The scan row has version, trigger, `requested_by`, target and `queued`. 10,000 jobs are still one INSERT, each payload `job_id` = its row id. Mismatched or empty id lists → `ValueError`, nothing written |
| CHK-M9-113 | PASS | `cancel_older_queued(policy P, [a1, a3], new scan)` cancels exactly scan 1's queued job for a1 and an older scan's queued **retry** for a1 (`finished_at` = now). Byte-identical: the original of that retry, a2's queued job (not listed), a3's dispatched job, another policy's queued job, both agents' queued inventory jobs, the new scan's own jobs, every `scan` row. A repeat → `[]` |
| CHK-M9-272 (part) | PASS | as `bitscan_app`, UPDATE of `scan_job.agent_id/scan_id/payload/eval_spec/retry_of` and of `scan.policy_id/policy_version/target` → `InsufficientPrivilege` |
| CHK-M9-352 | PASS (red) | plant: `v.state = 'active'` dropped → 2 failed |
| CHK-M9-353 | PASS (red) | plant: `FOR SHARE` dropped → 2 failed (the lock probe; the queue race rows) |
| CHK-M9-354 / -355 / -356 | PASS (red) | plants: status filter dropped / offline excluded / tags all-of → 1 failed each (resolution row) |
| CHK-M9-358 | PASS (red) | plants: dispatched jobs included / policy filter dropped → 1 failed each |
| CHK-M9-381 | PASS (red) | plant (rewritten, see note): join `OR j.scan_id IS NULL`, kind filter dropped, `IS DISTINCT FROM` the new scan → 2 failed (repo row and the TASK-198 queue row: inventory jobs cancelled) |
| CHK-M9-376 / -123 | PASS (red) | f-string query in `scan_queue.py` → ruff `S608` |

## Acceptance (TASK-193 row)

REQ-208 (3) → CHK-M9-110. The snapshot is one statement, and a concurrent policy delete waits for the scan's commit → CHK-M9-111 (the full delete race is TASK-198's, CHK-M9-150). N jobs in one INSERT → CHK-M9-112. The older-queued cancel touches only queued compliance jobs of that policy for the listed agents → CHK-M9-113. G1 red on a planted f-string → CHK-M9-376.

## Notes (no defect)

- CHK-M9-381 plant: the impl report's suggested plant (`OR j.scan_id IS NULL` without the kind filter) stays green, because `j.scan_id <> new` is NULL for an inventory job. The query has three independent guards against inventory jobs. The plant that turns red removes all three.
