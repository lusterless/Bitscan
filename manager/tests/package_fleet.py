"""Fixture fleet and independent oracles for the package search (TP-M5-03).

The fleet is built through the M3 inventory ingestion (the real decoder and
``ingest()`` with the real repositories, as bitscan_app); agent rows and tags
are inserted as bitscan_app, as the enrolment and tag routes would. Every
expected answer is computed here in Python from the fleet description:

- Debian order: ``deb_cmp`` is dpkg's ``verrevcmp`` written from dpkg's
  documented algorithm and checked against the whole M1 corpus
  (``fixtures/debversion_pairs.tsv``, recorded with dpkg 1.22.6);
- ``q`` similarity: ``trgm_similarity`` is pg_trgm's word-trigram rule
  (lower-cased alphanumeric words, two spaces before and one after each word),
  checked against the database's own ``similarity()`` on every fleet name;
- text order: the database collation rank of each string, read once with a
  plain ``ORDER BY`` over ``unnest`` of the fleet's strings (a neutral
  primitive, not the code under test).

Expected values: TS §7.1, §7.2, #83 (a)-(f) as approved 2026-10-24 (``hold ok
installed`` counts as installed; decommissioned hosts are never searched).
"""

import functools
import secrets
import string
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.inventory import InventoryRepo
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.inventory.ingest import NEW_PACKAGES_PER_DAY, ingest
from bitscan_manager.services.users.accounts import TxAudit

from .conftest import PgServer
from .test_inventory_ingest import DAY, T0, Clock, decoded, pkg

Conn = psycopg.Connection[Any]

CORPUS = Path(__file__).resolve().parent / "fixtures" / "debversion_pairs.tsv"

INSTALLED = "install ok installed"
HOLD = "hold ok installed"
DEINST = "deinstall ok installed"  # selected for removal, still installed
CONFIG = "deinstall ok config-files"
UNPACKED = "install ok unpacked"
# #83 (f), user 2026-10-24: held, and deinstall-selected but still installed.
INSTALLED_SET = frozenset({INSTALLED, HOLD, DEINST})

# ------------------------------------------------------------------ packages

Pkg3 = tuple[str, str, str]  # name, version, architecture

OPENSSL_NEW = ("openssl", "3.0.13-0ubuntu3.5", "amd64")
OPENSSL_OLD = ("openssl", "3.0.2-0ubuntu1.18", "amd64")
LIBSSL_A = ("libssl3", "3.0.13-0ubuntu3.5", "amd64")
LIBSSL_I = ("libssl3", "3.0.13-0ubuntu3.5", "i386")
LIBSSL_ARM = ("libssl3", "3.0.13-0ubuntu3.5", "arm64")
SSH_NEW = ("openssh-server", "1:9.6p1-3ubuntu13.5", "amd64")
SSH_OLD = ("openssh-server", "1:8.9p1-3ubuntu0.10", "amd64")
BASH_NEW = ("bash", "5.2.21-2ubuntu4", "amd64")
BASH_OLD = ("bash", "5.1-6ubuntu1.1", "amd64")
BASH_ARM = ("bash", "5.2.21-2ubuntu4", "arm64")
TZ = ("tzdata", "2024a-3ubuntu1.1", "all")
DOC = ("OpenSSL-Doc", "3.0.13-0ubuntu3.5", "all")
# Debian order: 1.0~rc1 < 1.0 = 1.0-0 < 1.0+b1 < 2.0 < 1:0.5
T_RC = ("pkg-tilde", "1.0~rc1", "amd64")
T_10 = ("pkg-tilde", "1.0", "amd64")
T_100 = ("pkg-tilde", "1.0-0", "amd64")
T_B1 = ("pkg-tilde", "1.0+b1", "amd64")
T_20 = ("pkg-tilde", "2.0", "amd64")
T_EPOCH = ("pkg-tilde", "1:0.5", "amd64")
T_10_I386 = ("pkg-tilde", "1.0", "i386")
# Literal wildcard and injection probes (REQ-115 (2)).
PCT = ("lib10%x", "1.0-1", "amd64")
PCT_DECOY = ("lib100x", "1.0-1", "amd64")
UND = ("lib_under", "1.0-1", "amd64")
UND_DECOY = ("libXunder", "1.0-1", "amd64")
BSL = ("back\\slash", "1.0-1", "amd64")
BSL_DECOY = ("backXslash", "1.0-1", "amd64")
INJ = ("x%_\\'\";--y", "1.0-1", "amd64")
# Hostile text (requirements M5 conventions).
SCRIPT = "<script>alert(1)</script>"
IMG = "<img src=x onerror=alert(1)>"
FORMULA = '=HYPERLINK("http://x")'
H_SCRIPT = (SCRIPT, "1.0", "amd64")
H_IMG = (IMG, "1.0", "amd64")
H_FORMULA = (FORMULA, "1.0", "amd64")
LONG_NAME = "ü" * 127 + "名" * 128  # 255 characters, 639 UTF-8 bytes
LONG = (LONG_NAME, "1.0", "amd64")
DECOM_ONLY = ("decom-only", "1.0", "amd64")
PENDING_ONLY = ("pending-only", "1.0", "amd64")
LONG_HOST = "ホ" * 100 + "é" * 155  # 255 characters
CORPUS_PKG = "corpus-pkg"


