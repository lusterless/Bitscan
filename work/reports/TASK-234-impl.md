# TASK-234 IMPL: scan reads repository

Implementer: impl-manager-a. REQ-264, REQ-265, REQ-266, REQ-272. Risk medium. Spec: TS §6.2 L1113, L1120, L1122; §6.3 L1136; §5.2 (`scan`, `scan_job`, `policy`, `agent`). Answers applied: #89, #145. Plan: `work/plans/TASK-232.md` (§3 operations, §4 models, §5 services).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/repositories/scan_reads.py` (new, 233 lines, 169 of code) | the whole task |

## Interface (frozen once W1 passes)

```python
AnchorGone  # re-exported: the same class as repositories.packages.AnchorGone (agents, packages)
@dataclass ScanRow: scan_id, policy_id, policy_name, policy_version, trigger, schedule_id,
    requested_by, state (scan.state as stored), target_kind ("agents"|"tags"|"all"),
    resolved_count, created_at, finished_at
@dataclass ScanDetailRow: scan: ScanRow; target: dict[str, Any]   # stored target minus resolved_agents
@dataclass JobRow: job_id, agent_id, hostname, state, retry_of, dispatched_at, started_at, finished_at
def scan_page(conn, *, policy_id, agent_id, state, created_after, created_before, limit, after: UUID | None) -> list[ScanRow]
def agent_scan_page(conn, agent_id, *, limit, after) -> list[ScanRow]
def agent_exists(conn, agent_id) -> bool
def scan_detail(conn, scan_id) -> ScanDetailRow | None
def scan_jobs(conn, scan_id) -> list[JobRow]
```

## Behaviour

- **Order and keyset (#89, #145 (d)).**
  - Lists are `created_at DESC, scan_id DESC`. The keyset is `(created_at, scan_id) < (anchor)`.
  - The cursor's `after` is the anchor `scan_id` only; its `created_at` is read with a separate `SELECT` in the caller's transaction.
  - A missing anchor raises `AnchorGone`. Re-exporting the existing class means TASK-240 and TASK-244 have one type to map to 400.
- **Filters, combined with AND and each one `(param IS NULL OR …)`:**
  - `policy_id` (`::bigint`);
  - `state`, compared as text (`s.state::text = %(state)s::text`), so a bad value can never fail an enum cast;
  - `created_after` as `>=` and `created_before` as `<`.
  - `agent_id` is a JSONB containment test with a parameter: `s.target -> 'resolved_agents' @> jsonb_build_array(%(agent)s::text)`, with `str(UUID)` (lowercase, as `stored_target` writes). Only the `resolved_agents` array is tested, so the same text in a tag never matches.
- **Times.** They are bound in UTC (`astimezone(UTC)`) because PostgreSQL refuses offsets past ±15:59, which `AwareDatetime` accepts (for example `+18:00`; builder checklist 1). A moment outside Python's UTC range (year 1 with a positive offset, year 9999 with a negative one) clamps to `datetime.min` or `datetime.max` in UTC, which selects the same rows. A naive datetime raises `ValueError`.
- **`target_kind`.** It is a `CASE` on the stored target's keys (`?`). `resolved_count` is `jsonb_array_length(target -> 'resolved_agents')`, or 0 when absent. An unknown kind raises `ValueError` (fixed text).
- **The resolved list stays in the database.** `scan_detail` selects `s.target - 'resolved_agents'`, so up to 10,000 ids never leave PostgreSQL (#145 (b)).
- **`scan_detail` and `scan_jobs`.**
  - `scan_detail` joins `policy` for the name. Policies are only soft-deleted, so a scan of a deleted policy is still returned (REQ-265 (4)).
  - `scan_jobs` returns compliance jobs only, joined to `agent` for the current hostname. They are ordered by hostname, `agent_id`, then original before retry (`retry_of IS NOT NULL`), `created_at` and `job_id`. It reads `scan_job` without an index on `scan_id` (#127 (f), accepted).
- **Host history.** It goes through the stored resolved target only, with no `scan_job` read (#145 (c)). `agent_exists` lets TASK-240 answer `AgentNotFound` for an unknown agent; a decommissioned agent still exists.
- **Statements.** SELECT only, with `psycopg.sql` composition of constant fragments and `%(name)s` parameters. No string building (S608).

## Notes

- No PostgreSQL run by me (WSL is the tester's). Please run CHK-M11-105 to -114.
- The repository takes keyword filters, not TASK-240's `ScanFilters`, so it does not import the service (layering).

## Commands run

As in the TASK-233 report. The file is clean under ruff, ruff format and `mypy --strict`.
