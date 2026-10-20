"""REQ-029: Debian version comparison through debversion (TP-M1-07).

Checks CHK-M1-100 to CHK-M1-106. The fixture records, for every pair, the
relation that ``dpkg --compare-versions`` gives; the pg part re-runs dpkg (so a
wrong fixture fails) and checks PostgreSQL's debversion agrees with every pair.
"""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg import sql

from .conftest import Conn, PgServer

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "debversion_pairs.tsv"
RELATIONS = ("lt", "eq", "gt")

Pair = tuple[str, str, str]


def load() -> list[Pair]:
    pairs = []
    for line in FIXTURE.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        a, b, rel = line.split("\t")
        pairs.append((a, b, rel))
    return pairs


def text_relation(a: str, b: str) -> str:
    return "lt" if a < b else "gt" if a > b else "eq"


# --- unit: the fixture (no Docker) ---------------------------------------------


def test_fixture_has_at_least_500_well_formed_pairs() -> None:
    pairs = load()
    assert len(pairs) >= 500
    assert all(rel in RELATIONS for _, _, rel in pairs)
    assert all(a and b and a != b for a, b, _ in pairs)
    assert len({(a, b) for a, b, _ in pairs}) == len(pairs)
    assert b"\r" not in FIXTURE.read_bytes()


def test_fixture_covers_every_required_category() -> None:
    pairs = load()
    versions = {v for a, b, _ in pairs for v in (a, b)}
    recorded = {(a, b): rel for a, b, rel in pairs}

    def rel(a: str, b: str) -> str:
        if (a, b) in recorded:
            return recorded[(a, b)]
        back = recorded[(b, a)]
        return {"lt": "gt", "gt": "lt", "eq": "eq"}[back]

    assert rel("0:1.0", "1.0") == "eq"
    assert rel("1.0~rc1", "1.0") == "lt"
    assert rel("1.0~~", "1.0~") == "lt"
    assert any(":" in v and not v.startswith("0:") for v in versions)  # epochs
    assert any("~" in v for v in versions)
    assert any("-" in v for v in versions) and any("-" not in v for v in versions)
    upstream = [v.split(":")[-1].rsplit("-", 1)[0] for v in versions]
    assert any("+" in u for u in upstream) and any("." in u for u in upstream)
    assert any(any(c.isalpha() for c in u) for u in upstream)  # letters vs digits
    assert any(".0" in u and u.split(".0", 1)[1][:1].isdigit() for u in upstream)
    runs = ["".join(c if c.isdigit() else " " for c in v).split() for v in versions]
    assert max(len(d) for r in runs for d in r) >= 10  # long digit runs


def test_at_least_20_pairs_order_differently_as_text() -> None:
    differing = [(a, b) for a, b, rel in load() if text_relation(a, b) != rel]
    assert len(differing) >= 20, differing


# --- PostgreSQL -----------------------------------------------------------------


@pytest.fixture
def owner(migrated_db: PgServer, owner_conn: Conn) -> Iterator[Conn]:
    """Until m0005 grants table privileges, comparisons run as bitscan_owner."""
    yield owner_conn


@pytest.mark.pg
def test_dpkg_agrees_with_every_recorded_relation() -> None:
    dpkg = shutil.which("dpkg")
    assert dpkg, "dpkg is required where the pg tests run (Debian/Ubuntu host)"
    wrong = []
    for a, b, rel in load():
        proc = subprocess.run(  # noqa: S603  # fixture values, no shell
            [dpkg, "--compare-versions", a, rel, b], capture_output=True, timeout=30
        )
        if proc.returncode != 0:
            wrong.append((a, rel, b))
    assert wrong == [], wrong[:10]


def compare_all(conn: Conn, pairs: list[Pair]) -> list[tuple[str, str, str, str]]:
    rows = conn.execute(
        "SELECT a, b, CASE WHEN a::debversion < b::debversion THEN 'lt'"
        " WHEN a::debversion = b::debversion THEN 'eq' ELSE 'gt' END"
        " FROM unnest(%s::text[], %s::text[]) AS t(a, b)",
        ([p[0] for p in pairs], [p[1] for p in pairs]),
    ).fetchall()
    expected = {(a, b): rel for a, b, rel in pairs}
    return [
        (a, b, expected[(a, b)], got) for a, b, got in rows if expected[(a, b)] != got
    ]


@pytest.mark.pg
def test_debversion_gives_the_recorded_relation_for_every_pair(owner: Conn) -> None:
    pairs = load()
    mismatches = compare_all(owner, pairs)
    assert mismatches == [], mismatches[:10]


@pytest.mark.pg
def test_name_and_debversion_query_uses_the_index(owner: Conn) -> None:
    with owner.transaction(force_rollback=True):
        owner.execute("SET LOCAL enable_seqscan = off")
        plan = "\n".join(
            r[0]
            for r in owner.execute(
                "EXPLAIN SELECT package_id FROM package"
                " WHERE name = %s AND version::debversion < %s::debversion",
                ("openssl", "3.0.13-0ubuntu3.1"),
            ).fetchall()
        )
    assert "ix_package_name_debver" in plan, plan


@pytest.mark.pg
def test_package_version_stays_text(owner: Conn) -> None:
    row = owner.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
        " WHERE attrelid = 'package'::regclass AND attname = 'version'"
    ).fetchone()
    assert row == ("character varying(255)",)


@pytest.mark.pg
def test_comparison_needs_no_table_privilege(app_conn: Conn) -> None:
    """The cast and operators are usable by bitscan_app even before m0005."""
    row = app_conn.execute(
        sql.SQL("SELECT {}::debversion > {}::debversion").format(
            sql.Literal("1:0.9"), sql.Literal("2.0")
        )
    ).fetchone()
    assert row == (True,)
