"""Catalog SQL for imports: family and policy rows, and the plugin owners
BIT015 needs (SR §3.1, §3.2, §3.6; TS §5.2). Parameterised statements only.
Plugin rows and policy_plugin are in catalog_plugins.

Each function runs in the caller's transaction or savepoint (the store, under
the catalog lock) and never commits. bitscan_app has INSERT and UPDATE on
family and policy and USAGE on the sequences, and no DELETE on either: family
rows are kept (#104 (e)) and a policy is only ever soft-deleted.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

type Conn = psycopg.Connection[Any]
_POLICY_FIELDS: Final = (
    "policy_id, policy_name, policy_description, policy_status, file_status,"
    " status_overridden, family_id, format_version, version, source_file,"
    " source_sha256, deleted_at, imported_at, updated_at"
).split(", ")
_P: Final = sql.SQL(", ").join(
    sql.SQL("{}::text").format(sql.Identifier("p", c))
    if c.endswith("_status")
    else sql.Identifier("p", c)
    for c in _POLICY_FIELDS
)


@dataclass(frozen=True)
class PolicyRow:
    policy_id: int
    policy_name: str
    policy_description: str
    policy_status: str
    file_status: str
    status_overridden: bool
    family_id: int
    format_version: str
    version: int
    source_file: str
    source_sha256: str
    deleted_at: datetime | None
    imported_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PolicyValues:
    """One file's policy values, trimmed and validated (file_status lowercase);
    source_file is relative to the server folder."""

    policy_name: str
    policy_description: str
    file_status: str
    family_id: int
    format_version: str
    source_file: str
    source_sha256: str


@dataclass(frozen=True)
class Owner:
    """The current owner of an existing plugin, for BIT015."""

    plugin_uuid: UUID
    owner_id: int
    owner_name: str
    owner_deleted: bool
    owner_lists: bool  # a policy_plugin row (owner, plugin) exists


def _policy(conn: Conn, column: str, value: object) -> PolicyRow | None:
    query = sql.SQL("SELECT {} FROM policy p WHERE {} = %s FOR UPDATE").format(
        _P, sql.Identifier("p", column)
    )
    row = conn.execute(query, (value,)).fetchone()
    return None if row is None else PolicyRow(*row)


def policy_by_name_for_update(conn: Conn, policy_name: str) -> PolicyRow | None:
    return _policy(conn, "policy_name", policy_name)


def policy_by_source_file_for_update(conn: Conn, source_file: str) -> PolicyRow | None:
    return _policy(conn, "source_file", source_file)


def policy_by_id_for_update(conn: Conn, policy_id: int) -> PolicyRow | None:
    return _policy(conn, "policy_id", policy_id)


def upsert_family(conn: Conn, family_name: str, now: datetime) -> int:
    """INSERT … ON CONFLICT DO NOTHING, then SELECT; rows are never changed."""
    row = conn.execute(
        "INSERT INTO family (family_name, created_at) VALUES (%s, %s)"
        " ON CONFLICT (family_name) DO NOTHING RETURNING family_id",
        (family_name, now),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT family_id FROM family WHERE family_name = %s", (family_name,)
        ).fetchone()
    if row is None:  # unreachable: family rows are never removed
        raise LookupError("family row missing after upsert")
    return int(row[0])


def next_policy_id(conn: Conn) -> int:
    """The id for insert_policy, known first so that an upload's source_file
    (uploaded/policy-<id>.bit) can name it."""
    row = conn.execute("SELECT nextval('policy_policy_id_seq')").fetchone()
    if row is None:
        raise LookupError("nextval gave no row")
    return int(row[0])


def _params(values: PolicyValues, now: datetime, policy_id: int) -> dict[str, object]:
    return {**asdict(values), "id": policy_id, "now": now}


_INSERT_POLICY: Final = sql.SQL(
    "INSERT INTO policy AS p (policy_id, policy_name, policy_description,"
    " policy_status, file_status, family_id, format_version, version,"
    " source_file, source_sha256, imported_at, updated_at) VALUES (%(id)s,"
    " %(policy_name)s, %(policy_description)s, CAST(%(file_status)s AS"
    " policy_status), CAST(%(file_status)s AS policy_status), %(family_id)s,"
    " %(format_version)s, 1, %(source_file)s, %(source_sha256)s, %(now)s,"
    " %(now)s) RETURNING {}"
).format(_P)


def insert_policy(
    conn: Conn, policy_id: int, values: PolicyValues, now: datetime
) -> PolicyRow:
    """A new policy at version 1 whose effective status is the file's."""
    row = conn.execute(_INSERT_POLICY, _params(values, now, policy_id)).fetchone()
    if row is None:
        raise LookupError("INSERT … RETURNING gave no row")
    return PolicyRow(*row)


