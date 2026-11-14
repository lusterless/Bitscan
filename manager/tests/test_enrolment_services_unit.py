"""G5 unit half (no PostgreSQL) for the enrolment services: enrol, enrolment
tokens, enrolment requests and token rotation, each driven through its
Protocol seams with fakes and a fixed clock.

The database behaviour is in test_enrol_api_pg.py, test_enrolment_tokens_api_pg.py,
test_enrolment_requests_api_pg.py and test_rotation_api_pg.py; this file
asserts the same outcomes at the service boundary. Expected values come from
the spec and the answers: TS §3.2 L181-L190 (bse_ checks, held enrolments,
approval, rejection, rotation window, 24 h rule, lost-response retry, reuse,
new-IP alert), §6.2 L1083 (only the SHA-256 is stored), §8.4 L1290-L1291
(risky tokens, enrolments per hour), #26, #36, #61, #62, #64, #71 and the
lead rulings of 2026-10-23 (TASK-075 r1, r2; alerts marked only on commit).
"""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.enrolment import (
    EnrolmentTokenRow,
    MatchRow,
    RequestRow,
    UsedToken,
)
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.enrolment import enrol as enrol_mod
from bitscan_manager.services.enrolment import enrolment_tokens as tokens_mod
from bitscan_manager.services.enrolment import requests as requests_mod
from bitscan_manager.services.enrolment import rotation as rotation_mod
from bitscan_manager.services.enrolment.token_check import AgentCaller
from bitscan_manager.services.scheduler.inventory import PICKUP_WINDOW

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEEDED: dict[str, Any] = {
    "agent_token_ttl_days": 365,
    "job_pull_seconds": 300,
    "decommission_after_days": 7,
    "redaction_patterns": [],
    "max_parallel_plugins": 2,
    "enrolment_alert_per_hour": 50,
    "max_parallel_jobs": 2,  # owner decision 2026-11-14 (TS §8.6)
}
BSA_LEN = 47


def is_bsa(token: str) -> bool:
    return token.startswith("bsa_") and len(token) == BSA_LEN


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def now(self) -> datetime:
        return self.at


@dataclass
class Settings:
    values: dict[str, Any] = field(default_factory=lambda: dict(SEEDED))
    interval: int = 21600

    def read_values(self) -> Mapping[str, Any]:
        return self.values

    def schedule_interval(self, job_kind: str) -> int | None:
        return self.interval if job_kind == "inventory" else 60


@dataclass
class Audit:
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

    def kinds(self) -> list[str]:
        return [a[0] for a in self.alerts]


@dataclass
class Queue:
    calls: list[tuple[datetime, datetime, UUID | None]] = field(default_factory=list)
    open_for: set[UUID] = field(default_factory=set)

    def queue_inventory(
        self, now: datetime, pickup_by: datetime, agent_id: UUID | None = None
    ) -> list[UUID]:
        self.calls.append((now, pickup_by, agent_id))
        if agent_id is None or agent_id in self.open_for:
            return []
        self.open_for.add(agent_id)
        return [uuid4()]


def agent_row(**over: Any) -> AgentRow:
    values: dict[str, Any] = {
        "agent_id": uuid4(),
        "machine_id": "a" * 32,
        "hostname": "host-1",
        "agent_version": "1.0.0",
        "token_hash": token_hash(new_agent_token(AgentTokenKind.AGENT)),
        "token_issued_at": NOW - timedelta(days=10),
        "token_expires_at": NOW + timedelta(days=355),
        "token_revoked_at": None,
        "prev_token_hash": None,
        "prev_token_expires_at": None,
        "last_rotation_at": None,
        "status": "online",
        "last_heartbeat_at": NOW - timedelta(minutes=1),
        "last_inventory_at": None,
        "last_seen_ip": "10.0.0.1",
        "runner_helpers": [],
        "enrolled_at": NOW - timedelta(days=10),
    } | over
    return AgentRow(**values)


# ------------------------------------------------------------------ enrol


@dataclass
class EnrolAgents:
    by_machine: dict[str, AgentRow] = field(default_factory=dict)
    inserted: list[dict[str, Any]] = field(default_factory=list)
    ips: list[tuple[UUID, str, datetime]] = field(default_factory=list)
    lose_insert_to: AgentRow | None = None  # a concurrent first enrolment

    def find_by_machine_id(
        self, machine_id: str, *, lock: bool = False
    ) -> AgentRow | None:
        assert lock is True  # the agent row is locked for the decision
        return self.by_machine.get(machine_id)

    def insert(self, **kw: Any) -> UUID | None:
        if self.lose_insert_to is not None:
            self.by_machine[kw["machine_id"]] = self.lose_insert_to
            return None
        self.inserted.append(kw)
        return uuid4()

    def record_ip(self, agent_id: UUID, ip: str, now: datetime) -> None:
        self.ips.append((agent_id, ip, now))


