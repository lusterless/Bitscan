# TASK-185 IMPL: re-evaluation service

Implementer: impl-manager-m8b. REQ-200, REQ-201, REQ-202 (REQ-204 through its tests). Risk high. Plan: `work/plans/TASK-185.md` §3–§6 (design note D4). Spec: TS §4.5 L601, §2.2 L114, §5.2 L929–L938 and L1005–L1006, §5.3 L1049. Answers applied: #12, #118 (a)–(h), #119; lead decision 2026-10-29, "A NULL `scan_result.stdout` on re-evaluation". Built on TASK-176 (`model`), TASK-178 (`classify`) and TASK-183 (`repositories/reeval.py`).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/reevaluate.py` (new, 138 lines) | `ScanNotFound`, `PolicyDeleted`, `ReevalResult`, `reevaluate_scan()`, private `_new_verdict()`, `_batch()` |

No file outside the task's list was changed.

## Interface (plan §3, frozen for M11)

```python
class ScanNotFound(Exception): ...      # M11: 404 not_found; raised with no args
class PolicyDeleted(Exception): ...     # M11: 409 conflict (#118 (c)); raised with no args

@dataclass(frozen=True, slots=True)
class ReevalResult:
    scan_id: UUID; policy_id: int; scan_policy_version: int
    policy_version: int; rows_added: int; not_in_version: int

def reevaluate_scan(db: Database, scan_id: UUID, *, user_id: int,
                    wake: Callable[[], None] | None = None) -> ReevalResult
```

## Algorithm (one `db.transaction()`, plan §4)

