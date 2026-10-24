"""POST /agent/enroll (TS §3.2 L183–L188; REQ-068, REQ-077; #25, #36, #59,
#61, #64, #71; plan work/plans/TASK-067.md).

One transaction: the atomic use of the bse_ token (expiry, revocation, the
source CIDRs and uses < max_uses in one statement), then exactly one of:
- a new machine-id with auto_approve: an enrolled agent, plus its first
  inventory job (#36);
- a new machine-id without it: an awaiting_approval agent holding the token
  hash, plus a kind 'new' request;
- a known machine-id, whatever the token allows: a kind 'reenrol' request
  holding the new hash; the existing agent row is not changed (#64).
Every enrolment writes one agent.enrol entry (#71) and counts toward the
token's per-hour window (#61). Only the SHA-256 of the new bsa_ token is
stored; the token itself is returned once.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.enrolment import UsedToken
from bitscan_manager.services.scheduler.inventory import (
    InventoryQueue,
    queue_first_inventory,
)
from bitscan_manager.services.settings.store import SettingsReader, read_settings


class EnrolAgents(Protocol):  # repositories.agents.AgentRepo
    def find_by_machine_id(
        self, machine_id: str, *, lock: bool = False
    ) -> AgentRow | None: ...

    def insert(
        self,
        *,
        machine_id: str,
        hostname: str,
        agent_version: str,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        status: str,
        now: datetime,
    ) -> UUID | None: ...

    def record_ip(self, agent_id: UUID, ip: str, now: datetime) -> None: ...


class EnrolRequests(Protocol):  # repositories.enrolment.EnrolmentRepo
    def use_token(
        self, token_hash: str, source_ip: str, now: datetime
    ) -> UsedToken | None: ...

    def insert_request(
        self,
        *,
        kind: str,
        agent_id: UUID,
        token_id: int,
        hostname: str,
        machine_id: str,
        os_pretty_name: str | None,
        agent_version: str,
        new_token_hash: str,
        token_expires_at: datetime,
        source_ip: str,
        now: datetime,
    ) -> int: ...


class Auditor(Protocol):  # services.users.TxAudit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...

    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


class PerTokenWindow(Protocol):  # services.audit.thresholds.SlidingCount
    def count_and_check(
        self, key: Any, weight: int = 1, threshold: int | None = None
    ) -> bool: ...

    def mark_fired(self, key: Any) -> None: ...


@dataclass(frozen=True)
class Enrolment:
    """The request body fields enrolment uses (os_id, os_version_id: #60)."""

    hostname: str
    machine_id: str
    agent_version: str
    os_pretty_name: str | None


@dataclass(frozen=True)
class Enrolled:
    agent_id: UUID
    agent_token: str  # returned once, never stored
    issued_at: datetime
    expires_at: datetime
    status: Literal["enrolled", "awaiting_approval"]


class EnrolRefused(Exception):
    """The bse_ token is unknown, expired, revoked, exhausted or the source is
    outside its CIDRs: one refusal for every cause (#59); nothing changed."""


def enrol(
    agents: EnrolAgents,
    requests: EnrolRequests,
    jobs: InventoryQueue,
    settings: SettingsReader,
    audit: Auditor,
    window: PerTokenWindow,
    on_commit: Callable[[Callable[[], None]], None],
    *,
    enrolment_token: str,
    body: Enrolment,
    source_ip: str,
    now: datetime,
) -> Enrolled:
    used = requests.use_token(token_hash(enrolment_token), source_ip, now)
    if used is None:
        raise EnrolRefused
    current = read_settings(settings)
    token = new_agent_token(AgentTokenKind.AGENT)
    digest = token_hash(token)
    expires = now + timedelta(days=current.agent_token_ttl_days)
    existing = agents.find_by_machine_id(body.machine_id, lock=True)
    agent_id: UUID | None = None
    if existing is None:
        status = "enrolled" if used.auto_approve else "awaiting_approval"
        agent_id = agents.insert(
            machine_id=body.machine_id,
            hostname=body.hostname,
            agent_version=body.agent_version,
            token_hash=digest,
            issued_at=now,
            expires_at=expires,
            status=status,
            now=now,
        )
        if agent_id is None:  # a concurrent first enrolment won the insert
            existing = agents.find_by_machine_id(body.machine_id, lock=True)
    request_id: int | None = None
    if agent_id is not None:
        kind = "new"
        agents.record_ip(agent_id, source_ip, now)  # #25 (b), the new row only
        if used.auto_approve:
            queue_first_inventory(jobs, agent_id, now)  # #36
            answer: Literal["enrolled", "awaiting_approval"] = "enrolled"
        else:
            answer = "awaiting_approval"
    else:
        if existing is None:
            raise RuntimeError("the agent row vanished during enrolment")
        kind, agent_id, answer = "reenrol", existing.agent_id, "awaiting_approval"
    if answer == "awaiting_approval":
        request_id = requests.insert_request(
            kind=kind,
            agent_id=agent_id,
            token_id=used.token_id,
            hostname=body.hostname,
            machine_id=body.machine_id,
            os_pretty_name=body.os_pretty_name,
            agent_version=body.agent_version,
            new_token_hash=digest,
            token_expires_at=expires,
            source_ip=source_ip,
            now=now,
        )
    actor = f"agent:{agent_id}"
    detail = {"token_id": used.token_id, "kind": kind, "status": answer}
    audit.audit(actor, "agent.enrol", actor, {**detail, "request_id": request_id})
    limit = current.enrolment_alert_per_hour
    if window.count_and_check(used.token_id, 1, limit):  # #61
        target = f"enrollment_token:{used.token_id}"
        audit.alert(
            "enrolments_per_hour",
            actor,  # #71: agent:<id> of the enrolment that crossed the threshold
            "alert.enrolments_per_hour",
            target,
            {"over_per_hour": limit},
        )
        on_commit(lambda: window.mark_fired(used.token_id))
    return Enrolled(agent_id, token, now, expires, answer)
