"""TASK-196 TEST: the compliance sweep repository on PostgreSQL as
bitscan_app (TP-M9-10; CHK-M9-120, -121; mutation rows CHK-M9-339, -340,
-346, -377).

Expected values: TS §4.4 L575 (dispatched or running jobs past their
deadline become failed or partial; a dispatched job that never starts
fails 24 h after dispatch), L577 (one retry: a new row with a new job_id,
retry_of = the original; a retry is never retried), §3.3 L218, §5.2 L1011
(UPDATE only of the progress columns); #127 (b) (strictly past: deadline_at
< now, dispatched_at < now − 24 h), #126 (c); #124 (c) (root, then job).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import job_sweep as js

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(days=2)
DAY = timedelta(hours=24)
US = timedelta(microseconds=1)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("js")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    with f.app_database(server) as db:
        yield f.make_catalog(db, f.Clock(), tmp_path)


def agent(server: PgServer, status: str = "online") -> UUID:
    with f.app(server) as c:
        return f.make_agent(c, status).agent_id


# ------------------------------------------------------------ CHK-M9-120


def test_deadline_candidates_are_strictly_past(
    server: PgServer, cat: f.Catalog
) -> None:
    """#127 (b), CHK-M9-339: deadline_at = now is not a candidate; now − 1 µs
    is; dispatched and running only; completed, partial, failed jobs with a
    passed deadline and inventory jobs never are."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")

        def job(state: str, deadline: datetime) -> UUID:
            return f.owner_job(
                o,
                s,
                a,
                pol,
                state=state,
                started_at=NOW - DAY,
                deadline_at=deadline,
            ).job_id

        at_now = job("running", NOW)
        past = job("running", NOW - US)
        dispatched_past = job("dispatched", NOW - timedelta(minutes=1))
        future = job("running", NOW + US)
        ended = [job(st, NOW - DAY) for st in ("completed", "partial", "failed")]
        inv = f.owner_inventory_job(o, a, state="dispatched", created_at=NOW - DAY)
    with f.app(server) as conn:
        got = set(js.past_deadline(conn, NOW))
    assert {past, dispatched_past} <= got
    assert not {at_now, future, inv, *ended} & got


def test_never_started_is_measured_from_dispatch_strictly(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L575, #127 (b), CHK-M9-340: dispatched_at = now − 24 h is not
    a candidate, − 24 h − 1 s is; a job created long ago but dispatched
    recently is not (measured from dispatched_at, not created_at); a started
    or running job and an inventory job never are."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")

        def job(
            dispatched: datetime,
            *,
            created: datetime | None = None,
            state: str = "dispatched",
            started: datetime | None = None,
        ) -> UUID:
            return f.owner_job(
                o,
                s,
                a,
                pol,
                state=state,
                created_at=created or NOW - timedelta(days=3),
                dispatched_at=dispatched,
                started_at=started,
            ).job_id

        exactly = job(NOW - DAY)
        over = job(NOW - DAY - timedelta(seconds=1))
        old_but_fresh = job(NOW - timedelta(hours=1), created=NOW - timedelta(days=5))
        started = job(
            NOW - timedelta(days=2), state="dispatched", started=NOW - timedelta(days=2)
        )
        running = job(NOW - timedelta(days=2), state="running")
        inv = f.owner_inventory_job(
            o, a, state="dispatched", created_at=NOW - timedelta(days=3)
        )
    with f.app(server) as conn:
        got = set(js.never_started(conn, NOW, DAY))
    assert over in got
    assert not {exactly, old_but_fresh, started, running, inv} & got


# ------------------------------------------------------------ CHK-M9-121


def test_lock_for_sweep_reads_the_job_with_policy_and_agent_flags(
    server: PgServer, cat: f.Catalog
) -> None:
    pol = cat.policy(2)
    gone = cat.policy(1)
    a, dec = agent(server), agent(server, "decommissioned")
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state="failed")
        retry = f.owner_job(
            o, s, a, pol, pol.plugins[1:], state="running", retry_of=orig.job_id
        )
        sg = f.owner_scan(o, gone, state="running")
        jg = f.owner_job(o, sg, dec, gone, state="running")
        f.owner_result(o, orig, pol, pol.plugins[0])
        f.owner_result(o, retry, pol, pol.plugins[1])
    cat.delete(gone)
    with f.app(server, autocommit=False) as conn:
        got = js.lock_for_sweep(conn, retry.job_id)
        g = js.lock_for_sweep(conn, jg.job_id)
        assert js.lock_for_sweep(conn, uuid4()) is None
        assert got is not None and g is not None
        have = js.unit_result_uuids(conn, got)
        conn.rollback()
    assert (got.job_id, got.root_id, got.retry_of, got.scan_id, got.agent_id) == (
        retry.job_id,
        orig.job_id,
        orig.job_id,
        s,
        a,
    )
    assert got.payload == retry.payload and got.eval_spec == retry.eval_spec
    assert (got.state, got.created_at) == ("running", retry.created_at)
    assert (got.policy_deleted, got.agent_decommissioned) == (False, False)
    assert (g.policy_deleted, g.agent_decommissioned) == (True, True)
    assert have == {pol.uuids[0], pol.uuids[1]}  # the unit: retry + original


