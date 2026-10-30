"""POST /api/v1/scans and POST /api/v1/scans/{id}/cancel (operator, `bsu_` or
`bsk_`; TS §6.2 L1119, L1122, L1084, §6.3 L1133–L1138, §6.4 L1146–L1155,
§8.4 L1290; REQ-212, REQ-220, REQ-221, REQ-222; open questions #3, #48,
#122, #123).

The handlers only validate, authorise and call services. A scan's commands
come only from the policy's active plugins (services.jobs.queue): the body
is `{policy_id, target}` and any other key is 400. `Idempotency-Key` is
honoured per user and key (#123). Every problem detail is fixed text that
never echoes the body or a header.
"""

import logging
import threading
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.api.user.idempotency import (
    IdempotencyStore,
    InvalidKey,
    KeyReused,
)
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.auth.tokens import TokenKind
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.jobs import build, queue
from bitscan_manager.services.jobs.cancel import ScanNotFound, cancel_scan
from bitscan_manager.services.jobs.scan_state import ScanState
from bitscan_manager.services.jobs.targets import (
    InvalidTarget,
    Target,
    parse_target,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/scans", tags=["scans"])
OPERATOR = Annotated[Principal, Depends(require_role("operator"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
# The hyphenated 8-4-4-4-12 form only; anything else is 400 (REQ-221 (4)).
SCAN_ID = Annotated[
    str,
    Path(
        pattern="^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        "-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    ),
]
IDEMPOTENCY_KEY = Annotated[
    str | None,
    Header(alias="Idempotency-Key", description="1 to 255 printable ASCII characters"),
]
_BASE: Final = (401, 403, 429, 503)
_JSON_SAFE_MAX: Final = 2**53 - 1
_STORE_LOCK: Final = threading.Lock()


class ScanRequest(BaseModel):
    """#122 (a), (b): `target` is exactly one of {"agents": [...]},
    {"tags": [...]} or {"all": true}."""

    model_config = ConfigDict(extra="forbid")
    policy_id: Annotated[StrictInt, Field(ge=1, le=_JSON_SAFE_MAX)]
    target: dict[str, Any]


class ScanQueuedItem(BaseModel):
    """TS §6.4 202 body."""

    scan_id: UUID
    state: Literal["queued"]
    policy_version: int
    jobs: int


class ScanCancelledItem(BaseModel):
    """#122 (g) 200 body."""

    scan_id: UUID
    state: ScanState
    cancelled_jobs: int


def _store(request: Request, runtime: Runtime) -> IdempotencyStore[ScanQueuedItem]:
    """One store per process (#123 (c)), built on first use."""
    with _STORE_LOCK:
        store = getattr(request.app.state, "scan_idempotency", None)
        if not isinstance(store, IdempotencyStore):
            store = IdempotencyStore[ScanQueuedItem](runtime.clock)
            request.app.state.scan_idempotency = store
        return store


def _queue(
    policy_id: int, target: Target, principal: Principal, runtime: Runtime
) -> ScanQueuedItem:
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            queued = queue.queue_scan(
                tx,
                policy_id=policy_id,
                target=target,
                trigger="manual",
                schedule_id=None,
                requested_by=principal.user_id,
                actor=f"user:{principal.user_id}",
                via_api_token=principal.kind is TokenKind.API,
                now=runtime.clock.now(),
            )
    except queue.PolicyNotFound:
        failure = Problem(404, "not_found", "No such policy.")
    except queue.PolicyDisabled:
        failure = Problem(409, "conflict", "The policy is disabled.")
    except queue.PolicyDeleted:
        failure = Problem(409, "conflict", "The policy is deleted.")
    except queue.PolicyHasNoPlugins:
        failure = Problem(409, "conflict", "The policy has no active plugin.")
    except queue.NoTargetAgents:
        failure = Problem(422, ABOUT_BLANK, "The target resolves to no host.")
    except build.UnstorableText as exc:  # #125 (g): logged by type only
        log.error("scan not built", extra={"data": {"exc_type": type(exc).__name__}})
        failure = Problem(500, ABOUT_BLANK, "An unexpected error occurred.")
    if failure is not None:
        raise failure
    return ScanQueuedItem(
        scan_id=queued.scan_id,
        state=queued.state,
        policy_version=queued.policy_version,
        jobs=queued.jobs,
    )


@router.post(
    "",
    status_code=202,
    responses=problem_responses((*_BASE, 404, 409, 413, 422)),
)
def create_scan(
    request: Request,
    body: ScanRequest,
    principal: OPERATOR,
    runtime: RUNTIME,
    idempotency_key: IDEMPOTENCY_KEY = None,
) -> ScanQueuedItem:
    """Queue one scan of a policy for a target (TS §6.4). With an
    `Idempotency-Key`, a repeat with the same body returns the first 202."""
    # The target is checked before the idempotency digest, so only a valid
    # body (no NaN or other value json.dumps refuses) reaches the store.
    try:
        target = parse_target(body.target)
    except InvalidTarget as exc:
        raise Problem(400, "invalid_request", str(exc)) from None
    if idempotency_key is None:
        return _queue(body.policy_id, target, principal, runtime)
    try:
        return _store(request, runtime).run(
            principal.user_id,
            idempotency_key,
            body.model_dump(mode="json"),
            lambda: _queue(body.policy_id, target, principal, runtime),
        )
    except InvalidKey:
        detail = "Invalid request: Idempotency-Key"
        raise Problem(400, "invalid_request", detail) from None
    except KeyReused:
        detail = "Idempotency-Key was used with a different request."
        raise Problem(409, "conflict", detail) from None


@router.post(
    "/{id}/cancel",
    responses=problem_responses((*_BASE, 404)),
)
def cancel(id: SCAN_ID, principal: OPERATOR, runtime: RUNTIME) -> ScanCancelledItem:
    """Cancel the scan's queued, dispatched and running jobs, manager-side
    only (TS §4.4 L581); a repeat answers `cancelled_jobs: 0`."""
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            done = cancel_scan(
                tx,
                scan_id=UUID(id),
                actor=f"user:{principal.user_id}",
                now=runtime.clock.now(),
            )
    except ScanNotFound:
        failure = Problem(404, "not_found", "No such scan.")
    if failure is not None:
        raise failure
    return ScanCancelledItem(
        scan_id=done.scan_id, state=done.state, cancelled_jobs=done.cancelled_jobs
    )
