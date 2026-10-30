# TASK-193 IMPL: scan queue repository

Implementer: impl-manager-m9b, 2026-10-30. REQ-208 (3), REQ-211, REQ-230. Open items #125 (d)–(f). Plan: `work/plans/TASK-198.md` §3.

## Files

- `manager/bitscan_manager/repositories/scan_queue.py` (new, 215 lines including docstrings and SQL text; about 150 code lines).

No other file changed.

## Interface (as plan TASK-198 §3)

```python
@dataclass(frozen=True)
class PolicySnapshot: policy_id: int; version: int; status: str; deleted: bool; plugins: list[CatalogPlugin]

def lock_policy_queue(conn, policy_id: int) -> None
def policy_snapshot(conn, policy_id: int) -> PolicySnapshot | None
def resolve_agents(conn, kind: str, agents: Sequence[UUID], tags: Sequence[str]) -> list[UUID]
def insert_scan(conn, *, policy_id, policy_version, trigger, schedule_id, target_json, requested_by, created_at) -> UUID
def insert_jobs(conn, *, scan_id, agent_ids, job_ids, created_at, pickup_by, pickup_text, plugins_json, patterns, eval_spec_json) -> int
def cancel_older_queued(conn, *, policy_id, agent_ids, new_scan_id, now) -> list[UUID]   # sorted
```

`CatalogPlugin` is imported from the pure `services/jobs/build.py` (TASK-189), as the plan's interface names it. This is a repository importing a pure services type (plain dataclass, no I/O); no repository-to-service call exists.

## How it meets the acceptance points

- **Queue lock:** `SELECT pg_advisory_xact_lock(hashtext('scan_queue:' || CAST(%s AS text)))`.
- **Snapshot in one statement after `FOR SHARE`:** `policy_snapshot` runs `SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE` (None for an unknown id), then ONE statement reads `version`, `policy_status`, `deleted_at IS NOT NULL` and the active plugins as one `json_agg(json_build_array(plugin_uuid, display_name, execute, timeout_s, operator, expected_result) ORDER BY sort_order, plugin_uuid)` over `policy_plugin JOIN v_plugin WHERE v.state = 'active'`. The second statement starts after the lock is granted, so under READ COMMITTED it sees a delete or import that committed while we waited; a delete or import that starts later waits on our share lock (its `UPDATE policy`) until we commit, and M7's cancel then sees our queued jobs.
- **Resolution (REQ-208 (3)):** one fixed statement per kind (`all`, `agents`, `tags`), chosen from a map; `status NOT IN ('decommissioned','awaiting_approval')` (offline included); tags by `EXISTS … agent_tag … tag = ANY(...)` (any of); unknown ids drop out; `ORDER BY agent_id` (distinct by construction). An unknown kind raises `ValueError`.
- **N jobs in one INSERT:** `INSERT … SELECT FROM unnest(CAST(%(jobs)s AS uuid[]), CAST(%(agents)s AS uuid[]))`; the payload is `jsonb_build_object('job_id', t.job_id::text, 'agent_id', t.agent_id::text, 'kind', 'compliance', 'pickup_by', <text>, 'plugins', <jsonb>, 'redaction_patterns', <jsonb>)`, so `job_id` in the payload equals the row id and both ids are lowercase hyphenated text. `eval_spec` is one JSONB parameter. Every job gets the scan's `created_at` (#125 (f)). Mismatched or empty id lists raise `ValueError` before SQL.
- **Older queued cancel (#125 (e)):** `UPDATE scan_job j … FROM scan s WHERE s.policy_id = %(policy)s AND j.kind = 'compliance' AND j.state = 'queued' AND j.agent_id = ANY(...) AND j.scan_id <> %(new)s RETURNING j.job_id`, `finished_at = now`. Dispatched/running jobs, other policies, other agents and inventory jobs are not matched; only `scan_job` rows are locked (UPDATE … FROM does not lock `scan`).
- **Grants:** INSERT on `scan` and `scan_job`; UPDATE only of `state`, `finished_at`; `FOR SHARE` needs UPDATE on one column of `policy`, which `bitscan_app` holds.
- Every statement is parameterised (`sql.SQL` constants; the resolve variants are composed with `sql.SQL` fragments, never input).

## Gates (Windows, worktree venv)

`ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` and the same with `--platform linux`: all green (349 files). Not run against PostgreSQL by me (the tester runs TP-M9-10 in WSL).

## Plants for the tester (mutation table)

- CHK-M9-352: drop `AND v.state = 'active'` in `_SNAPSHOT` (retired plugin included).
- CHK-M9-353: replace `FOR SHARE` in `policy_snapshot` by nothing (delete race leaves queued jobs).
- CHK-M9-354: drop `NOT IN ('decommissioned', 'awaiting_approval')` in `_RESOLVE_ANY`.
- CHK-M9-355: add `AND a.status <> 'offline'` to `_RESOLVE_ANY`.
- CHK-M9-356: tags all-of (for example `GROUP BY … HAVING count(*) = cardinality(...)`).
- CHK-M9-358: drop `j.state = 'queued'` or `s.policy_id = %(policy)s` in `cancel_older_queued`.
- CHK-M9-381: inventory jobs have `scan_id` NULL (the DDL CHECK), so three guards exclude them: the `j.kind = 'compliance'` filter, the `j.scan_id = s.scan_id` join, and `j.scan_id <> %(new)s` (NULL for an inventory job). A plant turns G68/G33 red only when it drops all three (corrected after tester-m9b's TASK-193 TEST; see `TASK-193-test.md`).
- CHK-M9-376: an f-string query in this module (G1 / S608).
