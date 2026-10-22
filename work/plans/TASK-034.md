# TASK-034 plan: audit sink (transports, disk queue, shipper, outage gate)

Covers TASK-032 (transports), TASK-033 (disk queue) and TASK-034 (shipper and gate). REQs: REQ-053, REQ-054, REQ-055 (the outage alert). Owner: impl-manager. Not on the TS §8.2 two-approval list; a second look by the lead is recommended (the sink is the only control against a full rewrite of the chain, `work/m2-brief.md`). Tests: TP-M2-10, TP-M2-11, TP-M2-12 (gate G26).

Files:
- TASK-032: `bm/services/audit/sink_transport.py`.
- TASK-033: `bm/services/audit/disk_queue.py`.
- TASK-034: `bm/services/audit/shipper.py`, `bm/repositories/audit_log.py` (adds `entries_after`).

**Blocked on:** #24 (wire format, sink authentication) for TASK-032; #51 (delivery model) for TASK-034. The design below is the #51 recommended default.

## Spec quotes

- TS §5.3 L1051: "Entries are also streamed to an external log store as they are written (`BITSCAN_AUDIT_SINK`, §8.6), so a database superuser or a restore cannot quietly rewrite history. If the sink is unreachable, entries queue on disk (`/var/lib/bitscan/audit-queue`), an alert fires at once, and sensitive actions (§6.2) are refused after 15 minutes of outage until the queue drains."
- TS §8.6 L1315: "`BITSCAN_AUDIT_SINK` | — | yes | Syslog or HTTPS endpoint that receives every audit entry".
- TS §8.7 L1344: "`/var/lib/bitscan/audit-queue/` (`bitscan-manager`, 0700)"; L1377: `ReadWritePaths=… /var/lib/bitscan/audit-queue`.
- TS §8.4 L1289: "every alert is written as an audit entry with `detail.alert = true`, so it reaches `BITSCAN_AUDIT_SINK`"; L1290: "audit sink unreachable" is an immediate alert.
- TS §8.1 L1256: "Audit sink outage | Entries queue on disk, an alert fires at once, and sensitive actions are refused after 15 minutes of outage (§5.3)".

## Why ship from committed rows (#51 default)

Sending from inside `append_entry()` would send entries whose transaction later rolls back (REQ-053 (2)) and would miss entries written by other processes: the server CLI (TS §8.7 L1347) and, in M11, the retention task. So `serve` runs one shipper that reads **committed** rows in `audit_id` order. Each process's appends call `SinkGate.wake()` from an on-commit hook (TASK-025), so in-process entries leave at once; a 1 s poll catches the others. Delivery is at least once; a crash can resend, and every record carries `audit_id` and `row_hash`, so the store can drop duplicates.

`audit_id` comes from a sequence and is allocated under the chain lock, but commit order can still differ from id order only if two transactions hold ids at once, which the advisory lock prevents for appends (the lock is held until commit). So reading `audit_id > cursor` in order never skips a later-committed lower id. A rolled-back append leaves a gap in the ids, which is harmless (M1 REQ-031 (4)).

## TASK-032: transports

```python
@dataclass(frozen=True)
class SinkRecord:                 # every audit_log column (REQ-053 (3))
    audit_id: int
    actor: str
    action: str
    target: str | None
    detail_text: str | None       # PostgreSQL detail::text, as hashed (#38)
    at_text: str                  # as hashed (#38)
    prev_hash: str
    row_hash: str

class DeliveryError(Exception): ...           # message never holds record content or credentials

class SinkTransport(Protocol):
    def send(self, records: Sequence[SinkRecord]) -> None: ...   # all or raise DeliveryError
    def close(self) -> None: ...

def transport_from_url(value: str, *, timeout_s: float = 5.0) -> SinkTransport: ...   # raises ConfigError for plain transports
```

#24 default: `syslog+tls://host:port` sends one RFC 5424 message per record (`APP-NAME` `bitscan-manager`, `MSGID` = `action`, structured data empty, `MSG` = the compact JSON of the record), octet-counted framing (RFC 5425), TLS 1.2+ with the system CA store and host-name check. `https://…` sends `POST` with a JSON array of records and expects 2xx. `udp://`, `tcp://`, `syslog://` without TLS and `http://` raise at start-up (REQ-053 (4)). No credential (TS §8.7 loads none; #24).

## TASK-033: disk queue

