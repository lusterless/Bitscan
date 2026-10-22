"""Health routes (TS §8.4 L1292; #5): outside /api/v1, no token, no rate limit.

/healthz is liveness and never touches the database. /readyz answers 200
only when the database is reachable as bitscan_app, the stored Alembic
revision is the head shipped in this package, and the three system_schedule
rows exist. A 503 names the failed check (db, migrations, system_schedule)
and nothing else. Every check is bounded on the client side: ping() takes at
most 2 s, and the revision and schedule queries run in one worker thread
that is waited for at most 2 s (one in flight), so /readyz never hangs.
"""

import threading
from functools import cache
from typing import Annotated, Final, Literal

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.db import MIGRATIONS_DIR
from bitscan_manager.repositories import health
from bitscan_manager.runtime import Database, Runtime, get_runtime

SCHEDULE_KINDS: Final = frozenset({"inventory", "offline_sweep", "retention"})
CHECK_TIMEOUT_S: Final = 2.0

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]


@cache
def packaged_head() -> str | None:
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


def _failed_check(db: Database) -> str | None:
    try:
        with db.transaction() as tx:
            health.bound_statements(tx.conn, int(CHECK_TIMEOUT_S * 1000))
            if health.alembic_revisions(tx.conn) != [packaged_head()]:
                return "migrations"
            if not SCHEDULE_KINDS <= health.schedule_kinds(tx.conn):
                return "system_schedule"
    except Exception:
        return "db"
    return None


class _Checker:
    """At most one readiness query in flight; a stuck one is not waited for."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def run(self, db: Database) -> str | None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return "db"
            result: list[str | None] = []
            self._thread = threading.Thread(
                target=lambda: result.append(_failed_check(db)),
                name="readyz",
                daemon=True,
            )
            self._thread.start()
            thread = self._thread
        thread.join(CHECK_TIMEOUT_S)
        return result[0] if result else "db"


def _checker(request: Request) -> _Checker:
    checker = getattr(request.app.state, "readyz_checker", None)
    if not isinstance(checker, _Checker):
        checker = _Checker()
        request.app.state.readyz_checker = checker
    return checker


@router.get("/healthz")
def healthz() -> Health:
    return Health(status="ok")


@router.get(
    "/readyz",
    responses={503: {"description": "Not ready; detail names the failed check."}},
)
def readyz(
    request: Request, runtime: Annotated[Runtime, Depends(get_runtime)]
) -> Health:
    failed = "db" if not runtime.db.ping() else _checker(request).run(runtime.db)
    if failed is not None:
        raise Problem(503, ABOUT_BLANK, failed)
    return Health(status="ok")
