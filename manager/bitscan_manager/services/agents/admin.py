"""Agent tags and revoke (TS §6.2 L1112–L1113, §3.2 L191, §5.2 L742–L746;
REQ-082; #68, #71, #73 (c)).

Tags: an operator replaces the agent's whole tag set; 0–32 distinct tags of
1–64 characters from A–Z, a–z, 0–9 and ._:- (#68). Revoke: an admin ends the
agent's current and any previous token at once, so every agent call gets
401 token_revoked and the host must re-enrol; the status is not changed
(#73 (c)). Each change writes one audit entry, decided with the agent row
locked, so concurrent calls cannot both write one.
"""

import string
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRow

MAX_TAGS: Final = 32
MAX_TAG_LENGTH: Final = 64
TAG_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "._:-")


class AdminAgents(Protocol):  # repositories.agents.AgentRepo
    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def tags(self, agent_id: UUID) -> list[str]: ...

    def replace_tags(self, agent_id: UUID, tags: list[str]) -> None: ...

    def revoke(self, agent_id: UUID, now: datetime) -> bool: ...


class Auditor(Protocol):  # services.users.TxAudit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...


class AgentNotFound(Exception):
    pass


class InvalidTags(Exception):
    """Too many, duplicates, empty, too long or outside the characters."""


def check_tags(tags: Sequence[str]) -> list[str]:
    if len(tags) > MAX_TAGS or len(set(tags)) != len(tags):
        raise InvalidTags
    for tag in tags:
        if not 1 <= len(tag) <= MAX_TAG_LENGTH or not TAG_CHARACTERS.issuperset(tag):
            raise InvalidTags
    return list(tags)


def set_tags(
    agents: AdminAgents,
    audit: Auditor,
    *,
    agent_id: UUID,
    tags: Sequence[str],
    user_id: int,
) -> list[str]:
    checked = check_tags(tags)  # before anything is written
    if agents.get(agent_id, lock=True) is None:
        raise AgentNotFound
    before = agents.tags(agent_id)
    agents.replace_tags(agent_id, checked)
    target = f"agent:{agent_id}"
    audit.audit(
        f"user:{user_id}",
        "agent.tags_set",
        target,
        {"old": before, "new": sorted(checked)},
    )
    return agents.tags(agent_id)


def revoke_agent(
    agents: AdminAgents, audit: Auditor, *, agent_id: UUID, user_id: int, now: datetime
) -> None:
    """A token already revoked keeps its revoked_at and writes no entry."""
    agent = agents.get(agent_id, lock=True)
    if agent is None:
        raise AgentNotFound
    if agent.token_revoked_at is None:
        agents.revoke(agent_id, now)
        audit.audit(f"user:{user_id}", "agent.revoke", f"agent:{agent_id}", {})
