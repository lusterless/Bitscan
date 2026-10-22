"""Audit sink shipper and outage gate (TS §5.3 L1051, §8.1 L1256; #51).

serve runs one Shipper. Each cycle reads committed audit_log rows after the
cursor, queues them on disk (so a crash loses nothing), then sends the queue
and acknowledges only what the sink accepted. While delivery fails the outage
start is kept in the queue folder (it survives restarts), one alert is
raised, and refusing() is true from 15 minutes of outage until the queue has
drained and the cursor has caught up. Logs carry counts and ids only.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import Final, Protocol

from bitscan_manager.repositories.audit_log import PgAuditRepo, entries_after
from bitscan_manager.runtime import Clock, Database
from bitscan_manager.services.audit.alerts import raise_alert
from bitscan_manager.services.audit.chain import append_entry
from bitscan_manager.services.audit.disk_queue import DiskQueue, QueueState
from bitscan_manager.services.audit.sink_transport import (
    DeliveryError,
    SinkRecord,
    SinkTransport,
)

log = logging.getLogger(__name__)

OUTAGE_LIMIT: Final = timedelta(minutes=15)
BATCH: Final = 500
POLL_S: Final = 1.0
ATTEMPT_S: Final = 30.0  # one delivery attempt sends batches for at most this long
BACKOFF_MAX_S: Final = 30.0


class AuditTail(Protocol):
    def entries_after(self, audit_id: int, limit: int) -> list[SinkRecord]: ...


class OutageAudit(Protocol):
    def unreachable(self) -> None: ...  # the audit_sink_unreachable alert

    def recovered(self) -> None: ...  # an audit.sink_recovered entry, no alert


class PgAuditTail:
    """AuditTail over the app pool: one short READ COMMITTED transaction."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def entries_after(self, audit_id: int, limit: int) -> list[SinkRecord]:
        with self._db.transaction() as tx:
            return [SinkRecord(*row) for row in entries_after(tx.conn, audit_id, limit)]


class DbOutageAudit:
    """Writes the outage entries in their own transactions; the alert counter
    hook runs after that commit (Database.transaction)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def unreachable(self) -> None:
        with self._db.transaction() as tx:
            raise_alert(
                PgAuditRepo(tx.conn),
                tx.on_commit,
                kind="audit_sink_unreachable",
                actor="system",
                action="audit.sink_unreachable",
            )

    def recovered(self) -> None:
        with self._db.transaction() as tx:
            append_entry(
                PgAuditRepo(tx.conn), actor="system", action="audit.sink_recovered"
            )


class Shipper:
    """Implements runtime.SinkGate."""

    def __init__(
        self,
        tail: AuditTail,
        queue: DiskQueue,
        transport: SinkTransport,
        clock: Clock,
        audit: OutageAudit,
        *,
        outage_limit: timedelta = OUTAGE_LIMIT,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._tail, self._queue, self._transport = tail, queue, transport
        self._clock, self._audit, self._limit = clock, audit, outage_limit
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.Lock()
        self._state = queue.load_state()  # outage_since survives a restart
        self._caught_up = False
        self._failures = 0
        self._next_send = clock.now()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refusing(self) -> bool:
        with self._lock:
            since = self._state.outage_since
        return since is not None and self._clock.now() - since >= self._limit

    def wake(self) -> None:
        self._wake.set()

    def _save(self, new: QueueState) -> None:
        # Memory first, so the gate holds even when the disk refuses the write;
        # a restart then re-reads from the older saved cursor (the queue skips
        # ids it already holds).
        with self._lock:
            self._state = new
        try:
            self._queue.save_state(new)
        except OSError as exc:  # disk full or unwritable
            log.error("audit shipper: state not saved (%s)", type(exc).__name__)

    def _read(self) -> bool:
        """Queue new committed rows; False if the disk queue failed."""
        try:
            rows = self._tail.entries_after(self._state.cursor, BATCH)
        except Exception as exc:  # database down: not a sink outage
            log.warning("audit shipper: cannot read audit_log (%s)", type(exc).__name__)
            self._caught_up = False
            return True
        if rows:
            try:
                self._queue.append([r.to_wire() for r in rows])
            except Exception as exc:
                log.error(
                    "audit shipper: cannot queue entries (%s)", type(exc).__name__
                )
                self._caught_up = False
                return False
            self._save(replace(self._state, cursor=rows[-1].audit_id))
        self._caught_up = len(rows) < BATCH
        return True

    def _send(self) -> bool:
        """Send queued batches for at most ATTEMPT_S; False on any failure,
        so the outage gate fails closed (not only on DeliveryError)."""
        try:
            return self._send_batches()
        except Exception as exc:  # queue peek/ack or an unwrapped transport error
            log.error("audit shipper: delivery failed (%s)", type(exc).__name__)
            return False

    def _send_batches(self) -> bool:
        deadline = self._monotonic() + ATTEMPT_S
        while self._monotonic() < deadline:
            batch = [SinkRecord.from_wire(d) for d in self._queue.peek(BATCH)]
            if not batch:
                return True
            try:
                self._transport.send(batch)
            except DeliveryError as exc:
                log.warning(
                    "audit shipper: delivery failed after %d of %d entries (%s)",
                    exc.delivered,
                    len(batch),
                    str(exc),
                )
                if exc.delivered:
                    self._queue.ack(batch[exc.delivered - 1].audit_id)
                return False
            self._queue.ack(batch[-1].audit_id)
            log.info(
                "audit shipper: sent entries %d to %d",
                batch[0].audit_id,
                batch[-1].audit_id,
            )
        return True

    def _outage(self) -> None:
        if self._state.outage_since is None:
            self._save(
                replace(self._state, outage_since=self._clock.now(), alerted=False)
            )
        if not self._state.alerted:
            try:
                self._audit.unreachable()
            except Exception as exc:  # retried on the next failed cycle
                log.error(
                    "audit shipper: outage alert not written (%s)", type(exc).__name__
                )
            else:
                self._save(replace(self._state, alerted=True))
        self._failures += 1
        delay = min(BACKOFF_MAX_S, 2.0 ** (self._failures - 1))
        self._next_send = self._clock.now() + timedelta(seconds=delay)

    def run_once(self) -> None:
        queued = self._read()
        if self._clock.now() < self._next_send:
            return
        if not (self._send() and queued):
            self._outage()
            return
        self._failures = 0
        drained = self._queue.depth() == 0 and self._caught_up
        if drained and self._state.outage_since is not None:
            self._save(replace(self._state, outage_since=None, alerted=False))
            try:
                self._audit.recovered()
            except Exception as exc:
                log.error(
                    "audit shipper: recovery entry not written (%s)", type(exc).__name__
                )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # keep shipping; the queue is on disk
                log.error("audit shipper: cycle failed (%s)", type(exc).__name__)
            self._wake.wait(POLL_S)
            self._wake.clear()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="audit-shipper", daemon=True
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        """Finish the current cycle; the queue stays intact on disk."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
        self._transport.close()