@dataclass(frozen=True)
class Host:
    key: str
    hostname: str
    status: str  # agent_status
    os: tuple[str, str]  # os_id, os_version_id
    tags: tuple[str, ...]
    packages: tuple[tuple[Pkg3, str], ...]  # (package, dpkg status)


def _base(os_version: str) -> list[tuple[Pkg3, str]]:
    new = os_version != "22.04"
    return [
        (TZ, INSTALLED),
        (BASH_NEW if new else BASH_OLD, INSTALLED),
        (OPENSSL_NEW if new else OPENSSL_OLD, INSTALLED),
        (LIBSSL_A, INSTALLED),
        (SSH_NEW if new else SSH_OLD, INSTALLED),
    ]


def _host(
    key: str,
    hostname: str,
    status: str,
    os: tuple[str, str],
    tags: Sequence[str] = (),
    extra: Sequence[tuple[Pkg3, str]] = (),
    override: dict[Pkg3, str] | None = None,
    base: bool = True,
) -> Host:
    items = (_base(os[1]) if base else []) + list(extra)
    if override:
        items = [(p, override.get(p, s)) for p, s in items]
    return Host(key, hostname, status, os, tuple(tags), tuple(items))


U24, U22, D12 = ("ubuntu", "24.04"), ("ubuntu", "22.04"), ("debian", "12")


def corpus_versions() -> list[str]:
    out: set[str] = set()
    for line in CORPUS.read_text(encoding="utf-8").split("\n"):
        if line and not line.startswith("#"):
            a, b, _ = line.split("\t")
            out.update((a, b))
    return sorted(out)


def corpus_pairs() -> list[tuple[str, str, str]]:
    pairs = []
    for line in CORPUS.read_text(encoding="utf-8").split("\n"):
        if line and not line.startswith("#"):
            a, b, rel = line.split("\t")
            pairs.append((a, b, rel))
    return pairs


