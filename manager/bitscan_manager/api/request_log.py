"""Structured JSON logs (TS §8.4; REQ-039).

Every record is one JSON line with request_id, agent_id and job_id (null when
unknown). The access record holds the method, the path without its query
string, the status and the duration: never a header, a query string or a body.
An unhandled exception is logged by type and stack frames only: never its
message, locals or the request.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO, Any, Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

access_log: Final = logging.getLogger("bitscan_manager.access")
error_log: Final = logging.getLogger("bitscan_manager.error")


class JsonFormatter(logging.Formatter):
    """Fields a caller adds go in extra={"data": {...}}."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "agent_id": agent_id_var.get(),
            "job_id": job_id_var.get(),
        }
        data = getattr(record, "data", None)
        if isinstance(data, dict):
            line.update({k: v for k, v in data.items() if k not in line})
        if record.exc_info and record.exc_info[1] is not None:
            # Third-party records: the type and frames, never the message.
            line["exc_type"] = type(record.exc_info[1]).__name__
            line["stack"] = _stack(record.exc_info[1])
        return json.dumps(line, default=str, ensure_ascii=False)


def _stack(exc: BaseException) -> list[str]:
    frames: list[str] = []
    tb = exc.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f"{code.co_filename}:{tb.tb_lineno} {code.co_name}")
        tb = tb.tb_next
    return frames


class _Handler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marks the handler configure_logging() installed."""


def configure_logging(stream: IO[str] | None = None, level: int = logging.INFO) -> None:
    """Send every record to stream (stderr by default) as JSON lines. Calling
    it again replaces the handler it installed before."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _Handler)]:
        root.removeHandler(handler)
    handler = _Handler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    # httpx logs every request URL at INFO (vault and sink calls in the
    # manager, query strings in test clients); keep only its warnings.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))


class RequestLog:
    """Outermost ASGI layer: a new request_id per request, one access record
    per response, and unhandled exceptions logged by type only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = request_id_var.set(str(uuid.uuid4()))
        started = time.perf_counter()
        status: int | None = None

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        except Exception as exc:
            # The error middleware has already answered 500. Logging here by
            # type and frames (not exc_info, which any handler would render
            # with the message) and not re-raising keeps the message out of
            # every log, the server's included.
            error_log.error(
                "unhandled exception",
                extra={"data": {"exc_type": type(exc).__name__, "stack": _stack(exc)}},
            )
            if status is None:
                raise
        finally:
            access_log.info(
                "request",
                extra={
                    "data": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
