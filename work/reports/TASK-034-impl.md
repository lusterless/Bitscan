# TASK-034 IMPL report: audit shipper and outage gate

REQ: REQ-053, REQ-054. Spec: TS §5.3 L1051, TS §8.1 L1256, TS §8.4 L1289–L1290; #51 (delivery model, as recommended and approved); #50 (`audit.sink_unreachable` with kind `audit_sink_unreachable`, `audit.sink_recovered`, actor `system`). Plan: `work/plans/TASK-034.md`. Lead rulings 2026-10-21:
- the TASK-033 `fchmod(0o600)` hardening is folded in here, and the tester re-tests it (CHK-M2-133);
- each delivery attempt is bounded by the shipper's own deadline (the condition on the TASK-032 per-address connect bound);
- the alert counter hook runs after the alert's own commit.

A second look is recommended.

## Files (3)

- `manager/bitscan_manager/services/audit/shipper.py`: new, 196 non-blank lines with docstrings.
- `manager/bitscan_manager/repositories/audit_log.py`: adds `entries_after(conn, audit_id, limit) -> list[ChainRow]`, which reads committed rows with `audit_id > cursor` in id order, in the hashed text form (`detail::text` and the #38 `at` text). It is a parameterised, composed statement.
- `manager/bitscan_manager/services/audit/disk_queue.py`: new helper `_owner_only(fd)`, which calls `os.fchmod(fd, 0o600)` after every `os.open` of a segment file and of the `.state.json.tmp` / `.acked.json.tmp` temp files, on non-Windows platforms. The `0o600` mode of `os.open` only applies when the call creates the file, so a leftover 0644 file kept its mode before this fix.

## Interface

```python
class AuditTail(Protocol):   entries_after(audit_id, limit) -> list[SinkRecord]
class OutageAudit(Protocol): unreachable() -> None;  recovered() -> None
class PgAuditTail(db: Database)      # one short READ COMMITTED transaction per read
class DbOutageAudit(db: Database)    # each entry in its own transaction
class Shipper:                       # implements runtime.SinkGate
    def __init__(self, tail, queue: DiskQueue, transport: SinkTransport, clock: Clock,
                 audit: OutageAudit, *, outage_limit=timedelta(minutes=15), monotonic=None)
    def run_once(self) -> None; def start(self) -> None; def stop(self, timeout_s=5.0) -> None
    def wake(self) -> None;     def refusing(self) -> bool
OUTAGE_LIMIT = 15 min; BATCH = 500; POLL_S = 1.0; ATTEMPT_S = 30.0; BACKOFF_MAX_S = 30.0
```

Deviation from the plan: the plan's `raise_outage_alert: Callable[[], None]` became the `OutageAudit` protocol. It also carries the recovery entry, so tests can fake both. `DbOutageAudit` is the production implementation:
- `unreachable()` calls `raise_alert(PgAuditRepo(tx.conn), tx.on_commit, kind="audit_sink_unreachable", actor="system", action="audit.sink_unreachable")`;
- `recovered()` calls `append_entry(..., actor="system", action="audit.sink_recovered")`, which is not an alert.

Each runs inside `db.transaction()`, so the counter hook fires only after that commit.

## `run_once()`

1. **Read.** `tail.entries_after(state.cursor, 500)`.
   - The rows are appended to the disk queue as `SinkRecord.to_wire()` dicts and fsynced, and then the cursor is saved. They are therefore on disk before any send, and a crash between the two steps only re-reads rows, which the queue skips by id.
   - "Caught up" means the read returned fewer than 500 rows.
   - **Database down is not an outage.** The error is logged by type, "caught up" is false, and sending continues.
   - **A disk-queue write failure** (for example disk full) **is treated as an outage**, as the plan's edge case says: the failed-delivery path below runs.
2. **Back-off.** If the last attempt failed, sending waits until `clock.now()` reaches the back-off time: 1, 2, 4, … up to 30 s. Reading continues every cycle.
3. **Send.** `queue.peek(500)` gives a batch, then `transport.send(batch)`, then `queue.ack(last id)`. This repeats until the queue is empty or `ATTEMPT_S` (30 s, monotonic) has passed, so one attempt has an overall time bound. Each `send` call is bounded by the transport's own timeouts.
   - On `DeliveryError`, the first `delivered` records are acknowledged and the rest stay queued. A record leaves the queue only after the sink accepted it, so delivery is at least once: a resent record has the same `audit_id` and `row_hash` (REQ-053 (1)).
4. **Failed attempt.**
   - The first failure of an outage sets `outage_since = clock.now()` and saves it in `state.json`.
   - If the outage has no alert yet, `audit.unreachable()` runs, then `alerted = True` is saved. If writing the alert fails (the database is down too), it is retried on the next failed cycle. That gives exactly one alert per outage, at the first failed delivery that can write it.
5. **Successful attempt.** When the queue is empty and "caught up" holds, any outage ends: `outage_since` is cleared, `alerted` is set to false, both are saved, and then `audit.recovered()` runs. A sink that accepts one batch and then fails again does not end the outage.
6. **`refusing()`** is `outage_since is not None and clock.now() - outage_since >= 15 min`. `outage_since` is loaded from the queue folder in `__init__`, so a restart does not reset the 15-minute clock (REQ-054 (5)).

`start()` runs `run_once` in a daemon thread, every second or as soon as `wake()` is called. That covers CLI and other-process entries by polling and in-process ones at once (#51). A failed cycle is logged by type, and the loop continues. `stop(timeout_s)` lets the current cycle finish, joins the thread, closes the transport and leaves the queue on disk (REQ-057 (6)). The `wake()` hook on in-process audit commits is wired in `serve` (TASK-045).

**Logs** carry counts, id ranges (`sent entries 1 to 5`) and exception type names only, never record content.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 87 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 900 passed, 231 skipped (pg); **gate FAILS at 75.70 %** until TP-M2-12 tests land, because `shipper.py` (136 statements) is at 0 %. `disk_queue.py` is still at 97 %; the new line 79 (`fchmod`) is POSIX-only |
| Scratch script (deleted): fake tail, fake transport and fake audit, a real `DiskQueue` in a temp folder, fake clock | Sink up: ids 1, 2, 5 were sent in order (the gaps did not stall) and `refusing()` was false. Sink down: one `unreachable`, then none over 100 more failed cycles 31 s apart. A new shipper over the same folder was not refusing at 14:59.999 after the first failure and was refusing at 15:00. A sink that took a record and then raised kept `refusing()` true and left the record queued; it was resent once later (1 duplicate). After the sink came back and the queue drained: `refusing()` false and one `recovered`. A later second outage raised a second `unreachable`. Every id arrived, in order |
| PostgreSQL (`PgAuditTail`, `DbOutageAudit`, rolled-back entries, CLI entries within 5 s) and Linux `fchmod` | NOT RUN here (no Docker on Windows); TP-M2-12 in WSL |

## For the tester (TP-M2-12, CHK-M2-133)

- Drive it with `run_once()` and a fake clock. Back-off uses `clock.now()`, so move the clock past it (at most 30 s) between failing cycles. The per-attempt deadline uses `monotonic`, which you can inject.
- `DbOutageAudit(db)` and `PgAuditTail(db)` take a TASK-025 `AppDatabase`.
- `fchmod` runs on every open of a segment file and on every temp-file write. CHK-M2-133 can pre-create stale 0644 files.

## Revision 1 (review CHANGES_REQUESTED, `work/reviews/TASK-034.md` finding 1)

**Cause.** `_send` caught only `DeliveryError`. A `queue.peek()` or `queue.ack()` that raises (for example `OSError` ENOSPC on `acked.json`), or a transport error that is not wrapped (for example `httpx.InvalidURL` or `StreamError`, which are not `HTTPError` subclasses, or any `RuntimeError`), escaped `run_once`. `_loop` only logged it, so `_outage()` never ran: no alert, and `refusing()` stayed false. The gate failed open.

**Fix.**
- `_send()` now wraps the batch loop, which moved to `_send_batches()`. Any `Exception` other than `DeliveryError` is logged by type only, and the attempt is a failure, so `_outage()` runs: one alert, then the 15-minute gate. This includes the partial-delivery `ack` after a `DeliveryError`.
- `_save()` now updates the in-memory state first and then persists it. An `OSError` from `save_state` (disk full or unwritable) is logged by type and does not escape, so a state file that cannot be written cannot stop the alert or the gate either.
  - On a restart after such a failure, the older saved cursor makes the shipper re-read rows, and the queue skips ids it already holds.
  - Other exceptions still propagate, so the tester's crash simulation with `RuntimeError` keeps its meaning.

**Re-checked.**
- ruff and mypy `--strict` pass.
- `pytest tests/test_shipper.py tests/test_disk_queue.py`: 76 passed, 12 skipped (pg).
- Scratch (deleted), 40 cycles 30 s apart with records queued, each of these gave one alert and `refusing()` true at 20 min:
  - a transport raising `RuntimeError`;
  - `queue.ack` raising `OSError(ENOSPC)`;
  - `save_state` raising `OSError` during a `DeliveryError` outage.

**For the tester.** The reviewer asks for two committed tests, an `ack` that raises `OSError` and a transport that raises `RuntimeError`. Each must alert once and reach `refusing()` at 15 min.
