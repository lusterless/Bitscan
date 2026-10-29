# TASK-182 IMPL: results read repository (effective verdicts and per-host counts)

Implementer: impl-manager-m8b. REQ-197, REQ-198. Risk high. Plan: `work/plans/TASK-182.md` (design note D3). Spec: TS §4.5 L601–L602, §4.4 L577–L583, §5.2 L872–L938, §6.5 L1165–L1180. Answers applied: #119 (latest = highest `reeval_id`), #120 (c) (the four counts).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/repositories/results.py` (new, 138 lines) | `EffectiveRow`, `HostCounts`, `effective_results()`, `host_counts()`, shared CTE `_EFFECTIVE` |

No file outside the task's list was changed. No migration, no route.

## Interface (as the plan's §2)

```python
@dataclass(frozen=True, slots=True)
class EffectiveRow:
    job_id: UUID; plugin_uuid: UUID; agent_id: UUID
    original_code: int; original_detail: str | None      # scan_result
    code: int; detail: str | None                          # effective (#119)
    reeval_id: int | None; reeval_policy_version: int | None
    reevaluated_by: int | None; reevaluated_at: datetime | None

@dataclass(frozen=True, slots=True)
class HostCounts:
    agent_id: UUID; passed: int; failed: int; errors: int; not_run: int

def effective_results(conn: psycopg.Connection[Any], scan_id: UUID) -> list[EffectiveRow]
def host_counts(conn: psycopg.Connection[Any], scan_id: UUID) -> list[HostCounts]
```

Both take the caller's `tx.conn` and never commit. Order: `effective_results` by `agent_id, job_id, plugin_uuid`; `host_counts` by `agent_id`. An unknown scan gives `[]` from both.

## SQL (one statement per call; `psycopg.sql` composition of constants, parameters only)

- `jobs AS MATERIALIZED`: the scan's `compliance` jobs (originals and retries).
- `latest`: `DISTINCT ON (job_id, plugin_uuid) … ORDER BY job_id, plugin_uuid, reeval_id DESC` over `scan_result_reeval`, filtered by `job_id = ANY(ARRAY(SELECT job_id FROM jobs))`. The array is an **InitPlan** (evaluated once), so `scan_result_reeval` is one Seq Scan with a filter. There is no SubPlan, and no join that could put `scan_result_reeval` on a Nested Loop's inner side. That's for the REQ-198 (5) `EXPLAIN` row, and it is the D3 note's `job_id = ANY(<the scan's job ids>)` form. The plan's `IN (SELECT …)` form becomes a semi join, which the planner could make a Nested Loop with the reeval scan inner when `jobs` is estimated at 1 row.
- `eff`: `jobs ⋈ scan_result` on `job_id` **and** `job_created_at = created_at` (partition pruning), `LEFT JOIN latest`. `code = COALESCE(latest, original)`. `detail` is the latest row's whenever one exists (even NULL), else the original's.
- `host_counts` adds `planned`: `SELECT DISTINCT agent_id, (item->>'plugin_uuid')::uuid` from the original jobs (`retry_of IS NULL`) via `LEFT JOIN LATERAL jsonb_array_elements(payload->'plugins')`. It then `LEFT JOIN eff` on `(agent_id, plugin_uuid)`. passed/failed/errors are `count(*) FILTER (code = 0/1/2)`, and not_run is `count(*) FILTER (planned plugin present AND no eff row)`.

### One deviation from the plan's SQL text (not from its contract)

The plan's `planned` uses an inner `FROM jobs j, jsonb_array_elements(...)`. With that, an agent whose original job has an empty `plugins` array would get **no** row, but plan §2 says "one row per agent that has an original compliance job". I used `LEFT JOIN LATERAL … ON true` and excluded the NULL plugin from `not_run`, so such an agent gets `(0, 0, 0, 0)`. Nothing else changes: with a non-empty payload the rows are the same as the plan's.

## Acceptance points (REQ-198) and how they are met

1. (a) Every result of the scan with both verdicts: `eff` joins all compliance jobs of the scan (retries included). (b) Counts:
   - all four kinds: FILTER counts;
   - a retry holding the missing plugins: the join is on `(agent_id, plugin_uuid)`, not `job_id`, so the retry's result fills the original's planned plugin and is counted once;
   - a `queued` job: no results, so every planned plugin is not_run;
   - FAIL re-evaluated to PASS: the effective code counts as PASS.
2. Another scan's rows never appear: everything is reached through `jobs` (`scan_id = %(scan_id)s`).
3. A re-evaluation row of another scan for the same plugin is ignored: `latest` is filtered by this scan's job ids, and the join is on `job_id` and `plugin_uuid`.
4. S608: the module has no f-string, `%` or `+` string building. Every query is a `sql.SQL` constant combined with `.format()`, the same pattern as `catalog.py`.
5. `EXPLAIN`: `scan_result_reeval` is read once (the InitPlan form above). In the counts statement, `eff` and `latest` are each referenced once, so they are inlined.
- REQ-197 (1), (2) on the SQL side: the highest `reeval_id` wins whatever `reevaluated_at` says; `reevaluated_at` is not in the `ORDER BY`.

First-result-wins: if M9 ever stored a duplicate (original and retry for one plugin), both rows join the planned plugin and it is counted twice. That's deliberate, so M9's own test sees the defect (plan §3 notes).

## Mutation plants for this task (M8 table)

- **CHK-M8-348:** `ORDER BY e.job_id, e.plugin_uuid, e.reeval_id DESC` → `ASC`, or → `e.reevaluated_at DESC`. Expect G64 red (ids 5, 9, 7 row; reevaluated_at out of id order).
- **CHK-M8-349:** turn `_RESULTS` into an f-string, e.g. `f"... WHERE scan_id = '{scan_id}'"`. Expect G1 (S608) red.
- **CHK-M8-351:** replace `latest` and its join with `LEFT JOIN LATERAL (SELECT … FROM scan_result_reeval e WHERE e.job_id = r.job_id AND e.plugin_uuid = r.plugin_uuid ORDER BY reeval_id DESC LIMIT 1) l ON true`. Expect the G64 `EXPLAIN` row red.
- **CHK-M8-352:** drop `WHERE j.retry_of IS NULL` in `planned` (retry plugins planned twice; DISTINCT hides that, so also try joining `eff` on `job_id` instead of `agent_id`: the retry's results become not_run). Expect G64 red.

## Gates (run from the worktree root)

The worktree has no `manager/.venv` yet. The main checkout's venv lacks `python_multipart` (4 unrelated `import-not-found` errors in `api/user/policy_import.py`), so I ran the `Bitscan-m7` venv's tools against this tree, as main allowed:

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 316 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues, 316 files.
- the same with `--platform linux`: no issues.

No local PostgreSQL or Docker, so the SQL hasn't been run. I rendered the composed text with `as_string(None)` to check that it is well-formed.

## For the tester

- Run as `bitscan_app` (only SELECT is used). Fixture rows must keep `scan_result.job_created_at = scan_job.created_at` (the trigger enforces it).
- `payload->'plugins'` must be the TS §6.5 list of objects with `plugin_uuid`. A non-array `plugins`, or a non-uuid `plugin_uuid`, makes the counts statement raise; M9 builds the payload.
- `EffectiveRow.detail` follows the latest row whenever one exists, even when that row's detail is NULL (PASS/FAIL), and never falls back to the original's.
