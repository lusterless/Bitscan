# TASK-182 REVIEW: results read repository (effective verdicts and per-host counts)

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-197, REQ-198. High risk (evaluator; interface for M11). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-182-impl.md`: one new file, `manager/bitscan_manager/repositories/results.py` (138 lines).

TEST: PASS (`work/reports/TASK-182-test.md`, tester-m8). 15/15 and 8/8 plants red.

Spec read: TS §4.5 L601–L602; §4.4 L577–L583; §5.2 L872–L938, L994–L1006; §6.5 L1165–L1180; §8.1 L1252; #119, #120 (c); design note D3.

My re-run:
- WSL, PostgreSQL 16 through Testcontainers, the tester's base copy (product files checked identical to the worktree): `pytest tests/test_results_repo_pg.py tests/test_reeval_repo_pg.py tests/test_scores_pg.py` gives 60 passed.
- Windows: `ruff check manager` is now clean across the whole tree, and `mypy --strict` is clean.

## Checks
1. **Latest-row rule in SQL (#119).** The latest row comes from a `DISTINCT ON (job_id, plugin_uuid) … ORDER BY …, reeval_id DESC`; `reevaluated_at` isn't in the order.
   - The detail comes from the latest row whenever one exists (`CASE WHEN l.reeval_id IS NULL`), so a NULL detail on a re-evaluated PASS doesn't fall back to the original's.
   - CHK-M8-348 (SQL) is red, and the TASK-184 property (200 random sets) shows the SQL and `effective()` agree.
2. **One pass over `scan_result_reeval` (no index allowed, TS §5.2).**
   - `= ANY(ARRAY(SELECT job_id FROM jobs))` makes the job list an InitPlan, so the table is one scan with a filter.
   - The implementer's reason for not using the plan's `IN (SELECT …)` holds: a semi-join could put the reeval scan on a Nested Loop's inner side.
   - The `EXPLAIN ANALYZE` row checks one node and `Actual Loops` = 1, and CHK-M8-351 (per-result lateral) is red.
3. **Counts (TS L577–L583).**
   - The planned plugins come from the original jobs only, and are joined to the effective verdicts on `(agent_id, plugin_uuid)`, so a retry's result fills its original's plugin once.
   - Not run is a planned plugin with no result. A `queued` host is all not run.
   - `LEFT JOIN LATERAL … ON true` keeps an agent with an empty payload as (0, 0, 0, 0). That's a justified departure from the plan's SQL text, not from its contract.
   - The deliberate double count of an M9 duplicate is pinned, so M9's first-result-wins test will see it.
   - CHK-M8-352 is red.
4. **Scope of the read.** Everything goes through `jobs` (`scan_id` bound, `kind = 'compliance'`), so other scans, their re-evaluation rows and inventory jobs never appear (CHK-M8-153, -154, -160; x182 plants red). The `job_created_at` join allows partition pruning, and the second-month partition is covered.
5. **SQL safety (TS §8.1, ruff S608).** Constant `sql.SQL` pieces composed with `.format()`, and the scan id bound as a parameter. SELECT only: one statement per call, with no write or lock word (CHK-M8-159). CHK-M8-349 is red in G1.
6. **Grants.** It needs only SELECT on `scan_job`, `scan_result` and `scan_result_reeval`, and runs as `bitscan_app`.

## Findings
None blocking or should-fix.

1. nit: `_opt_int` converts through `int(str(value))`, which is a detour for an `int | None` column value. It's harmless and typed. No change asked.
2. Carried to M9: `CAST(p.item ->> 'plugin_uuid' AS uuid)` and `jsonb_array_elements` raise on a payload that isn't the TS §6.5 shape, and that would make the whole counts statement fail. M9's job builder is the only writer, so its tests must pin the payload shape.