@pytest.mark.parametrize("held", ["root", "job"])
def test_a_unit_held_by_another_session_is_skipped_without_waiting(
    server: PgServer, cat: f.Catalog, held: str
) -> None:
    """#124 (c), D3: root then job, SKIP LOCKED — a sweep never waits for a
    result post holding the unit's root (or the job); it returns None at
    once and the job is handled by the next sweep."""
    pol = cat.policy(2)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state="failed")
        retry = f.owner_job(o, s, a, pol, state="running", retry_of=orig.job_id)
    target = orig.job_id if held == "root" else retry.job_id
    with (
        f.app(server, autocommit=False) as a_conn,
        f.app(server, autocommit=False) as b,
    ):
        a_conn.execute("SELECT 1 FROM scan_job WHERE job_id = %s FOR UPDATE", (target,))
        b.execute("SET lock_timeout = '2s'")  # a wait would raise, not hang
        assert js.lock_for_sweep(b, retry.job_id) is None
        b.rollback()
        a_conn.rollback()
        assert js.lock_for_sweep(b, retry.job_id) is not None
        b.rollback()


def test_end_job_ends_once_and_only_open_compliance_jobs(
    server: PgServer, cat: f.Catalog
) -> None:
    """#126 (c), CHK-M9-346: the first end_job of a running job returns True
    and writes state and finished_at only; a second returns False and changes
    nothing (so two sweeps make one retry); ended, queued and inventory jobs
    are not touched; a non-ending state is refused."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        run = f.owner_job(o, s, a, pol, state="running")
        others = [
            f.owner_job(o, s, a, pol, state=st).job_id
            for st in (
                "queued",
                "completed",
                "partial",
                "failed",
                "expired",
                "cancelled",
            )
        ]
        inv = f.owner_inventory_job(o, a, state="dispatched")
    with f.app(server) as conn:
        before = f.job_state(conn, run.job_id)
        snaps = {j: f.job_state(conn, j) for j in [*others, inv]}
        assert js.end_job(conn, run.job_id, "partial", NOW) is True
        after = f.job_state(conn, run.job_id)
        assert js.end_job(conn, run.job_id, "failed", NOW + US) is False
        assert f.job_state(conn, run.job_id) == after
        for j in [*others, inv]:
            assert js.end_job(conn, j, "failed", NOW) is False
            assert f.job_state(conn, j) == snaps[j]
        for bad in ("cancelled", "expired", "running", "queued"):
            with pytest.raises(ValueError):
                js.end_job(conn, run.job_id, bad, NOW)
    assert (after["state"], after["finished_at"]) == ("partial", NOW)
    for col in after:
        if col not in ("state", "finished_at"):
            assert after[col] == before[col], col


def test_insert_retry_writes_the_given_row_and_refuses_a_retry_of_a_retry(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L577, #126, REQ-210 (3): the retry row has the given payload
    and eval_spec (job_id = row id), the original's scan and agent, retry_of
    = the original, state queued, the given created_at and pickup_by; the
    original's row is unchanged; a retry of a retry and a payload whose
    job_id is not the row's are refused before SQL."""
    pol = cat.policy(3)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state="failed")
        rr = f.owner_job(o, s, a, pol, state="failed", retry_of=orig.job_id)
    new = uuid4()
    payload = f.payload_of(new, a, NOW, pol.plugins[1:])
    spec = f.eval_spec_of(pol, pol.plugins[1:])
    with f.app(server, autocommit=False) as conn:
        job = js.lock_for_sweep(conn, orig.job_id)
        retry_job = js.lock_for_sweep(conn, rr.job_id)
        assert job is not None and retry_job is not None
        before = f.job_state(conn, orig.job_id)
        js.insert_retry(
            conn,
            original=job,
            job_id=new,
            payload=payload,
            eval_spec=spec,
            created_at=NOW,
            pickup_by=NOW + DAY,
        )
        with pytest.raises(ValueError):
            js.insert_retry(
                conn,
                original=retry_job,
                job_id=uuid4(),
                payload=payload,
                eval_spec=spec,
                created_at=NOW,
                pickup_by=NOW + DAY,
            )
        with pytest.raises(ValueError):
            js.insert_retry(
                conn,
                original=job,
                job_id=uuid4(),
                payload=payload,
                eval_spec=spec,
                created_at=NOW,
                pickup_by=NOW + DAY,
            )
        conn.commit()
    with f.app(server) as conn:
        row = f.job_state(conn, new)
        assert f.job_state(conn, orig.job_id) == before
    assert (row["payload"], row["eval_spec"]) == (payload, spec)
    assert (row["scan_id"], row["agent_id"], row["retry_of"]) == (s, a, orig.job_id)
    assert (row["state"], row["created_at"], row["pickup_by"]) == (
        "queued",
        NOW,
        NOW + DAY,
    )
    assert row["kind"] == "compliance" and row["dispatched_at"] is None


def test_the_app_cannot_rewrite_a_jobs_payload(
    server: PgServer, cat: f.Catalog
) -> None:
    """CHK-M9-377, TS §5.2 L1011: a retry must be a new row because
    bitscan_app cannot UPDATE payload or eval_spec; the refusal surfaces."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a, pol, state="failed")
    with f.app(server) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "UPDATE scan_job SET payload = payload WHERE job_id = %s", (j.job_id,)
        )


def test_two_sessions_racing_end_job_end_it_once(
    server: PgServer, cat: f.Catalog
) -> None:
    """#126 (c): two sweeps ending one job: the first wins (True), the second,
    after the first commits, gets False (the state guard re-checks)."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a, pol, state="running")
    results: list[bool] = []
    with f.app(server, autocommit=False) as one, f.app(server, autocommit=False) as two:
        results.append(js.end_job(one, j.job_id, "failed", NOW))
        pid = f.backend_pid(two)
        t = threading.Thread(
            target=lambda: results.append(js.end_job(two, j.job_id, "failed", NOW))
        )
        t.start()
        try:
            f.wait_until_lock_waiting(server, pid)
        finally:
            one.commit()
            t.join(10)
        two.commit()
    assert results == [True, False]
