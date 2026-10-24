"""The bsa_ dependency for every agent route except enrol (TS §6, §6.1
L1069–L1070, §6.3 L1136; REQ-062, REQ-064, REQ-065, REQ-087; #25, #59, #63,
#65 (d); plan work/plans/TASK-059.md).

Order: bearer and X-Bitscan-Machine-Id; the token check (TASK-059) in one
transaction, so a revoke or alert it writes commits before the answer; then
the {id} form (400 invalid_request unless 8-4-4-4-12 hex) and match (403
forbidden), neither counted; then 30 requests per minute per agent (429);
then the source IP is recorded (#25 (b)). Every 401 counts as a failed check
for the per-IP limit and is answered 429 once the IP is over it; a valid token
is never counted or throttled by it. Nothing here logs a header or token.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

import re2  # type: ignore[import-untyped]
from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from bitscan_manager.api.agent import AUTH_FAILURES_PER_MIN, AgentWindows
from bitscan_manager.api.agent.schemas import UUID_PATTERN
from bitscan_manager.api.peer import peer_ip, peer_key
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.request_log import agent_id_var
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.enrolment import EnrolmentRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.enrolment import (
    AgentCaller,
    AgentTokenRefused,
    check_agent_token,
)
from bitscan_manager.services.users import TxAudit

MACHINE_ID_HEADER: Final = "x-bitscan-machine-id"
_CHECKED: Final = "bitscan.agent"  # scope key: this request's checked agent
_UUID_FORM: Final = re2.compile(UUID_PATTERN)
_DETAIL: Final = {
    401: "A valid agent token is required.",
    403: "This agent token does not allow this.",
}


@dataclass(frozen=True)
class AuthenticatedAgent:
    caller: AgentCaller
    source_ip: str | None  # the TCP peer (#55 (d)); None if it is not an IP
    ip_last_seen: datetime | None  # that IP's last_seen_at before this call


def source_ip(request: Request) -> str | None:
    """The TCP peer as an IP address (api.peer: zone dropped, IPv4-mapped IPv6
    as IPv4), or None if it is not an IP."""
    return peer_ip(request)


def agent_uuid(value: str, where: str) -> UUID:
    """A path or query id on an agent route: only the hyphenated 8-4-4-4-12
    hex form, either case (decisions 2026-10-23, extending W1 ruling (3));
    the 32-hex, {…} and urn:uuid: forms uuid.UUID also takes are 400."""
    if _UUID_FORM.fullmatch(value) is None:
        raise Problem(400, "invalid_request", f"Invalid request: {where}")
    return UUID(value)


def content_coding(request: Request) -> str | None:
    """The Content-Encoding value, lowercased: codings are case-insensitive
    (RFC 9110 §8.4.1), so GZIP is gzip."""
    value = request.headers.get("content-encoding")
    return None if value is None else value.lower()


def _single(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    return values[0] if len(values) == 1 else None


def bearer_token(request: Request) -> str | None:
    value = _single(request, "authorization")
    if value is None:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def retry_after(runtime: Runtime) -> dict[str, str]:
    now = runtime.clock.now().timestamp()
    return {"Retry-After": str(max(1, math.ceil(60 - now % 60)))}


def agent_windows(request: Request) -> AgentWindows:
    """The windows create_app() built for this app."""
    windows = getattr(request.app.state, "agent_windows", None)
    if not isinstance(windows, AgentWindows):
        raise Problem(503, "about:blank", "The service is not ready.")
    return windows


def failed_check(runtime: Runtime, ip: str, type_: str = "unauthorized") -> Problem:
    """Counts one failed token check for ip (TS §6.3 L1136) and returns the
    answer: 429 once the IP is over the limit, else 401 with type_."""
    blocked = runtime.limits.failed_check_blocked(ip)
    runtime.limits.record_failed_check(ip)
    if blocked:
        return Problem(
            429, "rate_limited", "Too many failed token checks.", retry_after(runtime)
        )
    return Problem(401, type_, _DETAIL[401])


def _refused(runtime: Runtime, ip: str, refusal: AgentTokenRefused) -> Problem:
    if not refusal.counted:  # 403 pending_approval
        return Problem(403, refusal.type, "The enrolment awaits approval.")
    return failed_check(runtime, ip, refusal.type)


def authenticate_agent(
    request: Request, id: str, runtime: Annotated[Runtime, Depends(get_runtime)]
) -> AuthenticatedAgent:
    """Sync: runs in the threadpool with the database calls. Runs once per
    request: after token_first it returns that result."""
    done = request.scope.get(_CHECKED)
    if isinstance(done, AuthenticatedAgent):
        return done
    peer = source_ip(request)
    limiter_key = peer_key(request)  # keyed as on user routes (REQ-065 (3))
    raw, header = bearer_token(request), _single(request, MACHINE_ID_HEADER)
    now = runtime.clock.now()
    refusal: Problem | None = None
    last_seen: datetime | None = None
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        agents = AgentRepo(tx.conn)
        audit = TxAudit(PgAuditRepo(tx.conn), tx.on_commit)
        try:
            caller = check_agent_token(
                agents,
                EnrolmentRepo(tx.conn),
                audit,
                raw=raw,
                machine_id_header=header,
                now=now,
            )
        except AgentTokenRefused as exc:  # caught here, so its writes commit
            refusal = _refused(runtime, limiter_key, exc)
            failing = exc.agent_id
            if exc.counted and failing is not None:
                window = agent_windows(request).auth_failures
                if window.count_and_check(failing):
                    target = f"agent:{failing}"
                    audit.alert(
                        "agent_auth_failures",
                        target,
                        "alert.agent_auth_failures",
                        target,
                        {"over_per_minute": AUTH_FAILURES_PER_MIN},
                    )
                    # The hour's slot is taken only once the alert committed.
                    tx.on_commit(lambda: window.mark_fired(failing))
        else:
            if _UUID_FORM.fullmatch(id) is None:  # after the token; not counted
                refusal = Problem(400, "invalid_request", "Invalid request: path.id")
            elif id.lower() != str(caller.agent_id):
                refusal = Problem(403, "forbidden", _DETAIL[403])
            elif not runtime.limits.allow_agent(caller.agent_id):
                refusal = Problem(
                    429, "rate_limited", "Too many requests.", retry_after(runtime)
                )
            elif peer is not None:
                last_seen = agents.ip_last_seen(caller.agent_id, peer)
                agents.record_ip(caller.agent_id, peer, now)
    if refusal is not None:
        raise refusal
    agent = AuthenticatedAgent(caller, peer, last_seen)
    request.scope[_CHECKED] = agent
    return agent


async def token_first(request: Request) -> None:
    """For limit_first on a bsa_ route that declares a JSON body (TASK-083):
    the whole check above runs before FastAPI parses the body, so a bad token
    with any body is 401 and counted (TS §6.3 L1136); the route's own
    current_agent dependency then reuses the result."""
    await run_in_threadpool(
        authenticate_agent, request, request.path_params["id"], get_runtime(request)
    )


async def current_agent(
    agent: Annotated[AuthenticatedAgent, Depends(authenticate_agent)],
) -> AuthenticatedAgent:
    """Async, so the log context it sets is the request task's: every record
    written while the route runs, and its access record, carry the agent_id."""
    agent_id_var.set(str(agent.caller.agent_id))
    return agent


current_agent.bitscan_agent_auth = "bsa_"  # type: ignore[attr-defined]
