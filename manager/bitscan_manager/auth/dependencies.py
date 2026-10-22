"""FastAPI auth dependencies for user routes (TS §6, §6.2, §6.3; REQ-044 to
REQ-047; #48; plan work/plans/TASK-037.md).

Refusals: 401 unauthorized (one body for every failed token check), or 429
rate_limited once the source IP is over the failed-check limit; 403
totp_enrolment_required, forbidden, session_required or
totp_session_required; 503 audit_sink_unavailable while the sink gate
refuses. Each factory marks the callable it returns with an AuthMarker, so
a route walk can list what every route requires.
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Request

from bitscan_manager.api.problems import Problem
from bitscan_manager.auth.principal import ROLE_ORDER, Principal, resolve
from bitscan_manager.auth.tokens import TokenKind
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.runtime import Runtime, get_runtime

log = logging.getLogger(__name__)

UNAUTHORIZED_DETAIL: Final = "A valid bearer token is required."


@dataclass(frozen=True)
class AuthMarker:
    check: str  # "role", "session" or "totp_session"
    minimum: str
    allow_restricted: bool
    sink_gate: bool
    admin_totp: bool = False  # admins need a TOTP-verified session (POST /api-tokens)


def _retry_after(runtime: Runtime) -> dict[str, str]:
    now = runtime.clock.now().timestamp()
    return {"Retry-After": str(max(1, math.ceil(60 - now % 60)))}


def _bearer(request: Request) -> str | None:
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return None
    scheme, _, token = values[0].partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def current_principal(
    request: Request, runtime: Annotated[Runtime, Depends(get_runtime)]
) -> Principal:
    ip = request.client.host if request.client is not None else "unknown"
    raw = _bearer(request)
    now = runtime.clock.now()
    principal: Principal | None = None
    with runtime.db.transaction() as tx:
        if raw is not None:
            principal = resolve(UserTokenRepo(tx.conn), raw, now)
        if principal is not None and not principal.admin_api_without_totp:
            UserTokenRepo(tx.conn).touch(principal.token_id, now)
    if principal is None:
        # Every failure counts, also those answered 429 (user decision
        # 2026-10-21); a valid token is checked first and never counted.
        blocked = runtime.limits.failed_check_blocked(ip)
        runtime.limits.record_failed_check(ip)
        log.debug("token check failed")
        if blocked:
            raise Problem(
                429,
                "rate_limited",
                "Too many failed token checks.",
                _retry_after(runtime),
            )
        raise Problem(401, "unauthorized", UNAUTHORIZED_DETAIL)
    if principal.admin_api_without_totp:
        raise Problem(
            403,
            "totp_enrolment_required",
            "Enrol TOTP before using an admin API token.",
        )
    if not runtime.limits.allow_user(principal.user_id):
        raise Problem(429, "rate_limited", "Too many requests.", _retry_after(runtime))
    log.debug(
        "token accepted",
        extra={"data": {"user_id": principal.user_id, "token_id": principal.token_id}},
    )
    return principal


def _gate(
    principal: Principal,
    runtime: Runtime,
    marker: AuthMarker,
) -> Principal:
    if principal.restricted and not marker.allow_restricted:
        raise Problem(403, "totp_enrolment_required", "Enrol TOTP to continue.")
    if marker.check == "session" and principal.kind is not TokenKind.SESSION:
        raise Problem(403, "session_required", "A web session is required.")
    if marker.check == "totp_session" and not (
        principal.kind is TokenKind.SESSION and principal.totp_verified
    ):
        raise Problem(
            403, "totp_session_required", "A TOTP-verified session is required."
        )
    if marker.admin_totp and principal.role == "admin" and not principal.totp_verified:
        raise Problem(
            403, "totp_session_required", "A TOTP-verified session is required."
        )
    if not principal.at_least(marker.minimum):
        raise Problem(403, "forbidden", "Your role does not allow this.")
    if marker.sink_gate and runtime.sink_gate.refusing():
        raise Problem(503, "audit_sink_unavailable", "The audit sink is unavailable.")
    return principal


def _factory(marker: AuthMarker) -> Callable[..., Principal]:
    if marker.minimum not in ROLE_ORDER:
        raise ValueError(f"unknown role {marker.minimum!r}")

    def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
        runtime: Annotated[Runtime, Depends(get_runtime)],
    ) -> Principal:
        return _gate(principal, runtime, marker)

    dependency.bitscan_auth = marker  # type: ignore[attr-defined]
    return dependency


def require_role(
    minimum: str, *, allow_restricted: bool = False
) -> Callable[..., Principal]:
    return _factory(AuthMarker("role", minimum, allow_restricted, False))


def require_session(
    minimum: str = "viewer", *, allow_restricted: bool = False, admin_totp: bool = False
) -> Callable[..., Principal]:
    """admin_totp: an admin caller also needs a TOTP-verified session (TS §6.2
    L1081, POST /api-tokens); it implies allow_restricted, so a restricted
    admin is told totp_session_required."""
    return _factory(
        AuthMarker(
            "session", minimum, allow_restricted or admin_totp, False, admin_totp
        )
    )


def require_totp_session(
    minimum: str = "admin", *, sink_gate: bool = True
) -> Callable[..., Principal]:
    return _factory(AuthMarker("totp_session", minimum, False, sink_gate))
