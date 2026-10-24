"""REQ-038 (1)-(3): problem details for every error (TASK-026).

Checks CHK-M2-040 to CHK-M2-042 of tests/m2/test-plan.md. Expected values:
TS §6.3 L1133 (the five keys), #48 (statuses and type values), the lead's
rulings of 2026-10-21 (413 too_large; about:blank where #48 has no value).
"""

from collections.abc import Iterator
from typing import Annotated, Any, Literal

import psycopg
import pytest
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from bitscan_manager.api.problems import Problem
from bitscan_manager.app import create_app
from bitscan_manager.runtime import Runtime, get_runtime

CANARY = "CANARY-prob-3b9e1f04c7a2d658"
KEYS = {"type", "title", "status", "detail", "instance"}
FORBIDDEN_TEXT = ("Traceback", 'File "', "SELECT", "postgresql://", "password=")


class Body(BaseModel):
    n: int
    name: str = Field(max_length=5)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int


class Mapped(BaseModel):
    m: dict[str, int]


def make_app() -> FastAPI:
    app = create_app()

    @app.post("/t/model")
    def model(body: Body) -> dict[str, int]:
        return {"n": body.n}

    @app.post("/t/strict")
    def strict(body: Strict) -> dict[str, int]:
        return {"n": body.n}

    @app.post("/t/mapped")
    def mapped(body: Mapped) -> dict[str, int]:
        return {"k": len(body.m)}

    @app.get("/t/q")
    def query(x: int, y: int = 0) -> dict[str, int]:
        return {"x": x}

    @app.get("/t/item/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    @app.get("/t/boom")
    def boom() -> None:
        raise RuntimeError(f"boom {CANARY} SELECT password=x")

    @app.get("/t/pgerr")
    def pgerr() -> None:
        raise psycopg.OperationalError(
            f"connection to postgresql://bitscan_app:{CANARY}@db/bitscan failed:"
            " SELECT 1"
        )

    @app.get("/t/problem/{code}")
    def problem(code: int) -> None:
        raise Problem(code)

    @app.get("/t/http/{code}")
    def http(code: int) -> None:
        raise HTTPException(status_code=code)

    @app.get("/t/typed")
    def typed() -> None:
        raise Problem(403, "totp_session_required")

    @app.get("/t/retry")
    def retry() -> None:
        raise Problem(429, headers={"Retry-After": "17"})

    @app.get("/t/runtime")
    def needs_runtime(rt: Runtime = Depends(get_runtime)) -> None:  # noqa: B008
        return None

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(make_app(), raise_server_exceptions=False) as c:
        yield c


AUTH = {"Authorization": f"Bearer bsu_{CANARY}", "Cookie": f"s={CANARY}"}


def check_problem(resp: Any, status: int, type_: str, path: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].split(";")[0] == "application/problem+json"
    body: dict[str, Any] = resp.json()
    assert set(body) == KEYS, body
    assert body["status"] == status
    assert body["type"] == type_
    assert body["instance"] == path
    assert isinstance(body["title"], str) and body["title"]
    assert isinstance(body["detail"], str) and body["detail"]
    for text in (CANARY, *FORBIDDEN_TEXT):
        assert text not in resp.text, text
    return body


# ------------------------------------------------------------ CHK-M2-040

CASES: list[tuple[str, str, dict[str, Any], int, str]] = [
    ("GET", "/no/such/path", {}, 404, "not_found"),
    ("GET", "/api/v1/agent/no-such-route", {}, 404, "not_found"),
    ("GET", "/api/v1/agent/enroll", {}, 405, "about:blank"),  # POST only (TASK-067)
    ("DELETE", "/t/q", {}, 405, "about:blank"),
    ("POST", "/t/model", {"content": b"{not json"}, 400, "invalid_request"),
    ("POST", "/t/model", {"json": {"name": "a"}}, 400, "invalid_request"),
    ("POST", "/t/model", {"json": {"n": "x", "name": "a"}}, 400, "invalid_request"),
    ("POST", "/t/model", {"json": [1, 2]}, 400, "invalid_request"),
    ("GET", "/t/q", {"params": {"x": "abc"}}, 400, "invalid_request"),
    ("GET", "/t/q", {}, 400, "invalid_request"),
    ("GET", "/t/item/abc", {}, 400, "invalid_request"),
    ("POST", "/t/model", {"content": b"x" * (1_048_577)}, 413, "too_large"),
    ("GET", "/t/boom", {}, 500, "about:blank"),
    ("GET", "/t/pgerr", {}, 500, "about:blank"),
    ("GET", "/t/problem/401", {}, 401, "unauthorized"),
    ("GET", "/t/problem/403", {}, 403, "forbidden"),
    ("GET", "/t/problem/404", {}, 404, "not_found"),
    ("GET", "/t/problem/409", {}, 409, "conflict"),
    ("GET", "/t/problem/429", {}, 429, "rate_limited"),
    ("GET", "/t/http/401", {}, 401, "unauthorized"),
    ("GET", "/t/http/403", {}, 403, "forbidden"),
    ("GET", "/t/http/409", {}, 409, "conflict"),
    ("GET", "/t/http/503", {}, 503, "about:blank"),
    ("GET", "/t/typed", {}, 403, "totp_session_required"),
    ("GET", "/t/runtime", {}, 503, "about:blank"),
]


@pytest.mark.parametrize(("method", "path", "kw", "status", "type_"), CASES)
def test_every_error_is_problem_details(
    client: TestClient,
    method: str,
    path: str,
    kw: dict[str, Any],
    status: int,
    type_: str,
) -> None:
    """REQ-038 (1), (2), #48: five keys, status, type, instance without query."""
    params = {**kw.get("params", {}), "q": CANARY}
    rest = {k: v for k, v in kw.items() if k != "params"}
    resp = client.request(method, path, params=params, headers=AUTH, **rest)
    check_problem(resp, status, type_, path)
    assert resp.status_code != 422


def test_405_keeps_allow_and_429_keeps_retry_after(client: TestClient) -> None:
    resp = client.delete("/t/q")
    assert "GET" in resp.headers["allow"]
    retry = client.get("/t/retry")
    check_problem(retry, 429, "rate_limited", "/t/retry")
    assert retry.headers["retry-after"] == "17"


def test_title_is_the_reason_phrase(client: TestClient) -> None:
    assert client.get("/no/such").json()["title"] == "Not Found"
    assert client.get("/t/problem/409").json()["title"] == "Conflict"
    assert client.get("/t/boom").json()["title"] == "Internal Server Error"


# ------------------------------------------------------- CHK-M2-041, -042


def test_validation_error_names_fields_never_values(client: TestClient) -> None:
    """REQ-038 (3): the field is named, the canary value is not."""
    resp = client.post("/t/model", json={"n": CANARY, "name": CANARY})
    body = check_problem(resp, 400, "invalid_request", "/t/model")
    assert "n" in body["detail"] and "name" in body["detail"]
    assert "body.n" in body["detail"] and "body.name" in body["detail"]
    for leak in ("input", "should be", "valid integer", "at most"):
        assert leak not in body["detail"]


def test_query_validation_names_the_parameter(client: TestClient) -> None:
    resp = client.get("/t/q", params={"x": CANARY, "y": CANARY})
    body = check_problem(resp, 400, "invalid_request", "/t/q")
    assert "query.x" in body["detail"] and "query.y" in body["detail"]


def test_many_fields_are_capped() -> None:
    app = make_app()

    class Many(BaseModel):
        values: list[int]

    @app.post("/t/many")
    def many(body: Many) -> None:
        return None

    with TestClient(app) as c:
        resp = c.post("/t/many", json={"values": [CANARY] * 30})
    body = check_problem(resp, 400, "invalid_request", "/t/many")
    assert 1 <= body["detail"].count("body.values.") <= 10
    assert len(body["detail"]) < 1000


@pytest.mark.parametrize(
    ("path", "payload"),
    [("/t/strict", {"n": 1, CANARY: 1}), ("/t/mapped", {"m": {CANARY: "x"}})],
    ids=["extra-key", "dict-key"],
)
def test_client_chosen_keys_are_not_echoed(
    client: TestClient, path: str, payload: dict[str, Any]
) -> None:
    """A key the client chose is part of the client's value, not a field name."""
    resp = client.post(path, json=payload)
    check_problem(resp, 400, "invalid_request", path)


def test_error_bodies_hold_no_secret_text(client: TestClient) -> None:
    """REQ-038 (2): canary sweep over 500, driver error and auth headers."""
    for path in ("/t/boom", "/t/pgerr"):
        resp = client.get(path, headers=AUTH, params={"token": CANARY})
        body = check_problem(resp, 500, "about:blank", path)
        assert body["detail"] == "An unexpected error occurred."


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int = 1


class Cat(BaseModel):
    kind: Literal["cat"]
    n: int


class Dog(BaseModel):
    kind: Literal["dog"]
    n: int


class Pets(BaseModel):
    item: Annotated[Cat | Dog, Field(discriminator="kind")]
    xs: list[dict[str, int]] = []


def keyed_app() -> FastAPI:
    app = make_app()

    @app.get("/t/qmodel")
    def qmodel(p: Annotated[QueryModel, Query()]) -> int:
        return p.a

    @app.get("/t/cmodel")
    def cmodel(p: Annotated[QueryModel, Cookie()]) -> int:
        return p.a

    @app.get("/t/hmodel")
    def hmodel(p: Annotated[QueryModel, Header()]) -> int:
        return p.a

    @app.post("/t/pets")
    def pets(body: Pets) -> int:
        return 1

    return app


@pytest.mark.parametrize("where", ["query", "cookie", "header"])
def test_client_chosen_parameter_keys_are_not_echoed(where: str) -> None:
    """Lead ruling 2026-10-21 (1): no client-chosen string in detail, any source."""
    key = "canaryparamkey7f3a"
    with TestClient(keyed_app()) as c:
        if where == "query":
            resp = c.get("/t/qmodel", params={key: "1"})
        elif where == "cookie":
            c.cookies.set(key, "1")
            resp = c.get("/t/cmodel")
        else:
            resp = c.get("/t/hmodel", headers={key: "1"})
    assert resp.status_code == 400
    assert key not in resp.text.lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"item": {"kind": CANARY, "n": 1}},
        {"item": {"kind": "cat", "n": CANARY}},
        {"item": {"kind": "cat", "n": 1}, "xs": [{CANARY: "x"}]},
    ],
    ids=["discriminator-value", "nested-value", "list-of-dict-key"],
)
def test_nested_client_strings_are_not_echoed(payload: dict[str, Any]) -> None:
    with TestClient(keyed_app()) as c:
        resp = c.post("/t/pets", json=payload)
    check_problem(resp, 400, "invalid_request", "/t/pets")