1. `reeval.lock_scan()`: the per-scan xact lock, then the scan. If it returns `None`, raise `ScanNotFound` (rollback; nothing written).
2. `reeval.current_definitions()`, one statement. If it returns `None` or the policy is deleted, raise `PolicyDeleted`. A disabled policy is re-evaluated normally (#118 (d)).
3. For each chunk of `reeval.stored_results()` (at most 1,000 rows), each result is handled by the first rule that matches:
   1. Its plugin is not listed by the current version: `not_in_version += 1`, and no row (#118 (b)).
   2. Its original `eval_detail` is in `INTAKE_DETAILS`: a row with ERROR and the same detail (#12, #118 (e)).
   3. Its `stdout` is NULL: a row with ERROR `cannot evaluate`, and `classify()` is **not** called (lead decision 2026-10-29).
   4. Otherwise: `classify(operator, expected, stdout, exit_code, timed_out, truncated)` with the current definition. Its code and detail go in the row, the detail as a plain `str`, so psycopg never has to choose a dumper for the `StrEnum`.

   Then one `insert_reevals()` per chunk, with `policy_version` = the current version and `reevaluated_by` = `user_id`.
4. `append_entry(PgAuditRepo(conn), actor="user:<id>", action="scan.reevaluate", target="scan:<uuid>", detail={policy_id, scan_policy_version, policy_version, rows_added, not_in_version})`. The target is 41 characters (well under 255). There is no alert.
5. If `wake` is given, `tx.on_commit(wake)`, then commit and return `ReevalResult`.

Interface change carried from TASK-183: `StoredResult.stdout` is `str | None` (step 3.3).

## Acceptance points

- **REQ-200 (1):** The scratch run of `_batch` covered PASS (`ok\r\n` under `equals ok`), FAIL, `oversize` kept, NULL stdout → `cannot evaluate`, `gt 5` on `x` → `stdout not numeric`, `runner_unavailable` kept, a dropped plugin (skipped 1) and exit 137 → `killed by signal`. Every detail came out as a plain `str`.
- **REQ-200 (2), (9):** the only writes are `INSERT INTO scan_result_reeval` and the audit insert. No UPDATE, DELETE or `FOR UPDATE` anywhere.
- **REQ-200 (3):** a second run adds rows with higher `reeval_id`s, so REQ-197 shows them.
- **REQ-200 (4):** audit fields as in step 4. `append_entry` keeps the chain.
- **REQ-200 (5):** both exceptions are raised before any insert, inside the transaction.
- **REQ-200 (6):** everything is in one transaction, so a fault after the first chunk rolls back the rows and the entry.
- **REQ-200 (7):** no results means no chunk and no insert. The audit entry is still written, with `rows_added` 0.
- **REQ-200 (8):** a disabled policy is not refused (only `deleted` is checked).
- **REQ-201 (1), (5):** the lock comes from `lock_scan`, keyed per scan.
- **REQ-201 (2):** definitions come from one statement, read once before any result.
- **REQ-201 (3):** the server-side cursor's snapshot is taken at DECLARE, so a result committed later is not seen.
- **REQ-201 (4):** at most one chunk of `StoredResult` and one batch of `ReevalInsert` are held at a time.
- **REQ-202:** no `logging` import. The exceptions carry no arguments. The audit detail holds only ids and counts. Details are the `Detail` constants.

## Mutation plants (M8 table)

- **CHK-M8-353:** add `conn.execute("UPDATE scan_result SET eval_code = %s WHERE job_id = %s …")` in the chunk loop. The grant refuses it, and the test must see the failure. Expect G64 and G65 red.
- **CHK-M8-355:** delete the `INTAKE_DETAILS` branch in `_new_verdict`. An `oversize` row with `''` stdout under `empty` then becomes PASS. Expect G64 red.
- **CHK-M8-356:** in `_batch`, on `spec is None`, append `ReevalInsert(row.job_id, row.plugin_uuid, …original…)`. Expect G64 red.
- **CHK-M8-357:** `if defs is None or defs.deleted` → `if defs is None`. Expect G64 red.
- **CHK-M8-359:** move `append_entry` into its own `db.transaction()` after the main one, or delete it. Expect G64 red (fault-injection row).
- **CHK-M8-360 (service half):** collect all chunks into one list before inserting. Expect G64 memory row red.
- **CHK-M8-362:** `log.debug("stdout %s", row.stdout)` in `_new_verdict`, or `raise ScanNotFound(str(row.stdout))`. Expect G65 canary red.
- **New (lead decision 2026-10-29):** delete the `row.stdout is None` branch and COALESCE stdout to `''` (in `reeval._STORED` or here as `row.stdout or ""`). Expect red: a NULL-stdout result under `empty` must give ERROR `cannot evaluate`, not PASS.

## Gates (worktree root, worktree's own `manager/.venv`)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 324 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`, and with `--platform linux`: no issues in 324 files.

No local PostgreSQL, so the service hasn't been run end to end. Only the pure `_batch` scratch above was run.

## For the tester

- `reevaluate_scan` takes a `runtime.Database` (READ COMMITTED transactions). `PgAuditRepo` refuses autocommit and other isolation levels, and so does `lock_scan`.
- `wake` runs only on commit; a raised `ScanNotFound` or `PolicyDeleted` never calls it.
- The NULL-stdout row: fixtures must write `stdout` NULL explicitly, because the column has no default. The expected outcome is ERROR `cannot evaluate` even under `empty`/`not_empty`, and the result still counts in `rows_added`.

## Revision 1 (2026-10-29, lead decision "Re-evaluation fails closed on an unrecognised stored ERROR detail")

- What changed: `_new_verdict` now applies four rules, in this order (after `_batch` skips plugins the current version no longer lists):
  1. An intake detail keeps its detail.
  2. **New:** `eval_code == 2` with a stored detail that is not a `Detail` value (NULL, an unknown or legacy text, a case or whitespace variant such as `' Oversize '`) gives ERROR `cannot evaluate`.
  3. A NULL stdout gives ERROR `cannot evaluate`.
  4. Otherwise `classify()`.
- Which errors still reach `classify()`: an ERROR with a known evaluation detail (for example `timed out` or `stdout not numeric`) is classified again. A non-ERROR original with an odd detail also reaches `classify()`, because the rule applies to `eval_code == 2` only.
- Why it can't raise: the stored text is only ever tested for membership in a frozenset, never passed to `Detail(text)`.
- Size: `reevaluate.py` is 149 lines.
- Scratch check of `_batch` (`empty` operator, stdout `''`):

  | Stored code and detail | New verdict |
  | --- | --- |
  | 2 `'oversize'` | 2 `'oversize'` |
  | 2 `' Oversize '` | 2 `'cannot evaluate'` |
  | 2 NULL | 2 `'cannot evaluate'` |
  | 2 `'legacy text'` | 2 `'cannot evaluate'` |
  | 2 `'timed out'` | 0 (re-classified) |
  | 0, NULL stdout | 2 `'cannot evaluate'` |
  | 1 `'weird'` | 0 (re-classified) |
- New plant: delete step 2 (the `row.eval_code == ERROR and row.eval_detail not in _KNOWN_DETAILS` branch). A `' Oversize '` ERROR with stdout `''` then re-evaluates to PASS under `empty`, and the test must go red. A second variant: test `row.eval_detail is not None` instead of NULL-or-unknown, so that an ERROR with a NULL detail becomes PASS.
- Gates: the same as TASK-183 r1. Both files are clean. The only whole-tree red is in tester-m8's in-progress `test_evaluator_operators.py`.
