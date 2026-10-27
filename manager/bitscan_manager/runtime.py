"""Runtime contract: what routes and services get from serve (TASK-025 plan).

Everything time-based reads the Clock, so tests use a fake one. The objects
behind each Protocol are built by serve; tests pass fakes.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import psycopg
from fastapi import HTTPException, Request


class Clock(Protocol):
    def now(self) -> datetime: ...  # timezone-aware, UTC


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class Tx(Protocol):
    @property
    def conn(self) -> psycopg.Connection[Any]: ...

    def on_commit(self, hook: Callable[[], None]) -> None: ...  # never on rollback


class Database(Protocol):
    def transaction(self) -> AbstractContextManager[Tx]: ...  # READ COMMITTED

    def ping(self) -> bool: ...  # for /readyz; never raises


class CatalogSession(Protocol):
    """One pinned connection for several transactions in a row, so the
    catalog lock spans them (TS §4.1 "Locking"). Used by one thread."""

    @property
    def conn(self) -> psycopg.Connection[Any]: ...  # autocommit; catalog_lock only

    # Entered several times in a row, never nested; hooks run after COMMIT.
    def transaction(self) -> AbstractContextManager[Tx]: ...

    # Inside an open transaction (a rebuild's per-file savepoint); on
    # rollback the hooks registered inside it are dropped.
    def savepoint(self) -> AbstractContextManager[None]: ...


class SessionDatabase(Protocol):
    def session(self) -> AbstractContextManager[CatalogSession]: ...


class TotpCipher(Protocol):
    def encrypt(self, seed: bytes) -> str: ...

    def decrypt(self, ciphertext: str) -> bytes: ...


class SinkGate(Protocol):
    def refusing(self) -> bool: ...  # after 15 min of outage until drained

    def wake(self) -> None: ...  # an audit entry was committed; ship soon


class RateLimits(Protocol):
    def allow_login(self, ip: str) -> bool: ...

    def allow_user(self, user_id: int) -> bool: ...

    def failed_check_blocked(self, ip: str) -> bool: ...

    def record_failed_check(self, ip: str) -> None: ...

    def allow_agent(self, agent_id: UUID) -> bool: ...  # 30 per minute

    def allow_enrol(self, ip: str) -> bool: ...  # 10 per minute, every attempt

    def allow_unscheduled_inventory(self, agent_id: UUID) -> bool: ...

    def unscheduled_inventory_retry_after(self, agent_id: UUID) -> int: ...


class Lifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class Runtime:
    clock: Clock
    db: Database
    totp_cipher: TotpCipher
    sink_gate: SinkGate
    limits: RateLimits
    lifecycle: Lifecycle | None = None  # None in tests and the OpenAPI export


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, Runtime):
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return runtime
