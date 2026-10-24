"""GET /api/v1/metrics (TS §8.4 L1288–L1289; REQ-086; #70): Prometheus
text format, a user route with the normal bearer check, minimum role viewer
(a scraper uses a viewer API token). Read-only.
"""

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_PLAIN_0_0_4

from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.audit.metrics import scrape

router = APIRouter(prefix="/metrics", tags=["metrics"])
# generate_latest() writes the classic 0.0.4 text format; label it as such.
_TEXT: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": "Prometheus text exposition format",
        "content": {CONTENT_TYPE_PLAIN_0_0_4: {"schema": {"type": "string"}}},
    }
}


@router.get(
    "",
    response_class=Response,
    responses={**_TEXT, **problem_responses((401, 403, 429, 503))},
)
def metrics(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Response:
    with runtime.db.transaction() as tx:  # counts only
        body = scrape(AgentRepo(tx.conn), JobRepo(tx.conn))
    return Response(body, media_type=CONTENT_TYPE_PLAIN_0_0_4)
