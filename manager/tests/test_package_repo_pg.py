"""TASK-110: package search repository on PostgreSQL (TP-M5-03, REQ-114, REQ-115).

Checks CHK-M5-040 to CHK-M5-059 of tests/m5/test-plan.md, as bitscan_app on a
database of this module's own (``own_migrated_server``: the filters match
fleet-wide, so no other test's agents may be present). The fleet and every
expected answer come from ``package_fleet`` (independent oracles; see there).
Expected values: TS §7.1, §7.2, §5.2 L795-L815; #83 (a)-(f) as approved
2026-10-24; #87 (the probe found that debversion never raises, lead
2026-10-24: keep it as a regression test).
"""

import hashlib
import itertools
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from bitscan_manager.repositories.packages import (
    AnchorGone,
    PackageSearchRepo,
    SearchFilter,
    VersionOp,
)

from . import package_fleet as pf
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
REPO_PY = (
    Path(__file__).resolve().parents[1]
    / "bitscan_manager"
    / "repositories"
    / "packages.py"
)
BIG = 100_000


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("pkgrepo")) as s:
        yield s


@pytest.fixture(scope="module")
def fleet(server: PgServer) -> pf.Fleet:
    return pf.build(server)


@pytest.fixture
def conn(server: PgServer, fleet: pf.Fleet) -> Iterator[Conn]:
    with server.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


@pytest.fixture
def repo(conn: Conn) -> PackageSearchRepo:
    return PackageSearchRepo(conn)


def to_filter(w: pf.Want) -> SearchFilter:
    d = asdict(w)
    d["version_op"] = None if w.version_op is None else VersionOp(w.version_op)
    d["statuses"] = None if w.statuses is None else tuple(sorted(w.statuses))
    return SearchFilter(**d)


def got_rows(repo: PackageSearchRepo, w: pf.Want) -> list[tuple[Any, ...]]:
    return [
        (
            r.package_id,
            r.name,
            r.version,
            r.architecture,
            r.status,
            r.agent_id,
            r.hostname,
        )
        for r in repo.rows(to_filter(w), BIG, None)
    ]


def got_packages(repo: PackageSearchRepo, w: pf.Want) -> list[tuple[Any, ...]]:
    return [
        (g.package_id, g.name, g.version, g.architecture, g.host_count)
        for g in repo.package_groups(to_filter(w), BIG, None)
    ]


def got_hosts(repo: PackageSearchRepo, w: pf.Want) -> list[tuple[Any, ...]]:
    return [
        (g.agent_id, g.hostname, g.package_count)
        for g in repo.host_groups(to_filter(w), BIG, None)
    ]


def check_all_shapes(repo: PackageSearchRepo, fleet: pf.Fleet, w: pf.Want) -> None:
    assert got_rows(repo, w) == pf.want_rows(fleet, w), w
    assert got_packages(repo, w) == pf.want_packages(fleet, w), w
    assert got_hosts(repo, w) == pf.want_hosts(fleet, w), w


def walk(repo: PackageSearchRepo, f: SearchFilter, shape: str, n: int) -> list[Any]:
    """Page with limit n through repo, the way the route does (asks n + 1)."""
    out: list[Any] = []
    after: Any = None
    for _ in range(10_000):
        if shape == "rows":
            got: list[Any] = repo.rows(f, n + 1, after)
        elif shape == "package":
            got = repo.package_groups(f, n + 1, after)
        else:
            got = repo.host_groups(f, n + 1, after)
        assert len(got) <= n + 1
        page = got[:n]
        out.extend(page)
        if len(got) <= n:
            return out
        last = page[-1]
        if shape == "rows":
            after = (last.package_id, last.agent_id)
        elif shape == "package":
            after = last.package_id
        else:
            after = last.agent_id
    raise AssertionError("paging did not end")


# ------------------------------------------------------------ oracle self-checks


