"""TP-M7-10 (TASK-149): bit_import and task repository, as bitscan_app.

CHK-M7-160 to -163 (tests/m7/test-plan.md). Expected values: SR §3.5, §3.6
("then, in its own transaction, insert the bit_import row"); TS §4.1 L520,
§4.2 L540, §5.2 (bit_import, task DDL and grants L1005); #98 (g), (h), #110.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import imports as rep
from bitscan_manager.repositories.imports import ImportRecord

from .catalog_rows import T0, T1, T2, Conn, app, sha, tag
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("imprepo")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[Conn]:
    with app(server) as c, c.transaction(force_rollback=True):
        yield c


ERRORS: list[dict[str, Any]] = [
    {
        "line": 3,
        "element": "Policy/PolicyStatus",
        "code": "BIT003",
        "message": 'x "on"',
    },
    {
        "line": 14,
        "element": "Policy/PluginsGroups/Plugin[1]/PluginName",
        "code": "BIT101",
        "message": "w",
    },
    {"line": None, "element": None, "code": "BIT001", "message": "é \\ ‮\t\n"},
]


def record(**kw: Any) -> ImportRecord:
    base: dict[str, Any] = {
        "file_name": f"{tag()}.bit",
        "file_sha256": sha(tag()),
        "mode": "manual",
        "outcome": "rejected",
    }
    base.update(kw)
    return ImportRecord(**base)


def row_by_id(conn: Conn, import_id: int) -> tuple[Any, ...]:
    r = conn.execute(
        "SELECT file_name, file_sha256, policy_version, mode, outcome, plugins_added,"
        " plugins_updated, plugins_retired, errors, imported_by, imported_at"
        " FROM bit_import WHERE import_id = %s",
        (import_id,),
    ).fetchone()
    assert r is not None
    return tuple(r)


# CHK-M7-160 ---------------------------------------------------------------------


def test_insert_import_writes_every_column(conn: Conn) -> None:
    rec = record(
        mode="auto",
        outcome="success",
        policy_version=7,
        plugins_added=1,
        plugins_updated=2,
        plugins_retired=3,
        errors=ERRORS[1:2],
        imported_by=42,
    )
    iid = rep.insert_import(conn, rec, T0)
    assert row_by_id(conn, iid) == (
        rec.file_name,
        rec.file_sha256,
        7,
        "auto",
        "success",
        1,
        2,
        3,
        ERRORS[1:2],
        42,
        T0,
    )


def test_defaults_rejected_without_version_or_user(conn: Conn) -> None:
    iid = rep.insert_import(conn, record(errors=ERRORS), T1)
    got = row_by_id(conn, iid)
    assert got[2] is None and got[5:8] == (0, 0, 0) and got[9] is None
    assert got[8] == ERRORS  # every finding, warnings included, order kept


def test_empty_errors_store_an_empty_list(conn: Conn) -> None:
    iid = rep.insert_import(conn, record(outcome="skipped", mode="auto"), T0)
    assert row_by_id(conn, iid)[8] == []


@pytest.mark.parametrize(
    ("mode", "outcome"),
    [("auto", "x"), ("watch", "success"), ("MANUAL", "success"), ("manual", "Success")],
)
def test_check_constraints_refuse_unknown_mode_or_outcome(
    conn: Conn, mode: str, outcome: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        rep.insert_import(conn, record(mode=mode, outcome=outcome), T0)


def test_insert_survives_a_sibling_rollback_on_another_connection(
    server: PgServer,
) -> None:
    name = f"own-tx-{tag()}.bit"
    with app(server) as catalog, app(server) as rec:
        catalog.execute("BEGIN")
        catalog.execute("INSERT INTO family (family_name) VALUES (%s)", (name,))
        with rec.transaction():
            iid = rep.insert_import(rec, record(file_name=name), T0)
        catalog.execute("ROLLBACK")
    with app(server) as check:
        assert row_by_id(check, iid)[0] == name
        assert check.execute(
            "SELECT count(*) FROM family WHERE family_name = %s", (name,)
        ).fetchone() == (0,)


def test_insert_in_its_own_transaction_on_a_pinned_connection(server: PgServer) -> None:
    # D4: tx1 (catalog) rolls back, then tx2 (record) on the same connection.
    name = f"pinned-{tag()}.bit"
    with app(server) as c:
        with pytest.raises(RuntimeError), c.transaction():
            c.execute("INSERT INTO family (family_name) VALUES (%s)", (name,))
            raise RuntimeError("catalog failure")
        with c.transaction():
            iid = rep.insert_import(c, record(file_name=name), T0)
    with app(server) as check:
        assert row_by_id(check, iid)[0] == name
        assert check.execute(
            "SELECT count(*) FROM family WHERE family_name = %s", (name,)
        ).fetchone() == (0,)


def test_insert_does_not_commit_the_callers_transaction(server: PgServer) -> None:
    name = f"nocommit-{tag()}.bit"
    with app(server) as c:
        with pytest.raises(RuntimeError), c.transaction():
            rep.insert_import(c, record(file_name=name), T0)
            raise RuntimeError("caller rolls back")
        assert c.execute(
            "SELECT count(*) FROM bit_import WHERE file_name = %s", (name,)
        ).fetchone() == (0,)


# CHK-M7-161 ---------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_newest_first_pages_each_row_once(server: PgServer, n: int) -> None:
    # Walk the whole table as the route will (limit + 1 per page).
    with app(server) as c, c.transaction(force_rollback=True):
        ids = [rep.insert_import(c, record(), T0) for _ in range(n + 1)]
        total = c.execute("SELECT count(*) FROM bit_import").fetchone()
        assert total is not None
        seen: list[int] = []
        before: int | None = None
        for _ in range(int(total[0]) + 2):  # bounded: a stuck cursor fails
            page = rep.imports_newest_first(c, n + 1, before)
            assert len(page) <= n + 1
            seen += [r.import_id for r in page[:n]]
            if len(page) <= n:
                break
            nxt = page[n - 1].import_id
            assert before is None or nxt < before, "cursor did not move"
            before = nxt
        else:
            pytest.fail("paging never ended")
        assert len(seen) == total[0]
        assert len(set(seen)) == len(seen)
        assert seen == sorted(seen, reverse=True)
        assert [i for i in seen if i in ids] == sorted(ids, reverse=True)


def test_first_page_is_newest_and_keyset_is_strict(conn: Conn) -> None:
    a = rep.insert_import(conn, record(), T0)
    b = rep.insert_import(conn, record(), T1)
    c = rep.insert_import(conn, record(), T2)
    first = rep.imports_newest_first(conn, 2, None)
    assert [r.import_id for r in first] == [c, b]
    assert [r.import_id for r in rep.imports_newest_first(conn, 2, b)][:1] == [a]
    assert all(r.import_id < b for r in rep.imports_newest_first(conn, 500, b))
    assert rep.imports_newest_first(conn, 5, 1) == []


def test_page_rows_carry_every_column_as_stored(conn: Conn) -> None:
    rec = record(
        file_name="<script>x</script>‮.bit",
        errors=ERRORS,
        outcome="success",
        policy_version=2,
        plugins_added=4,
        imported_by=9,
    )
    iid = rep.insert_import(conn, rec, T1)
    (row,) = rep.imports_newest_first(conn, 1, iid + 1)
    assert row == rep.ImportRow(
        iid,
        rec.file_name,
        rec.file_sha256,
        2,
        "manual",
        "success",
        4,
        0,
        0,
        ERRORS,
        9,
        T1,
    )


# CHK-M7-162 ---------------------------------------------------------------------


def test_task_insert_get_finish(conn: Conn) -> None:
    tid = rep.insert_task(conn, 5, T0)
    assert isinstance(tid, UUID)
    assert rep.get_task(conn, tid) == rep.TaskRow(
        tid, "rebuild", "running", 5, None, T0, None
    )
    cli = rep.insert_task(conn, None, T0)
    assert rep.get_task(conn, cli) == rep.TaskRow(
        cli, "rebuild", "running", None, None, T0, None
    )
    result = {
        "files": [{"source_file": "a.bit", "outcome": "success"}],
        "plugins_retired": 0,
    }
    assert rep.finish_task(conn, tid, "succeeded", result, T1) is True
    assert rep.get_task(conn, tid) == rep.TaskRow(
        tid, "rebuild", "succeeded", 5, result, T0, T1
    )
    # once only: a finished task is not finished again (checklist 8)
    assert rep.finish_task(conn, tid, "failed", {"error": "x"}, T2) is False
    assert rep.get_task(conn, tid) == rep.TaskRow(
        tid, "rebuild", "succeeded", 5, result, T0, T1
    )
    assert rep.get_task(conn, uuid4()) is None
    assert rep.finish_task(conn, uuid4(), "failed", {}, T1) is False


def test_fail_running_tasks_changes_only_running_rows(conn: Conn) -> None:
    rep.fail_running_tasks(conn, {"error": "baseline"}, T0)
    r1, r2 = rep.insert_task(conn, None, T0), rep.insert_task(conn, 1, T0)
    done = rep.insert_task(conn, 1, T0)
    failed = rep.insert_task(conn, 1, T0)
    rep.finish_task(conn, done, "succeeded", {"files": []}, T1)
    rep.finish_task(conn, failed, "failed", {"error": "earlier"}, T1)
    msg = {"error": "manager restarted during the rebuild"}
    got = rep.fail_running_tasks(conn, msg, T2)
    assert got == sorted([r1, r2])
    for t in (r1, r2):
        row = rep.get_task(conn, t)
        assert row is not None
        assert (row.state, row.result, row.finished_at) == ("failed", msg, T2)
    assert rep.get_task(conn, done) == rep.TaskRow(
        done, "rebuild", "succeeded", 1, {"files": []}, T0, T1
    )
    assert rep.get_task(conn, failed) == rep.TaskRow(
        failed, "rebuild", "failed", 1, {"error": "earlier"}, T0, T1
    )
    assert rep.finish_task(conn, r1, "succeeded", {"files": []}, T2) is False
    assert rep.fail_running_tasks(conn, msg, T2) == []


def test_concurrent_finish_and_fail_change_the_row_once(server: PgServer) -> None:
    with app(server) as setup, setup.transaction():
        tid = rep.insert_task(setup, None, T0)
    with app(server) as a, app(server) as b:
        a.execute("BEGIN")
        assert rep.finish_task(a, tid, "succeeded", {"files": []}, T1)
        import threading

        out: dict[str, list[UUID]] = {}

        def fail() -> None:
            with b.transaction():
                out["b"] = rep.fail_running_tasks(b, {"error": "x"}, T2)

        t = threading.Thread(target=fail)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "the UPDATE did not wait for the row lock"
        a.execute("COMMIT")
        t.join(10)
    assert tid not in out["b"]
    with app(server) as check:
        row = rep.get_task(check, tid)
        assert row is not None and row.state == "succeeded"


# CHK-M7-163 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    ["UPDATE bit_import SET outcome = 'success'", "DELETE FROM bit_import"],
)
def test_app_cannot_update_or_delete_bit_import(conn: Conn, statement: str) -> None:
    rep.insert_import(conn, record(), T0)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute(statement.encode())


def test_app_cannot_delete_tasks(conn: Conn) -> None:
    rep.insert_task(conn, None, T0)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("DELETE FROM task")
