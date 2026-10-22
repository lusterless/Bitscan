"""REQ-039 (1)-(4): JSON logs with request_id, no secrets (TASK-027).

Checks CHK-M2-050 to CHK-M2-055 of tests/m2/test-plan.md. TS §8.4 L1287
(structured JSON logs with request_id, agent_id, job_id; never stdout, stderr
or tokens), TS §5.3 L1052. Logs are captured at the handler the app installs
(configure_logging), not only through caplog.
"""

import io
import json
import logging
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bitscan_manager.api.request_log import configure_logging
from bitscan_manager.app import create_app

from .canary import exception_texts, new_canary, sweep

BASE_KEYS = {"time", "level", "logger", "message", "request_id", "agent_id", "job_id"}
handler_log = logging.getLogger("bitscan_manager.tests.handler")


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    stream = io.StringIO()
    configure_logging(stream, logging.DEBUG)
    yield stream
    for h in list(root.handlers):
        if h not in before[0]:
            root.removeHandler(h)
    root.setLevel(before[1])


def records(stream: io.StringIO) -> list[dict[str, Any]]:
    lines = [ln for ln in stream.getvalue().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]  # every line must parse


def make_app() -> FastAPI:
    app = create_app()

    @app.get("/t/ok")
    def ok() -> dict[str, str]:
        handler_log.info("inside handler")
        return {"ok": "yes"}

    @app.get("/t/async")
    async def async_ok() -> dict[str, str]:
        handler_log.info("inside async handler")
        return {"ok": "yes"}

    @app.post("/t/body")
    async def body(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    @app.get("/t/boom")
    def boom() -> None:
        secret_local = new_canary("local")  # noqa: F841  a local holding a secret
        raise RuntimeError(f"boom {BOOM_CANARY}")

    @app.post("/t/boom-body")
    async def boom_body(request: Request) -> None:
        await request.body()
        raise ValueError(f"bad {BOOM_CANARY}")

    @app.get("/t/third-party")
    def third_party() -> dict[str, str]:
        try:
            raise KeyError(BOOM_CANARY)
        except KeyError:
            logging.getLogger("somelib").exception("lib failed")
        return {}

    return app


BOOM_CANARY = new_canary("boom")


# ------------------------------------------------------------ CHK-M2-050


def test_every_line_is_json_with_the_three_ids(logs: io.StringIO) -> None:
    with TestClient(make_app()) as c:
        for path in ("/t/ok", "/t/async", "/no/such"):
            c.get(path)
    recs = records(logs)
    assert recs
    for r in recs:
        assert BASE_KEYS <= set(r), r
        assert r["agent_id"] is None and r["job_id"] is None
        assert datetime.fromisoformat(r["time"]).utcoffset() is not None
    access = [r for r in recs if r["logger"] == "bitscan_manager.access"]
    assert len(access) == 3


def test_request_id_is_shared_within_and_differs_between_requests(
    logs: io.StringIO,
) -> None:
    with TestClient(make_app()) as c:
        c.get("/t/ok")
        c.get("/t/async")
        c.get("/t/ok")
    recs = [r for r in records(logs) if r["request_id"] is not None]
    by_request: dict[str, list[str]] = {}
    for r in recs:
        by_request.setdefault(r["request_id"], []).append(r["logger"])
    assert len(by_request) == 3
    for loggers in by_request.values():
        assert "bitscan_manager.access" in loggers
        assert "bitscan_manager.tests.handler" in loggers  # handler line, same id


def test_request_ids_are_distinct_under_concurrency(logs: io.StringIO) -> None:
    with TestClient(make_app()) as c, ThreadPoolExecutor(10) as pool:
        list(pool.map(lambda _: c.get("/t/ok"), range(40)))
    recs = records(logs)
    access = [r for r in recs if r["logger"] == "bitscan_manager.access"]
    ids = [r["request_id"] for r in access]
    assert len(ids) == 40 and len(set(ids)) == 40
    for r in recs:
        if r["logger"] == "bitscan_manager.tests.handler":
            assert r["request_id"] in ids
    # each handler line pairs with exactly one access record
    handler_ids = [r["request_id"] for r in recs if r["logger"].endswith("handler")]
    assert sorted(handler_ids) == sorted(ids)


# ------------------------------------------------------- CHK-M2-051, -053


def test_access_record_fields_and_no_secret_anywhere(
    logs: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    """G28: Authorization, cookie, custom header, query and bodies never logged."""
    bearer, cookie, custom = (
        new_canary("bearer"),
        new_canary("cookie"),
        new_canary("hdr"),
    )
    query, json_body, raw_body = new_canary("q"), new_canary("json"), new_canary("raw")
    headers = {
        "Authorization": f"Bearer bsu_{bearer}",
        "Cookie": f"s={cookie}",
        "X-Custom": custom,
    }
    with TestClient(make_app()) as c:
        c.get("/t/ok", params={"token": query}, headers=headers)
        c.post("/t/body", json={"password": json_body}, headers=headers)
        c.post(
            "/t/body", content=raw_body.encode(), params={"q": query}, headers=headers
        )
        c.post(
            "/t/body", content=b"x" * 1_048_577, params={"q": query}, headers=headers
        )
        c.get(f"/no/such?token={query}", headers=headers)
    out = capsys.readouterr()
    canaries = [bearer, cookie, custom, query, json_body, raw_body]
    assert sweep(canaries, logs.getvalue(), out.out, out.err) == []
    access = [r for r in records(logs) if r["logger"] == "bitscan_manager.access"]
    assert [(r["method"], r["path"], r["status"]) for r in access] == [
        ("GET", "/t/ok", 200),
        ("POST", "/t/body", 200),
        ("POST", "/t/body", 200),
        ("POST", "/t/body", 413),
        ("GET", "/no/such", 404),
    ]
    for r in access:
        assert isinstance(r["duration_ms"], int | float) and r["duration_ms"] >= 0
        assert set(r) - BASE_KEYS <= {"method", "path", "status", "duration_ms"}


# ------------------------------------------------------------ CHK-M2-052


@pytest.mark.parametrize("raise_server_exceptions", [True, False])
def test_unhandled_exception_logged_by_type_without_message_locals_or_body(
    logs: io.StringIO,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    raise_server_exceptions: bool,
) -> None:
    body_canary = new_canary("body")
    caplog.set_level(logging.DEBUG)
    with TestClient(make_app(), raise_server_exceptions=raise_server_exceptions) as c:
        r1 = c.get("/t/boom")
        r2 = c.post("/t/boom-body", json={"secret": body_canary})
    assert (r1.status_code, r2.status_code) == (500, 500)
    out = capsys.readouterr()
    recs = records(logs)
    errors = [r for r in recs if r["logger"] == "bitscan_manager.error"]
    assert [e["exc_type"] for e in errors] == ["RuntimeError", "ValueError"]
    access = {
        r["request_id"]: r for r in recs if r["logger"] == "bitscan_manager.access"
    }
    for e in errors:
        assert e["level"] == "ERROR"
        assert e["request_id"] in access and access[e["request_id"]]["status"] == 500
        assert isinstance(e["stack"], list) and e["stack"]
    texts = [
        logs.getvalue(),
        out.out,
        out.err,
        caplog.text,
        *(r.getMessage() for r in caplog.records),
    ]
    assert sweep([BOOM_CANARY, body_canary, "CANARY-local-"], *texts) == []
    assert "Traceback" not in logs.getvalue()


def test_third_party_exc_info_record_has_type_not_message(
    logs: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    with TestClient(make_app()) as c:
        assert c.get("/t/third-party").status_code == 200
    recs = [r for r in records(logs) if r["logger"] == "somelib"]
    assert len(recs) == 1
    assert recs[0]["exc_type"] == "KeyError" and recs[0]["stack"]
    assert recs[0]["request_id"] is not None
    out = capsys.readouterr()
    assert sweep([BOOM_CANARY], logs.getvalue(), out.out, out.err) == []


# ------------------------------------------------------------ CHK-M2-054


def test_canary_helper_can_fail() -> None:
    c = new_canary("t")
    try:
        try:
            raise ValueError(c)
        except ValueError:
            raise RuntimeError("outer") from None
    except RuntimeError as exc:
        chained = exc
    assert any(c in t for t in exception_texts(chained))  # found via __context__
    assert sweep([c], f"log {c}", "clean") == [(c, 0)]
    assert sweep([c], b"bytes " + c.encode()) == [(c, 0)]
    try:
        ("\ud800" + c).encode("utf-8")
    except UnicodeEncodeError as exc:
        assert sweep([c], exc) != []
    assert sweep([c], "nothing", None, b"") == []


# ------------------------------------------------------------ CHK-M2-055


def test_record_outside_a_request_parses_with_null_ids(logs: io.StringIO) -> None:
    logging.getLogger("bitscan_manager.startup").warning("starting")
    (rec,) = [r for r in records(logs) if r["logger"] == "bitscan_manager.startup"]
    assert rec["request_id"] is None and rec["agent_id"] is None
    assert rec["level"] == "WARNING" and rec["message"] == "starting"


def test_caller_data_never_overrides_base_keys(logs: io.StringIO) -> None:
    logging.getLogger("x").info(
        "m", extra={"data": {"request_id": "forged", "level": "x", "k": 1}}
    )
    (rec,) = [r for r in records(logs) if r["logger"] == "x"]
    assert rec["request_id"] is None and rec["level"] == "INFO" and rec["k"] == 1


def test_configure_logging_twice_keeps_one_handler(logs: io.StringIO) -> None:
    second = io.StringIO()
    configure_logging(second, logging.INFO)
    logging.getLogger("y").warning("once")
    assert logs.getvalue().count('"once"') == 0
    assert second.getvalue().count('"once"') == 1
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_create_app_does_not_touch_global_logging() -> None:
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    create_app()
    assert (list(root.handlers), root.level) == before


def test_httpx_request_urls_are_not_logged(logs: io.StringIO) -> None:
    """The test client logs URLs through httpx at INFO; they must not appear."""
    q = new_canary("url")
    with TestClient(make_app()) as c:
        c.get("/t/ok", params={"t": q})
    assert q not in logs.getvalue()


def test_request_id_resets_after_the_request(logs: io.StringIO) -> None:
    from bitscan_manager.api.request_log import request_id_var

    with TestClient(make_app()) as c:
        c.get("/t/ok")
    assert request_id_var.get() is None
    seen: list[str | None] = []
    t = threading.Thread(target=lambda: seen.append(request_id_var.get()))
    t.start()
    t.join()
    assert seen == [None]


def test_request_id_is_reset_in_the_callers_context(logs: io.StringIO) -> None:
    """Two requests driven in one context: no id leaks out or into the next."""
    import asyncio

    from bitscan_manager.api.request_log import request_id_var

    app = make_app()

    def scope() -> dict[str, Any]:
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/t/ok",
            "raw_path": b"/t/ok",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("192.0.2.1", 1),
            "server": ("t", 443),
        }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        return None

    async def main() -> list[str | None]:
        seen = []
        for _ in range(2):
            await app(scope(), receive, send)  # type: ignore[arg-type]
            seen.append(request_id_var.get())
        return seen

    assert asyncio.run(main()) == [None, None]
    ids = [r["request_id"] for r in records(logs) if r["logger"].endswith("access")]
    assert len(ids) == 2 and len(set(ids)) == 2
