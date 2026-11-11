# TASK-242 plan: the retention task (design note D3)

Covers TASK-236 (rules), TASK-237 and TASK-238 (repositories), TASK-242 (service) and TASK-245 (wiring). Planner-m11, 2026-11-08. Answers used: #39, #44, #150, #151, PD-51. `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §5.3 L1049: "whole scans are deleted together (`scan`, `scan_job`, `scan_result`, `scan_result_reeval`) after 400 days; `inventory_snapshot` after 180 days; decided `enrollment_request` rows and expired `user_token` rows after 90 days; `audit_log` after 3 years. … Inventory jobs are deleted 30 days after they finish, and unreferenced `package` rows daily."
- TS §5.3 L1051: "`bitscan_retention` (the retention task) may read everything, delete only from the tables with a retention rule above, and insert `audit.checkpoint` entries into `audit_log`."
- TS §5.3 L1053: "before deleting expired entries, the retention task writes an `audit.checkpoint` entry recording the id and `row_hash` of the last deleted entry, so the chain can still be verified from that point."
- TS §5.2 L829–L835: `system_schedule` row `('retention', 86400)`; L1003–L1006: the retention grants.
- TS §2.1 L103: the scheduler runs retention; TS §8.6 L1309: `BITSCAN_RETENTION_DSN_FILE`.

## 2. Rules (`bm/services/retention/rules.py`, TASK-236; pure)

```python
SCAN_AGE = timedelta(days=400); SNAPSHOT_AGE = timedelta(days=180)
REQUEST_AGE = TOKEN_AGE = timedelta(days=90); INVENTORY_JOB_AGE = timedelta(days=30)
AUDIT_YEARS = 3; CLOCK_SKEW = timedelta(minutes=5); FUTURE_SLACK = timedelta(days=1)
SCAN_CHUNK = 100; JOB_CHUNK = 1_000; ROW_CHUNK = 10_000; AUDIT_CHUNK = 10_000

@dataclass(frozen=True) class Cutoffs: scans; snapshots; requests; tokens; audit; inventory_jobs
def cutoffs(now: datetime) -> Cutoffs                       # ValueError on a naive datetime
def minus_years(now: datetime, years: int) -> datetime      # Feb 29 → Feb 28
def audit_prefix(rows: Sequence[tuple[int, datetime]], cutoff: datetime,
                 shipped: int | None, limit: int) -> int | None
def clock_doubt(manager_now: datetime, db_now: datetime) -> bool   # > 5 min apart
def future_rows(newest: datetime | None, now: datetime) -> bool    # newest > now + 1 day
```

`audit_prefix` takes the oldest entries in id order (at most `limit`), walks while `at < cutoff`, stops at the first entry that is not older, and returns the last id walked, capped at `shipped`; None when nothing qualifies or `shipped` is None.

## 3. Repositories (TASK-237, TASK-238)

`bm/repositories/retention.py`, every function in the caller's transaction, parameterised:

