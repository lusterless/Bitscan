"""TP-M7-14 (TASK-154), G55 PostgreSQL half: 500 generated files through the
import pipeline leave the catalog complete or unchanged.

CHK-M7-197 (tests/m7/test-plan.md); REQ-176 (2) ("after each, the catalog is
either the complete import or unchanged"), TS §8.3 Property/fuzz ("no crash
and no partial import"), TS §4.1 L519-L520 and SR §3.6 (one transaction; any
error rolls back the whole file). Files are generated from a small pool of
names, plugin ids and target files (so updates, moves, BIT005, BIT007, BIT015,
BIT102 with `rm x`, renames and server-over-upload collide), half of them
byte-mutated. One in ten runs with a database fault injected late in the
store. "Complete" is checked against the file itself, read by the test with
defusedxml, never against the code's own view.
"""

from __future__ import annotations

import os
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from defusedxml import ElementTree
from psycopg import sql

from bitscan_manager.repositories import catalog_plugins
from bitscan_manager.services.importer.pipeline import (
    ImportOutcome,
    prepare,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer

from .bit_unit import SAMPLES, fixture
from .catalog_rows import owner
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, P, doc, make_env, sha

pytestmark = pytest.mark.pg

RUNS = 500
SEED = int(os.environ.get("BSTEST_FUZZ_SEED", "20261028"))
NAMES = [f"Fuzz policy {i}" for i in range(4)]
UUIDS = [f"00000000-0000-4000-8000-{i:012x}" for i in range(1, 11)]
FAMILIES = ["Fuzz family A", "Fuzz family B"]
FILES = ["f0.bit", "f1.bit", "f2.bit"]
EXECUTES = [
    "cat /etc/hostname",
    "dpkg-query -W -f='${Status}' apparmor 2>/dev/null",
    "grep -E '^\\s*PermitRootLogin' /etc/ssh/sshd_config",
    "rm x",  # BIT102 (stable under TASK-146 r2)
    "",  # BIT008
    "  stat -c %a /etc/x  ",
]
WS = " \t\r\n"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("fuzz")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    yield from make_env(server, tmp_path)


Snapshot = dict[str, dict[Any, tuple[Any, ...]]]
KEYS = {
    "family": ("family_id",),
    "policy": ("policy_id",),
    "plugin": ("plugin_uuid",),
    "policy_plugin": ("policy_id", "plugin_uuid"),
}


def snapshot(server: PgServer) -> Snapshot:
    out: Snapshot = {}
    with owner(server) as c:
        for table, key in KEYS.items():
            cur = c.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table)))
            cols = [d.name for d in cur.description or []]
            rows = {}
            for r in cur.fetchall():
                d = dict(zip(cols, r, strict=True))
                k = tuple(str(d[x]) for x in key)
                rows[k] = tuple((c2, d[c2]) for c2 in cols)
            out[table] = rows
    return out


def last_import(server: PgServer) -> int:
    with owner(server) as c:
        row = c.execute("SELECT coalesce(max(import_id), 0) FROM bit_import").fetchone()
    assert row is not None
    return int(row[0])


def new_rows(server: PgServer, after: int) -> list[dict[str, Any]]:
    with owner(server) as c:
        cur = c.execute(
            "SELECT import_id, outcome, policy_version FROM bit_import"
            " WHERE import_id > %s ORDER BY import_id",
            (after,),
        )
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def row(snap: Snapshot, table: str, *key: Any) -> dict[str, Any] | None:
    r = snap[table].get(tuple(str(k) for k in key))
    return None if r is None else dict(r)


# --- generation -------------------------------------------------------------


def generated(rnd: random.Random) -> bytes:
    roll = rnd.random()
    if roll < 0.1:
        return fixture("valid/sr-1.1-example.bit")
    if roll < 0.15:
        return rnd.choice(sorted(SAMPLES.glob("*.bit"))).read_bytes()
    n = rnd.randint(1, 4)
    ids = rnd.sample(UUIDS, n)
    if rnd.random() < 0.05 and n > 1:
        ids[-1] = ids[0]  # BIT005
    weights = [6, 3, 3, 1, 1, 1]
    plugins = [P(u, rnd.choices(EXECUTES, weights)[0]) for u in ids]
    status = rnd.choices(["enabled", "disabled", "Enabled", "on"], [6, 3, 1, 1])[0]
    return doc(
        rnd.choice(NAMES),
        plugins,
        status=status,
        family=rnd.choice(FAMILIES),
        desc=f"run {rnd.randint(0, 3)}",
    )


def mutate(rnd: random.Random, data: bytes) -> bytes:
    b = bytearray(data)
    for _ in range(rnd.randint(1, 3)):
        if not b:
            break
        i = rnd.randrange(len(b))
        j = min(len(b), i + rnd.randint(1, 40))
        op = rnd.randrange(6)
        if op == 0:
            b[i] = rnd.choice(b"abcXYZ019 <>/&;-\n\t\x00\xff")
        elif op == 1:
            del b[i:j]
        elif op == 2:
            b[i:i] = b[i:j]
        elif op == 3:
            b[i:i] = rnd.choice([b"<x/>", b"<!--c-->", b"&amp;", b"]]>", b"<Plugin>"])
        elif op == 4:
            del b[i:]
        else:
            b[i:j] = bytes(reversed(b[i:j]))
    return bytes(b)


# --- the file as the test reads it ---------------------------------------------


def text(el: Any, path: str) -> str:
    node = el.find(path)
    assert node is not None, path
    return str(node.text or "").strip(WS)


