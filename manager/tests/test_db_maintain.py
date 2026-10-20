"""REQ-028: ``bitscan-manager db maintain`` (TP-M1-13), plus CHK-M1-177.

Checks CHK-M1-170 to CHK-M1-179. Written from TS §5.3 L1047, REQ-028, decisions
#43 (UTC months, ``scan_result_YYYY_MM``, found by bounds) and #44 (drop when the
upper bound is at least 400 days before now, refuse over default-partition rows),
and the interface in work/plans/TASK-019.md, before reading the code. Database
cases use a container of their own (maintain adds partitions), migrated via the
CLI; the clock is injected through ``run_maintain(dsn, now=...)``.
"""

import secrets
import traceback
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from pydantic import SecretStr

from .conftest import Conn, PgServer, bootstrapped_server, run_cli, write_dsn_file

MIGRATE = "BITSCAN_MIGRATE_DSN_FILE"


def month_start(t: datetime) -> datetime:
    t = t.astimezone(UTC)
    return datetime(t.year, t.month, 1, tzinfo=UTC)


def add_months(t: datetime, n: int) -> datetime:
    m = t.month - 1 + n
    return t.replace(year=t.year + m // 12, month=m % 12 + 1)


def window(now: datetime) -> list[tuple[str, datetime, datetime]]:
    start = month_start(now)
    return [
        (
            f"scan_result_{add_months(start, i):%Y_%m}",
            add_months(start, i),
            add_months(start, i + 1),
        )
        for i in range(4)
    ]


def ranges(now: datetime, months: list[int]) -> list[Any]:
    from bitscan_manager.db.maintain import MonthRange

    start = month_start(now)
    return [
        MonthRange(
            f"scan_result_{add_months(start, i):%Y_%m}",
            add_months(start, i),
            add_months(start, i + 1),
        )
        for i in months
    ]


def chain_text(exc: BaseException) -> str:
    parts, cur, seen = [], exc, set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        parts += [str(cur), repr(cur)]
        cur = cur.__cause__ or cur.__context__  # type: ignore[assignment]
    return "\n".join([*parts, "".join(traceback.format_exception(exc))])


# --- unit: the pure planner (no Docker) ----------------------------------------------


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_plan_nothing_when_the_window_exists() -> None:
    from bitscan_manager.db.maintain import plan_partitions

    plan = plan_partitions(NOW, ranges(NOW, [0, 1, 2, 3]))
    assert plan.create == () and plan.drop == ()


def test_plan_after_two_months_creates_exactly_two() -> None:
    from bitscan_manager.db.maintain import plan_partitions

    later = add_months(NOW, 2)
    plan = plan_partitions(later, ranges(NOW, [0, 1, 2, 3]))
    assert [(r.name, r.lower, r.upper) for r in plan.create] == window(later)[2:]
    assert [r.name for r in plan.create] == [
        "scan_result_2027_02",
        "scan_result_2027_03",
    ]
    assert plan.drop == ()


@pytest.mark.parametrize(
    ("now", "names"),
    [
        (
            datetime(2026, 12, 15, tzinfo=UTC),
            ["2026_12", "2027_01", "2027_02", "2027_03"],
        ),
        (
            datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC),
            ["2026_11", "2026_12", "2027_01", "2027_02"],
        ),
        (
            datetime(2026, 10, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5))),
            ["2026_11", "2026_12", "2027_01", "2027_02"],
        ),
        (
            datetime(2027, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=9))),
            ["2026_12", "2027_01", "2027_02", "2027_03"],
        ),
    ],
    ids=[
        "december",
        "last-second-of-november",
        "utc-is-next-month",
        "utc-is-prev-month",
    ],
)
def test_plan_from_nothing_uses_utc_months(now: datetime, names: list[str]) -> None:
    from bitscan_manager.db.maintain import plan_partitions

    plan = plan_partitions(now, [])
    assert [r.name for r in plan.create] == [f"scan_result_{n}" for n in names]
    for r in plan.create:
        assert r.lower.utcoffset() == timedelta(0) and r.lower.day == 1
        assert r.lower.hour == r.lower.minute == r.lower.second == 0
        assert r.upper == add_months(r.lower, 1)
    assert [(r.name, r.lower, r.upper) for r in plan.create] == window(now)


