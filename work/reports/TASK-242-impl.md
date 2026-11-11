# TASK-242 IMPL: retention service `run_retention()`

Implementer: impl-manager-b, 2026-11-08. REQ-274, REQ-275, REQ-276, REQ-278. Spec: TS §5.3 L1049 (what goes and when), L1051 (`bitscan_retention` deletes only retention tables and inserts checkpoints), L1053 (checkpoint before delete; chain lock); TS §5.2 L983–L992, L1002–L1006. Open items: #150 (all parts), #151. Plan: `work/plans/TASK-242.md` §4, as corrected in decisions 2026-11-08 (the `user_token.created_at` probe, and no row lock in `scan_chunk`). It builds on TASK-236 (`5a9ecef`), TASK-237 and TASK-238 (TEST PASS, REVIEW APPROVED), all unchanged. High risk (the user's second look, PD-47).

## Files

`manager/bitscan_manager/services/retention/task.py` (new, about 255 lines including docstrings, about 175 of code). No other file changed. Nothing is wired yet: TASK-245 adds the scheduler job and the pool.

## Interface (plan §4)

```python
@dataclass(frozen=True) class StepResult: step: str; deleted: int; chunks: int; skipped: str | None
def run_retention(db: Database, now: datetime, *, shipped_through: Callable[[], int | None],
                  wake: Callable[[], None] | None = None) -> list[StepResult]
```

- **Constants:** `STEPS` = `scans`, `inventory_jobs`, `snapshots`, `requests`, `tokens`, `audit`, `packages`, in that order.
- **`skipped`:** None, `CLOCK_DOUBT`, `FUTURE_ROWS` or `FAILED`.
- **`deleted`:** counts scans (not their jobs) for `scans`, and rows for the other steps.
- **`chunks`:** counts the committed transactions that deleted at least one row.

## The run

1. **Cutoffs.** `rules.cutoffs(now)` raises `ValueError` on a naive `now`, before any database work.
2. **Clock check.** One transaction runs `db_now()`.
   - If `clock_doubt`: one `log.warning("retention refused: clock_doubt")`, and every step is returned with `skipped="clock_doubt"`. Nothing is deleted.
   - If the check itself raises (database down, scheduler stopping): it propagates, so nothing is deleted. The runner's `_guarded` logs it (TASK-245).
