"""TP-M7-14 (TASK-154): the import pipeline `import_one` on PostgreSQL with a
temporary bits folder.

CHK-M7-190 to -196 (tests/m7/test-plan.md) and the plan's flows
(work/plans/TASK-154.md §10). Expected values come from the spec and the
approved answers, not from the code: TS §4.1 L516-L532 (read once; one store
transaction; the record in its own transaction after commit or rollback; the
lock until the rename; every import audit-logged and alerting; `auto` skips a
file whose hash equals the last success, `manual` and rebuild never skip; the
server folder wins over `uploaded/`), §4.2 (a rebuild's rejected file keeps
its rows, the rebuild commits as a whole), §4.3 (rename in place), §8.4
L1288-L1291 (policy imported carries every changed Execute; any rejected
import alerts; import failures metric); SR §3.5, §3.6, §4 (BIT001 and BIT002
stop the content rules; every other failing rule is reported); REQ-150 (4),
REQ-155, REQ-157 (3), REQ-160, REQ-162; #23 (a skip writes only its row), #98
(j) (an internal error writes no row), #99 (b), (e), #100 (a) as widened,
#101 (actions, kinds, actors, targets, the failure metric), #106, #110; the
BIT016 ruling (decisions 2026-10-27). BIT102 is checked only through cases
TASK-146 r2 does not change (`rm x` rejected; the sample Executes pass).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import catalog_plugins
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    import_one,
    prepare,
    record,
    store_in_savepoint,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer, Target

from .bit_unit import FIXTURES, SAMPLES, canonical, fixture, no_side_effects
from .catalog_rows import T1, T2, app, catalog_checksums, owner, tag
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

SYSTEM = Actor("system", None)
FIVE_MIB = 5 * 1024 * 1024
SR_UUID = "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"
SR_EXECUTE = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"
HEX = frozenset(b"0123456789abcdef")


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def alerts(kind: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind})
    return 0.0 if v is None else v


def failures(mode: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_import_failures_total", {"mode": mode})
    return 0.0 if v is None else v


KINDS = (
    "policy_imported",
    "policy_import_rejected",
    "policy_deleted",
    "policy_reenabled",
)


def counters() -> dict[str, float]:
    out = {k: alerts(k) for k in KINDS}
    out |= {f"fail:{m}": failures(m) for m in ("auto", "manual", "rebuild")}
    return out


def delta(before: dict[str, float]) -> dict[str, float]:
    return {k: v - before[k] for k, v in counters().items() if v != before[k]}


# --- documents ------------------------------------------------------------------


def is_uuid(v: bytes) -> bool:
    return (
        len(v) == 36
        and all(v[i] == ord("-") for i in (8, 13, 18, 23))
        and all(c in HEX for i, c in enumerate(v) if i not in (8, 13, 18, 23))
    )


def isolate(data: bytes, ids: dict[bytes, bytes] | None = None) -> bytes:
    """Every well-formed `<PluginId>` value replaced by a fresh UUID (the same
    one for the same value), so no other test's policy owns it (BIT015)."""
    ids = {} if ids is None else ids
    tag_open, tag_close = b"<PluginId>", b"</PluginId>"
    out = bytearray()
    i = 0
    while (j := data.find(tag_open, i)) >= 0:
        k = j + len(tag_open)
        out += data[i:k]
        value = data[k : k + 36]
        if is_uuid(value) and data[k + 36 : k + 36 + len(tag_close)] == tag_close:
            out += ids.setdefault(value, str(uuid4()).encode())
            i = k + 36
        else:
            i = k
    out += data[i:]
    return bytes(out)


@dataclass(frozen=True)
class P:
    uuid: str
    execute: str = "cat /etc/hostname"
    name: str = ""


def plug(execute: str = "cat /etc/hostname", name: str = "") -> P:
    return P(str(uuid4()), execute, name)


