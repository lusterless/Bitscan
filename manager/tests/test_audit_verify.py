"""REQ-031: the audit chain verifier (TP-M1-15).

Checks CHK-M1-220 to CHK-M1-224. The unit part builds chains with the
independent #38 reference (test_audit_chain.reference), so a verifier that
agrees with a wrong hash would fail. The pg part tampers as bitscan_owner and
deletes behind a checkpoint as bitscan_retention (#39).
"""

import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from bitscan_manager.repositories.audit_log import PgAuditRepo, iter_entries
from bitscan_manager.services.audit import AuditError, append_entry
from bitscan_manager.services.audit.verify import (
    StoredEntry,
    VerifyResult,
    verify_chain,
    verify_rows,
)

from .conftest import PgServer, run_cli, write_dsn_file
from .test_audit_chain import GENESIS, reference

AT = "2026-10-20T12:00:00.{:06d}Z"


def build(
    n: int,
    start_id: int = 1,
    prev: str = GENESIS,
    gaps: int = 1,
    extra: list[tuple[str, str | None]] | None = None,
) -> list[StoredEntry]:
    """n chained rows; ``extra`` gives (action, detail_text) for rows after them."""
    rows = []
    specs = [("t.write", json.dumps({"i": i})) for i in range(n)] + (extra or [])
    audit_id = start_id
    for i, (action, detail) in enumerate(specs):
        at = AT.format(i)
        h = reference(prev, audit_id, "alice", action, "tgt", detail, at)
        rows.append(StoredEntry(audit_id, "alice", action, "tgt", detail, at, prev, h))
        prev = h
        audit_id += gaps
    return rows


def checkpoint_detail(last_id: int, last_hash: str) -> str:
    return json.dumps({"last_deleted_id": last_id, "last_deleted_row_hash": last_hash})


def rehash(row: StoredEntry, **changes: Any) -> StoredEntry:
    """A row with changed fields and a correct row_hash for them (forger's view)."""
    r = replace(row, **changes)
    h = reference(
        r.prev_hash, r.audit_id, r.actor, r.action, r.target, r.detail_text, r.at_text
    )
    return replace(r, row_hash=h)


# --- intact and empty ---


def test_intact_chain_verifies_and_counts() -> None:
    res = verify_rows(build(10))
    assert (res.ok, res.checked, res.first_bad_id, res.reason) == (True, 10, None, None)


def test_empty_log_verifies() -> None:
    res = verify_rows([])
    assert (res.ok, res.checked, res.first_bad_id) == (True, 0, None)


def test_gaps_in_audit_id_are_fine() -> None:
    res = verify_rows(build(6, start_id=5, gaps=3))
    assert res.ok and res.checked == 6


# --- tampering ---


FIELDS = [
    "actor",
    "action",
    "target",
    "detail_text",
    "at_text",
    "audit_id",
    "prev_hash",
]


@pytest.mark.parametrize("field", FIELDS)
def test_changing_any_hashed_field_reports_that_row(field: str) -> None:
    rows = build(8)
    victim = rows[4]
    value = getattr(victim, field)
    new: Any = value + 1000 if isinstance(value, int) else (value or "") + "x"
    rows[4] = replace(victim, **{field: new})
    res = verify_rows(rows)
    assert not res.ok
    assert res.first_bad_id == (new if field == "audit_id" else victim.audit_id)


def test_changed_row_hash_reports_that_row() -> None:
    rows = build(5)
    rows[2] = replace(rows[2], row_hash="f" * 64)
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, rows[2].audit_id)


def test_rehashed_tampered_row_breaks_the_next_link() -> None:
    rows = build(6)
    rows[2] = rehash(rows[2], actor="mallory")  # its own hash is consistent
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, rows[3].audit_id)


def test_deleting_a_middle_row_reports_the_row_after_the_gap() -> None:
    rows = build(7)
    del rows[3]
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, rows[3].audit_id)


@pytest.mark.parametrize("prev", ["e" * 64, GENESIS])
def test_inserting_a_row_with_a_wrong_prev_hash_reports_it(prev: str) -> None:
    rows = build(5, gaps=2)  # ids 1, 3, 5, 7, 9
    forged = rehash(replace(rows[1], audit_id=4, actor="mallory", prev_hash=prev))
    rows.insert(2, forged)  # between 3 and 5, with a self-consistent row_hash
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, 4)


def test_inserting_a_correctly_linked_row_reports_the_next_row() -> None:
    rows = build(5, gaps=2)
    forged = rehash(replace(rows[1], audit_id=4, prev_hash=rows[1].row_hash))
    rows.insert(2, forged)
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, 5)


