"""Schema-diff helper (TP-M1-05; REQ-027; question #40, answered 2026-10-20).

Reference: the TS §5.2 DDL and display-name blocks, read from the spec at test
time and applied as ``bitscan_owner`` to a separate scratch database (never the
database under test). Both databases are dumped with the same catalog queries
and compared object by object. Excluded everywhere: ``alembic_version`` (#41)
and the monthly ``scan_result`` partitions (REQ-026, date-dependent).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .spec_sql import SPEC, sql_block_after

DDL_HEADING = "### 5.2 DDL"
VIEW_HEADING = "**Display name.**"
EXCLUDED_TABLES = frozenset({"alembic_version"})

Dump = dict[str, dict[str, Any]]


def reference_sql(text: str | None = None) -> tuple[str, str]:
    """The TS §5.2 DDL block and the v_plugin view block, verbatim."""
    if text is None:
        text = SPEC.read_text(encoding="utf-8")
    ddl = "\n".join(sql_block_after(text, DDL_HEADING))
    view = "\n".join(sql_block_after(text, VIEW_HEADING))
    return ddl, view


@dataclass(frozen=True)
class Scope:
    """Which objects to compare; None means every object in schema public."""

    tables: frozenset[str] | None = None
    types: frozenset[str] | None = None
    functions: frozenset[str] | None = None
    views: frozenset[str] | None = None
    acls: bool = True

    @staticmethod
    def of(
        tables: Iterable[str] = (),
        types: Iterable[str] = (),
        functions: Iterable[str] = (),
        views: Iterable[str] = (),
        acls: bool = False,
    ) -> "Scope":
        return Scope(
            frozenset(tables),
            frozenset(types),
            frozenset(functions),
            frozenset(views),
            acls,
        )


ALL = Scope()


def _rows(conn: Any, query: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(query.encode()).fetchall()]


TABLES = """
SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner),
       coalesce(pg_get_partkeydef(c.oid), ''),
       coalesce(pg_get_expr(c.relpartbound, c.oid), ''),
       coalesce(p.relname, ''),
       coalesce((SELECT array_agg(a::text ORDER BY a::text)
                 FROM aclexplode(c.relacl) a), '{}')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_inherits i ON i.inhrelid = c.oid
LEFT JOIN pg_class p ON p.oid = i.inhparent
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  AND NOT (c.relispartition AND pg_get_expr(c.relpartbound, c.oid) <> 'DEFAULT')
"""
COLUMNS = """
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod),
       a.attnotnull, coalesce(pg_get_expr(d.adbin, d.adrelid), ''),
       a.attgenerated, a.attidentity,
       coalesce((SELECT array_agg(x::text ORDER BY x::text)
                 FROM aclexplode(a.attacl) x), '{}')
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v')
  AND a.attnum > 0 AND NOT a.attisdropped
"""
CONSTRAINTS = """
SELECT c.relname, k.conname, k.contype, pg_get_constraintdef(k.oid, true)
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
"""
INDEXES = """
SELECT t.relname, i.relname, pg_get_indexdef(i.oid), pg_get_userbyid(i.relowner)
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
"""
TYPES = """
SELECT t.typname, t.typtype, pg_get_userbyid(t.typowner),
       coalesce((SELECT array_agg(e.enumlabel::text ORDER BY e.enumsortorder)
                 FROM pg_enum e WHERE e.enumtypid = t.oid), '{}')
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'r', 'm')
"""
SEQUENCES = """
SELECT s.relname, pg_get_userbyid(s.relowner), format_type(q.seqtypid, NULL),
       q.seqstart, q.seqincrement, q.seqmin, q.seqmax, q.seqcycle,
       coalesce(t.relname || '.' || a.attname, ''),
       coalesce((SELECT array_agg(x::text ORDER BY x::text)
                 FROM aclexplode(s.relacl) x), '{}')
FROM pg_class s
JOIN pg_namespace n ON n.oid = s.relnamespace
JOIN pg_sequence q ON q.seqrelid = s.oid
LEFT JOIN pg_depend d ON d.objid = s.oid AND d.classid = 'pg_class'::regclass
     AND d.refclassid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')
LEFT JOIN pg_class t ON t.oid = d.refobjid
LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
WHERE n.nspname = 'public' AND s.relkind = 'S'
"""
FUNCTIONS = """
SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       pg_get_userbyid(p.proowner), pg_get_functiondef(p.oid)
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d
                  WHERE d.objid = p.oid AND d.deptype = 'e')
"""
TRIGGERS = """
SELECT c.relname, g.tgname, pg_get_triggerdef(g.oid, true)
FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND NOT g.tgisinternal
"""
VIEWS = """
SELECT c.relname, pg_get_userbyid(c.relowner), pg_get_viewdef(c.oid, true),
       coalesce((SELECT array_agg(x::text ORDER BY x::text)
                 FROM aclexplode(c.relacl) x), '{}')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'v'
