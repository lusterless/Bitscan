"""REQ-006: app factory with no docs routes, no CORS, no env/network
(routes: superseded from TASK-038/-044, see tests/m2/test-plan.md).

Checks CHK-M0-035 to CHK-M0-039 of tests/m0/test-plan.md.
"""

import importlib
import os
import socket
import sys
from collections.abc import Iterator, MutableMapping
from typing import NoReturn

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from bitscan_manager.app import create_app, openapi_document

NOT_SERVED = [
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
    "/api/v1/agent/enroll",
]


class EnvRecorder(MutableMapping[str, str]):
    def __init__(self, base: MutableMapping[str, str]) -> None:
        self._data = {k: v for k, v in base.items() if not k.startswith("BITSCAN_")}
        self.read: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.read.append(key)
        return self._data[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _no_network(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("network access attempted")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_create_app_returns_fastapi() -> None:
    assert isinstance(create_app(), FastAPI)


@pytest.mark.parametrize("path", NOT_SERVED)
def test_doc_and_api_paths_are_not_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_post_enroll_is_404(client: TestClient) -> None:
    assert client.post("/api/v1/agent/enroll", json={}).status_code == 404


# REQ-006 (1) is superseded for routes from TASK-044 (health) and TASK-038 on;
# it still holds for the documentation routes (REQ-035 (3)).
EXPECTED_PATHS_M2 = {"/healthz", "/readyz"}


def test_only_the_expected_routes_are_registered() -> None:
    """Grows as M2 route tasks land; docs routes never appear."""
    paths = set(openapi_document()["paths"])
    assert EXPECTED_PATHS_M2 <= paths
    assert {p for p in paths if not p.startswith("/api/v1/")} == EXPECTED_PATHS_M2
    for banned in ("/docs", "/redoc", "/openapi.json", "/metrics"):
        assert banned not in paths


def _acao(headers: dict[str, str]) -> list[str]:
    return [k for k in headers if k.lower().startswith("access-control-allow-")]


def test_cors_preflight_gets_no_allow_headers(client: TestClient) -> None:
    resp = client.options(
        "/api/v1/x",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert _acao(dict(resp.headers)) == []


def test_simple_request_with_origin_gets_no_allow_headers(client: TestClient) -> None:
    resp = client.get("/api/v1/x", headers={"Origin": "https://evil.example"})
    assert _acao(dict(resp.headers)) == []


def test_no_cors_middleware() -> None:
    app = create_app()
    classes: list[object] = [m.cls for m in app.user_middleware]
    assert CORSMiddleware not in classes


def test_each_call_returns_a_new_app() -> None:
    a, b = create_app(), create_app()
    assert a is not b

    @a.get("/only-on-a")
    def only_on_a() -> dict[str, str]:
        return {}

    assert TestClient(a).get("/only-on-a").status_code == 200
    assert TestClient(b).get("/only-on-a").status_code == 404


def test_import_and_create_need_no_env_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = EnvRecorder(os.environ)
    monkeypatch.setattr(os, "environ", recorder)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    for name in [m for m in sys.modules if m.startswith("bitscan_manager")]:
        monkeypatch.delitem(sys.modules, name)

    module = importlib.import_module("bitscan_manager.app")
    app = module.create_app()
    doc = module.openapi_document()

    assert isinstance(app, FastAPI)
    assert {
        p for p in doc["paths"] if not p.startswith("/api/v1/")
    } == EXPECTED_PATHS_M2
    assert [k for k in recorder.read if k.startswith("BITSCAN_")] == []