| Function | Statement (shape) |
| --- | --- |
| `db_now(conn)` | `SELECT now()` |
| `newest(conn, table)` | `SELECT max(<time column>)` for `scan.created_at`, `inventory_snapshot.collected_at`, `enrollment_request.decided_at`, `user_token.expires_at`, `scan_job.finished_at` (inventory); the table and column come from a fixed mapping, composed with `sql.Identifier` |
| `scan_chunk(conn, cutoff, n)` | `SELECT scan_id FROM scan WHERE created_at < %s ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED` |
| `try_reeval_lock(conn, scan_id)` | `SELECT pg_try_advisory_xact_lock(hashtext('scan_reeval'), hashtext(CAST(%s AS text)))` (the M8 key, #150 (k)) |
| `delete_scans(conn, ids)` | `DELETE FROM scan WHERE scan_id = ANY(%s)` (the cascades delete jobs, results in every partition and re-evaluation rows in the same statement) |
| `delete_inventory_jobs(conn, cutoff, n)` | `DELETE FROM scan_job WHERE job_id IN (SELECT job_id FROM scan_job WHERE kind = 'inventory' AND finished_at < %s LIMIT %s)` |
| `delete_snapshots`, `delete_requests`, `delete_tokens` | the same pattern on `collected_at`; `decision IS NOT NULL AND decided_at`; `expires_at` |
| `delete_packages(conn, n)` | `DELETE FROM package WHERE package_id IN (SELECT p.package_id FROM package p WHERE NOT EXISTS (SELECT 1 FROM agent_package ap WHERE ap.package_id = p.package_id) LIMIT %s)` (uses `ix_agent_package_pkg`) |

Each returns its row count. `bm/repositories/retention_audit.py`: `oldest(conn, n) -> list[(audit_id, at)]` (`ORDER BY audit_id LIMIT n`), `row_hash(conn, audit_id) -> str`, `delete_through(conn, audit_id) -> int` (`DELETE FROM audit_log WHERE audit_id <= %s`).

Grants (unchanged, m0005): `bitscan_retention` has SELECT on everything, DELETE on exactly the nine tables, INSERT on `audit_log`, USAGE on its sequence. Every function is also tested as `bitscan_app` to show the grants refuse it.

## 4. Service (`bm/services/retention/task.py`, TASK-242)

```python
@dataclass(frozen=True) class StepResult: step: str; deleted: int; chunks: int; skipped: str | None
def run_retention(db: Database, now: datetime, *, shipped_through: Callable[[], int | None],
                  wake: Callable[[], None] | None = None) -> list[StepResult]
```

Order and transactions:
1. **Clock check** (one read transaction): `db_now()`; if `clock_doubt(now, db_now)`, log `retention refused: clock_doubt` and return with every step skipped.
2. **scans**: `future_rows` check, then repeat: one transaction → `scan_chunk(SCAN_CHUNK)` → keep the ids whose `try_reeval_lock` succeeds → `delete_scans` → commit; stop when a chunk finds nothing to delete. Locked or under-re-evaluation scans are left for the next run.
3. **inventory_jobs**, 4. **snapshots**, 5. **requests**, 6. **tokens**: the future-row check, then chunk loops of one transaction each.
7. **audit**: repeat: one transaction → `oldest(AUDIT_CHUNK)` → `audit_prefix(..., shipped_through(), AUDIT_CHUNK)` → if None stop → `append_entry(PgAuditRepo(conn), actor="system", action="audit.checkpoint", target=None, detail={"last_deleted_id": n, "last_deleted_row_hash": row_hash(n), "deleted": count})` → `delete_through(n)` → `tx.on_commit(wake)` → commit. The checkpoint is written before the delete, in the same transaction; `append_entry` takes the chain lock, so app writers wait for the commit and the chain cannot fork. A chunk's checkpoint is newer than every entry it records, so M1's `verify_rows` accepts the oldest remaining entry through it.
8. **packages**: chunk loop.

A step that raises is logged (`retention step failed`, step, exception type) and the next step runs; nothing else is logged but `retention step done` with step, deleted and chunks. No row content, no ids beyond counts. No audit entry other than checkpoints.

## 5. Wiring (TASK-245)

- `bm/db/pool.py`: `AppDatabase(..., name: str = "bitscan_app")` (the pool name only).
- `bm/cli/serve.py` `build_runtime`: `retention_db = AppDatabase(bounded_dsn(config.retention_dsn), min_size=0, max_size=1, name="bitscan_retention")`; `SchedulerRunner(db, clock, shipper.wake, retention_db=retention_db, shipped_through=shipper.shipped_through)`; the lifecycle opens it with the app pool and closes it after the scheduler stops.
- `bm/services/audit/shipper.py`: `shipped_through() -> int | None`, the saved cursor (the id of the last entry already written to the disk queue, `QueueState.cursor` after `_save`), returned as one attribute read of the immutable saved state; None before the first save. Read-only; nothing else in the shipper changes.
- `bm/services/scheduler/runner.py`: a fourth job `retention`, interval from `SettingsRepo.schedule_interval("retention")` at start-up (86,400 if unreadable), `next_run_time = start + 10 min`, `max_instances=1`, `coalesce=True`; the retention pool wrapped in the same `_StoppableDatabase` (so a stop ends a run at its next transaction); `_guarded("retention", …)`. The docstring's "Retention is not scheduled until M11" goes.

## 6. Edge cases the tests must hit

- Each cutoff exactly at the boundary kept, 1 µs older deleted (REQ-274 (1)).
- A scan whose results are already gone with a dropped partition (`db maintain`, #44): the scan row and jobs still deleted.
- A scan with an original and a retry (self-reference): one statement deletes both.
- A pending request with `decided_at` NULL; a token revoked yesterday but expiring next year: kept.
- Audit: an entry with an old `at` after a recent one (clock step) stops the prefix; 25,000 expired entries → three chunks and three checkpoints; `verify_chain()` OK after each; an expired entry above the shipped cursor kept; a fault between the checkpoint and the delete rolls both back.
- Two app sessions appending audit entries during the audit step (barrier): no fork.
- A re-evaluation of an old scan in progress (another session holds the scan lock): that scan skipped, deleted next run; a re-evaluation started after the delete gets 404.
- The manager clock 1 h ahead of the database: nothing deleted; a scan dated 2 days ahead: the scans step skipped only.
- An inventory upload racing the package prune (barrier): the upload fails once, the retried upload stores the package (#150 (f)).
- Scheduler stop during a long scans step: the run ends at its next transaction; `stop()` returns.
- #151: the gate records the time per 1,000 inventory-job deletes and per 100 scans on a table of realistic size, for the owner.