3. **Probe-and-skip steps.** `scans`, `inventory_jobs`, `snapshots`, `requests` and `tokens` each first run one probe transaction: `newest()` on `scan`, `scan_job`, `inventory_snapshot`, `enrollment_request` and `user_token` respectively. If `future_rows(newest, now)`, the step is skipped (`future_rows`), and the other steps still run.
4. **scans.** Chunks of up to `SCAN_CHUNK` (100) scans.
   - Each chunk is one transaction: `scan_chunk`, then `try_reeval_lock` per scan, then one `delete_scans` for the ids whose lock was taken.
   - **Design choice (the TASK-237 review note and the lead's design point).**
     - The problem: `scan_chunk` returns the oldest scans and takes no row lock, so a scan skipped for its lock would head every later chunk.
     - The fix: the skipped ids are carried through the run in a set. Each chunk asks `scan_chunk` for `SCAN_CHUNK + len(skipped)` rows and drops the skipped ids, so it always brings up to 100 scans not yet tried.
     - The loop ends when a chunk brings no scan not yet tried, or when `scan_chunk` returned fewer rows than asked (nothing more past the cutoff).
     - Every chunk either deletes or skips each fresh scan, so the loop always ends. It never spins, and scans behind skipped ones are reached in the same run.
     - Skipped scans are not tried again in this run; the next run deletes them.
     - No repository signature changed: `scan_chunk(conn, cutoff, n)` is called with a larger `n`.
5. **inventory_jobs, snapshots, requests, tokens.** Each runs the repository delete, one transaction per chunk, until a chunk deletes fewer than its size: `JOB_CHUNK` 1,000 for inventory jobs and `ROW_CHUNK` 10,000 for the others.
6. **audit.** One transaction per chunk, in this order:
   1. `PgAuditRepo.lock_chain()`, so the decision is made under the chain lock (builder checklist 9);
   2. `retention_audit.oldest(AUDIT_CHUNK)`, then `rules.audit_prefix(rows, cut.audit, shipped_through(), AUDIT_CHUNK)`; on None the step stops;
   3. `append_entry(PgAuditRepo(conn), actor="system", action="audit.checkpoint", target=None, detail={"last_deleted_id", "last_deleted_row_hash": row_hash(last), "deleted": count})`;
   4. `delete_through(last)`;
   5. if the count deleted differs from the count walked, `RuntimeError` rolls back both;
   6. `tx.on_commit(wake)`, then commit.

   Notes on this step:
   - The checkpoint is always written before the delete, in the same transaction.
   - Only a prefix goes (the rules stop at the first entry that isn't older).
   - The prefix is never past `shipped_through()`, and nothing goes while that is None.
   - `append_entry` takes the same advisory lock again; PostgreSQL advisory locks are re-entrant within a session.
   - The checkpoints are newer than the entries they record. So in a later chunk the walk stops at the first checkpoint, and three chunks of 25,000 expired entries give three checkpoints (traced below).
7. **packages.** `delete_packages(ROW_CHUNK)` chunks until a chunk comes back short.

**Failure handling.** A step that raises is caught (`except Exception`) and logged with `log.error("retention step failed", data={step, exc_type})`. Its result is `skipped="failed"`, with the counts committed before the fault, and the next step runs.

**Logs.** Every step, including skipped and failed ones, ends with `log.info("retention step done", data={step, deleted, chunks, skipped})`. No ids, row content, hashes or tokens are logged.

## Behaviour the tester should know

- **Stop (REQ-277 (2)).** Every transaction goes through `db`. With TASK-245's `_StoppableDatabase`, the next transaction after `stop()` raises `SchedulerStopping`.
  - The current step logs it as failed, and each later step then fails at once at its first transaction. That gives one "retention step failed" line per remaining step, with `exc_type` `SchedulerStopping`.
  - This is the M9 sweep's behaviour (`run_sweep`); `services/scheduler` isn't imported here, which avoids an import cycle once the runner imports this module.
- **Per-chunk isolation (checklist 20).** A chunk that fails, for example a package prune losing the #150 (f) race to an upload, rolls back alone. Earlier chunks stay committed, and the next run retries.
  - No per-row content is read, so no single row can fail a chunk on every run. The one possible FK, `retry_of`, stays within a scan and is deleted in the same statement.
- **Audit trace with 25,000 expired entries, all shipped:**
  - chunk 1 deletes ids 1–10,000 and writes cp1;
  - chunk 2 deletes 10,001–20,000 and writes cp2;
  - chunk 3 walks 20,001–25,000, stops at cp1 (recent), deletes them and writes cp3, which records 25,000 and its hash;
  - chunk 4 sees cp1 first and stops.

  The oldest remaining entry, cp1, has `prev_hash` = `row_hash(25,000)` = cp3's `last_deleted_row_hash`, and cp3 is written after it. M1's verifier accepts that link.
- **Clock check.** It uses the manager's `now` against `SELECT now()`: 5 min exactly runs, 5 min 1 s refuses (TASK-236).
- **No audit entry other than checkpoints.** The checkpoint `target` is None (checklist 16 doesn't apply).

## Deviations

- **From plan §4 step 2:**
  - The plan says "stop when a chunk finds nothing to delete". The loop instead stops when a chunk brings no untried scan, with the skipped ids carried forward (the lead's design point and the TASK-237 review). With that design a chunk that deletes nothing is still never re-selected.
  - No `FOR UPDATE SKIP LOCKED`, as decided on 2026-11-08 for TASK-237.
- **From plan §4 step 7:** the chain lock is taken before `oldest()` rather than only inside `append_entry`. The plan's order of checkpoint, then delete, in one transaction, is unchanged; the decision is simply made under the lock.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check manager && ruff format --check manager`: all checks passed (411 files).
- `mypy --strict manager/bitscan_manager/services/retention`: no issues in 3 files. `mypy --strict manager`: the same 12 errors as on main, none in M11 files (the stale venv lacks `python_multipart`).
- The PostgreSQL tests with clock control are the tester's: `manager/tests/test_retention_pg.py` and `test_retention_race_pg.py` (TP-M11-10).

## Builder checklist

| Item | How it is met |
| --- | --- |
| 7 | wake runs on commit only |
| 8 and 9 | the audit decision is made under the chain lock; scans are decided under the advisory lock tried in the deleting transaction |
| 10 | every loop opens its transactions through `db` (stop) |
| 11 and 12 | logs carry counts, step names and exception types only, and the error texts are fixed |
| 16 | doesn't apply: the checkpoint target is None |
| 20 | one transaction per chunk |
| 1–6, 13–15, 17–19, 21, 22 | don't apply |
