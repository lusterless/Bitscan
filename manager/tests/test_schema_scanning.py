"""REQ-023: schema part 3, scanning (TP-M1-08).

Checks CHK-M1-090 to CHK-M1-095. Written from TS §5.2 L842-L938 before reading
the migration. Behaviour cases run as bitscan_owner in a transaction that is
always rolled back, with a savepoint per statement. Cases that write straight
into ``scan_result_default`` use a job dated 2000-01-01, outside any monthly
partition that m0005 adds, so they stay valid after m0005.
"""

import secrets
import uuid
from collections.abc import Iterator
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from .conftest import REFERENCE_DB, Conn, PgServer
from .schema_diff import Scope, diff, dump

SCANNING = Scope.of(
    tables=(
        "scan_schedule",
        "scan",
        "scan_job",
        "scan_result",
        "scan_result_default",
        "scan_result_reeval",
    ),
    types=("scan_state", "check_result"),
    functions=("scan_result_check_job",),
)
TRIGGER_MESSAGE = "scan_result.job_created_at must equal scan_job.created_at"
STATES = [
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "expired",
]
SNAPS = ("plugin_name_snap", "execute_snap", "operator_snap", "expected_snap")
OLD = "2000-01-01T00:00:00+00"


@pytest.fixture
def sc(migrated_db: PgServer, owner_conn: Conn) -> Iterator[Conn]:
    with owner_conn.transaction(force_rollback=True):
        yield owner_conn


