"""REQ-030 (1), (7), (8): the audit chain append, pure part (TP-M1-14 unit).

Checks CHK-M1-200, CHK-M1-202 and CHK-M1-209 (unit), without PostgreSQL. The
hash rule is decision #38; the reference below is written from it independently
of the implementation, and the known-answer vectors were computed by hand from
the rule. The append flow is driven through a fake repository that records
every call.
"""

import hashlib
import json
import logging
import math
from collections.abc import Mapping
from typing import Any

import pytest

from bitscan_manager.services.audit import AuditError, chain

GENESIS = "0" * 64
U, E = chr(0xFC), chr(0xE9)  # non-ASCII, kept as UTF-8 (ensure_ascii=False)
KAV_DETAIL = '{"k": 1, "' + U + '": "' + E + '"}'
KAV = [
    (
        (
            GENESIS,
            1,
            "admin",
            "policy.import",
            "cis.bit",
            KAV_DETAIL,
            "2026-10-20T12:00:00.000000Z",
        ),
        "b1524934910c8ad7307c0c21d23c5b899f2b4381c532df997d23887355a931ed",
    ),
    (
        (
            "a" * 64,
            2,
            "system",
            "audit.checkpoint",
            None,
            None,
            "2026-10-20T12:00:01.500000Z",
        ),
        "0112bc14f0e5243e2a499afa81e6bdb2e10f67d6396ad5921ac79d44dd6ff711",
    ),
]


def reference(
    prev: str,
    audit_id: int,
    actor: str,
    action: str,
    target: str | None,
    detail_text: str | None,
    at_text: str,
) -> str:
    """Decision #38, written independently of the code under test."""
    data = [prev, audit_id, actor, action, target, detail_text, at_text]
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute(
    prev: str,
    audit_id: int,
    actor: str,
    action: str,
    target: str | None,
    detail_text: str | None,
    at_text: str,
) -> str:
    entry = chain.HashInput(
        audit_id=audit_id,
        actor=actor,
        action=action,
        target=target,
        detail_text=detail_text,
        at_text=at_text,
    )
    return chain.compute_row_hash(prev, entry)


# --- the hash ---


def test_genesis_is_64_zeros() -> None:
    assert chain.GENESIS_PREV_HASH == GENESIS


@pytest.mark.parametrize(("fields", "expected"), KAV)
def test_known_answer_vectors(fields: tuple[Any, ...], expected: str) -> None:
    assert reference(*fields) == expected  # the reference itself is right
    assert compute(*fields) == expected


BASE = (
    GENESIS,
    7,
    "alice",
    "scan.create",
    "agent-1",
    '{"a": [1, 2]}',
    "2026-01-31T23:59:59.999999Z",
)


def test_matches_the_reference_and_is_lowercase_hex() -> None:
    got = compute(*BASE)
    assert got == reference(*BASE)
    assert len(got) == 64 and got == got.lower()
    assert all(c in "0123456789abcdef" for c in got)


@pytest.mark.parametrize("index", range(7))
def test_every_field_changes_the_hash(index: int) -> None:
    changed: list[Any] = list(BASE)
    value = changed[index]
    if isinstance(value, int):
        changed[index] = value + 1
    else:
        changed[index] = str(value)[:-1] + ("0" if str(value)[-1] != "0" else "1")
    assert compute(*changed) != compute(*BASE)
    assert compute(*changed) == reference(*changed)


@pytest.mark.parametrize(
    ("target", "detail"),
    [
        (None, None),
        ("", None),
        (None, "{}"),
        ("", "{}"),
        (None, "null"),
        ("null", None),
    ],
)
def test_null_differs_from_empty(target: str | None, detail: str | None) -> None:
    got = compute(GENESIS, 1, "a", "b", target, detail, "2026-10-20T00:00:00.000000Z")
    assert got == reference(
        GENESIS, 1, "a", "b", target, detail, "2026-10-20T00:00:00.000000Z"
    )


def test_null_and_empty_give_different_hashes() -> None:
    at = "2026-10-20T00:00:00.000000Z"
    hashes = {
        compute(GENESIS, 1, "a", "b", t, d, at)
        for t, d in [(None, None), ("", None), (None, "{}"), ("", "{}")]
    }
    assert len(hashes) == 4


