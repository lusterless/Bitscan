"""Enrolment requests: list, approve, reject (TS §3.2 L185–L188, L192, §6.2
L1084, L1114–L1115, §8.4 L1290; REQ-069, REQ-077; #26, #36, #64, #71; plan
work/plans/TASK-067.md, "Decisions").

A decision runs in the caller's transaction with the request row locked
first and the agent row second (one lock order), and is made once: a decided
request, or a second concurrent decision, is a conflict.
- approve new (the agent still awaiting_approval): → enrolled; first
  inventory job. A 'new' request whose agent was meanwhile enrolled through
  another request is decided like a re-enrolment (#64 (d), (f)).
- approve re-enrolment: the existing agent row is re-linked to the request's
  token (requested_at, token_expires_at), hostname and agent_version, every
  old token state cleared and status enrolled (#64), which ends the old
  token; first inventory job; the entry is a reenrolment_approved alert.
- reject new (the agent still awaiting_approval): the agent → decommissioned,
  token revoked (never deleted); otherwise only the request is rejected.
- reject re-enrolment: the agent row and its old token are unchanged (#26).
An expired request token can be rejected but not approved (#64 (e)).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.enrolment import MatchRow, RequestRow
from bitscan_manager.services.scheduler.inventory import (
    InventoryQueue,
    queue_first_inventory,
)

RequestState = Literal["pending", "decided", "all"]


class RequestStore(Protocol):  # repositories.enrolment.EnrolmentRepo
    def get_request_for_update(self, request_id: int) -> RequestRow | None: ...

    def decide(
        self, request_id: int, decision: str, decided_by: int, now: datetime
    ) -> bool: ...

    def request_page(
        self, state: RequestState, limit: int, after_id: int | None
    ) -> list[RequestRow]: ...

    def matches(self, request: RequestRow) -> list[MatchRow]: ...


class DecisionAgents(Protocol):  # repositories.agents.AgentRepo
    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def set_status(
        self, agent_id: UUID, status: str, only_from: tuple[str, ...]
    ) -> bool: ...

    def revoke(self, agent_id: UUID, now: datetime) -> bool: ...

    def relink(
        self,
        agent_id: UUID,
        *,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        hostname: str,
        agent_version: str,
    ) -> bool: ...


class AuditSink(Protocol):  # services.users.TxAudit
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


class RequestNotFound(Exception):
    pass


class RequestConflict(Exception):
    """Already decided, decided concurrently, an expired token on approval,
    or a new agent no longer awaiting approval. reason is a fixed text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RequestView:
    request: RequestRow
    matches: list[MatchRow]


def list_requests(
    store: RequestStore, state: RequestState, limit: int, after_id: int | None
) -> list[RequestView]:
    return [
        RequestView(r, store.matches(r))
        for r in store.request_page(state, limit, after_id)
    ]


def decide_request(
    store: RequestStore,
    agents: DecisionAgents,
    jobs: InventoryQueue,
    audit: AuditSink,
    *,
    request_id: int,
    approve: bool,
    admin_id: int,
    now: datetime,
) -> RequestView:
    request = store.get_request_for_update(request_id)  # lock order: request first
    if request is None:
        raise RequestNotFound
    if request.decision is not None:
        raise RequestConflict("The request is already decided.")
    if approve and now >= request.token_expires_at:
        raise RequestConflict("The request's token has expired; enrol again.")
    agent_id = request.agent_id
    agent = agents.get(agent_id, lock=True)  # then the agent row
    if agent is None:
        raise RequestNotFound
    # A 'new' request acts on the agent as new only while that agent still
    # awaits approval. Once another request of the agent was approved, a
    # 'new' one is decided like a re-enrolment (#64 (d), (f); lead ruling).
    first = request.kind == "new" and agent.status == "awaiting_approval"
    actor, target = f"user:{admin_id}", f"enrollment_request:{request_id}"
    detail = {"kind": request.kind, "agent_id": str(agent_id)}
    if approve:
        if first:
            agents.set_status(agent_id, "enrolled", ("awaiting_approval",))
            audit.audit(actor, "enrollment_request.approve", target, detail)
        else:
            agents.relink(
                agent_id,
                token_hash=request.new_token_hash,
                issued_at=request.requested_at,
                expires_at=request.token_expires_at,
                hostname=request.hostname,
                agent_version=request.agent_version,
            )
            audit.alert(
                "reenrolment_approved",
                actor,
                "enrollment_request.approve",
                target,
                detail,
            )
        queue_first_inventory(jobs, agent_id, now)  # #36
    else:
        if first:  # otherwise the agent and its current token stay (#26)
            agents.set_status(agent_id, "decommissioned", ("awaiting_approval",))
            agents.revoke(agent_id, now)
        audit.audit(actor, "enrollment_request.reject", target, detail)
    if not store.decide(
        request_id, "approved" if approve else "rejected", admin_id, now
    ):
        raise RequestConflict("The request is already decided.")
    decided = store.get_request_for_update(request_id)
    if decided is None:
        raise RequestNotFound
    return RequestView(decided, store.matches(decided))