def test_debian_oracle_agrees_with_every_corpus_pair() -> None:
    pairs = pf.corpus_pairs()
    assert len(pairs) >= 500
    rel = {"lt": -1, "eq": 0, "gt": 1}
    wrong = [(a, b, r) for a, b, r in pairs if pf.sign(pf.deb_cmp(a, b)) != rel[r]]
    assert wrong == []


def test_trigram_oracle_agrees_with_pg_similarity(conn: Conn, fleet: pf.Fleet) -> None:
    names = sorted({r.name for r in fleet.rows if r.name != pf.CORPUS_PKG})
    queries = [*QS, "OPENSSL", "libssl", "pkg-tild"]
    for q in queries:
        db = conn.execute(
            "SELECT n, similarity(n, %s) FROM unnest(CAST(%s AS text[])) AS t(n)",
            (q, names),
        ).fetchall()
        for name, sim in db:
            py = pf.trgm_similarity(name, q)
            assert abs(py - float(sim)) < 1e-5, (name, q, py, sim)
            # No case sits on the threshold, so >= versus > cannot matter.
            assert abs(py - fleet.threshold) > 1e-4, (name, q, py)


# ------------------------------------------------------------ CHK-M5-040


def test_fleet_has_the_planned_variety(fleet: pf.Fleet) -> None:
    hosts = fleet.hosts.values()
    assert len(fleet.hosts) >= 20
    assert {h.os for h in hosts} >= {pf.U24, pf.U22, pf.D12}
    assert {t for h in hosts for t in h.tags} >= {"prod-web", "db", "mail"}
    assert any(not h.tags for h in hosts)
    archs = {r.architecture for r in fleet.rows}
    assert archs >= {"amd64", "i386", "arm64", "all"}
    versions = {r.version for r in fleet.rows}
    assert {"1:0.5", "1.0~rc1", "1.0", "1.0-0"} <= versions
    statuses = {r.status for r in fleet.rows}
    assert statuses >= {pf.INSTALLED, pf.HOLD, pf.DEINST, pf.CONFIG, pf.UNPACKED}
    assert {h.status for h in hosts} >= {
        "decommissioned",
        "awaiting_approval",
        "online",
    }
    assert len(pf.LONG_NAME) == 255 and len(pf.LONG_HOST) == 255
    assert any(r.name == pf.LONG_NAME for r in fleet.rows)


# ------------------------------------------------------------ CHK-M5-041


QS = ["ssl", "SSL", "opnssl", "b_u", "10%", "k\\s", "%_\\'\";--", "<script>",
      "üüü", "lib", "zzzqqq", "a' OR '1'='1", "x'--", "%%%", "___"]  # fmt: skip


def alone_cases(fleet: pf.Fleet) -> list[pf.Want]:
    any_ = None
    cases = [pf.Want(), pf.Want(statuses=any_)]
    cases += [pf.Want(q=q) for q in QS]
    names = ("openssl", "OpenSSL-Doc", "openssl-doc", "libssl3", pf.LONG_NAME,
             pf.FORMULA, "decom-only", "pending-only", "nope")  # fmt: skip
    cases += [pf.Want(name=n) for n in names]
    cases += [
        pf.Want(version=v) for v in ("1.0", "1.0-0", "3.0.13-0ubuntu3.5", "1:0.5", "9")
    ]
    cases += [
        pf.Want(version=v, version_op=op)
        for op in pf.OPS
        for v in ("1.0", "1.0-0", "3.0.3", "1:0", "2.0")
    ]
    cases += [pf.Want(arch=a) for a in ("amd64", "i386", "arm64", "all", "AMD64")]
    cases += [pf.Want(os_id=o) for o in ("ubuntu", "debian", "Ubuntu", "ubunt")]
    cases += [
        pf.Want(os_id=o, os_version_id=v)
        for o, v in (("ubuntu", "24.04"), ("ubuntu", "22.04"), ("debian", "12"),
                     ("ubuntu", "24.0"), ("ubuntu", "24.10"))
    ]  # fmt: skip
    cases += [pf.Want(tag=t) for t in ("prod-web", "db", "prod-web-old", "prod",
                                        "PROD-WEB", pf.SCRIPT)]  # fmt: skip
    cases += [pf.Want(host=h) for h in ("web-0", "WEB", "_", "%", "box", "dup",
                                         "ホホ", pf.SCRIPT, "nope")]  # fmt: skip
    ids = (fleet.agent_ids["web03"], fleet.agent_ids["decom"], uuid4())
    cases += [pf.Want(agent_id=a) for a in ids]
    return cases


