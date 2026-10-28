"""TP-M7-14 (TASK-154): the import pipeline ``import_one`` on PostgreSQL.

CHK-M7-190 to -196 (tests/m7/test-plan.md); plan work/plans/TASK-154.md §10
rows 1 to 8 and 10; mutation rows CHK-M7-333, -339, -349, -350, -369. Expected
values come from the spec and the approved answers, not from the code:
TS §4.1 L516-L532 (read once, one catalog transaction, then the record in its
own transaction; every import audit-logged and alerted; ``auto`` skips an
unchanged file, ``manual`` and ``rebuild`` never skip), TS §5.2 (``bit_import``
columns; the app only inserts it), TS §8.4 L1290-L1291 (the import alert
carries every changed Execute; a rejected import alerts; the import-failure
metric), SR §3.6 (roll back the whole file on any error), SR L250 (only BIT001
and BIT002 stop the content rules), #23 (a skip writes no audit entry), #98 (j)
(an internal error is not a rejection: no row), #99 (b), (e), #100 (a) as
widened, #101 (actions, kinds, actors, targets, the metric label), #110
(warnings stored, never reject), REQ-150, -155, -157, -160, -162.

Owner: tester-m7-154. The code under test runs as ``bitscan_app``; results are
read as owner. Each test uses fresh policy names and plugin ids, except the
byte-identical SR §1.1 example (one test) and the ``bits/tests/db`` pairs.
"""

from __future__ import annotations

import inspect
import logging
import secrets
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import catalog_plugins
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import pipeline, pipeline_record, store
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    Mode,
    Pending,
    import_one,
    prepare,
    record,
    store_in_savepoint,
)

from .bit_unit import FIXTURES, fixture, no_side_effects
from .canary import new_canary
from .catalog_rows import T1, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .pipeline_rows import (
    ALL,
    MODES,
    NONE,
    FixedClock,
    P,
    audits_since,
    bit,
    bits_dir,
    catalog_now,
    codes,
    counter_delta,
    counters,
    imports_since,
    members,
    policy_by_name,
    policy_row,
    server_file,
    sha,
    snap,
    upload_file,
)
from .test_bit_fixtures import sr_example

pytestmark = pytest.mark.pg

USER = Actor("user:7", 7)
SYSTEM = Actor("system", None)
FINDING_KEYS = {"line", "element", "code", "message"}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("pipeline")) as s:
        yield s


