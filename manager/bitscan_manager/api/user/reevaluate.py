"""POST /api/v1/scans/{id}/reevaluate (admin, TOTP-verified session, sink
gate; TS §6.2 L1086, L1125, §4.5 L603, §5.3 L1053; REQ-270, REQ-273; open
question #147; plan work/plans/TASK-232.md §6).

A sensitive action: API tokens are refused, and so is every call during a
long audit-sink outage. The route declares no body, so none is read (#147
(b)). It imports no repository (REQ-270 (5)). The auth dependency runs before
the handler, so a refused call does no database work and writes nothing.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from bitscan_manager.api.agent.schemas import UUID_PATTERN
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.evaluator.reevaluate import (
    PolicyDeleted,
    ScanNotFound,
    reevaluate_scan,
)

router = APIRouter(tags=["scans"])
TOTP_ADMIN = Annotated[Principal, Depends(require_totp_session())]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
# The hyphenated 8-4-4-4-12 form only (builder checklist 5); anything else 400.
SCAN_ID = Annotated[str, Path(pattern=UUID_PATTERN)]
_BASE: Final = (401, 403, 429, 503)


class ReevalItem(BaseModel):
    """#147 (c): M8's ReevalResult."""

    scan_id: UUID
    policy_id: int
    scan_policy_version: int  # the version the scan was built from
    policy_version: int  # the version whose definitions were used
    rows_added: int
    not_in_version: int


@router.post("/scans/{id}/reevaluate", responses=problem_responses((*_BASE, 404, 409)))
def reevaluate(id: SCAN_ID, principal: TOTP_ADMIN, runtime: RUNTIME) -> ReevalItem:
    """Re-evaluate the scan's results against its policy's current version,
    in the request (#147 (a)); adds rows only (TS §4.5 L603)."""
    failure: Problem | None = None
    try:
        # M8's service, unchanged: it writes the one `scan.reevaluate` audit
        # entry (no alert, #148) and runs wake only after its commit.
        done = reevaluate_scan(
            runtime.db,
            UUID(id),
            user_id=principal.user_id,
            wake=runtime.sink_gate.wake,
        )
    except ScanNotFound:
        failure = Problem(404, "not_found", "No such scan.")
    except PolicyDeleted:
        failure = Problem(409, "conflict", "The policy is deleted.")
    if failure is not None:  # raised outside the except: no chained cause
        raise failure
    return ReevalItem(
        scan_id=done.scan_id,
        policy_id=done.policy_id,
        scan_policy_version=done.scan_policy_version,
        policy_version=done.policy_version,
        rows_added=done.rows_added,
        not_in_version=done.not_in_version,
    )