def test_plan_fills_a_gap_in_the_window() -> None:
    from bitscan_manager.db.maintain import plan_partitions

    plan = plan_partitions(NOW, ranges(NOW, [0, 2]))
    assert [r.name for r in plan.create] == [
        "scan_result_2026_11",
        "scan_result_2027_01",
    ]


def test_plan_drops_at_400_days_and_not_at_399() -> None:
    from bitscan_manager.db.maintain import MonthRange, plan_partitions

    upper = datetime(2025, 9, 1, tzinfo=UTC)
    aug = MonthRange("scan_result_2025_08", datetime(2025, 8, 1, tzinfo=UTC), upper)
    exactly = upper + timedelta(days=400)
    assert plan_partitions(exactly, [aug]).drop == ("scan_result_2025_08",)
    just_before = exactly - timedelta(seconds=1)
    assert plan_partitions(just_before, [aug]).drop == ()
    default_like = plan_partitions(exactly, [aug, *ranges(exactly, [0, 1, 2, 3])])
    assert default_like.drop == ("scan_result_2025_08",) and default_like.create == ()


def test_plan_moving_the_clock_back_never_drops_future_partitions() -> None:
    from bitscan_manager.db.maintain import plan_partitions

    plan = plan_partitions(add_months(NOW, -2), ranges(NOW, [0, 1, 2, 3]))
    assert plan.drop == ()
    assert [r.name for r in plan.create] == [
        "scan_result_2026_08",
        "scan_result_2026_09",
    ]


def test_plan_finds_partitions_by_bounds_not_name() -> None:
    from bitscan_manager.db.maintain import MonthRange, plan_partitions

    renamed = [
        MonthRange(f"weird_{i}", r.lower, r.upper)
        for i, r in enumerate(ranges(NOW, [0, 1, 2, 3]))
    ]
    assert plan_partitions(NOW, renamed).create == ()


# --- unit: no secret leaks through a DSN parse error (TASK-013 nit) ---


@pytest.mark.parametrize("runner", ["migrate", "maintain"])
def test_malformed_dsn_passed_straight_to_the_runner_leaks_nothing(runner: str) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    bad = SecretStr(f"host=db.example password='{canary} sslmode=require")
    from bitscan_manager.db import run_migrations
    from bitscan_manager.db.maintain import run_maintain

    run: Callable[[SecretStr], object] = (
        run_migrations if runner == "migrate" else run_maintain
    )
    with pytest.raises(Exception) as err:
        run(bad)
    assert canary not in chain_text(err.value)


# --- PostgreSQL ---


@pytest.fixture
def fresh_migrated(fresh_pg_server: PgServer, tmp_path: Path) -> PgServer:
    env = {
        MIGRATE: str(
            write_dsn_file(
                tmp_path, "migrate_dsn", fresh_pg_server.dsn("bitscan_migrate")
            )
        )
    }
    proc = run_cli(["db", "migrate"], env)
    assert proc.returncode == 0, proc.stderr
    return fresh_pg_server


@pytest.fixture
def owner(fresh_migrated: PgServer) -> Iterator[Conn]:
    with fresh_migrated.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        conn.execute("SET TimeZone = 'UTC'")
        yield conn


def maintain(server: PgServer, now: datetime | None = None) -> Any:
    from bitscan_manager.db.maintain import run_maintain

    return run_maintain(SecretStr(server.dsn("bitscan_migrate")), now=now)