def test_first_row_must_link_to_genesis() -> None:
    rows = build(4, prev="c" * 64)
    res = verify_rows(rows)
    assert (res.ok, res.first_bad_id) == (False, rows[0].audit_id)


# --- checkpoints (#39) ---


def chain_with_checkpoint(delete_upto: int) -> tuple[list[StoredEntry], StoredEntry]:
    """10 rows, then a checkpoint recording row ``delete_upto`` (index)."""
    base = build(10)
    last = base[delete_upto]
    full = build(
        10,
        extra=[("audit.checkpoint", checkpoint_detail(last.audit_id, last.row_hash))],
    )
    return full, last


def test_checkpoint_lets_the_chain_start_after_deleted_rows() -> None:
    full, last = chain_with_checkpoint(3)
    remaining = [r for r in full if r.audit_id > last.audit_id]
    assert verify_rows(full).ok
    res = verify_rows(remaining)
    assert res.ok and res.checked == len(remaining)


def test_deleting_one_row_more_than_the_checkpoint_fails() -> None:
    full, last = chain_with_checkpoint(3)
    remaining = [r for r in full if r.audit_id > last.audit_id + 1]
    res = verify_rows(remaining)
    assert not res.ok and res.first_bad_id == remaining[0].audit_id


def test_changed_checkpoint_hash_fails() -> None:
    full, last = chain_with_checkpoint(3)
    remaining = [r for r in full if r.audit_id > last.audit_id]
    cp = remaining[-1]
    forged = checkpoint_detail(last.audit_id, "d" * 64)
    edited = replace(cp, detail_text=forged)  # edited in place, hash not redone
    res = verify_rows(remaining[:-1] + [edited])
    assert (res.ok, res.first_bad_id) == (False, cp.audit_id)  # the edited row
    rehashed = rehash(cp, detail_text=forged)  # a forger who also redoes the hash
    res = verify_rows(remaining[:-1] + [rehashed])
    assert (res.ok, res.first_bad_id) == (False, remaining[0].audit_id)


def test_checkpoint_id_not_lower_than_the_oldest_row_fails() -> None:
    base = build(10)
    oldest = base[4]
    cp_detail = checkpoint_detail(oldest.audit_id, oldest.prev_hash)  # id == oldest
    full = build(10, extra=[("audit.checkpoint", cp_detail)])
    remaining = [r for r in full if r.audit_id >= oldest.audit_id]
    res = verify_rows(remaining)
    assert (res.ok, res.first_bad_id) == (False, oldest.audit_id)
    # control: the same chain with the id one lower verifies
    good = checkpoint_detail(oldest.audit_id - 1, oldest.prev_hash)
    full = build(10, extra=[("audit.checkpoint", good)])
    assert verify_rows([r for r in full if r.audit_id >= oldest.audit_id]).ok


def test_checkpoint_recording_ids_after_itself_does_not_vouch() -> None:
    """A checkpoint cannot record rows written after it (id order forged)."""
    hole = "c" * 64
    at = AT.format(0)
    oldest_hash = reference(hole, 50, "alice", "t.write", "tgt", None, at)
    oldest = StoredEntry(50, "alice", "t.write", "tgt", None, at, hole, oldest_hash)

    def cp_row(cp_id: int, last_id: int) -> StoredEntry:
        detail = checkpoint_detail(last_id, hole)
        h = reference(oldest_hash, cp_id, "x", "audit.checkpoint", None, detail, at)
        return StoredEntry(
            cp_id, "x", "audit.checkpoint", None, detail, at, oldest_hash, h
        )

    # last_deleted_id 20 < oldest 50, but not below the checkpoint's own id 10
    res = verify_rows([oldest, cp_row(10, 20)])
    assert (res.ok, res.first_bad_id) == (False, 50)
    assert verify_rows([oldest, cp_row(60, 20)]).ok  # control: written after


