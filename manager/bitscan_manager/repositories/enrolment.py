"""enrollment_token and enrollment_request SQL (TS §5.2, §3.2). Parameterised
statements only; only SHA-256 token hashes reach this module, never tokens.

Runs inside the caller's transaction; never commits. bitscan_app has UPDATE on
both tables and DELETE on neither: tokens end with revoked_at, and requests
keep their decision (retention removes decided ones, M11).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql

RequestState = Literal["pending", "decided", "all"]

_TOKEN_COLS = sql.SQL(
    "token_id, max_uses, uses, auto_approve, allowed_cidrs::text[], expires_at,"
    " revoked_at, created_by, created_at"
)
_REQUEST_COLS = sql.SQL(
    "request_id, kind, agent_id, enrollment_token_id, hostname, machine_id,"
    " os_pretty_name, agent_version, new_token_hash, token_expires_at,"
    " host(source_ip), requested_at, decision, decided_by, decided_at"
)
_STATE = {
    "pending": sql.SQL("decision IS NULL"),
    "decided": sql.SQL("decision IS NOT NULL"),
    "all": sql.SQL("true"),
}


@dataclass(frozen=True)
class EnrolmentTokenRow:
    """Never holds token_hash: list and read never show it (REQ-067 (3))."""

    token_id: int
    max_uses: int
    uses: int
    auto_approve: bool
    allowed_cidrs: list[str] | None
    expires_at: datetime
    revoked_at: datetime | None
    created_by: int
    created_at: datetime


@dataclass(frozen=True)
class UsedToken:
    token_id: int
    auto_approve: bool


@dataclass(frozen=True)
class RequestRow:
    request_id: int
    kind: str
    agent_id: UUID
    enrollment_token_id: int
    hostname: str
    machine_id: str
    os_pretty_name: str | None
    agent_version: str
    new_token_hash: str = field(repr=False)
    token_expires_at: datetime
    source_ip: str
    requested_at: datetime
    decision: str | None
    decided_by: int | None
    decided_at: datetime | None


@dataclass(frozen=True)
class MatchRow:
    agent_id: UUID
    hostname: str
    machine_id: str
    status: str


def _returned_id(cur: psycopg.Cursor[Any]) -> int:
    row = cur.fetchone()  # INSERT … RETURNING gives exactly one row
    if row is None:
        raise RuntimeError("INSERT … RETURNING returned no row")
    return int(row[0])


class EnrolmentRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    # ---------------------------------------------------- enrollment_token

    def insert_token(
        self,
        *,
        token_hash: str,
        max_uses: int,
        auto_approve: bool,
        allowed_cidrs: list[str] | None,
        expires_at: datetime,
        created_by: int,
        now: datetime,
    ) -> int:
        row = self._conn.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, auto_approve,"
            " allowed_cidrs, expires_at, created_by, created_at)"
            " VALUES (%s, %s, %s, CAST(%s AS cidr[]), %s, %s, %s) RETURNING token_id",
            (
                token_hash,
                max_uses,
                auto_approve,
                allowed_cidrs,
                expires_at,
                created_by,
                now,
            ),
        )
        return _returned_id(row)

    def use_token(
        self, token_hash: str, source_ip: str, now: datetime
    ) -> UsedToken | None:
        """One atomic use: expiry, revocation, the source CIDRs and uses <
        max_uses are checked and uses incremented in one statement, so
        concurrent enrolments never pass max_uses (TS §3.2 L183). None for every
        refusal alike; nothing changes then."""
        row = self._conn.execute(
            "UPDATE enrollment_token SET uses = uses + 1 WHERE token_hash = %s"
            " AND uses < max_uses AND revoked_at IS NULL AND expires_at > %s"
            " AND (allowed_cidrs IS NULL OR CAST(%s AS inet) <<= ANY (allowed_cidrs))"
            " RETURNING token_id, auto_approve",
            (token_hash, now, source_ip),
        ).fetchone()
        return None if row is None else UsedToken(int(row[0]), bool(row[1]))

    def revoke_token(self, token_id: int, now: datetime) -> bool:
        """True if the token exists; an earlier revoked_at is kept."""
        cur = self._conn.execute(
            "UPDATE enrollment_token SET revoked_at = COALESCE(revoked_at, %s)"
            " WHERE token_id = %s",
            (now, token_id),
        )
        return cur.rowcount == 1

    def revoke_active_token(self, token_id: int, now: datetime) -> bool:
        """True only for the one call that revoked a still-active token, so
        concurrent revokes write one audit entry (#71)."""
        cur = self._conn.execute(
            "UPDATE enrollment_token SET revoked_at = %s"
            " WHERE token_id = %s AND revoked_at IS NULL",
            (now, token_id),
        )
        return cur.rowcount == 1

    def get_token(self, token_id: int) -> EnrolmentTokenRow | None:
        query = sql.SQL("SELECT {} FROM enrollment_token WHERE token_id = %s")
        row = self._conn.execute(query.format(_TOKEN_COLS), (token_id,)).fetchone()
        return None if row is None else EnrolmentTokenRow(*row)

    def token_page(self, limit: int, after_id: int | None) -> list[EnrolmentTokenRow]:
        query = sql.SQL(
            "SELECT {} FROM enrollment_token WHERE %s::bigint IS NULL"
            " OR token_id > %s ORDER BY token_id LIMIT %s"
        ).format(_TOKEN_COLS)
        rows = self._conn.execute(query, (after_id, after_id, limit)).fetchall()
        return [EnrolmentTokenRow(*r) for r in rows]

    # -------------------------------------------------- enrollment_request

    def insert_request(
        self,
        *,
        kind: str,
        agent_id: UUID,
        token_id: int,
        hostname: str,
        machine_id: str,
        os_pretty_name: str | None,
        agent_version: str,
        new_token_hash: str,
        token_expires_at: datetime,
        source_ip: str,
        now: datetime,
    ) -> int:
        row = self._conn.execute(
            "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id,"
            " hostname, machine_id, os_pretty_name, agent_version, new_token_hash,"
            " token_expires_at, source_ip, requested_at) VALUES (%s, %s, %s, %s,"
            " %s, %s, %s, %s, %s, CAST(%s AS inet), %s) RETURNING request_id",
            (
                kind,
                agent_id,
                token_id,
                hostname,
                machine_id,
                os_pretty_name,
                agent_version,
                new_token_hash,
                token_expires_at,
                source_ip,
                now,
            ),
        )
        return _returned_id(row)

    def _request(self, where: sql.Composable, value: object) -> RequestRow | None:
        query = sql.SQL("SELECT {} FROM enrollment_request WHERE {}")
        row = self._conn.execute(
            query.format(_REQUEST_COLS, where), (value,)
        ).fetchone()
        return None if row is None else RequestRow(*row)  # columns in field order

    def find_by_new_token_hash(self, token_hash: str) -> RequestRow | None:
        return self._request(sql.SQL("new_token_hash = %s"), token_hash)

    def get_request_for_update(self, request_id: int) -> RequestRow | None:
        """Locks the row, so two concurrent decisions serialise (REQ-069 (5))."""
        return self._request(sql.SQL("request_id = %s FOR UPDATE"), request_id)

    def rejected_new_for_agent(self, agent_id: UUID) -> bool:
        """True when the agent's own new enrolment was rejected (#26, #59)."""
        row = self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM enrollment_request WHERE agent_id = %s"
            " AND kind = 'new' AND decision = 'rejected')",
            (agent_id,),
        ).fetchone()
        return bool(row is not None and row[0])

    def request_page(
        self, state: RequestState, limit: int, after_id: int | None
    ) -> list[RequestRow]:
        query = sql.SQL(
            "SELECT {} FROM enrollment_request WHERE {} AND (%s::bigint IS NULL"
            " OR request_id > %s) ORDER BY request_id LIMIT %s"
        ).format(_REQUEST_COLS, _STATE[state])
        rows = self._conn.execute(query, (after_id, after_id, limit)).fetchall()
        return [RequestRow(*r) for r in rows]

    def decide(
        self, request_id: int, decision: str, decided_by: int, now: datetime
    ) -> bool:
        """True for exactly one decision per request."""
        cur = self._conn.execute(
            "UPDATE enrollment_request SET decision = %s, decided_by = %s,"
            " decided_at = %s WHERE request_id = %s AND decision IS NULL",
            (decision, decided_by, now, request_id),
        )
        return cur.rowcount == 1

    def matches(self, request: RequestRow) -> list[MatchRow]:
        """Every other agent sharing the request's hostname or machine-id (TS
        §3.2 L192: cloned images show up this way)."""
        rows = self._conn.execute(
            "SELECT agent_id, hostname, machine_id, status::text FROM agent"
            " WHERE agent_id <> %s AND (machine_id = %s OR hostname = %s)"
            " ORDER BY hostname, agent_id",
            (request.agent_id, request.machine_id, request.hostname),
        ).fetchall()
        return [MatchRow(*r) for r in rows]
