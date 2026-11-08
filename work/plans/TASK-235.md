# TASK-235 plan: results read SQL and the results view (design note D2)

Covers TASK-233 (pure results view), TASK-235 (repository) and TASK-241 (service). Planner-m11, 2026-11-08. Answers used: #119, #144, #146, PD-46. `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §4.5 L603: "Results views, CSV exports and scores use the latest `scan_result_reeval` row for each job and plugin when one exists, otherwise the original result; plugins no longer in the current version keep their original verdict. The API returns both `result` and `original_result`."
- TS §4.4 L585: "Plugins with no result show as *Not run* and are left out of the score."
- TS §6.2 L1123: "`stdout` and `stderr` are included only for operator and admin."
- TS §6.3 L1144: the CSV formula rule, "This applies to every export."
- REQ-197 (M8): one pure function (`effective()`) and one SQL form implement the latest-row rule.

## 2. Pure results view (`bm/services/jobs/results_view.py`, TASK-233)

```python
Status = Literal["PASS", "FAIL", "ERROR", "NOT_RUN"]
CSV_MAX_ROWS: Final = 100_000
CSV_HEADER: Final = ("hostname", "agent_id", "plugin_uuid", "plugin_name", "result",
    "eval_detail", "original_result", "original_eval_detail", "reevaluated_at",
    "reeval_policy_version", "exit_code", "timed_out", "truncated", "started_at",
    "finished_at", "job_id", "retry")
OUTPUT_COLUMNS: Final = ("stdout", "stderr")

class InvalidResultQuery(Exception): ...          # message names the parameter only
@dataclass(frozen=True) class ResultQuery: status: Status | None; agent_id: UUID | None
def include_output(role: str) -> bool             # True for "operator" and "admin" only
def item(row: ResultRow, *, with_output: bool) -> dict[str, object]  # keys of ResultItem(+Output)
def csv_text(rows: Iterable[ResultRow], *, with_output: bool) -> str  # csv_export.write_csv
```

- `include_output` is the only place the role rule lives. An unknown role is False (fails closed).
- `item(..., with_output=False)` builds a mapping with **no** `stdout`/`stderr` key; the route picks `ResultItem` or `ResultItemWithOutput` from the same flag.
- CSV cells: null → `""`, booleans `true`/`false`, times RFC 3339 UTC with `Z`, codes as `PASS`/`FAIL`/`ERROR`; every cell, header included, through `csv_export.write_csv` (which calls `escape_cell`). Never Python's `csv` module (CHK-M11-324).
- Pure: imports only `csv_export`, the row dataclass type and the standard library.

## 3. Repository (`bm/repositories/result_reads.py`, TASK-235)

PD-46 (a): compose M8's CTE, never copy it.

```python
from bitscan_manager.repositories import results as _m8
_PAGE = sql.SQL("{} , planned AS (...), rows AS (...) SELECT ... ").format(_m8._EFFECTIVE)
```