def doc(
    name: str,
    plugins: list[P],
    *,
    status: str = "enabled",
    family: str = "Pipeline Family",
    fv: str = 'formatVersion="1.0"',
    desc: str = "Generated by tester-m7.",
    extra_root: str = "",
) -> bytes:
    body = "".join(
        "    <Plugin>\n"
        f"      <PluginName>{p.name or f'{i}.1 - Check {i}'}</PluginName>\n"
        f"      <PluginDescription>Check {i}.</PluginDescription>\n"
        f"      <PluginId>{p.uuid}</PluginId>\n"
        f'      <Execute timeout="30"><![CDATA[{p.execute}]]></Execute>\n'
        "      <Operator>not_empty</Operator>\n"
        "      <ExpectedResult></ExpectedResult>\n"
        "    </Plugin>\n"
        for i, p in enumerate(plugins, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Policy {fv}>\n"
        f"  <PolicyName>{name}</PolicyName>\n"
        f"  <PolicyDescription>{desc}</PolicyDescription>\n"
        f"  <PolicyStatus>{status}</PolicyStatus>\n"
        f"{extra_root}"
        "  <Family>\n"
        f"    <FamilyName>{family}</FamilyName>\n"
        "  </Family>\n"
        "  <PluginsGroups>\n"
        f"{body}"
        "  </PluginsGroups>\n"
        "</Policy>\n"
    ).encode()


# --- environment ----------------------------------------------------------------


@dataclass
class Env:
    server: PgServer
    db: AppDatabase
    bits: Path
    clock: Clock

    def exists(self, rel: str) -> bool:
        return (self.bits / rel).is_file()

    def put(self, rel: str, data: bytes) -> str:
        (self.bits / rel).write_bytes(data)
        return rel

    def file(
        self, data: bytes | None, rel: str | None = None, *, name: str | None = None
    ) -> FileInput:
        digest = sha(data) if data is not None else "f" * 64
        target = (
            Target("server", rel, digest) if rel else Target("upload", None, digest)
        )
        return FileInput(
            data, digest, name if name is not None else (rel or ""), target
        )

    def imp(
        self,
        data: bytes | None,
        rel: str | None = None,
        *,
        mode: Any = "manual",
        actor: Actor = SYSTEM,
        name: str | None = None,
        write: bool = True,
        **kw: Any,
    ) -> ImportOutcome:
        if rel is not None and write and data is not None:
            self.put(rel, data)
        f = self.file(data, rel, name=name)
        prep = prepare(data)  # before the lock (plan §4)
        with self.db.session() as s, catalog_lock(s):
            return import_one(
                s,
                self.clock,
                self.bits,
                f,
                mode=mode,
                actor=actor,
                file_exists=self.exists,
                prepared=prep,
                **kw,
            )

    def mark(self) -> int:
        with app(self.server) as c:
            row = c.execute(
                "SELECT coalesce(max(audit_id), 0) FROM audit_log"
            ).fetchone()
        assert row is not None
        return int(row[0])

    def entries(self, after: int) -> list[dict[str, Any]]:
        with app(self.server) as c:
            rows = c.execute(
                "SELECT actor, action, target, detail::text FROM audit_log"
                " WHERE audit_id > %s ORDER BY audit_id",
                (after,),
            ).fetchall()
        return [
            {"actor": a, "action": b, "target": t, "detail": json.loads(d)}
            for a, b, t, d in rows
        ]

    def imports_after(self, after: int) -> list[dict[str, Any]]:
        with app(self.server) as c:
            cur = c.execute(
                "SELECT * FROM bit_import WHERE import_id > %s ORDER BY import_id",
                (after,),
            )
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def last_import(self) -> int:
        with app(self.server) as c:
            row = c.execute(
                "SELECT coalesce(max(import_id), 0) FROM bit_import"
            ).fetchone()
        assert row is not None
        return int(row[0])

    def catalog(self) -> dict[str, str]:
        with app(self.server) as c:
            return catalog_checksums(c)

    def policy(self, pid: int) -> dict[str, Any]:
        with app(self.server) as c:
            cur = c.execute("SELECT * FROM policy WHERE policy_id = %s", (pid,))
            cols = [d.name for d in cur.description or []]
            row = cur.fetchone()
        assert row is not None
        return dict(zip(cols, row, strict=True))

    def policy_by_name(self, name: str) -> dict[str, Any] | None:
        with app(self.server) as c:
            row = c.execute(
                "SELECT policy_id FROM policy WHERE policy_name = %s", (name,)
            ).fetchone()
        return None if row is None else self.policy(int(row[0]))

    def members(self, pid: int) -> list[tuple[str, int]]:
        with app(self.server) as c:
            rows = c.execute(
                "SELECT plugin_uuid::text, sort_order FROM policy_plugin"
                " WHERE policy_id = %s ORDER BY sort_order",
                (pid,),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def plugin(self, u: str) -> dict[str, Any]:
        with app(self.server) as c:
            cur = c.execute("SELECT * FROM plugin WHERE plugin_uuid = %s", (u,))
            cols = [d.name for d in cur.description or []]
            row = cur.fetchone()
        assert row is not None
        return dict(zip(cols, row, strict=True))


def make_env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    db.open()
    bits = tmp_path / "bits"
    (bits / "uploaded").mkdir(parents=True)
    try:
        yield Env(server, db, bits, Clock(T1))
    finally:
        db.close()


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("pipeline")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    yield from make_env(server, tmp_path)


@pytest.fixture
def fresh(tmp_path: Path) -> Iterator[Env]:
    """A database no other test has written to (exact first-import values)."""
    (tmp_path / "creds").mkdir()
    with own_migrated_server(tmp_path / "creds") as s:
        yield from make_env(s, tmp_path)


def codes(row: dict[str, Any]) -> list[str]:
    return [e["code"] for e in row["errors"]]


def only(entries: list[dict[str, Any]], action: str) -> dict[str, Any]:
    hits = [e for e in entries if e["action"] == action]
    assert len(hits) == 1, (action, entries)
    return hits[0]


# CHK-M7-190: the SR §1.1 example -------------------------------------------------


def test_sr_example_imports_with_one_success_row_and_one_alert(fresh: Env) -> None:
    data = fixture("valid/sr-1.1-example.bit")
    assert sha(data) == FIXTURES["valid/sr-1.1-example.bit"]["sha256"]
    m, i0, c0 = fresh.mark(), fresh.last_import(), counters()
    out = fresh.imp(data, "cis-ubuntu.bit", actor=Actor("user:7", 7))
    assert (out.outcome, out.policy_version) == ("success", 1)
    assert (out.plugins_added, out.plugins_updated, out.plugins_retired) == (1, 0, 0)
    (row,) = fresh.imports_after(i0)
    assert row["import_id"] == out.import_id
    assert {k: v for k, v in row.items() if k not in ("import_id", "imported_at")} == {
        "file_name": "cis-ubuntu.bit",
        "file_sha256": sha(data),
        "policy_version": 1,
        "mode": "manual",
        "outcome": "success",
        "plugins_added": 1,
        "plugins_updated": 0,
        "plugins_retired": 0,
        "errors": [],
        "imported_by": 7,
    }
    assert row["imported_at"] == T1
    (entry,) = fresh.entries(m)  # one entry: the import, which is the alert
    assert (entry["actor"], entry["action"]) == ("user:7", "policy.import")
    assert entry["target"] == f"policy:{out.policy_id}"
    d = entry["detail"]
    assert (d["alert"], d["alert_kind"]) == (True, "policy_imported")
    assert (d["version"], d["mode"], d["source_file"], d["file_sha256"]) == (
        1,
        "manual",
        "cis-ubuntu.bit",
        sha(data),
    )
    assert d["changed_executes"] == [
        {
            "plugin_uuid": SR_UUID,
            "plugin_name": "1.3.1.1 - Ensure AppArmor is installed",
            "execute": SR_EXECUTE,
            "execute_sha256": sha(SR_EXECUTE.encode()),
            "reason": "new",
            "flags": [],
        }
    ]
    assert delta(c0) == {"policy_imported": 1.0}
    p = fresh.policy(out.policy_id or 0)
    assert (p["version"], p["source_file"], p["source_sha256"]) == (
        1,
        "cis-ubuntu.bit",
        sha(data),
    )
    assert fresh.members(out.policy_id or 0) == [(SR_UUID, 1)]


def test_both_samples_import_with_no_reject_and_no_bit102(fresh: Env) -> None:
    for path in sorted(SAMPLES.glob("*.bit")):
        c0 = counters()
        out = fresh.imp(path.read_bytes(), path.name)
        assert out.outcome == "success", (path.name, out.findings)
        assert [f for f in out.findings if f.rejects] == []
        assert all(f.code.value != "BIT102" for f in out.findings)
        assert out.plugins_added >= 10
        assert delta(c0) == {"policy_imported": 1.0}


# CHK-M7-191: each rejecting fixture ---------------------------------------------

# Every rejecting fixture, the six BIT102 ones included (TASK-146 r2 deferred;
# the r1 rules apply, lead 2026-10-29).
REJECTING = sorted(
    f
    for f, m in FIXTURES.items()
    if m["outcome"] == "rejected" and not f.startswith("db/")
)
SUCCEEDING = sorted(
    f
    for f, m in FIXTURES.items()
    if m["outcome"] == "success" and not f.startswith("db/")
)


def assert_rejected(
    e: Env,
    out: ImportOutcome,
    *,
    expected: set[str],
    before: tuple[int, int, dict[str, str], dict[str, float]],
    mode: str,
    file_name: str,
) -> dict[str, Any]:
    m, i0, cat0, c0 = before
    assert out.outcome == "rejected" and isinstance(out.import_id, int)
    assert (out.policy_id, out.policy_version, out.store) == (None, None, None)
    (row,) = e.imports_after(i0)
    assert row["import_id"] == out.import_id
    assert (row["outcome"], row["mode"], row["policy_version"]) == (
        "rejected",
        mode,
        None,
    )
    assert (row["plugins_added"], row["plugins_updated"], row["plugins_retired"]) == (
        0,
        0,
        0,
    )
    assert row["file_name"] == file_name
    assert set(codes(row)) == expected, codes(row)
    assert all(set(f) == {"line", "element", "code", "message"} for f in row["errors"])
    lines = [f["line"] or 0 for f in row["errors"]]
    assert lines == sorted(lines)  # REQ-155 (5)
    (entry,) = e.entries(m)  # only the rejected alert
    assert entry["action"] == "policy.import_rejected"
    d = entry["detail"]
    assert (d["alert"], d["alert_kind"]) == (True, "policy_import_rejected")
    assert d["import_id"] == out.import_id and d["mode"] == mode
    assert d["codes"] == list(dict.fromkeys(codes(row)))
    assert d["finding_count"] == len(row["errors"])
    assert e.catalog() == cat0  # no catalog change
    assert delta(c0) == {"policy_import_rejected": 1.0, f"fail:{mode}": 1.0}
    return entry


def before(e: Env) -> tuple[int, int, dict[str, str], dict[str, float]]:
    return e.mark(), e.last_import(), e.catalog(), counters()


@pytest.mark.parametrize("name", REJECTING)
def test_each_rejecting_fixture_writes_its_rejected_row_and_alert(
    env: Env, name: str
) -> None:
    data = isolate(fixture(name))
    rel = f"rej-{tag()}.bit"
    b = before(env)
    out = env.imp(data, rel)
    assert_rejected(
        env,
        out,
        expected=set(FIXTURES[name]["codes"]),
        before=b,
        mode="manual",
        file_name=rel,
    )


def test_the_rejecting_set_covers_every_code() -> None:
    seen = {c for f in REJECTING for c in FIXTURES[f]["codes"]}
    rejects = {
        "BIT001", "BIT002", "BIT003", "BIT004", "BIT005", "BIT008", "BIT010",
        "BIT011", "BIT012", "BIT013", "BIT014", "BIT016", "BIT017", "BIT102",
    }  # fmt: skip
    assert rejects <= seen, rejects - seen
    assert len(REJECTING) > 100


@pytest.mark.parametrize("mode", ["auto", "manual", "rebuild"])
def test_a_rejection_counts_its_own_mode(env: Env, mode: str) -> None:
    data = isolate(fixture("content/bit003-on.bit"))
    rel = f"m-{tag()}.bit"
    b = before(env)
    out = env.imp(data, rel, mode=mode)
    assert_rejected(env, out, expected={"BIT003"}, before=b, mode=mode, file_name=rel)


def test_an_oversize_folder_file_is_a_rejected_bit001_import(env: Env) -> None:
    # #99 (b): a folder file over 5 MiB arrives as data None (streamed hash).
    b = before(env)
    rel = f"big-{tag()}.bit"
    f = FileInput(None, "a" * 64, rel, Target("server", rel, "a" * 64))
    with env.db.session() as s, catalog_lock(s):
        out = import_one(
            s, env.clock, env.bits, f, mode="auto", actor=SYSTEM,
            file_exists=env.exists,
        )  # fmt: skip
    row = env.imports_after(b[1])[0]
    assert row["file_sha256"] == "a" * 64
    assert_rejected(env, out, expected={"BIT001"}, before=b, mode="auto", file_name=rel)


def test_one_byte_over_5_mib_is_bit001_and_5_mib_exactly_imports(env: Env) -> None:
    exact = isolate(canonical(1, pad_to=FIVE_MIB))
    assert len(exact) == FIVE_MIB
    exact = exact.replace(b"Generated policy", f"Big {tag()}".encode()[:16].ljust(16))
    assert len(exact) == FIVE_MIB
    out = env.imp(exact, f"exact-{tag()}.bit")
    assert out.outcome == "success", out.findings
    over = isolate(canonical(1, pad_to=FIVE_MIB + 1))
    rel = f"over-{tag()}.bit"
    b = before(env)
    out = env.imp(over, rel)
    assert_rejected(
        env, out, expected={"BIT001"}, before=b, mode="manual", file_name=rel
    )


def test_rejected_target_is_the_matched_policy_or_the_file_name(env: Env) -> None:
    name = f"Target {tag()}"
    p = plug()
    good = env.imp(doc(name, [p]), "t.bit")
    assert good.outcome == "success"
    b = before(env)
    out = env.imp(doc(name, [p], status="on"), "t.bit")  # an update, BIT003
    entry = assert_rejected(
        env, out, expected={"BIT003"}, before=b, mode="manual", file_name="t.bit"
    )
    assert entry["target"] == f"policy:{good.policy_id}"
    assert entry["detail"]["policy_id"] == good.policy_id
    b = before(env)
    out = env.imp(doc(f"Unknown {tag()}", [plug()], status="on"), "u.bit")
    entry = assert_rejected(
        env, out, expected={"BIT003"}, before=b, mode="manual", file_name="u.bit"
    )
    assert entry["target"] == "u.bit" and entry["detail"]["policy_id"] is None


# CHK-M7-193: success fixtures, warnings stored (#110) ---------------------------


@pytest.mark.parametrize("name", SUCCEEDING)
def test_each_valid_fixture_imports_with_its_warnings(env: Env, name: str) -> None:
    data = isolate(fixture(name))
    m, i0, c0 = env.mark(), env.last_import(), counters()
    out = env.imp(data, f"ok-{tag()}.bit")
    assert out.outcome == "success", out.findings
    (row,) = env.imports_after(i0)
    assert row["outcome"] == "success" and row["policy_version"] == out.policy_version
    assert set(codes(row)) == set(FIXTURES[name]["codes"])  # warnings kept (#110)
    assert {f.code.value for f in out.findings} == set(FIXTURES[name]["codes"])
    imported = only(env.entries(m), "policy.import")
    assert imported["detail"]["alert_kind"] == "policy_imported"
    assert "policy.import_rejected" not in [e["action"] for e in env.entries(m)]
    assert delta(c0).get("policy_imported") == 1.0


# CHK-M7-192: auto skip; manual and rebuild never skip ---------------------------


def test_auto_unchanged_writes_only_a_skipped_row(env: Env) -> None:
    data = doc(f"Skip {tag()}", [plug(), plug()])
    first = env.imp(data, "s.bit")
    assert first.outcome == "success"
    m, i0, cat0, c0 = before(env)
    out = env.imp(data, "s.bit", mode="auto")
    assert (out.outcome, out.policy_id) == ("skipped", first.policy_id)
    (row,) = env.imports_after(i0)
    # SR §3.5: policy_version only "if it succeeded"; a skip is not a success
    # (lead ruling "TASK-154 test questions" (2), 2026-10-28; TASK-154 r1).
    assert (row["outcome"], row["mode"], row["policy_version"], row["errors"]) == (
        "skipped",
        "auto",
        None,
        [],
    )
    assert (row["plugins_added"], row["plugins_updated"], row["plugins_retired"]) == (
        0,
        0,
        0,
    )
    assert env.entries(m) == []  # no audit entry (#23)
    assert env.catalog() == cat0 and delta(c0) == {}


@pytest.mark.parametrize("mode", ["manual", "rebuild"])
def test_manual_and_rebuild_never_skip(env: Env, mode: str) -> None:
    data = doc(f"NoSkip {tag()}", [plug()])
    first = env.imp(data, "n.bit", mode="auto")
    assert first.outcome == "success"
    m, i0, _, c0 = before(env)
    out = env.imp(data, "n.bit", mode=mode)
    assert out.outcome == "success"
    assert out.policy_version == first.policy_version  # same hash: no +1
    assert (out.plugins_added, out.plugins_updated, out.plugins_retired) == (0, 0, 0)
    (row,) = env.imports_after(i0)
    assert (row["outcome"], row["mode"]) == ("success", mode)
    if mode == "manual":
        imported = only(env.entries(m), "policy.import")
        assert imported["detail"]["changed_executes"] == []  # every import alerts
        assert delta(c0) == {"policy_imported": 1.0}
    else:
        # TASK-154 r2 ("TASK-157 rulings" (2), #23, REQ-166 (6)): a rebuild
        # alerts only for a policy whose rows it changed; this one is unchanged.
        assert env.entries(m) == [] and delta(c0) == {}


# TASK-154 r2: rebuild alerts only for a policy whose rows changed ------------------


def rebuild_one(e: Env, rel: str, data: bytes) -> ImportOutcome:
    e.put(rel, data)
    f = e.file(data, rel)
    with e.db.session() as s, catalog_lock(s):
        with s.transaction() as tx:
            out = store_in_savepoint(
                s, tx, e.clock, f, prepare(data), actor=SYSTEM, file_exists=e.exists
            )
        with s.transaction() as tx2:
            record(tx2, f, "rebuild", SYSTEM, out, now=e.clock.now())
    return out


def test_a_rebuild_that_changes_nothing_alerts_for_nothing(env: Env) -> None:
    files = {f"u{i}.bit": doc(f"Unch {i} {tag()}", [plug(), plug()]) for i in range(3)}
    for rel, data in files.items():
        assert env.imp(data, rel).outcome == "success"
    m, i0, cat0, c0 = before(env)
    outs = [rebuild_one(env, rel, data) for rel, data in files.items()]
    assert [o.outcome for o in outs] == ["success"] * 3
    assert [r["outcome"] for r in env.imports_after(i0)] == ["success"] * 3
    assert env.entries(m) == [] and delta(c0) == {}
    assert env.catalog() == cat0


def corrupt(e: Env, kind: str, pid: int, uuids: list[str], other: int) -> None:
    sql = {
        "execute": "UPDATE plugin SET execute = 'cat /etc/x-corrupt'"
        " WHERE plugin_uuid = %(u)s",
        "membership": "DELETE FROM policy_plugin WHERE policy_id = %(p)s"
        " AND plugin_uuid = %(u)s",
        "retired": "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %(u)s",
        "status": "UPDATE policy SET policy_status = 'disabled'"
        " WHERE policy_id = %(p)s AND NOT status_overridden",
        "sha": "UPDATE policy SET source_sha256 = repeat('0', 64)"
        " WHERE policy_id = %(p)s",
        "owner": "UPDATE plugin SET owner_policy_id = %(o)s WHERE plugin_uuid = %(u)s",
    }[kind]
    with owner(e.server) as c:  # REQ-166 (1): a catalog corrupted by the owner
        cur = c.execute(sql, {"p": pid, "u": uuids[1], "o": other})
        assert cur.rowcount == 1, kind


@pytest.mark.parametrize(
    "kind", ["execute", "membership", "retired", "status", "sha", "owner"]
)
def test_each_corruption_gives_exactly_one_policy_imported(env: Env, kind: str) -> None:
    other = env.imp(doc(f"Other {tag()}", [plug()]), f"o-{tag()}.bit")
    p1, p2 = plug("cat /etc/one"), plug("cat /etc/two")
    data = doc(f"Corrupt {tag()}", [p1, p2])
    first = env.imp(data, "c.bit")
    pid = first.policy_id or 0
    good = (env.policy(pid)["policy_status"], env.members(pid), env.plugin(p2.uuid))
    corrupt(env, kind, pid, [p1.uuid, p2.uuid], other.policy_id or 0)
    m, c0 = env.mark(), counters()
    out = rebuild_one(env, "c.bit", data)
    assert out.outcome == "success"
    imported = [e for e in env.entries(m) if e["action"] == "policy.import"]
    assert [e["target"] for e in imported] == [f"policy:{pid}"]
    assert delta(c0).get("policy_imported") == 1.0
    # restored as a fresh import of the same file gives
    assert env.policy(pid)["policy_status"] == good[0]
    assert env.members(pid) == good[1]
    p = env.plugin(p2.uuid)
    assert (p["execute"], p["state"], p["owner_policy_id"]) == (
        good[2]["execute"],
        "active",
        pid,
    )
    assert env.policy(pid)["source_sha256"] == sha(data)


def test_auto_imports_a_changed_file_and_retries_a_rejected_one(env: Env) -> None:
    name, p = f"Auto {tag()}", plug()
    v1 = env.imp(doc(name, [p]), "a.bit", mode="auto")
    v2 = env.imp(doc(name, [p], desc="changed"), "a.bit", mode="auto")
    assert (v1.outcome, v2.outcome) == ("success", "success")
    assert v2.policy_version == (v1.policy_version or 0) + 1
    bad = doc(name, [p], status="on")
    assert env.imp(bad, "a.bit", mode="auto").outcome == "rejected"
    assert env.imp(bad, "a.bit", mode="auto").outcome == "rejected"  # tried again
    # back to the last successful bytes: skipped (hash equals the last success)
    assert env.imp(doc(name, [p], desc="changed"), "a.bit", mode="auto").outcome == (
        "skipped"
    )


def test_auto_does_not_skip_a_deleted_policy(env: Env) -> None:
    data = doc(f"Revive {tag()}", [plug()])
    first = env.imp(data, "r.bit")
    with app(env.server) as c, c.transaction():
        assert adm.soft_delete_effects(c, first.policy_id or 0, T2) is not None
    out = env.imp(data, "r.bit", mode="auto")
    assert out.outcome == "success" and out.policy_id == first.policy_id
    assert out.store is not None and out.store.revived
    assert out.policy_version == (first.policy_version or 0) + 1  # #14


# Database rules with file-local rules (plan §10 row 4, BIT016 ruling) ------------


def test_bit016_and_bit003_are_reported_together(env: Env) -> None:
    for fv in ('formatVersion="2.0"', 'formatVersion="1.1"'):
        b = before(env)
        rel = f"fv-{tag()}.bit"
        out = env.imp(doc(f"FV {tag()}", [plug()], status="on", fv=fv), rel)
        assert_rejected(
            env, out, expected={"BIT016", "BIT003"}, before=b, mode="manual",
            file_name=rel,
        )  # fmt: skip


def test_bit002_stops_the_content_rules(env: Env) -> None:
    b = before(env)
    rel = f"b2-{tag()}.bit"
    data = doc(f"B2 {tag()}", [plug()], status="on", extra_root="  <Extra/>\n")
    out = env.imp(data, rel)
    assert_rejected(
        env, out, expected={"BIT002"}, before=b, mode="manual", file_name=rel
    )


def test_bit007_bit015_and_bit003_in_one_rejected_row(env: Env) -> None:
    shared = plug()
    owner_name = f"Owner {tag()}"
    assert env.imp(doc(owner_name, [shared]), "owner.bit").outcome == "success"
    other = f"Other {tag()}"
    assert env.imp(doc(other, [plug()]), "other.bit").outcome == "success"
    b = before(env)
    # a third file: the other file's name (still on disk), the owner's plugin id,
    # and a bad status
    out = env.imp(doc(other, [plug(), shared], status="on"), "third.bit")
    assert_rejected(
        env, out, expected={"BIT003", "BIT007", "BIT015"}, before=b, mode="manual",
        file_name="third.bit",
    )  # fmt: skip


def test_bit007_fixture_pair_then_the_move_when_the_file_is_gone(env: Env) -> None:
    ids: dict[bytes, bytes] = {}
    name = f"Pair {tag()}".encode()
    a = isolate(fixture("db/bit007-a.bit"), ids).replace(
        b"Fixture BIT007 shared name", name
    )
    bb = isolate(fixture("db/bit007-b.bit"), ids).replace(
        b"Fixture BIT007 shared name", name
    )
    first = env.imp(a, "a.bit")
    assert first.outcome == "success"
    b = before(env)
    out = env.imp(bb, "b.bit")
    assert_rejected(
        env, out, expected={"BIT007"}, before=b, mode="manual", file_name="b.bit"
    )
    row = env.imports_after(b[1])[0]
    assert row["errors"][0]["element"] == "Policy/PolicyName"
    (env.bits / "a.bit").unlink()
    m = env.mark()
    moved = env.imp(bb, "b.bit")
    assert moved.outcome == "success" and moved.policy_id == first.policy_id
    assert env.policy(first.policy_id or 0)["source_file"] == "b.bit"
    move = only(env.entries(m), "policy.move")
    assert move["detail"] == {"from": "a.bit", "to": "b.bit"}
    assert "alert" not in move["detail"]


def test_bit015_fixtures_reject_then_claim_after_the_owner_drops_it(env: Env) -> None:
    ids: dict[bytes, bytes] = {}
    sfx = tag().encode()

    def load(n: str) -> bytes:
        data = isolate(fixture(n), ids)
        return data.replace(b"Fixture db/bit015-", b"Fixture db/bit015-" + sfx + b"-")

    owner_ = env.imp(load("db/bit015-owner.bit"), "owner.bit")
    assert owner_.outcome == "success"
    b = before(env)
    out = env.imp(load("db/bit015-claimer.bit"), "claimer.bit")
    assert_rejected(
        env, out, expected={"BIT015"}, before=b, mode="manual", file_name="claimer.bit"
    )
    row = env.imports_after(b[1])[0]
    assert row["errors"][0]["element"] == "Policy/PluginsGroups/Plugin[2]/PluginId"
    assert env.imp(load("db/bit015-owner-dropped.bit"), "owner.bit").outcome == (
        "success"
    )
    claimed = env.imp(load("db/bit015-claimer.bit"), "claimer.bit")
    assert claimed.outcome == "success"
    shared = ids[b"a41ae0c5-4173-55e2-90bb-f9eaeac0fe00"].decode()
    assert env.plugin(shared)["owner_policy_id"] == claimed.policy_id


# BIT102 on every entry point (REQ-157 (3), CHK-M7-333) ---------------------------


@pytest.mark.parametrize("mode", ["auto", "manual", "rebuild"])
@pytest.mark.parametrize("where", ["server", "upload"])
def test_rm_is_rejected_on_every_entry_point(env: Env, mode: str, where: str) -> None:
    name, good = f"BIT102 {tag()}", plug()
    rel = "p.bit" if where == "server" else None
    first = env.imp(doc(name, [good]), rel, mode=mode)
    assert first.outcome == "success"
    b = before(env)
    out = env.imp(
        doc(name, [good, plug("rm x")]),
        rel,
        mode=mode,
        name="" if rel is None else None,
    )
    assert_rejected(
        env, out, expected={"BIT102"}, before=b, mode=mode,
        file_name=rel or "",
    )  # fmt: skip
    row = env.imports_after(b[1])[0]
    assert row["errors"][0]["element"] == "Policy/PluginsGroups/Plugin[2]/Execute"


def test_a_sample_execute_passes_inside_a_generated_file(env: Env) -> None:
    out = env.imp(doc(f"Sample cmd {tag()}", [plug(SR_EXECUTE)]), f"x-{tag()}.bit")
    assert out.outcome == "success" and out.findings == ()


# Rebuild: one file rejected (plan §10 row 7) -------------------------------------


def test_rebuild_with_one_file_rejected_keeps_its_rows(env: Env) -> None:
    t = tag()
    pa, pb, pc = plug(), plug(), plug()
    files = {
        "ra.bit": doc(f"RA {t}", [pa]),
        "rb.bit": doc(f"RB {t}", [pb]),
        "rc.bit": doc(f"RC {t}", [pc]),
    }
    for rel, data in files.items():
        assert env.imp(data, rel).outcome == "success"
    b_policy = env.policy_by_name(f"RB {t}")
    assert b_policy is not None
    b_rows = (b_policy, env.members(b_policy["policy_id"]), env.plugin(pb.uuid))
    files["ra.bit"] = doc(f"RA {t}", [pa], desc="rebuilt")
    files["rb.bit"] = doc(f"RB {t}", [pb, plug("rm x")])  # BIT102
    files["rc.bit"] = doc(f"RC {t}", [pc], desc="rebuilt")
    m, i0, c0 = env.mark(), env.last_import(), counters()
    pending: list[tuple[FileInput, ImportOutcome]] = []
    with env.db.session() as s, catalog_lock(s):
        with s.transaction() as tx:
            for rel, data in files.items():
                env.put(rel, data)
                f = env.file(data, rel)
                pending.append(
                    (
                        f,
                        store_in_savepoint(
                            s,
                            tx,
                            env.clock,
                            f,
                            prepare(data),
                            actor=SYSTEM,
                            file_exists=env.exists,
                        ),  # fmt: skip
                    )
                )
        assert [p.outcome for _, p in pending] == ["success", "rejected", "success"]
        assert all(p.import_id is None for _, p in pending)
        with s.transaction() as tx2:
            ids = [
                record(tx2, f, "rebuild", SYSTEM, p, now=env.clock.now())
                for f, p in pending
            ]
    rows = env.imports_after(i0)
    assert [r["import_id"] for r in rows] == ids
    assert [(r["outcome"], r["mode"]) for r in rows] == [
        ("success", "rebuild"),
        ("rejected", "rebuild"),
        ("success", "rebuild"),
    ]
    assert codes(rows[1]) == ["BIT102"]
    after_b = env.policy(b_policy["policy_id"])
    assert (after_b, env.members(b_policy["policy_id"]), env.plugin(pb.uuid)) == b_rows
    for n in ("RA", "RC"):
        p = env.policy_by_name(f"{n} {t}")
        assert p is not None and p["policy_description"] == "rebuilt"
    entries = env.entries(m)
    imported = [e for e in entries if e["action"] == "policy.import"]
    assert sorted(e["detail"]["policy_name"] for e in imported) == [
        f"RA {t}",
        f"RC {t}",
    ]
    assert [e["detail"]["mode"] for e in imported] == ["rebuild", "rebuild"]
    rejected = only(entries, "policy.import_rejected")
    assert rejected["target"] == f"policy:{b_policy['policy_id']}"
    assert [e["action"] for e in entries if e["target"] == rejected["target"]] == [
        "policy.import_rejected"
    ]  # the rejected file's savepoint entries are gone
    assert delta(c0) == {
        "policy_imported": 2.0,
        "policy_import_rejected": 1.0,
        "fail:rebuild": 1.0,
    }


# Moves, displaced policies, rename, re-enable (plan §10 row 8) -------------------


def test_server_file_wins_over_an_upload(env: Env) -> None:
    name, p = f"Wins {tag()}", plug()
    up = env.imp(doc(name, [p]), None, name="client.bit")
    assert up.outcome == "success" and up.policy_id is not None
    copy = f"uploaded/policy-{up.policy_id}.bit"
    assert env.policy(up.policy_id)["source_file"] == copy
    env.put(copy, doc(name, [p]))
    m, c0 = env.mark(), counters()
    out = env.imp(doc(name, [p], desc="server"), "srv.bit")
    assert out.outcome == "success" and out.policy_id == up.policy_id
    assert env.policy(up.policy_id)["source_file"] == "srv.bit"
    assert not (env.bits / copy).exists()  # the uploaded copy is deleted
    entries = env.entries(m)
    assert [e["action"] for e in entries] == ["policy.import", "policy.move"]
    assert entries[1]["detail"] == {"from": copy, "to": "srv.bit"}
    assert entries[1]["target"] == f"policy:{up.policy_id}"
    assert delta(c0) == {"policy_imported": 1.0}


def test_a_file_taking_an_uploaded_name_displaces_its_old_policy(env: Env) -> None:
    t = tag()
    x = env.imp(doc(f"X {t}", [plug()]), "a.bit")
    py = plug()
    y = env.imp(doc(f"Y {t}", [py]), None, name="y.bit")
    assert x.outcome == y.outcome == "success"
    copy = f"uploaded/policy-{y.policy_id}.bit"
    env.put(copy, b"y")
    m, c0 = env.mark(), counters()
    out = env.imp(doc(f"Y {t}", [py]), "a.bit")  # a.bit now holds Y (#106)
    assert out.outcome == "success" and out.policy_id == y.policy_id
    assert out.store is not None and out.store.deleted_policy_ids == (x.policy_id,)
    gone = env.policy(x.policy_id or 0)
    assert gone["deleted_at"] is not None
    assert gone["source_file"] == f"deleted/{x.policy_id}"
    assert env.policy(y.policy_id or 0)["source_file"] == "a.bit"
    assert not (env.bits / copy).exists()
    entries = env.entries(m)
    assert sorted(e["action"] for e in entries) == [
        "policy.delete",
        "policy.import",
        "policy.move",
    ]
    dele = only(entries, "policy.delete")
    assert dele["target"] == f"policy:{x.policy_id}"
    assert dele["detail"]["alert_kind"] == "policy_deleted"
    assert dele["detail"]["reason"] == "file now holds another policy"
    assert delta(c0) == {"policy_imported": 1.0, "policy_deleted": 1.0}


def test_rename_in_place_keeps_the_id(env: Env) -> None:
    t, p = tag(), plug()
    first = env.imp(doc(f"Old {t}", [p]), "ren.bit")
    m = env.mark()
    out = env.imp(doc(f"New {t}", [p]), "ren.bit")
    assert out.policy_id == first.policy_id and out.policy_name == f"New {t}"
    imported = only(env.entries(m), "policy.import")
    assert imported["detail"]["renamed_from"] == f"Old {t}"


def test_a_file_reenabling_a_policy_alerts_unless_overridden(env: Env) -> None:
    t, p = tag(), plug()
    first = env.imp(doc(f"RE {t}", [p], status="disabled"), "re.bit")
    m, c0 = env.mark(), counters()
    env.imp(doc(f"RE {t}", [p], status="enabled"), "re.bit")
    change = only(env.entries(m), "policy.status_change")
    assert change["detail"]["alert_kind"] == "policy_reenabled"
    assert (change["detail"]["by"], change["detail"]["to"]) == ("file", "enabled")
    assert delta(c0) == {"policy_imported": 1.0, "policy_reenabled": 1.0}
    with app(env.server) as c, c.transaction():
        assert adm.set_status(c, first.policy_id or 0, "disabled", T2)  # override
    env.imp(doc(f"RE {t}", [p], status="disabled"), "re.bit")
    m, c0 = env.mark(), counters()
    env.imp(doc(f"RE {t}", [p], status="enabled"), "re.bit")
    assert [e["action"] for e in env.entries(m)] == ["policy.import"]
    assert env.policy(first.policy_id or 0)["policy_status"] == "disabled"
    assert delta(c0) == {"policy_imported": 1.0}


def test_changed_executes_new_changed_and_reactivated(env: Env) -> None:
    t = tag()
    a, b = plug("cat /etc/x"), plug("cat /etc/shadow")
    m = env.mark()
    env.imp(doc(f"CE {t}", [a, b]), "ce.bit")
    d = only(env.entries(m), "policy.import")["detail"]
    assert [
        (c["plugin_uuid"], c["reason"], c["flags"]) for c in d["changed_executes"]
    ] == [
        (a.uuid, "new", []),
        (b.uuid, "new", ["shadow"]),
    ]
    m = env.mark()
    env.imp(doc(f"CE {t}", [a, P(b.uuid, "cat /etc/y")]), "ce.bit")  # one changed
    d = only(env.entries(m), "policy.import")["detail"]
    assert [(c["plugin_uuid"], c["reason"]) for c in d["changed_executes"]] == [
        (b.uuid, "changed")
    ]
    env.imp(doc(f"CE {t}", [a]), "ce.bit")  # b retired
    assert env.plugin(b.uuid)["state"] == "retired"
    m = env.mark()
    env.imp(doc(f"CE {t}", [a, P(b.uuid, "cat /etc/y")]), "ce.bit")
    d = only(env.entries(m), "policy.import")["detail"]
    assert [(c["plugin_uuid"], c["reason"]) for c in d["changed_executes"]] == [
        (b.uuid, "reactivated")
    ]


# Refusal (#99 (e), plan §10 row 5) ------------------------------------------------


def test_upload_of_a_server_folder_policy_is_refused_without_a_row(env: Env) -> None:
    name, p = f"Managed {tag()}", plug()
    srv = env.imp(doc(name, [p]), "managed.bit")
    m, i0, cat0, c0 = before(env)
    data = doc(name, [p], desc="from an upload")
    with pytest.raises(PolicyManagedOnServer) as err:
        env.imp(data, None, name="evil.bit", actor=Actor("user:3", 3))
    assert err.value.policy_id == srv.policy_id
    assert env.imports_after(i0) == []  # no bit_import row
    (entry,) = env.entries(m)
    assert entry == {
        "actor": "user:3",
        "action": "policy.import_refused",
        "target": f"policy:{srv.policy_id}",
        "detail": {
            "policy_id": srv.policy_id,
            "mode": "manual",
            "file_sha256": sha(data),
        },
    }
    assert env.catalog() == cat0 and delta(c0) == {}


# Transactions and faults (CHK-M7-194, -196; plan §10 row 6) ----------------------


def test_before_commit_failure_rolls_back_with_no_row_and_no_alert(env: Env) -> None:
    name, p = f"BC {tag()}", plug()
    first = env.imp(doc(name, [p]), "bc.bit")
    m, i0, cat0, c0 = before(env)
    seen: list[int] = []

    def fail(pid: int) -> None:
        seen.append(pid)
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        env.imp(doc(name, [p], desc="v2"), "bc.bit", before_commit=fail)
    assert seen == [first.policy_id]
    assert env.imports_after(i0) == [] and env.entries(m) == []  # #98 (j)
    assert env.catalog() == cat0 and delta(c0) == {}


def test_a_database_error_in_the_store_writes_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*a: Any, **k: Any) -> None:
        raise psycopg.errors.QueryCanceled("canceling statement")

    m, i0, cat0, c0 = before(env)
    monkeypatch.setattr(catalog_plugins, "replace_membership", broken)
    with pytest.raises(psycopg.Error):
        env.imp(doc(f"DB {tag()}", [plug(), plug()]), "db.bit")
    monkeypatch.undo()
    assert env.imports_after(i0) == [] and env.entries(m) == []
    assert env.catalog() == cat0 and delta(c0) == {}


def test_a_record_failure_after_commit_keeps_the_catalog(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*a: Any, **k: Any) -> int:
        raise psycopg.OperationalError("server closed the connection")

    name, marker = f"RF {tag()}", f"cat /etc/marker-{tag()}"
    m, i0, c0 = env.mark(), env.last_import(), counters()
    monkeypatch.setattr(imports_repo, "insert_import", broken)
    caplog.set_level(logging.DEBUG)
    out = env.imp(doc(name, [plug(marker)]), "rf.bit")
    monkeypatch.undo()
    assert out.outcome == "success" and out.import_id is None
    stored = env.policy_by_name(name)
    assert stored is not None and stored["policy_id"] == out.policy_id
    assert env.imports_after(i0) == []
    assert [e["action"] for e in env.entries(m)] == ["policy.import"]
    assert delta(c0) == {"policy_imported": 1.0}
    assert "bit_import record failed: OperationalError" in caplog.text
    assert marker not in caplog.text and name not in caplog.text


def test_a_record_failure_on_a_rejection_propagates_without_the_alert(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*a: Any, **k: Any) -> int:
        raise psycopg.OperationalError("gone")

    m, i0, cat0, c0 = before(env)
    monkeypatch.setattr(imports_repo, "insert_import", broken)
    with pytest.raises(psycopg.OperationalError):
        env.imp(doc(f"RR {tag()}", [plug()], status="on"), "rr.bit")
    monkeypatch.undo()
    assert env.imports_after(i0) == [] and env.entries(m) == []
    assert env.catalog() == cat0 and delta(c0) == {}


def test_after_commit_failure_still_writes_the_success_row(env: Env) -> None:
    name = f"AC {tag()}"
    seen: list[ImportOutcome] = []
    i0 = env.last_import()

    def rename(o: ImportOutcome) -> None:
        seen.append(o)
        raise OSError("rename failed")

    with pytest.raises(OSError, match="rename failed"):
        env.imp(doc(name, [plug()]), None, name="ac.bit", after_commit=rename)
    (o,) = seen
    assert (o.outcome, o.import_id, o.policy_name) == ("success", None, name)
    (row,) = env.imports_after(i0)
    assert (row["outcome"], row["file_name"]) == ("success", "ac.bit")
    assert env.policy_by_name(name) is not None  # committed before the rename


def test_after_commit_runs_after_the_commit_and_before_the_record(env: Env) -> None:
    name = f"Order {tag()}"
    i0 = env.last_import()
    seen: list[tuple[bool, int]] = []

    def check(o: ImportOutcome) -> None:
        with app(env.server) as c:  # another connection sees the commit
            row = c.execute(
                "SELECT count(*) FROM policy WHERE policy_name = %s", (name,)
            ).fetchone()
        seen.append((row == (1,), len(env.imports_after(i0))))

    out = env.imp(doc(name, [plug()]), None, name="o.bit", after_commit=check)
    assert seen == [(True, 0)] and isinstance(out.import_id, int)


# Read once, purity, actors, logs (CHK-M7-195, plan §10 row 10) -------------------


def test_the_buffer_is_used_and_the_file_is_never_opened(env: Env) -> None:
    name, p = f"Once {tag()}", plug("cat /etc/first")
    data = doc(name, [p])
    env.put("once.bit", doc(name, [P(p.uuid, "cat /etc/changed-on-disk")]))
    f = env.file(data, "once.bit")
    prep = prepare(data)
    with env.db.session() as s, catalog_lock(s), no_side_effects() as events:
        out = import_one(
            s, env.clock, env.bits, f, mode="manual", actor=SYSTEM,
            file_exists=lambda rel: True, prepared=prep,
        )  # fmt: skip
    assert out.outcome == "success"
    assert [e for e in events if str(env.bits) in e[1]] == []
    pol = env.policy(out.policy_id or 0)
    assert pol["source_sha256"] == sha(data)
    assert env.plugin(p.uuid)["execute"] == "cat /etc/first"


def test_prepare_is_pure() -> None:
    assert list(inspect.signature(prepare).parameters) == ["data"]
    data = canonical(2)
    with no_side_effects() as events:
        a = prepare(data)
        b = prepare(data)
    assert events == [] and a == b and a.candidate is not None
    assert prepare(None).candidate is None
    assert [f.code.value for f in prepare(None).findings] == ["BIT001"]


@pytest.mark.parametrize(
    ("actor", "imported_by"),
    [(Actor("user:42", 42), 42), (Actor("cli:root", None), None), (SYSTEM, None)],
)
def test_actor_and_imported_by(env: Env, actor: Actor, imported_by: int | None) -> None:
    m, i0 = env.mark(), env.last_import()
    env.imp(doc(f"Actor {tag()}", [plug()]), f"ac-{tag()}.bit", actor=actor)
    env.imp(
        doc(f"Actor {tag()}", [plug()], status="on"), f"ar-{tag()}.bit", actor=actor
    )
    rows = env.imports_after(i0)
    assert [r["imported_by"] for r in rows] == [imported_by, imported_by]
    assert {e["actor"] for e in env.entries(m)} == {actor.audit}


def test_no_file_content_reaches_the_logs(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = f"cat /etc/secret-{tag()}"
    name = f"Logs {tag()}"
    env.imp(doc(name, [plug(marker)], desc=marker), "lg.bit")
    env.imp(doc(name, [plug(marker), plug("rm x")]), "lg.bit")
    env.imp(doc(name, [plug(marker)], status="on"), "lg.bit")
    for text in (marker, name, "rm x"):
        assert text not in caplog.text


def test_the_callers_lock_is_held_throughout_and_not_released(env: Env) -> None:
    # D4: the caller holds the catalog lock; import_one neither takes nor
    # releases it, so another session cannot get it during the import (even
    # in before_commit) or after import_one returns, until the caller lets go.
    def lock_free() -> bool:
        with app(env.server) as probe:
            row = probe.execute(
                "SELECT pg_try_advisory_lock(hashtext('catalog'))"
            ).fetchone()
            if row == (True,):
                probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
            return row == (True,)

    seen: list[bool] = []
    data = doc(f"Lock {tag()}", [plug()])
    f = env.file(data, env.put("lock.bit", data))
    with env.db.session() as s, catalog_lock(s):
        out = import_one(
            s, env.clock, env.bits, f, mode="manual", actor=SYSTEM,
            file_exists=env.exists, before_commit=lambda _: seen.append(lock_free()),
            after_commit=lambda _: seen.append(lock_free()),
        )  # fmt: skip
        seen.append(lock_free())
    assert out.outcome == "success"
    assert seen == [False, False, False]
    assert lock_free()
