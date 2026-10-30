"""offline_sweep (TS §3.3 L218, L220, §3.4 L244, §4.4 L572, L575; REQ-078;
#25, #73; plan work/plans/TASK-061.md).

Each step runs in its own transaction, so a step that fails leaves the others
applied and the next sweep simply runs it again; a failure is logged by step
name and exception type only. Inventory jobs are never retried (TS §3.4
L244).

M9 (TS §4.4 L575, L577, L579–L580; REQ-218, REQ-219; #126, #127; design note
D3) appends three steps:
- compliance_deadline: dispatched or running compliance jobs strictly past
  their deadline end completed, partial or failed by the unit's results;
- never_started: compliance jobs dispatched strictly more than 24 h ago that
  never started end failed;
- in both, an original (never a retry) that ends failed or partial gets its
  single retry in the same transaction, unless its policy is deleted or its
  agent decommissioned (#126 (c), (d)). Each job is locked root first, then
  itself, SKIP LOCKED (the intake's order), and its state re-checked under
  the lock; a skipped job is handled by the next sweep. Each job runs in
  its own savepoint, so one job that cannot be ended or retried is rolled
  back and logged alone and the others still end;
- scan_states: every refresh candidate (#127 (f)) is locked, its units read
  in one statement, and only scans whose state or finished_at changes are
  written.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import psycopg

from bitscan_manager.repositories import job_sweep, scan_progress
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.job_sweep import SweepJob
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Database, Tx
from bitscan_manager.services.audit.metrics import JOBS_EXPIRED
from bitscan_manager.services.jobs import build, states
from bitscan_manager.services.jobs.scan_state import Unit, derive
from bitscan_manager.services.scheduler.inventory import PICKUP_WINDOW
from bitscan_manager.services.settings.store import SettingsReader, read_settings
from bitscan_manager.services.users import TxAudit

log = logging.getLogger("bitscan_manager.scheduler")

STALE_AFTER: Final = timedelta(minutes=10)  # online below, stale from here
OFFLINE_AFTER: Final = timedelta(minutes=30)  # offline above
INVENTORY_UPLOAD_WINDOW: Final = timedelta(minutes=30)  # TS §3.4 L244


class SweepAgents(Protocol):
    def apply_heartbeat_ages(
        self, now: datetime, stale_after: timedelta, offline_after: timedelta
    ) -> int: ...

    def decommission_offline(self, now: datetime, after: timedelta) -> list[UUID]: ...


class SweepJobs(Protocol):
    def expire_past_pickup(self, now: datetime) -> int: ...

    def fail_dispatched_inventory(
        self, dispatched_before: datetime, now: datetime
    ) -> int: ...


class Auditor(Protocol):  # services.users.TxAudit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...


class ComplianceRepos:
    """The compliance steps' SQL (repositories job_sweep and scan_progress)
    over one connection; unit tests pass a subclass with fakes."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def past_deadline(self, now: datetime) -> list[UUID]:
        return job_sweep.past_deadline(self._conn, now)

    def never_started(self, now: datetime, after: timedelta) -> list[UUID]:
        return job_sweep.never_started(self._conn, now, after)

    def lock_for_sweep(self, job_id: UUID) -> SweepJob | None:
        return job_sweep.lock_for_sweep(self._conn, job_id)

    def unit_result_uuids(self, job: SweepJob) -> set[UUID]:
        return job_sweep.unit_result_uuids(self._conn, job)

    def end_job(self, job_id: UUID, state: str, now: datetime) -> bool:
        return job_sweep.end_job(self._conn, job_id, state, now)

    def insert_retry(
        self,
        original: SweepJob,
        job_id: UUID,
        payload: Mapping[str, Any],
        eval_spec: Mapping[str, Any],
        now: datetime,
    ) -> None:
        job_sweep.insert_retry(
            self._conn,
            original=original,
            job_id=job_id,
            payload=payload,
            eval_spec=eval_spec,
            created_at=now,
            pickup_by=now + PICKUP_WINDOW,
        )

    def refresh_candidates(self, now: datetime) -> list[UUID]:
        return scan_progress.refresh_candidates(self._conn, now)

    def lock_scan(self, scan_id: UUID) -> tuple[str, datetime | None] | None:
        return scan_progress.scan_row(self._conn, scan_id, lock=True)

    def unit_facts(self, scan_ids: Sequence[UUID]) -> dict[UUID, list[Unit]]:
        return scan_progress.unit_facts(self._conn, scan_ids)

    def set_scan_state(
        self, scan_id: UUID, state: str, finished_at: datetime | None
    ) -> bool:
        return scan_progress.set_scan_state(self._conn, scan_id, state, finished_at)

    def savepoint(self) -> AbstractContextManager[object]:
        """A savepoint for one job's lock, end and retry (rolled back alone)."""
        return self._conn.transaction()