def one(conn: Conn, query: LiteralString, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def insert(conn: Conn, table: str, values: dict[str, Any], returning: str = "") -> Any:
    q = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    if returning:
        q = q + sql.SQL(" RETURNING {}").format(sql.Identifier(returning))
        row = conn.execute(q, list(values.values())).fetchone()
        assert row is not None
        return row[0]
    conn.execute(q, list(values.values()))
    return None


def insert_state(conn: Conn, table: str, values: dict[str, Any]) -> str | None:
    try:
        with conn.transaction():
            insert(conn, table, values)
    except psycopg.Error as exc:
        return exc.sqlstate
    return None


@pytest.fixture
def world(sc: Conn) -> dict[str, Any]:
    """A family, policy, plugin and agent to hang scans and jobs on."""
    fam = insert(sc, "family", {"family_name": "F"}, "family_id")
    pol = insert(
        sc,
        "policy",
        {
            "policy_name": "p",
            "policy_status": "enabled",
            "file_status": "enabled",
            "family_id": fam,
            "source_file": "p.bit",
            "source_sha256": "a" * 64,
        },
        "policy_id",
    )
    plug = insert(
        sc,
        "plugin",
        {
            "plugin_uuid": uuid.uuid4(),
            "family_id": fam,
            "owner_policy_id": pol,
            "plugin_name": "1.1 - x",
            "execute": "true",
            "execute_sha256": "b" * 64,
            "operator": "equals",
        },
        "plugin_uuid",
    )
    agent = insert(
        sc,
        "agent",
        {
            "machine_id": secrets.token_hex(16),
            "hostname": "h",
            "agent_version": "v",
            "token_hash": secrets.token_hex(32),
            "token_issued_at": "now",
            "token_expires_at": "2099-01-01",
        },
        "agent_id",
    )
    return {"conn": sc, "policy": pol, "plugin": plug, "agent": agent}


def new_scan(w: dict[str, Any], **cols: Any) -> uuid.UUID:
    values = {
        "policy_id": w["policy"],
        "policy_version": 1,
        "trigger": "manual",
        "target": Jsonb({"all": True}),
    } | cols
    return uuid.UUID(str(insert(w["conn"], "scan", values, "scan_id")))


def new_job(w: dict[str, Any], scan_id: uuid.UUID | None, **cols: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "kind": "compliance" if scan_id else "inventory",
        "scan_id": scan_id,
        "agent_id": w["agent"],
        "payload": Jsonb({}),
        "eval_spec": Jsonb([]) if scan_id else None,
        "pickup_by": "2099-01-01",
    } | cols
    return uuid.UUID(str(insert(w["conn"], "scan_job", values, "job_id")))


def result_row(
    w: dict[str, Any], job: uuid.UUID, created: Any, **cols: Any
) -> dict[str, Any]:
    return {
        "job_id": job,
        "job_created_at": created,
        "plugin_uuid": w["plugin"],
        "eval_code": 0,
        "plugin_name_snap": "F - 1.1 - x",
        "execute_snap": "true",
        "operator_snap": "equals",
        "expected_snap": "",
        "started_at": "now",
        "finished_at": "now",
    } | cols


def job_created(conn: Conn, job: uuid.UUID) -> Any:
    return one(conn, "SELECT created_at FROM scan_job WHERE job_id = %s", (job,))


# --- diff -------------------------------------------------------------------------


@pytest.mark.pg
def test_scanning_objects_are_diff_equal_to_the_spec(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with (
        migrated_db.connect("bitscan_migrate") as got,
        reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref,
    ):
        problems = diff(dump(ref, SCANNING), dump(got, SCANNING))
    assert problems == [], "\n".join(problems)


# --- types and defaults ------------------------------------------------------------


@pytest.mark.pg
def test_labels_and_defaults(world: dict[str, Any]) -> None:
    c = world["conn"]
    assert one(c, "SELECT enum_range(NULL::scan_state)::text[]") == STATES
    assert one(c, "SELECT enum_range(NULL::check_result)::text[]") == [
        "PASS",
        "FAIL",
        "ERROR",
    ]
    sched = insert(
        c,
        "scan_schedule",
        {
            "name": "n",
            "policy_id": world["policy"],
            "target": Jsonb({"all": True}),
            "cron": "0 3 * * *",
            "created_by": 1,
        },
        "schedule_id",
    )
    row = c.execute(
        "SELECT timezone, enabled, last_run_at FROM scan_schedule"
        " WHERE schedule_id = %s",
        (sched,),
    ).fetchone()
    assert row == ("UTC", True, None)
    s = new_scan(world)
    assert one(c, "SELECT state::text FROM scan WHERE scan_id = %s", (s,)) == "queued"
    j = new_job(world, s)
    assert (
        one(c, "SELECT state::text FROM scan_job WHERE job_id = %s", (j,)) == "queued"
    )


# --- scan_job CHECKs and the pending index ------------------------------------------


@pytest.mark.pg
def test_scan_job_checks(world: dict[str, Any]) -> None:
    c = world["conn"]
    s = new_scan(world)
    base: dict[str, Any] = {
        "agent_id": world["agent"],
        "payload": Jsonb({}),
        "pickup_by": "2099-01-01",
    }
    cases: list[tuple[dict[str, Any], str | None]] = [
        ({"kind": "compliance", "scan_id": None, "eval_spec": Jsonb([])}, "23514"),
        ({"kind": "inventory", "scan_id": s}, "23514"),
        ({"kind": "compliance", "scan_id": s, "eval_spec": None}, "23514"),
        ({"kind": "patch", "scan_id": None}, "23514"),
        ({"kind": "inventory", "scan_id": None, "eval_spec": None}, None),
        ({"kind": "compliance", "scan_id": s, "eval_spec": Jsonb([])}, None),
        ({"kind": "inventory", "scan_id": None, "pickup_by": None}, "23502"),
        ({"kind": "inventory", "scan_id": None, "payload": None}, "23502"),
        ({"kind": "inventory", "scan_id": None, "agent_id": None}, "23502"),
    ]
    for cols, expected in cases:
        assert insert_state(c, "scan_job", base | cols) == expected, cols
    other = uuid.uuid4()
    assert (
        insert_state(c, "scan_job", base | {"kind": "inventory", "retry_of": other})
        == "23503"
    )
    first = new_job(world, None)
    assert (
        insert_state(c, "scan_job", base | {"kind": "inventory", "retry_of": first})
        is None
    )
    pending = one(
        c, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_job_pending'"
    )
    assert pending.endswith(
        "USING btree (agent_id) WHERE (state = 'queued'::scan_state)"
    )


# --- partitioning --------------------------------------------------------------------


@pytest.mark.pg
def test_scan_result_is_range_partitioned_with_a_default(sc: Conn) -> None:
    assert one(sc, "SELECT pg_get_partkeydef('scan_result'::regclass)") == (
        "RANGE (job_created_at)"
    )
    row = sc.execute(
        "SELECT p.relname, pg_get_expr(c.relpartbound, c.oid)"
        " FROM pg_class c JOIN pg_inherits i ON i.inhrelid = c.oid"
        " JOIN pg_class p ON p.oid = i.inhparent"
        " WHERE c.relname = 'scan_result_default'"
    ).fetchone()
    assert row == ("scan_result", "DEFAULT")


@pytest.mark.pg
def test_default_partition_is_empty_after_migrate(sc: Conn) -> None:
    assert one(sc, "SELECT count(*) FROM scan_result_default") == 0


# --- the job_created_at trigger ----------------------------------------------------


@pytest.mark.pg
def test_trigger_rejects_a_mismatched_job_created_at(world: dict[str, Any]) -> None:
    c = world["conn"]
    job = new_job(world, new_scan(world), created_at=OLD)
    created = job_created(c, job)
    wrong = "2000-01-02T00:00:00+00"
    for table in ("scan_result", "scan_result_default"):
        with pytest.raises(psycopg.errors.RaiseException) as err:
            with c.transaction():
                insert(c, table, result_row(world, job, wrong))
        assert err.value.diag.message_primary == TRIGGER_MESSAGE, table
    with pytest.raises(psycopg.errors.RaiseException):
        with c.transaction():
            insert(c, "scan_result", result_row(world, uuid.uuid4(), created))
    insert(c, "scan_result_default", result_row(world, job, created))
    where = one(
        c, "SELECT tableoid::regclass::text FROM scan_result WHERE job_id = %s", (job,)
    )
    assert where == "scan_result_default"


@pytest.mark.pg
def test_trigger_accepts_a_matching_row_through_the_parent(
    world: dict[str, Any],
) -> None:
    c = world["conn"]
    job = new_job(world, new_scan(world))
    insert(c, "scan_result", result_row(world, job, job_created(c, job)))
    assert one(c, "SELECT count(*) FROM scan_result WHERE job_id = %s", (job,)) == 1


# --- eval_code, generated result, snapshots ----------------------------------------


@pytest.mark.pg
def test_eval_code_and_generated_result(world: dict[str, Any]) -> None:
    c = world["conn"]
    job = new_job(world, new_scan(world))
    created = job_created(c, job)
    plugins = [world["plugin"]]
    for _ in range(2):
        plugins.append(
            insert(
                c,
                "plugin",
                {
                    "plugin_uuid": uuid.uuid4(),
                    "family_id": one(c, "SELECT min(family_id) FROM family"),
                    "owner_policy_id": world["policy"],
                    "plugin_name": "x",
                    "execute": "true",
                    "execute_sha256": "c" * 64,
                    "operator": "equals",
                },
                "plugin_uuid",
            )
        )
    for code, plug in zip((0, 1, 2), plugins, strict=True):
        insert(
            c,
            "scan_result",
            result_row(world, job, created, eval_code=code, plugin_uuid=plug),
        )
    got = c.execute(
        "SELECT eval_code, result::text FROM scan_result WHERE job_id = %s"
        " ORDER BY eval_code",
        (job,),
    ).fetchall()
    assert got == [(0, "PASS"), (1, "FAIL"), (2, "ERROR")]
    job2 = new_job(world, new_scan(world))
    c2 = job_created(c, job2)
    assert (
        insert_state(c, "scan_result", result_row(world, job2, c2, eval_code=3))
        == "23514"
    )
    assert (
        insert_state(c, "scan_result", result_row(world, job2, c2, eval_code=-1))
        == "23514"
    )
    assert (
        insert_state(c, "scan_result", result_row(world, job2, c2, result="PASS"))
        == "428C9"
    )
    for snap in SNAPS:
        assert insert_state(
            c, "scan_result", result_row(world, job2, c2, **{snap: None})
        ) == ("23502"), snap
    row = c.execute(
        "SELECT timed_out, truncated, received_at IS NOT NULL"
        " FROM scan_result WHERE job_id = %s",
        (job,),
    ).fetchone()
    assert row == (False, False, True)


# --- scan trigger values, schedule and scan deletes, reeval -------------------------


@pytest.mark.pg
def test_scan_trigger_and_delete_behaviour(world: dict[str, Any]) -> None:
    c = world["conn"]
    for trig, expected in (
        ("manual", None),
        ("scheduled", None),
        ("api", "23514"),
        ("Manual", "23514"),
    ):
        assert (
            insert_state(
                c,
                "scan",
                {
                    "policy_id": world["policy"],
                    "policy_version": 1,
                    "trigger": trig,
                    "target": Jsonb({}),
                },
            )
            == expected
        ), trig
    sched = insert(
        c,
        "scan_schedule",
        {
            "name": "n",
            "policy_id": world["policy"],
            "target": Jsonb({"all": True}),
            "cron": "0 3 * * *",
            "created_by": 1,
        },
        "schedule_id",
    )
    s = new_scan(world, trigger="scheduled", schedule_id=sched)
    c.execute("DELETE FROM scan_schedule WHERE schedule_id = %s", (sched,))
    assert one(c, "SELECT schedule_id FROM scan WHERE scan_id = %s", (s,)) is None

    job = new_job(world, s)
    insert(c, "scan_result", result_row(world, job, job_created(c, job)))
    insert(
        c,
        "scan_result_reeval",
        {
            "job_id": job,
            "plugin_uuid": world["plugin"],
            "policy_version": 1,
            "eval_code": 1,
            "reevaluated_by": 1,
        },
    )
    c.execute("DELETE FROM scan WHERE scan_id = %s", (s,))
    for table in ("scan_job", "scan_result", "scan_result_reeval"):
        n = c.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE job_id = %s").format(
                sql.Identifier(table)
            ),
            (job,),
        ).fetchone()
        assert n == (0,), table


@pytest.mark.pg
def test_reeval_eval_code_check(world: dict[str, Any]) -> None:
    c = world["conn"]
    job = new_job(world, new_scan(world))
    base = {
        "job_id": job,
        "plugin_uuid": world["plugin"],
        "policy_version": 1,
        "reevaluated_by": 1,
    }
    for code, expected in ((0, None), (2, None), (3, "23514"), (-1, "23514")):
        assert (
            insert_state(c, "scan_result_reeval", base | {"eval_code": code})
            == expected
        )
    assert (
        insert_state(
            c, "scan_result_reeval", base | {"eval_code": 0, "reevaluated_by": None}
        )
        == "23502"
    )
