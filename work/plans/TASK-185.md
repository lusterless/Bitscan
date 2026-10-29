# TASK-185 plan: re-evaluation service (with the TASK-183 repository interface)

Planner: planner-m8, 2026-10-29. Design note D4 in `work/tasks.md`. Requirements REQ-200, REQ-201, REQ-202, REQ-204. Open questions #12 (agreed), #112, #118, #119. `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §4.5 L601: "if a later import corrects an Operator or ExpectedResult, an admin can re-evaluate a scan against the policy's current version (`POST /api/v1/scans/{id}/reevaluate`, TOTP session, audit-logged). New verdicts are added to `scan_result_reeval`; original results never change. … plugins no longer in the current version keep their original verdict."
- TS §2.2 L114: "Scan results snapshot the plugin name, command, Operator, ExpectedResult and policy version at run time. Re-evaluation adds rows; it never changes them."
- TS §5.2 L933: `policy_version INTEGER NOT NULL, -- policy.version whose Operator and ExpectedResult were used`; L1005–L1006: the app may never change `scan_result` or `scan_result_reeval`.
- TS §5.3 L1049: "Re-evaluations are the one way the app changes a shown verdict, and they are only added through the admin route in §4.5."
- #12 (agreed): runner-error and oversize results "stay ERROR on re-evaluation".

## 2. TASK-183 interface (`bm/repositories/reeval.py`)

```python
@dataclass(frozen=True, slots=True)
class ScanRef:
    scan_id: UUID
    policy_id: int
    policy_version: int          # the version the scan was built from

@dataclass(frozen=True, slots=True)
class Definitions:
    policy_version: int          # policy.version now
    deleted: bool                # policy.deleted_at IS NOT NULL
    plugins: Mapping[UUID, tuple[str, str]]   # plugin_uuid -> (operator, expected_result), listed by the current version

@dataclass(frozen=True, slots=True)
class StoredResult:
    job_id: UUID
    plugin_uuid: UUID
    stdout: str | None           # scan_result.stdout is nullable (TS §5.2 L903); NULL rule below
    exit_code: int | None
    timed_out: bool
    truncated: bool
    eval_code: int               # the original code (TASK-183 r1); 2 = ERROR
    eval_detail: str | None      # the original detail (intake details are kept, #12)

@dataclass(frozen=True, slots=True)
class ReevalInsert:
    job_id: UUID
    plugin_uuid: UUID
    eval_code: int
    eval_detail: str | None

def lock_scan(conn, scan_id: UUID) -> ScanRef | None: ...
def current_definitions(conn, policy_id: int) -> Definitions | None: ...
def stored_results(conn, scan_id: UUID, *, chunk: int = 1000) -> Iterator[list[StoredResult]]: ...
def insert_reevals(conn, rows: Sequence[ReevalInsert], *, policy_version: int, reevaluated_by: int) -> int: ...
```

**Unrecognised stored ERROR detail rule** (decisions 2026-10-29, "Re-evaluation fails closed on an unrecognised stored ERROR detail"): a stored result with `eval_code` 2 whose `eval_detail` is not a `Detail` value, NULL included, re-evaluates to ERROR `cannot evaluate` without calling `classify()`.

**NULL stdout rule** (decisions 2026-10-29, "A NULL scan_result.stdout on re-evaluation"): a stored result whose `stdout` is NULL re-evaluates to ERROR `cannot evaluate` without calling `classify()`.

Order of the rules (§4 step 3): intake detail (kept) → unrecognised stored ERROR detail → NULL stdout → `classify()`.

SQL (parameterised; one statement each):
- `lock_scan`: `SELECT pg_advisory_xact_lock(hashtext('scan_reeval'), hashtext(%(scan_id)s::text))`, then `SELECT scan_id, policy_id, policy_version FROM scan WHERE scan_id = %(scan_id)s`. A transaction-level lock: released at commit or rollback, so no unlock path can be forgotten. It never blocks M9's intake or the scan's state updates (no row lock on `scan`). Two different scans use different keys (a `hashtext` collision only serialises two unrelated re-evaluations, which is harmless).
- `current_definitions`: `SELECT p.version, p.deleted_at IS NOT NULL, pl.plugin_uuid, pl.operator::text, pl.expected_result FROM policy p LEFT JOIN policy_plugin pp ON pp.policy_id = p.policy_id LEFT JOIN plugin pl ON pl.plugin_uuid = pp.plugin_uuid WHERE p.policy_id = %(policy_id)s`. One statement is one snapshot under READ COMMITTED, so the version and the definitions always belong together, even while an import of the policy commits (the importer writes `policy`, `policy_plugin` and `plugin` in one transaction, M7 D3). `None` when the policy row does not exist (a foreign key makes that impossible; returned for totality).
- `stored_results`: a named (server-side) cursor inside the caller's transaction over `SELECT r.job_id, r.plugin_uuid, r.stdout, r.exit_code, r.timed_out, r.truncated, r.eval_code, r.eval_detail FROM scan_job j JOIN scan_result r ON r.job_id = j.job_id AND r.job_created_at = j.created_at WHERE j.scan_id = %(scan_id)s AND j.kind = 'compliance' ORDER BY r.job_id, r.plugin_uuid`, fetched `chunk` rows at a time. Memory is bounded by the chunk (REQ-201 (4)).
- `insert_reevals`: `INSERT INTO scan_result_reeval (job_id, plugin_uuid, policy_version, eval_code, eval_detail, reevaluated_by) SELECT j, p, %(v)s, c, d, %(by)s FROM unnest(%(jobs)s::uuid[], %(plugins)s::uuid[], %(codes)s::smallint[], %(details)s::text[]) AS t(j, p, c, d)`; returns the row count. `reevaluated_at` keeps its default (`now()`).

