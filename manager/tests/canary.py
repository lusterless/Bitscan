"""Canary sweep helper (TP-M2-05, REQ-039 (2); reused by every later M2 test).

A canary is a unique random string planted as a secret. `sweep` searches every
place a secret could leak to and reports where each canary was found:
captured log text, stdout/stderr, response bodies and headers, and exceptions
with their whole chain (str, repr, args, __cause__, __context__, formatted
traceback, and the attributes a UnicodeError keeps).
"""

import secrets
import traceback
from collections.abc import Iterable
from typing import Any


def new_canary(kind: str = "x") -> str:
    return f"CANARY-{kind}-{secrets.token_hex(8)}"


def exception_texts(exc: BaseException) -> list[str]:
    """Every text an exception chain can expose."""
    out: list[str] = []
    seen: set[int] = set()
    todo: list[BaseException | None] = [exc]
    while todo:
        item = todo.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        out += [str(item), repr(item), *map(repr, item.args)]
        obj = getattr(item, "object", None)  # UnicodeError keeps the input
        if obj is not None:
            out.append(repr(obj))
        todo += [item.__cause__, item.__context__]
    out.append("".join(traceback.format_exception(exc)))
    return out


def texts_of(item: Any) -> list[str]:
    if item is None:
        return []
    if isinstance(item, BaseException):
        return exception_texts(item)
    if isinstance(item, bytes):
        return [item.decode("utf-8", "replace")]
    if isinstance(item, str):
        return [item]
    headers = getattr(item, "headers", None)
    text = getattr(item, "text", None)
    if headers is not None and text is not None:  # an HTTP response
        return [text, *(f"{k}: {v}" for k, v in headers.multi_items())]
    return [repr(item)]


def sweep(canaries: Iterable[str], *places: Any) -> list[tuple[str, int]]:
    """(canary, index of the place) for every hit; [] means nothing leaked."""
    hits: list[tuple[str, int]] = []
    wanted = [c for c in canaries if c]
    for index, place in enumerate(places):
        for text in texts_of(place):
            for canary in wanted:
                if canary in text:
                    hits.append((canary, index))
    return sorted(set(hits))
