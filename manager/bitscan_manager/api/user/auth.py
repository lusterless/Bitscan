"""POST /api/v1/auth/login, /auth/logout, /auth/totp/enrol and /auth/password
(TS §6.2 L1080, L1085, L1096, L1097; #47, #48, #49 (b), #53 (a), #55)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from bitscan_manager.api.attempt_limits import limit_first, per_ip_limit
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth import login as login_service
from bitscan_manager.auth import password_change, totp_enrol
from bitscan_manager.auth.dependencies import UNAUTHORIZED_DETAIL, require_session
from bitscan_manager.auth.passwords import PasswordRejected
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = Field(default=None, max_length=16)


class LoginResponse(BaseModel):
    token: str
    expires_at: UtcDatetime
    role: str
    totp_enrolled: bool
    totp_verified: bool


# 10 sign-in requests per minute per TCP peer, every attempt counted (#55 (c)),
# before the body is even read (TASK-082: the route class).
_login_limit = per_ip_limit(
    lambda runtime, ip: runtime.limits.allow_login(ip), "Too many sign-in attempts."
)
_sign_in = APIRouter(route_class=limit_first(_login_limit))


@_sign_in.post("/login", responses=problem_responses((401, 429, 503)))
def login(
    body: LoginRequest, runtime: Annotated[Runtime, Depends(get_runtime)]
) -> LoginResponse:
    try:
        result = login_service.login(
            runtime,
            username=body.username,
            password=body.password,
            totp_code=body.totp_code,
        )
    except login_service.LoginFailed:
        raise Problem(401, "unauthorized", UNAUTHORIZED_DETAIL) from None
    return LoginResponse(
        token=result.token,
        expires_at=result.expires_at,
        role=result.role,
        totp_enrolled=result.totp_enrolled,
        totp_verified=result.totp_verified,
    )


router.include_router(_sign_in)


@router.post(
    "/logout", status_code=204, responses=problem_responses((401, 403, 429, 503))
)
def logout(
    request: Request,
    principal: Annotated[Principal, Depends(require_session(allow_restricted=True))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Response:
    login_service.logout(
        runtime, user_id=principal.user_id, token_id=principal.token_id
    )
    _pending(request).drop(principal.token_id)
    return Response(status_code=204)


def _pending(request: Request) -> totp_enrol.PendingEnrolments:
    pending = getattr(request.app.state, "totp_pending", None)
    if not isinstance(pending, totp_enrol.PendingEnrolments):
        pending = totp_enrol.PendingEnrolments()
        request.app.state.totp_pending = pending
    return pending


class TotpEnrolRequest(BaseModel):
    """{} or {current_password, current_code} starts; {totp_code} confirms."""

    model_config = ConfigDict(extra="forbid")
    current_password: str | None = Field(default=None, max_length=1024)
    current_code: str | None = Field(default=None, max_length=16)
    totp_code: str | None = Field(default=None, max_length=16)


class EnrolStartResponse(BaseModel):
    secret: str
    otpauth_uri: str


@router.post("/totp/enrol", responses=problem_responses((401, 403, 409, 429, 503)))
def totp_enrol_route(
    request: Request,
    body: TotpEnrolRequest,
    principal: Annotated[Principal, Depends(require_session(allow_restricted=True))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> EnrolStartResponse | LoginResponse:
    pending = _pending(request)
    try:
        if body.totp_code is None:
            started = totp_enrol.start(
                runtime,
                pending,
                principal,
                current_password=body.current_password,
                current_code=body.current_code,
            )
            return EnrolStartResponse(
                secret=started.secret, otpauth_uri=started.otpauth_uri
            )
        if body.current_password is not None or body.current_code is not None:
            raise Problem(400, "invalid_request", "Invalid request: body")
        done = totp_enrol.confirm(runtime, pending, principal, code=body.totp_code)
    except totp_enrol.EnrolRefused:
        raise Problem(403, "forbidden", "The password or code is not valid.") from None
    except totp_enrol.NoPendingEnrolment:
        raise Problem(409, "conflict", "No TOTP enrolment is in progress.") from None
    return LoginResponse(
        token=done.token,
        expires_at=done.expires_at,
        role=done.role,
        totp_enrolled=True,
        totp_verified=True,
    )


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str  # REQ-041 rules are checked by the service (400 names the rule)


@router.post(
    "/password", status_code=204, responses=problem_responses((401, 403, 429, 503))
)
def change_password(
    body: PasswordChangeRequest,
    principal: Annotated[Principal, Depends(require_session())],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Response:
    """On success every session of the caller ends: sign in again (#53 (a))."""
    try:
        password_change.change_password(
            runtime,
            principal,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except PasswordRejected as exc:
        raise Problem(400, "invalid_request", str(exc)) from None
    except password_change.PasswordChangeRefused:
        raise Problem(403, "forbidden", "The current password is not valid.") from None
    return Response(status_code=204)
