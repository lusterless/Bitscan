# TASK-183 IMPL: re-evaluation repository

Implementer: impl-manager-m8b. REQ-200, REQ-201 (REQ-204 through its tests). Risk high. Plan: `work/plans/TASK-185.md` §2 (design note D4). Spec: TS §4.5 L601, §5.2 L859–L938 and L994–L1013 (grants), §2.2 L114. Answers applied: #118 (f), (h); #12 (the intake details are carried in `eval_detail`); lead decision 2026-10-29, "A NULL `scan_result.stdout` on re-evaluation".

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/repositories/reeval.py` (new, 160 lines) | `CHUNK`, `ScanRef`, `Definitions`, `StoredResult`, `ReevalInsert`, `lock_scan()`, `current_definitions()`, `stored_results()`, `insert_reevals()` |

No file outside the task's list was changed. No migration.

## Interface (plan §2, with one approved change)

```python
CHUNK: Final = 1000
@dataclass(frozen=True, slots=True) class ScanRef: scan_id: UUID; policy_id: int; policy_version: int
@dataclass(frozen=True, slots=True) class Definitions:
    policy_version: int; deleted: bool
    plugins: Mapping[UUID, tuple[str, str]]      # (operator, expected_result); a MappingProxyType
@dataclass(frozen=True, slots=True) class StoredResult:
    job_id: UUID; plugin_uuid: UUID
    stdout: str | None                           # CHANGED from str (lead decision 2026-10-29)
    exit_code: int | None; timed_out: bool; truncated: bool; eval_detail: str | None
@dataclass(frozen=True, slots=True) class ReevalInsert:
    job_id: UUID; plugin_uuid: UUID; eval_code: int; eval_detail: str | None

