"""REQ-038 (4), #47 (d), #52: cursor pagination (TASK-026).

Checks CHK-M2-043, CHK-M2-044 and CHK-M2-046 of tests/m2/test-plan.md.
TS §6.3 L1134 (?limit=50&cursor=<opaque>, at most 500), TS §7.1 L1215
({items, next_cursor}), #48 (400 invalid_request).
"""

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from bitscan_manager.api import pagination
from bitscan_manager.api.pagination import (
    Page,
    PageParams,
    decode_cursor,
    encode_cursor,
    page_of,
    page_params,
)
from bitscan_manager.app import create_app

SOURCE: list[int] = []


def make_app() -> FastAPI:
    app = create_app()

    def listing(scope: str, p: PageParams) -> Page[int]:
        after = -1 if p.cursor is None else decode_cursor(scope, p.cursor)
        assert isinstance(after, int)
        rows = [i for i in SOURCE if i > after][: p.limit + 1]
        return page_of(rows, p.limit, scope, lambda i: i)

    @app.get("/t/list")
    def t_list(p: PageParams = Depends(page_params)) -> Page[int]:  # noqa: B008
        return listing("t", p)

    @app.get("/t/other")
    def t_other(p: PageParams = Depends(page_params)) -> Page[int]:  # noqa: B008
        return listing("u", p)

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(make_app()) as c:
        yield c


def set_source(n: int) -> list[int]:
    SOURCE[:] = [10 * i + 7 for i in range(n)]  # BIGSERIAL-like ids with gaps
    return list(SOURCE)


def walk(c: TestClient, limit: int | None, path: str = "/t/list") -> list[list[int]]:
    pages: list[list[int]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        resp = c.get(path, params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"items", "next_cursor"}
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
        assert len(pages) < 10_000


# ------------------------------------------------------------ CHK-M2-043


@pytest.mark.parametrize("n", [1, 2, 49, 50, 500])
def test_walking_n_plus_one_items_with_limit_n(client: TestClient, n: int) -> None:
    items = set_source(n + 1)
    pages = walk(client, n)
    assert pages == [items[:n], items[n:]]
    flat = [i for p in pages for i in p]
    assert flat == items
    assert len(set(flat)) == len(flat)


def test_default_limit_is_50(client: TestClient) -> None:
    items = set_source(120)
    pages = walk(client, None)
    assert [len(p) for p in pages] == [50, 50, 20]
    assert [i for p in pages for i in p] == items


def test_exact_multiple_ends_with_null_cursor(client: TestClient) -> None:
    items = set_source(10)
    resp = client.get("/t/list", params={"limit": 10}).json()
    assert resp == {"items": items, "next_cursor": None}


def test_empty_list(client: TestClient) -> None:
    set_source(0)
    assert client.get("/t/list").json() == {"items": [], "next_cursor": None}


def test_order_is_stable_across_walks(client: TestClient) -> None:
    set_source(37)
    assert walk(client, 5) == walk(client, 5)


@pytest.mark.parametrize("limit", ["1", "500"])
def test_limit_bounds_accepted(client: TestClient, limit: str) -> None:
    set_source(3)
    assert client.get("/t/list", params={"limit": limit}).status_code == 200


@pytest.mark.parametrize("limit", ["0", "501", "-1", "abc", "1.5", "", "1e2"])
def test_bad_limits_are_400(client: TestClient, limit: str) -> None:
    set_source(3)
    resp = client.get("/t/list", params={"limit": limit})
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "invalid_request"
    assert "limit" in body["detail"]


# ------------------------------------------------------------ CHK-M2-044


def first_cursor(c: TestClient, path: str = "/t/list") -> str:
    set_source(20)
    cursor = c.get(path, params={"limit": 3}).json()["next_cursor"]
    assert isinstance(cursor, str)
    return cursor


def assert_refused(c: TestClient, cursor: str, path: str = "/t/list") -> None:
    resp = c.get(path, params={"limit": 3, "cursor": cursor})
    assert resp.status_code == 400, cursor
    body = resp.json()
    assert body["type"] == "invalid_request"
    assert cursor not in resp.text or len(cursor) < 3


def test_valid_cursor_is_opaque_base64url(client: TestClient) -> None:
    cursor = first_cursor(client)
    assert set(cursor) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert (
        client.get("/t/list", params={"limit": 3, "cursor": cursor}).status_code == 200
    )


def test_every_single_character_change_is_refused(client: TestClient) -> None:
    cursor = first_cursor(client)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    for i, ch in enumerate(cursor):
        for repl in (
            alphabet[(alphabet.index(ch) + 1) % 64],
            alphabet[(alphabet.index(ch) + 33) % 64],
        ):
            assert_refused(client, cursor[:i] + repl + cursor[i + 1 :])


@pytest.mark.parametrize(
    "change",
    [
        "truncate1",
        "truncate_half",
        "append_eq",
        "append_A",
        "append_bang",
        "empty",
        "garbage",
        "padded",
        "space",
    ],
)
def test_malformed_cursors_are_refused(client: TestClient, change: str) -> None:
    cursor = first_cursor(client)
    bad = {
        "truncate1": cursor[:-1],
        "truncate_half": cursor[: len(cursor) // 2],
        "append_eq": cursor + "=",
        "append_A": cursor + "A",
        "append_bang": cursor + "!",
        "empty": "",
        "garbage": "%%%not-base64%%%",
        "padded": cursor + "=" * (-len(cursor) % 4)
        if len(cursor) % 4
        else cursor + "==",
        "space": " " + cursor,
    }[change]
    assert_refused(client, bad)


def test_cursor_from_another_list_is_refused(client: TestClient) -> None:
    foreign = first_cursor(client, "/t/other")
    assert (
        client.get("/t/other", params={"limit": 3, "cursor": foreign}).status_code
        == 200
    )
    assert_refused(client, foreign, "/t/list")


def test_hand_built_cursor_without_a_valid_mac_is_refused(client: TestClient) -> None:
    for mac in (b"\x00" * 16, b""):
        payload = json.dumps(["t", 7], separators=(",", ":")).encode()
        forged = base64.urlsafe_b64encode(mac + payload).rstrip(b"=").decode()
        assert_refused(client, forged)


def test_cursor_from_another_process_key_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pagination, "_KEY", b"\x01" * 32)
    other = encode_cursor("t", 7)
    monkeypatch.undo()
    assert_refused(client, other)


def test_overlong_cursor_is_refused(client: TestClient) -> None:
    assert_refused(client, "A" * 513)


# ------------------------------------------------------------ CHK-M2-046


@pytest.mark.parametrize("key", [7, 2**62, "alice", [3, "x"], [10**15, 2]])
def test_cursor_keys_round_trip_with_their_json_type(key: Any) -> None:
    assert decode_cursor("s", encode_cursor("s", key)) == key


def test_ids_stay_json_integers(client: TestClient) -> None:
    set_source(3)
    body = client.get("/t/list").json()
    assert all(type(i) is int for i in body["items"])