"""
EXTENSIONS = "SELECT extname FROM pg_extension WHERE extname <> 'plpgsql'"
DEFAULT_ACLS = """
SELECT pg_get_userbyid(d.defaclrole), coalesce(n.nspname, ''), d.defaclobjtype,
       coalesce((SELECT array_agg(x::text ORDER BY x::text)
                 FROM aclexplode(d.defaclacl) x), '{}')
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
"""


def _keep_table(name: str, scope: Scope, kept: set[str]) -> bool:
    if name in EXCLUDED_TABLES:
        return False
    return name in kept if scope.tables is not None else True


def dump(conn: Any, scope: Scope = ALL) -> Dump:
    """Catalog of schema public as comparable values, keyed by object."""
    out: Dump = {
        k: {}
        for k in (
            "extension",
            "type",
            "table",
            "column",
            "constraint",
            "index",
            "sequence",
            "function",
            "trigger",
            "view",
            "default_acl",
        )
    }
    tables = {r[0]: r for r in _rows(conn, TABLES)}
    kept = {
        name
        for name in tables
        if name not in EXCLUDED_TABLES
        and (scope.tables is None or name in scope.tables)
    }
    for name in sorted(kept):
        _, kind, owner, partkey, bound, parent, acl = tables[name]
        out["table"][name] = {
            "kind": kind,
            "owner": owner,
            "partkey": partkey,
            "bound": bound,
            "parent": parent,
        }
        if scope.acls:
            out["table"][name]["acl"] = acl
    for ext in _rows(conn, EXTENSIONS):
        out["extension"][ext[0]] = True
    for name, typtype, owner, labels in _rows(conn, TYPES):
        if scope.types is None or name in scope.types:
            out["type"][name] = {"type": typtype, "owner": owner, "labels": labels}
    views = {r[0]: r for r in _rows(conn, VIEWS)}
    kept_views = {v for v in views if scope.views is None or v in scope.views}
    for name in sorted(kept_views):
        _, owner, definition, acl = views[name]
        out["view"][name] = {"owner": owner, "definition": definition}
        if scope.acls:
            out["view"][name]["acl"] = acl
    for table, num, col, typ, notnull, default, gen, ident, acl in _rows(conn, COLUMNS):
        if table in kept or table in kept_views:
            value: dict[str, object] = {
                "position": num,
                "type": typ,
                "notnull": notnull,
                "default": default,
                "generated": gen,
                "identity": ident,
            }
            if scope.acls:
                value["acl"] = acl
            out["column"][f"{table}.{col}"] = value
    for table, name, contype, definition in _rows(conn, CONSTRAINTS):
        if table in kept:
            out["constraint"][f"{table}.{name}"] = {"type": contype, "def": definition}
    for table, name, definition, owner in _rows(conn, INDEXES):
        if table in kept:
            out["index"][name] = {"def": definition, "owner": owner}
    for row in _rows(conn, SEQUENCES):
        name, owner, typ, start, inc, mn, mx, cycle, owned_by, acl = row
        owner_table = owned_by.split(".")[0] if owned_by else ""
        if (owner_table and _keep_table(owner_table, scope, kept)) or (
            not owner_table and scope.tables is None
        ):
            seq: dict[str, object] = {
                "owner": owner,
                "type": typ,
                "start": start,
                "increment": inc,
                "min": mn,
                "max": mx,
                "cycle": cycle,
                "owned_by": owned_by,
            }
            if scope.acls:
                seq["acl"] = acl
            out["sequence"][name] = seq
    for signature, owner, definition in _rows(conn, FUNCTIONS):
        if scope.functions is None or signature.split("(")[0] in scope.functions:
            out["function"][signature] = {"owner": owner, "def": definition}
    for table, name, definition in _rows(conn, TRIGGERS):
        if table in kept:
            out["trigger"][f"{table}.{name}"] = {"def": definition}
    if scope.acls and scope.tables is None:
        for role, schema, objtype, acl in _rows(conn, DEFAULT_ACLS):
            out["default_acl"][f"{role}/{schema}/{objtype}"] = {"acl": acl}
    return out


def diff(
    reference: Mapping[str, Mapping[str, Any]],
    actual: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Human-readable differences; empty means diff-equal."""
    problems: list[str] = []
    for kind in sorted(set(reference) | set(actual)):
        ref, got = reference.get(kind, {}), actual.get(kind, {})
        for key in sorted(set(ref) - set(got)):
            problems.append(f"missing {kind} {key}")
        for key in sorted(set(got) - set(ref)):
            problems.append(f"extra {kind} {key}")
        for key in sorted(set(ref) & set(got)):
            if ref[key] != got[key]:
                problems.append(
                    f"different {kind} {key}: spec={ref[key]!r} got={got[key]!r}"
                )
    return problems
