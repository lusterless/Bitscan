"""TASK-085: services/inventory/upload.py with fake stores, no database.

TP-M4-24, CHK-M4-280 of tests/m4/test-plan.md (REQ-112 (2)); mutation row
CHK-M4-366. Expected values come from TS §3.4 L239–L244, #72 (c)–(e) and the
M3 behaviour this refactor must keep (REQ-112: no behaviour change):
- a job_id is classified before anything is decoded: this agent's dispatched
  inventory job completes in the ingest transaction; one that failed or
  completed is an unscheduled snapshot with the job unchanged; anything else
  (unknown, another agent's, compliance, queued, expired, cancelled, running)
  is 409 job_not_acceptable, audited, nothing stored;
- an unscheduled upload asks the 10-minute window first: refused, 429 with
  Retry-After and nothing decoded;
- a 413 or 422 decode refusal fails a dispatched job it named, a 400 leaves
  it; one agent.inventory_refused entry each; answers carry the problem type;
- an agent revoked since its token check: 401 token_revoked, nothing stored.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories.jobs import JobRow
from bitscan_manager.runtime import Database, RateLimits, Tx
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.inventory import upload as up_mod
from bitscan_manager.services.inventory.ingest import NEW_PACKAGES_PER_DAY
from bitscan_manager.services.inventory.upload import (
    Stores,
    Upload,
    UploadRefused,
    classify,
    refuse_unread,
    store_upload,
)

from .test_inventory_ingest import (
    DAY,
    T0,
    Clock,
    FakeAgents,
    FakeInventory,
    Fleet,
    agent_row,
    body,
    pkg,
)

# ------------------------------------------------------------ fakes


class FakeTx:
    """conn is never touched by the fakes; on_commit hooks run on commit."""

    def __init__(self, db: "FakeDB") -> None:
        self.db = db
        self.hooks: list[Callable[[], None]] = []

    @property
    def conn(self) -> Any:
        raise AssertionError("a fake-store test touched tx.conn")

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


@dataclass
class FakeDB:
    opened: int = 0
    committed: int = 0
    rolled_back: int = 0
    current: FakeTx | None = None

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        tx = FakeTx(self)
        self.opened += 1
        self.current = tx
        try:
            yield tx
        except BaseException:
            self.rolled_back += 1
            raise
        finally:
            self.current = None
        self.committed += 1
        for h in tx.hooks:
            h()

    def ping(self) -> bool:
        return True


@dataclass
class FakeJobs:
    rows: dict[UUID, JobRow] = field(default_factory=dict)
    calls: list[tuple[str, UUID]] = field(default_factory=list)

    def get_for_agent(
        self, job_id: UUID, agent_id: UUID, *, lock: bool = False
    ) -> JobRow | None:
        self.calls.append(("get", job_id))
        row = self.rows.get(job_id)
        return row if row is not None and row.agent_id == agent_id else None

    def complete(self, job_id: UUID, now: Any) -> bool:
        self.calls.append(("complete", job_id))
        row = self.rows.get(job_id)
        if row is None or row.state != "dispatched":
            return False
        self.rows[job_id] = replace(row, state="completed", finished_at=now)
        return True

    def fail(self, job_id: UUID, now: Any) -> bool:
        self.calls.append(("fail", job_id))
        row = self.rows.get(job_id)
        if row is None or row.state != "dispatched":
            return False
        self.rows[job_id] = replace(row, state="failed", finished_at=now)
        return True


@dataclass
class FakeAuditSink:
    entries: list[tuple[str, str, str, dict[str, object]]] = field(default_factory=list)
    alerts: list[tuple[str, str, str, str, dict[str, object]]] = field(
        default_factory=list
    )

    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None:
        self.entries.append((actor, action, target, dict(detail)))

    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None:
        self.alerts.append((kind, actor, action, target, dict(detail)))


@dataclass
class FakeLimits:
    allow: bool = True
    retry: int = 417
    asked: list[UUID] = field(default_factory=list)

    def allow_unscheduled_inventory(self, agent_id: UUID) -> bool:
        self.asked.append(agent_id)
        return self.allow

    def unscheduled_inventory_retry_after(self, agent_id: UUID) -> int:
        return self.retry


class World:
    def __init__(self) -> None:
        self.db = FakeDB()
        self.jobs = FakeJobs()
        self.inv = FakeInventory(Fleet())
        self.agents = FakeAgents()
        self.audit = FakeAuditSink()
        self.limits = FakeLimits()
        self.clock = Clock()
        self.burst: SlidingCount[object] = SlidingCount(
            self.clock, DAY, DAY, NEW_PACKAGES_PER_DAY
        )
        self.wakes = 0
        self.factory_txs: list[FakeTx] = []
        self.agent = uuid4()
        self.agents.rows[self.agent] = agent_row(self.agent)

    def stores(self, tx: Tx) -> Stores:
        self.factory_txs.append(cast(FakeTx, tx))
        return Stores(tx, self.jobs, self.inv, self.agents, self.audit)

    def wake(self) -> None:
        self.wakes += 1

    def job(
        self, state: str, kind: str = "inventory", agent: UUID | None = None
    ) -> UUID:
        jid = uuid4()
        self.jobs.rows[jid] = JobRow(
            jid,
            kind,
            agent or self.agent,
            state,
            T0 - timedelta(minutes=5),
            T0 + DAY,
            T0 - timedelta(minutes=1) if state != "queued" else None,
            None,
        )
        return jid

    def up(self, job_id: UUID | None) -> Upload:
        return Upload(self.agent, job_id, T0)

    @property
    def database(self) -> Database:
        return cast(Database, self.db)

    @property
    def rl(self) -> RateLimits:
        return cast(RateLimits, self.limits)

    def store(self, job_id: UUID | None, data: bytes) -> None:
        store_upload(
            self.database,
            self.wake,
            self.rl,
            self.burst,
            self.up(job_id),
            data,
            self.stores,
        )


GOOD = [
    pkg("bash", "5.2.21-2ubuntu4"),
    pkg("zlib1g", "1:1.3.dfsg-3.1ubuntu2", source="zlib"),
]


@pytest.fixture
def w() -> World:
    return World()


def refused_entry(
    w: World, reason: str, status: int, job_id: UUID | None
) -> tuple[str, str, str, dict[str, object]]:
    actor = f"agent:{w.agent}"
    return (
        actor,
        "agent.inventory_refused",
        actor,
        {
            "reason": reason,
            "status": status,
            "job_id": None if job_id is None else str(job_id),
        },
    )


# ------------------------------------------------------------ classify (#72 (d))


def test_no_job_id_is_unscheduled_without_a_transaction(w: World) -> None:
    assert classify(w.database, w.wake, w.up(None), w.stores) == "unscheduled"
    assert w.db.opened == 0 and w.audit.entries == []


def test_dispatched_inventory_job_completes(w: World) -> None:
    jid = w.job("dispatched")
    assert classify(w.database, w.wake, w.up(jid), w.stores) == "completes"
    assert w.audit.entries == [] and w.jobs.rows[jid].state == "dispatched"


@pytest.mark.parametrize("state", ["failed", "completed"])
def test_failed_or_completed_job_is_unscheduled_and_unchanged(
    w: World, state: str
) -> None:
    jid = w.job(state)
    assert classify(w.database, w.wake, w.up(jid), w.stores) == "unscheduled"
    assert w.jobs.rows[jid].state == state and w.audit.entries == []


@pytest.mark.parametrize(
    "case",
    ["unknown", "foreign", "compliance", "queued", "expired", "cancelled", "running"],
)
def test_not_acceptable_job_is_409_audited_and_nothing_stored(
    w: World, case: str
) -> None:
    if case == "unknown":
        jid = uuid4()
    elif case == "foreign":
        other = uuid4()
        w.agents.rows[other] = agent_row(other)
        jid = w.job("dispatched", agent=other)
    elif case == "compliance":
        jid = w.job("dispatched", kind="compliance")
    else:
        jid = w.job(case)
    before = dict(w.jobs.rows)
    with pytest.raises(UploadRefused) as exc:
        w.store(jid, body(GOOD))
    assert (exc.value.status, exc.value.type, exc.value.headers) == (
        409,
        "job_not_acceptable",
        {},
    )
    assert w.audit.entries == [refused_entry(w, "job_not_acceptable", 409, jid)]
    assert w.jobs.rows == before  # no job failed or completed, incl. a foreign one
    assert w.inv.os == {} and w.inv.snaps == {}  # nothing decoded or stored
    assert w.limits.asked == []  # refused before the window is asked
    assert w.wakes == 1  # the audit transaction wakes the shipper on commit


# ------------------------------------------------------------ store_upload


def test_completing_upload_ingests_and_completes_in_one_transaction(w: World) -> None:
    jid = w.job("dispatched")
    w.store(jid, body(GOOD))
    assert w.jobs.rows[jid].state == "completed"
    assert w.inv.os[w.agent].os_id == "ubuntu" and len(w.inv.snaps[w.agent]) == 1
    # classify's read, then one ingest+complete transaction
    assert w.db.opened == 2 and w.db.committed == 2 and w.db.rolled_back == 0
    complete_tx = w.factory_txs[-1]
    assert ("complete", jid) in w.jobs.calls
    assert w.factory_txs.count(complete_tx) == 1  # one stores(tx) per transaction
    assert w.limits.asked == []  # a job upload never asks the window
    assert w.audit.entries == [] and w.wakes == 1


@pytest.mark.parametrize("state", ["failed", "completed"])
def test_upload_for_a_finished_job_is_a_snapshot_with_the_job_unchanged(
    w: World, state: str
) -> None:
    jid = w.job(state)
    w.store(jid, body(GOOD))
    assert w.jobs.rows[jid].state == state
    assert ("complete", jid) not in w.jobs.calls
    assert len(w.inv.snaps[w.agent]) == 1
    assert w.limits.asked == [w.agent]  # an unscheduled upload asks the window


def test_unscheduled_upload_inside_the_window_is_429_and_not_decoded(w: World) -> None:
    w.limits.allow = False
    for jid in (None, w.job("failed")):
        with pytest.raises(UploadRefused) as exc:
            w.store(jid, b"not even gzip")  # would be 400 if it were decoded
        assert (exc.value.status, exc.value.type) == (429, "rate_limited")
        assert exc.value.headers == {"Retry-After": "417"}
    assert w.inv.os == {} and w.audit.entries == []


def test_unscheduled_upload_outside_the_window_is_stored(w: World) -> None:
    w.store(None, body(GOOD))
    assert len(w.inv.snaps[w.agent]) == 1 and w.limits.asked == [w.agent]


@pytest.mark.parametrize(
    ("data", "status", "type_", "reason", "fails"),
    [
        (b"\x1f\x8b not really gzip", 400, "invalid_request", None, False),
        (b"plain text", 400, "invalid_request", None, False),
        (None, 422, "about:blank", "invalid_field", True),
        ("raw", 413, "too_large", "raw_too_large", True),
    ],
)
def test_decode_refusal_audits_and_fails_a_dispatched_job_on_413_422(
    w: World, data: Any, status: int, type_: str, reason: str | None, fails: bool
) -> None:
    jid = w.job("dispatched")
    if data is None:  # schema-invalid: cpu_count negative
        data = body(GOOD, cpu_count=-1)
    elif data == "raw":  # raw over 256 KiB compact
        data = body(GOOD, raw={"big": "x" * 262_200})
    with pytest.raises(UploadRefused) as exc:
        w.store(jid, data)
    assert (exc.value.status, exc.value.type) == (status, type_)
    assert len(w.audit.entries) == 1
    actor, action, target, detail = w.audit.entries[0]
    assert (actor, action, target) == (
        f"agent:{w.agent}",
        "agent.inventory_refused",
        f"agent:{w.agent}",
    )
    assert detail["status"] == status and detail["job_id"] == str(jid)
    if reason is not None:
        assert detail["reason"] == reason
    assert w.jobs.rows[jid].state == ("failed" if fails else "dispatched")
    assert w.inv.os == {}


def test_decode_refusal_of_an_unscheduled_upload_fails_no_job(w: World) -> None:
    jid = w.job("failed")
    other = w.job("dispatched")
    with pytest.raises(UploadRefused) as exc:
        w.store(jid, body(GOOD, cpu_count=-1))
    assert exc.value.status == 422
    assert ("fail", jid) not in w.jobs.calls and w.jobs.rows[
        other
    ].state == "dispatched"
    assert w.audit.entries == [refused_entry(w, "invalid_field", 422, jid)]


def test_agent_revoked_since_its_token_check_is_401_and_nothing_stays(w: World) -> None:
    jid = w.job("dispatched")
    w.agents.rows[w.agent] = agent_row(w.agent, revoked=T0)
    with pytest.raises(UploadRefused) as exc:
        w.store(jid, body(GOOD))
    assert (exc.value.status, exc.value.type) == (401, "token_revoked")
    assert w.jobs.rows[jid].state == "dispatched"
    assert w.db.rolled_back == 1 and w.wakes == 0  # the ingest transaction rolled back
    assert w.inv.os == {}


def test_job_no_longer_dispatched_at_completion_is_not_an_error(w: World) -> None:
    jid = w.job("dispatched")
    real = w.jobs.complete

    def late(job_id: UUID, now: Any) -> bool:
        w.jobs.rows[job_id] = replace(
            w.jobs.rows[job_id], state="failed"
        )  # the sweep won
        return real(job_id, now)

    w.jobs.complete = late  # type: ignore[method-assign]
    w.store(jid, body(GOOD))
    assert w.jobs.rows[jid].state == "failed" and len(w.inv.snaps[w.agent]) == 1


# ------------------------------------------------------------ refuse_unread


@pytest.mark.parametrize(("status", "fails"), [(413, True), (400, False)])
def test_refuse_unread_fails_a_dispatched_job_only_on_413(
    w: World, status: int, fails: bool
) -> None:
    jid = w.job("dispatched")
    refuse_unread(w.database, w.wake, w.up(jid), status, "body_too_large", w.stores)
    assert w.jobs.rows[jid].state == ("failed" if fails else "dispatched")
    assert w.audit.entries == [refused_entry(w, "body_too_large", status, jid)]
    assert w.wakes == 1


@pytest.mark.parametrize("case", ["none", "foreign", "failed", "compliance", "queued"])
def test_refuse_unread_413_without_a_dispatched_job_fails_nothing(
    w: World, case: str
) -> None:
    other = uuid4()
    jid: UUID | None
    if case == "none":
        jid = None
    elif case == "foreign":
        jid = w.job("dispatched", agent=other)
    elif case == "compliance":
        jid = w.job("dispatched", kind="compliance")
    else:
        jid = w.job(case)
    before = dict(w.jobs.rows)
    refuse_unread(w.database, w.wake, w.up(jid), 413, "body_too_large", w.stores)
    assert w.jobs.rows == before
    assert w.audit.entries == [refused_entry(w, "body_too_large", 413, jid)]
    if case == "none":
        assert w.db.opened == 1  # only the audit transaction: no job read


# ------------------------------------------------------------ the seam itself


def test_default_factory_is_pg_stores_and_every_transaction_uses_it_once(
    w: World,
) -> None:
    import inspect

    for fn in (classify, refuse_unread, store_upload):
        assert inspect.signature(fn).parameters["stores"].default is up_mod.pg_stores
    jid = w.job("dispatched")
    w.store(jid, body(GOOD))
    assert len(w.factory_txs) == w.db.opened  # exactly one stores(tx) per transaction
