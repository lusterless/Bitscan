# TASK-198 IMPL: queue service `queue_scan()` (design note D1)

Implementer: impl-manager-m9. REQ-209, REQ-211, REQ-212, REQ-227. Risk high (lead's second look, PD-39). Spec: TS §2.3 L133, §3.3 L213, §4.4 L555–L560, L566, §4.1 L530, §4.3 L547, L550, §8.4 L1290. Answers applied: #3, #18, #122 (f), #125, #129 (a), (b). Built on TASK-188 (`targets`), TASK-189 (`build`) and TASK-193 (`repositories/scan_queue.py`, impl-manager-m9b).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/queue.py` (new, 146 lines) | refusals, `ScanQueued`, `queue_scan()` |
| `manager/bitscan_manager/services/audit/alerts.py` (+4 lines) | `M9_ALERT_KINDS = frozenset({"all_hosts_scan_api_token"})` joined into `ALERT_KINDS`, so `raise_alert` accepts it and `bitscan_alerts_total{kind="all_hosts_scan_api_token"}` is exported from zero (main's ruling, decisions 2026-10-30 "M9 builder rulings" (1)) |

## Interface

```python
ALERT_KIND = "all_hosts_scan_api_token"
class PolicyNotFound(Exception)      # 404
class PolicyDisabled(Exception)      # 409 "The policy is disabled."
class PolicyDeleted(Exception)       # 409 "The policy is deleted."
class PolicyHasNoPlugins(Exception)  # 409 (#125 (h))
class NoTargetAgents(Exception)      # 422 (#3)
@dataclass(frozen=True, slots=True)
class ScanQueued: scan_id: UUID; state: Literal["queued"]; policy_version: int; jobs: int

def queue_scan(tx: Tx, *, policy_id: int, target: Target,
               trigger: Literal["manual", "scheduled"], schedule_id: int | None,
               requested_by: int | None, actor: str, via_api_token: bool,
               now: datetime) -> ScanQueued
```

**Departure from plan §4:** there is no `settings: SettingsReader` parameter. `queue_scan` reads `read_settings(SettingsRepo(tx.conn)).redaction_patterns` itself, inside the scan's transaction. The route cannot build a `SettingsRepo` without importing a repository, which REQ-221 (5) forbids. `main` has been told.

Also raised: `build.UnstorableText` (500, #125 (g)); `targets.InvalidTarget` is the caller's (it parses the target before calling).

## Order (design note D1), all inside the caller's transaction

1. `lock_policy_queue` (the per-policy advisory transaction lock).
2. `policy_snapshot` (the row `FOR SHARE`, then one statement). It refuses, in this order: no row → `PolicyNotFound`; `deleted` → `PolicyDeleted`; status not `enabled` → `PolicyDisabled`; no active plugin → `PolicyHasNoPlugins`.
3. `read_settings(...).redaction_patterns`, then `build.plugins_and_spec(snapshot.plugins, patterns)`. The unstorable-text check happens here, before any write.
4. `resolve_agents(kind, agents, tags)`. An empty result raises `NoTargetAgents`.
5. `insert_scan` (state `queued`, `target = stored_target(target, resolved)`, `created_at = now`).
6. `insert_jobs`: one `uuid4()` job id per resolved agent, `created_at = now`, `pickup_by = now + 24 h`, `pickup_text = build.pickup_text(now)`, the shared plugins, patterns and eval_spec.
7. `cancel_older_queued`.
8. One audit entry, target `scan:<scan_id>`, detail `{policy_id, policy_version, trigger, schedule_id, target_kind, jobs, cancelled_older}`. `cancelled_older` is a count. When `target.kind == "all" and via_api_token`, it is `TxAudit.alert("all_hosts_scan_api_token", actor, "scan.create", …)`, the alert entry itself (`detail.alert = true`, `alert_kind`, and `bitscan_alerts_total` incremented on commit). Otherwise it is `TxAudit.audit(actor, "scan.create", …)`.

Every refusal raises before step 5, so the caller's rollback leaves `scan`, `scan_job` and `audit_log` unchanged (REQ-211 (2)). `execute` comes only from the snapshot (REQ-212): no argument carries command text. The detail holds no `execute`, expected value or target list. The caller registers `tx.on_commit(runtime.sink_gate.wake)` (route TASK-205, tick TASK-203).

A new scan's jobs are all `queued`, so its derived state is the inserted `queued` (#127 (f)). No extra derivation runs.

## Resolved point

`all_hosts_scan_api_token` was missing from `ALERT_KINDS`; main ruled it goes into `services/audit/alerts.py` under this task (M9 builder rulings (1)). Done: the M7 pattern, 4 lines. Tester: `services/audit/alerts.py` is a file outside the original list; the M2/M3/M7 alert-kind suites that pin `ALERT_KINDS` may need the new kind.

## For the tester (tester-m9b)

- `actor` is the caller's: `user:<id>` for a session or API token, `system` for the schedule tick. `via_api_token` is True only for `bsk_`.
- Callers must not call `queue_scan` with a `Target` whose kind is outside the three; `resolve_agents` raises `ValueError` then.
- REQ-209 (5) (M8 `host_counts` on an M9 scan) and the REQ-211 (4) races go through this function unchanged.

## Plants

- CHK-M9-352: drop the `status != "enabled"` check (a disabled policy is then queued).
- CHK-M9-357: remove the `if not resolved` check (an empty scan is then written, or `insert_jobs` raises).
- CHK-M9-366: `if target.kind == "all"` without `via_api_token`, or the alert branch removed.
- CHK-M9-351: pass `[]` instead of the setting.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`) on `manager/bitscan_manager`: pass. The only mypy and ruff findings are in the testers' in-progress M9 files under `manager/tests/`.
