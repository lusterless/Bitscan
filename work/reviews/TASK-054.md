# TASK-054 REVIEW: job repository (inventory jobs)

Reviewer: reviewer. Date: 2026-10-23. REQ-072, REQ-076, REQ-077, REQ-078, REQ-079. Spec: TS §5.2 L872–L890 (`scan_job`), L1011 (progress-column grant), L1006 (no DELETE on `scan_job`); §3.4 L230 (eligible agents, open states), L244 (inventory failure, never retried); §4.4 (`pickup_by`, expired); §6.1 L1064 and §3.3 L214 (at most 10 per pull); §6.5 L1182 (inventory job keys); #36, #66. Plan: `work/plans/TASK-061.md` (queue statement). Inputs:
- `work/reports/TASK-054-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-080 to -086, `manager/tests/test_jobs_repo_pg.py`, WSL 32 passed, 16 of 16 plants red; rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/repositories/jobs.py` (new, 157 lines);
- the tester's `manager/tests/test_jobs_repo_pg.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance.**
  - `queue_inventory`: one statement selects the eligible agents (not `decommissioned` or `awaiting_approval`, no inventory job `queued`, `dispatched` or `running`) and generates the id once in a materialised CTE. The row id and `payload.job_id` are therefore the same value, and the payload has exactly the four TS §6.5 keys.
  - `queue_inventory` takes `pg_advisory_xact_lock(hashtext('inventory_queue'))` first. Under READ COMMITTED the INSERT's snapshot is taken after the lock is granted, so two runs at once still give one open job per agent.
  - `pull` returns only this agent's `queued` inventory jobs with `pickup_by > now`, oldest first, at most `PULL_LIMIT` = 10 (a constant, not a parameter). It works by `FOR UPDATE SKIP LOCKED` plus a re-check of `state = 'queued'` in the UPDATE. `eval_spec` is never selected.
  - `expire_past_pickup` (`pickup_by <= now`) is the exact complement of the pull's bound.
  - `fail_dispatched_inventory` is strict (`dispatched_at < now − 30 min`), matching REQ-078 (3) "more than 30 minutes"; no retry row is created. The test plan row CHK-M3-084 says `<=`, but the tester asserted the REQ wording (30 min exactly stays `dispatched`), so code, test and REQ agree.
  - `oldest_queued_for_online` counts only `online` agents (#66).
- **Security invariants and grants.** Every UPDATE writes only `state`, `dispatched_at` or `finished_at` (TS §5.2 L1011). There is no DELETE. No function accepts a payload or a command, so the only job body is built from columns, by the scheduler path (TS §3.3: no ad-hoc command). The SQL is static or composed with `psycopg.sql`, and every value is a parameter. ruff S608 is clean.
- **Scope.** One file. `count_queued` (5 lines) is not named in the task row, but it is the REQ-086 "jobs queued" input that TASK-079 needs. Accepted.
- **Tests.**
  - The tests run as `bitscan_app` on a migrated database, so a missing grant would fail with 42501.
  - There are concurrency races for queueing (10 repeats) and pulls (a held transaction, and 10 pullers over 40 jobs).
  - Grant probes on `agent_id`, `payload`, `kind`, `scan_id`, `eval_spec`, `created_at`, `pickup_by` and `retry_of`; DELETE is refused.
  - Each repository UPDATE is captured and its SET columns checked against the progress columns.
  - There are boundary tests at `pickup_by` = now, at 29 min 59 s, 30 min and 30 min 1 s, and a compliance row planted as owner.
  - These would turn red for CHK-M3-347 to -351, and the tester reports 16 of 16 plants red.
  - My run (Windows): ruff, format and `mypy --strict` are clean on both files. The PostgreSQL cases skip locally (no Docker) and ran in WSL (tester), as in M2.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/repositories/jobs.py:116-122`. `complete` and `fail` move any `dispatched` job, compliance included, though only inventory callers exist in M3. When M9 adds compliance completion, keep these two inventory-only (add `kind = 'inventory'`) or rename them, so that a compliance job is never closed by an inventory path.
2. **note (no action)**, `jobs.py:28-29`. The open-job `NOT EXISTS` over `dispatched` and `running` has no supporting index (`ix_job_pending` covers only `queued`). With retention keeping inventory jobs for 30 days this is a growing scan once per inventory run, not a correctness issue, and no schema change is allowed. Watch it in the M6 load test.
