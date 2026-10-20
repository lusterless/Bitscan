# TASK-019 plan: `bitscan-manager db maintain`

REQ: REQ-028. Owner: impl-manager. Depends on: TASK-018. Files: `manager/bitscan_manager/db/maintain.py`, `manager/bitscan_manager/cli/__init__.py`. Tests: TP-M1-13, plus the new-partition grant probe in TP-M1-10. Open questions: #43 (names, time zone), #44 (drop rule, default-partition rows).

## Spec quotes

- TS §5.3 L1047: "`scan_result` is partitioned by month on `job_created_at`: `bitscan-manager db maintain` (a daily timer, as `bitscan_migrate` with `SET ROLE bitscan_owner`, so new partitions are owned by `bitscan_owner` and get the default grants) keeps three future months of partitions and drops whole partitions past retention. The default partition must stay empty; rows in it alert."
- TS §5.3 L1047: "whole scans are deleted together (`scan`, `scan_job`, `scan_result`, `scan_result_reeval`) after 400 days".
- TS §8.7 L1437–L1480: the maintain service and the daily timer (`OnCalendar=daily`, `Persistent=true`, `RandomizedDelaySec=1h`). Only `BITSCAN_MIGRATE_DSN_FILE` is set.
- TS §8.3 L1278: integration tests cover "partition maintenance" and grant probes on "a newly created partition".

## What is in M1 and what is not

- In: creating missing monthly partitions for the current month and the next three, and dropping whole partitions past retention (both are `db maintain`, as stated in L1047).
- Not in: row deletes of any kind (the retention task, run as `bitscan_retention`, is M11), and writing the default-partition alert. Alerts need the M2 sink, and who checks is open (#44). In M1, `db maintain` only refuses to create a partition whose range has rows in the default partition (REQ-028 (6)), which PostgreSQL forces anyway.

## Interface

```python
# bitscan_manager/db/maintain.py
from dataclasses import dataclass
from datetime import datetime
from pydantic import SecretStr

@dataclass(frozen=True)
class MonthRange:
    name: str
    lower: datetime   # inclusive, tz-aware UTC (#43)
    upper: datetime   # exclusive

@dataclass(frozen=True)
class MaintainPlan:
    create: tuple[MonthRange, ...]
    drop: tuple[str, ...]

def plan_partitions(now: datetime, existing: list[MonthRange]) -> MaintainPlan: ...   # pure
def run_maintain(dsn: SecretStr, now: datetime | None = None) -> MaintainPlan: ...
```

`plan_partitions` is pure and unit-tested without PostgreSQL. `run_maintain` reads the existing partitions, calls the planner and applies the plan in one transaction. The CLI `db maintain` calls `load_db_config(os.environ)` and `run_maintain(cfg.migrate_dsn)`, prints one line per partition created or dropped, and uses the same exit codes and lazy imports as `db migrate` (TASK-013 plan).

## Approach

1. Connect with psycopg (no SQLAlchemy needed), run `SET ROLE bitscan_owner`, check `current_user`, commit (same reasons as TASK-013 step 3). Then `SET TIME ZONE 'UTC'` for the session (#43, suggested).
2. Read the existing partitions from the catalog by **bounds**, not by name: `pg_inherits` joined to `pg_class`, with `pg_get_expr(relpartbound, oid)` and `relispartition`. Skip the `DEFAULT` partition. With the session time zone at UTC, the bounds render as UTC text, and the code parses them into `MonthRange`. A partition whose bounds are not exactly one calendar month is reported, and the run exits non-zero without changing anything (someone made it by hand).
3. Plan:
   - create every month from `month_start(now)` up to `month_start(now) + 3 months` that no existing range covers;
   - drop every non-default partition past retention under #44. The suggested rule: `upper <= now - 400 days`.
4. Apply in one transaction. Compose the DDL only with `psycopg.sql`: `sql.SQL("CREATE TABLE {} PARTITION OF scan_result FOR VALUES FROM ({}) TO ({})").format(sql.Identifier(name), sql.Literal(lower), sql.Literal(upper))` and `sql.SQL("DROP TABLE {}").format(sql.Identifier(name))`. No f-strings or `%` (G1, S608).
5. Print `created <name>` or `dropped <name>` per action, or `nothing to do`. Exit 0.

## Edge cases

- **Rows in the default partition** in the range of a new partition: `CREATE TABLE … PARTITION OF` fails ("updated partition constraint for default partition would be violated"). Catch that SQLSTATE (23514), roll back, print a message that names `scan_result_default`, and exit 1. REQ-028 (6).
- **Gaps:** if the database has a hole (for example months 1 and 3 but not 2), the planner fills it if the month is in the current-plus-three window. Months before the window are not created.
- **Clock injection:** `now` is a parameter, so tests can move it forward 2 months (creates 2) and back (creates nothing; never drops future partitions). The CLI always uses `datetime.now(UTC)`.
- **Concurrency:** the timer and a manual run at once. Both try the same `CREATE`, and one fails on the duplicate name or overlap. That run exits 1, with nothing half-done because of the one transaction. PostgreSQL forbids overlapping partitions, so the table can never end up with an overlap.
- **Drop and FKs:** `scan_result` references `scan_job` and `plugin`, and nothing references `scan_result`. So dropping a partition violates no FK. It does remove results whose `scan` rows may still exist until the M11 retention task deletes them. That is why #44 asks whether the drop should wait for the row retention.
- **Lock impact:** creating a partition takes an ACCESS EXCLUSIVE lock on the default partition and a lock on the parent. The run is short and daily, and `RandomizedDelaySec=1h` already spreads it.
- **Default ACL:** new partitions get SELECT, INSERT for `bitscan_app` and SELECT for `bitscan_retention` from the `m0005` default privileges, because the creator is `bitscan_owner`. TP-M1-10 probes it.

## Not in this task

Row retention (M11), the default-partition alert (M2 or later, #44), metrics (M2/M3).
