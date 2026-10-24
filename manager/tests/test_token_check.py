"""TASK-059: the agent token check service (fake repositories, fake clock).

Checks CHK-M3-120 to CHK-M3-127 of tests/m3/test-plan.md (TP-M3-13). Expected
values: the outcome table of work/plans/TASK-059.md, #59 (statuses, types,
order; every 401 counts, 403 does not), #62 (overlap until 10 min after the new
token's first use; after that, revoke both and alert token_reuse), #63 (missing
or malformed header = mismatch; a pending request's token: alert only), #26
(rejected re-enrolment), TS §3.2 L185-L191, REQ-064 (1)-(8), REQ-087 (no token
in logs or errors), #71 (alert kinds and actions).
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
)
from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.enrolment import RequestRow
from bitscan_manager.services.enrolment.token_check import (
    OVERLAP,
    AgentCaller,
    AgentTokenRefused,
    check_agent_token,
)

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
MIN = timedelta(minutes=1)
MACHINE = "0123456789abcdef0123456789abcdef"


def h(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def agent_row(token: str, **kw: Any) -> AgentRow:
    base: dict[str, Any] = {
        "agent_id": uuid4(),
        "machine_id": MACHINE,
        "hostname": "web-01",
        "agent_version": "1.0.0",
        "token_hash": h(token),
        "token_issued_at": T0 - timedelta(days=10),
        "token_expires_at": T0 + timedelta(days=355),
        "token_revoked_at": None,
        "prev_token_hash": None,
        "prev_token_expires_at": None,
        "last_rotation_at": None,
        "status": "online",
        "last_heartbeat_at": T0 - MIN,
        "last_inventory_at": None,
        "last_seen_ip": "192.0.2.1",
        "runner_helpers": [],
        "enrolled_at": T0 - timedelta(days=10),
    }
    if kw.get("prev_token_hash") is not None and "last_rotation_at" not in kw:
        # rotate() always sets last_rotation_at with prev_token_hash
        base["last_rotation_at"] = T0 - timedelta(days=1)
    base.update(kw)
    return AgentRow(**base)


def request_row(token: str, agent_id: UUID, **kw: Any) -> RequestRow:
    base: dict[str, Any] = {
        "request_id": 7,
        "kind": "reenrol",
        "agent_id": agent_id,
        "enrollment_token_id": 1,
        "hostname": "web-01",
        "machine_id": MACHINE,
        "os_pretty_name": None,
        "agent_version": "1.0.0",
        "new_token_hash": h(token),
        "token_expires_at": T0 + timedelta(days=365),
        "source_ip": "192.0.2.1",
        "requested_at": T0 - MIN,
        "decision": None,
        "decided_by": None,
        "decided_at": None,
    }
    base.update(kw)
    return RequestRow(**base)


@dataclass
class Fakes:
    agents: list[AgentRow] = field(default_factory=list)
    requests: list[RequestRow] = field(default_factory=list)
    rejected_new: set[UUID] = field(default_factory=set)
    revoked: list[tuple[UUID, datetime]] = field(default_factory=list)
    marked: list[tuple[UUID, datetime]] = field(default_factory=list)
    alerts: list[tuple[str, str, str, str, dict[str, object]]] = field(
        default_factory=list
    )
    lookups: int = 0

    # AgentLookup
    def find_by_token_hash(self, token_hash: str) -> AgentRow | None:
        self.lookups += 1
        return next((a for a in self.agents if a.token_hash == token_hash), None)

    def find_by_prev_hash(self, token_hash: str) -> AgentRow | None:
        self.lookups += 1
        return next((a for a in self.agents if a.prev_token_hash == token_hash), None)

    def revoke(self, agent_id: UUID, now: datetime) -> bool:
        self.revoked.append((agent_id, now))
        return True

    def mark_new_token_used(self, agent_id: UUID, overlap_until: datetime) -> bool:
        self.marked.append((agent_id, overlap_until))
        return True

    # RequestLookup
    def find_by_new_token_hash(self, token_hash: str) -> RequestRow | None:
        self.lookups += 1
        return next((r for r in self.requests if r.new_token_hash == token_hash), None)

    def rejected_new_for_agent(self, agent_id: UUID) -> bool:
        return agent_id in self.rejected_new

    # Alerter
    def alert(
        self, kind: str, actor: str, action: str, target: str, detail: Any
    ) -> None:
        self.alerts.append((kind, actor, action, target, dict(detail)))


def run(
    f: Fakes, raw: str | None, header: str | None = MACHINE, now: datetime = T0
) -> AgentCaller:
    return check_agent_token(f, f, f, raw=raw, machine_id_header=header, now=now)


def refused(
    f: Fakes, raw: str | None, header: str | None = MACHINE, now: datetime = T0
) -> AgentTokenRefused:
    with pytest.raises(AgentTokenRefused) as exc:
        run(f, raw, header, now)
    return exc.value


def tok() -> str:
    return new_agent_token(AgentTokenKind.AGENT)


def no_side_effects(f: Fakes) -> None:
    assert (f.revoked, f.marked, f.alerts) == ([], [], [])


# ------------------------------------------------------------ CHK-M3-120: table rows


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        new_agent_token(AgentTokenKind.ENROLMENT),
        new_token(TokenKind.SESSION),
        new_token(TokenKind.API),
        "bsa_short",
        "Bearer bsa_" + "A" * 43,
    ],
    ids=["none", "empty", "bse", "bsu", "bsk", "short", "with-scheme"],
)
def test_malformed_or_wrong_prefix_is_401_without_lookup(raw: str | None) -> None:
    f = Fakes()
    e = refused(f, raw)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "unauthorized",
        True,
        None,
    )
    assert f.lookups == 0
    no_side_effects(f)


def test_unknown_token_is_401() -> None:
    f = Fakes(agents=[agent_row(tok())])
    e = refused(f, tok())
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "unauthorized",
        True,
        None,
    )
    no_side_effects(f)


def test_normal_current_token_is_accepted() -> None:
    t = tok()
    a = agent_row(t)
    f = Fakes(agents=[a])
    got = run(f, t)
    assert got == AgentCaller(a.agent_id, "current", a)
    no_side_effects(f)


def test_rejected_request_token() -> None:
    """Row 2, #26: 401 enrollment_rejected; the old agent row is untouched."""
    old, new = tok(), tok()
    a = agent_row(old)
    f = Fakes(agents=[a], requests=[request_row(new, a.agent_id, decision="rejected")])
    e = refused(f, new)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "enrollment_rejected",
        True,
        a.agent_id,
    )
    no_side_effects(f)
    assert run(f, old).agent_id == a.agent_id  # the old token still works