(The private import is deliberate and pinned by a test: `results.py` byte-identical to `6efe0fb`, and `_PAGE` begins with `_m8._EFFECTIVE`'s text.)

Statement (one per page), continuing after `_EFFECTIVE`'s `jobs`, `latest`, `eff`:

```sql
, planned AS (
    SELECT j.agent_id, j.job_id AS orig_job_id, p.ord,
           CAST(p.item ->> 'plugin_uuid' AS uuid) AS plugin_uuid,
           p.item ->> 'execute' AS planned_execute
    FROM jobs j
    CROSS JOIN LATERAL jsonb_array_elements(j.payload -> 'plugins')
         WITH ORDINALITY AS p(item, ord)
    WHERE j.retry_of IS NULL)
SELECT pl.agent_id, a.hostname, pl.ord, pl.plugin_uuid, pl.orig_job_id,
       e.job_id, e.original_code, e.original_detail, e.code, e.detail,
       e.policy_version, e.reevaluated_by, e.reevaluated_at,
       r.plugin_name_snap, r.operator_snap, r.expected_snap, r.execute_snap,
       r.exit_code, r.timed_out, r.truncated, r.started_at, r.finished_at,
       r.received_at, r.stdout, r.stderr,
       pl.planned_execute, sj.eval_spec               -- not-run name, operator, expected
FROM planned pl
JOIN agent a ON a.agent_id = pl.agent_id
LEFT JOIN eff e ON e.agent_id = pl.agent_id AND e.plugin_uuid = pl.plugin_uuid
LEFT JOIN jobs rj ON rj.job_id = e.job_id
LEFT JOIN scan_result r ON r.job_id = e.job_id AND r.plugin_uuid = e.plugin_uuid
                       AND r.job_created_at = rj.created_at
LEFT JOIN scan_job sj ON sj.job_id = pl.orig_job_id AND e.job_id IS NULL
WHERE (%(agent_id)s::uuid IS NULL OR pl.agent_id = %(agent_id)s)
  AND (%(status)s::text IS NULL
       OR (%(status)s = 'NOT_RUN' AND e.job_id IS NULL)
       OR (e.code = %(code)s))
  AND (%(after_agent)s::uuid IS NULL OR (pl.agent_id, pl.ord) > (%(after_agent)s, %(after_ord)s))
ORDER BY pl.agent_id, pl.ord
LIMIT %(limit)s
```

Notes:
- `stdout`/`stderr` are read only when the caller may see them: two statement variants, the viewer one selecting `NULL::text` for both, so a viewer's output never leaves the database (defence in depth beside TASK-233's mapping). The variant is chosen by the `with_output` flag the service passes.
- The not-run item's name, operator and expected come from the original job's `eval_spec` entry for that plugin (`parse_eval_spec`, M8), its execute from the payload item; never from the current catalog (CHK-M11-330).
- `retry` = `e.job_id IS NOT NULL AND e.job_id <> pl.orig_job_id`.
- One unit holds at most one result per plugin (first result wins, M9 REQ-216). If M8's deliberate double count ever appeared, the page would show two items for a plugin; the property test of TP-M11-04 runs on intake-written data, where it cannot.
- `read_only_snapshot()` (as `PackageSearchRepo`): `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`, the first statement of the transaction; the service always calls it.
- `exists(scan_id)`: one SELECT, so an unknown scan is 404 rather than an empty page.
- CSV read: the same statement without the keyset, `LIMIT CSV_MAX_ROWS + 1`; the service raises `TooManyRows` when the extra row exists, before building any text.

Cost (recorded, accepted): every page re-reads the scan's jobs (`scan_job` has no index on `scan_id`, #127 (f)) and `scan_result_reeval` once (no index on `job_id`, M8 note). `EXPLAIN` must show `scan_result_reeval` scanned once per statement (no correlated subquery: CHK-M11-368) and partition pruning on `scan_result` through `job_created_at`.

## 4. Service (`bm/services/jobs/results_read.py`, TASK-241)

`results_page`: one transaction → `read_only_snapshot()` → `exists()` → page read with `limit + 1` → map with `results_view.item()`; the extra row only sets `next_cursor`. `results_csv`: one transaction → snapshot → `exists()` → CSV read → `TooManyRows` or `results_view.csv_text()`. Both take `role` and derive `with_output = include_output(role)` once.

## 5. Edge cases the tests must hit

- A result re-evaluated twice: `result` from the higher `reeval_id` even when its `reevaluated_at` is earlier (#119).
- A plugin dropped from the current version and re-evaluated before it was dropped: shows that earlier re-evaluation (#118 (b)).
- An intake ERROR (`oversize` stored with empty streams; `runner_unavailable` from a 0.1.0 agent): ERROR with that detail, both verdicts equal.
- A host whose job is still `queued`: every plugin *Not run*.
- A result in the retry for a plugin of the original: one item, `retry` true; the original's not-run row does not also appear.
- Results in two monthly partitions of one scan (a retry created in the next month): both read.
- `status=NOT_RUN` with `agent_id` of a host with no missing plugin: empty page, 200.
- A viewer through an operator's revoked role: the role is read per request.
- NUL already replaced by U+FFFD at intake (#121): returned as stored; a `‮` or `<script>` in stdout is returned verbatim as a JSON string (the UI renders it as text).
