"""Catalog admin SQL: profile list and detail, status and soft delete (TS §4.3,
§5.2; #98, #104). Parameterised statements only. The #103 start-up reads are
in catalog_integrity.

Each function runs in the caller's transaction and never commits. Grants used
(TS §5.2 L1005–L1013): UPDATE on policy and plugin, UPDATE of state and
finished_at on scan_job, UPDATE on scan_schedule, SELECT on v_plugin. A
policy is never DELETEd: a delete sets deleted_at (TS §4.3 L550).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

import psycopg
from psycopg import sql

type Conn = psycopg.Connection[Any]

_ITEM: Final = sql.SQL(
    "p.policy_id, p.policy_name, p.policy_description, p.policy_status::text,"
    " p.file_status::text, p.status_overridden, p.family_id, f.family_name,"
    " p.format_version, p.version, p.source_file, {count}, p.imported_at,"
    " p.updated_at"
)
_COUNT: Final = sql.SQL(
    "(SELECT count(*) FROM policy_plugin pp WHERE pp.policy_id = p.policy_id)"
)
_FROM: Final = sql.SQL(" FROM policy p JOIN family f ON f.family_id = p.family_id")


@dataclass(frozen=True)
class ProfileItem:
    """One GET /policies item, in the #98 (a) field order."""

    policy_id: int
    policy_name: str
    policy_description: str
    policy_status: str
    file_status: str
    status_overridden: bool
    family_id: int
    family_name: str
    format_version: str
    version: int
    source_file: str
    plugin_count: int
    imported_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProfilePlugin:
    """One plugin of a detail, in the #98 (b) field order."""

    plugin_uuid: UUID
    sort_order: int
    display_name: str
    plugin_name: str
    control_ref: str | None
    plugin_description: str
    execute: str
    execute_sha256: str
    operator: str
    expected_result: str
    timeout_s: int
    state: str
    updated_at: datetime


@dataclass(frozen=True)
class ProfileDetail:
    item: ProfileItem
    deleted_at: datetime | None
    plugins: list[ProfilePlugin]


@dataclass(frozen=True)
class PolicyState:
    """The row as locked for a status change or a delete."""

    policy_id: int
    policy_status: str
    file_status: str
    status_overridden: bool
    source_file: str
    deleted_at: datetime | None


@dataclass(frozen=True)
class DeleteEffects:
    cancelled_job_ids: list[UUID]
    disabled_schedule_ids: list[int]
    retired_plugin_uuids: list[UUID]


def list_page(
    conn: Conn,
    limit: int,
    status: Literal["enabled", "disabled"] | None,
    after: tuple[str, int] | None,
) -> list[ProfileItem]:
    """Non-deleted policies (#9), by effective status if given, in
    (policy_name, policy_id) order, keyset after `after`."""
    name, policy_id = after if after is not None else (None, None)
    query = sql.SQL(
        "SELECT {item}{from_} WHERE p.deleted_at IS NULL AND"
        " (CAST(%(st)s AS policy_status) IS NULL OR"
        " p.policy_status = CAST(%(st)s AS policy_status)) AND"
        " (CAST(%(name)s AS varchar) IS NULL OR (p.policy_name, p.policy_id) >"
        " (CAST(%(name)s AS varchar), CAST(%(id)s AS bigint)))"
        " ORDER BY p.policy_name, p.policy_id LIMIT %(limit)s"
    ).format(item=_ITEM.format(count=_COUNT), from_=_FROM)
    params = {"st": status, "name": name, "id": policy_id, "limit": limit}
    return [ProfileItem(*r) for r in conn.execute(query, params).fetchall()]


def item(conn: Conn, policy_id: int) -> ProfileItem | None:
    """One policy in the list shape, deleted or not (the PATCH answer)."""
    query = sql.SQL("SELECT {item}{from_} WHERE p.policy_id = %s").format(
        item=_ITEM.format(count=_COUNT), from_=_FROM
    )
    row = conn.execute(query, (policy_id,)).fetchone()
    return None if row is None else ProfileItem(*row)


# One statement, so the policy and its plugins come from one snapshot; the
# plugins of a deleted policy are kept and shown (#104 (a)).
_DETAIL: Final = sql.SQL(
    "SELECT {item}, p.deleted_at, COALESCE((SELECT json_agg(json_build_array("
    "v.plugin_uuid, pp.sort_order, v.display_name, v.plugin_name, v.control_ref,"
    " v.plugin_description, v.execute, v.execute_sha256, v.operator,"
    " v.expected_result, v.timeout_s, v.state, v.updated_at)"
    " ORDER BY pp.sort_order, pp.plugin_uuid) FROM policy_plugin pp"
    " JOIN v_plugin v ON v.plugin_uuid = pp.plugin_uuid"
    " WHERE pp.policy_id = p.policy_id), '[]'){from_} WHERE p.policy_id = %s"
).format(item=_ITEM.format(count=sql.SQL("0")), from_=_FROM)