def test_non_ascii_is_hashed_as_utf8_not_escaped() -> None:
    at = "2026-10-20T00:00:00.000000Z"
    got = compute(GENESIS, 1, "j" + U + "rg", "x", None, None, at)
    escaped = hashlib.sha256(
        json.dumps(
            [GENESIS, 1, "j" + U + "rg", "x", None, None, at],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    spaced = hashlib.sha256(
        json.dumps(
            [GENESIS, 1, "j" + U + "rg", "x", None, None, at], ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert got != escaped and got != spaced
    assert got == reference(GENESIS, 1, "j" + U + "rg", "x", None, None, at)


# --- the append flow, through a fake repository ---


class FakeRepo:
    def __init__(
        self,
        head: str | None,
        audit_id: int = 41,
        at_text: str = "2026-10-20T12:34:56.123456Z",
    ) -> None:
        self.head = head
        self.audit_id = audit_id
        self.at_text = at_text
        self.calls: list[tuple[str, Any]] = []

    def lock_chain(self) -> None:
        self.calls.append(("lock", None))

    def head_row_hash(self) -> str | None:
        self.calls.append(("head", None))
        return self.head

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
        self.calls.append(("allocate", detail_json))
        # stand-in for PostgreSQL's canonical jsonb text
        text = (
            None
            if detail_json is None
            else json.dumps(json.loads(detail_json), sort_keys=True)
        )
        return self.audit_id, self.at_text, text

    def insert(
        self,
        audit_id: int,
        actor: str,
        action: str,
        target: str | None,
        detail_text: str | None,
        at_text: str,
        prev_hash: str,
        row_hash: str,
    ) -> None:
        self.calls.append(
            (
                "insert",
                (
                    audit_id,
                    actor,
                    action,
                    target,
                    detail_text,
                    at_text,
                    prev_hash,
                    row_hash,
                ),
            )
        )


def test_append_locks_first_then_links_and_inserts(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    repo = FakeRepo(head="b" * 64)
    detail: Mapping[str, object] = {"z": 1, "a": [True, None, "x"], "n": {"k": 1.5}}
    entry = chain.append_entry(
        repo, actor="alice", action="policy.import", target="cis.bit", detail=detail
    )
    assert [c[0] for c in repo.calls] == ["lock", "head", "allocate", "insert"]
    sent = repo.calls[2][1]
    assert isinstance(sent, str) and json.loads(sent) == detail
    audit_id, actor, action, target, detail_text, at_text, prev, row = repo.calls[3][1]
    assert (audit_id, actor, action, target) == (
        41,
        "alice",
        "policy.import",
        "cis.bit",
    )
    assert detail_text == json.dumps(
        detail, sort_keys=True
    )  # the repo's text is hashed
    assert prev == "b" * 64
    assert row == reference(
        prev, 41, "alice", "policy.import", "cis.bit", detail_text, at_text
    )
    assert (entry.audit_id, entry.prev_hash, entry.row_hash, entry.at_text) == (
        41,
        prev,
        row,
        "2026-10-20T12:34:56.123456Z",
    )
    out = capsys.readouterr()
    assert out.out == "" and out.err == "" and caplog.text == ""


def test_first_entry_uses_the_genesis_hash() -> None:
    repo = FakeRepo(head=None, audit_id=1)
    entry = chain.append_entry(repo, actor="system", action="audit.start")
    assert entry.prev_hash == GENESIS
    assert repo.calls[2] == ("allocate", None)
    assert repo.calls[3][1][3:5] == (None, None)  # target and detail stay NULL
    assert entry.row_hash == reference(
        GENESIS, 1, "system", "audit.start", None, None, "2026-10-20T12:34:56.123456Z"
    )


def test_consecutive_appends_form_a_chain() -> None:
    head: str | None = None
    for i in range(1, 6):
        repo = FakeRepo(head=head, audit_id=i)
        entry = chain.append_entry(repo, actor="a", action="x", detail={"i": i})
        assert entry.prev_hash == (head or GENESIS)
        head = entry.row_hash


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_refused_before_any_repo_call(bad: float) -> None:
    repo = FakeRepo(head=None)
    with pytest.raises((ValueError, AuditError)):
        chain.append_entry(repo, actor="a", action="x", detail={"v": [1, {"w": bad}]})
    assert repo.calls == []


def test_append_opens_no_network_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("append opened a network connection")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    repo = FakeRepo(head=None, audit_id=3)
    entry = chain.append_entry(repo, actor="a", action="x", detail={"k": "v"})
    assert entry.audit_id == 3 and [c[0] for c in repo.calls][-1] == "insert"


def test_repo_failure_propagates_and_nothing_is_inserted() -> None:
    class Failing(FakeRepo):
        def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
            raise RuntimeError("database gone")

    repo = Failing(head=None)
    with pytest.raises(RuntimeError, match="database gone"):
        chain.append_entry(repo, actor="a", action="x")
    assert [c[0] for c in repo.calls] == ["lock", "head"]
