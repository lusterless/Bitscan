"""Agent routes under /api/v1/agent/ (TS §6, §6.1): bsa_ tokens only, plus
bse_ on POST /agent/enroll. The wire contract is in schemas.py (TS §6.5).

Refusals on agent routes use the TS §6.5 L1190 type values where they apply,
and the #59 generic values (as #48) for statuses that list has none for.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from bitscan_manager.runtime import Clock
from bitscan_manager.services.audit.thresholds import OncePerPeriod, SlidingCount

# TS §6.5 L1190, exactly.
AGENT_PROBLEM_TYPES: Final = frozenset(
    {
        "pending_approval",
        "enrollment_rejected",
        "token_revoked",
        "token_expired",
        "machine_id_mismatch",
        "job_not_acceptable",
        "too_large",
        "rate_limited",
    }
)

# #59: 401 unauthorized (one body for every token failure), 403 forbidden
# (a foreign {id}), 400 invalid_request (malformed input), and about:blank
# for the inventory 422 and a 503 when the database is down.
AGENT_GENERIC_PROBLEM_TYPES: Final = frozenset(
    {"unauthorized", "forbidden", "invalid_request", "about:blank"}
)


@dataclass(frozen=True)
class AgentWindows:
    """The agent routes' in-memory threshold windows, built once per app by
    create_app() (one manager process; reset on restart, #65). Each is
    marked as fired only once its alert entry committed."""

    auth_failures: SlidingCount[UUID]  # #65 (d): > 20 401s/min per agent, 1 h
    enrolments: SlidingCount[int]  # #61: per token, 60 min, setting per call
    clock_skew: OncePerPeriod[UUID]  # #65 (a): once per agent per hour
    result_409: SlidingCount[UUID]  # #54 (c): > 20 per agent in 10 min, 1 h
    new_packages: SlidingCount[UUID]  # #65 (e): > 1,000 per agent in 24 h, 24 h


AUTH_FAILURES_PER_MIN: Final = 20


def build_agent_windows(clock: Clock) -> AgentWindows:
    # Imported here, not at package import: services.inventory.decode imports
    # this package (for schemas), so a module-level import of ingest would be
    # circular (TASK-084).
    from bitscan_manager.services.inventory.ingest import NEW_PACKAGES_PER_DAY
    from bitscan_manager.services.jobs.pull import FLOOD_PER_10_MIN

    return AgentWindows(
        auth_failures=SlidingCount(
            clock, timedelta(minutes=1), timedelta(hours=1), AUTH_FAILURES_PER_MIN
        ),
        enrolments=SlidingCount(clock, timedelta(hours=1), timedelta(hours=1), 50),
        clock_skew=OncePerPeriod(clock, timedelta(hours=1)),
        result_409=SlidingCount(
            clock, timedelta(minutes=10), timedelta(hours=1), FLOOD_PER_10_MIN
        ),
        new_packages=SlidingCount(
            clock, timedelta(hours=24), timedelta(hours=24), NEW_PACKAGES_PER_DAY
        ),
    )


def build_agent_router() -> APIRouter:
    """The agent route group: its own router with its own token dependency
    (TS §6 L1056); never the user dependency. Route modules (TASK-067, 072
    to 075) add one include line each."""
    from bitscan_manager.api.agent import (  # route modules import this package
        enrol,
        heartbeat,
        inventory,
        jobs,
        rotate,
    )

    router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
    router.include_router(enrol.router)
    router.include_router(heartbeat.router)
    router.include_router(jobs.router)
    router.include_router(inventory.router)
    router.include_router(rotate.router)
    return router


def documented_request_bodies() -> tuple[type[BaseModel], ...]:
    """Request bodies of agent routes that read their own body after the token
    check (no FastAPI body parameter): the app's OpenAPI hook adds them to
    components/schemas, so the document still carries the contract (REQ-060)."""
    from bitscan_manager.api.agent.schemas import (
        InventoryBody,
        ResultsRequest,
        RotateRequest,
    )

    return (ResultsRequest, InventoryBody, RotateRequest)