def partitions(conn: Conn) -> list[tuple[str, str, str, frozenset[tuple[str, str]]]]:
    rows = conn.execute(
        "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid),"
        " pg_get_userbyid(c.relowner),"
        " coalesce((SELECT array_agg(pg_get_userbyid(a.grantee)"
        " || ':' || a.privilege_type)"
        " FROM aclexplode(c.relacl) a WHERE a.grantee <> c.relowner), '{}')"
        " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
        " WHERE i.inhparent = 'scan_result'::regclass ORDER BY 1"
    ).fetchall()
    return [
        (r[0], r[1], r[2], frozenset(tuple(x.split(":")) for x in r[3])) for r in rows
    ]


def bound(lower: datetime, upper: datetime) -> str:
    return (
        f"FOR VALUES FROM ('{lower:%Y-%m-%d} 00:00:00+00')"
        f" TO ('{upper:%Y-%m-%d} 00:00:00+00')"
    )


DEFAULT_ACL = frozenset(
    {
        ("bitscan_app", "SELECT"),
        ("bitscan_app", "INSERT"),
        ("bitscan_retention", "SELECT"),
    }
)


def old_partition(conn: Conn, name: str, lower: datetime, upper: datetime) -> None:
    conn.execute(
        sql.SQL(
            "CREATE TABLE {} PARTITION OF scan_result FOR VALUES FROM ({}) TO ({})"
        ).format(sql.Identifier(name), sql.Literal(lower), sql.Literal(upper))
    )


def fill_months(conn: Conn, lo: datetime, hi: datetime) -> None:
    """Every monthly partition from ``lo`` up to, not including, ``hi``, so the set
    stays contiguous (guard (c), second amendment to #44)."""
    month = lo
    while month < hi:
        old_partition(conn, f"scan_result_{month:%Y_%m}", month, add_months(month, 1))
        month = add_months(month, 1)


def drop_month(conn: Conn, month: datetime) -> None:
    conn.execute(
        sql.SQL("DROP TABLE {}").format(sql.Identifier(f"scan_result_{month:%Y_%m}"))
    )


def result_at(conn: Conn, when: datetime) -> None:
    """One scan_result row with job_created_at = when (job created at that time)."""
    fam = conn.execute(
        "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
        (f"F{secrets.token_hex(4)}",),
    ).fetchone()
    assert fam is not None
    pol = conn.execute(
        "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
        " source_file, source_sha256) VALUES (%s, 'enabled', 'enabled', %s, %s, %s)"
        " RETURNING policy_id",
        (secrets.token_hex(4), fam[0], secrets.token_hex(4), "a" * 64),
    ).fetchone()
    assert pol is not None
    plug = conn.execute(
        "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
        " execute,"
        " execute_sha256, operator) VALUES (gen_random_uuid(), %s, %s, 'x', 'true', %s,"
        " 'equals') RETURNING plugin_uuid",
        (fam[0], pol[0], "b" * 64),
    ).fetchone()
    agent = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at) VALUES (%s, 'h', 'v', %s, now(), now())"
        " RETURNING agent_id",
        (secrets.token_hex(16), secrets.token_hex(32)),
    ).fetchone()
    assert plug is not None and agent is not None
    job = conn.execute(
        "INSERT INTO scan_job (kind, agent_id, payload, pickup_by, created_at)"
        " VALUES ('inventory', %s, '{}', now(), %s) RETURNING job_id, created_at",
        (agent[0], when),
    ).fetchone()
    assert job is not None
    conn.execute(
        "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
        " plugin_name_snap, execute_snap, operator_snap, expected_snap, started_at,"
        " finished_at) VALUES (%s, %s, %s, 0, 'n', 'e', 'equals', '', now(), now())",
        (job[0], job[1], plug[0]),
    )


