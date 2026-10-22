import json
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fastapi import FastAPI, Request, Response
from fastapi.telemetry import TelemetryConfig
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bitscan_manager import __version__
from bitscan_manager.api import health, problems
from bitscan_manager.api.problems import ABOUT_BLANK, PROBLEM_JSON, problem_body
from bitscan_manager.api.request_log import RequestLog
from bitscan_manager.api.user import PROBLEM_REF, build_user_router
from bitscan_manager.auth.vault import VaultUnavailable
from bitscan_manager.db.pool import DatabaseUnavailable
from bitscan_manager.runtime import Lifecycle, Runtime

MIB: Final = 1_048_576  # "MB" in TS §6.3 means MiB (#57).

# TS §6.3 size limits: the largest request-body cap a route of each class may
# register. inventory caps the gzip body as sent; its 64 MiB decompressed limit
# belongs to the decoder. result_batch is 1.5 MiB after decompression, so the
# result route must also apply it to the decoded size.
BODY_CAP_CLASSES: Final[Mapping[str, int]] = {
    "json": MIB,
    "result_batch": 3 * MIB // 2,
    "bit": 5 * MIB,
    "inventory": 10 * MIB,
}

# (path, class, bytes) for routes that need more than the json cap.
ROUTE_BODY_CAPS: list[tuple[str, str, int]] = []

SECURITY_HEADERS: Final[tuple[tuple[bytes, bytes], ...]] = (
    (b"strict-transport-security", b"max-age=31536000"),
    (
        b"content-security-policy",
        b"default-src 'self'; frame-ancestors 'none'; object-src 'none'; "
        b"base-uri 'none'; form-action 'self'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)
_REPLACED: Final = frozenset(name for name, _ in SECURITY_HEADERS)

# Every FastAPI telemetry signal off, so no FASTAPI_OTEL_* or OTEL_* variable
# can switch export on (TS §8.4 names only logs and metrics).
TELEMETRY_OFF: Final[TelemetryConfig] = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}


def _route_caps() -> dict[str, int]:
    caps: dict[str, int] = {}
    for path, cap_class, limit in ROUTE_BODY_CAPS:
        if path in caps:
            raise ValueError(f"body cap for {path} registered twice")
        maximum = BODY_CAP_CLASSES.get(cap_class)
        if maximum is None:
            raise ValueError(f"unknown body cap class {cap_class!r} for {path}")
        if not 0 < limit <= maximum:
            raise ValueError(f"body cap for {path} is outside 1..{maximum} bytes")
        caps[path] = limit
    return caps


class SecurityHeaders:
    """Sets the TS §6.3 headers exactly once on every response, 500s included."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in _REPLACED
                    and not k.lower().startswith(b"access-control-allow-")
                ]
                message["headers"] = kept + list(SECURITY_HEADERS)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimit:
    """Refuses bodies over the cap with 413 before the app sees any of them."""

    def __init__(self, app: ASGIApp, route_caps: Mapping[str, int]) -> None:
        self.app = app
        self.route_caps = route_caps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cap = self.route_caps.get(scope["path"], BODY_CAP_CLASSES["json"])
        for name, value in scope["headers"]:
            if name == b"content-length" and value.isdigit() and int(value) > cap:
                await self._too_large(scope, send)
                return

        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return  # client went away before the body was complete
            body: bytes = message.get("body", b"")
            total += len(body)
            if total > cap:
                await self._too_large(scope, send)
                return
            chunks.append(body)
            more = message.get("more_body", False)

        whole = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": whole, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(scope: Scope, send: Send) -> None:
        body = problem_body(
            413, "too_large", "The request body exceeds the size limit.", scope["path"]
        )
        headers = [
            (b"content-type", PROBLEM_JSON.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class BitscanApp(FastAPI):
    """FastAPI with the header and size layers outside its error middleware."""

    route_caps: Mapping[str, int] = MappingProxyType({})

    def build_middleware_stack(self) -> ASGIApp:
        inner = super().build_middleware_stack()
        return RequestLog(SecurityHeaders(BodyLimit(inner, self.route_caps)))


def _lifespan(
    lifecycle: Lifecycle,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await lifecycle.start()
        try:
            yield
        finally:
            await lifecycle.stop()

    return lifespan


def create_app(runtime: Runtime | None = None) -> FastAPI:
    """runtime is None for the OpenAPI export and tests that need no
    database; routes that need it then answer 503 (get_runtime)."""
    # No docs or schema routes: every call needs a bearer token (TS §2.3) and
    # TS §6.2 lists no such route. No CORS middleware (TS §6.3).
    lifecycle = runtime.lifecycle if runtime is not None else None
    app = BitscanApp(
        title="Bitscan",
        version=__version__,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        telemetry=TELEMETRY_OFF,
        lifespan=_lifespan(lifecycle) if lifecycle is not None else None,
    )
    app.route_caps = _route_caps()
    if runtime is not None:
        app.state.runtime = runtime
    problems.install(app)
    # A database or vault outage is a 503, never a 500 or a failed check.
    app.add_exception_handler(DatabaseUnavailable, _unavailable("database"))
    app.add_exception_handler(VaultUnavailable, _unavailable("vault"))
    app.include_router(health.router)  # outside /api/v1, no token (#5)
    app.include_router(build_user_router())
    app.openapi = _problem_openapi(app.openapi)  # type: ignore[method-assign]
    return app


def _unavailable(what: str) -> Callable[[Request, Exception], Awaitable[Response]]:
    async def handler(request: Request, exc: Exception) -> Response:
        detail = f"The {what} is unavailable."
        return problems.problem_response(
            request, problems.Problem(503, ABOUT_BLANK, detail)
        )

    return handler


PROBLEM_SCHEMA: Final = {
    "type": "object",
    "required": ["type", "title", "status", "detail", "instance"],
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
    },
    "additionalProperties": False,
}


def _problem_openapi(
    build: Callable[[], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    """The document says what the app does (#48): no 422 or validation-error
    schemas; a problem+json 400 on every operation that takes input; every
    error response documented as problem+json."""

    def openapi() -> dict[str, Any]:
        doc = build()
        schemas = doc.setdefault("components", {}).setdefault("schemas", {})
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        schemas["Problem"] = PROBLEM_SCHEMA
        for item in doc.get("paths", {}).values():
            for op in item.values():
                op["responses"].pop("422", None)
                for status, response in op["responses"].items():
                    if int(status) >= 400 and "content" not in response:
                        response["content"] = {
                            "application/problem+json": {"schema": PROBLEM_REF}
                        }
                if op.get("parameters") or op.get("requestBody"):
                    op["responses"]["400"] = {
                        "description": "Bad Request",
                        "content": {
                            "application/problem+json": {"schema": PROBLEM_REF}
                        },
                    }
        return doc

    return openapi


def openapi_document() -> dict[str, Any]:
    return create_app().openapi()


def write_openapi(path: Path) -> None:
    text = json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m bitscan_manager.app <output.json>", file=sys.stderr)
        return 2
    write_openapi(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