@dataclass
class EnrolRequests:
    tokens: dict[str, UsedToken] = field(default_factory=dict)
    used: list[tuple[str, str, datetime]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def use_token(
        self, token_hash: str, source_ip: str, now: datetime
    ) -> UsedToken | None:
        self.used.append((token_hash, source_ip, now))
        return self.tokens.get(token_hash)

    def insert_request(self, **kw: Any) -> int:
        self.requests.append(kw)
        return 100 + len(self.requests)


@dataclass
class EnrolWorld:
    agents: EnrolAgents = field(default_factory=EnrolAgents)
    requests: EnrolRequests = field(default_factory=EnrolRequests)
    jobs: Queue = field(default_factory=Queue)
    settings: Settings = field(default_factory=Settings)
    audit: Audit = field(default_factory=Audit)
    clock: Clock = field(default_factory=Clock)
    hooks: list[Callable[[], None]] = field(default_factory=list)
    window: SlidingCount[int] = field(init=False)

    def __post_init__(self) -> None:
        self.window = SlidingCount(
            self.clock, timedelta(minutes=60), timedelta(hours=1), 50
        )

    def token(self, auto: bool, token_id: int = 7) -> str:
        raw = new_agent_token(AgentTokenKind.ENROLMENT)
        self.requests.tokens[token_hash(raw)] = UsedToken(token_id, auto)
        return raw

    def enrol(self, bse: str, machine: str = "b" * 32) -> enrol_mod.Enrolled:
        body = enrol_mod.Enrolment("host-x", machine, "1.2.3", "Ubuntu 24.04.1 LTS")
        return enrol_mod.enrol(
            self.agents,
            self.requests,
            self.jobs,
            self.settings,
            self.audit,
            self.window,
            self.hooks.append,
            enrolment_token=bse,
            body=body,
            source_ip="10.1.2.3",
            now=self.clock.now(),
        )

    def commit(self) -> None:
        for hook in self.hooks:
            hook()
        self.hooks.clear()


def test_enrol_refused_token_changes_nothing() -> None:
    """TS §3.2 L183, #59: unknown, expired, revoked, exhausted and outside-CIDR
    all arrive as no used token: one refusal, nothing written."""
    w = EnrolWorld()
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    with pytest.raises(enrol_mod.EnrolRefused):
        w.enrol(bse)
    assert w.requests.used == [(token_hash(bse), "10.1.2.3", NOW)]
    assert w.agents.inserted == [] and w.requests.requests == []
    assert w.audit.entries == [] and w.jobs.calls == [] and w.agents.ips == []


def test_enrol_auto_approved_new_host() -> None:
    """TS §3.2 L184, #36: a new machine-id with auto_approve is enrolled at
    once, gets its first inventory job, and no request is held."""
    w = EnrolWorld()
    out = w.enrol(w.token(auto=True))
    assert out.status == "enrolled" and is_bsa(out.agent_token)
    assert (out.issued_at, out.expires_at) == (NOW, NOW + timedelta(days=365))
    [row] = w.agents.inserted
    assert row["status"] == "enrolled"
    assert row["token_hash"] == hashlib.sha256(out.agent_token.encode()).hexdigest()
    assert out.agent_token not in repr(row)
    assert (row["issued_at"], row["expires_at"]) == (out.issued_at, out.expires_at)
    assert w.jobs.calls == [(NOW, NOW + PICKUP_WINDOW, out.agent_id)]
    assert w.requests.requests == []
    assert w.agents.ips == [(out.agent_id, "10.1.2.3", NOW)]
    actor = f"agent:{out.agent_id}"
    assert w.audit.entries == [
        (
            actor,
            "agent.enrol",
            actor,
            {"token_id": 7, "kind": "new", "status": "enrolled", "request_id": None},
        )
    ]


def test_enrol_held_new_host() -> None:
    """TS §3.2 L185: without auto_approve the new agent awaits approval,
    holding the token hash, with one kind 'new' request; no job yet."""
    w = EnrolWorld()
    out = w.enrol(w.token(auto=False))
    assert out.status == "awaiting_approval"
    [row] = w.agents.inserted
    assert row["status"] == "awaiting_approval"
    [req] = w.requests.requests
    digest = token_hash(out.agent_token)
    assert (req["kind"], req["agent_id"], req["token_id"]) == ("new", out.agent_id, 7)
    assert req["new_token_hash"] == digest == row["token_hash"]
    assert req["token_expires_at"] == out.expires_at
    assert (req["hostname"], req["machine_id"], req["source_ip"]) == (
        "host-x",
        "b" * 32,
        "10.1.2.3",
    )
    assert w.jobs.calls == []
    assert w.audit.entries[0][3] == {
        "token_id": 7,
        "kind": "new",
        "status": "awaiting_approval",
        "request_id": 101,
    }


@pytest.mark.parametrize("auto", [True, False])
def test_enrol_known_machine_id_is_always_held(auto: bool) -> None:
    """TS §3.2 L184-L186, #64: a re-enrolment is held even with auto_approve;
    the existing agent_id is returned, its row unchanged, the new hash only
    in the request, no source IP recorded on it."""
    w = EnrolWorld()
    existing = agent_row(machine_id="c" * 32)
    w.agents.by_machine["c" * 32] = existing
    out = w.enrol(w.token(auto=auto), machine="c" * 32)
    assert out.status == "awaiting_approval" and out.agent_id == existing.agent_id
    assert w.agents.inserted == [] and w.agents.ips == [] and w.jobs.calls == []
    [req] = w.requests.requests
    assert req["kind"] == "reenrol" and req["agent_id"] == existing.agent_id
    assert req["new_token_hash"] == token_hash(out.agent_token)
    assert req["new_token_hash"] != existing.token_hash
    assert w.audit.entries[0][3]["kind"] == "reenrol"


def test_enrol_lost_insert_race_becomes_a_reenrolment() -> None:
    """Two first enrolments of one machine-id: the loser is held as a
    re-enrolment of the winner's row."""
    w = EnrolWorld()
    winner = agent_row(machine_id="b" * 32)
    w.agents.lose_insert_to = winner
    out = w.enrol(w.token(auto=True))
    assert (out.agent_id, out.status) == (winner.agent_id, "awaiting_approval")
    assert [r["kind"] for r in w.requests.requests] == ["reenrol"]
    assert w.jobs.calls == []


def test_enrol_ttl_comes_from_the_setting() -> None:
    w = EnrolWorld()
    w.settings.values["agent_token_ttl_days"] = 60
    out = w.enrol(w.token(auto=True))
    assert out.expires_at == NOW + timedelta(days=60)


def test_enrolments_per_hour_alert_once_marked_on_commit() -> None:
    """#61: every successful enrolment counts, sliding 60 min per token; the
    enrolment above the setting alerts, at most once per token per hour, and
    the hour is taken only when the alert commits."""
    w = EnrolWorld()
    w.settings.values["enrolment_alert_per_hour"] = 3
    bse = w.token(auto=True, token_id=9)
    for i in range(3):
        w.enrol(bse, machine=f"{i:032x}")
        w.commit()
    assert w.audit.alerts == []
    fourth = w.enrol(bse, machine=f"{4:032x}")
    [alert] = w.audit.alerts
    actor = f"agent:{fourth.agent_id}"
    assert alert == (
        "enrolments_per_hour",
        actor,
        "alert.enrolments_per_hour",
        "enrollment_token:9",
        {"over_per_hour": 3},
    )
    w.hooks.clear()  # the alert's transaction rolled back: the hour stays free
    w.enrol(bse, machine=f"{5:032x}")
    assert len(w.audit.alerts) == 2
    w.commit()
    w.enrol(bse, machine=f"{6:032x}")
    w.commit()
    assert len(w.audit.alerts) == 2  # once per token per hour
    other = w.token(auto=True, token_id=10)
    for i in range(3):
        w.enrol(other, machine=f"{20 + i:032x}")
    assert len(w.audit.alerts) == 2  # counted per token


# --------------------------------------------------------- enrolment tokens


@dataclass
class TokenStore:
    rows: dict[int, EnrolmentTokenRow] = field(default_factory=dict)
    hashes: dict[int, str] = field(default_factory=dict)
    inserted: list[dict[str, Any]] = field(default_factory=list)
    revoke_changes: bool = True

    def insert_token(self, **kw: Any) -> int:
        self.inserted.append(kw)
        token_id = len(self.rows) + 1
        self.hashes[token_id] = kw["token_hash"]
        self.rows[token_id] = EnrolmentTokenRow(
            token_id,
            kw["max_uses"],
            0,
            kw["auto_approve"],
            kw["allowed_cidrs"],
            kw["expires_at"],
            None,
            kw["created_by"],
            kw["now"],
        )
        return token_id

    def revoke_active_token(self, token_id: int, now: datetime) -> bool:
        row = self.rows[token_id]
        if row.revoked_at is not None or not self.revoke_changes:
            return False
        self.rows[token_id] = replace(row, revoked_at=now)
        return True

    def get_token(self, token_id: int) -> EnrolmentTokenRow | None:
        return self.rows.get(token_id)

    def token_page(self, limit: int, after_id: int | None) -> list[EnrolmentTokenRow]:
        return list(self.rows.values())[:limit]


def create(store: TokenStore, audit: Audit, **over: Any) -> tokens_mod.CreatedToken:
    kw: dict[str, Any] = {
        "admin_id": 3,
        "max_uses": 1,
        "expires_in_hours": 24,
        "allowed_cidrs": None,
        "auto_approve": False,
        "now": NOW,
    } | over
    return tokens_mod.create_token(store, audit, **kw)


def test_create_token_stores_only_the_hash_and_audits() -> None:
    """TS §3.2 L181, §6.2 L1083: a bse_ shown once, only its SHA-256 stored,
    expiry = now + hours; one enrollment_token.create entry."""
    store, audit = TokenStore(), Audit()
    made = create(store, audit, max_uses=25, expires_in_hours=48)
    assert made.token.startswith("bse_") and len(made.token) == BSA_LEN
    [kw] = store.inserted
    assert kw["token_hash"] == hashlib.sha256(made.token.encode()).hexdigest()
    assert made.token not in repr(kw) and made.token not in repr(made.row)
    assert (kw["max_uses"], kw["created_by"]) == (25, 3)
    assert kw["expires_at"] == NOW + timedelta(hours=48)
    assert made.row.token_id == 1 and made.row.uses == 0
    assert audit.alerts == []
    assert audit.entries == [
        (
            "user:3",
            "enrollment_token.create",
            "enrollment_token:1",
            {
                "max_uses": 25,
                "auto_approve": False,
                "allowed_cidrs": None,
                "expires_at": (NOW + timedelta(hours=48)).isoformat(),
            },
        )
    ]


@pytest.mark.parametrize(
    ("auto", "uses", "risky"),
    [
        (True, 1, {"auto_approve": True, "over_100_uses": False}),
        (False, 101, {"auto_approve": False, "over_100_uses": True}),
        (True, 10000, {"auto_approve": True, "over_100_uses": True}),
        (False, 100, None),
    ],
)
def test_risky_tokens_alert_instead_of_a_plain_entry(
    auto: bool, uses: int, risky: dict[str, bool] | None
) -> None:
    """TS §3.2 L181, #71: auto_approve or more than 100 uses: the create
    entry is one enrolment_token_risky alert (one entry per event)."""
    store, audit = TokenStore(), Audit()
    create(store, audit, auto_approve=auto, max_uses=uses)
    if risky is None:
        assert audit.alerts == [] and len(audit.entries) == 1
        return
    assert audit.entries == []
    [(kind, actor, action, target, detail)] = audit.alerts
    assert (kind, actor, action, target) == (
        "enrolment_token_risky",
        "user:3",
        "enrollment_token.create",
        "enrollment_token:1",
    )
    assert detail["risky"] == risky and detail["max_uses"] == uses


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        (["10.20.0.0/16"], ["10.20.0.0/16"]),
        (["127.0.0.0/8", "::1/128"], ["127.0.0.0/8", "::1/128"]),
        (["2001:DB8::/32"], ["2001:db8::/32"]),
        (["192.0.2.7"], ["192.0.2.7/32"]),
    ],
)
def test_cidrs_are_stored_in_canonical_form(
    given: list[str], stored: list[str]
) -> None:
    store, audit = TokenStore(), Audit()
    create(store, audit, allowed_cidrs=given)
    assert store.inserted[0]["allowed_cidrs"] == stored