def hosts() -> list[Host]:
    corpus = tuple(((CORPUS_PKG, v, "amd64"), INSTALLED) for v in corpus_versions())
    return [
        _host("web01", "web-01", "online", U24, ["prod-web"],
              [(T_RC, INSTALLED), (LIBSSL_I, INSTALLED)]),
        _host("web02", "web-02", "online", U24, ["prod-web"],
              [(T_10, INSTALLED), (DOC, INSTALLED)]),
        _host("web03", "WEB-03", "stale", U22, ["prod-web", "db"], [],
              {OPENSSL_OLD: HOLD}),
        _host("db01", "db-01", "online", U22, ["db"],
              [(T_100, INSTALLED), (LIBSSL_I, CONFIG)]),
        _host("db02", "db-02", "offline", U24, ["db"], [(T_10_I386, INSTALLED)],
              {BASH_NEW: CONFIG}),
        _host("build_", "build_box", "enrolled", U24, [], [(T_B1, INSTALLED)]),
        _host("build-", "build-box", "online", U22, [], [(T_20, HOLD)]),
        _host("pct%", "pct%host", "online", D12, [],
              [(PCT, INSTALLED), (PCT_DECOY, INSTALLED)]),
        _host("pct-", "pct-host", "online", D12, ["prod-web-old"],
              [(UND, INSTALLED), (UND_DECOY, INSTALLED)]),
        _host("mail01", "mail-01", "online", U24, ["mail"],
              [(T_EPOCH, INSTALLED), (BSL, INSTALLED), (BSL_DECOY, INSTALLED),
               (INJ, INSTALLED)]),
        _host("mail02", "mail-02", "online", U22, ["mail"], [], {LIBSSL_A: CONFIG}),
        _host("cache01", "cache-01", "online", U24, [],
              [(T_10, INSTALLED), (LONG, INSTALLED)], {SSH_NEW: HOLD}),
        _host("cache02", "cache-02", "online", U24, [], [(T_100, CONFIG)],
              {OPENSSL_NEW: DEINST, BASH_NEW: UNPACKED}),
        _host("script", SCRIPT, "online", U24, ["hostile", SCRIPT],
              [(H_SCRIPT, INSTALLED), (H_IMG, INSTALLED), (H_FORMULA, INSTALLED)]),
        _host("img", IMG, "online", U22, [], [(H_FORMULA, INSTALLED)]),
        _host("long", LONG_HOST, "online", U24, ["long"],
              [(LONG, INSTALLED), (T_10, INSTALLED)]),
        _host("decom", "decom-01", "decommissioned", U24, ["prod-web"],
              [(T_RC, INSTALLED), (DECOM_ONLY, INSTALLED), (LIBSSL_I, INSTALLED)]),
        _host("pending", "pending-01", "awaiting_approval", U24, ["prod-web"],
              [(PENDING_ONLY, INSTALLED)]),
        _host("Ucase", "edge-01", "online", ("Ubuntu", "24.04"), []),
        _host("u2410", "edge-02", "online", ("ubuntu", "24.10"), []),
        _host("arm", "arm-01", "online", U24, [],
              [(LIBSSL_ARM, INSTALLED), (BASH_ARM, INSTALLED)]),
        _host("dupA", "dup-name", "online", U24, ["dup"], [(T_10, INSTALLED)]),
        _host("dupB", "dup-name", "online", U24, ["dup"], [(T_10, INSTALLED)]),
        _host("corpus", "corpus-host", "online", U24, [], corpus, base=False),
    ]  # fmt: skip


# ------------------------------------------------------------------ build


@dataclass(frozen=True)
class Row:
    """One agent_package row as the search sees it."""

    package_id: int
    name: str
    version: str
    architecture: str
    status: str
    agent_id: UUID
    hostname: str
    host: Host


@dataclass
class Fleet:
    hosts: dict[str, Host]
    agent_ids: dict[str, UUID]
    package_ids: dict[Pkg3, int]
    rows: list[Row]
    rank: dict[str, int] = field(default_factory=dict)  # DB collation rank
    threshold: float = 0.3

    def host_of(self, agent_id: UUID) -> Host:
        for key, a in self.agent_ids.items():
            if a == agent_id:
                return self.hosts[key]
        raise KeyError(agent_id)


def _insert_agent(conn: Conn, h: Host) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status, enrolled_at)"
        " VALUES (%s, %s, '0.5.0', %s, %s, %s, %s, %s) RETURNING agent_id",
        (
            secrets.token_hex(16),
            h.hostname,
            secrets.token_hex(32),
            T0 - DAY,
            T0 + 300 * DAY,
            h.status,
            T0 - DAY,
        ),
    ).fetchone()
    assert row is not None
    agent_id = UUID(str(row[0]))
    for tag in h.tags:
        conn.execute(
            "INSERT INTO agent_tag (agent_id, tag) VALUES (%s, %s)", (agent_id, tag)
        )
    return agent_id


