"""REQ-027: the final migrated schema equals TS §5.2 (TP-M1-12; G19).

Checks CHK-M1-150 and CHK-M1-151. The reference is the spec DDL and view applied
as bitscan_owner to bitscan_ref (#40); the comparison now covers every object in
schema public, including table, column and sequence ACLs and default ACLs.
"""

import pytest

from . import schema_diff
from .conftest import REFERENCE_DB, Conn, PgServer
from .schema_diff import ALL, diff, dump


@pytest.mark.pg
def test_migrated_schema_equals_the_spec(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with (
        migrated_db.connect("bitscan_migrate") as got,
        reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref,
    ):
        reference, actual = dump(ref, ALL), dump(got, ALL)
    assert reference["table"] and reference["default_acl"] and reference["view"]
    problems = diff(reference, actual)
    assert problems == [], "\n".join(problems)


def _relations(conn: Conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid ="
            " c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
        ).fetchall()
    }


@pytest.mark.pg
def test_only_alembic_version_and_monthly_partitions_are_excluded(
    migrated_db: PgServer,
) -> None:
    assert schema_diff.EXCLUDED_TABLES == frozenset({"alembic_version"})
    with migrated_db.connect("bitscan_migrate") as conn:
        excluded = _relations(conn) - set(dump(conn, ALL)["table"])
    monthly = {t for t in excluded if t.startswith("scan_result_2")}
    assert excluded == {"alembic_version", *monthly}
    assert len(monthly) == 4