@pytest.mark.parametrize(
    "detail",
    [
        None,
        "not json",
        "[1, 2]",
        '{"last_deleted_id": "4", "last_deleted_row_hash": "x"}',
        '{"last_deleted_id": 4.0, "last_deleted_row_hash": "x"}',
        '{"last_deleted_id": 4}',
        '{"last_deleted_row_hash": "x"}',
        '{"last_deleted_id": 4, "last_deleted_row_hash": 7}',
        '{"last_deleted_id": true, "last_deleted_row_hash": "x"}',
    ],
)
def test_malformed_checkpoint_does_not_vouch(detail: str | None) -> None:
    base = build(10)
    last = base[3]
    good = checkpoint_detail(last.audit_id, last.row_hash)
    row_hash = json.dumps(last.row_hash)
    bad_detail = None if detail is None else detail.replace('"x"', row_hash)
    full = build(10, extra=[("audit.checkpoint", bad_detail)])
    remaining = [r for r in full if r.audit_id > last.audit_id]
    assert not verify_rows(remaining).ok
    full_ok = build(10, extra=[("audit.checkpoint", good)])
    assert verify_rows([r for r in full_ok if r.audit_id > last.audit_id]).ok


def test_checkpoint_with_another_action_does_not_vouch() -> None:
    base = build(10)
    last = base[3]
    detail = checkpoint_detail(last.audit_id, last.row_hash)
    full = build(10, extra=[("audit.note", detail)])
    assert not verify_rows([r for r in full if r.audit_id > last.audit_id]).ok


def test_forged_checkpoint_cannot_make_a_mid_chain_row_the_oldest() -> None:
    """An attacker deletes rows from the middle and appends a checkpoint that
    names the row before the hole; the rows before the hole still exist, so the
    hole must still be reported."""
    full = build(10)
    hole_before = full[4]
    kept = full[:4] + full[6:]  # rows 5 and 6 deleted from the middle
    prev = kept[-1].row_hash
    forged_id = kept[-1].audit_id + 1
    detail = checkpoint_detail(full[5].audit_id, full[5].row_hash)
    at = AT.format(99)
    h = reference(prev, forged_id, "mallory", "audit.checkpoint", "tgt", detail, at)
    kept.append(
        StoredEntry(
            forged_id, "mallory", "audit.checkpoint", "tgt", detail, at, prev, h
        )
    )
    res = verify_rows(kept)
    assert not res.ok
    assert res.first_bad_id == full[6].audit_id
    assert hole_before.audit_id < res.first_bad_id


def test_forged_checkpoint_after_a_deleted_prefix_and_tail_tamper() -> None:
    """A tamper before the vouching checkpoint is reported where it is (REQ-031
    (2), (3)), not as the oldest row: the checkpoint is never reached."""
    full, last = chain_with_checkpoint(3)
    remaining = [r for r in full if r.audit_id > last.audit_id]
    assert verify_rows(remaining).ok  # control
    rehashed = list(remaining)
    rehashed[2] = rehash(remaining[2], actor="mallory")  # consistent own hash
    res = verify_rows(rehashed)
    assert (res.ok, res.first_bad_id) == (False, remaining[3].audit_id)
    edited = list(remaining)
    edited[2] = replace(remaining[2], actor="mallory")  # hash not redone
    res = verify_rows(edited)
    assert (res.ok, res.first_bad_id) == (False, remaining[2].audit_id)
    gap = remaining[:2] + remaining[3:]  # a row deleted before the checkpoint
    res = verify_rows(gap)
    assert (res.ok, res.first_bad_id) == (False, remaining[3].audit_id)


def test_reviewer_repro_tamper_in_a_checkpointed_chain_names_the_row() -> None:
    """Checkpoint for id 4, ids 1-4 deleted, actor of id 8 changed: report 8,
    not the oldest row 5 (reviewer should-fix on verify.py, rev 1)."""
    full, last = chain_with_checkpoint(3)
    assert last.audit_id == 4
    remaining = [r for r in full if r.audit_id > 4]
    i = next(n for n, r in enumerate(remaining) if r.audit_id == 8)
    remaining[i] = replace(remaining[i], actor="mallory")
    res = verify_rows(remaining)
    assert (res.ok, res.first_bad_id, res.reason) == (False, 8, "row_hash mismatch")


# --- PostgreSQL (TASK-021 step 2): verify_chain over the stored log ---
#
# REQ-031 (1) to (5) and #39 on a real database. Tampering is done as
# bitscan_owner (bitscan_migrate + SET ROLE), the checkpoint and its deletes as
# bitscan_retention. The verifier itself reads as bitscan_app.


@pytest.fixture
def db(fresh_pg_server: PgServer, tmp_path: Path) -> PgServer:
    dsn_file = write_dsn_file(tmp_path, "m", fresh_pg_server.dsn("bitscan_migrate"))
    proc = run_cli(["db", "migrate"], {"BITSCAN_MIGRATE_DSN_FILE": str(dsn_file)})
    assert proc.returncode == 0, proc.stderr
    return fresh_pg_server