def build(server: PgServer) -> Fleet:
    db = AppDatabase(SecretStr(server.dsn("bitscan_app")), connect_timeout_s=10)
    db.open()
    clock = Clock()
    burst: SlidingCount[object] = SlidingCount(clock, DAY, DAY, NEW_PACKAGES_PER_DAY)
    spec = hosts()
    agent_ids: dict[str, UUID] = {}
    try:
        with server.connect("bitscan_app") as conn:
            for h in spec:
                agent_ids[h.key] = _insert_agent(conn, h)
        for h in spec:
            pkgs = [pkg(n, v, a, s) for (n, v, a), s in h.packages]
            dec = decoded(pkgs, os_id=h.os[0], os_version_id=h.os[1])
            clock.at += timedelta(seconds=1)
            with db.transaction() as tx:
                ingest(
                    InventoryRepo(tx.conn),
                    AgentRepo(tx.conn),
                    TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                    burst,
                    tx.on_commit,
                    agent_id=agent_ids[h.key],
                    decoded=dec,
                    now=clock.at,
                )
    finally:
        db.close()
    with server.connect("bitscan_app") as conn:
        ids = {
            (n, v, a): int(i)
            for i, n, v, a in conn.execute(
                "SELECT package_id, name, version, architecture FROM package"
            ).fetchall()
        }
        # The setting exists once pg_trgm is loaded in the session; show_limit()
        # loads it and returns pg_trgm.similarity_threshold.
        threshold_row = conn.execute("SELECT show_limit()").fetchone()
        assert threshold_row is not None
        by_key = {h.key: h for h in spec}
        rows = [
            Row(ids[p], *p, s, agent_ids[h.key], h.hostname, h)
            for h in spec
            for p, s in h.packages
        ]
        # The fleet in the database is exactly the description (ingestion
        # stored every row): the oracle starts from what is really there.
        stored = {
            (int(pid), UUID(str(aid)), st)
            for pid, aid, st in conn.execute(
                "SELECT package_id, agent_id, status FROM agent_package"
            ).fetchall()
        }
        assert stored == {(r.package_id, r.agent_id, r.status) for r in rows}
        fleet = Fleet(by_key, agent_ids, ids, rows, threshold=float(threshold_row[0]))
        fleet.rank = collation_rank(conn, all_strings(fleet))
    return fleet


def all_strings(fleet: Fleet) -> set[str]:
    out: set[str] = set()
    for r in fleet.rows:
        out.update((r.name, r.version, r.architecture, r.hostname))
    return out


def collation_rank(conn: Conn, values: Iterable[str]) -> dict[str, int]:
    ordered = conn.execute(
        "SELECT x FROM unnest(CAST(%s AS text[])) AS t(x) ORDER BY x", (list(values),)
    ).fetchall()
    return {str(x): i for i, (x,) in enumerate(ordered)}


# ------------------------------------------------------------------ Debian order

_DIGITS = frozenset(string.digits)
_LETTERS = frozenset(string.ascii_letters)


def _order(c: str) -> int:
    if c in _DIGITS:
        return 0
    if c in _LETTERS:
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def verrevcmp(a: str, b: str) -> int:
    """dpkg lib/dpkg/version.c verrevcmp()."""
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and a[i] not in _DIGITS) or (
            j < len(b) and b[j] not in _DIGITS
        ):
            ac = _order(a[i]) if i < len(a) else 0
            bc = _order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i] in _DIGITS and j < len(b) and b[j] in _DIGITS:
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i] in _DIGITS:
            return 1
        if j < len(b) and b[j] in _DIGITS:
            return -1
        if first_diff:
            return first_diff
    return 0


def _split(v: str) -> tuple[int, str, str]:
    epoch, colon, rest = v.partition(":")
    if not colon:
        epoch, rest = "0", v
    upstream, hyphen, revision = rest.rpartition("-")
    if not hyphen:
        upstream, revision = rest, ""
    return int(epoch), upstream, revision


