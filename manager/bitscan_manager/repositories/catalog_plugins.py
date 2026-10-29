"""Catalog SQL for imports: plugin and policy_plugin rows (SR §3.3, §3.4,
§3.6 steps 3 to 5; TS §5.2). Parameterised statements only.

Each function runs in the caller's transaction or savepoint (the store, under
the catalog lock) and never commits. bitscan_app has INSERT and UPDATE on
plugin and INSERT and DELETE on policy_plugin. It has no DELETE on plugin:
plugins no policy lists are retired, never removed, so old results stay
readable (TS §4.1 L519).
"""

from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

type Conn = psycopg.Connection[Any]
BATCH: Final = 500  # plugin rows per upsert statement (TASK-151 plan §3.4)


@dataclass(frozen=True)
class PluginValues:
    plugin_uuid: UUID
    plugin_name: str
    control_ref: str | None
    plugin_description: str
    execute: str
    execute_sha256: str
    timeout_s: int
    operator: str
    expected_result: str


def current_plugins(conn: Conn, plugin_uuids: Sequence[UUID]) -> dict[UUID, str]:
    """The stored execute_sha256 of each existing id (#100 (a))."""
    rows = conn.execute(
        "SELECT plugin_uuid, execute_sha256 FROM plugin"
        " WHERE plugin_uuid = ANY(CAST(%s AS uuid[]))",
        (list(plugin_uuids),),
    ).fetchall()
    return {UUID(str(u)): str(h) for u, h in rows}


def retired_among(conn: Conn, plugin_uuids: Sequence[UUID]) -> frozenset[UUID]:
    """Those of the given ids whose plugin is retired now (#100 (a), read
    before the import changes anything); unknown ids are not in it."""
    if not plugin_uuids:
        return frozenset()
    rows = conn.execute(
        "SELECT plugin_uuid FROM plugin WHERE state = 'retired'"
        " AND plugin_uuid = ANY(CAST(%s AS uuid[]))",
        (list(plugin_uuids),),
    ).fetchall()
    return frozenset(UUID(str(r[0])) for r in rows)


_COLS: Final = (
    "plugin_name, control_ref, plugin_description, execute, execute_sha256,"
    " timeout_s, operator, expected_result, state"
).split(", ")


def _join(alias: str) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(alias, c) for c in _COLS)


# old is read with the statement's snapshot, so a uuid in it existed before
# this statement: that decides "inserted" without relying on xmax. The WHERE
# skips rows whose stored columns are all unchanged; they are not returned (#21).
_UPSERT_PLUGINS: Final = sql.SQL(
    "WITH v AS (SELECT * FROM unnest(CAST(%(plugin_uuid)s AS uuid[]),"
    " CAST(%(plugin_name)s AS varchar[]), CAST(%(control_ref)s AS varchar[]),"
    " CAST(%(plugin_description)s AS text[]), CAST(%(execute)s AS text[]),"
    " CAST(%(execute_sha256)s AS char(64)[]), CAST(%(timeout_s)s AS integer[]),"
    " CAST(%(operator)s AS plugin_operator[]), CAST(%(expected_result)s AS text[]))"
    " AS u (plugin_uuid, plugin_name, control_ref, plugin_description, execute,"
    " execute_sha256, timeout_s, operator, expected_result)),"
    " old AS MATERIALIZED (SELECT o.plugin_uuid FROM plugin o"
    " WHERE o.plugin_uuid = ANY(CAST(%(plugin_uuid)s AS uuid[])))"
    " INSERT INTO plugin AS p (plugin_uuid, family_id, owner_policy_id, {cols},"
    " updated_at) SELECT v.plugin_uuid, %(fam)s, %(owner)s, {vals}, %(now)s"
    " FROM v ON CONFLICT (plugin_uuid) DO UPDATE SET"
    " family_id = EXCLUDED.family_id, owner_policy_id = EXCLUDED.owner_policy_id,"
    " {sets}, updated_at = EXCLUDED.updated_at"
    " WHERE (p.family_id, p.owner_policy_id, {pc}) IS DISTINCT FROM"
    " (EXCLUDED.family_id, EXCLUDED.owner_policy_id, {ec})"
    " RETURNING p.plugin_uuid, p.plugin_uuid NOT IN (SELECT plugin_uuid FROM old)"
).format(
    cols=sql.SQL(", ").join(sql.Identifier(c) for c in _COLS),
    vals=sql.SQL(", ").join(
        [sql.Identifier("v", c) for c in _COLS[:-1]]
        + [sql.SQL("CAST('active' AS plugin_state)")]
    ),
    sets=sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Identifier("excluded", c))
        for c in _COLS
    ),
    pc=_join("p"),
    ec=_join("excluded"),
)


_PLUGIN_FIELDS: Final = tuple(f.name for f in fields(PluginValues))


def upsert_plugins(
    conn: Conn,
    plugins: Sequence[PluginValues],
    *,
    family_id: int,
    owner_policy_id: int,
    now: datetime,
) -> list[tuple[UUID, bool]]:
    """Each plugin by plugin_uuid, active and owned by owner_policy_id, in
    batches of BATCH rows. Returns (uuid, inserted) for the rows inserted or
    changed. plugin_uuid must be unique in plugins (BIT005)."""
    written: list[tuple[UUID, bool]] = []
    for start in range(0, len(plugins), BATCH):
        part = plugins[start : start + BATCH]
        rows = conn.execute(
            _UPSERT_PLUGINS,
            {f: [getattr(p, f) for p in part] for f in _PLUGIN_FIELDS}
            | {"fam": family_id, "owner": owner_policy_id, "now": now},
        ).fetchall()
        written += [(UUID(str(u)), bool(i)) for u, i in rows]
    return written


def replace_membership(
    conn: Conn, policy_id: int, plugin_uuids: Sequence[UUID]
) -> None:
    """The policy's policy_plugin rows, sort_order 1-based in the given order."""
    conn.execute("DELETE FROM policy_plugin WHERE policy_id = %s", (policy_id,))
    conn.execute(
        "INSERT INTO policy_plugin (policy_id, plugin_uuid, sort_order)"
        " SELECT %s, t.u, t.n FROM unnest(CAST(%s AS uuid[]))"
        " WITH ORDINALITY AS t (u, n)",
        (policy_id, list(plugin_uuids)),
    )


def retire_unreferenced(conn: Conn, now: datetime) -> list[UUID]:
    """Active plugins that no non-deleted policy lists become retired (#104
    (b)); rows are never deleted. Returns the plugins it changed."""
    rows = conn.execute(
        "UPDATE plugin pl SET state = 'retired', updated_at = %s"
        " WHERE pl.state = 'active' AND NOT EXISTS (SELECT 1 FROM policy_plugin pp"
        " JOIN policy o ON o.policy_id = pp.policy_id"
        " WHERE pp.plugin_uuid = pl.plugin_uuid AND o.deleted_at IS NULL)"
        " RETURNING pl.plugin_uuid",
        (now,),
    ).fetchall()
    return sorted(UUID(str(r[0])) for r in rows)