Grants used (TS §5.2 L994–L998): SELECT on `scan`, `scan_job`, `scan_result`, `policy`, `policy_plugin`, `plugin`; INSERT on `scan_result_reeval` and USAGE on its sequence; the advisory lock functions need no grant. No UPDATE, DELETE or row lock.

## 3. TASK-185 interface (`bm/services/evaluator/reevaluate.py`)

```python
class ScanNotFound(Exception): ...     # M11: 404 not_found
class PolicyDeleted(Exception): ...    # M11: 409 conflict (#118 (c))

@dataclass(frozen=True, slots=True)
class ReevalResult:
    scan_id: UUID
    policy_id: int
    scan_policy_version: int
    policy_version: int
    rows_added: int
    not_in_version: int

def reevaluate_scan(db: Database, scan_id: UUID, *, user_id: int,
                    wake: Callable[[], None] | None = None) -> ReevalResult: ...
```

The admin TOTP-session check, the sink gate (refused after 15 minutes of sink outage, a sensitive action), the 404/409 mapping and the response body are the M11 route's (`require_totp_session("admin")`); the service trusts its caller for authorisation, like the M7 delete service.

## 4. Algorithm (one `db.transaction()`)

1. `ref = reeval.lock_scan(conn, scan_id)`; `None` → raise `ScanNotFound` (the transaction rolls back; nothing written).
2. `defs = reeval.current_definitions(conn, ref.policy_id)`; `defs is None or defs.deleted` → raise `PolicyDeleted`.
3. For each chunk of `reeval.stored_results(conn, scan_id)`:
   - for each row: if `row.plugin_uuid not in defs.plugins`: `not_in_version += 1`, no row (#118 (b));
   - elif `row.eval_detail in INTAKE_DETAILS`: `ReevalInsert(…, 2, row.eval_detail)` (#12, #118 (e)); the intake details win over every later rule;
   - elif `row.eval_code == 2 and row.eval_detail not in {d.value for d in Detail}` (NULL included): `ReevalInsert(…, 2, Detail.CANNOT_EVALUATE)`, without calling `classify()` (§2 unrecognised stored ERROR detail rule; decisions 2026-10-29, fails closed);
   - elif `row.stdout is None`: `ReevalInsert(…, 2, Detail.CANNOT_EVALUATE)`, without calling `classify()` (§2 NULL stdout rule; decisions 2026-10-29; order confirmed by the lead);
   - else: `v = classify(op, expected, row.stdout, row.exit_code, row.timed_out, row.truncated)` with `(op, expected) = defs.plugins[row.plugin_uuid]`, then `ReevalInsert(…, v.code, v.detail)`;
   - `rows_added += reeval.insert_reevals(conn, batch, policy_version=defs.policy_version, reevaluated_by=user_id)`.
4. `append_entry(PgAuditRepo(conn), actor=f"user:{user_id}", action="scan.reevaluate", target=f"scan:{scan_id}", detail={"policy_id": …, "scan_policy_version": ref.policy_version, "policy_version": defs.policy_version, "rows_added": rows_added, "not_in_version": not_in_version})` (#118 (g)); no alert.
5. `if wake: tx.on_commit(wake)`; leave the block (commit). Return `ReevalResult`.

Why this order: the lock comes first so a second re-evaluation of the same scan waits before it reads anything (its rows then get higher `reeval_id`s, #119); definitions are read once, before any result, so every row of one run uses one version; the audit entry is last, so it records the true counts, and it shares the transaction, so a fault anywhere leaves neither rows nor entry (REQ-200 (6)).

## 5. Races and accepted behaviour

| Case | Behaviour | Test (REQ-201) |
| --- | --- | --- |
| Two re-evaluations of one scan | the second blocks on the advisory lock until the first commits, then reads and inserts; its rows have higher ids and become the latest | (1), two sessions and a barrier |
| An import of the policy commits during the run | the single definitions statement sees either the old or the new version, never a mix; the recorded `policy_version` matches | (2), an import thread released by a barrier between steps 1 and 2, and again between 2 and 3 |
| Intake stores a late result during the run | the server-side cursor's snapshot is taken at its first fetch; a row committed afterwards is not seen and keeps its intake verdict until the next run | (3), insert from a second session after the first chunk |
| Re-evaluations of two scans | different lock keys; neither waits | (5) |
| The manager stops mid-run | the transaction rolls back: no rows, no audit entry | REQ-200 (6) (fault injection) |

## 6. Output handling

No log line in this module carries stdout, stderr, an expected value or a pattern; exceptions carry only ids. The audit detail holds only ids and counts. `classify()` details are the #112 constants. REQ-202 (2) runs the suite with a canary in every text column.

## 7. Size

`repositories/reeval.py` about 160 lines; `reevaluate.py` about 110 lines. If `reeval.py` grows past 200, `insert_reevals` moves to `repositories/reeval_insert.py` (one task id).