@pytest.mark.parametrize(
    "bad",
    [
        [],
        ["10.20.0.1/16"],  # host bits set
        ["fe80::/10%eth0"],
        ["fe80::1%eth0"],
        ["not-a-network"],
        ["10.0.0.0/33"],
        [f"10.0.{i}.0/24" for i in range(65)],
    ],
)
def test_bad_cidrs_refuse_before_anything_is_written(bad: list[str]) -> None:
    store, audit = TokenStore(), Audit()
    with pytest.raises(tokens_mod.InvalidCidrs):
        create(store, audit, allowed_cidrs=bad)
    assert store.inserted == [] and audit.entries == [] and audit.alerts == []


def test_sixty_four_cidrs_are_accepted() -> None:
    store, audit = TokenStore(), Audit()
    create(store, audit, allowed_cidrs=[f"10.0.{i}.0/24" for i in range(64)])
    assert len(store.inserted[0]["allowed_cidrs"]) == 64


def test_revoke_token_once_and_keeps_the_row() -> None:
    """REQ-067: delete revokes and keeps the row; a repeat or a lost race
    writes no second entry; an unknown id is not found."""
    store, audit = TokenStore(), Audit()
    create(store, audit)
    audit.entries.clear()
    later = NOW + timedelta(minutes=5)
    assert tokens_mod.revoke_token(store, audit, admin_id=4, token_id=1, now=later)
    assert store.rows[1].revoked_at == later
    assert audit.entries == [
        ("user:4", "enrollment_token.revoke", "enrollment_token:1", {})
    ]
    assert tokens_mod.revoke_token(store, audit, admin_id=4, token_id=1, now=NOW)
    assert store.rows[1].revoked_at == later and len(audit.entries) == 1
    assert not tokens_mod.revoke_token(store, audit, admin_id=4, token_id=99, now=NOW)
    assert len(audit.entries) == 1


