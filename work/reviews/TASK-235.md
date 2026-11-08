# TASK-235 REVIEW: result reads repository (composes M8's `_EFFECTIVE`)

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

**Scope reviewed:** `manager/bitscan_manager/repositories/result_reads.py` (new, 251 lines, the only file).

**Checked against:** TS §4.5 L603, §4.4 L585, §6.2 L1123, §5.2 (`scan_job`, `scan_result`, `scan_result_reeval`); REQ-267, REQ-269, REQ-272; #119, #144; PD-46; plan `work/plans/TASK-235.md` §3.

**Reports:** `work/reports/TASK-235-impl.md` and `work/reports/TASK-235-test.md` (PASS: 22/22 on PostgreSQL 16 in WSL after one test-count fix; 29/29 plants red).

## Checks

- **Viewers never get stdout or stderr (security invariant, TS §6.2 L1123):**
  - `_PAGE_VIEWER` selects `NULL::text, NULL::text` in place of `r.stdout, r.stderr`, so a viewer's output never leaves PostgreSQL. This is defence in depth beside TASK-233's key omission.
  - The variant is chosen only by `with_output`, which the service derives from `include_output(role)`.
  - The tester captured the raw rows psycopg fetched and found no output byte in the viewer variant. The plants "viewer statement reads output" and "variant ignored" were red.
- **PD-46:**
  - `from bitscan_manager.repositories import results as _m8`, and `_ROWS.format(effective=_m8._EFFECTIVE, …)`: the M8 CTE is composed as the same object, not copied.
  - `git diff 6efe0fb` on `repositories/results.py` and `repositories/reeval.py` is empty.
  - The copy plant and the M8 latest-by-`reevaluated_at` plant were red.
- **Effective verdict (#119):** `result`/`detail` come from `eff.code`/`eff.detail`, the highest `reeval_id` or else the original; `original_*` come from `eff.original_*`. `scan_result_reeval` is read once per statement inside `_EFFECTIVE`, and `EXPLAIN` shows no SubPlan (CHK-M11-130, plant -368 red).
- **The `specs` deviation from the plan sketch:**
  - Not-run name, operator and expected are read from the original job's `eval_spec -> 'plugins'` entries, joined by `(job_id, plugin_uuid)`. Execute comes from the payload item.
  - The keys match M8's `build_eval_spec` (`services/evaluator/eval_spec.py:70`: `plugin_uuid`, `name`, `operator`, `expected`) and M9's payload (`services/jobs/build.py:108`: `plugin_uuid`, `execute`). So the fixtures are not the only source agreeing with the SQL.
  - Same outcome as the plan (never the current catalog; CHK-M11-120 and the four catalog plants red). It also avoids shipping a whole `eval_spec` per not-run row and keeps the repository from importing a service.
- **Other scans' rows (REQ-267 (6)):** `jobs` is scoped by `scan_id`. `planned`, `specs`, `eff`, `rj` and the `scan_result` back-join (on `job_id`, `plugin_uuid`, `job_created_at`) are all keyed on those jobs. The same-microsecond third-scan test and plant -331 were red.
- **SQL:** constant `psycopg.sql` fragments with `%(name)s` parameters only (S608, plant -344 red). An unknown `status` raises before any statement. SELECT and `SET TRANSACTION` only, as `bitscan_app`.
- **`read_only_snapshot`:** `REPEATABLE READ, READ ONLY`, first statement only. The tester shows a late result is invisible inside the snapshot and an UPDATE is refused. The name matches plan §3 and `PackageSearchRepo`, so keep it for TASK-240.
- **Export:** reads `max_rows + 1`, so the service can refuse an over-cap export before building any text (#146 (e)).
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` are clean on the module and both test files. The PostgreSQL suites are Linux-only, so I relied on the tester's WSL run. The property test's oracle is M8's pure `effective()` and `host_counts`, not this module.

## Findings

1. nit (design note for the lead, not this task's defect), `result_reads.py:232`, `results_export`:
   - For an operator or admin, the export holds up to 100,001 rows in memory, each with up to 64 KB stdout and 16 KB stderr (TS §4.4 L601 caps). That is a worst case of about 8 GB, before TASK-233 builds the text and the route encodes it, which roughly triples it.
   - #146 (e), (f), as approved, cap rows, not bytes; the impl report records this.
   - It is an operator-reachable memory exhaustion of the single manager instance. The reachable size depends on the fleet: a 100,000-row results set needs, for example, 20 plugins × 5,000 hosts.
   - I raised it with the lead as a possible new open item (a byte cap, or a lower row cap with output). No change is asked in TASK-235.
2. nit, `result_reads.py:60`: two stored results for one plugin in a unit (the original and the retry) would give two items. M9's first-result-wins intake prevents this, and the impl report records it. No change.