def read_file(data: bytes) -> tuple[str, str, list[tuple[str, str]]]:
    root = ElementTree.fromstring(data, forbid_dtd=True)
    plugins = [
        (text(p, "PluginId"), text(p, "Execute"))
        for p in root.findall("PluginsGroups/Plugin")
    ]
    return text(root, "PolicyName"), text(root, "Family/FamilyName"), plugins


def check_complete(
    pre: Snapshot,
    post: Snapshot,
    data: bytes,
    out: ImportOutcome,
    rel: str | None,
) -> None:
    name, family, plugins = read_file(data)
    pid = out.policy_id
    assert pid is not None
    pol = row(post, "policy", pid)
    assert pol is not None
    assert (pol["policy_name"], pol["deleted_at"]) == (name, None)
    assert pol["source_sha256"] == sha(data)
    assert pol["source_file"] == (rel or f"uploaded/policy-{pid}.bit")
    fam = row(post, "family", pol["family_id"])
    assert fam is not None and fam["family_name"] == family
    old = row(pre, "policy", pid)
    if old is None:
        assert pol["version"] == 1
    else:
        bump = old["source_sha256"] != sha(data) or old["deleted_at"] is not None
        assert pol["version"] == old["version"] + int(bump)
    assert out.policy_version == pol["version"]
    members = sorted(
        (dict(r)["sort_order"], k[1])
        for k, r in post["policy_plugin"].items()
        if k[0] == str(pid)
    )
    assert members == [(i, u) for i, (u, _) in enumerate(plugins, 1)]
    for u, execute in plugins:
        p = row(post, "plugin", u)
        assert p is not None
        assert (p["owner_policy_id"], p["state"]) == (pid, "active")
        assert (p["execute"], p["execute_sha256"]) == (execute, sha(execute.encode()))
        assert p["family_id"] == pol["family_id"]
    # Nothing else changed, except the policy this file displaced (#106), and
    # plugins retired because no live policy lists them any more.
    for k, before in pre["policy"].items():
        if k == (str(pid),):
            continue
        after = dict(post["policy"][k])
        b = dict(before)
        if after != b:
            assert b["source_file"] == rel and b["deleted_at"] is None, (b, after)
            assert after["deleted_at"] is not None
            assert after["source_file"] == f"deleted/{b['policy_id']}"
    others = {k: v for k, v in pre["policy_plugin"].items() if k[0] != str(pid)}
    assert {k: v for k, v in post["policy_plugin"].items() if k[0] != str(pid)} == (
        others
    )
    live = {
        k[1]
        for k in post["policy_plugin"]
        if dict(post["policy"][(k[0],)])["deleted_at"] is None
    }
    listed = {u for u, _ in plugins}
    for k, before in pre["plugin"].items():
        if k[0] in listed:
            continue
        after, b = dict(post["plugin"][k]), dict(before)
        if after != b:
            assert (b["state"], after["state"]) == ("active", "retired"), (b, after)
            assert k[0] not in live
            assert {
                c: v for c, v in after.items() if c not in ("state", "updated_at")
            } == {c: v for c, v in b.items() if c not in ("state", "updated_at")}
    for k, before in pre["family"].items():
        assert post["family"][k] == before
    assert set(post["family"]) - set(pre["family"]) <= {(str(pol["family_id"]),)}


def test_500_generated_files_leave_the_catalog_complete_or_unchanged(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    rnd = random.Random(SEED)  # noqa: S311 - reproducible test data
    seen: dict[str, int] = {}

    def fault(*a: Any, **k: Any) -> None:
        raise psycopg.errors.QueryCanceled("injected fault")

    real = catalog_plugins.replace_membership
    for n in range(RUNS):
        data = generated(rnd)
        if rnd.random() < 0.5:
            data = mutate(rnd, data)
        rel = rnd.choice(FILES) if rnd.random() < 0.75 else None
        if rnd.random() < 0.1:  # a server file removed by an administrator
            gone = env.bits / rnd.choice(FILES)
            gone.unlink(missing_ok=True)
        mode = rnd.choice(["auto", "manual"])
        injected = rnd.random() < 0.1
        pre, i0 = snapshot(env.server), last_import(env.server)
        monkeypatch.setattr(
            catalog_plugins, "replace_membership", fault if injected else real
        )
        ctx = f"run {n} seed {SEED} mode {mode} target {rel} injected {injected}"
        try:
            out = env.imp(data, rel, mode=mode, name="" if rel is None else None)
        except PolicyManagedOnServer:
            assert snapshot(env.server) == pre, ctx
            assert new_rows(env.server, i0) == [], ctx
            seen["refused"] = seen.get("refused", 0) + 1
            continue
        except Exception as exc:  # only an injected fault may end an import
            assert injected, f"{ctx}: {type(exc).__name__}"
            assert snapshot(env.server) == pre, ctx  # no partial import
            assert new_rows(env.server, i0) == [], ctx  # #98 (j)
            seen["fault"] = seen.get("fault", 0) + 1
            continue
        finally:
            monkeypatch.setattr(catalog_plugins, "replace_membership", real)
        post = snapshot(env.server)
        rows = new_rows(env.server, i0)
        assert [r["outcome"] for r in rows] == [out.outcome], ctx
        if out.outcome != "success":  # SR §3.5 (lead ruling 2026-10-28 (2))
            assert rows[0]["policy_version"] is None, ctx
        seen[out.outcome] = seen.get(out.outcome, 0) + 1
        if out.outcome == "success":
            assert not injected, ctx
            check_complete(pre, post, data, out, rel)
        else:
            assert post == pre, ctx
    # the generator reached every branch
    assert {"success", "rejected", "skipped", "fault"} <= set(seen), seen
    assert sum(seen.values()) == RUNS
    assert prepare(None).candidate is None
