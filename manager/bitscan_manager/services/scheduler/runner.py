"""The scheduler inside serve (TS §2.1 L103, §3.3 L218, §3.4 L230, §4.4 L557,
§8.7 L1343; REQ-080, REQ-225; #67, #128 (e); plan work/plans/TASK-061.md,
"Scheduler wiring", and work/plans/TASK-203.md §5).

APScheduler 3 (BackgroundScheduler) runs four jobs, each at most one at a
time, on four worker threads:
- inventory: at start-up, then every system_schedule interval for
  'inventory' (#67). Each sweep re-reads that interval and restarts the timer
  when it changed, so a PATCH /settings takes effect within one sweep.
- offline_sweep: every system_schedule interval for 'offline_sweep' (read at
  start-up only; it is not a runtime setting), running run_sweep() and then
  the fleet threshold alerts.
- scan_schedules: every 30 s, running each due scan schedule once
  (run_due_schedules; not a runtime setting, no system_schedule row).
- retention: 10 minutes after start-up, then every system_schedule interval
  for 'retention' (read at start-up only; 86,400 s if unreadable), running
  run_retention() on the bitscan_retention pool only (TS §5.3 L1051; REQ-277;
  #150 (h)). serve always passes that pool and the shipper's cursor; a runner
  built without them (tests) schedules the other three jobs only.
A run that raises is logged by job name and exception type only, and the
next run still happens. Every transaction a job opens wakes the audit shipper
on commit (retention wakes it after each checkpoint). On stop, a flag makes
every further transaction a job asks for, on either pool, fail at once
(SchedulerStopping), so a run gives up at its next sweep step, fleet check,
interval read, inventory run, schedule row or retention chunk instead of
waiting on a refusing database each time; stop() then waits for the run, so
nothing touches a pool after it closed. Nothing here opens a connection other
than the manager's database, through those two pools.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, timedelta
from typing import Any, Final

from apscheduler.executors.pool import (  # type: ignore[import-untyped]
    ThreadPoolExecutor,
)
from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)

from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Clock, Database, Tx
from bitscan_manager.services.retention import task as retention_task
from bitscan_manager.services.scheduler.fleet_alerts import FleetAlerts, pg_fleet_stores
from bitscan_manager.services.scheduler.inventory import run_inventory
from bitscan_manager.services.scheduler.scan_schedules import (
    TICK_S,
    run_due_schedules,
)
from bitscan_manager.services.scheduler.sweep import pg_stores, run_sweep

log = logging.getLogger("bitscan_manager.scheduler")

INVENTORY: Final = "inventory"
SWEEP: Final = "offline_sweep"
SCAN_SCHEDULES: Final = "scan_schedules"
RETENTION: Final = "retention"
# The seeded intervals (TS §5.2 L835), used only if system_schedule cannot be
# read at start-up; the sweep then re-reads the inventory interval.
DEFAULT_INTERVAL_S: Final = {INVENTORY: 21_600, SWEEP: 60, RETENTION: 86_400}
RETENTION_DELAY: Final = timedelta(minutes=10)  # the first run (#150 (h))


class SchedulerStopping(Exception):
    """The scheduler is stopping: a job may not start another transaction."""


class _StoppableDatabase:
    """The database as the jobs see it: no new transaction once stopping."""

    def __init__(self, db: Database, stopping: threading.Event) -> None:
        self._db, self._stopping = db, stopping

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        if self._stopping.is_set():
            raise SchedulerStopping
        with self._db.transaction() as tx:
            yield tx

    def ping(self) -> bool:
        return self._db.ping()


class SchedulerRunner:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        wake: Callable[[], None],
        scheduler: Any | None = None,  # tests may pass their own
        *,
        retention_db: Database | None = None,  # the bitscan_retention pool
        shipped_through: Callable[[], int | None] | None = None,  # the shipper's
    ) -> None:
        if (retention_db is None) != (shipped_through is None):
            raise ValueError("retention_db and shipped_through go together")
        self._stopping = threading.Event()
        self._db: Database = _StoppableDatabase(db, self._stopping)
        self._retention_db: Database | None = (
            None
            if retention_db is None
            else _StoppableDatabase(retention_db, self._stopping)
        )
        self._shipped_through = shipped_through
        self._clock, self._wake = clock, wake
        self._fleet = FleetAlerts(clock)  # built once per process
        self._scheduler = scheduler or BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(4)}, timezone=UTC
        )
        self._inventory_s = DEFAULT_INTERVAL_S[INVENTORY]

    def _interval(self, job_kind: str) -> int:
        with self._db.transaction() as tx:
            value = SettingsRepo(tx.conn).schedule_interval(job_kind)
        return DEFAULT_INTERVAL_S[job_kind] if value is None else value

    def _tx(self, tx: Tx) -> Tx:
        tx.on_commit(self._wake)  # audit entries reach the sink promptly
        return tx

    def _guarded(self, name: str, run: Callable[[], None]) -> None:
        try:
            run()
        except Exception as exc:
            log.error(
                "scheduler run failed",
                extra={"data": {"job": name, "exc_type": type(exc).__name__}},
            )

    def run_inventory(self) -> None:
        def run() -> None:
            with self._db.transaction() as tx:
                run_inventory(JobRepo(self._tx(tx).conn), self._clock.now())

        self._guarded(INVENTORY, run)

    def run_sweep(self) -> None:
        def run() -> None:
            now = self._clock.now()
            run_sweep(self._db, now, lambda tx: pg_stores(self._tx(tx)))
            self._fleet.run(self._db, now, lambda tx: pg_fleet_stores(self._tx(tx)))
            interval = self._interval(INVENTORY)
            if interval != self._inventory_s:  # #67: restart the inventory timer
                self._inventory_s = interval
                self._scheduler.reschedule_job(
                    INVENTORY, trigger="interval", seconds=interval
                )

        self._guarded(SWEEP, run)

    def run_scan_schedules(self) -> None:
        def run() -> None:
            run_due_schedules(self._db, self._clock.now(), self._wake)

        self._guarded(SCAN_SCHEDULES, run)

    def run_retention(self) -> None:
        def run() -> None:
            if self._retention_db is None or self._shipped_through is None:
                return  # not configured (tests); serve always configures it
            retention_task.run_retention(
                self._retention_db,
                self._clock.now(),
                shipped_through=self._shipped_through,
                wake=self._wake,
            )

        self._guarded(RETENTION, run)

    def start(self) -> None:
        kinds = [INVENTORY, SWEEP]
        if self._retention_db is not None:
            kinds.append(RETENTION)
        intervals = {kind: DEFAULT_INTERVAL_S[kind] for kind in kinds}
        try:
            intervals = {kind: self._interval(kind) for kind in kinds}
        except Exception as exc:  # the database may still be starting
            log.error(
                "scheduler intervals not read, using the seeded values",
                extra={"data": {"exc_type": type(exc).__name__}},
            )
        self._inventory_s = intervals[INVENTORY]
        first = self._clock.now()  # #67: one inventory run at start-up
        intervals[SCAN_SCHEDULES] = TICK_S
        jobs = [
            (INVENTORY, self.run_inventory, first),
            (SWEEP, self.run_sweep, first),
            (SCAN_SCHEDULES, self.run_scan_schedules, first),
        ]
        if self._retention_db is not None:
            jobs.append((RETENTION, self.run_retention, first + RETENTION_DELAY))
        for job_id, func, next_run in jobs:
            self._scheduler.add_job(
                func,
                "interval",
                seconds=intervals[job_id],
                id=job_id,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=intervals[job_id],
                next_run_time=next_run,
            )
        self._scheduler.start()

    def stop(self) -> None:
        """Running jobs give up at their next transaction; waits for them, and
        no run starts afterwards."""
        self._stopping.set()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
