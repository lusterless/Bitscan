import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from bitscan_manager import __version__


def create_app() -> FastAPI:
    # No docs or schema routes: every call needs a bearer token (TS §2.3) and
    # TS §6.2 lists no such route. No CORS middleware (TS §6.3).
    return FastAPI(
        title="Bitscan",
        version=__version__,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )


def openapi_document() -> dict[str, Any]:
    return create_app().openapi()


def write_openapi(path: Path) -> None:
    text = json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m bitscan_manager.app <output.json>", file=sys.stderr)
        return 2
    write_openapi(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
