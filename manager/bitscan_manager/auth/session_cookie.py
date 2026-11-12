"""The web session cookie and its CSRF checks (TS §6.2, §6.3, §8.1; owner
decision 2026-11-12, work/plans/session-cookie-proposal.md).

The bsu_ session token travels in `__Host-bitscan_session` (HttpOnly, Secure,
SameSite=Strict, Path=/, no Max-Age, no Domain). User routes read it only when
the request has no Authorization header; agent routes never read it. A request
authenticated by the cookie must send `X-Bitscan-Request: 1` and, when an
Origin header is present, the manager's own origin. The cookie value is never
logged: the access log holds no headers (api.request_log).
"""

from typing import Final

from starlette.requests import Request

COOKIE_NAME: Final = "__Host-bitscan_session"
CSRF_HEADER: Final = "x-bitscan-request"
CSRF_VALUE: Final = "1"

# Path=/ and no Domain are what the __Host- prefix requires; no Max-Age makes
# it a browser-session cookie (the server still enforces 8 h idle, 24 h max).
_ATTRIBUTES: Final = "Path=/; Secure; HttpOnly; SameSite=Strict"


def set_cookie_header(token: str) -> str:
    """The Set-Cookie value that stores a bsu_ session token."""
    return f"{COOKIE_NAME}={token}; {_ATTRIBUTES}"


def clear_cookie_header() -> str:
    """The Set-Cookie value that removes the session cookie."""
    return f"{COOKIE_NAME}=; Max-Age=0; {_ATTRIBUTES}"


def has_authorization(request: Request) -> bool:
    return bool(request.headers.getlist("authorization"))


def cookie_token(request: Request) -> str | None:
    """The cookie's token, or None when the cookie is absent or empty. Several
    Cookie values with this name are refused (None), like several bearers."""
    found: list[str] = []
    for header in request.headers.getlist("cookie"):
        for part in header.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name == COOKIE_NAME:
                found.append(value)
    if len(found) != 1 or not found[0]:
        return None
    return found[0]


def _own_origin(request: Request) -> str | None:
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not hosts[0]:
        return None
    return f"{request.url.scheme}://{hosts[0]}".lower()


def csrf_ok(request: Request) -> bool:
    """True when a cookie-authenticated request may proceed: exactly one
    `X-Bitscan-Request: 1`, and any Origin equal to the manager's own."""
    marks = request.headers.getlist(CSRF_HEADER)
    if marks != [CSRF_VALUE]:
        return False
    origins = request.headers.getlist("origin")
    if not origins:
        return True
    own = _own_origin(request)
    return len(origins) == 1 and own is not None and origins[0].lower() == own
