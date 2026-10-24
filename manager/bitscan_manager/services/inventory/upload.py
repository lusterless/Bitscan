"""PUT /agent/{id}/inventory[?job_id=…] (TS §3.4 L239–L244, §6.5 L1186,
§6.1 L1072; REQ-076, REQ-066; #72; plan work/plans/TASK-060.md, steps 2–7).

A job_id is classified before anything is decoded (#72 (d)):
- this agent's dispatched inventory job: the upload completes it, in the
  same transaction as the ingest;
- one that already failed or completed: stored as an unscheduled snapshot,
  the job unchanged;
- anything else (unknown, another agent's, compliance, queued, expired,
  cancelled, running): 409 job_not_acceptable, audit-logged, nothing stored.
An unscheduled upload (no job_id, failed or completed) asks the 10-minute
window before decoding (#72 (e)): refused, it is 429 and nothing is decoded.
A refused upload is audit-logged; a 413 or 422 also fails a dispatched job it
named (TS §3.4 L244), while a 400 leaves that job to the 30-minute sweep
(#72 (c)). Answers carry InventoryRefused.type, never its reason word.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.inventory import InventoryRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Database, RateLimits
from bitscan_manager.services.inventory.decode import InventoryRefused, decode_inventory
from bitscan_manager.services.inventory.ingest import AgentGone, BurstWindow, ingest
from bitscan_manager.services.users import TxAudit

Kind = Literal["completes", "unscheduled"]


class UploadRefused(Exception):
    """status and type for the problem answer; headers (Retry-After) if any."""

    def __init__(
        self, status: int, type_: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(type_)
        self.status, self.type, self.headers = status, type_, headers or {}


@dataclass(frozen=True)
class Upload:
    agent_id: UUID
    job_id: UUID | None
    now: datetime


Wake = Callable[[], None]  # the audit shipper's wake, run on commit


def _audit(
    db: Database, wake: Wake, up: Upload, reason: str, status: int, fail: bool
) -> None:
    """One agent.inventory_refused entry; fails the named dispatched job."""
    with db.transaction() as tx:
        tx.on_commit(wake)
        if fail and up.job_id is not None:
            JobRepo(tx.conn).fail(up.job_id, up.now)  # only while dispatched
        actor = f"agent:{up.agent_id}"
        TxAudit(PgAuditRepo(tx.conn), tx.on_commit).audit(
            actor,
            "agent.inventory_refused",
            actor,
            {"reason": reason, "status": status, "job_id": _text(up.job_id)},
        )


def _text(job_id: UUID | None) -> str | None:
    return None if job_id is None else str(job_id)


def classify(db: Database, wake: Wake, up: Upload) -> Kind:
    if up.job_id is None:
        return "unscheduled"
    with db.transaction() as tx:
        job = JobRepo(tx.conn).get_for_agent(up.job_id, up.agent_id)
    if job is not None and job.kind == "inventory":
        if job.state == "dispatched":
            return "completes"
        if job.state in ("failed", "completed"):
            return "unscheduled"
    _audit(db, wake, up, "job_not_acceptable", 409, fail=False)
    raise UploadRefused(409, "job_not_acceptable")


def refuse_unread(
    db: Database, wake: Wake, up: Upload, status: int, reason: str
) -> None:
    """A body refused before decoding (over the cap: 413; not gzip: 400)."""
    completes = False
    if up.job_id is not None:
        with db.transaction() as tx:
            job = JobRepo(tx.conn).get_for_agent(up.job_id, up.agent_id)
        completes = (
            job is not None and job.kind == "inventory" and job.state == "dispatched"
        )
    _audit(db, wake, up, reason, status, fail=completes and status == 413)


def store_upload(
    db: Database,
    wake: Wake,
    limits: RateLimits,
    burst: BurstWindow,
    up: Upload,
    body: bytes,
) -> None:
    kind = classify(db, wake, up)
    if kind == "unscheduled" and not limits.allow_unscheduled_inventory(up.agent_id):
        retry = limits.unscheduled_inventory_retry_after(up.agent_id)
        raise UploadRefused(429, "rate_limited", {"Retry-After": str(retry)})
    try:
        decoded = decode_inventory(body)
    except InventoryRefused as exc:
        fails = kind == "completes" and exc.status in (413, 422)
        _audit(db, wake, up, exc.reason, exc.status, fail=fails)
        raise UploadRefused(exc.status, exc.type) from None
    try:
        with db.transaction() as tx:
            tx.on_commit(wake)
            ingest(
                InventoryRepo(tx.conn),
                AgentRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                burst,
                tx.on_commit,
                agent_id=up.agent_id,
                decoded=decoded,
                now=up.now,
            )
            if kind == "completes" and up.job_id is not None:
                JobRepo(tx.conn).complete(up.job_id, up.now)  # if still dispatched
    except AgentGone:
        raise UploadRefused(401, "token_revoked") from None
