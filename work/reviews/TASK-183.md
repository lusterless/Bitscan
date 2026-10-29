# TASK-183 REVIEW: re-evaluation repository (revision 1)

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-200, REQ-201, REQ-204 (1). High risk (evaluator). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-183-impl.md` (with "Revision 1"): one new file, `manager/bitscan_manager/repositories/reeval.py` (162 lines).

TEST: PASS r1 (`work/reports/TASK-183-test.md`, tester-m8). 40/40 and 8/8 plants red. The single r1 failure was a test bug: `TRUNCATE` matched the `truncated` column. It was fixed with a whole-word check.

Spec read: TS §4.5 L601; §2.2 L114; §5.2 L859–L938, L994–L1006; #118 (a), (f), (h); decisions 2026-10-29 "A NULL `scan_result.stdout` on re-evaluation" and "Re-evaluation fails closed on an unrecognised stored ERROR detail".

My re-run: WSL PostgreSQL gives 60/60 across the three repository and score suites (`test_reeval_repo_pg.py` 40 of them). `ruff check` and `mypy --strict` are clean on Windows.

## Checks
1. **Per-scan serialisation (#118 (h), REQ-201 (1), (5)).**
   - The lock is `pg_advisory_xact_lock(hashtext('scan_reeval'), hashtext(<canonical uuid text>))`. It's transaction-level, so it's released on commit and on rollback, with no unlock path to forget.
   - The two-key space is separate from the single-key `audit_log` and `catalog` locks, so no lock-order cycle is possible. The run takes the scan lock, then the audit lock, and nothing takes them the other way round.
   - Autocommit is refused, and there's no row lock on `scan`, so intake isn't blocked.
   - Two sessions are serialised, while two scans run in parallel (CHK-M8-174). CHK-M8-358 and the session-level-lock plant are red.
2. **One snapshot for the definitions (#118 (f)).**
   - A single statement reads `policy.version`, `deleted_at` and every listed plugin's Operator and ExpectedResult, through `policy_plugin` membership, so under READ COMMITTED the version and definitions can't be mixed.
   - `plugin.state` isn't read (#118 (a)), and membership isn't taken from `owner_policy_id` (that plant is red).
   - The statement spy counts 1, and CHK-M8-354 is red.
3. **Chunked read (REQ-201 (4)).**
   - A named server-side cursor with `fetchmany(chunk)` returns ordered results, retries included, across partitions.
   - `chunk < 1` is refused, and every chunk is at most its size, with each result read exactly once.
   - CHK-M8-360 (`fetchall`) is red.
4. **r1 fields.**
   - `stdout` comes back as `None` for a SQL NULL, never COALESCEd (the x183-coalesce plant is red).
   - `eval_code` is now read, so TASK-185 can fail closed on an unrecognised stored ERROR detail. That matches both decision rows.
5. **Rows only added (TS §5.2 L1005–L1006, REQ-204 (1)).** There's one `INSERT … SELECT FROM unnest(…)` per chunk, `reevaluated_at` keeps its default, and nothing runs UPDATE, DELETE, TRUNCATE, MERGE or `FOR UPDATE` (CHK-M8-175).
   - Grant probes as `bitscan_app` cover all four targets: the parent, the current partition, the default partition and `scan_result_reeval`.
   - Each refuses UPDATE, DELETE and TRUNCATE (CHK-M8-225, 20 rows).
6. **SQL safety.** Literal statements with named parameters. CHK-M8-350 (an f-string) is red in S608.

## Findings
None blocking or should-fix.

1. nit (resolved): `work/plans/TASK-185.md` §2 was stale (`StoredResult.stdout: str`, no `eval_code`). The planner has since aligned it with both decision rows.