@dataclass(frozen=True)
class Stores:
    """What one step's transaction works with. `compliance` None means the
    PostgreSQL repositories over `tx.conn` (factories written before M9)."""

    tx: Tx
    agents: SweepAgents
    jobs: SweepJobs
    settings: SettingsReader
    audit: Auditor
    compliance: ComplianceRepos | None = None


def pg_stores(tx: Tx) -> Stores:
    return Stores(
        tx,
        AgentRepo(tx.conn),
        JobRepo(tx.conn),
        SettingsRepo(tx.conn),
        TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
        ComplianceRepos(tx.conn),
    )


@dataclass
class SweepResult:
    statuses_changed: int = 0
    decommissioned: int = 0
    expired: int = 0
    inventory_failed: int = 0
    deadline_ended: int = 0
    never_started_failed: int = 0
    retries: int = 0
    scans_refreshed: int = 0
    failed_steps: list[str] = field(default_factory=list)


def _statuses(s: Stores, now: datetime, out: SweepResult) -> None:
    out.statuses_changed = s.agents.apply_heartbeat_ages(
        now, STALE_AFTER, OFFLINE_AFTER
    )


def _decommission(s: Stores, now: datetime, out: SweepResult) -> None:
    days = read_settings(s.settings).decommission_after_days
    if days == 0:  # 0 = never (TS §3.3 L220)
        return
    ids = s.agents.decommission_offline(now, timedelta(days=days))
    for agent_id in ids:  # one entry per decommissioned agent (#73 (d))
        target = f"agent:{agent_id}"
        s.audit.audit("system", "agent.decommission", target, {"after_days": days})
    out.decommissioned = len(ids)


def _expire(s: Stores, now: datetime, out: SweepResult) -> None:
    count = s.jobs.expire_past_pickup(now)
    if count:
        s.tx.on_commit(lambda: JOBS_EXPIRED.inc(count))  # only once committed
    out.expired = count


def _inventory_timeout(s: Stores, now: datetime, out: SweepResult) -> None:
    out.inventory_failed = s.jobs.fail_dispatched_inventory(
        now - INVENTORY_UPLOAD_WINDOW, now
    )


def _compliance(s: Stores) -> ComplianceRepos:
    return s.compliance if s.compliance is not None else ComplianceRepos(s.tx.conn)


def _planned(job: SweepJob) -> list[UUID]:
    return [UUID(p["plugin_uuid"]) for p in job.payload["plugins"]]


def _end(
    c: ComplianceRepos, job: SweepJob, state: str, have: set[UUID], now: datetime
) -> tuple[bool, int]:
    """Ends the locked job, then makes its retry when one is due (#126 (c),
    (d)) from the plugins with no result in the unit (`have`), in this
    transaction. Returns (ended by this call, retries made)."""
    if not c.end_job(job.job_id, state, now):
        return False, 0
    if (
        state not in ("failed", "partial")
        or job.retry_of is not None  # a retry is never retried
        or job.policy_deleted
        or job.agent_decommissioned
    ):
        return True, 0
    retry_id = uuid4()
    payload, spec = build.retry(
        job.payload,
        job.eval_spec,
        [u for u in _planned(job) if u not in have],
        job_id=retry_id,
        created_at=now,
        original_is_retry=False,
    )
    c.insert_retry(job, retry_id, payload, spec, now)
    return True, 1