def test_create_with_a_missing_row_fails_loudly() -> None:
    class Lossy(TokenStore):
        def get_token(self, token_id: int) -> EnrolmentTokenRow | None:
            return None

    with pytest.raises(RuntimeError):
        create(Lossy(), Audit())


# ------------------------------------------------------- enrolment requests


def request_row(agent_id: UUID, kind: str = "new", **over: Any) -> RequestRow:
    values: dict[str, Any] = {
        "request_id": 5,
        "kind": kind,
        "agent_id": agent_id,
        "enrollment_token_id": 7,
        "hostname": "host-new",
        "machine_id": "d" * 32,
        "os_pretty_name": "Debian GNU/Linux 12",
        "agent_version": "1.4.0",
        "new_token_hash": "f" * 64,
        "token_expires_at": NOW + timedelta(days=365),
        "source_ip": "10.1.2.3",
        "requested_at": NOW - timedelta(minutes=5),
        "decision": None,
        "decided_by": None,
        "decided_at": None,
    } | over
    return RequestRow(**values)


@dataclass
class RequestStore:
    row: RequestRow | None
    decide_ok: bool = True
    decided: list[tuple[int, str, int, datetime]] = field(default_factory=list)

    def get_request_for_update(self, request_id: int) -> RequestRow | None:
        if self.row is None or self.row.request_id != request_id:
            return None
        return self.row

    def decide(
        self, request_id: int, decision: str, decided_by: int, now: datetime
    ) -> bool:
        self.decided.append((request_id, decision, decided_by, now))
        if not self.decide_ok or self.row is None:
            return False
        self.row = replace(
            self.row, decision=decision, decided_by=decided_by, decided_at=now
        )
        return True

    def request_page(
        self, state: str, limit: int, after_id: int | None
    ) -> list[RequestRow]:
        return [] if self.row is None else [self.row]

    def matches(self, request: RequestRow) -> list[MatchRow]:
        return [MatchRow(uuid4(), request.hostname, request.machine_id, "online")]


