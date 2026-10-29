"""User routes: one router under /api/v1 that accepts only bsu_ and bsk_
tokens (TS §6, §6.2). Refusals are documented as problem+json (#48)."""

from collections.abc import Iterable
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter

PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}


def problem_responses(statuses: Iterable[int]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for a route's refusals, all application/problem+json."""
    return {
        status: {
            "description": HTTPStatus(status).phrase,
            "content": {"application/problem+json": {"schema": PROBLEM_REF}},
        }
        for status in statuses
    }


def build_user_router() -> APIRouter:
    # Imported here: the route modules import problem_responses from this package.
    from bitscan_manager.api.user import (
        agents,
        api_tokens,
        audit_log,
        auth,
        enrolment,
        imports,
        metrics,
        packages,
        policies,
        policy_import,
        rebuild,
        settings,
        users,
    )

    router = APIRouter(prefix="/api/v1")
    router.include_router(auth.router)
    router.include_router(api_tokens.router)
    router.include_router(users.router)
    router.include_router(settings.router)
    router.include_router(enrolment.router)
    router.include_router(agents.router)
    router.include_router(packages.router)
    router.include_router(audit_log.router)
    router.include_router(metrics.router)
    router.include_router(policies.router)
    router.include_router(policy_import.router)
    router.include_router(rebuild.router)
    router.include_router(imports.router)
    return router