def lock_scan(conn, scan_id: UUID) -> ScanRef | None
def current_definitions(conn, policy_id: int) -> Definitions | None
def stored_results(conn, scan_id: UUID, *, chunk: int = CHUNK) -> Iterator[list[StoredResult]]
def insert_reevals(conn, rows: Sequence[ReevalInsert], *, policy_version: int, reevaluated_by: int) -> int
```

**Interface change:** `StoredResult.stdout` is `str | None`. A NULL `scan_result.stdout` (allowed by TS §5.2 L903) is returned as `None`, never COALESCEd to `''`. TASK-185 gives such a result ERROR `cannot evaluate` without calling `classify()`, so `empty` can never PASS on a missing value. The planner's TASK-185 plan §2 still says `str`; the decision row records the change.

## Behaviour

- `lock_scan`:
  - Raises `RuntimeError` (fixed text) when the connection is in autocommit, because an xact lock would end with its own statement.
  - Takes `pg_advisory_xact_lock(hashtext('scan_reeval'), hashtext(CAST(CAST(%(scan_id)s AS uuid) AS text)))`. The two-key form is a separate lock space from the single-key `hashtext('audit_log')` and the catalog locks.
  - Then `SELECT scan_id, policy_id, policy_version FROM scan WHERE scan_id = …`. It takes no row lock, so intake and scan-state updates are never blocked.
  - The lock is released at commit or rollback, so there is no unlock path to forget.
- `current_definitions`: one statement, `policy p LEFT JOIN (policy_plugin pp JOIN plugin pl …) ON pp.policy_id = p.policy_id`.
  - A policy listing no plugin gives `plugins` = `{}`. An unknown `policy_id` gives `None`.
  - Under READ COMMITTED the one statement is one snapshot, so the version and the definitions always belong together (#118 (f)).
  - Only `policy_plugin` membership counts; `plugin.state` is not read (#118 (a)).
- `stored_results`:
  - A named (server-side) cursor `reeval_results` with `itersize = chunk` and `fetchmany(chunk)`, so each yielded list has at most `chunk` rows. Results come in `ORDER BY r.job_id, r.plugin_uuid`, with originals and retries both included.
  - The join uses `job_created_at = created_at` for partition pruning.
  - `chunk < 1` raises `ValueError`.
  - Must be consumed inside the caller's transaction. Closing the generator closes the cursor.
- `insert_reevals`:
  - Empty input returns 0 and runs no statement.
  - Otherwise one `INSERT … SELECT … FROM unnest(uuid[], uuid[], smallint[], text[])`, returning `rowcount`.
  - `reevaluated_at` keeps its default.
  - No `ON CONFLICT`, no UPDATE, no DELETE.

Grants used (TS §5.2 L994–L998): SELECT on `scan`, `scan_job`, `scan_result`, `policy`, `policy_plugin`, `plugin`; INSERT on `scan_result_reeval`, with USAGE on `scan_result_reeval_reeval_id_seq`. Advisory locks need no grant.

## Acceptance points (task row) and how they are met

- **Each function works with only the TS §5.2 grants:** see the list above. Nothing needs UPDATE, DELETE or `FOR UPDATE`.
- **The definitions read is one statement (statement spy):** `current_definitions` makes exactly one `execute`.
- **Chunks never exceed the given size and cover each result exactly once:** `fetchmany(chunk)` on one ordered server-side cursor.
- **Inserting N rows adds exactly N:** one `unnest` row per input row; the return value is the statement's `rowcount`.
- **Two sessions locking one scan serialise, and two scans do not:** the second key is the hash of the scan's canonical uuid text. A `hashtext` collision between two scans would only serialise them, which is harmless.
- **S608 passes, and a planted f-string is red:** every query is a literal string constant with named parameters.

## Mutation plants for this task (M8 table)

- **CHK-M8-350:** make `_STORED` an f-string, e.g. `f"… WHERE j.scan_id = '{scan_id}' …"`. Expect G1 (S608) red.
- **CHK-M8-354:** split `current_definitions` into a version read plus one `SELECT … FROM plugin WHERE plugin_uuid = …` per listed plugin. Expect the G64 race row and the statement spy red.
- **CHK-M8-358:** delete the `pg_advisory_xact_lock` statement in `lock_scan`. Expect the G64 concurrent row red.
- **CHK-M8-360:** replace the cursor loop with one `conn.execute(_STORED, …).fetchall()` yielded as a single list. Expect the G64 memory or chunk row red.
- **New (lead decision 2026-10-29):** change `r.stdout` in `_STORED` to `COALESCE(r.stdout, '')`. A NULL-stdout result under `empty` then PASSes instead of ERROR `cannot evaluate`, and the TASK-185 test must turn red. The repository side of the check: a NULL `stdout` row must come back as `StoredResult.stdout is None`.

## Gates (run from the worktree root, with the `Bitscan-m7` venv's tools, as for TASK-182)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 316 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`, and the same with `--platform linux`: no issues, 316 files each.

No local PostgreSQL or Docker, so the statements haven't been run.

## For the tester

- `lock_scan` must run inside `db.transaction()` (READ COMMITTED, not autocommit). The race tests need two sessions, each in its own transaction.
- `stored_results` must be iterated inside the same transaction that called `lock_scan`.
- `insert_reevals` with an all-NULL `eval_detail` list relies on `CAST(... AS text[])` typing the array; please cover a chunk of PASS/FAIL rows only (every detail NULL).
- `Definitions.plugins` is read-only (`MappingProxyType`).

## Revision 1 (2026-10-29, lead decision "Re-evaluation fails closed on an unrecognised stored ERROR detail")

- What changed: `StoredResult` has a new field `eval_code: int` (the original `scan_result.eval_code`), placed before `eval_detail`. `_STORED` now selects `r.eval_code`. This is an interface change: positional construction of `StoredResult` now takes 8 values. `reeval.py` is 162 lines.
- Why: TASK-185 r1 needs the original code to fail closed on an ERROR whose stored detail is not recognised.
- Gates: ruff check and ruff format --check on `manager/bitscan_manager` pass. mypy --strict on `manager/bitscan_manager` passes, both on Windows and with `--platform linux` (159 files).
- Whole-tree gate: `ruff check manager` and `mypy manager` are currently red, but only in tester-m8's in-progress `manager/tests/test_evaluator_operators.py`: E501 at lines 52, 150, 313 and 369, and `no-untyped-call` at line 369. Neither file of this task is involved.
