"""Cursor pagination (TS §6.3: ?limit=50&cursor=<opaque>, at most 500).

Every list answers {items, next_cursor} (TS §7.1 L1215; #47 (d)). A cursor
holds the list's name and the sort key of the last item, with an HMAC under a
per-process key, so a tampered cursor, or one from another list, is refused
with 400 invalid_request (#48). Cursors do not survive a manager restart.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Query
from pydantic import BaseModel

from bitscan_manager.api.problems import Problem

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 500
_KEY: Final = secrets.token_bytes(32)
_MAC_BYTES: Final = 16

CursorKey = int | str | list[int | str]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class PageParams:
    limit: int
    cursor: str | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PageParams:
    """FastAPI dependency; a bad limit is a validation error (400)."""
    return PageParams(limit=limit, cursor=cursor)


def _mac(payload: bytes) -> bytes:
    return hmac.new(_KEY, payload, hashlib.sha256).digest()[:_MAC_BYTES]


def encode_cursor(scope: str, key: CursorKey) -> str:
    payload = json.dumps([scope, key], separators=(",", ":")).encode("utf-8")
    raw = _mac(payload) + payload
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(scope: str, cursor: str) -> CursorKey:
    bad = Problem(400, "invalid_request", "Invalid request: query.cursor")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    except (binascii.Error, ValueError):
        raise bad from None
    mac, payload = raw[:_MAC_BYTES], raw[_MAC_BYTES:]
    # The decoder ignores stray characters and unused bits; only the exact
    # string this module produced is accepted.
    canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if canonical != cursor or not hmac.compare_digest(mac, _mac(payload)):
        raise bad
    found_scope, key = json.loads(payload)
    if found_scope != scope:
        raise bad
    return key  # type: ignore[no-any-return]


def page_of[T](
    rows: Sequence[T], limit: int, scope: str, key: Callable[[T], CursorKey]
) -> Page[T]:
    """rows is the query result for limit + 1 rows; the extra one only says
    that another page exists."""
    items = list(rows[:limit])
    more = len(rows) > limit and items
    return Page[T](
        items=items, next_cursor=encode_cursor(scope, key(items[-1])) if more else None
    )