def test_approved_request_whose_token_was_replaced_is_unknown() -> None:
    new = tok()
    f = Fakes(requests=[request_row(new, uuid4(), decision="approved")])
    e = refused(f, new)
    assert (e.status, e.type) == (401, "unauthorized")


def test_rejected_new_enrolment_agent() -> None:
    """Row 3, REQ-064 (4): decommissioned new agent whose request was rejected."""
    t = tok()
    a = agent_row(t, status="decommissioned", token_revoked_at=T0 - MIN)
    f = Fakes(agents=[a], rejected_new={a.agent_id})
    e = refused(f, t)
    assert (e.status, e.type, e.counted) == (401, "enrollment_rejected", True)
    no_side_effects(f)


def test_decommissioned_by_the_sweep_is_token_revoked() -> None:
    """REQ-064 (7)."""
    t = tok()
    a = agent_row(t, status="decommissioned", token_revoked_at=T0 - MIN)
    f = Fakes(agents=[a])
    e = refused(f, t)
    assert (e.status, e.type, e.counted) == (401, "token_revoked", True)
    no_side_effects(f)


@pytest.mark.parametrize("via", ["current", "previous"])
def test_revoked_row_refuses_current_and_previous(via: str) -> None:
    cur, prev = tok(), tok()
    a = agent_row(cur, prev_token_hash=h(prev), token_revoked_at=T0 - MIN)
    f = Fakes(agents=[a])
    e = refused(f, cur if via == "current" else prev)
    assert (e.status, e.type, e.agent_id) == (401, "token_revoked", a.agent_id)
    no_side_effects(f)