@dataclass
class DecisionAgents:
    row: AgentRow | None
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        assert lock is True
        return self.row

    def set_status(
        self, agent_id: UUID, status: str, only_from: tuple[str, ...]
    ) -> bool:
        self.calls.append(("status", agent_id, status, only_from))
        return True

    def revoke(self, agent_id: UUID, now: datetime) -> bool:
        self.calls.append(("revoke", agent_id, now))
        return True

    def relink(self, agent_id: UUID, **kw: Any) -> bool:
        self.calls.append(("relink", agent_id, kw))
        return True


def decide(
    store: RequestStore, agents: DecisionAgents, jobs: Queue, audit: Audit, **kw: Any
) -> requests_mod.RequestView:
    args: dict[str, Any] = {"request_id": 5, "admin_id": 2, "now": NOW} | kw
    return requests_mod.decide_request(store, agents, jobs, audit, **args)


def test_approve_new_enrols_and_queues_the_first_job() -> None:
    """TS §3.2 L187, #36: approving a new request enrols the agent (only
    from awaiting_approval) and queues its first inventory job."""
    a = agent_row(status="awaiting_approval")
    store, agents, jobs, audit = (
        RequestStore(request_row(a.agent_id)),
        DecisionAgents(a),
        Queue(),
        Audit(),
    )
    view = decide(store, agents, jobs, audit, approve=True)
    assert agents.calls == [("status", a.agent_id, "enrolled", ("awaiting_approval",))]
    assert jobs.calls == [(NOW, NOW + PICKUP_WINDOW, a.agent_id)]
    assert store.decided == [(5, "approved", 2, NOW)]
    assert audit.alerts == []
    assert audit.entries == [
        (
            "user:2",
            "enrollment_request.approve",
            "enrollment_request:5",
            {"kind": "new", "agent_id": str(a.agent_id)},
        )
    ]
    assert view.request.decision == "approved" and len(view.matches) == 1


