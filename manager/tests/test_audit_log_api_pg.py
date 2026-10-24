"""TASK-078: GET /api/v1/audit-log on PostgreSQL (TP-M3-32).

Checks CHK-M3-285 to CHK-M3-287 of tests/m3/test-plan.md. Expected values come
from the spec and the answers, not from the code: TS §6.2 L1127 (admin,
session or API token), TS §5.2 L981-L990 (the eight columns), TS §5.3 L1051
(hash chain: row_hash = SHA-256 of prev_hash and the entry), #38 (the hash
input: [prev_hash, audit_id, actor, action, target, detail_text, at_text],
detail_text = PostgreSQL's own detail::text, at_text YYYY-MM-DDTHH:MM:SS.ffffffZ
UTC, genesis prev_hash 64 zeros), #68 (newest first; items are the eight
columns; no filters; {items, next_cursor}), REQ-085 (1)-(3).
"""

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit.chain import (
    GENESIS_PREV_HASH,
    HashInput,
    compute_row_hash,
)
from bitscan_manager.services.users import TxAudit

from .conftest import PgServer
from .test_contract_agent import RFC3339
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ROUTE = "/api/v1/audit-log"
# the eight columns (#68) plus detail_text, the exact string hashed (ruling
# 2026-10-23, TASK-078 (b))
KEYS = [
    "detail_text",
    "audit_id",
    "actor",
    "action",
    "target",
    "detail",
    "at",
    "prev_hash",
    "row_hash",
]


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


class Env:
    def __init__(self, server: PgServer, db: AppDatabase, client: TestClient) -> None:
        self.server, self.db, self.client = server, db, client

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str, kind: str = "api", verified: bool = True) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', %s, 'enc', 1, %s)"
                " RETURNING user_id",
                (f"al{secrets.token_hex(5)}", role, T0),
            ).fetchone()
            assert uid is not None
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uid[0],
                    kind,
                    token_hash(tok),
                    verified and kind == "session",
                    T0 + timedelta(days=30),
                    T0,
                ),
            )
        return tok

    def append(self, detail: Any, action: str = "test.entry") -> None:
        with self.db.transaction() as tx:
            TxAudit(PgAuditRepo(tx.conn), tx.on_commit).audit(
                "system", action, f"t:{secrets.token_hex(3)}", detail
            )

    def get(self, tok: str | None, **params: Any) -> Any:
        h = {} if tok is None else {"Authorization": f"Bearer {tok}"}
        return self.client.get(ROUTE, headers=h, params=params)

    def walk(
        self, tok: str, limit: int, pages: int | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        n = 0
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            r = self.get(tok, **params)
            n += 1
            assert r.status_code == 200, r.text
            body = r.json()
            assert list(body) == ["items", "next_cursor"]
            assert len(body["items"]) <= limit
            out += body["items"]
            cursor = body["next_cursor"]
            if cursor is None or (pages is not None and n >= pages):
                return out
            assert n < 550

    def counts(self) -> tuple[Any, ...]:
        with self.conn() as c:
            row = c.execute("SELECT count(*), max(audit_id) FROM audit_log").fetchone()
        assert row is not None
        return tuple(row)


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=4, connect_timeout_s=5
    )
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.78.0.1", 1)) as client:
        yield Env(migrated_db, db, client)
    db.close()


def detail_text(item: dict[str, Any]) -> str | None:
    """The hashed detail text as the item carries it; it must parse back to
    the item's detail (ruling 2026-10-23, TASK-078 (b))."""
    text = item["detail_text"]
    if text is None:
        assert item["detail"] is None
        return None
    assert isinstance(text, str) and json.loads(text) == item["detail"]
    return text


def verify(items: list[dict[str, Any]]) -> None:
    """Every item's row_hash recomputes from the item, and each prev_hash is
    the row_hash of the next older item (newest first)."""
    for i, it in enumerate(items):
        entry = HashInput(
            it["audit_id"],
            it["actor"],
            it["action"],
            it["target"],
            detail_text(it),
            it["at"],
        )
        assert compute_row_hash(it["prev_hash"], entry) == it["row_hash"], it
        if i + 1 < len(items):
            assert it["prev_hash"] == items[i + 1]["row_hash"], (it, items[i + 1])


# ------------------------------------------------------------ CHK-M3-285


def test_admin_api_token_pages_through_every_entry_once_newest_first(env: Env) -> None:
    """REQ-085 (1), #68: an admin bsk_ walks the whole log; each entry exactly
    once; strictly newest first; the walk with a small limit equals the
    newest part of the walk with the largest limit."""
    for i in range(5):
        env.append({"i": i})
    admin = env.user("admin", "api")
    whole = env.walk(admin, 500)
    ids = [i["audit_id"] for i in whole]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, reverse=True)
    with env.conn() as c:
        all_ids = [
            r[0]
            for r in c.execute("SELECT audit_id FROM audit_log ORDER BY audit_id DESC")
        ]
    assert ids == all_ids
    small = env.walk(env.user("admin", "api"), 3, pages=10)
    assert small == whole[: len(small)] and len(small) == min(30, len(whole))
    assert [i["detail"] for i in whole[:5]] == [
        {"i": 4},
        {"i": 3},
        {"i": 2},
        {"i": 1},
        {"i": 0},
    ]


