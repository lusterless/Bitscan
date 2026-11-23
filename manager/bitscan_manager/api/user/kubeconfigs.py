"""/api/v1/kubeconfigs (TS §3.8, §6.2; owner decision 2026-11-23).

Listing is admin. Upload, replace and delete are sensitive: they need an admin
TOTP-verified session, refuse API tokens and are refused during a long
audit-sink outage. No response ever holds the content or its ciphertext; a
refusal names the broken rule only. The content is encrypted with the vault
before the transaction starts, so a vault outage (503) changes nothing.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

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
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.kubeconfigs import KubeconfigRepo, KubeconfigRow
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services import kubeconfigs as service
from bitscan_manager.services.users import TxAudit

router = APIRouter(prefix="/kubeconfigs", tags=["kubeconfigs"])
SCOPE = "kubeconfigs"
ADMIN_TOTP = Annotated[Principal, Depends(require_totp_session())]
ADMIN = Annotated[Principal, Depends(require_role("admin"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_BASE = (401, 403, 429, 503)
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class KubeconfigUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(pattern=NAME_PATTERN)
    description: StrictStr = Field(default="", max_length=1000)
    content: StrictStr = Field(min_length=1, max_length=service.MAX_BYTES)


class KubeconfigReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: StrictStr | None = Field(default=None, max_length=1000)
    content: StrictStr = Field(min_length=1, max_length=service.MAX_BYTES)


class KubeconfigItem(BaseModel):
    kubeconfig_id: int
    name: str
    description: str
    cluster_name: str
    server: str
    created_by: int
    created_at: UtcDatetime
    replaced_at: UtcDatetime | None
    deleted_at: UtcDatetime | None


def _item(row: KubeconfigRow) -> KubeconfigItem:
    return KubeconfigItem(
        kubeconfig_id=row.kubeconfig_id,
        name=row.name,
        description=row.description,
        cluster_name=row.cluster_name,
        server=row.server,
        created_by=row.created_by,
        created_at=row.created_at,
        replaced_at=row.replaced_at,
        deleted_at=row.deleted_at,
    )


@contextmanager
def _stores(runtime: Runtime) -> Iterator[tuple[KubeconfigRepo, TxAudit]]:
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        yield KubeconfigRepo(tx.conn), TxAudit(PgAuditRepo(tx.conn), tx.on_commit)


def _checked(content: str) -> service.Checked:
    try:
        return service.check(content)
    except service.KubeconfigInvalid as exc:
        raise Problem(
            422, "invalid_kubeconfig", f"The kubeconfig is refused: {exc}"
        ) from None


@router.get("", responses=problem_responses(_BASE))
def list_kubeconfigs(
    principal: ADMIN,
    runtime: RUNTIME,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[KubeconfigItem]:
    """Every kubeconfig, deleted ones included (deleted_at set), so old scans
    can still name theirs."""
    after = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with _stores(runtime) as (repo, _):
        rows = repo.page(page.limit + 1, after)
    return page_of(
        [_item(r) for r in rows], page.limit, SCOPE, lambda k: k.kubeconfig_id
    )


@router.get("/{kubeconfig_id}", responses=problem_responses((*_BASE, 404)))
def get_kubeconfig(
    kubeconfig_id: int, principal: ADMIN, runtime: RUNTIME
) -> KubeconfigItem:
    with _stores(runtime) as (repo, _):
        row = repo.get(kubeconfig_id)
    if row is None:
        raise Problem(404, "not_found", "No such kubeconfig.")
    return _item(row)


@router.post("", status_code=201, responses=problem_responses((*_BASE, 409, 422)))
def upload_kubeconfig(
    body: KubeconfigUpload, principal: ADMIN_TOTP, runtime: RUNTIME
) -> KubeconfigItem:
    checked = _checked(body.content)
    content_enc = runtime.totp_cipher.encrypt(body.content.encode("utf-8"))
    failure: Problem | None = None
    try:
        with _stores(runtime) as (repo, audit):
            new_id = service.create(
                repo,
                audit,
                name=body.name,
                description=body.description,
                checked=checked,
                content_enc=content_enc,
                admin_id=principal.user_id,
                now=runtime.clock.now(),
            )
            row = repo.get(new_id)
    except service.NameTaken:
        failure = Problem(409, "conflict", "A kubeconfig with this name exists.")
    if failure is not None:
        raise failure
    if row is None:  # written in the same transaction; cannot be missing
        raise Problem(404, "not_found", "No such kubeconfig.")
    return _item(row)


@router.put("/{kubeconfig_id}", responses=problem_responses((*_BASE, 404, 422)))
def replace_kubeconfig(
    kubeconfig_id: int, body: KubeconfigReplace, principal: ADMIN_TOTP, runtime: RUNTIME
) -> KubeconfigItem:
    checked = _checked(body.content)
    content_enc = runtime.totp_cipher.encrypt(body.content.encode("utf-8"))
    failure: Problem | None = None
    try:
        with _stores(runtime) as (repo, audit):
            service.replace(
                repo,
                audit,
                kubeconfig_id,
                description=body.description,
                checked=checked,
                content_enc=content_enc,
                admin_id=principal.user_id,
                now=runtime.clock.now(),
            )
            row = repo.get(kubeconfig_id)
    except service.NotFound:
        failure = Problem(404, "not_found", "No such kubeconfig.")
    if failure is not None:
        raise failure
    if row is None:  # written in the same transaction; cannot be missing
        raise Problem(404, "not_found", "No such kubeconfig.")
    return _item(row)


@router.delete(
    "/{kubeconfig_id}", status_code=204, responses=problem_responses((*_BASE, 404))
)
def delete_kubeconfig(
    kubeconfig_id: int, principal: ADMIN_TOTP, runtime: RUNTIME
) -> Response:
    failure: Problem | None = None
    try:
        with _stores(runtime) as (repo, audit):
            service.delete(
                repo,
                audit,
                kubeconfig_id,
                admin_id=principal.user_id,
                now=runtime.clock.now(),
            )
    except service.NotFound:
        failure = Problem(404, "not_found", "No such kubeconfig.")
    if failure is not None:
        raise failure
    return Response(status_code=204)
