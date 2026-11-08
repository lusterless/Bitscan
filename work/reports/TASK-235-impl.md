# TASK-235 IMPL: result reads repository (composes M8's `_EFFECTIVE`)

Implementer: impl-manager-a. REQ-267, REQ-269, REQ-272. Risk high (second look, PD-47). Spec: TS §4.5 L603; §4.4 L585; §6.2 L1123; §5.2 (`scan_job`, `scan_result`, `scan_result_reeval`). Answers applied: #119, #144, PD-46. Plan: `work/plans/TASK-235.md` §3.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/repositories/result_reads.py` (new, 251 lines, 187 of code) | the whole task |

`manager/bitscan_manager/repositories/results.py` (M8, frozen) is unchanged; `git diff` on it is empty.

## Interface (frozen once W1 passes)

```python
class UnreadableRow(Exception)       # fixed text
@dataclass(frozen=True, slots=True) class ResultRow:
    agent_id: UUID; hostname: str; position: int; plugin_uuid: UUID; orig_job_id: UUID
    job_id: UUID | None                 # None = Not run
    original_code: int | None; original_detail: str | None
    code: int | None; detail: str | None          # effective (#119)
    reeval_policy_version: int | None; reevaluated_by: int | None; reevaluated_at: datetime | None
    plugin_name: str; operator: str; expected: str; execute: str
    exit_code: int | None; timed_out: bool | None; truncated: bool | None
    started_at: datetime | None; finished_at: datetime | None; received_at: datetime | None
    stdout: str | None; stderr: str | None        # always None in the viewer variant
    retry: bool  (property)                       # job_id is not None and job_id != orig_job_id
def read_only_snapshot(conn) -> None
def exists(conn, scan_id) -> bool
def results_page(conn, scan_id, *, status, agent_id, with_output, after: tuple[UUID, int] | None, limit) -> list[ResultRow]
def results_export(conn, scan_id, *, status, agent_id, with_output, max_rows) -> list[ResultRow]   # reads max_rows + 1
```

`status` takes `PASS`, `FAIL` or `ERROR` (on the effective code), `NOT_RUN`, or None. Anything else raises `ValueError` before any statement runs; the service validates the value first (TASK-233 `parse_query`).

## The statement (one per page or export)

- `_PAGE = _ROWS.format(effective=_m8._EFFECTIVE, output=…)`. The text begins with `results._EFFECTIVE`'s text: it is composed, not copied (PD-46; `_PAGE.as_string(None).startswith(_m8._EFFECTIVE.as_string(None))` is True).
- After `_EFFECTIVE`'s `jobs`, `latest` and `eff`, the statement adds the following.
  - **`planned`:** the plugins of each original job's payload, `WITH ORDINALITY` (position 1-based, bigint), with `plugin_uuid` and the payload `execute`.
  - **`specs`:** each original job's `eval_spec` entries (`plugin_uuid`, `name`, `operator`, `expected`).
    - This is joined by `(job_id, plugin_uuid)`, so it does not rely on array order.
    - It is a hash-joinable set, read once per original job. Plan §3 fetched the whole `sj.eval_spec` per row and parsed it in Python; that would have sent a job's full `eval_spec` (up to 5,000 entries) once per not-run row.
    - The parse stays in SQL so the repository does not import the M8 service `parse_eval_spec` (layering).
    - This is a deviation from the plan's sketch. The outcome is the same: the name, Operator and ExpectedResult of a not-run item come from the original job's `eval_spec` and its Execute from the payload, never from the current catalog (CHK-M11-330).
  - **Joins:**
    - `planned` JOIN `agent`, for the current hostname;
    - LEFT JOIN `eff` on `(agent_id, plugin_uuid)`, which covers the original and the retry;
    - LEFT JOIN `jobs rj` for the result job's `created_at`;
    - LEFT JOIN `scan_result r` on `(job_id, plugin_uuid, job_created_at)`, so partitions prune;
    - LEFT JOIN `specs`.
  - **Columns:** for a not-run row (`e.job_id IS NULL`), name, operator, expected and execute come from `specs` and `planned`; otherwise from the snapshots (`operator_snap::text`).
  - **Filters, all parameterised:**
    - `agent_id`;
    - status, as `any_status OR (not_run AND e.job_id IS NULL) OR e.code = code::smallint`;
    - the keyset `(pl.agent_id, pl.ord) > (after_agent, after_ord)`.
  - `ORDER BY pl.agent_id, pl.ord LIMIT %(limit)s`.
- **Output only when allowed:**
  - `_PAGE` selects `r.stdout, r.stderr`.
  - `_PAGE_VIEWER` selects `NULL::text, NULL::text`, so a viewer's output never leaves the database.
  - The variant is chosen by `with_output`, which the service derives from `results_view.include_output(role)`.
- **`scan_result_reeval` cost:** it is read only inside `_EFFECTIVE`'s `latest` (one pass, `ANY(ARRAY(…))`). `eff` and `latest` are referenced once and inlined, and there is no correlated subquery (CHK-M11-368).
- **Other scans:** `jobs` is filtered by `scan_id`. `eff`, `rj` and the back-join are keyed on those jobs' ids, and `specs` on the original job ids, so another scan's rows cannot appear (CHK-M11-331).
- **`read_only_snapshot`:** `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`, as `PackageSearchRepo`. It must be the transaction's first statement.
- **`exists`:** `SELECT 1 FROM scan WHERE scan_id = …`.
- **`results_export`:** the same statement without a keyset, `LIMIT max_rows + 1`. The service compares the length with `CSV_MAX_ROWS` before building any text.

Every statement is `psycopg.sql` composition of constant fragments plus `%(name)s` parameters. No string building, so ruff S608 stays clean.

## Notes and risks for the reviewer

- **One-result rule.** One unit holds at most one result per plugin (M9 first result wins). If a plugin ever had results in both the original and the retry, the page would show two items for it (plan §3 note). Not guarded here.
- **`UnreadableRow`.** It is raised if a not-run plugin has no `eval_spec` entry. M9 always writes one entry per payload plugin (#117), so this is a can't-happen guard: it fails loudly instead of inventing a name.
- **Memory.** `results_export` loads up to 100,001 rows, each up to 64 KB stdout plus 16 KB stderr for operator and admin, so the worst case is several GB. This is what #146 (e) and (f) chose (built in full, no streaming). Recorded here, not changed.
- **Not run by me.** No PostgreSQL run: the rules keep WSL and Testcontainers for the tester. I rendered the composed statement and desk-checked it. Please run CHK-M11-118 to -131 first.

## Commands run

As in the TASK-233 report. `ruff check` and `ruff format --check` on the file are clean, and `mypy --strict` on `manager/bitscan_manager` passes. The only whole-tree failures are in `manager/tests/m11_pg_fixtures.py` (the tester's file).
