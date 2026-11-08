# TASK-240 IMPL: scan views service

Implementer: impl-manager-a. REQ-264, REQ-265, REQ-266. Risk medium. Spec: TS §6.2 L1113, L1120, L1122; §4.5 L602–L604; §4.4 L577–L585; §4.3 L552. Answers applied: #120, #145. Plan: `work/plans/TASK-232.md` §5. Built on TASK-234 (`repositories/scan_reads.py`), M8 `repositories/results.py` and `services/evaluator/score.py` (all unchanged).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/scan_views.py` (new, 138 lines, 89 of code) | the whole task |

## Interface (plan §5)

```python
class ScanNotFound(Exception); class AgentNotFound(Exception)
AnchorGone                      # re-exported from repositories.scan_reads (= packages.AnchorGone)
@dataclass(frozen=True) class ScanFilters: policy_id; agent_id; state; created_after; created_before
@dataclass HostView: agent_id: UUID; hostname: str; jobs: list[JobRow]; host: HostScore
@dataclass ScanDetail: scan: ScanRow; target: dict[str, Any]; hosts: list[HostView]
def list_scans(db, filters: ScanFilters, limit: int, after: UUID | None) -> list[ScanRow]
def scan_detail(db, scan_id: UUID) -> ScanDetail                       # raises ScanNotFound
def agent_scans(db, agent_id: UUID, limit: int, after: UUID | None) -> list[ScanRow]   # raises AgentNotFound
```

`ScanRow` and `JobRow` are TASK-234's rows. TASK-244 maps them to `ScanItem`, `HostJob` and `HostSummary`: `HostView.host` holds `passed`, `failed`, `errors`, `not_run` and `score`.

## Behaviour

- **`list_scans`:** one transaction, then `scan_reads.scan_page` with the filters. `AnchorGone` propagates, and the route turns it into a 400.
- **`agent_scans`:** one transaction. `scan_reads.agent_exists` raises `AgentNotFound` for an unknown agent (a decommissioned agent exists). Then `agent_scan_page`.
- **`scan_detail`:** one transaction whose first statement is `result_reads.read_only_snapshot` (REPEATABLE READ, READ ONLY). Then:
  - `scan_reads.scan_detail`, which raises `ScanNotFound` when there is no such scan;
  - `scan_reads.scan_jobs`;
  - M8's `results.host_counts`.

  All three read one snapshot (REQ-265).
- **Hosts:** the jobs grouped by agent, keeping the repository's order (hostname, `agent_id`, original first, then retry).
  - A host is an agent with an original job. A retry joins its original's host, so a retry's results count once.
  - Counts are M8's effective counts per agent (latest re-evaluation, #119). The score comes from `score.host_score()`: passed ÷ (passed + failed), `None` when that is 0, with errors and not-run beside it (#120).
  - Nothing is re-derived or stored.
- **State:** `ScanRow.state` is `scan.state` as stored, never re-derived (M9 interface note; CHK-M11-333).
- **Deleted policies:** a scan of a deleted policy is returned. Policies are soft-deleted, and the repository joins `policy` without a `deleted_at` filter.
- The service writes nothing and logs nothing.

## Notes

- **Dependency outside TASK-234.** `scan_detail` takes its snapshot through TASK-235's `result_reads.read_only_snapshot(conn)`. `scan_reads` (committed) has no such function, and a service cannot run SQL itself. That function is a one-line `SET TRANSACTION`. If TASK-235's TEST or REVIEW renames it, this call changes with it.
- **Consistency guard.** Every agent with an original job has a `host_counts` row in the same snapshot (M8 `_COUNTS` keeps an agent even with an empty payload). A missing one would be a `KeyError`, not a silent zero.
- No PostgreSQL run by me (WSL is the tester's).

## Commands run

`PYTHONPATH` and `MYPYPATH` point at this worktree's `manager/`. I used the `Bitscan-m9/manager/.venv` tools; see TASK-232 for why.

| Command | Result |
| --- | --- |
| `ruff check` / `ruff format --check` on the file | clean |
| `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` | Success, 188 files |

Files outside the task list: none. `manager/pyproject.toml` shows as modified in the working tree, but not by me.
