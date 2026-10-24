"""Checks that run before the body is read: the per-IP attempt limits (TS
§6.3 L1136, #55 (c); TASK-082, decisions 2026-10-23 option (B)) and the bsa_
token check on agent routes with a declared JSON body (TASK-083).

FastAPI parses a JSON body before it solves any dependency, so a limit in a
dependency never sees a request whose body does not parse. A route built
from limit_first(check) runs check(request) first (awaited if it is a
coroutine), before FastAPI's own handler reads anything; the body is then
parsed, validated and documented exactly as before. A refusal is a Problem,
answered by the app's handlers (problem+json, security headers). The
body-cap middleware still runs before any route.
"""

import inspect
import math
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from bitscan_manager.api.peer import peer_key
from bitscan_manager.api.problems import Problem
from bitscan_manager.runtime import Runtime, get_runtime


def retry_after_minute(runtime: Runtime) -> dict[str, str]:
    """Whole seconds to the end of the current UTC minute (1 to 60)."""
    now = runtime.clock.now().timestamp()
    return {"Retry-After": str(max(1, math.ceil(60 - now % 60)))}


def per_ip_limit(
    allow: Callable[[Runtime, str], bool], detail: str
) -> Callable[[Request], None]:
    """A check that counts every attempt for the peer and refuses with 429."""

    def check(request: Request) -> None:
        runtime = get_runtime(request)
        if not allow(runtime, peer_key(request)):
            raise Problem(429, "rate_limited", detail, retry_after_minute(runtime))

    return check


def limit_first(
    check: Callable[[Request], Awaitable[None] | None],
) -> type[APIRoute]:
    class LimitFirstRoute(APIRoute):
        def get_route_handler(
            self,
        ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def limited(request: Request) -> Response:
                pending = check(request)  # before FastAPI reads or parses the body
                if inspect.isawaitable(pending):
                    await pending
                return await handler(request)

            return limited

    return LimitFirstRoute
