# TASK-035 IMPL report: alerts and the alert counter

REQ: REQ-055. Spec: TS §8.4 L1289 ("every alert is written as an audit entry with `detail.alert = true` … and is counted in the metric `bitscan_alerts_total{kind}`"), L1290–L1291. #50 as approved: `detail = {"alert": true, "alert_kind": "<kind>", …}` with the M2 kinds listed below, and actors `user:<id>`, `cli:root` or `system`. #5: there is no metrics route in M2.

## Files (3)

- `manager/bitscan_manager/services/audit/metrics.py` (new): `REGISTRY`, its own `CollectorRegistry` rather than prometheus_client's global default, so a later route can serve exactly these metrics. It holds `ALERTS_TOTAL = Counter("bitscan_alerts", …, ["kind"])`, which prometheus_client exposes as `bitscan_alerts_total{kind}`.
- `manager/bitscan_manager/services/audit/alerts.py` (new): `ALERT_KINDS` and `raise_alert()`.
- `manager/bitscan_manager/services/audit/__init__.py`: also exports `ALERT_KINDS`, `ALERTS_TOTAL`, `REGISTRY` and `raise_alert`.

## API

```python
ALERT_KINDS = {api_token_created, totp_enrolled, totp_replaced, totp_reset, user_created,
               role_granted, admin_created, audit_sink_unreachable, login_failures,
               token_check_failures}

def raise_alert(repo: AuditRepo, on_commit: Callable[[Callable[[], None]], None], *,
                kind: str, actor: str, action: str, target: str | None = None,
                detail: Mapping[str, object] | None = None) -> AppendedEntry
```

- `repo` is the M1 `AuditRepo`; production passes `PgAuditRepo(tx.conn)`. `on_commit` is the transaction's hook registrar (`tx.on_commit`, TASK-025). Taking both through protocols keeps `services/` free of psycopg, so unit tests need no database.
- `raise_alert` writes exactly one audit entry through `append_entry` in the caller's transaction. Its `detail` is `{"alert": true, "alert_kind": kind, **detail}`. It then registers `ALERTS_TOTAL.labels(kind).inc` as an on-commit hook. A rollback therefore leaves neither the entry nor a count change, because `AppDatabase` runs hooks only after COMMIT.
- Refusals (`ValueError`, before anything is written): an unknown `kind`, or a caller `detail` that tries to set `alert` or `alert_kind`.
- Every kind is pre-registered at zero, so the counter shows all ten labels from start-up.
- The `action` is the caller's #50 action, for example `api_token.create`. `raise_alert` does not choose it, because one kind can follow different actions; for example, `admin_created` may follow `user.role_change`.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 80 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 782 passed, 229 skipped (pg), 96.11 %. `alerts.py` is at 50 % until TP-M2-13 lands |
| Scratch, with a fake `AuditRepo` and a list as `on_commit` | one row whose detail text is `{"alert": true, "alert_kind": "api_token_created", "token_id": 5}`. The counter read 0.0 before the hook ran and 1.0 after. A second alert whose hooks were dropped (a rollback) left its counter at 0.0. An unknown kind and `detail={"alert": False}` were refused, and no row was written for either |

## For the tester (TP-M2-13)

- Read the counter with `REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": k})`.
- The registry is module-global, so measure the change (before vs after) rather than absolute values.
