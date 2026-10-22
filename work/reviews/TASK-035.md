# TASK-035 REVIEW: alerts and the alert counter

Reviewer: reviewer. Date: 2026-10-21. REQ-055. Spec: TS §8.4 L1289 (an alert is an audit entry with `detail.alert = true`, counted in `bitscan_alerts_total{kind}`), L1290–L1291; #50 (c); #5 (no metrics route in M2). Inputs: `work/reports/TASK-035-impl.md`; `work/reports/TASK-035-test.md` (PASS, CHK-M2-135 to -138, 27 tests, 8 of 8 mutations red; a fresh-process test catches the pre-seeding mutant).

Files reviewed:
- `manager/bitscan_manager/services/audit/alerts.py`;
- `manager/bitscan_manager/services/audit/metrics.py`;
- `manager/bitscan_manager/services/audit/__init__.py`.

Verdict: APPROVED

TASK-035 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **One entry per alert (REQ-055 (1)).** `raise_alert` writes exactly one entry through the M1 `append_entry`, in the caller's transaction, with `detail = {"alert": true, "alert_kind": kind, …}` (#50 (c)). An unknown kind, or caller detail that sets `alert` or `alert_kind`, is refused before anything is written. The ten kinds match #50 (c).
- **Counter on commit only (REQ-055 (2)).** The increment is registered through `on_commit`. With `AppDatabase.transaction()` (TASK-025), hooks run only after COMMIT, so a rollback leaves neither the entry nor a count.
- **Registry (REQ-055 (3)).** It is a dedicated `CollectorRegistry`, not prometheus_client's global one, so a later route serves only Bitscan metrics. `Counter("bitscan_alerts", …)` is exposed as `bitscan_alerts_total{kind}`. Every kind is pre-registered at zero. No route is added (#5).
- **Layering.** `services/` takes the repository and the hook registrar through protocols and imports no psycopg. Coverage of `alerts.py` and `metrics.py` is 100 %.
- **Gates (my run).** ruff, format and `mypy --strict` are clean. `test_alerts.py` passes, and G5 is at 97.84 %.
- **Scope.** 3 files, about 75 lines.

## Findings

None block approval.

1. **note for TASK-046 (CLI) and TASK-034 (shipper).** The counter rises only if the caller's `on_commit` actually runs after its commit. The CLI writes on its own connection (TASK-046), and the shipper raises the outage alert itself (TASK-034). Each must pass a registrar whose hooks run after its own commit, or use `AppDatabase.transaction()`. Note also that a CLI process's counter lives in that process: a `users create-api-token` alert is counted only in the CLI process, never in `serve`'s registry. The audit entry still reaches the sink, which is what TS §8.4 relies on. That is a metrics gap to record in TASK-046, not a defect here.
2. **nit.** The tests share the module-global registry and measure deltas, which is correct. If tests ever run in parallel threads, deltas could interleave. That is not a concern with the current serial runner.