@pytest.fixture(scope="module")
def db(server: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    return bits_dir(tmp_path)


def run(
    db: AppDatabase,
    bits: Path,
    file: FileInput,
    mode: str = "manual",
    actor: Actor = USER,
    exists: Callable[[str], bool] = NONE,
    **kw: Any,
) -> ImportOutcome:
    """The caller's side of the contract: a pinned session holding the lock."""
    with db.session() as s, catalog_lock(s):
        return import_one(
            s,
            FixedClock(),
            bits,
            file,
            mode=Mode(mode),
            actor=actor,
            file_exists=exists,
            **kw,
        )


def one(rows: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(rows) == 1, rows
    return rows[0]


# CHK-M7-190 / CHK-M7-192: the SR §1.1 example, then auto, manual, rebuild ----

SR_NAME = "CIS Ubuntu 24.04 Level 1 - Server"
SR_UUID = "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"
SR_EXEC = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"


def test_sr_example_imports_with_one_success_row_and_one_alert_then_auto_skips(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data = sr_example()
    assert sha(data) == FIXTURES["valid/sr-1.1-example.bit"]["sha256"]
    assert policy_by_name(server, SR_NAME) is None  # this test is its only importer
    s0 = snap(server)
    out = run(db, bits, server_file(data, "sr.bit"), "manual")

    row = one(imports_since(server, s0))
    assert {k: v for k, v in row.items() if k not in ("import_id", "xmin")} == {
        "file_name": "sr.bit",
        "file_sha256": sha(data),
        "policy_version": 1,
        "mode": "manual",
        "outcome": "success",
        "plugins_added": 1,
        "plugins_updated": 0,
        "plugins_retired": 0,
        "errors": [],
        "imported_by": 7,
        "imported_at": T1,
    }
    assert (out.import_id, out.outcome, out.policy_name, out.policy_version) == (
        row["import_id"], "success", SR_NAME, 1,
    )  # fmt: skip
    assert (out.plugins_added, out.plugins_updated, out.plugins_retired) == (1, 0, 0)
    assert out.findings == ()
    pid = out.policy_id
    assert pid is not None
    pol = policy_row(server, pid)
    assert (pol["version"], pol["source_file"], pol["source_sha256"]) == (
        1, "sr.bit", sha(data),
    )  # fmt: skip
    assert members(server, pid) == [(UUID(SR_UUID), SR_EXEC, "active")]

    entry = one(audits_since(server, s0))
    assert (entry["actor"], entry["action"], entry["target"]) == (
        "user:7", "policy.import", f"policy:{pid}",
    )  # fmt: skip
    d = entry["detail"]
    assert d["alert"] is True and d["alert_kind"] == "policy_imported"
    assert (d["policy_id"], d["policy_name"], d["version"], d["mode"]) == (
        pid, SR_NAME, 1, "manual",
    )  # fmt: skip
    assert (d["file_sha256"], d["source_file"], d["revived"]) == (
        sha(data), "sr.bit", False,
    )  # fmt: skip
    assert (d["plugins_added"], d["plugins_updated"], d["plugins_retired"]) == (1, 0, 0)
    assert d["changed_executes"] == [
        {
            "plugin_uuid": SR_UUID,
            "plugin_name": "1.3.1.1 - Ensure AppArmor is installed",
            "execute": SR_EXEC,
            "execute_sha256": sha(SR_EXEC.encode()),
            "reason": "new",
            "flags": [],
        }
    ]
    assert counter_delta(s0) == {"alert:policy_imported": 1.0}
    # The alert is in the catalog transaction; the record is in its own (D4).
    assert entry["xmin"] == pol["xmin"]
    assert row["xmin"] != pol["xmin"]

    # auto + unchanged: exactly one skipped row, nothing else (#23).
    s1 = snap(server)
    skipped = run(db, bits, server_file(data, "sr.bit"), "auto", actor=SYSTEM)
    srow = one(imports_since(server, s1))
    assert (srow["outcome"], srow["mode"], srow["policy_version"]) == (
        "skipped", "auto", 1,
    )  # fmt: skip
    counts = ("plugins_added", "plugins_updated", "plugins_retired")
    assert [srow[k] for k in counts] == [0, 0, 0]
    assert (srow["errors"], srow["imported_by"], srow["file_sha256"]) == (
        [], None, sha(data),
    )  # fmt: skip
    assert (skipped.outcome, skipped.policy_id, skipped.import_id) == (
        "skipped", pid, srow["import_id"],
    )  # fmt: skip
    assert audits_since(server, s1) == []
    assert counter_delta(s1) == {}
    assert catalog_now(server) == s1.catalog

    # The plain string "auto" behaves like Mode.AUTO.
    s1b = snap(server)
    with db.session() as s, catalog_lock(s):
        again = import_one(
            s, FixedClock(), bits, server_file(data, "sr.bit"),
            mode=cast(Mode, "auto"), actor=SYSTEM, file_exists=NONE,
        )  # fmt: skip
    assert again.outcome == "skipped"
    assert one(imports_since(server, s1b))["mode"] == "auto"

    # manual and rebuild never skip; identical bytes keep version 1, 0/0/0,
    # and still write the import alert ("every import alerts").
    for mode in ("manual", "rebuild"):
        s2 = snap(server)
        o = run(db, bits, server_file(data, "sr.bit"), mode)
        r = one(imports_since(server, s2))
        assert (r["outcome"], r["mode"], r["policy_version"]) == ("success", mode, 1)
        assert (r["plugins_added"], r["plugins_updated"], r["plugins_retired"]) == (
            0, 0, 0,
        )  # fmt: skip
        assert o.policy_id == pid
        if mode == "manual":  # every manual import alerts
            e = one(audits_since(server, s2))
            assert e["action"] == "policy.import" and e["detail"]["mode"] == mode
            assert e["detail"]["changed_executes"] == []
            assert counter_delta(s2) == {"alert:policy_imported": 1.0}
        else:  # r1: a rebuild putting no command live stays quiet (#23, #100 (a))
            assert audits_since(server, s2) == []
            assert counter_delta(s2) == {}


# CHK-M7-191: every rejecting fixture -----------------------------------------

REJECTING = sorted(
    n for n, f in FIXTURES.items() if f["outcome"] == "rejected" and n[:3] != "db/"
)


@pytest.mark.parametrize("name", REJECTING)
def test_each_rejecting_fixture_is_one_rejected_row_one_alert_no_catalog_change(
    server: PgServer, db: AppDatabase, bits: Path, name: str
) -> None:
    entry = FIXTURES[name]
    canary = bits / f"canary-{tag()}"
    data = fixture(name, canary=str(canary), port=9)
    mode = MODES[REJECTING.index(name) % 3]
    file = server_file(data, f"fx-{tag()}.bit")
    s0 = snap(server)
    out = run(db, bits, file, mode, actor=SYSTEM)

    assert out.outcome == "rejected"
    row = one(imports_since(server, s0))
    assert (row["outcome"], row["mode"], row["policy_version"], row["imported_by"]) == (
        "rejected", mode, None, None,
    )  # fmt: skip
    assert (row["plugins_added"], row["plugins_updated"], row["plugins_retired"]) == (
        0, 0, 0,
    )  # fmt: skip
    assert (row["file_name"], row["file_sha256"]) == (file.file_name, sha(data))
    errors = row["errors"]
    assert sorted(set(codes(errors))) == sorted(entry["codes"]), errors
    assert errors == [f.to_json() for f in out.findings]
    assert all(set(e) == FINDING_KEYS for e in errors)
    lines = [e["line"] or 0 for e in errors]
    assert lines == sorted(lines)  # REQ-155 (5)
    first = next(e for e in errors if e["code"] == entry["codes"][0])
    if entry.get("lines") and len(entry["codes"]) == 1:
        assert first["line"] in entry["lines"], first
    if "element" in entry:
        assert first["element"] == entry["element"], first

    alert = one(audits_since(server, s0))
    assert (alert["action"], alert["actor"]) == ("policy.import_rejected", "system")
    d = alert["detail"]
    assert d["alert"] is True and d["alert_kind"] == "policy_import_rejected"
    assert (d["import_id"], d["mode"], d["file_name"]) == (
        row["import_id"], mode, file.file_name,
    )  # fmt: skip
    assert d["codes"] == list(dict.fromkeys(codes(errors)))
    expected_target = (
        f"policy:{out.policy_id}" if out.policy_id is not None else file.file_name
    )
    assert alert["target"] == expected_target
    assert alert["xmin"] == row["xmin"]  # the alert is in the record transaction
    assert counter_delta(s0) == {
        "alert:policy_import_rejected": 1.0,
        f"fail:{mode}": 1.0,
    }
    assert catalog_now(server) == s0.catalog
    assert not canary.exists()


# Size and count boundaries (SR §2.3, §4.1 BIT001, BIT017; #99 (b)) ---------------


def padded(data: bytes, size: int) -> bytes:
    decl, rest = data.split(b"\n", 1)
    overhead = len(data) + len(b"<!---->\n")
    out = decl + b"\n<!--" + b"a" * (size - overhead) + b"-->\n" + rest
    assert len(out) == size
    return out


def test_oversize_folder_file_without_a_buffer_is_one_bit001_row(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    streamed = "e" * 64
    s0 = snap(server)
    out = run(db, bits, server_file(None, "big.bit", digest=streamed), "auto", SYSTEM)
    row = one(imports_since(server, s0))
    assert (out.outcome, row["outcome"], row["file_sha256"]) == (
        "rejected", "rejected", streamed,
    )  # fmt: skip
    assert row["errors"] == [
        {"line": None, "element": None, "code": "BIT001",
         "message": "The file is larger than 5 MiB."}
    ]  # fmt: skip
    assert one(audits_since(server, s0))["target"] == "big.bit"
    assert counter_delta(s0) == {"alert:policy_import_rejected": 1.0, "fail:auto": 1.0}
    assert catalog_now(server) == s0.catalog


def test_5_mib_passes_and_one_byte_more_is_bit001(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    limit = 5 * 1024 * 1024
    at, _ = bit()
    ok = run(db, bits, upload_file(padded(at, limit)))
    assert ok.outcome == "success", ok.findings
    over, _ = bit()
    s0 = snap(server)
    bad = run(db, bits, upload_file(padded(over, limit + 1)))
    assert bad.outcome == "rejected"
    assert codes(one(imports_since(server, s0))["errors"]) == ["BIT001"]
    assert catalog_now(server) == s0.catalog


def test_5000_plugins_import_and_5001_are_bit017(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, ids = bit(plugins=[P(execute=f"echo {i}") for i in range(5000)])
    s0 = snap(server)
    out = run(db, bits, upload_file(data))
    assert (out.outcome, out.plugins_added) == ("success", 5000), out.findings[:3]
    assert out.policy_id is not None
    assert [m[0] for m in members(server, out.policy_id)] == ids
    entry = one(audits_since(server, s0))
    assert len(entry["detail"]["changed_executes"]) == 5000

    data2, _ = bit(plugins=[P(execute=f"echo {i}") for i in range(5001)])
    s1 = snap(server)
    bad = run(db, bits, upload_file(data2))
    assert bad.outcome == "rejected"
    assert "BIT017" in codes(one(imports_since(server, s1))["errors"])
    assert catalog_now(server) == s1.catalog


# Plan row 4: database rules beside file-local faults (SR L250) ----------------


def test_bit007_is_rejected_with_the_matched_policy_as_target_and_beside_bit003(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    a = run(db, bits, server_file(fixture("db/bit007-a.bit"), "bit007-a.bit"))
    assert a.outcome == "success"
    b = fixture("db/bit007-b.bit")
    s0 = snap(server)
    out = run(db, bits, server_file(b, "bit007-b.bit"), "auto", exists=ALL)
    row = one(imports_since(server, s0))
    assert codes(row["errors"]) == ["BIT007"]
    assert row["errors"][0]["element"] == "Policy/PolicyName"
    assert row["errors"][0]["line"] == 4
    assert out.policy_id == a.policy_id
    assert one(audits_since(server, s0))["target"] == f"policy:{a.policy_id}"
    assert catalog_now(server) == s0.catalog

    both = b.replace(b"<PolicyStatus>enabled<", b"<PolicyStatus>on<")
    s1 = snap(server)
    run(db, bits, server_file(both, "bit007-b.bit"), "auto", exists=ALL)
    errors = one(imports_since(server, s1))["errors"]
    assert [(e["code"], e["line"]) for e in errors] == [("BIT007", 4), ("BIT003", 6)]
    assert catalog_now(server) == s1.catalog


def test_bit015_is_rejected_beside_bit003_and_passes_once_the_owner_drops_the_id(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    owner_out = run(db, bits, server_file(fixture("db/bit015-owner.bit"), "o15.bit"))
    assert owner_out.outcome == "success"
    claimer = fixture("db/bit015-claimer.bit")
    s0 = snap(server)
    out = run(db, bits, server_file(claimer, "c15.bit"))
    errors = one(imports_since(server, s0))["errors"]
    assert codes(errors) == ["BIT015"]
    assert errors[0]["element"] == "Policy/PluginsGroups/Plugin[2]/PluginId"
    assert out.outcome == "rejected"
    assert catalog_now(server) == s0.catalog

    both = claimer.replace(b"<PolicyStatus>enabled<", b"<PolicyStatus>on<")
    s1 = snap(server)
    run(db, bits, server_file(both, "c15.bit"))
    errors = one(imports_since(server, s1))["errors"]
    assert codes(errors) == ["BIT003", "BIT015"]  # by line
    assert errors[0]["line"] < errors[1]["line"]
    assert catalog_now(server) == s1.catalog

    dropped = fixture("db/bit015-owner-dropped.bit")
    assert run(db, bits, server_file(dropped, "o15.bit")).outcome == "success"
    ok = run(db, bits, server_file(claimer, "c15.bit"))
    assert ok.outcome == "success", ok.findings
    with owner(server) as c:
        owners = c.execute(
            "SELECT DISTINCT owner_policy_id FROM plugin p JOIN policy_plugin pp"
            " USING (plugin_uuid) WHERE pp.policy_id = %s",
            (ok.policy_id,),
        ).fetchall()
    assert owners == [(ok.policy_id,)]


@pytest.mark.parametrize("version", ["2.0", "1.1"])
def test_bit016_is_reported_with_the_content_faults(
    server: PgServer, db: AppDatabase, bits: Path, version: str
) -> None:
    data, _ = bit(status="on", format_version=version)
    s0 = snap(server)
    out = run(db, bits, upload_file(data))
    errors = one(imports_since(server, s0))["errors"]
    assert out.outcome == "rejected"
    assert sorted(codes(errors)) == ["BIT003", "BIT016"]
    assert catalog_now(server) == s0.catalog


def test_bit002_stops_the_content_rules(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(status="on")
    data = data.replace(b"  <Family>", b"  <Extra/>\n  <Family>")
    s0 = snap(server)
    run(db, bits, upload_file(data))
    assert codes(one(imports_since(server, s0))["errors"]) == ["BIT002"]


# CHK-M7-193: warnings (#110) ----------------------------------------------------


def test_warnings_only_file_is_success_with_its_warnings_stored(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data = fixture("valid/warnings-only.bit")
    s0 = snap(server)
    out = run(db, bits, server_file(data, "warn.bit"), "auto", SYSTEM)
    row = one(imports_since(server, s0))
    assert (out.outcome, row["outcome"], row["policy_version"]) == (
        "success", "success", 1,
    )  # fmt: skip
    assert sorted(set(codes(row["errors"]))) == ["BIT101", "BIT103"]
    assert row["errors"] == [f.to_json() for f in out.findings]
    assert counter_delta(s0) == {"alert:policy_imported": 1.0}


def test_a_rejected_file_lists_its_warnings_too(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(plugins=[P(name="No reference here", execute="rm -f /etc/x")])
    s0 = snap(server)
    out = run(db, bits, upload_file(data))
    assert out.outcome == "rejected"
    assert sorted(set(codes(one(imports_since(server, s0))["errors"]))) == [
        "BIT101", "BIT102",
    ]  # fmt: skip


# CHK-M7-369 / REQ-160 (2): skip rules ------------------------------------------


def test_auto_skip_only_for_an_unchanged_last_success(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name, [P(), P()])
    first = run(db, bits, server_file(d1, "sk.bit"), "auto", SYSTEM)
    assert (first.outcome, first.policy_version) == ("success", 1)
    # changed bytes in auto: imported, version + 1
    d2, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue"), P(uuid=ids[1])])
    second = run(db, bits, server_file(d2, "sk.bit"), "auto", SYSTEM)
    assert (second.outcome, second.policy_version, second.plugins_updated) == (
        "success", 2, 1,
    )  # fmt: skip
    # one plugin dropped: the counts reach the row
    d3, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])
    s0 = snap(server)
    third = run(db, bits, server_file(d3, "sk.bit"), "manual")
    row = one(imports_since(server, s0))
    assert (row["policy_version"], row["plugins_added"], row["plugins_updated"],
            row["plugins_retired"]) == (3, 0, 0, 1)  # fmt: skip
    assert third.policy_id == first.policy_id
    # a rejected file is tried again every time in auto mode
    bad = d3.replace(b"<PolicyStatus>enabled<", b"<PolicyStatus>on<")
    s1 = snap(server)
    for _ in range(2):
        assert run(db, bits, server_file(bad, "sk.bit"), "auto").outcome == "rejected"
    assert [r["outcome"] for r in imports_since(server, s1)] == ["rejected"] * 2
    assert counter_delta(s1)["fail:auto"] == 2.0


def test_auto_skips_an_unchanged_live_upload_and_manual_upload_does_not(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit()
    first = run(db, bits, upload_file(data))
    assert first.outcome == "success"
    s0 = snap(server)
    assert run(db, bits, upload_file(data), "auto", SYSTEM).outcome == "skipped"
    assert audits_since(server, s0) == [] and catalog_now(server) == s0.catalog
    assert run(db, bits, upload_file(data), "manual").outcome == "success"


# CHK-M7-333: BIT102 on every entry point --------------------------------------

BIT102_FIXTURES = sorted(
    n for n, f in FIXTURES.items() if n.startswith("content/bit102-")
)


@pytest.mark.parametrize("kind", ["server", "upload"])
@pytest.mark.parametrize("mode", MODES)
def test_bit102_rejects_in_every_mode_and_target(
    server: PgServer, db: AppDatabase, bits: Path, mode: str, kind: str
) -> None:
    for name in BIT102_FIXTURES:
        data = fixture(name)
        file = upload_file(data) if kind == "upload" else server_file(data)
        for given in (None, prepare(data)):
            s0 = snap(server)
            out = run(db, bits, file, mode, prepared=given)
            assert out.outcome == "rejected", (name, mode, kind)
            assert "BIT102" in codes(one(imports_since(server, s0))["errors"])
            assert catalog_now(server) == s0.catalog


# CHK-M7-350: the failure metric counts once per rejection, with its mode -------


@pytest.mark.parametrize("mode", MODES)
def test_failure_metric_counts_once_per_rejection_with_its_mode(
    server: PgServer, db: AppDatabase, bits: Path, mode: str
) -> None:
    s0 = snap(server)
    for i in range(1, 3):
        data, _ = bit(status="maybe")
        run(db, bits, upload_file(data), mode)
        assert counter_delta(s0) == {
            "alert:policy_import_rejected": float(i),
            f"fail:{mode}": float(i),
        }


def test_rejecting_an_update_names_the_policy_and_keeps_it(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name)
    ok = run(db, bits, server_file(d1, "ru.bit"))
    d2, _ = bit(name, [P(uuid=ids[0], execute="rm -rf /")])
    s0 = snap(server)
    out = run(db, bits, server_file(d2, "ru.bit"))
    assert (out.outcome, out.policy_id) == ("rejected", ok.policy_id)
    assert one(audits_since(server, s0))["target"] == f"policy:{ok.policy_id}"
    assert catalog_now(server) == s0.catalog


def test_long_client_name_is_kept_whole_and_cut_to_255_in_the_target(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    client = "é" * 300 + ".bit"
    s0 = snap(server)
    run(db, bits, upload_file(b"<Policy", client))
    assert one(imports_since(server, s0))["file_name"] == client
    assert one(audits_since(server, s0))["target"] == client[:255]


# Plan row 5: an upload of a server-folder policy (#99 (e)) ---------------------


def test_upload_of_a_server_folder_policy_is_refused_with_no_row_and_no_alert(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, _ = bit(name)
    srv = run(db, bits, server_file(d1, "srv.bit"))
    client = new_canary("client")
    d2, _ = bit(name)
    s0 = snap(server)
    with pytest.raises(store.PolicyManagedOnServer) as err:
        run(db, bits, upload_file(d2, client))
    assert err.value.policy_id == srv.policy_id
    assert imports_since(server, s0) == []
    entry = one(audits_since(server, s0))
    assert (entry["action"], entry["target"], entry["actor"]) == (
        "policy.import_refused", f"policy:{srv.policy_id}", "user:7",
    )  # fmt: skip
    assert "alert" not in entry["detail"]
    assert client not in str(entry)
    assert counter_delta(s0) == {}
    assert catalog_now(server) == s0.catalog


# CHK-M7-194 / REQ-162 (4): a rolled-back import --------------------------------


def test_before_commit_gets_the_policy_id_and_its_failure_rolls_everything_back(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(plugins=[P(), P(), P()])
    seen: list[int] = []

    def boom(policy_id: int) -> None:
        seen.append(policy_id)
        raise OSError("disk full")

    s0 = snap(server)
    with pytest.raises(OSError, match="disk full"):
        run(db, bits, upload_file(data), before_commit=boom)
    assert len(seen) == 1 and isinstance(seen[0], int)
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == []  # #98 (j): not a rejection
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}

    # update: before_commit gets the existing id; the old version stays
    name = f"Pipeline {tag()}"
    d1, ids = bit(name)
    ok = run(db, bits, upload_file(d1))
    d2, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])
    seen.clear()
    s1 = snap(server)
    with pytest.raises(OSError):
        run(db, bits, upload_file(d2), before_commit=boom)
    assert seen == [ok.policy_id]
    assert catalog_now(server) == s1.catalog
    assert imports_since(server, s1) == [] and audits_since(server, s1) == []
    assert counter_delta(s1) == {}


def _div0(conn: psycopg.Connection[Any]) -> None:
    conn.execute("SELECT 1/0")  # a real database error, which aborts the transaction


@pytest.mark.parametrize("where", ["membership", "after_store", "after_audit"])
@pytest.mark.parametrize("mode", MODES)
def test_database_error_in_the_catalog_transaction_is_not_a_rejection(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    mode: str,
) -> None:
    if where == "membership":
        real_m = catalog_plugins.replace_membership

        def membership(conn: Any, *a: Any, **k: Any) -> Any:
            _div0(conn)
            return real_m(conn, *a, **k)

        monkeypatch.setattr(catalog_plugins, "replace_membership", membership)
    elif where == "after_store":
        real_a = store.apply

        def apply(conn: Any, *a: Any, **k: Any) -> Any:
            out = real_a(conn, *a, **k)
            _div0(conn)
            return out

        monkeypatch.setattr(store, "apply", apply)
    else:
        real_s = pipeline_record.audit_success

        def audit(tx: Any, *a: Any, **k: Any) -> None:
            real_s(tx, *a, **k)
            _div0(tx.conn)

        monkeypatch.setattr(pipeline, "audit_success", audit)
    data, _ = bit(plugins=[P(), P(), P()])
    s0 = snap(server)
    with pytest.raises(psycopg.errors.DivisionByZero):
        run(db, bits, server_file(data), mode)
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == []
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}


def test_record_failure_after_a_committed_success_keeps_the_catalog(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def bad(conn: Any, *a: Any, **k: Any) -> int:
        _div0(conn)
        return 0

    monkeypatch.setattr(imports_repo, "insert_import", bad)
    caplog.set_level(logging.INFO)
    data, ids = bit()
    s0 = snap(server)
    out = run(db, bits, server_file(data))
    assert (out.outcome, out.import_id) == ("success", None)
    assert out.policy_id is not None
    assert [m[0] for m in members(server, out.policy_id)] == ids  # committed
    assert imports_since(server, s0) == []
    assert one(audits_since(server, s0))["action"] == "policy.import"
    assert counter_delta(s0) == {"alert:policy_imported": 1.0}
    assert "bit_import record failed: DivisionByZero" in caplog.text


@pytest.mark.parametrize("outcome", ["rejected", "skipped"])
def test_record_failure_with_nothing_committed_propagates(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    data, _ = bit()
    if outcome == "skipped":
        run(db, bits, upload_file(data))
    else:
        data = data.replace(b"<PolicyStatus>enabled<", b"<PolicyStatus>on<")

    def bad(conn: Any, *a: Any, **k: Any) -> int:
        _div0(conn)
        return 0

    monkeypatch.setattr(imports_repo, "insert_import", bad)
    s0 = snap(server)
    with pytest.raises(psycopg.errors.DivisionByZero):
        run(db, bits, upload_file(data), "auto")
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    assert catalog_now(server) == s0.catalog


def test_after_commit_runs_after_the_commit_and_before_the_record(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit()
    s0 = snap(server)
    seen: list[tuple[str, int | None, bool, int]] = []

    def rename(p: Pending) -> None:
        visible = (
            p.policy_id is not None
            and policy_by_name(server, str(p.policy_name)) is not None
        )  # committed: visible from another connection
        seen.append((p.outcome, p.policy_id, visible, len(imports_since(server, s0))))
        raise OSError("rename failed")

    with pytest.raises(OSError, match="rename failed"):
        run(db, bits, upload_file(data), after_commit=rename)
    assert len(seen) == 1
    outcome, pid, visible, rows_then = seen[0]
    assert (outcome, visible, rows_then) == ("success", True, 0)
    row = one(imports_since(server, s0))  # the success row is still written
    assert (row["outcome"], row["policy_version"]) == ("success", 1)
    assert pid is not None and policy_row(server, pid)["version"] == 1


def test_after_commit_is_not_called_for_a_rejection_or_a_skip(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    calls: list[Pending] = []
    data, _ = bit()
    run(db, bits, upload_file(data))
    again = run(db, bits, upload_file(data), "auto", after_commit=calls.append)
    assert again.outcome == "skipped"
    bad = data.replace(b"<PolicyStatus>enabled<", b"<PolicyStatus>on<")
    out = run(db, bits, upload_file(bad), after_commit=calls.append)
    assert out.outcome == "rejected"
    assert calls == []


# Plan row 8: move, displaced policy, re-enable (#100, #101, #106) ---------------


def test_reenable_by_file_alerts_and_an_admin_override_suppresses_it(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name, status="disabled")
    first = run(db, bits, server_file(d1, "re.bit"))
    pid = first.policy_id
    assert pid is not None
    d2, _ = bit(name, [P(uuid=ids[0])], status="enabled")
    s0 = snap(server)
    run(db, bits, server_file(d2, "re.bit"))
    entries = audits_since(server, s0)
    assert [e["action"] for e in entries] == ["policy.import", "policy.status_change"]
    st = entries[1]
    assert st["target"] == f"policy:{pid}"
    assert st["detail"]["alert_kind"] == "policy_reenabled"
    assert (st["detail"]["by"], st["detail"]["status_overridden"]) == ("file", False)
    assert counter_delta(s0) == {
        "alert:policy_imported": 1.0, "alert:policy_reenabled": 1.0,
    }  # fmt: skip

    with owner(server) as c:
        c.execute(
            "UPDATE policy SET policy_status = 'disabled', status_overridden = true"
            " WHERE policy_id = %s",
            (pid,),
        )
    run(db, bits, server_file(d1, "re.bit"))
    s1 = snap(server)
    run(db, bits, server_file(d2, "re.bit"))
    assert [e["action"] for e in audits_since(server, s1)] == ["policy.import"]
    assert policy_row(server, pid)["policy_status"] == "disabled"


def test_move_from_upload_to_the_server_folder_writes_a_move_entry(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name)
    up = run(db, bits, upload_file(d1))
    pid = up.policy_id
    copy = bits / "uploaded" / f"policy-{pid}.bit"
    copy.write_bytes(d1)
    d2, _ = bit(name, [P(uuid=ids[0])])
    s0 = snap(server)
    out = run(db, bits, server_file(d2, "mv.bit"), "auto", SYSTEM)
    assert (out.outcome, out.policy_id) == ("success", pid)
    entries = audits_since(server, s0)
    assert [e["action"] for e in entries] == ["policy.import", "policy.move"]
    mv = entries[1]
    assert mv["target"] == f"policy:{pid}"
    assert mv["detail"] == {"from": f"uploaded/policy-{pid}.bit", "to": "mv.bit"}
    assert counter_delta(s0) == {"alert:policy_imported": 1.0}
    assert not copy.exists()  # removed after the commit
    assert policy_row(server, cast(int, pid))["source_file"] == "mv.bit"


def test_a_file_renamed_onto_an_uploaded_name_deletes_the_displaced_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    x_name, y_name = f"Pipeline X {tag()}", f"Pipeline Y {tag()}"
    dx, _ = bit(x_name)
    x = run(db, bits, server_file(dx, "ren.bit"))
    dy, y_ids = bit(y_name)
    y = run(db, bits, upload_file(dy))
    dy2, _ = bit(y_name, [P(uuid=y_ids[0])])
    s0 = snap(server)
    out = run(db, bits, server_file(dy2, "ren.bit"))
    assert (out.outcome, out.policy_id) == ("success", y.policy_id)
    entries = audits_since(server, s0)
    assert [e["action"] for e in entries] == [
        "policy.import", "policy.move", "policy.delete",
    ]  # fmt: skip
    dele = entries[2]
    assert dele["target"] == f"policy:{x.policy_id}"
    assert dele["detail"]["alert_kind"] == "policy_deleted"
    assert dele["detail"]["reason"] == "file now holds another policy"
    xr = policy_row(server, cast(int, x.policy_id))
    assert xr["deleted_at"] is not None
    assert counter_delta(s0) == {
        "alert:policy_imported": 1.0, "alert:policy_deleted": 1.0,
    }  # fmt: skip


# Plan row 7: rebuild support --------------------------------------------------


def test_rebuild_savepoints_store_the_good_files_and_record_every_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    da, a_ids = bit()
    db_, _ = bit(plugins=[P(execute="systemctl stop ssh")])  # BIT102
    dc, _ = bit()
    dd, _ = bit(plugins=[P(uuid=a_ids[0])])  # BIT015: a lists it
    files = [server_file(d) for d in (da, db_, dc, dd)]
    clock = FixedClock()
    s0 = snap(server)
    with db.session() as s, catalog_lock(s):
        with s.transaction() as tx:
            pend = [
                store_in_savepoint(
                    s, tx, clock, f, prepare(f.data), actor=SYSTEM, file_exists=NONE
                )
                for f in files
            ]
            assert counters() == s0.counters  # hooks run only after commit
        assert counter_delta(s0) == {"alert:policy_imported": 2.0}
        with s.transaction() as tx:
            ids = [
                record(tx, clock, f, Mode.REBUILD, SYSTEM, p)
                for f, p in zip(files, pend, strict=True)
            ]
    assert [p.outcome for p in pend] == ["success", "rejected", "success", "rejected"]
    rows = imports_since(server, s0)
    assert [r["import_id"] for r in rows] == ids
    assert [(r["outcome"], r["mode"]) for r in rows] == [
        ("success", "rebuild"), ("rejected", "rebuild"),
        ("success", "rebuild"), ("rejected", "rebuild"),
    ]  # fmt: skip
    assert codes(rows[1]["errors"]) == ["BIT102"]
    assert codes(rows[3]["errors"]) == ["BIT015"]
    entries = audits_since(server, s0)
    assert [e["action"] for e in entries] == [
        "policy.import", "policy.import",
        "policy.import_rejected", "policy.import_rejected",
    ]  # fmt: skip
    assert [e["target"] for e in entries[:2]] == [
        f"policy:{pend[0].policy_id}", f"policy:{pend[2].policy_id}",
    ]  # fmt: skip
    assert counter_delta(s0) == {
        "alert:policy_imported": 2.0,
        "alert:policy_import_rejected": 2.0,
        "fail:rebuild": 2.0,
    }
    with owner(server) as c:
        names = {
            n for (n,) in c.execute(
                "SELECT policy_name FROM policy WHERE policy_id > %s",
                (cast(int, pend[0].policy_id) - 1,),
            ).fetchall()
        }  # fmt: skip
    assert pend[1].policy_id is None and pend[3].policy_id is None
    assert len(names) == 2


# CHK-M7-195: read once ---------------------------------------------------------


def test_the_buffer_is_hashed_and_parsed_once_and_never_reread(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    path = bits / "once.bit"
    data, ids = bit(plugins=[P(execute="cat /etc/hostname")])
    path.write_bytes(data)
    buf = path.read_bytes()
    other, _ = bit(plugins=[P(execute="cat /etc/issue")])
    path.write_bytes(other)  # the file changes after the one read
    file = server_file(buf, "once.bit")
    s0 = snap(server)
    with no_side_effects() as events:
        out = run(db, bits, file)
    opened = [a for e, a in events if e == "open" and "once.bit" in a]
    assert opened == []
    pid = cast(int, out.policy_id)
    assert policy_row(server, pid)["source_sha256"] == sha(buf)
    assert one(imports_since(server, s0))["file_sha256"] == sha(buf)
    assert members(server, pid) == [(ids[0], "cat /etc/hostname", "active")]


# CHK-M7-196 extra: application logs --------------------------------------------


def test_execute_text_names_and_tokens_never_reach_application_logs(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    c = new_canary("exec")
    token = "bsa_" + secrets.token_urlsafe(32)
    pname = f"Policy {new_canary('name')}"
    fname = f"{new_canary('file')}.bit"
    ok_data, ids = bit(pname, [P(execute=f"echo {c} {token}")])
    run(db, bits, upload_file(ok_data, fname))
    run(db, bits, upload_file(ok_data, fname), "auto")
    bad, _ = bit(f"{pname} 2", [P(execute=f"rm /etc/{c}{token}")])
    run(db, bits, upload_file(bad, fname))
    status, _ = bit(f"{pname} 3", status=f"{c}{token}")
    run(db, bits, upload_file(status, fname))

    def fail(conn: Any, *a: Any, **k: Any) -> int:
        _div0(conn)
        return 0

    monkeypatch.setattr(imports_repo, "insert_import", fail)
    third, _ = bit(f"{pname} 4", [P(execute=f"echo {c} {token} again")])
    run(db, bits, upload_file(third, fname))

    texts = [caplog.text] + [
        f"{r.getMessage()} {r.args!r} {r.__dict__!r}" for r in caplog.records
    ]
    for secret in (c, token, pname, fname):
        assert not any(secret in t for t in texts), secret
    mine = [r.getMessage() for r in caplog.records if r.name == pipeline.__name__]
    assert any(m.startswith("bit import success") for m in mine), mine
    assert any(m.startswith("bit import rejected") for m in mine), mine
    assert any(m.startswith("bit import skipped") for m in mine), mine


# The caller-holds-the-lock contract (D4; TS §4.1 "Locking") ------------------------


def test_import_one_never_takes_the_catalog_lock_itself(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit()
    result: list[ImportOutcome | BaseException] = []

    def worker() -> None:
        try:
            with db.session() as s:
                result.append(
                    import_one(
                        s, FixedClock(), bits, upload_file(data), mode=Mode.MANUAL,
                        actor=USER, file_exists=NONE,
                    )
                )  # fmt: skip
        except BaseException as exc:  # reported below
            result.append(exc)

    with app(server) as probe:
        probe.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(30)
            assert not t.is_alive(), "import_one waited on the catalog lock"
        finally:
            probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    assert len(result) == 1 and isinstance(result[0], ImportOutcome), result
    assert result[0].outcome == "success"
    doc = inspect.getdoc(import_one) or ""
    assert "caller" in doc and "lock" in doc  # the contract is documented


def test_the_callers_lock_spans_the_rename_and_the_record(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit()

    def free(probe: psycopg.Connection[Any]) -> bool:
        row = probe.execute(
            "SELECT pg_try_advisory_lock(hashtext('catalog'))"
        ).fetchone()
        assert row is not None
        if row[0]:
            probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        return bool(row[0])

    held_at_rename: list[bool] = []
    with app(server) as probe:
        with db.session() as s, catalog_lock(s):

            def rename(p: Pending) -> None:
                held_at_rename.append(not free(probe))

            out = import_one(
                s, FixedClock(), bits, upload_file(data), mode=Mode.MANUAL,
                actor=USER, file_exists=NONE, after_commit=rename,
            )  # fmt: skip
            assert out.import_id is not None
            assert not free(probe)  # still the caller's after import_one returns
        assert free(probe)
    assert held_at_rename == [True]


# Plan row 10: prepare is pure; import_one uses the prepared result --------------


def test_prepare_is_pure_and_a_given_prepared_is_not_redone(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert list(inspect.signature(prepare).parameters) == ["data"]
    data, _ = bit()
    with no_side_effects() as events:
        prep = prepare(data)
    assert events == []
    assert prep.candidate is not None and prep.rules is not None
    calls: list[bytes | None] = []
    real = pipeline.prepare

    def spy(d: bytes | None) -> Any:
        calls.append(d)
        return real(d)

    monkeypatch.setattr(pipeline, "prepare", spy)
    assert run(db, bits, upload_file(data), prepared=prep).outcome == "success"
    assert calls == []
    other, _ = bit()
    assert run(db, bits, upload_file(other)).outcome == "success"
    assert calls == [other]


# Revision 1 (lead, 2026-10-28, "W6 rulings" Q1 + "TASK-154 r1 edge"): a rebuild
# writes `policy.import` only when it puts a command live on hosts (new,
# changed or reactivated; #23 with #100 (a) as widened). auto and manual keep
# their behaviour; moves, displaced deletes and re-enables keep their entries.

DESC = b"Generated by tester-m7-154."


def rebuild(db: AppDatabase, bits: Path, file: FileInput) -> ImportOutcome:
    return run(db, bits, file, "rebuild", SYSTEM)


def actions(server: PgServer, s: Any) -> list[str]:
    return [e["action"] for e in audits_since(server, s)]


def test_r1_rebuild_of_identical_bytes_is_success_with_no_alert(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(plugins=[P(), P()])
    file = server_file(data)
    first = run(db, bits, file)
    # through import_one
    s0 = snap(server)
    out = rebuild(db, bits, file)
    row = one(imports_since(server, s0))
    assert (out.outcome, row["outcome"], row["mode"], row["policy_version"]) == (
        "success", "success", "rebuild", 1,
    )  # fmt: skip
    counts = ("plugins_added", "plugins_updated", "plugins_retired")
    assert [row[k] for k in counts] == [0, 0, 0]
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    # through store_in_savepoint + record
    s1 = snap(server)
    clock = FixedClock()
    with db.session() as s, catalog_lock(s):
        with s.transaction() as tx:
            pend = store_in_savepoint(
                s, tx, clock, file, prepare(data), actor=SYSTEM, file_exists=NONE
            )
        with s.transaction() as tx:
            record(tx, clock, file, Mode.REBUILD, SYSTEM, pend)
    assert (pend.outcome, pend.policy_id) == ("success", first.policy_id)
    assert one(imports_since(server, s1))["outcome"] == "success"
    assert audits_since(server, s1) == []
    assert counter_delta(s1) == {}


@pytest.mark.parametrize("change", ["description", "rename", "disable"])
def test_r1_rebuild_with_bytes_changed_but_commands_unchanged_is_quiet(
    server: PgServer, db: AppDatabase, bits: Path, change: str
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name, [P(), P(execute="cat /etc/issue")])
    path = f"q-{tag()}.bit"
    first = run(db, bits, server_file(d1, path))
    same = [P(uuid=ids[0]), P(uuid=ids[1], execute="cat /etc/issue")]
    if change == "description":
        d2 = bit(name, same)[0].replace(DESC, b"Another description.")
    elif change == "rename":
        d2 = bit(f"{name} renamed", same)[0]
    else:
        d2 = bit(name, same, status="disabled")[0]
    assert sha(d2) != sha(d1)
    s0 = snap(server)
    out = rebuild(db, bits, server_file(d2, path))
    assert (out.outcome, out.policy_id, out.policy_version) == (
        "success", first.policy_id, 2,
    )  # fmt: skip
    assert out.plugins_added == 0 and out.plugins_updated == 0
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    # the same change in manual mode still alerts (control)
    d3 = d2.replace(b"</Policy>", b"<!-- x --></Policy>")
    s1 = snap(server)
    run(db, bits, server_file(d3, path))
    assert actions(server, s1) == ["policy.import"]


@pytest.mark.parametrize("corruption", ["retired", "edited"])
def test_r1_corrupted_catalog_then_rebuild_same_bytes_alerts_exactly_once(
    server: PgServer, db: AppDatabase, bits: Path, corruption: str
) -> None:
    hot = "cat /etc/shadow"
    data, ids = bit(plugins=[P(execute=hot), P(execute="cat /etc/hostname")])
    file = server_file(data)
    first = run(db, bits, file)
    pid = cast(int, first.policy_id)
    with owner(server) as c:
        if corruption == "retired":
            c.execute(
                "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s", (ids[0],)
            )
        else:
            c.execute(
                "UPDATE plugin SET execute = 'echo forged', execute_sha256 = %s"
                " WHERE plugin_uuid = %s",
                (sha(b"echo forged"), ids[0]),
            )
    s0 = snap(server)
    out = rebuild(db, bits, file)  # the same bytes: is_unchanged holds
    assert out.outcome == "success"
    entry = one(audits_since(server, s0))
    assert (entry["action"], entry["target"]) == ("policy.import", f"policy:{pid}")
    assert entry["detail"]["alert_kind"] == "policy_imported"
    assert entry["detail"]["mode"] == "rebuild"
    reason = "reactivated" if corruption == "retired" else "changed"
    assert entry["detail"]["changed_executes"] == [
        {
            "plugin_uuid": str(ids[0]),
            "plugin_name": "1.1 - Check 1",
            "execute": hot,
            "execute_sha256": sha(hot.encode()),
            "reason": reason,
            "flags": ["shadow"],
        }
    ]
    assert counter_delta(s0) == {"alert:policy_imported": 1.0}
    assert members(server, pid) == [
        (ids[0], hot, "active"), (ids[1], "cat /etc/hostname", "active"),
    ]  # fmt: skip


def test_r1_rebuild_listing_only_the_commands_that_go_live(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name, [P(), P()])
    path = f"n-{tag()}.bit"
    run(db, bits, server_file(d1, path))
    d2, ids2 = bit(
        name, [P(uuid=ids[0]), P(uuid=ids[1], execute="cat /etc/issue"), P()]
    )
    s0 = snap(server)
    rebuild(db, bits, server_file(d2, path))
    entry = one(audits_since(server, s0))
    got = [(c["plugin_uuid"], c["reason"]) for c in entry["detail"]["changed_executes"]]
    assert got == [(str(ids[1]), "changed"), (str(ids2[2]), "new")]
    # a new policy in rebuild mode: one alert with every command new
    d3, ids3 = bit(plugins=[P(), P()])
    s1 = snap(server)
    rebuild(db, bits, server_file(d3))
    e3 = one(audits_since(server, s1))
    assert [
        (c["plugin_uuid"], c["reason"]) for c in e3["detail"]["changed_executes"]
    ] == [(str(u), "new") for u in ids3]
    assert counter_delta(s1) == {"alert:policy_imported": 1.0}


def test_r1_rebuild_of_a_revived_policy_alerts_with_reactivated_commands(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    from bitscan_manager.services.importer import delete as dl

    data, ids = bit(plugins=[P(), P(execute="cat /etc/issue")])
    up = run(db, bits, upload_file(data))
    dl.delete_policy(
        db, cast(int, up.policy_id), actor="user:7", clock=FixedClock(), bits_dir=bits
    )
    s0 = snap(server)
    out = rebuild(db, bits, upload_file(data))
    assert (out.outcome, out.policy_id) == ("success", up.policy_id)
    entry = one(audits_since(server, s0))
    assert entry["detail"]["revived"] is True
    assert [
        (c["plugin_uuid"], c["reason"]) for c in entry["detail"]["changed_executes"]
    ] == [(str(u), "reactivated") for u in ids]


def test_r1_auto_and_manual_alert_as_before(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name)
    path = f"am-{tag()}.bit"
    s0 = snap(server)
    run(db, bits, server_file(d1, path), "auto", SYSTEM)
    assert actions(server, s0) == ["policy.import"]
    d2 = bit(name, [P(uuid=ids[0])])[0].replace(DESC, b"Other.")  # command same
    s1 = snap(server)
    assert run(db, bits, server_file(d2, path), "auto", SYSTEM).outcome == "success"
    e = one(audits_since(server, s1))
    assert e["action"] == "policy.import" and e["detail"]["changed_executes"] == []
    s2 = snap(server)
    run(db, bits, server_file(d2, path), "manual")
    e = one(audits_since(server, s2))
    assert e["action"] == "policy.import" and e["detail"]["changed_executes"] == []


def test_r1_rebuild_reenable_writes_only_its_status_entry(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name, status="disabled")
    path = f"re-{tag()}.bit"
    first = run(db, bits, server_file(d1, path))
    d2, _ = bit(name, [P(uuid=ids[0])], status="enabled")
    s0 = snap(server)
    rebuild(db, bits, server_file(d2, path))
    entry = one(audits_since(server, s0))
    assert (entry["action"], entry["target"]) == (
        "policy.status_change", f"policy:{first.policy_id}",
    )  # fmt: skip
    assert entry["detail"]["alert_kind"] == "policy_reenabled"
    assert counter_delta(s0) == {"alert:policy_reenabled": 1.0}


def test_r1_rebuild_move_writes_only_its_move_entry(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Pipeline {tag()}"
    d1, ids = bit(name)
    up = run(db, bits, upload_file(d1))
    pid = cast(int, up.policy_id)
    copy = bits / "uploaded" / f"policy-{pid}.bit"
    copy.write_bytes(d1)
    d2, _ = bit(name, [P(uuid=ids[0])])
    path = f"mv-{tag()}.bit"
    s0 = snap(server)
    out = rebuild(db, bits, server_file(d2, path))
    assert (out.outcome, out.policy_id) == ("success", pid)
    entry = one(audits_since(server, s0))
    assert entry["action"] == "policy.move"
    assert entry["detail"] == {"from": f"uploaded/policy-{pid}.bit", "to": path}
    assert counter_delta(s0) == {}
    assert not copy.exists()


def test_r1_rebuild_displaced_policy_still_writes_its_delete_alert(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    x_name, y_name = f"Pipeline X {tag()}", f"Pipeline Y {tag()}"
    path = f"ren-{tag()}.bit"
    x = run(db, bits, server_file(bit(x_name)[0], path))
    dy, y_ids = bit(y_name)
    y = run(db, bits, upload_file(dy))
    s0 = snap(server)
    out = rebuild(db, bits, server_file(bit(y_name, [P(uuid=y_ids[0])])[0], path))
    assert (out.outcome, out.policy_id) == ("success", y.policy_id)
    entries = audits_since(server, s0)
    assert [e["action"] for e in entries] == ["policy.move", "policy.delete"]
    assert entries[1]["target"] == f"policy:{x.policy_id}"
    assert entries[1]["detail"]["alert_kind"] == "policy_deleted"
    assert counter_delta(s0) == {"alert:policy_deleted": 1.0}