def _append_n(server: PgServer, n: int, role: str = "bitscan_app") -> None:
    with psycopg.connect(server.dsn(role), autocommit=False) as conn:
        for i in range(n):
            append_entry(
                PgAuditRepo(conn), actor="alice", action="t.write", detail={"i": i}
            )
            conn.commit()


def _ids(server: PgServer) -> list[tuple[int, str]]:
    with server.connect("bitscan_migrate") as c:
        rows = c.execute(
            "SELECT audit_id, row_hash FROM audit_log ORDER BY audit_id"
        ).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def _owner_exec(server: PgServer, stmt: str, params: tuple[Any, ...] = ()) -> None:
    with server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        c.execute(stmt, params)


def _verify(server: PgServer) -> VerifyResult:
    with server.connect("bitscan_app") as conn:
        res = verify_chain(conn)
        assert conn.info.transaction_status == TransactionStatus.IDLE
    return res


@pytest.fixture
def chain6(db: PgServer) -> PgServer:
    _append_n(db, 6)
    return db


@pytest.mark.pg
def test_pg_intact_and_empty_chains_verify(db: PgServer) -> None:
    res = _verify(db)
    assert (res.ok, res.checked) == (True, 0)
    _append_n(db, 5)
    res = _verify(db)
    assert (res.ok, res.checked, res.first_bad_id) == (True, 5, None)


TAMPER = [
    ("actor", "UPDATE audit_log SET actor = 'mallory' WHERE audit_id = %s"),
    ("action", "UPDATE audit_log SET action = 'x.y' WHERE audit_id = %s"),
    ("target", "UPDATE audit_log SET target = 't' WHERE audit_id = %s"),
    ("detail", "UPDATE audit_log SET detail = '{\"i\": 99}' WHERE audit_id = %s"),
    (
        "at",
        "UPDATE audit_log SET at = at + interval '1 microsecond' WHERE audit_id = %s",
    ),
    (
        "prev_hash",
        "UPDATE audit_log SET prev_hash = repeat('e', 64) WHERE audit_id = %s",
    ),
    (
        "row_hash",
        "UPDATE audit_log SET row_hash = repeat('f', 64) WHERE audit_id = %s",
    ),
]


@pytest.mark.pg
@pytest.mark.parametrize(("field", "stmt"), TAMPER, ids=[t[0] for t in TAMPER])
def test_pg_changing_a_hashed_field_reports_that_entry(
    chain6: PgServer, field: str, stmt: str
) -> None:
    victim = _ids(chain6)[3][0]
    _owner_exec(chain6, stmt, (victim,))
    res = _verify(chain6)
    assert (res.ok, res.first_bad_id) == (False, victim), field


@pytest.mark.pg
def test_pg_deleted_middle_entry_reports_the_entry_after_the_gap(
    chain6: PgServer,
) -> None:
    ids = [i for i, _ in _ids(chain6)]
    _owner_exec(chain6, "DELETE FROM audit_log WHERE audit_id = %s", (ids[2],))
    res = _verify(chain6)
    assert (res.ok, res.first_bad_id, res.reason) == (False, ids[3], "broken link")


@pytest.mark.pg
def test_pg_inserted_entry_with_a_wrong_prev_hash_reports_it(chain6: PgServer) -> None:
    at = "2026-10-20T00:00:00.000000Z"
    prev = "e" * 64
    with chain6.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        row = c.execute("SELECT nextval('audit_log_audit_id_seq')").fetchone()
        assert row is not None
        new_id = int(row[0])
        h = reference(prev, new_id, "mallory", "x", None, None, at)
        c.execute(
            "INSERT INTO audit_log (audit_id, actor, action, target, detail, at,"
            " prev_hash, row_hash) VALUES (%s, 'mallory', 'x', NULL, NULL,"
            " CAST(%s AS timestamptz), %s, %s)",
            (new_id, at, prev, h),
        )
    res = _verify(chain6)
    assert (res.ok, res.first_bad_id, res.reason) == (False, new_id, "broken link")


@pytest.mark.pg
def test_pg_rolled_back_appends_leave_gaps_that_verify(db: PgServer) -> None:
    with psycopg.connect(db.dsn("bitscan_app"), autocommit=False) as conn:
        for i in range(4):
            append_entry(PgAuditRepo(conn), actor="a", action="x", detail={"i": i})
            if i % 2:
                conn.rollback()
            else:
                conn.commit()
    ids = [i for i, _ in _ids(db)]
    assert len(ids) == 2 and ids[1] - ids[0] == 2
    res = _verify(db)
    assert (res.ok, res.checked) == (True, 2)