@pytest.mark.pg
def test_maintain_on_a_fresh_migrate_is_a_no_op(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    before = partitions(owner)
    plan = maintain(fresh_migrated)
    assert plan.create == () and plan.drop == ()
    assert partitions(owner) == before


@pytest.mark.pg
def test_two_months_later_creates_exactly_the_missing_two(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    now = datetime.now(UTC)
    later = add_months(month_start(now), 2) + timedelta(days=3)
    plan = maintain(fresh_migrated, now=later)
    expected = window(later)
    assert [r.name for r in plan.create] == [n for n, _, _ in expected[2:]]
    parts = {p[0]: p for p in partitions(owner)}
    for name, lower, upper in expected:
        assert parts[name][1] == bound(lower, upper), name
    for name in (n for n in parts if n != "scan_result_default"):
        assert parts[name][2] == "bitscan_owner", name
        assert parts[name][3] == DEFAULT_ACL, name
    assert len(parts) == 7  # default + 4 from m0005 + 2 new, contiguous
    again = maintain(fresh_migrated, now=later)
    assert again.create == () and again.drop == ()
    assert {p[0]: p for p in partitions(owner)} == parts


@pytest.mark.pg
def test_app_is_refused_changes_on_a_maintain_created_partition(
    fresh_migrated: PgServer,
) -> None:
    """CHK-M1-177: REQ-025 (2) on a partition made by db maintain."""
    later = add_months(month_start(datetime.now(UTC)), 1) + timedelta(days=1)
    plan = maintain(fresh_migrated, now=later)
    assert len(plan.create) == 1
    name = plan.create[0].name
    with fresh_migrated.connect("bitscan_app") as app:
        t = sql.Identifier(name)
        for stmt in (
            sql.SQL("UPDATE {} SET eval_code = eval_code WHERE false").format(t),
            sql.SQL("DELETE FROM {} WHERE false").format(t),
            sql.SQL("TRUNCATE {}").format(t),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with app.transaction(force_rollback=True):
                    app.execute(stmt)
        app.execute(sql.SQL("SELECT 1 FROM {} LIMIT 0").format(t))


@pytest.mark.pg
def test_drops_only_partitions_past_400_days_and_keeps_rows_elsewhere(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    now = datetime.now(UTC)
    edge = month_start(now - timedelta(days=400))
    past_lo, past_hi = add_months(edge, -1), edge  # upper >= 400 days ago: dropped
    young_lo, young_hi = edge, add_months(edge, 1)  # upper < 400 days ago: kept
    past, young = f"scan_result_{past_lo:%Y_%m}", f"scan_result_{young_lo:%Y_%m}"
    old_partition(owner, past, past_lo, past_hi)
    old_partition(owner, young, young_lo, young_hi)
    fill_months(owner, young_hi, month_start(now))  # no gap up to m0005's months
    result_at(owner, past_lo + timedelta(days=3))  # rows do not stop the drop (#44)
    result_at(owner, young_lo + timedelta(days=3))
    result_at(owner, now)
    keep = owner.execute(
        "SELECT tableoid::regclass::text, count(*), md5(string_agg(job_id::text, ','"
        " ORDER BY job_id)) FROM scan_result GROUP BY 1 ORDER BY 1"
    ).fetchall()
    plan = maintain(fresh_migrated, now=now)
    # a row exactly at now is not "later than now": the guard lets drops run
    assert plan.drop == (past,) and plan.drops_refused is None
    names = {p[0] for p in partitions(owner)}
    assert past not in names and young in names and "scan_result_default" in names
    after = owner.execute(
        "SELECT tableoid::regclass::text, count(*), md5(string_agg(job_id::text, ','"
        " ORDER BY job_id)) FROM scan_result GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert after == [r for r in keep if r[0] != past]


@pytest.mark.pg
def test_refuses_to_create_over_default_partition_rows(
    fresh_migrated: PgServer, owner: Conn, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    later = add_months(month_start(now), 1) + timedelta(days=2)
    new_month = window(later)[3]
    result_at(owner, new_month[1] + timedelta(days=5))  # lands in scan_result_default
    job = owner.execute("SELECT job_id::text FROM scan_result_default").fetchone()
    assert job is not None
    before = partitions(owner)
    with pytest.raises(Exception) as err:
        maintain(fresh_migrated, now=later)
    text = chain_text(err.value)
    message = str(err.value)
    assert "scan_result_default" in message
    assert f"{new_month[1]:%Y-%m}" in message  # names the month it would create
    assert job[0] not in text
    assert partitions(owner) == before


@pytest.mark.pg
def test_cli_db_maintain(fresh_migrated: PgServer, tmp_path: Path) -> None:
    dsn = fresh_migrated.dsn("bitscan_migrate")
    password = dsn.split("password=")[1].split()[0]
    env = {MIGRATE: str(write_dsn_file(tmp_path, "m", dsn))}
    ok = run_cli(["db", "maintain"], env)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == "nothing to do"
    assert password not in ok.stdout + ok.stderr
    assert run_cli(["db", "maintain"], {}).returncode == 2
    unset = run_cli(["db", "maintain"], {})
    assert MIGRATE in unset.stderr and unset.stdout == ""
    canary = f"CANARY-{secrets.token_hex(8)}"
    wrong = dsn.split("password=")[0] + f"password={canary} sslmode=require"
    bad = run_cli(
        ["db", "maintain"], {MIGRATE: str(write_dsn_file(tmp_path, "w", wrong))}
    )
    assert bad.returncode == 1
    assert canary not in bad.stdout + bad.stderr
    plain = dsn.replace("sslmode=require", "sslmode=disable")
    notls = run_cli(
        ["db", "maintain"], {MIGRATE: str(write_dsn_file(tmp_path, "p", plain))}
    )
    assert notls.returncode == 2 and MIGRATE in notls.stderr
    app = fresh_migrated.dsn("bitscan_app")
    as_app = run_cli(
        ["db", "maintain"], {MIGRATE: str(write_dsn_file(tmp_path, "a", app))}
    )
    assert as_app.returncode == 1


@pytest.mark.pg
def test_maintain_runs_no_delete_and_only_partition_ddl(tmp_path: Path) -> None:
    log: list[str] = []
    args = ("-c", "log_statement=all", "-c", "log_line_prefix=%u|")
    with bootstrapped_server(extra_args=args, log=log) as server:
        env = {
            MIGRATE: str(write_dsn_file(tmp_path, "m", server.dsn("bitscan_migrate")))
        }
        assert run_cli(["db", "migrate"], env).returncode == 0
        with server.connect("bitscan_migrate") as marker:
            marker.execute("SELECT 'maintain starts here'")
        later = add_months(month_start(datetime.now(UTC)), 2) + timedelta(days=1)
        maintain(server, now=later)
    lines = log[0].split("\n")
    start = next(i for i, line in enumerate(lines) if "maintain starts here" in line)
    statements = [
        line.split("statement: ", 1)[1]
        for line in lines[start + 1 :]
        if line.startswith("bitscan_migrate|") and "statement: " in line
    ]
    assert statements, "no statement logged for db maintain"
    for s in statements:
        upper = s.upper()
        assert not upper.startswith(("DELETE", "UPDATE", "INSERT", "TRUNCATE")), s
        if upper.startswith(("CREATE", "DROP", "ALTER")):
            assert upper.startswith(('CREATE TABLE "SCAN_RESULT_', "DROP TABLE")), s
            assert "PARTITION OF SCAN_RESULT" in upper or upper.startswith("DROP"), s


# --- revision 1: clock guard, naive clock, advisory lock (#44 amendment) ---


def test_naive_now_is_refused() -> None:
    from bitscan_manager.db.maintain import plan_partitions, run_maintain

    naive = datetime(2026, 10, 20, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_partitions(naive, [])
    with pytest.raises(ValueError, match="timezone-aware"):
        run_maintain(SecretStr("host=127.0.0.1 port=1 sslmode=require"), now=naive)


@pytest.mark.pg
def test_clock_far_ahead_refuses_every_drop_but_creates_the_window(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    now = datetime.now(UTC)
    start = month_start(now)
    for i in range(-24, 0):  # 24 older monthly partitions
        lo = add_months(start, i)
        old_partition(owner, f"scan_result_{lo:%Y_%m}", lo, add_months(lo, 1))
    before = {p[0] for p in partitions(owner)}
    ahead = add_months(start, 24) + timedelta(days=3)
    plan = maintain(fresh_migrated, now=ahead)
    assert plan.drops_refused is not None and plan.drop == ()
    assert f"{ahead:%Y-%m-%dT%H:%M:%S}" in plan.drops_refused  # names the clock
    after = {p[0] for p in partitions(owner)}
    assert before <= after  # nothing dropped
    assert {n for n, _, _ in window(ahead)} <= after  # the window was created


@pytest.mark.pg
def test_clock_inside_the_window_keeps_the_400_day_behaviour(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    now = datetime.now(UTC)
    edge = month_start(now - timedelta(days=400))
    past_lo = add_months(edge, -1)
    old_partition(owner, f"scan_result_{past_lo:%Y_%m}", past_lo, edge)
    fill_months(owner, edge, month_start(now))  # contiguous: guard (c) not tripped
    plan = maintain(fresh_migrated, now=now)
    assert plan.drops_refused is None
    assert plan.drop == (f"scan_result_{past_lo:%Y_%m}",)


@pytest.mark.pg
def test_future_job_created_at_refuses_drops(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    now = datetime.now(UTC)
    edge = month_start(now - timedelta(days=400))
    past_lo = add_months(edge, -1)
    past = f"scan_result_{past_lo:%Y_%m}"
    old_partition(owner, past, past_lo, edge)
    fill_months(owner, edge, month_start(now))
    result_at(owner, now + timedelta(days=20))  # data from "the future"
    plan = maintain(fresh_migrated, now=now)
    assert plan.drops_refused is not None and plan.drop == ()
    assert f"{now:%Y-%m-%dT%H:%M:%S}" in plan.drops_refused
    assert past in {p[0] for p in partitions(owner)}


@pytest.mark.pg
def test_cli_exit_1_when_drops_are_refused(
    fresh_migrated: PgServer, owner: Conn, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    edge = month_start(now - timedelta(days=400))
    past_lo = add_months(edge, -1)
    old_partition(owner, f"scan_result_{past_lo:%Y_%m}", past_lo, edge)
    fill_months(owner, edge, month_start(now))  # contiguous: guard (c) not tripped
    result_at(owner, now + timedelta(days=20))
    dsn = fresh_migrated.dsn("bitscan_migrate")
    env = {MIGRATE: str(write_dsn_file(tmp_path, "m", dsn))}
    before = datetime.now(UTC)
    proc = run_cli(["db", "maintain"], env)
    after = datetime.now(UTC)
    assert proc.returncode == 1
    assert "drops refused" in proc.stderr
    assert f"{before:%Y-%m-%d}" in proc.stderr or f"{after:%Y-%m-%d}" in proc.stderr
    assert "dropped" not in proc.stdout
    job = owner.execute(
        "SELECT job_id::text FROM scan_result ORDER BY job_created_at DESC LIMIT 1"
    ).fetchone()
    assert job is not None and job[0] not in proc.stdout + proc.stderr


@pytest.mark.pg
def test_two_concurrent_runs_do_not_both_plan(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    import threading

    later = add_months(month_start(datetime.now(UTC)), 2) + timedelta(days=1)
    results: list[Any] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        try:
            barrier.wait()
            results.append(maintain(fresh_migrated, now=later))
        except BaseException as exc:  # noqa: BLE001  # asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    created = sorted(r.name for res in results for r in res.create)
    assert created == sorted(n for n, _, _ in window(later)[2:])  # once, not twice
    assert len(partitions(owner)) == 7


@pytest.mark.pg
def test_a_run_waits_for_the_maintain_lock_then_plans_afresh(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    """Deterministic form of the run lock (key from the TASK-019 rev 1 report)."""
    import threading
    import time

    later = add_months(month_start(datetime.now(UTC)), 1) + timedelta(days=1)
    holder = psycopg.connect(fresh_migrated.dsn("bitscan_migrate"), autocommit=False)
    holder.execute("SET ROLE bitscan_owner")
    holder.execute("SELECT pg_advisory_xact_lock(hashtext('db_maintain'))")
    results: list[Any] = []
    t = threading.Thread(target=lambda: results.append(maintain(fresh_migrated, later)))
    t.start()
    waited = False
    for _ in range(200):
        row = owner.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        ).fetchone()
        if row and row[0] > 0:
            waited = True
            break
        time.sleep(0.05)
    assert waited, "db maintain did not wait on its advisory lock"
    assert results == [] and len(partitions(owner)) == 5  # nothing created yet
    old_partition(holder, window(later)[3][0], window(later)[3][1], window(later)[3][2])
    holder.commit()  # releases the lock; the waiting run must see this partition
    holder.close()
    t.join(timeout=60)
    assert len(results) == 1 and results[0].create == ()
    assert len(partitions(owner)) == 6


def test_cli_exit_codes_for_refused_and_normal_drops(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Windows-run: the CLI maps drops_refused to exit 1 (run_maintain stubbed)."""
    from bitscan_manager import cli
    from bitscan_manager.db import maintain as maintain_mod
    from bitscan_manager.db.maintain import MaintainPlan, MonthRange

    dsn = "host=127.0.0.1 port=1 dbname=bitscan user=bitscan_migrate sslmode=require"
    monkeypatch.setenv(MIGRATE, str(write_dsn_file(tmp_path, "m", dsn)))
    lo = datetime(2030, 1, 1, tzinfo=UTC)
    made = MonthRange("scan_result_2030_01", lo, add_months(lo, 1))
    refused = MaintainPlan(
        create=(made,), drop=(), drops_refused="drops refused: CLOCK-REASON"
    )
    normal = MaintainPlan(create=(), drop=("scan_result_2020_01",))
    for plan, code, out, err in (
        (refused, 1, "created scan_result_2030_01", "CLOCK-REASON"),
        (normal, 0, "dropped scan_result_2020_01", None),
    ):
        monkeypatch.setattr(maintain_mod, "run_maintain", lambda d, now=None, p=plan: p)
        assert cli.main(["db", "maintain"]) == code
        got = capsys.readouterr()
        assert out in got.out
        if err is None:
            assert got.err == ""
        else:
            assert err in got.err and err not in got.out


# --- revision 2: guard (c), second amendment to #44 (contiguous partitions) ---
#
# "db maintain refuses every DROP when the existing non-default scan_result
# partitions, read before the run's creates, are not contiguous (a UTC month
# missing between the oldest and the newest); the window is still created; exit 1;
# the message names the missing month(s)."


@pytest.mark.pg
def test_fast_clock_second_run_still_drops_nothing_and_names_the_gap(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    """(1) The CHK-M1-186 probe scenario: clock +24 months, run twice."""
    now = datetime.now(UTC)
    start = month_start(now)
    fill_months(owner, add_months(start, -6), start)  # in retention, contiguous
    ahead = add_months(start, 24) + timedelta(days=3)
    first = maintain(fresh_migrated, now=ahead)
    assert first.drops_refused is not None and first.drop == ()
    kept = {p[0] for p in partitions(owner)}
    second = maintain(fresh_migrated, now=ahead + timedelta(days=1))
    assert second.drops_refused is not None, f"second run dropped {second.drop}"
    assert second.drop == ()
    # the hole run 1 left: the month after m0005's last one is named
    assert f"{add_months(start, 4):%Y-%m}" in second.drops_refused
    assert {p[0] for p in partitions(owner)} == kept  # nothing dropped by run 2


@pytest.mark.pg
def test_contiguous_partitions_and_a_correct_clock_still_drop(
    fresh_migrated: PgServer, owner: Conn
) -> None:
    """(2) No gap and no clock doubt: the 400-day drop happens as before."""
    now = datetime.now(UTC)
    edge = month_start(now - timedelta(days=400))
    oldest = add_months(edge, -2)
    fill_months(owner, oldest, month_start(now))
    plan = maintain(fresh_migrated, now=now)
    assert plan.drops_refused is None
    assert set(plan.drop) == {
        f"scan_result_{oldest:%Y_%m}",
        f"scan_result_{add_months(oldest, 1):%Y_%m}",
    }


@pytest.mark.pg
@pytest.mark.parametrize("holes", [1, 2])
def test_a_manually_dropped_middle_month_refuses_drops_and_names_it(
    fresh_migrated: PgServer, owner: Conn, holes: int
) -> None:
    """(3) and (4): a gap refuses every drop, names the month(s), and the window
    is still created (clock +1 month so there is one partition to create)."""
    now = datetime.now(UTC)
    start = month_start(now)
    edge = month_start(now - timedelta(days=400))
    oldest = add_months(edge, -1)
    fill_months(owner, oldest, start)
    missing = [add_months(start, -3 - i) for i in range(holes)]
    for month in missing:
        drop_month(owner, month)
    later = add_months(start, 1) + timedelta(days=1)
    before = {p[0] for p in partitions(owner)}
    plan = maintain(fresh_migrated, now=later)
    assert plan.drops_refused is not None and plan.drop == ()
    for month in missing:
        assert f"{month:%Y-%m}" in plan.drops_refused, month
    after = {p[0] for p in partitions(owner)}
    assert before <= after  # nothing dropped, the past-retention month kept
    assert f"scan_result_{oldest:%Y_%m}" in after
    assert {n for n, _, _ in window(later)} <= after  # (4) window created
    assert [r.name for r in plan.create] == [window(later)[3][0]]


@pytest.mark.pg
def test_cli_exit_1_and_names_the_gap(
    fresh_migrated: PgServer, owner: Conn, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    start = month_start(now)
    edge = month_start(now - timedelta(days=400))
    fill_months(owner, add_months(edge, -1), start)
    gap = add_months(start, -2)
    drop_month(owner, gap)
    env = {
        MIGRATE: str(
            write_dsn_file(tmp_path, "m", fresh_migrated.dsn("bitscan_migrate"))
        )
    }
    proc = run_cli(["db", "maintain"], env)
    assert proc.returncode == 1
    assert "drops refused" in proc.stderr and f"{gap:%Y-%m}" in proc.stderr
    assert "dropped" not in proc.stdout


def test_missing_months_lists_the_holes_between_oldest_and_newest() -> None:
    """Pure part of guard (c), from the second amendment text (no Docker)."""
    from bitscan_manager.db.maintain import missing_months, month_range

    def months(*pairs: tuple[int, int]) -> list[Any]:
        return [month_range(datetime(y, m, 1, tzinfo=UTC)) for y, m in pairs]

    assert missing_months([]) == []
    assert missing_months(months((2026, 10))) == []
    assert missing_months(months((2026, 11), (2027, 2), (2026, 10))) == [
        "2026-12",
        "2027-01",
    ]  # across a year end, order of input irrelevant
    contiguous = months(
        *[(2025 + (m - 1) // 12, (m - 1) % 12 + 1) for m in range(1, 25)]
    )
    assert missing_months(contiguous) == []


def test_gap_message_names_at_most_twelve_months_then_counts() -> None:
    from bitscan_manager.db.maintain import _clock_doubt, month_range

    lo = datetime(2026, 1, 1, tzinfo=UTC)
    existing = [month_range(lo), month_range(add_months(lo, 20))]
    now = add_months(lo, 20) + timedelta(days=2)

    class NoQuery:
        def execute(self, *args: object) -> None:
            raise AssertionError("guard (c) must refuse before guard (b) queries")

    msg = _clock_doubt(NoQuery(), now, existing)  # type: ignore[arg-type]
    assert msg is not None
    assert "2026-02" in msg and "2027-01" in msg  # first 12 of the 19 missing
    assert "2027-02" not in msg and "and 7 more" in msg
    assert f"{now:%Y-%m-%dT%H:%M:%S}" in msg
