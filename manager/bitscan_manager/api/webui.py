"""The built web UI, served from the manager's own origin (#6 M5 half; REQ-118;
work/plans/TASK-112.md).

GET / is the build's index.html and GET /assets/{name} one file directly in
its assets/ folder. Both need no token: a browser cannot send one when it
loads a page (#6 (f), a recorded deviation from TS §2.3 L118); the files hold
no data, and every API call the page makes carries its token. Every file is
read into memory when the app is created, so no request touches the file
system and a file added or replaced later is never served. There is no
catch-all (the UI uses hash routes), no CORS, and the routes are not in the
OpenAPI document; the TS §6.3 headers come from SecurityHeaders like on every
other response.
"""

import logging
import os
import stat
import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Response
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)

# PD-28 (b): Vite writes the build straight into bitscan_manager/webui/.
DEFAULT_WEBUI_DIR: Final = Path(__file__).resolve().parents[1] / "webui"
MAX_TOTAL_BYTES: Final = 32 * 1_048_576
MAX_NAME: Final = 128
CONTENT_TYPES: Final[Mapping[str, str]] = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
INDEX_TYPE: Final = "text/html; charset=utf-8"

_FIRST: Final = frozenset(string.ascii_letters + string.digits)
_NAME_CHARS: Final = _FIRST | frozenset("._-")
# Never follow a symlink swapped in after the lstat check, and never block on
# a FIFO; both flags are POSIX only.
_OPEN_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
)


@dataclass(frozen=True)
class Asset:
    body: bytes = field(repr=False)
    content_type: str


@dataclass(frozen=True)
class WebUi:
    index: bytes | None = field(default=None, repr=False)  # None: not built
    assets: Mapping[str, Asset] = field(default_factory=dict)


class _TooLarge(Exception):
    pass


def _asset_name(name: str) -> bool:
    return (
        0 < len(name) <= MAX_NAME
        and name[0] in _FIRST
        and all(c in _NAME_CHARS for c in name)
        and os.path.splitext(name)[1] in CONTENT_TYPES
    )


def _read(path: Path, budget: int) -> bytes | None:
    """The file's bytes; None when it is not a regular file (a symlink, a
    folder, a device). Raises _TooLarge past budget."""
    if not stat.S_ISREG(path.lstat().st_mode):
        return None
    fd = os.open(path, _OPEN_FLAGS)
    with open(fd, "rb") as fh:  # closes fd
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return None
        body = fh.read(budget + 1)
    if len(body) > budget:
        raise _TooLarge
    return body


def load(folder: Path) -> WebUi:
    """The build in folder, or WebUi() (not built) when it is missing or
    unreadable. Never raises; an OSError is not logged, since its message
    can name paths outside the folder."""
    try:
        index = _read(folder / "index.html", MAX_TOTAL_BYTES)
        if index is None:
            return WebUi()
        budget = MAX_TOTAL_BYTES - len(index)
        assets: dict[str, Asset] = {}
        assets_dir = folder / "assets"
        try:
            mode = assets_dir.lstat().st_mode
        except FileNotFoundError:
            mode = 0  # a build without assets/
        if stat.S_ISDIR(mode):  # not through a symlink
            for name in sorted(os.listdir(assets_dir)):
                if not _asset_name(name):
                    continue
                body = _read(assets_dir / name, budget)
                if body is not None:
                    budget -= len(body)
                    kind = CONTENT_TYPES[os.path.splitext(name)[1]]
                    assets[name] = Asset(body, kind)
        return WebUi(index, assets)
    except _TooLarge:
        log.error("web ui build exceeds 32 MiB; not served")
        return WebUi()
    except OSError:  # not built (no index.html), or unreadable
        return WebUi()


def build_router(ui: WebUi) -> APIRouter:
    """Both routes are always registered, so the route table is the same with
    or without a build; a missing file is the normal problem+json 404."""
    router = APIRouter(include_in_schema=False)

    @router.get("/")
    async def webui_index() -> Response:
        if ui.index is None:
            raise HTTPException(404)
        return Response(ui.index, media_type=INDEX_TYPE)

    @router.get("/assets/{name}")
    async def webui_asset(name: str) -> Response:
        found = ui.assets.get(name)  # a lookup, never a path join
        if found is None:
            raise HTTPException(404)
        return Response(found.body, media_type=found.content_type)

    return router