def test_expiry_boundary() -> None:
    """REQ-064 (5): accepted 1 s before token_expires_at, refused at it."""
    t = tok()
    a = agent_row(t, token_expires_at=T0)
    f = Fakes(agents=[a])
    assert run(f, t, now=T0 - SEC).agent_id == a.agent_id
    e = refused(f, t, now=T0)
    assert (e.status, e.type, e.counted) == (401, "token_expired", True)
    e = refused(f, t, now=T0 + timedelta(days=1))
    assert e.type == "token_expired"
    no_side_effects(f)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "f" * 32,
        MACHINE.upper(),
        MACHINE[:31],
        MACHINE + "0",
        "g" * 32,
        " " + MACHINE[1:],
        "01234567-89ab-cdef-0123-456789abcdef",
    ],
    ids=[
        "missing",
        "empty",
        "other",
        "upper",
        "31",
        "33",
        "non-hex",
        "space",
        "uuid-form",
    ],
)
def test_mismatch_revokes_and_alerts(header: str | None) -> None:
    """Row 6, REQ-064 (2), #63: missing or malformed counts as a mismatch."""
    t = tok()
    a = agent_row(t)
    f = Fakes(agents=[a])
    e = refused(f, t, header)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "machine_id_mismatch",
        True,
        a.agent_id,
    )
    assert f.revoked == [(a.agent_id, T0)]
    assert len(f.alerts) == 1
    kind, actor, action, target, detail = f.alerts[0]
    assert (kind, action) == ("machine_id_mismatch", "agent.machine_id_mismatch")
    assert actor == target == f"agent:{a.agent_id}"
    text = repr(detail)
    assert t not in text and h(t) not in text and (header or "\u0000") not in text
    assert f.marked == []


def test_after_a_mismatch_the_same_token_is_revoked() -> None:
    """REQ-064 (2): the revoke sticks (the repository sets token_revoked_at)."""
    t = tok()
    a = agent_row(t)
    f = Fakes(agents=[a])
    refused(f, t, "f" * 32)
    f.agents = [replace(a, token_revoked_at=T0)]
    e = refused(f, t, MACHINE, now=T0 + SEC)
    assert e.type == "token_revoked"
    assert len(f.alerts) == 1  # no second alert


def test_mismatch_on_the_previous_token_revokes_the_row() -> None:
    cur, prev = tok(), tok()
    a = agent_row(cur, prev_token_hash=h(prev))
    f = Fakes(agents=[a])
    e = refused(f, prev, "f" * 32)
    assert e.type == "machine_id_mismatch"
    assert f.revoked == [(a.agent_id, T0)]
    assert f.alerts[0][4] == {"via": "previous"}


def test_pending_request_mismatch_alerts_only() -> None:
    """Row 6b, #63: the request stays pending; no revoke (no state to set)."""
    new = tok()
    aid = uuid4()
    f = Fakes(requests=[request_row(new, aid)])
    e = refused(f, new, "f" * 32)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "machine_id_mismatch",
        True,
        aid,
    )
    assert f.revoked == []
    assert [(k, a) for k, _, a, _, _ in f.alerts] == [
        ("machine_id_mismatch", "agent.machine_id_mismatch")
    ]
    assert f.alerts[0][4] == {"via": "request"}


def test_previous_token_before_first_use_is_accepted() -> None:
    """Row 7: the new token unused (the lost-response retry may follow)."""
    cur, prev = tok(), tok()
    a = agent_row(cur, prev_token_hash=h(prev), prev_token_expires_at=None)
    f = Fakes(agents=[a])
    got = run(f, prev)
    assert (got.agent_id, got.via) == (a.agent_id, "previous")
    no_side_effects(f)


def test_previous_token_overlap_and_reuse() -> None:
    """Rows 8, 9, REQ-064 (via #62), REQ-071 (4): 9 min 59 s ok, 10 min reuse."""
    cur, prev = tok(), tok()
    used_at = T0
    a = agent_row(cur, prev_token_hash=h(prev), prev_token_expires_at=used_at + OVERLAP)
    assert OVERLAP == timedelta(minutes=10)
    f = Fakes(agents=[a])
    assert run(f, prev, now=used_at + OVERLAP - SEC).via == "previous"
    no_side_effects(f)
    e = refused(f, prev, now=used_at + OVERLAP)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "token_revoked",
        True,
        a.agent_id,
    )
    assert f.revoked == [(a.agent_id, used_at + OVERLAP)]
    assert [(x[0], x[2]) for x in f.alerts] == [("token_reuse", "agent.token_reuse")]
    # the current token is not refused by the check itself; the revoke ends it
    assert run(f, cur, now=used_at + OVERLAP).via == "current"


