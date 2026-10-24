"""Agent token rotation (TS §3.2 L190–L191, §8.4 L1290; REQ-071; #62;
plan work/plans/TASK-059.md, "Rotation"). Runs in the caller's transaction
with the agent row locked, so two rotations serialise.

- Called with the current token: first at most once per 24 h, counting only
  a rotation whose new token was then used: otherwise 429 with Retry-After to
  the end of those 24 h and no window alert (#62; checked before the window,
  lead ruling 2026-10-23, TASK-075 revision 1). Then only inside the window
  from issued_at + max(TTL − 30 d, TTL ÷ 2) to expires_at, where TTL is that
  token's own expires_at − issued_at (after expires_at the token check
  already answered 401 token_expired). Earlier: 403 forbidden and a
  rotation_outside_window alert. The new token lives for the current
  agent_token_ttl_days.
- Called with the previous token while the new one is unused: the lost-
  response retry. A fresh token replaces the unused one; last_rotation_at is
  kept, so neither the 24 h rule nor the 30-day cap of the old token moves.
  It is a rotation for the new-IP rule below (revision 1). A call that
  presented the current token, but whose token became the previous one
  through a concurrent rotation while it waited for the row lock (the new
  token still unused), is the same retry: no false window alert (user
  ruling 2026-10-23, TASK-075 revision 2).
- Called with the previous token after the new one was used, even inside the
  10-minute overlap: reuse. Both tokens are revoked, token_reuse alerts, 401.
- A rotation from an IP this agent was not seen from in the last 7 days
  (or never) alerts rotation_new_ip.
Only the new token's SHA-256 is stored; the token is returned once.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.services.enrolment.token_check import AgentCaller
from bitscan_manager.services.settings.store import SettingsReader, read_settings

WINDOW_BEFORE_EXPIRY: Final = timedelta(days=30)
ONCE_PER: Final = timedelta(hours=24)
NEW_IP_AFTER: Final = timedelta(days=7)


class RotationAgents(Protocol):  # repositories.agents.AgentRepo
    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def rotate(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool: ...

    def replace_unused_token(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool: ...

    def revoke(self, agent_id: UUID, now: datetime) -> bool: ...


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


@dataclass(frozen=True)
class Rotated:
    agent_token: str  # returned once, never stored
    issued_at: datetime
    expires_at: datetime


class RotationRefused(Exception):
    """Raised after any revoke or alert was written; the caller lets them
    commit, then answers status and type (with headers, such as Retry-After)."""

    def __init__(
        self, status: int, type_: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(type_)
        self.status, self.type, self.headers = status, type_, headers or {}


def window_opens(issued_at: datetime, expires_at: datetime) -> datetime:
    ttl = expires_at - issued_at
    return issued_at + max(ttl - WINDOW_BEFORE_EXPIRY, ttl / 2)


def rotate_token(
    agents: RotationAgents,
    settings: SettingsReader,
    audit: AuditSink,
    *,
    caller: AgentCaller,
    ip_last_seen: datetime | None,
    now: datetime,
) -> Rotated:
    agent_id = caller.agent_id
    row = agents.get(agent_id, lock=True)
    if row is None or row.token_revoked_at is not None:
        raise RotationRefused(401, "token_revoked")
    actor = f"agent:{agent_id}"
    ttl = timedelta(days=read_settings(settings).agent_token_ttl_days)
    token = new_agent_token(AgentTokenKind.AGENT)
    digest, expires = token_hash(token), now + ttl
    via = caller.via
    if (
        via == "current"
        and row.token_hash != caller.agent.token_hash
        and row.prev_token_hash == caller.agent.token_hash
        and row.prev_token_expires_at is None
    ):  # revision 2: rotated by a concurrent call while this one waited
        via = "previous"
    if via == "previous":
        if row.prev_token_expires_at is not None:  # the new token was used: reuse
            agents.revoke(agent_id, now)
            audit.alert(
                "token_reuse", actor, "agent.token_reuse", actor, {"via": "rotate"}
            )
            raise RotationRefused(401, "token_revoked")
        agents.replace_unused_token(agent_id, digest, now, expires)  # lost response
        audit.audit(actor, "agent.token_rotate", actor, {"retry": True})
        _new_ip_alert(audit, actor, ip_last_seen, now)
        return Rotated(token, now, expires)
    last = row.last_rotation_at
    if (
        last is not None
        and row.prev_token_expires_at is not None
        and now - last < ONCE_PER
    ):
        wait = math.ceil((last + ONCE_PER - now).total_seconds())
        raise RotationRefused(429, "rate_limited", {"Retry-After": str(max(1, wait))})
    opens = window_opens(row.token_issued_at, row.token_expires_at)
    if now < opens:
        audit.alert(
            "rotation_outside_window",
            actor,
            "alert.rotation_outside_window",
            actor,
            {"window_opens": opens.isoformat()},
        )
        raise RotationRefused(403, "forbidden")
    agents.rotate(agent_id, digest, now, expires)
    audit.audit(actor, "agent.token_rotate", actor, {"retry": False})
    _new_ip_alert(audit, actor, ip_last_seen, now)
    return Rotated(token, now, expires)


def _new_ip_alert(
    audit: AuditSink, actor: str, ip_last_seen: datetime | None, now: datetime
) -> None:
    """TS §3.2 L190: a rotation from an IP not seen for 7 days (or never)."""
    if ip_last_seen is None or now - ip_last_seen > NEW_IP_AFTER:
        audit.alert(
            "rotation_new_ip",
            actor,
            "alert.rotation_new_ip",
            actor,
            {
                "ip_last_seen": None
                if ip_last_seen is None
                else ip_last_seen.isoformat()
            },
        )
