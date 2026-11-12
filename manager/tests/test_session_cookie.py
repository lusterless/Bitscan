"""The web session cookie and its CSRF check, without a database.

Expected values: TS §6.2 (the `__Host-bitscan_session` cookie: HttpOnly,
Secure, SameSite=Strict, Path=/, no Max-Age; read only without an
Authorization header), TS §6.3 (`X-Bitscan-Request: 1`; a present Origin must
be the manager's own; otherwise 403 csrf_required); owner decision 2026-11-12
(work/plans/session-cookie-proposal.md §2.1, §2.2).
"""

import pytest
from starlette.requests import Request

from bitscan_manager.auth import session_cookie as sc

TOKEN = "bsu_" + "A" * 43


def request(
    headers: list[tuple[str, str]],
    *,
    scheme: str = "https",
    host: str = "manager.example:8443",
) -> Request:
    raw = [(b"host", host.encode())] if host else []
    raw += [(k.lower().encode(), v.encode()) for k, v in headers]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "path": "/api/v1/auth/session",
            "query_string": b"",
            "headers": raw,
            "server": ("manager.example", 8443),
        }
    )


def attributes(header: str) -> tuple[str, set[str]]:
    first, *rest = (part.strip() for part in header.split(";"))
    return first, set(rest)


def test_the_set_cookie_header_has_exactly_the_specified_attributes() -> None:
    first, rest = attributes(sc.set_cookie_header(TOKEN))
    assert first == f"__Host-bitscan_session={TOKEN}"
    assert rest == {"Path=/", "Secure", "HttpOnly", "SameSite=Strict"}


def test_no_lifetime_or_domain_on_the_session_cookie() -> None:
    header = sc.set_cookie_header(TOKEN).lower()
    assert "max-age" not in header
    assert "expires" not in header
    assert "domain" not in header


def test_the_clearing_header_removes_the_same_cookie() -> None:
    first, rest = attributes(sc.clear_cookie_header())
    assert first == "__Host-bitscan_session="
    assert rest == {"Max-Age=0", "Path=/", "Secure", "HttpOnly", "SameSite=Strict"}


@pytest.mark.parametrize(
    ("cookies", "expected"),
    [
        ([f"__Host-bitscan_session={TOKEN}"], TOKEN),
        ([f"a=1; __Host-bitscan_session={TOKEN}; b=2"], TOKEN),
        (["a=1", f"__Host-bitscan_session={TOKEN}"], TOKEN),
        ([], None),
        (["a=1; b=2"], None),
        (["__Host-bitscan_session="], None),
        (["bitscan_session=" + TOKEN], None),
        (["__host-bitscan_session=" + TOKEN], None),
        ([f"__Host-bitscan_session={TOKEN}; __Host-bitscan_session={TOKEN}"], None),
        ([f"__Host-bitscan_session={TOKEN}", "__Host-bitscan_session=x"], None),
    ],
)
def test_cookie_token(cookies: list[str], expected: str | None) -> None:
    req = request([("cookie", value) for value in cookies])
    assert sc.cookie_token(req) == expected


def test_has_authorization() -> None:
    assert sc.has_authorization(request([("authorization", "Bearer x")]))
    # An empty header is still an Authorization header: no cookie fallback.
    assert sc.has_authorization(request([("authorization", "")]))
    assert sc.has_authorization(request([])) is False


@pytest.mark.parametrize(
    "headers",
    [
        [("x-bitscan-request", "1")],
        [("x-bitscan-request", "1"), ("origin", "https://manager.example:8443")],
        [("x-bitscan-request", "1"), ("origin", "HTTPS://Manager.Example:8443")],
    ],
)
def test_csrf_accepted(headers: list[tuple[str, str]]) -> None:
    assert sc.csrf_ok(request(headers))


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("x-bitscan-request", "0")],
        [("x-bitscan-request", "true")],
        [("x-bitscan-request", "")],
        [("x-bitscan-request", "1"), ("x-bitscan-request", "1")],
        [("origin", "https://manager.example:8443")],
        [("x-bitscan-request", "1"), ("origin", "https://evil.example")],
        [("x-bitscan-request", "1"), ("origin", "https://manager.example")],
        [("x-bitscan-request", "1"), ("origin", "http://manager.example:8443")],
        [("x-bitscan-request", "1"), ("origin", "null")],
        [
            ("x-bitscan-request", "1"),
            ("origin", "https://manager.example:8443"),
            ("origin", "https://manager.example:8443"),
        ],
    ],
)
def test_csrf_refused(headers: list[tuple[str, str]]) -> None:
    assert sc.csrf_ok(request(headers)) is False


def test_an_origin_with_no_host_header_is_refused() -> None:
    headers = [("x-bitscan-request", "1"), ("origin", "https://manager.example")]
    assert sc.csrf_ok(request(headers, host="")) is False
