"""agent, agent_ip_seen and agent_tag SQL (TS §5.2, §3.2, §3.3). Parameterised
statements only; only SHA-256 token hashes reach this module, never tokens.

Runs inside the caller's transaction; never commits. bitscan_app has UPDATE on
agent and agent_ip_seen, DELETE on agent_tag and agent_ip_seen, and no DELETE
on agent: agents end as decommissioned with token_revoked_at set.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from bitscan_manager.repositories.packages import AnchorGone

# Swept statuses (TS §3.3 L218); awaiting_approval and decommissioned are never
# touched by the sweep.
SWEPT: tuple[str, ...] = ("enrolled", "online", "stale", "offline")

_COLS = sql.SQL(
    "a.agent_id, a.machine_id, a.hostname, a.agent_version, a.token_hash,"
    " a.token_issued_at, a.token_expires_at, a.token_revoked_at,"
    " a.prev_token_hash, a.prev_token_expires_at, a.last_rotation_at,"
    " a.status::text, a.last_heartbeat_at, a.last_inventory_at,"
    " host(a.last_seen_ip), a.runner_helpers, a.enrolled_at"
)
# b.enrol_base: when each agent became enrolled (#25 (c)), the approval that
# let it in or enrolled_at when it was auto-approved. One grouped scan of
# enrollment_request (it has no agent_id index), joined once, not per agent.
_ENROL = sql.SQL(
    "(SELECT x.agent_id, GREATEST(x.enrolled_at, r.approved_at) AS enrol_base"
    " FROM agent x LEFT JOIN (SELECT agent_id, max(decided_at) AS approved_at"
    " FROM enrollment_request WHERE decision = 'approved' GROUP BY agent_id) r"
    " ON r.agent_id = x.agent_id) b"
)
# The heartbeat age (#25 (c), #73 (b)). a.last_heartbeat_at is read from the
# row being updated, so a heartbeat committed meanwhile is the one used.
_AGE = sql.SQL("(%(now)s - GREATEST(a.last_heartbeat_at, b.enrol_base))")
# offline above offline_after and stale from stale_after, on the GREATEST age.
# online needs a heartbeat under stale_after old (TS §3.3 L218) made since the
# agent's enrolment or approval: younger than stale_after, that heartbeat is
# the age base itself. An agent with no heartbeat since then is enrolled, like
# one that never heartbeat (lead ruling 2026-10-23).
_TARGET = sql.SQL(
    "CASE WHEN {age} > %(offline)s THEN 'offline' WHEN {age} >= %(stale)s"
    " THEN 'stale' WHEN a.last_heartbeat_at >= b.enrol_base THEN 'online'"
    " ELSE 'enrolled' END"
).format(age=_AGE)


@dataclass(frozen=True)
class AgentRow:
    agent_id: UUID
    machine_id: str
    hostname: str
    agent_version: str
    token_hash: str = field(repr=False)
    token_issued_at: datetime
    token_expires_at: datetime
    token_revoked_at: datetime | None
    prev_token_hash: str | None = field(repr=False)
    prev_token_expires_at: datetime | None
    last_rotation_at: datetime | None
    status: str
    last_heartbeat_at: datetime | None
    last_inventory_at: datetime | None
    last_seen_ip: str | None
    runner_helpers: list[str]
    enrolled_at: datetime


@dataclass(frozen=True)
class AgentListRow:
    """One GET /agents item (#68)."""

    agent_id: UUID
    hostname: str
    status: str
    agent_version: str
    os_id: str | None
    os_version_id: str | None
    os_pretty_name: str | None
    last_heartbeat_at: datetime | None
    last_inventory_at: datetime | None
    tags: list[str]
    runner_helpers: list[str]


class AgentRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def _one(self, where: str, value: object, lock: bool = False) -> AgentRow | None:
        query = sql.SQL("SELECT {} FROM agent a WHERE {} = %s{}").format(
            _COLS, sql.Identifier("a", where), sql.SQL(" FOR UPDATE" if lock else "")
        )
        row = self._conn.execute(query, (value,)).fetchone()
        return None if row is None else AgentRow(*row)  # _COLS is in field order

    def _update(self, query: str, params: tuple[Any, ...]) -> bool:
        return self._conn.execute(query, params).rowcount == 1

    def find_by_token_hash(self, token_hash: str) -> AgentRow | None:
        return self._one("token_hash", token_hash)

    def find_by_prev_hash(self, token_hash: str) -> AgentRow | None:
        return self._one("prev_token_hash", token_hash)

    def find_by_machine_id(
        self, machine_id: str, *, lock: bool = False
    ) -> AgentRow | None:
        return self._one("machine_id", machine_id, lock)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        return self._one("agent_id", agent_id, lock)

    def insert(
        self,
        *,
        machine_id: str,
        hostname: str,
        agent_version: str,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        status: str,
        now: datetime,
    ) -> UUID | None:
        """The new agent_id, or None when the machine-id already has a row."""
        row = self._conn.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, enrolled_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS agent_status), %s)"
            " ON CONFLICT (machine_id) DO NOTHING RETURNING agent_id",
            (
                machine_id,
                hostname,
                agent_version,
                token_hash,
                issued_at,
                expires_at,
                status,
                now,
            ),
        ).fetchone()
        return None if row is None else UUID(str(row[0]))

    def set_status(
        self, agent_id: UUID, status: str, only_from: tuple[str, ...]
    ) -> bool:
        """Changes the row only while its status is one of only_from."""
        return self._update(
            "UPDATE agent SET status = CAST(%s AS agent_status) WHERE agent_id = %s"
            " AND status = ANY(CAST(%s AS agent_status[]))",
            (status, agent_id, list(only_from)),
        )

    def revoke(self, agent_id: UUID, now: datetime) -> bool:
        """Ends the current and any previous token (the check reads this column)."""
        return self._update(
            "UPDATE agent SET token_revoked_at = COALESCE(token_revoked_at, %s)"
            " WHERE agent_id = %s",
            (now, agent_id),
        )

    def rotate(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool:
        return self._update(
            "UPDATE agent SET prev_token_hash = token_hash, prev_token_expires_at ="
            " NULL, token_hash = %s, token_issued_at = %s, token_expires_at = %s,"
            " last_rotation_at = %s WHERE agent_id = %s",
            (new_hash, issued_at, expires_at, issued_at, agent_id),
        )

    def replace_unused_token(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool:
        """Lost-response retry: only while the rotated-in token is still unused."""
        return self._update(
            "UPDATE agent SET token_hash = %s, token_issued_at = %s,"
            " token_expires_at = %s WHERE agent_id = %s"
            " AND prev_token_hash IS NOT NULL AND prev_token_expires_at IS NULL",
            (new_hash, issued_at, expires_at, agent_id),
        )

    def mark_new_token_used(self, agent_id: UUID, overlap_until: datetime) -> bool:
        """True for exactly one caller: the first use after a rotation."""
        return self._update(
            "UPDATE agent SET prev_token_expires_at = %s WHERE agent_id = %s"
            " AND prev_token_hash IS NOT NULL AND prev_token_expires_at IS NULL",
            (overlap_until, agent_id),
        )

    def relink(
        self,
        agent_id: UUID,
        *,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        hostname: str,
        agent_version: str,
    ) -> bool:
        """An approved re-enrolment (#64): the request's token, all old token
        state cleared, status enrolled."""
        return self._update(
            "UPDATE agent SET token_hash = %s, token_issued_at = %s,"
            " token_expires_at = %s, token_revoked_at = NULL, prev_token_hash = NULL,"
            " prev_token_expires_at = NULL, last_rotation_at = NULL, hostname = %s,"
            " agent_version = %s, status = 'enrolled' WHERE agent_id = %s",
            (token_hash, issued_at, expires_at, hostname, agent_version, agent_id),
        )

    def record_heartbeat(
        self, agent_id: UUID, now: datetime, agent_version: str, helpers: list[str]
    ) -> bool:
        """Heartbeat columns; enrolled, stale and offline become online (#73 (a))."""
        return self._update(
            "UPDATE agent SET last_heartbeat_at = %s, agent_version = %s,"
            " runner_helpers = %s, status = CASE WHEN status IN"
            " ('enrolled', 'stale', 'offline') THEN 'online' ELSE status END"
            " WHERE agent_id = %s",
            (now, agent_version, Jsonb(helpers), agent_id),
        )

    def set_last_inventory(self, agent_id: UUID, now: datetime) -> bool:
        return self._update(
            "UPDATE agent SET last_inventory_at = %s WHERE agent_id = %s",
            (now, agent_id),
        )

    def ip_last_seen(self, agent_id: UUID, ip: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_seen_at FROM agent_ip_seen WHERE agent_id = %s"
            " AND ip = CAST(%s AS inet)",
            (agent_id, ip),
        ).fetchone()
        seen: datetime | None = None if row is None else row[0]
        return seen

    def record_ip(self, agent_id: UUID, ip: str, now: datetime) -> None:
        """agent.last_seen_ip and the agent_ip_seen upsert (#25 (b));
        first_seen_at is kept."""
        self._conn.execute(
            "INSERT INTO agent_ip_seen (agent_id, ip, first_seen_at, last_seen_at)"
            " VALUES (%s, CAST(%s AS inet), %s, %s) ON CONFLICT (agent_id, ip)"
            " DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at",
            (agent_id, ip, now, now),
        )
        self._conn.execute(
            "UPDATE agent SET last_seen_ip = CAST(%s AS inet) WHERE agent_id = %s",
            (ip, agent_id),
        )

    def tags(self, agent_id: UUID) -> list[str]:
        rows = self._conn.execute(
            "SELECT tag FROM agent_tag WHERE agent_id = %s ORDER BY tag", (agent_id,)
        ).fetchall()
        return [str(r[0]) for r in rows]

    def replace_tags(self, agent_id: UUID, tags: list[str]) -> None:
        """All or nothing with the caller's transaction; tags must be distinct."""
        self._conn.execute("DELETE FROM agent_tag WHERE agent_id = %s", (agent_id,))
        self._conn.execute(
            "INSERT INTO agent_tag (agent_id, tag)"
            " SELECT %s, unnest(CAST(%s AS varchar[]))",
            (agent_id, tags),
        )

    def list_page(self, limit: int, after_id: UUID | None) -> list[AgentListRow]:
        """GET /agents in (hostname, agent_id) order, keyset-paged after the
        agent after_id (the previous page's last row). The cursor holds only
        that id and its hostname is read here, in the caller's transaction
        (#89); AnchorGone if no such agent."""
        hostname: str | None = None
        agent_id: UUID | None = None
        if after_id is not None:
            anchor = self._conn.execute(
                "SELECT hostname, agent_id FROM agent WHERE agent_id = %s",
                (after_id,),
            ).fetchone()
            if anchor is None:
                raise AnchorGone
            hostname, agent_id = anchor
        rows = self._conn.execute(
            "SELECT a.agent_id, a.hostname, a.status::text, a.agent_version,"
            " o.os_id, o.os_version_id, o.os_pretty_name, a.last_heartbeat_at,"
            " a.last_inventory_at, ARRAY(SELECT t.tag FROM agent_tag t"
            " WHERE t.agent_id = a.agent_id ORDER BY t.tag), a.runner_helpers"
            " FROM agent a LEFT JOIN os_info o ON o.agent_id = a.agent_id"
            " WHERE CAST(%s AS text) IS NULL OR (a.hostname, a.agent_id) >"
            " (CAST(%s AS text), CAST(%s AS uuid))"
            " ORDER BY a.hostname, a.agent_id LIMIT %s",
            (hostname, hostname, agent_id, limit),
        ).fetchall()
        return [AgentListRow(*r) for r in rows]

    def count_by_status(self) -> Counter[str]:
        rows = self._conn.execute(
            "SELECT status::text, count(*) FROM agent GROUP BY status"
        ).fetchall()
        return Counter({str(s): int(n) for s, n in rows})

    def apply_heartbeat_ages(
        self, now: datetime, stale_after: timedelta, offline_after: timedelta
    ) -> int:
        """The sweep's status step: one statement over the SWEPT statuses, so a
        heartbeat committed meanwhile is re-read before the row changes."""
        query = sql.SQL(
            "UPDATE agent a SET status = CAST({t} AS agent_status) FROM {enrol}"
            " WHERE b.agent_id = a.agent_id"
            " AND a.status = ANY(CAST(%(swept)s AS agent_status[]))"
            " AND a.status::text <> {t}"
        ).format(t=_TARGET, enrol=_ENROL)
        params = {"now": now, "stale": stale_after, "offline": offline_after}
        return self._conn.execute(query, {**params, "swept": list(SWEPT)}).rowcount

    def decommission_offline(self, now: datetime, after: timedelta) -> list[UUID]:
        """offline agents older than after: decommissioned, token revoked."""
        query = sql.SQL(
            "UPDATE agent a SET status = 'decommissioned', token_revoked_at ="
            " COALESCE(a.token_revoked_at, %(now)s) FROM {enrol}"
            " WHERE b.agent_id = a.agent_id AND a.status = 'offline'"
            " AND {age} > %(after)s RETURNING a.agent_id"
        ).format(age=_AGE, enrol=_ENROL)
        rows = self._conn.execute(query, {"now": now, "after": after}).fetchall()
        return [UUID(str(r[0])) for r in rows]

    def stale_inventory(self, now: datetime, older_than: timedelta) -> list[UUID]:
        """online agents whose last inventory (or enrolment, #65 (c)) is older."""
        query = sql.SQL(
            "SELECT a.agent_id FROM agent a JOIN {enrol} ON b.agent_id = a.agent_id"
            " WHERE a.status = 'online'"
            " AND %(now)s - COALESCE(a.last_inventory_at, b.enrol_base) > %(older)s"
            " ORDER BY a.agent_id"
        ).format(enrol=_ENROL)
        rows = self._conn.execute(query, {"now": now, "older": older_than}).fetchall()
        return [UUID(str(r[0])) for r in rows]
