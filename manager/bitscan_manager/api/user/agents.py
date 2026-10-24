"""GET /api/v1/agents, /agents/{id}, /agents/{id}/packages (viewer), PUT
/agents/{id}/tags (operator), POST /agents/{id}/revoke (admin, TOTP session,
sink gate) (TS §6.2 L1108–L1113; REQ-081, REQ-082; #68, #69, #73 (c)). Lists
are {items, next_cursor}. Stored text (hostnames, package names, raw) is returned
verbatim as JSON strings; no response holds a token or a token hash.
"""

import uuid
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from bitscan_manager.api.pagination import (
    Page,
    PageParams,
    decode_cursor,
    page_of,
    page_params,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role, require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.agents import AgentListRow, AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.inventory import (
    AgentPackageRow,
    InventoryRepo,
    OsInfoRow,
    SnapshotRow,
)
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.agents import admin
from bitscan_manager.services.agents import fleet as service
from bitscan_manager.services.users import TxAudit

router = APIRouter(prefix="/agents", tags=["agents"])
VIEWER = Annotated[Principal, Depends(require_role("viewer"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
PAGE = Annotated[PageParams, Depends(page_params)]
_BASE = (401, 403, 429, 503)
SCOPE = "agents"


class AgentItem(BaseModel):
    agent_id: UUID
    hostname: str
    status: str
    agent_version: str
    os_id: str | None
    os_version_id: str | None
    os_pretty_name: str | None
    last_heartbeat_at: UtcDatetime | None
    last_inventory_at: UtcDatetime | None
    tags: list[str]
    runner_helpers: list[str]


class OsInfoItem(BaseModel):
    os_id: str | None
    os_version_id: str | None
    os_pretty_name: str | None
    kernel_release: str | None
    architecture: str | None
    cpu_count: int | None
    memory_mb: int | None
    ip_addresses: list[str]
    uptime_s: int | None
    raw: dict[str, Any]
    collected_at: UtcDatetime


class PackageLine(BaseModel):
    name: str
    version: str
    architecture: str
    status: str


class SnapshotItem(BaseModel):
    snapshot_id: int
    collected_at: UtcDatetime
    package_count: int
    added: list[PackageLine]
    removed: list[PackageLine]


class AgentDetailItem(AgentItem):
    machine_id: str
    enrolled_at: UtcDatetime
    last_seen_ip: str | None
    token_issued_at: UtcDatetime
    token_expires_at: UtcDatetime
    token_revoked_at: UtcDatetime | None
    os_info: OsInfoItem | None
    last_snapshot: SnapshotItem | None


class AgentPackageItem(BaseModel):
    name: str
    version: str
    architecture: str
    status: str
    source_name: str | None
    installed_size_kb: int | None
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime


def _list_item(r: AgentListRow) -> AgentItem:
    return AgentItem(
        agent_id=r.agent_id,
        hostname=r.hostname,
        status=r.status,
        agent_version=r.agent_version,
        os_id=r.os_id,
        os_version_id=r.os_version_id,
        os_pretty_name=r.os_pretty_name,
        last_heartbeat_at=r.last_heartbeat_at,
        last_inventory_at=r.last_inventory_at,
        tags=r.tags,
        runner_helpers=r.runner_helpers,
    )


def _os(o: OsInfoRow | None) -> OsInfoItem | None:
    if o is None:
        return None
    return OsInfoItem(**{f: getattr(o, f) for f in OsInfoItem.model_fields})


def _snapshot(s: SnapshotRow | None) -> SnapshotItem | None:
    if s is None:
        return None
    return SnapshotItem(
        snapshot_id=s.snapshot_id,
        collected_at=s.collected_at,
        package_count=s.package_count,
        added=[PackageLine(**line) for line in s.added],
        removed=[PackageLine(**line) for line in s.removed],
    )


def _package(p: AgentPackageRow) -> AgentPackageItem:
    return AgentPackageItem(**{f: getattr(p, f) for f in AgentPackageItem.model_fields})


def _agent_id(value: str) -> UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise Problem(404, "not_found", "No such agent.") from None


def _cursor(scope: str, cursor: str | None, size: int) -> list[str] | None:
    if cursor is None:
        return None
    key = decode_cursor(scope, cursor)
    if (
        not isinstance(key, list)
        or len(key) != size
        or not all(isinstance(k, str) for k in key)
    ):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    return [str(k) for k in key]


@router.get("", responses=problem_responses(_BASE))
def list_agents(principal: VIEWER, runtime: RUNTIME, page: PAGE) -> Page[AgentItem]:
    key = _cursor(SCOPE, page.cursor, 2)
    after = None if key is None else (key[0], _agent_id(key[1]))
    with runtime.db.transaction() as tx:
        rows = service.list_agents(AgentRepo(tx.conn), page.limit + 1, after)
    items = [_list_item(r) for r in rows]
    return page_of(items, page.limit, SCOPE, lambda a: [a.hostname, str(a.agent_id)])


@router.get("/{id}", responses=problem_responses((*_BASE, 404)))
def get_agent(id: str, principal: VIEWER, runtime: RUNTIME) -> AgentDetailItem:
    agent_id = _agent_id(id)
    with runtime.db.transaction() as tx:
        detail = service.agent_detail(
            AgentRepo(tx.conn), InventoryRepo(tx.conn), agent_id
        )
    if detail is None:
        raise Problem(404, "not_found", "No such agent.")
    a = detail.agent
    return AgentDetailItem(
        agent_id=a.agent_id,
        hostname=a.hostname,
        status=a.status,
        agent_version=a.agent_version,
        os_id=None if detail.os_info is None else detail.os_info.os_id,
        os_version_id=None if detail.os_info is None else detail.os_info.os_version_id,
        os_pretty_name=None
        if detail.os_info is None
        else detail.os_info.os_pretty_name,
        last_heartbeat_at=a.last_heartbeat_at,
        last_inventory_at=a.last_inventory_at,
        tags=detail.tags,
        runner_helpers=a.runner_helpers,
        machine_id=a.machine_id,
        enrolled_at=a.enrolled_at,
        last_seen_ip=a.last_seen_ip,
        token_issued_at=a.token_issued_at,
        token_expires_at=a.token_expires_at,
        token_revoked_at=a.token_revoked_at,
        os_info=_os(detail.os_info),
        last_snapshot=_snapshot(detail.last_snapshot),
    )


@router.get("/{id}/packages", responses=problem_responses((*_BASE, 404)))
def list_packages(
    id: str, principal: VIEWER, runtime: RUNTIME, page: PAGE
) -> Page[AgentPackageItem]:
    agent_id = _agent_id(id)
    scope = f"agent_packages:{agent_id}"  # a cursor is valid for its agent only
    key = _cursor(scope, page.cursor, 3)
    after = None if key is None else (key[0], key[1], key[2])
    with runtime.db.transaction() as tx:
        rows = service.agent_packages(
            AgentRepo(tx.conn), InventoryRepo(tx.conn), agent_id, page.limit + 1, after
        )
    if rows is None:
        raise Problem(404, "not_found", "No such agent.")
    items = [_package(p) for p in rows]
    return page_of(
        items, page.limit, scope, lambda p: [p.name, p.architecture, p.version]
    )


# ------------------------------------------- tags (operator) and revoke (admin)


class TagsBody(BaseModel):
    """Replaces the whole set: 0–32 distinct tags of 1–64 characters from
    A–Z, a–z, 0–9 and ._:- (#68)."""

    model_config = ConfigDict(extra="forbid")
    tags: list[StrictStr] = Field(max_length=admin.MAX_TAGS)


class TagsItem(BaseModel):
    tags: list[str]


@router.put("/{id}/tags", responses=problem_responses((*_BASE, 404)))
def put_tags(
    id: str,
    body: TagsBody,
    principal: Annotated[Principal, Depends(require_role("operator"))],
    runtime: RUNTIME,
) -> TagsItem:
    agent_id = _agent_id(id)
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            tags = admin.set_tags(
                AgentRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                agent_id=agent_id,
                tags=body.tags,
                user_id=principal.user_id,
            )
    except admin.InvalidTags:
        failure = Problem(400, "invalid_request", "Invalid request: body.tags")
    except admin.AgentNotFound:
        failure = Problem(404, "not_found", "No such agent.")
    if failure is not None:
        raise failure
    return TagsItem(tags=tags)


@router.post(
    "/{id}/revoke", status_code=204, responses=problem_responses((*_BASE, 404))
)
def revoke_agent(
    id: str,
    principal: Annotated[Principal, Depends(require_totp_session())],
    runtime: RUNTIME,
) -> Response:
    """Admin, TOTP-verified session, refused during a long audit-sink outage
    (TS §6.2 L1084, L1113). Again: 204."""
    agent_id = _agent_id(id)
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            admin.revoke_agent(
                AgentRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                agent_id=agent_id,
                user_id=principal.user_id,
                now=runtime.clock.now(),
            )
    except admin.AgentNotFound:
        failure = Problem(404, "not_found", "No such agent.")
    if failure is not None:
        raise failure
    return Response(status_code=204)
