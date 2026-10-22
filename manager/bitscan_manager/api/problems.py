"""RFC 9457 problem details for every error response (TS §6.3; #48).

Bodies have exactly type, title, status, detail and instance. type is the bare
#48 string; statuses #48 gives no value for use RFC 9457 "about:blank". No
body ever holds an exception message, a stack trace or a request value.
"""

import json
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from types import UnionType
from typing import Annotated, Any, Final, Union, get_args, get_origin

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException

PROBLEM_JSON: Final = "application/problem+json"
ABOUT_BLANK: Final = "about:blank"

# The type used when only a status is known (#48; 413 per the lead's ruling).
TYPE_BY_STATUS: Final[Mapping[int, str]] = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "too_large",
    429: "rate_limited",
}

_MAX_FIELDS: Final = 10
_MAX_FIELD_LEN: Final = 64


class Problem(Exception):
    """Raise from a route or dependency to answer with a problem body."""

    def __init__(
        self,
        status: int,
        type_: str | None = None,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status)
        self.status = status
        self.type = type_ or TYPE_BY_STATUS.get(status, ABOUT_BLANK)
        self.detail = detail or _title(status)
        self.headers = dict(headers or {})


def _title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def problem_body(status: int, type_: str, detail: str, instance: str) -> bytes:
    body = {
        "type": type_,
        "title": _title(status),
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def problem_response(
    request: Request, problem: Problem, headers: Mapping[str, str] | None = None
) -> Response:
    body = problem_body(problem.status, problem.type, problem.detail, request.url.path)
    merged = {**(headers or {}), **problem.headers}
    return Response(body, problem.status, headers=merged, media_type=PROBLEM_JSON)


def _unwrap(tp: Any) -> Any:
    """Strip Annotated and Optional so a declared model or list shows through."""
    origin = get_origin(tp)
    if origin is Annotated:
        return _unwrap(get_args(tp)[0])
    if origin in (Union, UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return _unwrap(args[0]) if len(args) == 1 else tp
    return tp


def _names(tp: Any) -> Mapping[str, Any] | None:
    """Declared names under tp: a parameter namespace or a model's fields."""
    if isinstance(tp, Mapping):
        return tp
    tp = _unwrap(tp)
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return {(f.alias or n): f.annotation for n, f in tp.model_fields.items()}
    return None


def _declared(route: object) -> dict[str, Any]:
    """Per error source, what the route declares: the body type, and the
    query, header, cookie and path parameters of it and its dependencies
    (a parameter model contributes its fields). Header names are lower case."""
    roots: dict[str, Any] = {}
    if not isinstance(route, APIRoute):
        return roots
    if route.body_field is not None:
        roots["body"] = route.body_field.field_info.annotation
    params: dict[str, dict[str, Any]] = {
        s: {} for s in ("query", "header", "cookie", "path")
    }
    pending = [route.dependant]
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        for source, fields in (
            ("query", dependant.query_params),
            ("header", dependant.header_params),
            ("cookie", dependant.cookie_params),
            ("path", dependant.path_params),
        ):
            for f in fields:
                inner = _names(f.field_info.annotation)
                params[source].update(inner if inner is not None else {f.alias: None})
    params["header"] = {k.lower(): v for k, v in params["header"].items()}
    return {**params, **roots}


def _field(loc: Sequence[Any], roots: Mapping[str, Any], error_type: str) -> str:
    """The error path with declared names and list indexes only. A key the
    client chose (a dict key, an unknown field or parameter, a header it
    sent) is never named (REQ-038)."""
    source = str(loc[0]) if loc else "request"
    parts, tp = [source], roots.get(source)
    for part in loc[1:]:
        if isinstance(part, int) and not isinstance(part, bool):
            parts.append(str(part))
            tp = _unwrap(tp)
            items = get_args(tp) if get_origin(tp) in (list, tuple, set) else ()
            tp = items[0] if items else None
            continue
        names = _names(tp)
        key = part.lower() if source == "header" and isinstance(part, str) else part
        if names is None or key not in names:
            reason = (
                "unknown field" if error_type == "extra_forbidden" else "invalid key"
            )
            return f"{'.'.join(parts)[:_MAX_FIELD_LEN]}: {reason}"
        parts.append(str(part))
        tp = names[key]
    return ".".join(parts)[:_MAX_FIELD_LEN]


async def _on_problem(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, Problem):
        raise exc
    return problem_response(request, exc)


async def _on_http(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, HTTPException):
        raise exc
    # Our own HTTPException details are fixed text; Starlette's are phrases.
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(
        request, Problem(exc.status_code, None, detail), exc.headers
    )


async def _on_validation(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Name the fields only, never the values or the validator messages.
    roots = _declared(request.scope.get("route"))
    fields = sorted(
        {_field(e.get("loc", ()), roots, str(e.get("type"))) for e in exc.errors()}
    )
    detail = "Invalid request: " + ", ".join(fields[:_MAX_FIELDS])
    return problem_response(request, Problem(400, "invalid_request", detail))


async def _on_unhandled(request: Request, exc: Exception) -> Response:
    return problem_response(
        request, Problem(500, ABOUT_BLANK, "An unexpected error occurred.")
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _on_problem)
    app.add_exception_handler(HTTPException, _on_http)
    app.add_exception_handler(RequestValidationError, _on_validation)
    app.add_exception_handler(Exception, _on_unhandled)