def _deadline_job(c: ComplianceRepos, job_id: UUID, now: datetime) -> tuple[bool, int]:
    job = c.lock_for_sweep(job_id)
    if (  # re-checked under the lock; strictly past (#127 (b))
        job is None
        or job.state not in ("dispatched", "running")
        or job.deadline_at is None
        or not job.deadline_at < now
    ):
        return False, 0
    planned = set(_planned(job))
    have = c.unit_result_uuids(job) & planned
    state = states.after_deadline(
        any_result=bool(have), all_have_results=planned <= have
    )
    if not states.allowed(job.state, state):
        return False, 0
    return _end(c, job, state, have, now)


def _never_started_job(
    c: ComplianceRepos, job_id: UUID, now: datetime
) -> tuple[bool, int]:
    job = c.lock_for_sweep(job_id)
    if (  # re-checked under the lock; strictly past (#127 (b))
        job is None
        or job.state != "dispatched"
        or job.started_at is not None
        or job.dispatched_at is None
        or not job.dispatched_at < now - states.NEVER_STARTED_AFTER
    ):
        return False, 0
    # No batch was ever accepted, so `failed`; the unit's results still
    # decide the retry's plugins (#126 (a)).
    return _end(c, job, "failed", c.unit_result_uuids(job), now)


def _each_job(
    c: ComplianceRepos,
    step: str,
    job_ids: Sequence[UUID],
    handle: Callable[[ComplianceRepos, UUID, datetime], tuple[bool, int]],
    now: datetime,
) -> tuple[int, int]:
    """Each job in its own savepoint, so one job that cannot be ended or
    retried (an unreadable eval_spec or payload, a failing insert) is rolled
    back alone, logged by step, job_id and exception type only, and the
    others still end (fails closed per job, as intake does, #124 (h)).
    Returns (jobs ended, retries made)."""
    ended = retries = 0
    for job_id in job_ids:
        try:
            with c.savepoint():
                done, made = handle(c, job_id, now)
        except Exception as exc:
            log.error(
                "sweep job failed",
                extra={
                    "data": {
                        "step": step,
                        "job_id": str(job_id),
                        "exc_type": type(exc).__name__,
                    }
                },
            )
            continue
        ended += done
        retries += made
    return ended, retries


def _compliance_deadline(s: Stores, now: datetime, out: SweepResult) -> None:
    c = _compliance(s)
    ids = c.past_deadline(now)
    ended, retries = _each_job(c, "compliance_deadline", ids, _deadline_job, now)
    out.deadline_ended += ended
    out.retries += retries


def _never_started(s: Stores, now: datetime, out: SweepResult) -> None:
    c = _compliance(s)
    ids = c.never_started(now, states.NEVER_STARTED_AFTER)
    ended, retries = _each_job(c, "never_started", ids, _never_started_job, now)
    out.never_started_failed += ended
    out.retries += retries


def _scan_states(s: Stores, now: datetime, out: SweepResult) -> None:
    c = _compliance(s)
    current: dict[UUID, tuple[str, datetime | None]] = {}
    for scan_id in c.refresh_candidates(now):  # scan_id order: no lock cycle
        row = c.lock_scan(scan_id)
        if row is not None:
            current[scan_id] = row
    for scan_id, units in c.unit_facts(list(current)).items():
        state, finished = derive(units)
        old_state, old_finished = current[scan_id]
        if state == old_state and (old_finished is not None or not finished):
            continue  # unchanged: not written
        if c.set_scan_state(scan_id, state, now if finished else None):
            out.scans_refreshed += 1


STEPS: Final[
    tuple[tuple[str, Callable[[Stores, datetime, SweepResult], None]], ...]
] = (
    ("statuses", _statuses),
    ("decommission", _decommission),
    ("expire", _expire),
    ("inventory_timeout", _inventory_timeout),
    ("compliance_deadline", _compliance_deadline),
    ("never_started", _never_started),
    ("scan_states", _scan_states),
)


def run_sweep(
    db: Database, now: datetime, stores: Callable[[Tx], Stores] = pg_stores
) -> SweepResult:
    out = SweepResult()
    for name, step in STEPS:
        try:
            with db.transaction() as tx:
                step(stores(tx), now, out)
        except Exception as exc:  # the other steps still run (REQ-078 (5))
            out.failed_steps.append(name)
            log.error(
                "sweep step failed",
                extra={"data": {"step": name, "exc_type": type(exc).__name__}},
            )
    return out