def detail(conn: Conn, policy_id: int) -> ProfileDetail | None:
    """GET /policies/{id} (#98 (b)): plugins in sort_order with display_name
    from v_plugin; a deleted policy is returned with deleted_at (#9)."""
    row = conn.execute(_DETAIL, (policy_id,)).fetchone()
    if row is None:
        return None
    # json_build_array order = ProfilePlugin order; uuid and timestamp
    # arrive as JSON strings.
    plugins = [
        ProfilePlugin(*[UUID(p[0]), *p[1:12], datetime.fromisoformat(p[12])])
        for p in row[15]
    ]
    head = ProfileItem(*[*row[:11], len(plugins), *row[12:14]])
    return ProfileDetail(head, row[14], plugins)


def lock(conn: Conn, policy_id: int) -> PolicyState | None:
    """The row FOR UPDATE, so the caller decides on state re-read under lock."""
    row = conn.execute(
        "SELECT policy_id, policy_status::text, file_status::text,"
        " status_overridden, source_file, deleted_at FROM policy"
        " WHERE policy_id = %s FOR UPDATE",
        (policy_id,),
    ).fetchone()
    return None if row is None else PolicyState(*row)


def set_status(
    conn: Conn, policy_id: int, status: Literal["enabled", "disabled"], now: datetime
) -> bool:
    """An admin override (REQ-168): policy_status and status_overridden = true.
    False for a deleted or unknown policy. updated_at moves only on a change
    (#104 (d))."""
    return (
        conn.execute(
            "UPDATE policy SET policy_status = CAST(%(s)s AS policy_status),"
            " status_overridden = true, updated_at = CASE WHEN status_overridden"
            " AND policy_status = CAST(%(s)s AS policy_status) THEN updated_at"
            " ELSE %(now)s END WHERE policy_id = %(id)s AND deleted_at IS NULL",
            {"s": status, "now": now, "id": policy_id},
        ).rowcount
        == 1
    )


def clear_override(conn: Conn, policy_id: int, now: datetime) -> bool:
    """policy_status back to file_status, override cleared (TS §4.3 L548)."""
    return (
        conn.execute(
            "UPDATE policy SET policy_status = file_status, status_overridden ="
            " false, updated_at = CASE WHEN NOT status_overridden AND"
            " policy_status = file_status THEN updated_at ELSE %s END"
            " WHERE policy_id = %s AND deleted_at IS NULL",
            (now, policy_id),
        ).rowcount
        == 1
    )


def soft_delete_effects(
    conn: Conn, policy_id: int, now: datetime
) -> DeleteEffects | None:
    """The TS §4.3 L550 database effects, or None (and nothing changed) when
    the policy is unknown or already deleted. Only queued compliance jobs are
    cancelled; dispatched and running ones finish. Retired: active plugins it
    owns or lists that no non-deleted policy lists (#104 (b)). The uploaded
    file is the caller's, after commit."""
    params = {"id": policy_id, "now": now}
    if (
        conn.execute(
            "UPDATE policy SET deleted_at = %(now)s, source_file = 'deleted/' ||"
            " policy_id, updated_at = %(now)s WHERE policy_id = %(id)s"
            " AND deleted_at IS NULL",
            params,
        ).rowcount
        != 1
    ):
        return None
    jobs = conn.execute(
        "UPDATE scan_job SET state = 'cancelled', finished_at = %(now)s"
        " WHERE kind = 'compliance' AND state = 'queued'"
        " AND scan_id IN (SELECT scan_id FROM scan WHERE policy_id = %(id)s)"
        " RETURNING job_id",
        params,
    ).fetchall()
    schedules = conn.execute(
        "UPDATE scan_schedule SET enabled = false WHERE policy_id = %(id)s"
        " AND enabled RETURNING schedule_id",
        params,
    ).fetchall()
    plugins = conn.execute(
        "UPDATE plugin pl SET state = 'retired', updated_at = %(now)s"
        " WHERE pl.state = 'active' AND (pl.owner_policy_id = %(id)s OR EXISTS"
        " (SELECT 1 FROM policy_plugin m WHERE m.policy_id = %(id)s"
        " AND m.plugin_uuid = pl.plugin_uuid)) AND NOT EXISTS (SELECT 1"
        " FROM policy_plugin pp JOIN policy o ON o.policy_id = pp.policy_id"
        " WHERE pp.plugin_uuid = pl.plugin_uuid AND o.deleted_at IS NULL)"
        " RETURNING pl.plugin_uuid",
        params,
    ).fetchall()
    return DeleteEffects(
        sorted(UUID(str(r[0])) for r in jobs),
        sorted(int(r[0]) for r in schedules),
        sorted(UUID(str(r[0])) for r in plugins),
    )