def test_pending_new_agent_is_403_not_counted() -> None:
    """Row 10, REQ-064 (8)."""
    t = tok()
    a = agent_row(t, status="awaiting_approval")
    f = Fakes(agents=[a])
    e = refused(f, t)
    assert (e.status, e.type, e.counted, e.agent_id) == (
        403,
        "pending_approval",
        False,
        a.agent_id,
    )
    no_side_effects(f)


def test_pending_reenrolment_token_is_403_and_old_token_works() -> None:
    """Row 11, REQ-064 (3)."""
    old, new = tok(), tok()
    a = agent_row(old)
    f = Fakes(agents=[a], requests=[request_row(new, a.agent_id)])
    e = refused(f, new)
    assert (e.status, e.type, e.counted) == (403, "pending_approval", False)
    assert run(f, old).agent_id == a.agent_id
    no_side_effects(f)


def test_expired_pending_request_token() -> None:
    new = tok()
    f = Fakes(requests=[request_row(new, uuid4(), token_expires_at=T0)])
    e = refused(f, new)
    assert (e.status, e.type) == (401, "token_expired")


def test_first_use_of_the_new_token_starts_the_overlap() -> None:
    """Row 12, #62: the first call with the new token that passes the check."""
    cur, prev = tok(), tok()
    a = agent_row(cur, prev_token_hash=h(prev), prev_token_expires_at=None)
    f = Fakes(agents=[a])
    assert run(f, cur, now=T0 + 3 * MIN).via == "current"
    assert f.marked == [(a.agent_id, T0 + 3 * MIN + timedelta(minutes=10))]
    assert (f.revoked, f.alerts) == ([], [])


def test_no_mark_while_the_overlap_runs_or_without_rotation() -> None:
    cur, prev = tok(), tok()
    running = agent_row(
        cur, prev_token_hash=h(prev), prev_token_expires_at=T0 + 5 * MIN
    )
    plain_tok = tok()
    plain = agent_row(plain_tok)
    f = Fakes(agents=[running, plain])
    run(f, cur)
    run(f, plain_tok)
    assert f.marked == []


def test_first_use_that_fails_the_check_does_not_start_the_overlap() -> None:
    """A mismatching first call is not a use that 'passes the check' (#62)."""
    cur, prev = tok(), tok()
    a = agent_row(cur, prev_token_hash=h(prev), prev_token_expires_at=None)
    f = Fakes(agents=[a])
    refused(f, cur, "f" * 32)
    assert f.marked == []


# ------------------------------------------------------------ CHK-M3-121: order (#59)


def test_order_revoked_before_expired_and_mismatch() -> None:
    t = tok()
    a = agent_row(t, token_revoked_at=T0 - MIN, token_expires_at=T0 - SEC)
    f = Fakes(agents=[a])
    assert refused(f, t, "f" * 32).type == "token_revoked"
    no_side_effects(f)  # no second revoke, no mismatch alert


def test_order_expired_before_mismatch() -> None:
    t = tok()
    a = agent_row(t, token_expires_at=T0 - SEC)
    f = Fakes(agents=[a])
    assert refused(f, t, None).type == "token_expired"
    no_side_effects(f)


def test_order_mismatch_before_pending() -> None:
    t = tok()
    a = agent_row(t, status="awaiting_approval")
    f = Fakes(agents=[a])
    e = refused(f, t, "f" * 32)
    assert (e.status, e.type) == (401, "machine_id_mismatch")
    assert f.revoked == [(a.agent_id, T0)]


def test_order_rejected_before_revoked() -> None:
    t = tok()
    a = agent_row(
        t, status="decommissioned", token_revoked_at=T0 - MIN, token_expires_at=T0 - SEC
    )
    f = Fakes(agents=[a], rejected_new={a.agent_id})
    assert refused(f, t, None).type == "enrollment_rejected"
    no_side_effects(f)


def test_order_request_rejected_before_expired_and_mismatch() -> None:
    new = tok()
    f = Fakes(
        requests=[
            request_row(new, uuid4(), decision="rejected", token_expires_at=T0 - SEC)
        ]
    )
    assert refused(f, new, None).type == "enrollment_rejected"
    no_side_effects(f)


def test_order_request_expired_before_mismatch() -> None:
    new = tok()
    f = Fakes(requests=[request_row(new, uuid4(), token_expires_at=T0 - SEC)])
    assert refused(f, new, None).type == "token_expired"
    no_side_effects(f)


