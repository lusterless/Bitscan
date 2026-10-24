"""Enrolment tokens (TS §3.2 L181, §6.2 L1084, L1116, §8.4 L1290; REQ-063,
REQ-067; #68, #71; plan work/plans/TASK-067.md).

An admin with a TOTP-verified session creates a bse_ token: max_uses 1–10,000
(default 1), an expiry (default 24 h, at most 720 h), optional allowed_cidrs
(None = any source) and auto_approve (default off). The token is returned
once; only its SHA-256 hash is stored. Delete revokes it and keeps the row.
Every create and revoke writes one audit entry; a create with auto_approve
or more than 100 uses writes that entry as an enrolment_token_risky alert
instead (one entry per event, #71).
"""

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.enrolment import EnrolmentTokenRow

MAX_CIDRS: Final = 64
RISKY_USES: Final = 100  # more than this alerts (TS §3.2 L181)


class TokenStore(Protocol):  # repositories.enrolment.EnrolmentRepo
    def insert_token(
        self,
        *,
        token_hash: str,
        max_uses: int,
        auto_approve: bool,
        allowed_cidrs: list[str] | None,
        expires_at: datetime,
        created_by: int,
        now: datetime,
    ) -> int: ...

    def revoke_active_token(self, token_id: int, now: datetime) -> bool: ...

    def get_token(self, token_id: int) -> EnrolmentTokenRow | None: ...

    def token_page(
        self, limit: int, after_id: int | None
    ) -> list[EnrolmentTokenRow]: ...


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


class InvalidCidrs(Exception):
    """allowed_cidrs is empty, too long, or holds a non-network value."""


@dataclass(frozen=True)
class CreatedToken:
    token: str  # shown once, never stored
    row: EnrolmentTokenRow


def check_cidrs(cidrs: Sequence[str] | None) -> list[str] | None:
    """Network addresses only (a CIDR column refuses host bits), 1–64 of them;
    returned in PostgreSQL's canonical text form. An IPv6 scope id (fe80::%eth0)
    is refused: Python accepts it, PostgreSQL does not."""
    if cidrs is None:
        return None
    if not 1 <= len(cidrs) <= MAX_CIDRS or any("%" in c for c in cidrs):
        raise InvalidCidrs
    try:
        return [str(ipaddress.ip_network(c, strict=True)) for c in cidrs]
    except ValueError:
        raise InvalidCidrs from None


def create_token(
    store: TokenStore,
    audit: AuditSink,
    *,
    admin_id: int,
    max_uses: int,
    expires_in_hours: int,
    allowed_cidrs: Sequence[str] | None,
    auto_approve: bool,
    now: datetime,
) -> CreatedToken:
    cidrs = check_cidrs(allowed_cidrs)  # before anything is written
    token = new_agent_token(AgentTokenKind.ENROLMENT)
    token_id = store.insert_token(
        token_hash=token_hash(token),
        max_uses=max_uses,
        auto_approve=auto_approve,
        allowed_cidrs=cidrs,
        expires_at=now + timedelta(hours=expires_in_hours),
        created_by=admin_id,
        now=now,
    )
    row = store.get_token(token_id)
    if row is None:
        raise RuntimeError("the new enrolment token row is missing")
    actor, target = f"user:{admin_id}", f"enrollment_token:{token_id}"
    detail: dict[str, object] = {
        "max_uses": max_uses,
        "auto_approve": auto_approve,
        "allowed_cidrs": cidrs,
        "expires_at": row.expires_at.isoformat(),
    }
    over = max_uses > RISKY_USES
    if auto_approve or over:
        risky = {
            **detail,
            "risky": {"auto_approve": auto_approve, "over_100_uses": over},
        }
        audit.alert(
            "enrolment_token_risky", actor, "enrollment_token.create", target, risky
        )
    else:
        audit.audit(actor, "enrollment_token.create", target, detail)
    return CreatedToken(token, row)


def revoke_token(
    store: TokenStore, audit: AuditSink, *, admin_id: int, token_id: int, now: datetime
) -> bool:
    """False if there is no such token. A token already revoked keeps its
    revoked_at and writes no second entry; of two concurrent revokes only the
    one whose conditional update changed the row writes it."""
    if store.get_token(token_id) is None:
        return False
    if store.revoke_active_token(token_id, now):
        audit.audit(
            f"user:{admin_id}",
            "enrollment_token.revoke",
            f"enrollment_token:{token_id}",
            {},
        )
    return True
