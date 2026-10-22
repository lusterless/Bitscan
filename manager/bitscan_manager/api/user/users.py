"""/api/v1/users (TS §6.2 L1125: CRUD, delete means disable; admin, TOTP
session, refused during a long audit-sink outage; #47 (c), #48, #52, #53)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

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
from bitscan_manager.auth import login
from bitscan_manager.auth.dependencies import require_totp_session
from bitscan_manager.auth.passwords import PasswordRejected
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import UserRepo, UserRow
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services import users as service

router = APIRouter(prefix="/users", tags=["users"])
SCOPE = "users"
ADMIN = Annotated[Principal, Depends(require_totp_session())]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_BASE = (401, 403, 429, 503)  # TASK-037 refusals; 503 also for the sink gate

_RULE_STATUS = {
    service.Rule.NOT_FOUND: (404, "not_found", "No such user."),
    service.Rule.INVALID_USERNAME: (
        400,
        "invalid_request",
        "Invalid request: username",
    ),
    service.Rule.INVALID_ROLE: (400, "invalid_request", "Invalid request: role"),
    service.Rule.DUPLICATE: (409, "conflict", "The username is already taken."),
    service.Rule.LAST_ADMIN: (409, "conflict", "The last active admin must stay."),
    service.Rule.NEEDS_TOTP: (409, "conflict", "Promotion to admin needs TOTP."),
    service.Rule.SELF_RESET: (409, "conflict", "Another admin must reset your TOTP."),
}


class UserItem(BaseModel):
    user_id: int
    username: str
    role: str
    disabled: bool
    totp_enrolled: bool
    created_at: UtcDatetime


class CreateUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str  # REQ-041 rules are checked by the service (400 names the rule)
    role: Literal["viewer", "operator"] = "viewer"  # #53 (f)


class PatchUser(BaseModel):
    """One of: {role}, {disabled: false}, {totp: null}, {revoke_tokens: true}."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["viewer", "operator", "admin"] | None = None
    disabled: Literal[False] | None = None
    totp: None = None
    revoke_tokens: Literal[True] | None = None


def _item(row: UserRow) -> UserItem:
    return UserItem(
        user_id=row.user_id,
        username=row.username,
        role=row.role,
        disabled=row.disabled,
        totp_enrolled=row.totp_enrolled,
        created_at=row.created_at,
    )


@contextmanager
def _stores(
    runtime: Runtime,
) -> Iterator[tuple[UserRepo, UserTokenRepo, service.TxAudit]]:
    """One transaction for the change and its audit entry; UserRuleError and
    PasswordRejected roll it back and become problem answers."""
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            yield (
                UserRepo(tx.conn),
                UserTokenRepo(tx.conn),
                service.TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
            )
    except service.UserRuleError as exc:
        failure = Problem(*_RULE_STATUS[exc.rule])
    except PasswordRejected as exc:
        failure = Problem(400, "invalid_request", str(exc))
    if failure is not None:
        raise failure


@router.get("", responses=problem_responses(_BASE))
def list_users(
    principal: ADMIN,
    runtime: RUNTIME,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[UserItem]:
    after = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with _stores(runtime) as (users, _, _):
        rows = service.list_users(users, page.limit + 1, after)
    return page_of([_item(r) for r in rows], page.limit, SCOPE, lambda u: u.user_id)


@router.post("", status_code=201, responses=problem_responses((*_BASE, 409)))
def create_user(body: CreateUser, principal: ADMIN, runtime: RUNTIME) -> UserItem:
    with login.VERIFY_GATE, _stores(runtime) as (users, _, audit):  # Argon2id hash
        user_id = service.create_user(
            users,
            audit,
            actor=f"user:{principal.user_id}",
            username=body.username,
            password=body.password,
            role=body.role,
            now=runtime.clock.now(),
        )
        row = service.get_user(users, user_id)
    return _item(row)


@router.get("/{user_id}", responses=problem_responses((*_BASE, 404)))
def get_user(user_id: int, principal: ADMIN, runtime: RUNTIME) -> UserItem:
    with _stores(runtime) as (users, _, _):
        row = service.get_user(users, user_id)
    return _item(row)


@router.patch("/{user_id}", responses=problem_responses((*_BASE, 404, 409)))
def patch_user(
    user_id: int, body: PatchUser, principal: ADMIN, runtime: RUNTIME
) -> UserItem:
    fields = body.model_fields_set
    if len(fields) != 1:
        raise Problem(
            400, "invalid_request", "Invalid request: give exactly one change"
        )
    # model_fields_set also holds fields sent as null: only the documented
    # value counts ({totp: null} is the one where null is the value).
    documented = {
        "role": body.role is not None,
        "disabled": body.disabled is False,
        "revoke_tokens": body.revoke_tokens is True,
        "totp": True,
    }
    field = next(iter(fields))
    if not documented[field]:
        raise Problem(400, "invalid_request", f"Invalid request: body.{field}")
    actor, now = f"user:{principal.user_id}", runtime.clock.now()
    with _stores(runtime) as (users, tokens, audit):
        change: dict[str, Callable[[], None]] = {
            "role": lambda: service.change_role(
                users,
                tokens,
                audit,
                actor=actor,
                user_id=user_id,
                role=str(body.role),
                now=now,
            ),
            "disabled": lambda: service.enable_user(
                users, audit, actor=actor, user_id=user_id
            ),
            "totp": lambda: service.reset_totp(
                users,
                tokens,
                audit,
                actor=actor,
                actor_id=principal.user_id,
                user_id=user_id,
                now=now,
            ),
            "revoke_tokens": lambda: service.revoke_user_tokens(
                users, tokens, audit, actor=actor, user_id=user_id, now=now
            ),
        }
        change[field]()
        row = service.get_user(users, user_id)
    return _item(row)


@router.delete(
    "/{user_id}", status_code=204, responses=problem_responses((*_BASE, 404, 409))
)
def disable_user(user_id: int, principal: ADMIN, runtime: RUNTIME) -> Response:
    with _stores(runtime) as (users, tokens, audit):
        service.disable_user(
            users,
            tokens,
            audit,
            actor=f"user:{principal.user_id}",
            user_id=user_id,
            now=runtime.clock.now(),
        )
    return Response(status_code=204)
