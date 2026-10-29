# TASK-182 plan: results read repository (effective verdicts and per-host counts)

Planner: planner-m8, 2026-10-29. Design note D3 in `work/tasks.md`. Requirements REQ-197, REQ-198 (REQ-199 uses it through TASK-184). Open questions #118, #119, #120. `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §4.5 L601: "Results views, CSV exports and scores use the latest `scan_result_reeval` row for each job and plugin when one exists, otherwise the original result; plugins no longer in the current version keep their original verdict. The API returns both `result` and `original_result`."
- TS §4.5 L602: "host compliance score = PASS ÷ (PASS + FAIL), excluding ERROR and *Not run*, shown with the error count beside it. With no PASS or FAIL the score is NULL".
- TS §4.4 L577: a retry is "a new `scan_job` row with a new `job_id`, `retry_of` pointing at the original, holding only the plugins with no result"; L578: "the first result to arrive wins, whether it came from the original job or the retry"; L583: "Plugins with no result show as *Not run* and are left out of the score."
- TS §5.2 L892–L915: `scan_result` PK `(job_id, plugin_uuid, job_created_at)`, partitioned by `job_created_at`; L929–L938: `scan_result_reeval` with only `reeval_id` as key, no other index.
- TS §6.5 L1165–L1180: the job body (`scan_job.payload`) has `plugins: [{plugin_uuid, execute, timeout_s}]`.

## 2. Interface (`bm/repositories/results.py`)

```python
@dataclass(frozen=True, slots=True)
class EffectiveRow:
    job_id: UUID
    plugin_uuid: UUID
    agent_id: UUID
    original_code: int            # scan_result.eval_code
    original_detail: str | None   # scan_result.eval_detail
    code: int                     # effective (#119)
    detail: str | None
    reeval_id: int | None         # None when no re-evaluation exists
    reeval_policy_version: int | None
    reevaluated_by: int | None
    reevaluated_at: datetime | None

@dataclass(frozen=True, slots=True)
class HostCounts:
    agent_id: UUID
    passed: int
    failed: int
    errors: int
    not_run: int

def effective_results(conn: psycopg.Connection[Any], scan_id: UUID) -> list[EffectiveRow]: ...
def host_counts(conn: psycopg.Connection[Any], scan_id: UUID) -> list[HostCounts]: ...
```

Both take a connection from the caller's transaction (`tx.conn`), as the M7 repositories do. `effective_results` returns rows ordered by `agent_id`, `job_id`, `plugin_uuid` (deterministic for tests; M11 adds its own paging and filters to this module, using the same CTE). `host_counts` returns one row per agent that has an original compliance job in the scan, ordered by `agent_id`.

## 3. SQL shape (one statement each; parameters only, never string-built)

```sql
WITH jobs AS (
  SELECT job_id, agent_id, created_at, retry_of, payload
  FROM scan_job
  WHERE scan_id = %(scan_id)s AND kind = 'compliance'
),
latest AS (                                   -- one pass over scan_result_reeval (#119: highest reeval_id)
  SELECT DISTINCT ON (e.job_id, e.plugin_uuid)
         e.job_id, e.plugin_uuid, e.reeval_id, e.eval_code, e.eval_detail,
         e.policy_version, e.reevaluated_by, e.reevaluated_at
  FROM scan_result_reeval e
  WHERE e.job_id IN (SELECT job_id FROM jobs)
  ORDER BY e.job_id, e.plugin_uuid, e.reeval_id DESC
),
eff AS (
  SELECT r.job_id, r.plugin_uuid, j.agent_id,
         r.eval_code AS original_code, r.eval_detail AS original_detail,
         COALESCE(l.eval_code, r.eval_code) AS code,
         CASE WHEN l.reeval_id IS NULL THEN r.eval_detail ELSE l.eval_detail END AS detail,
         l.reeval_id, l.policy_version, l.reevaluated_by, l.reevaluated_at
  FROM jobs j
  JOIN scan_result r ON r.job_id = j.job_id AND r.job_created_at = j.created_at
  LEFT JOIN latest l ON l.job_id = r.job_id AND l.plugin_uuid = r.plugin_uuid
)
```

- `effective_results`: `SELECT … FROM eff ORDER BY agent_id, job_id, plugin_uuid`.
- `host_counts`:

```sql
, planned AS (                                -- plugins of each agent's original job(s)
  SELECT j.agent_id, (p->>'plugin_uuid')::uuid AS plugin_uuid
  FROM jobs j, jsonb_array_elements(j.payload->'plugins') p
  WHERE j.retry_of IS NULL
)
SELECT pl.agent_id,
       count(*) FILTER (WHERE e.code = 0) AS passed,
       count(*) FILTER (WHERE e.code = 1) AS failed,
       count(*) FILTER (WHERE e.code = 2) AS errors,
       count(*) FILTER (WHERE e.plugin_uuid IS NULL) AS not_run
FROM (SELECT DISTINCT agent_id, plugin_uuid FROM planned) pl
LEFT JOIN eff e ON e.agent_id = pl.agent_id AND e.plugin_uuid = pl.plugin_uuid
GROUP BY pl.agent_id
ORDER BY pl.agent_id
```

Notes:
- **First result wins** is M9's insert rule (a plugin has a result in the original or the retry, never both). The counts join on `(agent_id, plugin_uuid)`, so a result in the retry fills the original's planned plugin and is counted once. If a duplicate ever existed (a defect in M9), it would be counted twice; a test pins that the M8 query does not hide it (count equals rows), so M9's own test sees the defect.
- `job_created_at = j.created_at` lets the planner prune partitions; the trigger (L919–L927) guarantees it equals the job's `created_at`.
- `latest` is a single scan of `scan_result_reeval` filtered by `job_id IN (…)`; there is no index to use and none may be added (TS §5.2 is the schema). The REQ-198 (5) test reads `EXPLAIN` and fails on a SubPlan or a Nested Loop whose inner side is `scan_result_reeval`.
- A plugin listed in a result but not in the original payload (impossible by M9's builder) is not in `planned`, so it never enters the counts; `effective_results` still returns it.
- A host whose original job was `cancelled` or is still `queued` has all its planned plugins `not_run`.
- `bitscan_app` needs only SELECT on `scan_job`, `scan_result` (and partitions, via the default privileges) and `scan_result_reeval`: all granted by L994–L997.

## 4. Edge cases for the tests

- Scan with no jobs: `effective_results` `[]`, `host_counts` `[]`.
- Re-evaluation rows for a job of another scan with the same plugin: ignored (filtered by `job_id`).
- Three re-evaluation rows for one result with ids out of insertion order: the highest id wins, whatever `reevaluated_at` says (#119).
- Results in both the current month's partition and an older one (jobs created in different months): both read.
- 255-character non-ASCII hostnames do not matter here (no text in keys).

## 5. Size

About 170 lines (two dataclasses, the shared CTE text, two functions). If it grows past 200, `host_counts` moves to `repositories/results_counts.py` importing the CTE (one task id).