def test_current_wins_over_previous_and_request() -> None:
    """Lookup order: current, then previous, then the pending request."""
    t = tok()
    a = agent_row(t)
    b = agent_row(tok(), prev_token_hash=h(t))
    f = Fakes(agents=[b, a], requests=[request_row(t, uuid4())])
    got = run(f, t)
    assert (got.agent_id, got.via) == (a.agent_id, "current")


# ------------------------------------------------------------ CHK-M3-127 (REQ-087)


def test_no_token_or_hash_in_errors_alerts_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    t = tok()
    a = agent_row(t)
    f = Fakes(agents=[a])
    errors: list[AgentTokenRefused] = []
    for header in ("f" * 32, MACHINE):
        try:
            run(f, t, header)
        except AgentTokenRefused as e:
            errors.append(e)
        f.agents = [replace(a, token_revoked_at=T0)]
    errors.append(refused(Fakes(), t))
    blob = " ".join(
        [str(e) + repr(e) + repr(e.args) + repr(vars(e)) for e in errors]
        + [repr(x) for x in f.alerts]
        + [r.getMessage() + repr(r.args) for r in caplog.records]
    )
    assert errors and t not in blob and h(t) not in blob and t[4:] not in blob
    assert secrets.compare_digest(t, t)  # the token itself was used


# ------------------------------------------------------------ TASK-059 r1: the cap
# work/decisions.md 2026-10-23 (user): while the new token is unused, the
# previous token is accepted only while now < last_rotation_at + 30 days; after
# that it gets 401 token_expired. The lost-response retry keeps
# last_rotation_at, so it cannot move the cap.

CAP = timedelta(days=30)


def _unused_rotation(rotated_at: datetime) -> tuple[str, str, AgentRow]:
    cur, prev = tok(), tok()
    a = agent_row(
        cur,
        prev_token_hash=h(prev),
        prev_token_expires_at=None,
        last_rotation_at=rotated_at,
        token_issued_at=rotated_at,
        token_expires_at=rotated_at + timedelta(days=365),
    )
    return cur, prev, a


def test_previous_token_cap_boundary() -> None:
    _, prev, a = _unused_rotation(T0)
    f = Fakes(agents=[a])
    got = run(f, prev, now=T0 + CAP - SEC)  # 29 d 23:59:59
    assert (got.agent_id, got.via) == (a.agent_id, "previous")
    e = refused(f, prev, now=T0 + CAP)  # exactly 30 days
    assert (e.status, e.type, e.counted, e.agent_id) == (
        401,
        "token_expired",
        True,
        a.agent_id,
    )
    e = refused(f, prev, now=T0 + CAP + timedelta(days=100))
    assert e.type == "token_expired"
    no_side_effects(f)  # expiry revokes nothing and alerts nothing


def test_lost_response_retry_does_not_move_the_cap() -> None:
    """A retry swaps in a fresh new token but keeps last_rotation_at."""
    _, prev, a = _unused_rotation(T0)
    retried = replace(a, token_hash=h(tok()), token_issued_at=T0 + timedelta(days=20))
    f = Fakes(agents=[retried])
    assert run(f, prev, now=T0 + CAP - SEC).via == "previous"
    assert refused(f, prev, now=T0 + CAP).type == "token_expired"


def test_cap_does_not_touch_the_new_token_or_a_used_rotation() -> None:
    cur, prev, a = _unused_rotation(T0)
    f = Fakes(agents=[a])
    assert run(f, cur, now=T0 + CAP + timedelta(days=1)).via == "current"
    # once the new token was used, the overlap rule (#62) decides, not the cap
    used = replace(a, prev_token_expires_at=T0 + timedelta(minutes=10))
    f2 = Fakes(agents=[used])
    e = refused(f2, prev, now=T0 + timedelta(minutes=10))
    assert e.type == "token_revoked"  # reuse


def test_previous_token_without_a_rotation_time_is_refused() -> None:
    """Unreachable (rotate sets both columns); the check fails closed."""
    _, prev, a = _unused_rotation(T0)
    f = Fakes(agents=[replace(a, last_rotation_at=None)])
    assert refused(f, prev, now=T0 + SEC).type == "token_expired"


def test_cap_comes_before_the_mismatch_check() -> None:
    """#59 order: token_expired before machine_id_mismatch (no revoke)."""
    _, prev, a = _unused_rotation(T0)
    f = Fakes(agents=[a])
    assert refused(f, prev, header=None, now=T0 + CAP).type == "token_expired"
    no_side_effects(f)
