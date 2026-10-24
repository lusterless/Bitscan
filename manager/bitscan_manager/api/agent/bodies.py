"""The capped body reader for after-auth routes (TS §6.3 L1138, §3.4 L240,
L244; REQ-066; plan work/plans/TASK-049.md).

Such a route declares no body parameter, so FastAPI reads nothing before its
token check; it then calls read_capped. The cap comes from the BodyCap that
BodyLimit put in the scope: a Content-Length over it is refused unread, and a
stream is read through CappedReceive, which stops after the chunk that
crosses it. Without a BodyCap nothing is read (fail closed). A refusal is
TooLarge (413 too_large, Connection: close), which the route may catch to
audit and fail its job before answering.
"""

from typing import Final

from fastapi import Request

from bitscan_manager.api.problems import Problem
from bitscan_manager.app import BODY_CAP_SCOPE_KEY, BodyCap, BodyTooLarge

_DETAIL: Final = "The request body exceeds the size limit."


class TooLarge(Problem):
    def __init__(self) -> None:
        super().__init__(413, "too_large", _DETAIL, {"Connection": "close"})


async def read_capped(request: Request) -> bytes:
    cap = request.scope.get(BODY_CAP_SCOPE_KEY)
    if not isinstance(cap, BodyCap):
        raise TooLarge  # no cap registered for this path: read nothing
    if cap.content_length is not None and cap.content_length > cap.limit:
        raise TooLarge
    chunks: list[bytes] = []
    try:
        async for chunk in request.stream():
            chunks.append(chunk)
    except BodyTooLarge:
        raise TooLarge from None
    return b"".join(chunks)