# v types each parameter once. version: +1 when the hash differs (SR §3.6
# step 2) and on every revival (#14). policy_status keeps an admin override, in
# the statement itself (D3); status_overridden is never written. updated_at
# moves only when a stored column changes (#104 (d)).
_EFF: Final = sql.SQL(
    "CASE WHEN p.status_overridden THEN p.policy_status ELSE v.st END"
)
_UPDATE_POLICY: Final = sql.SQL(
    "WITH v (name, descr, st, fam, fmt, file, sha) AS (VALUES"
    " (CAST(%(policy_name)s AS varchar), CAST(%(policy_description)s AS text),"
    " CAST(%(file_status)s AS policy_status), CAST(%(family_id)s AS bigint),"
    " CAST(%(format_version)s AS varchar), CAST(%(source_file)s AS text),"
    " CAST(%(source_sha256)s AS char(64))))"
    " UPDATE policy p SET policy_name = v.name, policy_description = v.descr,"
    " file_status = v.st, policy_status = {eff}, family_id = v.fam,"
    " format_version = v.fmt, version = p.version + CASE WHEN"
    " p.source_sha256 <> v.sha OR p.deleted_at IS NOT NULL THEN 1 ELSE 0 END,"
    " source_file = v.file, source_sha256 = v.sha, deleted_at = NULL,"
    " imported_at = %(now)s, updated_at = CASE WHEN p.deleted_at IS NOT NULL OR"
    " (p.policy_name, p.policy_description, p.file_status, p.policy_status,"
    " p.family_id, p.format_version, p.source_file, p.source_sha256)"
    " IS DISTINCT FROM (v.name, v.descr, v.st, {eff}, v.fam, v.fmt, v.file, v.sha)"
    " THEN %(now)s ELSE p.updated_at END FROM v WHERE p.policy_id = %(id)s"
    " RETURNING {cols}"
).format(eff=_EFF, cols=_P)


def update_policy(
    conn: Conn, policy_id: int, values: PolicyValues, now: datetime
) -> PolicyRow | None:
    """The file's values onto an existing row (update, rename in place, move
    or revival), deleted_at cleared. None for an unknown id."""
    row = conn.execute(_UPDATE_POLICY, _params(values, now, policy_id)).fetchone()
    return None if row is None else PolicyRow(*row)


def owners_of(conn: Conn, plugin_uuids: Sequence[UUID]) -> list[Owner]:
    """BIT015 inputs for every existing id in one query; new ids are absent."""
    rows = conn.execute(
        "SELECT pl.plugin_uuid, o.policy_id, o.policy_name, o.deleted_at IS NOT NULL,"
        " EXISTS (SELECT 1 FROM policy_plugin pp WHERE pp.policy_id = o.policy_id"
        " AND pp.plugin_uuid = pl.plugin_uuid) FROM plugin pl"
        " JOIN policy o ON o.policy_id = pl.owner_policy_id"
        " WHERE pl.plugin_uuid = ANY(CAST(%s AS uuid[])) ORDER BY pl.plugin_uuid",
        (list(plugin_uuids),),
    ).fetchall()
    return [
        Owner(UUID(str(u)), int(i), str(n), bool(d), bool(x)) for u, i, n, d, x in rows
    ]