@pytest.mark.parametrize(
    ("kind", "status"), [("reenrol", "online"), ("new", "enrolled")]
)
def test_approve_reenrolment_relinks_and_alerts(kind: str, status: str) -> None:
    """TS §3.2 L187, #64: the existing row takes the request's token, times,
    hostname and version; the entry is a reenrolment_approved alert; a 'new'
    request whose agent was enrolled meanwhile is decided the same way."""
    a = agent_row(status=status)
    req = request_row(a.agent_id, kind)
    store, agents, jobs, audit = RequestStore(req), DecisionAgents(a), Queue(), Audit()
    decide(store, agents, jobs, audit, approve=True)
    assert agents.calls == [
        (
            "relink",
            a.agent_id,
            {
                "token_hash": req.new_token_hash,
                "issued_at": req.requested_at,
                "expires_at": req.token_expires_at,
                "hostname": "host-new",
                "agent_version": "1.4.0",
            },
        )
    ]
    assert audit.entries == []
    assert [x[:4] for x in audit.alerts] == [
        (
            "reenrolment_approved",
            "user:2",
            "enrollment_request.approve",
            "enrollment_request:5",
        )
    ]
    assert jobs.calls == [(NOW, NOW + PICKUP_WINDOW, a.agent_id)]


def test_reject_new_decommissions_and_revokes() -> None:
    """TS §3.2 L188: a rejected new agent is decommissioned (never deleted)
    and its token revoked; no job."""
    a = agent_row(status="awaiting_approval")
    store, agents, jobs, audit = (
        RequestStore(request_row(a.agent_id)),
        DecisionAgents(a),
        Queue(),
        Audit(),
    )
    decide(store, agents, jobs, audit, approve=False)
    assert agents.calls == [
        ("status", a.agent_id, "decommissioned", ("awaiting_approval",)),
        ("revoke", a.agent_id, NOW),
    ]
    assert jobs.calls == [] and store.decided == [(5, "rejected", 2, NOW)]
    assert [e[1] for e in audit.entries] == ["enrollment_request.reject"]


def test_reject_reenrolment_leaves_the_agent_alone() -> None:
    """#26: the existing agent row and its old token stay as they were."""
    a = agent_row()
    store = RequestStore(request_row(a.agent_id, "reenrol"))
    agents, jobs, audit = DecisionAgents(a), Queue(), Audit()
    decide(store, agents, jobs, audit, approve=False)
    assert agents.calls == [] and jobs.calls == []
    assert store.decided == [(5, "rejected", 2, NOW)]


def test_an_expired_request_token_can_be_rejected_not_approved() -> None:
    """#64 (e): approval of an expired request token is a conflict."""
    a = agent_row(status="awaiting_approval")
    expired = request_row(a.agent_id, token_expires_at=NOW)
    store, agents, jobs, audit = (
        RequestStore(expired),
        DecisionAgents(a),
        Queue(),
        Audit(),
    )
    with pytest.raises(requests_mod.RequestConflict):
        decide(store, agents, jobs, audit, approve=True)
    assert agents.calls == [] and store.decided == [] and audit.entries == []
    decide(store, agents, jobs, audit, approve=False)
    assert store.decided[0][1] == "rejected"


def test_decided_twice_or_concurrently_is_a_conflict() -> None:
    a = agent_row(status="awaiting_approval")
    done = request_row(a.agent_id, decision="approved", decided_by=1, decided_at=NOW)
    store, agents, jobs, audit = RequestStore(done), DecisionAgents(a), Queue(), Audit()
    for approve in (True, False):
        with pytest.raises(requests_mod.RequestConflict):
            decide(store, agents, jobs, audit, approve=approve)
    assert agents.calls == [] and audit.entries == []
    racing = RequestStore(request_row(a.agent_id), decide_ok=False)
    with pytest.raises(requests_mod.RequestConflict):
        decide(racing, DecisionAgents(a), Queue(), Audit(), approve=True)


def test_unknown_request_or_agent_is_not_found() -> None:
    a = agent_row()
    with pytest.raises(requests_mod.RequestNotFound):
        decide(RequestStore(None), DecisionAgents(a), Queue(), Audit(), approve=True)
    with pytest.raises(requests_mod.RequestNotFound):
        decide(
            RequestStore(request_row(a.agent_id)),
            DecisionAgents(None),
            Queue(),
            Audit(),
            approve=True,
        )


def test_list_requests_carries_the_matches() -> None:
    """TS §3.2 L192: each request comes with the agents sharing its hostname
    or machine-id."""
    a = agent_row()
    views = requests_mod.list_requests(
        RequestStore(request_row(a.agent_id)), "pending", 50, None
    )
    assert len(views) == 1
    assert [(m.hostname, m.machine_id) for m in views[0].matches] == [
        ("host-new", "d" * 32)
    ]