```python
class DiskQueue:
    def __init__(self, folder: Path) -> None: ...   # creates it 0700 if missing; refuses a folder others can write
    def append(self, records: Sequence[SinkRecord]) -> None: ...   # one line per record, fsync file and folder
    def peek(self, max_records: int) -> list[SinkRecord]: ...      # oldest first
    def ack(self, upto_audit_id: int) -> None: ...                 # drop records up to that id
    def depth(self) -> int: ...
    def last_queued_id(self) -> int | None: ...
    # small state file next to the records (written atomically: temp file, fsync, rename)
    def load_state(self) -> QueueState: ...
    def save_state(self, state: QueueState) -> None: ...

@dataclass(frozen=True)
class QueueState:
    cursor: int                     # highest audit_id read from the database into the queue
    outage_since: datetime | None   # first failed delivery of the current outage (#51 (c))
    alerted: bool                   # the outage alert has been written
```

Format: append-only segment files of JSON lines, each line `{"crc": <crc32 of the record JSON>, "record": {...}}`; a new segment every 10,000 records; a segment is deleted once fully acknowledged. Reading stops at the first line that is not complete JSON or whose CRC does not match, and that tail is truncated on the next append (REQ-054 (6)). Files are created 0600 (`os.open` with mode, `umask` 0077 in the unit too).

## TASK-034: shipper and gate

```python
class AuditTail(Protocol):                          # repositories/audit_log.py implements it
    def entries_after(self, audit_id: int, limit: int) -> list[SinkRecord]: ...   # committed only, ORDER BY audit_id

class Shipper:                                       # implements SinkGate (TASK-025)
    def __init__(self, tail: AuditTail, queue: DiskQueue, transport: SinkTransport,
                 clock: Clock, raise_outage_alert: Callable[[], None],
                 outage_limit: timedelta = timedelta(minutes=15)) -> None: ...
    def run_once(self) -> None: ...                  # one cycle; unit tests drive this directly
    def start(self) -> None: ...                     # background thread, run_once every 1 s or on wake()
    def stop(self, timeout_s: float = 5.0) -> None: ...
    def wake(self) -> None: ...
    def refusing(self) -> bool: ...
```

`run_once`:
1. Read: `entries_after(state.cursor, 500)`; `queue.append(...)`; `state.cursor = last id`; save state. (Records are on disk before any send, so a crash after this loses nothing.)
2. Send: `queue.peek(500)` → `transport.send(...)`.
   - Success: `queue.ack(last id)`. If `queue.depth() == 0` and the cursor equals the newest committed id: the outage (if any) ends: `outage_since = None`, `alerted = False`, and write an `audit.sink_recovered` entry (#50 default; not an alert).
   - `DeliveryError`: if `outage_since is None`, set it to `clock.now()`; if not `alerted`, call `raise_outage_alert()` (an `audit.sink_unreachable` entry with `detail.alert = true`, kind `audit_sink_unreachable`, REQ-055), set `alerted = True`. Save state. Back off: next attempt after 1, 2, 4 … 30 s (the 1 s read loop keeps queueing meanwhile).
3. `refusing()` = `outage_since is not None and clock.now() - outage_since >= 15 min`. Because `outage_since` is cleared only when the queue is empty and the cursor has caught up, "until the queue drains" holds (REQ-054 (3)). It is read from the saved state at start, so a restart does not reset it (REQ-054 (5)).

The outage alert is itself an audit entry, so it is queued behind the failed records and reaches the sink when the sink is back. During the outage the operator sees it through `bitscan_alerts_total{kind="audit_sink_unreachable"}` and the JSON log line the alert path writes.

## Edge cases

- Database down while the sink is up: step 1 fails; log once, retry; queued records keep being sent. Not an outage.
- Both down: the state file still holds `outage_since`; the gate keeps refusing.
- Disk full or the queue folder unwritable: `append` raises; treat as an outage (set `outage_since`, alert once). The spec gives no other rule; record it in the TASK-034 report.
- Sink slow: `send` has a timeout (5 s); a timeout is a `DeliveryError`.
- `stop()` on `SIGTERM` finishes the current cycle and leaves the queue intact (REQ-057 (6)).
- Nothing here logs record content: log lines carry counts and `audit_id` ranges only.
- `entries_after` runs as `bitscan_app` (SELECT only) through the TASK-025 pool, in a short READ COMMITTED transaction.
