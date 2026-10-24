"""The agent token check on every bsa_ route (TS §3.2 L185–L191, §6.1 L1070;
#25, #26, #59, #62, #63; plan work/plans/TASK-059.md, outcome table).

Order (#59): token shape; lookup by agent.token_hash, then prev_token_hash,
then enrollment_request.new_token_hash; enrollment_rejected; token_revoked;
token_expired; machine_id_mismatch; then the rotation overlap and reuse
(#62); pending_approval. The {id} match and the agent rate limit follow in
the route dependency (TASK-063). Every 401 counts as a failed check; the 403
pending_approval does not.

A refusal is raised as AgentTokenRefused after any revoke and alert were
written; the caller catches it inside its transaction so those commit, then
answers. Only token hashes are handled here, and nothing is logged.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, NoReturn, Protocol
from uuid import UUID

from bitscan_manager.auth.tokens import AgentTokenKind, is_agent_token, token_hash
from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.enrolment import RequestRow

OVERLAP: Final = timedelta(minutes=10)  # #62: old token after the new one's first use
# While the rotated-in token is still unused, the old token works only this
# long after the rotation (user ruling 2026-10-23): rotate() overwrote its own
# expires_at, so this is its expiry in the lost-response state.
UNUSED_ROTATION_CAP: Final = timedelta(days=30)
_HEX: Final = frozenset("0123456789abcdef")


class AgentLookup(Protocol):  # repositories.agents.AgentRepo
    def find_by_token_hash(self, token_hash: str) -> AgentRow | None: ...

    def find_by_prev_hash(self, token_hash: str) -> AgentRow | None: ...

    def revoke(self, agent_id: UUID, now: datetime) -> bool: ...

    def mark_new_token_used(self, agent_id: UUID, overlap_until: datetime) -> bool: ...


class RequestLookup(Protocol):  # repositories.enrolment.EnrolmentRepo
    def find_by_new_token_hash(self, token_hash: str) -> RequestRow | None: ...

    def rejected_new_for_agent(self, agent_id: UUID) -> bool: ...


class Alerter(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


@dataclass(frozen=True)
class AgentCaller:
    agent_id: UUID
    via: Literal["current", "previous"]
    agent: AgentRow


class AgentTokenRefused(Exception):
    """status and type per #59; counted: a failed token check (every 401);
    agent_id: the agent the token resolved to, if any (#65 (d))."""

    def __init__(self, status: int, type_: str, agent_id: UUID | None = None) -> None:
        super().__init__(type_)
        self.status = status
        self.type = type_
        self.counted = status == 401
        self.agent_id = agent_id


def _same_machine(header: str | None, machine_id: str) -> bool:
    """A missing or malformed header counts as a different machine-id (#63)."""
    return (
        header is not None
        and len(header) == 32
        and _HEX.issuperset(header)
        and header == machine_id
    )


def _mismatch(audit: Alerter, agent_id: UUID, via: str) -> None:
    audit.alert(
        "machine_id_mismatch",
        f"agent:{agent_id}",
        "agent.machine_id_mismatch",
        f"agent:{agent_id}",
        {"via": via},
    )


def check_agent_token(
    agents: AgentLookup,
    requests: RequestLookup,
    audit: Alerter,
    *,
    raw: str | None,
    machine_id_header: str | None,
    now: datetime,
) -> AgentCaller:
    if raw is None or not is_agent_token(raw, AgentTokenKind.AGENT):
        raise AgentTokenRefused(401, "unauthorized")
    digest = token_hash(raw)
    agent = agents.find_by_token_hash(digest)
    via: Literal["current", "previous"] = "current"
    if agent is None:
        agent, via = agents.find_by_prev_hash(digest), "previous"
    if agent is None:
        _pending_request(requests, audit, digest, machine_id_header, now)
    agent_id = agent.agent_id
    if (
        via == "current"
        and agent.status == "decommissioned"
        and requests.rejected_new_for_agent(agent_id)
    ):
        raise AgentTokenRefused(401, "enrollment_rejected", agent_id)
    if agent.token_revoked_at is not None:
        raise AgentTokenRefused(401, "token_revoked", agent_id)
    if via == "current" and now >= agent.token_expires_at:
        raise AgentTokenRefused(401, "token_expired", agent_id)
    if via == "previous" and agent.prev_token_expires_at is None:
        rotated = agent.last_rotation_at
        if rotated is None or now >= rotated + UNUSED_ROTATION_CAP:
            raise AgentTokenRefused(401, "token_expired", agent_id)
    if not _same_machine(machine_id_header, agent.machine_id):
        agents.revoke(agent_id, now)  # also ends the previous token
        _mismatch(audit, agent_id, via)
        raise AgentTokenRefused(401, "machine_id_mismatch", agent_id)
    if via == "previous":
        until = agent.prev_token_expires_at
        if until is not None and now >= until:  # used after the overlap (#62)
            agents.revoke(agent_id, now)
            audit.alert(
                "token_reuse",
                f"agent:{agent_id}",
                "agent.token_reuse",
                f"agent:{agent_id}",
                {"via": via},
            )
            raise AgentTokenRefused(401, "token_revoked", agent_id)
    elif agent.status == "awaiting_approval":
        raise AgentTokenRefused(403, "pending_approval", agent_id)
    elif agent.prev_token_hash is not None and agent.prev_token_expires_at is None:
        agents.mark_new_token_used(agent_id, now + OVERLAP)  # first use (#62)
    return AgentCaller(agent_id, via, agent)


def _pending_request(
    requests: RequestLookup,
    audit: Alerter,
    digest: str,
    machine_id_header: str | None,
    now: datetime,
) -> NoReturn:
    """A held re-enrolment's new token: never accepted (#26, #59, #63)."""
    request = requests.find_by_new_token_hash(digest)
    if request is None or request.decision == "approved":
        raise AgentTokenRefused(401, "unauthorized")  # a replaced token is unknown
    agent_id = request.agent_id
    if request.decision == "rejected":
        raise AgentTokenRefused(401, "enrollment_rejected", agent_id)
    if now >= request.token_expires_at:
        raise AgentTokenRefused(401, "token_expired", agent_id)
    if not _same_machine(machine_id_header, request.machine_id):
        _mismatch(audit, agent_id, "request")  # the request stays pending (#63)
        raise AgentTokenRefused(401, "machine_id_mismatch", agent_id)
    raise AgentTokenRefused(403, "pending_approval", agent_id)