# ------------------------------------------------------------------ rotation


@dataclass
class RotationAgents:
    row: AgentRow | None
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        assert lock is True
        return self.row

    def rotate(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool:
        self.calls.append(("rotate", new_hash, issued_at, expires_at))
        return True

    def replace_unused_token(
        self, agent_id: UUID, new_hash: str, issued_at: datetime, expires_at: datetime
    ) -> bool:
        self.calls.append(("replace", new_hash, issued_at, expires_at))
        return True

    def revoke(self, agent_id: UUID, now: datetime) -> bool:
        self.calls.append(("revoke", now))
        return True


def in_window(**over: Any) -> AgentRow:
    """A 365-day token issued 336 days ago: inside its window (335 days)."""
    return agent_row(
        token_issued_at=NOW - timedelta(days=336),
        token_expires_at=NOW + timedelta(days=29),
        **over,
    )


def rotate(
    row: AgentRow | None,
    *,
    via: str = "current",
    presented: AgentRow | None = None,
    ip_last_seen: datetime | None = NOW - timedelta(hours=1),
    settings: Settings | None = None,
) -> tuple[RotationAgents, Audit, rotation_mod.Rotated | rotation_mod.RotationRefused]:
    agents, audit = RotationAgents(row), Audit()
    shown = presented or row or agent_row()
    caller = AgentCaller(shown.agent_id, via, shown)  # type: ignore[arg-type]
    try:
        out: Any = rotation_mod.rotate_token(
            agents,
            settings or Settings(),
            audit,
            caller=caller,
            ip_last_seen=ip_last_seen,
            now=NOW,
        )
    except rotation_mod.RotationRefused as exc:
        out = exc
    return agents, audit, out


@pytest.mark.parametrize(
    ("ttl_days", "opens_after"),
    [(365, 335), (60, 30), (730, 700), (100, 70), (50, 25)],
)
def test_window_opens_at_max_of_ttl_minus_30_days_and_half(
    ttl_days: int, opens_after: int
) -> None:
    """TS §3.2 L190: issued_at + max(TTL - 30 d, TTL / 2)."""
    issued = NOW - timedelta(days=400)
    expires = issued + timedelta(days=ttl_days)
    assert rotation_mod.window_opens(issued, expires) == issued + timedelta(
        days=opens_after
    )


def test_rotation_inside_the_window() -> None:
    """A fresh bsa_ for the current TTL setting, only its hash stored, one
    agent.token_rotate entry; no alert from a recently seen IP."""
    s = Settings()
    s.values["agent_token_ttl_days"] = 90
    agents, audit, out = rotate(in_window(), settings=s)
    assert isinstance(out, rotation_mod.Rotated) and is_bsa(out.agent_token)
    assert (out.issued_at, out.expires_at) == (NOW, NOW + timedelta(days=90))
    assert agents.calls == [
        ("rotate", token_hash(out.agent_token), NOW, out.expires_at)
    ]
    assert [e[1:] for e in audit.entries] == [
        ("agent.token_rotate", f"agent:{agents.row.agent_id}", {"retry": False})  # type: ignore[union-attr]
    ]
    assert audit.alerts == []


def test_rotation_before_the_window_is_403_and_alerts() -> None:
    row = agent_row()  # issued 10 days ago
    agents, audit, out = rotate(row)
    assert isinstance(out, rotation_mod.RotationRefused)
    assert (out.status, out.type) == (403, "forbidden")
    assert agents.calls == [] and audit.entries == []
    opens = rotation_mod.window_opens(row.token_issued_at, row.token_expires_at)
    assert audit.alerts == [
        (
            "rotation_outside_window",
            f"agent:{row.agent_id}",
            "alert.rotation_outside_window",
            f"agent:{row.agent_id}",
            {"window_opens": opens.isoformat()},
        )
    ]


def test_rotation_one_second_before_the_window_is_refused() -> None:
    row = agent_row(
        token_issued_at=NOW - timedelta(days=335) + timedelta(seconds=1),
        token_expires_at=NOW + timedelta(days=30) + timedelta(seconds=1),
    )
    _, _, out = rotate(row)
    assert isinstance(out, rotation_mod.RotationRefused) and out.status == 403
    exact = agent_row(
        token_issued_at=NOW - timedelta(days=335),
        token_expires_at=NOW + timedelta(days=30),
    )
    _, _, ok = rotate(exact)
    assert isinstance(ok, rotation_mod.Rotated)


def test_revoked_or_missing_agent_is_401() -> None:
    for row in (None, in_window(token_revoked_at=NOW - timedelta(seconds=1))):
        agents, audit, out = rotate(row, presented=agent_row())
        assert isinstance(out, rotation_mod.RotationRefused)
        assert (out.status, out.type) == (401, "token_revoked")
        assert agents.calls == [] and audit.entries == [] and audit.alerts == []


def test_second_used_rotation_within_24_hours_is_429() -> None:
    """#62, TASK-075 r1: a rotation whose new token was used counts; 429 with
    Retry-After to the end of the 24 h, checked before the window, no alert."""
    row = in_window(
        last_rotation_at=NOW - timedelta(hours=23),
        prev_token_expires_at=NOW - timedelta(hours=22),
    )
    agents, audit, out = rotate(row)
    assert isinstance(out, rotation_mod.RotationRefused)
    assert (out.status, out.type) == (429, "rate_limited")
    assert out.headers == {"Retry-After": str(3600)}
    assert agents.calls == [] and audit.alerts == [] and audit.entries == []
    early = agent_row(
        last_rotation_at=NOW - timedelta(hours=1),
        prev_token_expires_at=NOW - timedelta(minutes=50),
    )
    _, audit2, out2 = rotate(early)
    assert isinstance(out2, rotation_mod.RotationRefused) and out2.status == 429
    assert audit2.alerts == []  # 24 h rule before the window check


def test_unused_or_old_rotations_do_not_count() -> None:
    unused = in_window(last_rotation_at=NOW - timedelta(hours=1))
    _, _, out = rotate(unused)
    assert isinstance(out, rotation_mod.Rotated)
    old = in_window(
        last_rotation_at=NOW - timedelta(hours=24),
        prev_token_expires_at=NOW - timedelta(hours=23),
    )
    _, _, out2 = rotate(old)
    assert isinstance(out2, rotation_mod.Rotated)


def test_lost_response_retry_replaces_the_unused_token() -> None:
    """TS §3.2 L190: the old token retries; a fresh token replaces the
    unused one; an entry with retry true."""
    row = in_window(
        prev_token_hash="1" * 64, last_rotation_at=NOW - timedelta(minutes=2)
    )
    agents, audit, out = rotate(row, via="previous")
    assert isinstance(out, rotation_mod.Rotated)
    assert agents.calls == [
        ("replace", token_hash(out.agent_token), NOW, NOW + timedelta(days=365))
    ]
    assert [e[3] for e in audit.entries] == [{"retry": True}]
    assert audit.alerts == []


def test_concurrent_rotation_while_waiting_is_a_retry() -> None:
    """TASK-075 r2: the presented current token became the previous one
    while this call waited for the row lock (new token unused)."""
    presented = in_window()
    row = replace(presented, token_hash="2" * 64, prev_token_hash=presented.token_hash)
    agents, audit, out = rotate(row, presented=presented)
    assert isinstance(out, rotation_mod.Rotated)
    assert agents.calls[0][0] == "replace" and audit.alerts == []


def test_old_token_after_the_new_one_was_used_revokes_both() -> None:
    """TS §3.2 L190, #62: reuse revokes both tokens and alerts token_reuse."""
    row = in_window(
        prev_token_hash="1" * 64, prev_token_expires_at=NOW + timedelta(minutes=5)
    )
    agents, audit, out = rotate(row, via="previous")
    assert isinstance(out, rotation_mod.RotationRefused)
    assert (out.status, out.type) == (401, "token_revoked")
    assert agents.calls == [("revoke", NOW)]
    assert [a[0] for a in audit.alerts] == ["token_reuse"]
    assert audit.alerts[0][4] == {"via": "rotate"}


@pytest.mark.parametrize(
    ("seen", "alerts"),
    [
        (None, True),
        (NOW - timedelta(days=8), True),
        (NOW - timedelta(days=7, seconds=1), True),
        (NOW - timedelta(days=7), False),
        (NOW - timedelta(days=6), False),
    ],
)
def test_rotation_from_an_ip_not_seen_for_7_days_alerts(
    seen: datetime | None, alerts: bool
) -> None:
    _, audit, out = rotate(in_window(), ip_last_seen=seen)
    assert isinstance(out, rotation_mod.Rotated)
    assert audit.kinds() == (["rotation_new_ip"] if alerts else [])
    if alerts:
        want = None if seen is None else seen.isoformat()
        assert audit.alerts[0][4] == {"ip_last_seen": want}
    _, audit2, _ = rotate(
        in_window(prev_token_hash="1" * 64), via="previous", ip_last_seen=seen
    )
    assert audit2.kinds() == (["rotation_new_ip"] if alerts else [])