@pytest.mark.parametrize(
    ("role", "kind", "status", "type_"),
    [
        ("admin", "session", 200, None),
        ("admin", "api", 200, None),
        ("operator", "session", 403, "forbidden"),
        ("operator", "api", 403, "forbidden"),
        ("viewer", "api", 403, "forbidden"),
    ],
)
def test_roles(env: Env, role: str, kind: str, status: int, type_: str | None) -> None:
    """TS §6.2 L1127: admin (session or API token); operators and viewers
    are refused."""
    r = env.get(env.user(role, kind), limit=1)
    assert r.status_code == status, r.text
    if type_:
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["type"] == type_


def test_no_token_and_agent_tokens_are_401(env: Env) -> None:
    for tok in (
        None,
        new_agent_token(AgentTokenKind.AGENT),
        new_agent_token(AgentTokenKind.ENROLMENT),
    ):
        r = env.get(tok)
        assert r.status_code == 401 and r.json()["type"] == "unauthorized"


def test_bad_cursors_and_limits_are_400(env: Env) -> None:
    admin = env.user("admin")
    env.append({"x": 1})
    env.append({"x": 2})
    cursor = env.get(admin, limit=1).json()["next_cursor"]
    assert cursor
    flipped = cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]
    for params in ({"cursor": flipped}, {"cursor": "x"}, {"limit": 0}, {"limit": 501}):
        r = env.get(admin, **params)
        assert r.status_code == 400 and r.json()["type"] == "invalid_request", params


# ------------------------------------------------------------ CHK-M3-286


def test_items_are_the_eight_columns_and_the_chain_reverifies(env: Env) -> None:
    """REQ-085 (2), #38: items are exactly the eight columns, at is the hashed
    UTC text form, and the whole returned chain re-verifies from the items
    with compute_row_hash, down to the genesis entry."""
    env.append({"k": "v", "n": 3, "nested": {"b": [1, 2], "a": None}})
    env.append({})
    env.append({"text": 'café 中 "q" \\ /', "ctl": "\u0001"})
    whole = env.walk(env.user("admin"), 500)
    for it in whole:
        assert sorted(it) == sorted(KEYS)
        assert RFC3339.match(it["at"]) and it["at"].endswith("Z")
        assert len(it["at"]) == len("2026-10-23T12:00:00.000000Z")
    verify(whole)
    assert whole[-1]["prev_hash"] == GENESIS_PREV_HASH
    # and the items equal the stored rows
    with env.conn() as c:
        rows = c.execute(
            "SELECT audit_id, actor, action, target, detail::text, prev_hash, row_hash"
            " FROM audit_log ORDER BY audit_id DESC"
        ).fetchall()
    for it, row in zip(whole, rows, strict=True):
        assert (it["audit_id"], it["actor"], it["action"], it["target"]) == tuple(
            row[:4]
        )
        assert detail_text(it) == row[4]
        assert (it["prev_hash"], it["row_hash"]) == (row[5], row[6])


def test_numbers_written_by_the_app_reverify(env: Env) -> None:
    """#38, ruling 2026-10-23 (TASK-078 (b)): an entry the app writes with
    float values (jsonb renders 1e-07 as 0.0000001) re-verifies from the
    item, because the item carries detail_text, PostgreSQL's own
    detail::text, the exact string hashed."""
    env.append({"tiny": 1e-07, "big": 1e20, "half": 0.5, "neg": -0.0, "pi": 3.14159})
    (it,) = env.walk(env.user("admin"), 1, pages=1)
    with env.conn() as c:
        row = c.execute(
            "SELECT detail::text FROM audit_log WHERE audit_id = %s", (it["audit_id"],)
        ).fetchone()
    assert row is not None
    assert detail_text(it) == row[0], (it, row[0])
    verify([it])


# ------------------------------------------------------------ CHK-M3-287


def test_the_route_writes_nothing(env: Env) -> None:
    """REQ-085 (3): reading (full walk, refused callers included) leaves the
    row count and the newest id unchanged."""
    env.append({"before": True})
    before = env.counts()
    env.walk(env.user("admin"), 500)
    env.walk(env.user("admin", "session"), 2, pages=5)
    env.get(env.user("operator"))
    env.get(None)
    assert env.counts() == before


def test_openapi_documents_the_route() -> None:
    from .test_contract_agent import OPENAPI

    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert set(doc["paths"][ROUTE]) == {"get"}
    op = doc["paths"][ROUTE]["get"]
    assert "requestBody" not in op and "422" not in op["responses"]
    names = sorted(p["name"] for p in op.get("parameters", []))
    assert names == ["cursor", "limit"]  # no filters (#68)
    for status in ("401", "403", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