def _checkpoint_and_delete(server: PgServer, upto: int) -> list[tuple[int, str]]:
    """As bitscan_retention: an audit.checkpoint entry for row ``upto`` (index),
    then delete every entry up to it (#39, TS §5.3)."""
    last_id, last_hash = _ids(server)[upto]
    with psycopg.connect(server.dsn("bitscan_retention"), autocommit=False) as conn:
        append_entry(
            PgAuditRepo(conn),
            actor="system",
            action="audit.checkpoint",
            detail={"last_deleted_id": last_id, "last_deleted_row_hash": last_hash},
        )
        conn.commit()
        conn.execute("DELETE FROM audit_log WHERE audit_id <= %s", (last_id,))
        conn.commit()
    return _ids(server)


@pytest.mark.pg
def test_pg_checkpoint_then_retention_delete_still_verifies(chain6: PgServer) -> None:
    left = _checkpoint_and_delete(chain6, 3)
    assert len(left) == 3  # entries 5, 6 and the checkpoint
    res = _verify(chain6)
    assert (res.ok, res.checked) == (True, 3)
    _append_n(chain6, 2)  # the chain keeps growing after the checkpoint
    res = _verify(chain6)
    assert (res.ok, res.checked) == (True, 5)


@pytest.mark.pg
def test_pg_deleting_one_more_entry_than_the_checkpoint_fails(
    chain6: PgServer,
) -> None:
    left = _checkpoint_and_delete(chain6, 3)
    with chain6.connect("bitscan_retention") as c:
        c.execute("DELETE FROM audit_log WHERE audit_id = %s", (left[0][0],))
    res = _verify(chain6)
    assert (res.ok, res.first_bad_id) == (False, left[1][0])


@pytest.mark.pg
def test_pg_changed_checkpoint_hash_fails(chain6: PgServer) -> None:
    left = _checkpoint_and_delete(chain6, 3)
    cp_id = left[-1][0]
    _owner_exec(
        chain6,
        "UPDATE audit_log SET detail = jsonb_set(detail, '{last_deleted_row_hash}',"
        " to_jsonb(repeat('d', 64))) WHERE audit_id = %s",
        (cp_id,),
    )
    res = _verify(chain6)
    assert (res.ok, res.first_bad_id, res.reason) == (
        False,
        cp_id,
        "row_hash mismatch",
    )


@pytest.mark.pg
def test_pg_verifier_reads_one_snapshot(chain6: PgServer) -> None:
    """CHK-M1-224: entries committed mid-walk are not seen; no false failure."""
    before = [i for i, _ in _ids(chain6)]
    with chain6.connect("bitscan_app") as conn:
        with closing(iter_entries(conn)) as rows:
            first = next(rows)
            # the plan's contract: one REPEATABLE READ, READ ONLY transaction
            # (a single cursor statement is one snapshot even in READ COMMITTED,
            # so the behaviour below alone cannot tell the two apart)
            iso = conn.execute("SHOW transaction_isolation").fetchone()
            ro = conn.execute("SHOW transaction_read_only").fetchone()
            assert (iso, ro) == (("repeatable read",), ("on",))
            _append_n(chain6, 3)  # another connection, committed
            rest = list(rows)
        assert [first[0], *[r[0] for r in rest]] == before
        assert conn.info.transaction_status == TransactionStatus.IDLE
    res = _verify(chain6)
    assert (res.ok, res.checked) == (True, 9)


@pytest.mark.pg
def test_pg_verify_needs_a_connection_without_an_open_transaction(
    chain6: PgServer,
) -> None:
    with psycopg.connect(chain6.dsn("bitscan_app"), autocommit=False) as conn:
        conn.execute("SELECT 1")  # opens a transaction
        with pytest.raises(AuditError):
            verify_chain(conn)
        conn.rollback()
        assert verify_chain(conn).ok
        assert conn.info.transaction_status == TransactionStatus.IDLE


@pytest.mark.pg
def test_pg_early_failure_leaves_the_connection_idle(chain6: PgServer) -> None:
    first = _ids(chain6)[0][0]
    _owner_exec(
        chain6, "UPDATE audit_log SET actor = 'm' WHERE audit_id = %s", (first,)
    )
    with chain6.connect("bitscan_app") as conn:
        res = verify_chain(conn)
        assert (res.ok, res.first_bad_id, res.checked) == (False, first, 1)
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert conn.execute("SELECT 1").fetchone() == (1,)