def deb_cmp(a: str, b: str) -> int:
    """<0, 0, >0 as dpkg --compare-versions (well-formed versions only)."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    return verrevcmp(ua, ub) or verrevcmp(ra, rb)


def sign(n: int) -> int:
    return (n > 0) - (n < 0)


OPS: dict[str, Callable[[int], bool]] = {
    "lt": lambda c: c < 0,
    "le": lambda c: c <= 0,
    "eq": lambda c: c == 0,
    "ge": lambda c: c >= 0,
    "gt": lambda c: c > 0,
}


# ------------------------------------------------------------------ pg_trgm


def _words(s: str) -> list[str]:
    out, cur = [], []
    for c in s.lower():
        if c.isalnum():
            cur.append(c)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def trigrams(s: str) -> set[str]:
    out: set[str] = set()
    for w in _words(s):
        padded = "  " + w + " "
        out.update(padded[k : k + 3] for k in range(len(padded) - 2))
    return out


def trgm_similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


# ------------------------------------------------------------------ oracle


@dataclass(frozen=True)
class Want:
    """A filter, as plain values (mirrors SearchFilter field names)."""

    q: str | None = None
    name: str | None = None
    version: str | None = None
    version_op: str | None = None
    arch: str | None = None
    statuses: frozenset[str] | None = INSTALLED_SET
    os_id: str | None = None
    os_version_id: str | None = None
    tag: str | None = None
    host: str | None = None
    agent_id: UUID | None = None


def matches(fleet: Fleet, r: Row, w: Want) -> bool:
    h = r.host
    if h.status == "decommissioned":  # #83 (e)
        return False
    if w.q is not None and not (
        w.q.lower() in r.name.lower() or trgm_similarity(r.name, w.q) >= fleet.threshold
    ):
        return False
    if w.name is not None and r.name != w.name:
        return False
    if w.version is not None:
        if w.version_op is None:
            if r.version != w.version:
                return False
        elif not OPS[w.version_op](deb_cmp(r.version, w.version)):
            return False
    if w.arch is not None and r.architecture != w.arch:
        return False
    if w.statuses is not None and r.status not in w.statuses:
        return False
    if w.os_id is not None and h.os[0] != w.os_id:
        return False
    if w.os_version_id is not None and h.os[1] != w.os_version_id:
        return False
    if w.tag is not None and w.tag not in h.tags:
        return False
    if w.host is not None and w.host.lower() not in r.hostname.lower():
        return False
    return not (w.agent_id is not None and r.agent_id != w.agent_id)


def _tuple_cmp(a: Sequence[Any], b: Sequence[Any], kinds: str) -> int:
    for x, y, kind in zip(a, b, kinds, strict=True):
        if kind == "d":
            c = sign(deb_cmp(x, y))
        else:
            c = (x > y) - (x < y)
        if c:
            return c
    return 0


def _sorted(
    items: list[Any], key: Callable[[Any], Sequence[Any]], kinds: str
) -> list[Any]:
    return sorted(
        items, key=functools.cmp_to_key(lambda a, b: _tuple_cmp(key(a), key(b), kinds))
    )


def want_rows(fleet: Fleet, w: Want) -> list[tuple[Any, ...]]:
    """Expected rows, as (package_id, name, version, arch, status, agent_id,
    hostname), in the #83 (b) order: name, Debian version, version text,
    architecture, hostname, agent_id."""
    rk = fleet.rank
    found = [r for r in fleet.rows if matches(fleet, r, w)]
    ordered = _sorted(
        found,
        lambda r: (rk[r.name], r.version, rk[r.version], rk[r.architecture],
                   rk[r.hostname], r.agent_id),
        "tdtttt",
    )  # fmt: skip
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
        for r in ordered
    ]


def want_packages(fleet: Fleet, w: Want) -> list[tuple[Any, ...]]:
    """(package_id, name, version, arch, host_count), name, Debian version,
    version text, architecture."""
    rk = fleet.rank
    groups: dict[int, set[UUID]] = {}
    info: dict[int, Row] = {}
    for r in fleet.rows:
        if matches(fleet, r, w):
            groups.setdefault(r.package_id, set()).add(r.agent_id)
            info[r.package_id] = r
    ordered = _sorted(
        list(groups),
        lambda p: (rk[info[p].name], info[p].version, rk[info[p].version],
                   rk[info[p].architecture]),
        "tdtt",
    )  # fmt: skip
    return [
        (p, info[p].name, info[p].version, info[p].architecture, len(groups[p]))
        for p in ordered
    ]


def want_hosts(fleet: Fleet, w: Want) -> list[tuple[Any, ...]]:
    """(agent_id, hostname, package_count), hostname then agent_id."""
    rk = fleet.rank
    counts: dict[UUID, int] = {}
    names: dict[UUID, str] = {}
    for r in fleet.rows:
        if matches(fleet, r, w):
            counts[r.agent_id] = counts.get(r.agent_id, 0) + 1
            names[r.agent_id] = r.hostname
    ordered = sorted(counts, key=lambda a: (rk[names[a]], a))
    return [(a, names[a], counts[a]) for a in ordered]
