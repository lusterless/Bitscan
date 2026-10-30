"""CRUD /api/v1/scan-schedules (operator, `bsu_` or `bsk_`; TS §6.2 L1124,
L1084, §6.3 L1133–L1138, §4.4 L557, §5.2 L846–L857; REQ-212, REQ-224; open
questions #48, #122 (h), (i), #128 (d), (i)).

The handlers only validate, authorise and call services
(services.scheduler.schedules_admin). A schedule holds a policy, a target, a
cron and a time zone, never command text: any other body key is 400, and
`policy_id` cannot be changed (make a new schedule). Every role check is
operator, GET included; any operator may change any schedule. Every problem
detail is fixed text naming the field, never the value.
"""

from collections.abc import Callable
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

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
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, Tx, get_runtime
from bitscan_manager.services.jobs.queue import PolicyNotFound
from bitscan_manager.services.jobs.targets import InvalidTarget
from bitscan_manager.services.scheduler import schedules_admin as service
from bitscan_manager.services.scheduler.cron import InvalidSchedule

router = APIRouter(prefix="/scan-schedules", tags=["scan-schedules"])
OPERATOR = Annotated[Principal, Depends(require_role("operator"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
PAGE = Annotated[PageParams, Depends(page_params)]
# Digits only, so "+1", "1.0" and "1_0" are 400.
SCHEDULE_ID = Annotated[str, Path(pattern="^[0-9]{1,20}$")]
SCOPE: Final = "scan_schedules"
_BASE: Final = (401, 403, 429, 503)
_BIGINT_MAX: Final = 2**63 - 1
_JSON_SAFE_MAX: Final = 2**53 - 1
_INVALID = (service.InvalidField, InvalidTarget, InvalidSchedule)


class CreateSchedule(BaseModel):
    """#122 (h): `target` is exactly one of {"agents": [...]}, {"tags": [...]}
    or {"all": true}; `cron` is five-field crontab(5)."""

    model_config = ConfigDict(extra="forbid")
    name: StrictStr
    policy_id: Annotated[StrictInt, Field(ge=1, le=_JSON_SAFE_MAX)]
    target: dict[str, Any]
    cron: StrictStr
    timezone: StrictStr = "UTC"
    enabled: StrictBool = True


class PatchSchedule(BaseModel):
    """Any non-empty subset; `policy_id` is not accepted."""

    model_config = ConfigDict(extra="forbid")
    name: StrictStr | None = None
    target: dict[str, Any] | None = None
    cron: StrictStr | None = None
    timezone: StrictStr | None = None
    enabled: StrictBool | None = None


class ScheduleItem(BaseModel):
    schedule_id: int
    name: str
    policy_id: int
    target: dict[str, Any]
    cron: str
    timezone: str
    enabled: bool
    last_run_at: UtcDatetime | None
    next_run_at: UtcDatetime | None
    created_by: int


def _item(row: object) -> ScheduleItem:
    return ScheduleItem.model_validate(row, from_attributes=True)


def _not_found() -> Problem:
    return Problem(404, "not_found", "No such scan schedule.")


def _schedule_id(value: str) -> int:
    number = int(value)  # the path pattern allows ASCII digits only
    if not 1 <= number <= _BIGINT_MAX:
        raise _not_found()  # an integer no schedule_id can hold
    return number


def _after(cursor: str | None) -> int | None:
    """The previous page's last schedule_id, checked before PostgreSQL casts
    it (builder checklist 1)."""
    if cursor is None:
        return None
    key = decode_cursor(SCOPE, cursor)
    if type(key) is int and 1 <= key <= _BIGINT_MAX:
        return key
    raise Problem(400, "invalid_request", "Invalid request: query.cursor")


def _problem(exc: Exception) -> Problem:
    if isinstance(exc, _INVALID):
        return Problem(400, "invalid_request", str(exc))
    if isinstance(exc, PolicyNotFound):
        return Problem(404, "not_found", "No such policy.")
    if isinstance(exc, service.ScheduleConflict):
        return Problem(409, "conflict", "The policy is deleted.")
    return _not_found()  # ScheduleNotFound


_REFUSALS = (
    *_INVALID,
    PolicyNotFound,
    service.ScheduleConflict,
    service.ScheduleNotFound,
)


def _run[T](runtime: Runtime, change: Callable[[Tx], T]) -> T:
    """Runs change(tx) in one transaction (an audited change wakes the sink
    on commit); a refusal rolls it back and becomes its problem."""
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            result = change(tx)
    except _REFUSALS as exc:
        failure = _problem(exc)
    if failure is not None:
        raise failure
    return result


@router.post("", status_code=201, responses=problem_responses((*_BASE, 404, 409, 413)))
def create_schedule(
    body: CreateSchedule, principal: OPERATOR, runtime: RUNTIME
) -> ScheduleItem:
    """Create a scan schedule; `next_run_at` is its next fire after now."""

    def change(tx: Tx) -> object:
        return service.create(
            tx,
            name=body.name,
            policy_id=body.policy_id,
            target=body.target,
            cron=body.cron,
            timezone=body.timezone,
            enabled=body.enabled,
            user_id=principal.user_id,
            now=runtime.clock.now(),
        )

    return _item(_run(runtime, change))


@router.get("", responses=problem_responses(_BASE))
def list_schedules(
    principal: OPERATOR, runtime: RUNTIME, page: PAGE
) -> Page[ScheduleItem]:
    after = _after(page.cursor)
    with runtime.db.transaction() as tx:
        rows = service.list_page(tx, limit=page.limit + 1, after_id=after)
    items = [_item(r) for r in rows]
    return page_of(items, page.limit, SCOPE, lambda s: s.schedule_id)


@router.get("/{id}", responses=problem_responses((*_BASE, 404)))
def get_schedule(
    id: SCHEDULE_ID, principal: OPERATOR, runtime: RUNTIME
) -> ScheduleItem:
    schedule_id = _schedule_id(id)
    return _item(_run(runtime, lambda tx: service.get(tx, schedule_id)))


@router.patch("/{id}", responses=problem_responses((*_BASE, 404, 409, 413)))
def patch_schedule(
    id: SCHEDULE_ID, body: PatchSchedule, principal: OPERATOR, runtime: RUNTIME
) -> ScheduleItem:
    """Change any non-empty subset of name, target, cron, timezone, enabled."""
    schedule_id = _schedule_id(id)
    changes = {key: getattr(body, key) for key in body.model_fields_set}

    def change(tx: Tx) -> object:
        return service.update(
            tx,
            schedule_id,
            changes=changes,
            user_id=principal.user_id,
            now=runtime.clock.now(),
        )

    return _item(_run(runtime, change))


@router.delete("/{id}", status_code=204, responses=problem_responses((*_BASE, 404)))
def delete_schedule(id: SCHEDULE_ID, principal: OPERATOR, runtime: RUNTIME) -> Response:
    """Delete a scan schedule; the scans it started keep their rows."""
    schedule_id = _schedule_id(id)
    _run(runtime, lambda tx: service.delete(tx, schedule_id, user_id=principal.user_id))
    return Response(status_code=204)