def test_each_filter_alone_matches_the_oracle_in_all_shapes(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    for w in alone_cases(fleet):
        check_all_shapes(repo, fleet, w)
        check_all_shapes(repo, fleet, pf.Want(**{**asdict(w), "statuses": None}))


def test_oracle_sets_are_not_trivial(fleet: pf.Fleet) -> None:
    """Guard: the filter cases select real, distinct subsets."""
    sizes = {w: len(pf.want_rows(fleet, w)) for w in alone_cases(fleet)}
    assert sum(1 for s in sizes.values() if s > 0) >= 40
    assert len(set(sizes.values())) >= 15


# ------------------------------------------------------------ CHK-M5-042


def pair_kinds(fleet: pf.Fleet) -> dict[str, dict[str, Any]]:
    return {
        "q": {"q": "ssl"},
        "name": {"name": "openssl"},
        "version": {"version": "3.0.13-0ubuntu3.5"},
        "version_op": {"version": "3.0.3", "version_op": "ge"},
        "arch": {"arch": "amd64"},
        "status": {"statuses": None},
        "os": {"os_id": "ubuntu"},
        "os_version": {"os_id": "ubuntu", "os_version_id": "24.04"},
        "tag": {"tag": "prod-web"},
        "host": {"host": "web"},
        "agent_id": {"agent_id": fleet.agent_ids["web03"]},
    }


EXCLUSIVE = {frozenset({"q", "name"}), frozenset({"version", "version_op"}),
             frozenset({"os", "os_version"})}  # fmt: skip


def test_every_pair_of_filters_matches_the_oracle(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    kinds = pair_kinds(fleet)
    nonempty = 0
    for a, b in itertools.combinations(sorted(kinds), 2):
        if frozenset({a, b}) in EXCLUSIVE:
            continue
        w = pf.Want(**{**kinds[a], **kinds[b]})
        check_all_shapes(repo, fleet, w)
        nonempty += bool(pf.want_rows(fleet, w))
    assert nonempty >= 30


# ------------------------------------------------------------ CHK-M5-043


def test_five_filter_combination(repo: PackageSearchRepo, fleet: pf.Fleet) -> None:
    w = pf.Want(q="ssl", version="3.0", version_op="ge", arch="amd64",
                os_id="ubuntu", os_version_id="24.04", tag="prod-web")  # fmt: skip
    want = pf.want_rows(fleet, w)
    # pending-01 is awaiting approval: still searched (#83 (e)); decom-01 is not.
    assert {r[6] for r in want} == {"web-01", "web-02", "pending-01"}
    assert {r[1] for r in want} == {"openssl", "libssl3"}
    check_all_shapes(repo, fleet, w)


# ------------------------------------------------------------ CHK-M5-044 / -045


def corpus_filter(op: str | None, version: str) -> SearchFilter:
    return SearchFilter(
        name=pf.CORPUS_PKG,
        version=version,
        version_op=None if op is None else VersionOp(op),
    )


def test_version_op_agrees_with_dpkg_on_corpus_pairs(repo: PackageSearchRepo) -> None:
    pairs = pf.corpus_pairs()[:120]
    assert len(pairs) >= 50
    stored = set(pf.corpus_versions())
    checked = 0
    for b in sorted({b for _, b, _ in pairs}):
        for op, test in pf.OPS.items():
            got = {r.version for r in repo.rows(corpus_filter(op, b), BIG, None)}
            # The whole stored set against the oracle...
            assert got == {v for v in stored if test(pf.deb_cmp(v, b))}, (op, b)
            # ...and every recorded dpkg relation for this right-hand side.
            for a, b2, rel in pairs:
                if b2 == b:
                    c = {"lt": -1, "eq": 0, "gt": 1}[rel]
                    assert (a in got) == test(c), (a, op, b, rel)
                    checked += 1
    assert checked >= 250


@pytest.mark.parametrize(
    ("a", "op", "b", "expected"),
    [
        ("1:1.0", "gt", "2.0", True),
        ("1.0~rc1", "lt", "1.0", True),
        ("1.0", "eq", "1.0-0", True),
        ("1.0", "lt", "1.0+b1", True),
        ("10", "gt", "9", True),  # text order would say 10 < 9
        ("1.10", "gt", "1.9", True),
    ],
)
def test_named_debian_relations(
    conn: Conn, a: str, op: str, b: str, expected: bool
) -> None:
    assert pf.OPS[op](pf.deb_cmp(a, b)) is expected
    sym = {"lt": "<", "le": "<=", "eq": "=", "ge": ">=", "gt": ">"}[op]
    row = conn.execute(
        sql.SQL("SELECT CAST(%s AS debversion) {} CAST(%s AS debversion)").format(
            sql.SQL(sym)
        ),
        (a, b),
    ).fetchone()
    assert row == (expected,)


def test_version_op_is_debian_order_not_text(repo: PackageSearchRepo) -> None:
    """CHK-M5-320 target: pairs where text and Debian order disagree."""
    gt9 = {r.version for r in repo.rows(corpus_filter("gt", "9"), BIG, None)}
    lt_rc = {
        r.version
        for r in repo.rows(
            SearchFilter(name="pkg-tilde", version="1.0", version_op=VersionOp.LT),
            BIG,
            None,
        )
    }
    assert "1.0~rc1" in lt_rc  # text: "1.0~rc1" > "1.0"
    assert "1:0.5" not in lt_rc  # text: "1:0.5" < "1.0"? no; Debian: epoch 1 wins
    ge_e = {
        r.version
        for r in repo.rows(
            SearchFilter(name="pkg-tilde", version="2.0", version_op=VersionOp.GT),
            BIG,
            None,
        )
    }
    assert ge_e == {"1:0.5"}  # text: "1:0.5" < "2.0"
    assert all(pf.deb_cmp(v, "9") > 0 for v in gt9)


def test_version_alone_is_exact_text_and_eq_is_debian_equality(
    repo: PackageSearchRepo,
) -> None:
    exact = {
        r.version
        for r in repo.rows(SearchFilter(name="pkg-tilde", version="1.0"), BIG, None)
    }
    assert exact == {"1.0"}
    eq = {
        r.version
        for r in repo.rows(
            SearchFilter(name="pkg-tilde", version="1.0", version_op=VersionOp.EQ),
            BIG,
            None,
        )
    }
    assert eq == {"1.0", "1.0-0"}


# ------------------------------------------------------------ CHK-M5-046


def test_installed_statuses_and_any(repo: PackageSearchRepo, fleet: pf.Fleet) -> None:
    default = {r.status for r in repo.rows(SearchFilter(), BIG, None)}
    assert default == {pf.INSTALLED, pf.HOLD, pf.DEINST}
    every = {r.status for r in repo.rows(SearchFilter(statuses=None), BIG, None)}
    assert every == {pf.INSTALLED, pf.HOLD, pf.DEINST, pf.CONFIG, pf.UNPACKED}
    # cache-02 holds openssl as "deinstall ok installed" and bash unpacked.
    cache02 = fleet.agent_ids["cache02"]
    names = {r.name for r in repo.rows(SearchFilter(agent_id=cache02), BIG, None)}
    assert "openssl" in names
    assert "bash" not in names
    assert "pkg-tilde" not in names  # deinstall ok config-files


# ------------------------------------------------------------ CHK-M5-047


def test_decommissioned_hosts_are_never_searched(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    decom = fleet.agent_ids["decom"]
    assert repo.rows(SearchFilter(name="decom-only", statuses=None), BIG, None) == []
    assert repo.rows(SearchFilter(agent_id=decom, statuses=None), BIG, None) == []
    assert repo.package_groups(SearchFilter(agent_id=decom), BIG, None) == []
    hosts = {
        g.agent_id for g in repo.host_groups(SearchFilter(statuses=None), BIG, None)
    }
    assert decom not in hosts
    assert fleet.agent_ids["pending"] in hosts  # awaiting_approval is searched
    assert fleet.agent_ids["db02"] in hosts  # offline
    assert fleet.agent_ids["web03"] in hosts  # stale
    assert fleet.agent_ids["build_"] in hosts  # enrolled
    # host_count never counts the decommissioned holder of libssl3 i386.
    i386 = {
        (g.name, g.version): g.host_count
        for g in repo.package_groups(SearchFilter(arch="i386"), BIG, None)
    }
    assert i386[("libssl3", "3.0.13-0ubuntu3.5")] == 1  # web-01 (db-01 is config-files)


# ------------------------------------------------------------ CHK-M5-048 / -050 / -051


def test_q_is_case_insensitive_substring_or_trigram(repo: PackageSearchRepo) -> None:
    upper = {r.name for r in repo.rows(SearchFilter(q="SSL"), BIG, None)}
    assert {"openssl", "libssl3", "openssh-server", "OpenSSL-Doc"} - {
        "openssh-server"
    } <= upper
    fuzzy = {r.name for r in repo.rows(SearchFilter(q="opnssl"), BIG, None)}
    assert "openssl" in fuzzy  # trigram only: "opnssl" is no substring


def test_host_is_case_insensitive(repo: PackageSearchRepo) -> None:
    hosts = {
        g.hostname for g in repo.host_groups(SearchFilter(host="web-0"), BIG, None)
    }
    assert hosts == {"web-01", "web-02", "WEB-03"}


def test_name_tag_and_arch_are_exact(repo: PackageSearchRepo, fleet: pf.Fleet) -> None:
    assert repo.rows(SearchFilter(name="OPENSSL"), BIG, None) == []
    assert repo.rows(SearchFilter(name="openss"), BIG, None) == []
    assert repo.rows(SearchFilter(arch="amd6"), BIG, None) == []
    prod = {g.hostname for g in repo.host_groups(SearchFilter(tag="prod"), BIG, None)}
    assert prod == set()
    pw = {g.agent_id for g in repo.host_groups(SearchFilter(tag="prod-web"), BIG, None)}
    assert fleet.agent_ids["pct-"] not in pw  # tagged prod-web-old


# ------------------------------------------------------------ CHK-M5-049


def names_for(repo: PackageSearchRepo, q: str) -> set[str]:
    return {r.name for r in repo.rows(SearchFilter(q=q, statuses=None), BIG, None)}


def test_like_wildcards_in_q_match_literally(repo: PackageSearchRepo) -> None:
    pct = names_for(repo, "10%")
    assert "lib10%x" in pct
    assert "lib100x" not in pct
    und = names_for(repo, "b_u")
    assert "lib_under" in und
    assert "libXunder" not in und
    bsl = names_for(repo, "k\\s")
    assert "back\\slash" in bsl
    assert "backXslash" not in bsl
    inj = names_for(repo, "%_\\'\";--")
    assert pf.INJ[0] in inj
    assert len(inj) <= 2  # no catch-all
    every = names_for(repo, "%%%")
    assert every <= {pf.PCT[0], pf.INJ[0]}  # only names holding "%%%"? none
    assert names_for(repo, "___") == set()


def test_like_wildcards_in_host_match_literally(repo: PackageSearchRepo) -> None:
    under = {g.hostname for g in repo.host_groups(SearchFilter(host="_"), BIG, None)}
    assert under == {"build_box"}
    pct = {g.hostname for g in repo.host_groups(SearchFilter(host="%"), BIG, None)}
    assert pct == {"pct%host"}
    bs = repo.host_groups(SearchFilter(host="\\"), BIG, None)
    assert bs == []


@pytest.mark.parametrize(
    "value",
    ["a' OR '1'='1", "x'--", "'; DROP TABLE package; --", "%(q)s", "%s", "{}",
     "\\'", "$1", "') OR TRUE --"],
)  # fmt: skip
def test_injection_text_is_bound_not_executed(
    repo: PackageSearchRepo, conn: Conn, fleet: pf.Fleet, value: str
) -> None:
    for w in (pf.Want(q=value), pf.Want(host=value), pf.Want(name=value),
              pf.Want(tag=value), pf.Want(arch=value[:16])):  # fmt: skip
        if w.q is not None and len(w.q) < 3:
            continue
        check_all_shapes(repo, fleet, w)
    assert conn.execute("SELECT count(*) FROM package").fetchone() == (
        len(fleet.package_ids),
    )


# ------------------------------------------------------------ CHK-M5-052


def test_item_shapes_and_counts(repo: PackageSearchRepo, fleet: pf.Fleet) -> None:
    row = repo.rows(SearchFilter(name="openssl"), 1, None)[0]
    assert set(asdict(row)) == {"package_id", "name", "version", "architecture",
                                "status", "agent_id", "hostname"}  # fmt: skip
    assert isinstance(row.agent_id, UUID)
    g = repo.package_groups(SearchFilter(name="openssl"), BIG, None)
    assert set(asdict(g[0])) == {
        "package_id",
        "name",
        "version",
        "architecture",
        "host_count",
    }
    counts = {(x.version, x.architecture): x.host_count for x in g}
    want: dict[tuple[str, str], set[UUID]] = {}
    for r in fleet.rows:
        if (
            r.name == "openssl"
            and r.status in pf.INSTALLED_SET
            and r.host.status != "decommissioned"
        ):
            want.setdefault((r.version, r.architecture), set()).add(r.agent_id)
    assert counts == {k: len(v) for k, v in want.items()}
    h = repo.host_groups(SearchFilter(agent_id=fleet.agent_ids["mail01"]), BIG, None)
    assert [asdict(x) for x in h] == [
        {"agent_id": fleet.agent_ids["mail01"], "hostname": "mail-01",
         "package_count": len(fleet.hosts["mail01"].packages)}
    ]  # fmt: skip


# ------------------------------------------------------------ CHK-M5-053 / -054


PAGE_CASES = [
    pf.Want(),
    pf.Want(statuses=None),
    pf.Want(name="pkg-tilde", statuses=None),
    pf.Want(q="lib"),
    pf.Want(os_id="ubuntu", os_version_id="24.04"),
]


@pytest.mark.parametrize("n", [1, 2, 3, 7, 50])
@pytest.mark.parametrize("shape", ["rows", "package", "host"])
def test_paging_returns_each_item_once_in_order(
    repo: PackageSearchRepo, fleet: pf.Fleet, shape: str, n: int
) -> None:
    for w in PAGE_CASES:
        f = to_filter(w)
        got = walk(repo, f, shape, n)
        if shape == "rows":
            assert [(r.package_id, r.agent_id) for r in got] == [
                (x[0], x[5]) for x in pf.want_rows(fleet, w)
            ]
        elif shape == "package":
            assert [(g.package_id, g.host_count) for g in got] == [
                (x[0], x[4]) for x in pf.want_packages(fleet, w)
            ]
        else:
            assert [(g.agent_id, g.package_count) for g in got] == [
                (x[0], x[2]) for x in pf.want_hosts(fleet, w)
            ]


def test_equal_debian_versions_page_across_a_boundary(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    """1.0 and 1.0-0 are equal in Debian order (CHK-M5-327 target)."""
    f = SearchFilter(name="pkg-tilde", arch="amd64", statuses=None)
    groups = walk(repo, f, "package", 1)
    versions = [g.version for g in groups]
    assert versions == ["1.0~rc1", "1.0", "1.0-0", "1.0+b1", "2.0", "1:0.5"]
    for n in (1, 2, 3):
        rows = walk(repo, f, "rows", n)
        keys = [(r.package_id, r.agent_id) for r in rows]
        assert len(keys) == len(set(keys))
        assert keys == [(x[0], x[5]) for x in pf.want_rows(fleet, pf.Want(
            name="pkg-tilde", arch="amd64", statuses=None))]  # fmt: skip


def test_long_non_ascii_name_and_hostname_on_page_boundaries(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    for shape in ("rows", "package", "host"):
        full = walk(repo, SearchFilter(), shape, BIG)
        for n in range(1, len(full) + 1, max(1, len(full) // 40)):
            assert walk(repo, SearchFilter(), shape, n) == full
    rows = walk(repo, SearchFilter(name=pf.LONG_NAME), "rows", 1)
    assert {r.hostname for r in rows} == {"cache-01", pf.LONG_HOST}
    hosts = walk(repo, SearchFilter(host="ホ"), "host", 1)
    assert [h.hostname for h in hosts] == [pf.LONG_HOST]


def test_same_hostname_is_ordered_by_agent_id(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    got = walk(repo, SearchFilter(host="dup-name"), "host", 1)
    ids = sorted([fleet.agent_ids["dupA"], fleet.agent_ids["dupB"]])
    assert [g.agent_id for g in got] == ids


# ------------------------------------------------------------ CHK-M5-055


def test_anchor_that_never_existed_is_gone(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    missing_pkg = max(fleet.package_ids.values()) + 10_000
    some_agent = fleet.agent_ids["web01"]
    with pytest.raises(AnchorGone):
        repo.rows(SearchFilter(), 5, (missing_pkg, some_agent))
    with pytest.raises(AnchorGone):
        repo.rows(SearchFilter(), 5, (fleet.package_ids[pf.TZ], uuid4()))
    with pytest.raises(AnchorGone):
        repo.package_groups(SearchFilter(), 5, missing_pkg)
    with pytest.raises(AnchorGone):
        repo.host_groups(SearchFilter(), 5, uuid4())


def test_anchor_removed_since_the_page_is_gone(
    server: PgServer, fleet: pf.Fleet
) -> None:
    """A real removal: the package and agent rows a cursor points at are
    deleted (as owner: retention and agent deletion are not app operations),
    inside a transaction that is rolled back, so the fleet is unchanged."""
    with server.connect("bitscan_migrate") as owner:
        owner.execute("SET ROLE bitscan_owner")
        owner.autocommit = False
        try:
            r = PackageSearchRepo(owner)
            first = r.rows(SearchFilter(name="pkg-tilde"), 2, None)
            anchor = (first[0].package_id, first[0].agent_id)
            group = r.package_groups(SearchFilter(name="pkg-tilde"), 2, None)[0]
            host = r.host_groups(SearchFilter(), 2, None)[0]
            assert r.rows(SearchFilter(name="pkg-tilde"), 2, anchor)  # works before
            owner.execute(
                "DELETE FROM agent_package WHERE package_id = %s", (anchor[0],)
            )
            owner.execute("DELETE FROM package WHERE package_id = %s", (anchor[0],))
            with pytest.raises(AnchorGone):
                r.rows(SearchFilter(name="pkg-tilde"), 2, anchor)
            if group.package_id == anchor[0]:
                with pytest.raises(AnchorGone):
                    r.package_groups(
                        SearchFilter(name="pkg-tilde"), 2, group.package_id
                    )
            owner.execute("DELETE FROM agent WHERE agent_id = %s", (host.agent_id,))
            with pytest.raises(AnchorGone):
                r.host_groups(SearchFilter(), 2, host.agent_id)
        finally:
            owner.rollback()
    with server.connect("bitscan_app") as c:
        assert c.execute("SELECT count(*) FROM package").fetchone() == (
            len(fleet.package_ids),
        )


# ------------------------------------------------------------ CHK-M5-056


TABLES = ("package", "agent_package", "agent", "agent_tag", "os_info",
          "inventory_snapshot", "audit_log", "scan_job")  # fmt: skip


def table_digest(conn: Conn) -> dict[str, str]:
    out = {}
    for t in TABLES:
        rows = conn.execute(
            sql.SQL("SELECT to_jsonb(x)::text FROM {} x ORDER BY 1").format(
                sql.Identifier(t)
            )
        ).fetchall()
        out[t] = hashlib.sha256("\n".join(r[0] for r in rows).encode()).hexdigest()
    return out


def test_queries_write_nothing(
    repo: PackageSearchRepo, conn: Conn, fleet: pf.Fleet
) -> None:
    before = table_digest(conn)
    for w in alone_cases(fleet)[:40]:
        f = to_filter(w)
        for shape in ("rows", "package", "host"):
            walk(repo, f, shape, 3)
    assert table_digest(conn) == before


def test_repository_issues_select_statements_only() -> None:
    text = REPO_PY.read_text(encoding="utf-8").upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", "MERGE ", "COPY "):
        assert verb not in text, verb


# ------------------------------------------------------------ CHK-M5-058


def test_hostile_text_comes_back_byte_for_byte(
    repo: PackageSearchRepo, fleet: pf.Fleet
) -> None:
    for name in (pf.SCRIPT, pf.IMG, pf.FORMULA, pf.LONG_NAME, pf.INJ[0], pf.BSL[0]):
        rows = repo.rows(SearchFilter(name=name), BIG, None)
        assert rows and all(r.name == name for r in rows)
        assert all(r.name.encode() == name.encode() for r in rows)
    hosts = {g.hostname for g in repo.host_groups(SearchFilter(host="<"), BIG, None)}
    assert hosts == {pf.SCRIPT, pf.IMG}


# ------------------------------------------------------------ CHK-M5-059 (#87)


MALFORMED = ["1.0 beta", "a1", "1:", "1.0-", ":1", "1.0-ü", " 1.0", "x:1.0",
             "99999999999:1.0", "1.0\t", "ü1", "1.0-1:"]  # fmt: skip


def test_malformed_stored_versions_never_break_a_query(
    server: PgServer, fleet: pf.Fleet
) -> None:
    """#87: debversion accepts any text, so rows with versions dpkg would
    refuse never make a search raise. Inserted as bitscan_app in a
    transaction that is rolled back."""
    with server.connect("bitscan_app") as c:
        c.autocommit = False
        try:
            agent = fleet.agent_ids["web01"]
            for v in [*MALFORMED, "1.0"]:
                pid = c.execute(
                    "INSERT INTO package (name, version, architecture)"
                    " VALUES ('bad-ver', %s, 'amd64') RETURNING package_id",
                    (v,),
                ).fetchone()
                assert pid is not None
                c.execute(
                    "INSERT INTO agent_package (agent_id, package_id, status,"
                    " first_seen_at, last_seen_at) VALUES (%s, %s, %s, now(), now())",
                    (agent, pid[0], pf.INSTALLED),
                )
            r = PackageSearchRepo(c)
            rows = r.rows(SearchFilter(name="bad-ver"), BIG, None)
            assert sorted(x.version for x in rows) == sorted([*MALFORMED, "1.0"])
            for op in VersionOp:
                r.rows(
                    SearchFilter(name="bad-ver", version="1.0", version_op=op),
                    BIG,
                    None,
                )
                r.rows(SearchFilter(version="1.0", version_op=op), BIG, None)
            groups = walk(r, SearchFilter(name="bad-ver"), "package", 2)
            assert len(groups) == len(MALFORMED) + 1
            assert len({g.package_id for g in groups}) == len(groups)
            r.host_groups(SearchFilter(q="bad"), BIG, None)
        finally:
            c.rollback()


# ------------------------------------------------------------ CHK-M5-057


def test_fail_closed_on_combinations_parse_search_prevents(
    repo: PackageSearchRepo,
) -> None:
    """version_op without version and an os version without os_id are never
    built by parse_search; if they reach the repository they match nothing
    rather than dropping the filter."""
    assert repo.rows(SearchFilter(version_op=VersionOp.LT), BIG, None) == []
    assert repo.rows(SearchFilter(os_version_id="24.04"), BIG, None) == []
