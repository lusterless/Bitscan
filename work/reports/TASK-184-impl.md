# TASK-184 IMPL: host scores service

Implementer: impl-manager-m8b. REQ-199, REQ-197 (3) (the SQL-versus-`effective()` property test runs here). Risk high. Spec: TS §4.5 L602, §4.4 L579, L583, §2.1 L105. Answer applied: #120. Depends on TASK-181 (`score.py`) and TASK-182 (`repositories/results.py`), both built.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/scores.py` (new, 33 lines) | `AgentScore`, `scan_host_scores()` |

No file outside the task's list was changed.

## Interface (frozen for M11 once W3 passes)

```python
@dataclass(frozen=True, slots=True)
class AgentScore:
    agent_id: UUID
    host: HostScore          # score.HostScore: passed, failed, errors, not_run, score

def scan_host_scores(db: Database, scan_id: UUID) -> list[AgentScore]
```

The task row and REQ-199 name only the function. `AgentScore` pairs the agent with the pure `HostScore` rather than copying its five fields.

## Behaviour

- One `db.transaction()` holding one statement, `results.host_counts(tx.conn, scan_id)`, the REQ-198 counts from the effective verdicts. Then `host_score()` per agent, outside the transaction.
- Order and membership: as `host_counts`, that is one entry per agent with an original compliance job in the scan, ordered by `agent_id`. An unknown scan gives `[]`.
- Nothing is stored or cached, so a late result or a re-evaluation changes the next call at once (REQ-199 (2)).
- Nothing is logged. It runs no `SET TRANSACTION`, so a statement spy sees exactly one SELECT (REQ-199 (4)).

## Acceptance points (REQ-199)

1. Expected score per host from the REQ-198 fixture. An all-ERROR host has passed + failed = 0, so its score is None; so does the queued host (all not run).
2. A late result row, then a re-evaluation row, each change the next call: both are read live through the `eff` CTE.
3. Unknown `scan_id`: `host_counts` returns `[]`, so the result is `[]`.
4. Statement spy: one `SELECT` (the `WITH … SELECT` counts statement).
- REQ-197 (3) property test: compare `results.effective_results()` with `score.effective()` over the same rows. `Effective.policy_version` corresponds to `EffectiveRow.reeval_policy_version`; the other shared fields have the same names.

## Mutation plants

None of the M8 table rows targets TASK-184 directly. Rows that turn its tests red through its dependencies: CHK-M8-346 and -347 (score), -348 (latest row), -352 (retry and not run). An extra plant: return `host_score(c.passed, c.failed, 0, 0)` (errors dropped). Expect G64 red (the errors count beside the score).

## Gates (worktree root, worktree's own `manager/.venv`)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 324 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`, and with `--platform linux`: no issues in 324 files.
