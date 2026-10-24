"""TASK-038 without PostgreSQL: dummy verification, the verify gate, the
failure alert rule and the OpenAPI error contract.

Checks CHK-M2-171, CHK-M2-178 (unit), CHK-M2-182, CHK-M2-185 and CHK-M2-186
(unit) of tests/m2/test-plan.md. TS §6.2 L1086 (same response whether or not
the user exists), REQ-048 (2) (the unknown-user and back-off paths cost one
Argon2id verification), #54 (a) (alert at 5 consecutive failures, then each 5
more), decisions 2026-10-21 "sign-in memory bound" (at most 4 verifications at
once, the dummy path included, none refused) and "OpenAPI error contract".
"""

import functools
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bitscan_manager.app import create_app, openapi_document
from bitscan_manager.auth import login as login_service
from bitscan_manager.auth import passwords
from bitscan_manager.repositories.users import UserRow
from bitscan_manager.runtime import Runtime
from bitscan_manager.runtime import Tx as TxProto

from .test_runtime import FakeCipher, FakeClock, FakeGate, FakeLimits

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
COMMITTED = Path(__file__).resolve().parents[1] / "openapi.json"


# ------------------------------------------------- fakes for login.login()


@dataclass
class Store:
    users: dict[str, UserRow] = field(default_factory=dict)
    failures: list[int] = field(default_factory=list)
    entries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    alerts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)


class FakeUsers:
    def __init__(self, store: Store) -> None:
        self.s = store

    def find_by_username(self, username: str) -> UserRow | None:
        return self.s.users.get(username)

    def record_failure(self, user_id: int, now: datetime) -> int:
        self.s.failures.append(user_id)
        n = min(self.s.failures.count(user_id), 1000)
        for name, row in self.s.users.items():
            if row.user_id == user_id:
                delay = timedelta(seconds=min(2 ** (n - 1), 900))
                self.s.users[name] = UserRow(
                    row.user_id,
                    row.username,
                    row.password_hash,
                    row.totp_secret_enc,
                    row.totp_last_step,
                    row.role,
                    row.disabled,
                    n,
                    now + delay,
                    row.created_at,
                )
        return n

    def claim_totp_step(self, user_id: int, step: int) -> bool:
        return True

    def reset_failures(self, user_id: int) -> bool:
        self.s.failures = [u for u in self.s.failures if u != user_id]
        return True


class FakeTokens:
    def __init__(self, store: Store) -> None:
        self.s = store

    def insert(self, **kw: Any) -> int:
        self.s.sessions.append(kw)
        return len(self.s.sessions)


class Tx:
    def __init__(self) -> None:
        self.hooks: list[Callable[[], None]] = []

    @property
    def conn(self) -> Any:
        return None

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


class Db:
    @contextmanager
    def transaction(self) -> Iterator[TxProto]:
        tx = Tx()
        yield tx
        for hook in tx.hooks:
            hook()

    def ping(self) -> bool:
        return True


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    s = Store()
    monkeypatch.setattr(login_service, "UserRepo", lambda conn: FakeUsers(s))
    monkeypatch.setattr(login_service, "UserTokenRepo", lambda conn: FakeTokens(s))
    monkeypatch.setattr(login_service, "PgAuditRepo", lambda conn: None)

    def append_entry(repo: object, **kw: Any) -> None:
        s.entries.append((kw["action"], kw))

    def raise_alert(repo: object, on_commit: object, **kw: Any) -> None:
        s.alerts.append((kw["kind"], kw))

    monkeypatch.setattr(login_service, "append_entry", append_entry)
    monkeypatch.setattr(login_service, "raise_alert", raise_alert)
    return s


def runtime(clock: FakeClock | None = None) -> Runtime:
    return Runtime(
        clock=clock or FakeClock(NOW),
        db=Db(),
        totp_cipher=FakeCipher(),
        sink_gate=FakeGate(),
        limits=FakeLimits(),
    )


RIGHT = "the right " + "password"
WRONG = "wrong " + "password!"
HASH = passwords.hash_password(RIGHT)


def add(
    store: Store,
    name: str,
    *,
    role: str = "viewer",
    disabled: bool = False,
    next_login_at: datetime | None = None,
) -> UserRow:
    row = UserRow(
        len(store.users) + 1,
        name,
        HASH,
        None,
        None,
        role,
        disabled,
        0,
        next_login_at,
        NOW,
    )
    store.users[name] = row
    return row


class Counting:
    """Counts Argon2id verifications at the hasher, and which wrapper ran.
    passwords.dummy_verify calls verify_password itself, so wrappers are
    counted separately from hasher runs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.argon2, self.real, self.dummy = 0, 0, 0
        hasher = passwords._HASHER  # noqa: SLF001
        counter = self

        class CountingHasher:
            def hash(self, pw: bytes) -> str:
                return str(hasher.hash(pw))

            def verify(self, stored: str, pw: bytes) -> bool:
                counter.argon2 += 1
                return bool(hasher.verify(stored, pw))

        real_v, real_d = login_service.verify_password, login_service.dummy_verify

        def verify(stored: str, pw: str) -> bool:
            self.real += 1
            return real_v(stored, pw)

        def dummy(pw: str) -> None:
            self.dummy += 1
            real_d(pw)

        # Make the cached dummy hash with the real hasher first, so its creation
        # is neither counted here nor left depending on test order.
        passwords._dummy_hash.cache_clear()  # noqa: SLF001  start from a cold cache
        passwords._dummy_hash()  # noqa: SLF001
        monkeypatch.setattr(passwords, "_HASHER", CountingHasher())
        monkeypatch.setattr(login_service, "verify_password", verify)
        monkeypatch.setattr(login_service, "dummy_verify", dummy)


# ------------------------------------------------------------ CHK-M2-171


@pytest.mark.parametrize(
    ("case", "real", "dummy"),
    [
        ("unknown", 0, 1),
        ("disabled", 0, 1),
        ("backoff", 0, 1),
        ("wrong", 1, 0),
        ("right", 1, 0),
    ],
)
def test_each_path_runs_exactly_one_argon2_verification(
    store: Store, monkeypatch: pytest.MonkeyPatch, case: str, real: int, dummy: int
) -> None:
    add(store, "dis", disabled=True)
    add(store, "slow", next_login_at=NOW + timedelta(seconds=30))
    add(store, "ok")
    counter = Counting(monkeypatch)
    name, pw = {
        "unknown": ("nobody", "x" * 12),
        "disabled": ("dis", RIGHT),
        "backoff": ("slow", RIGHT),
        "wrong": ("ok", WRONG),
        "right": ("ok", RIGHT),
    }[case]
    try:
        login_service.login(runtime(), username=name, password=pw, totp_code=None)
        outcome = "ok"
    except login_service.LoginFailed:
        outcome = "failed"
    assert counter.argon2 == 1  # exactly one Argon2id run on every path
    assert (counter.real, counter.dummy) == (real, dummy)
    assert outcome == ("ok" if case == "right" else "failed")


def test_backoff_and_unknown_paths_count_nothing(store: Store) -> None:
    add(store, "slow", next_login_at=NOW + timedelta(seconds=30))
    for name in ("slow", "nobody"):
        with pytest.raises(login_service.LoginFailed):
            login_service.login(
                runtime(), username=name, password=RIGHT, totp_code=None
            )
    assert store.failures == [] and store.entries == [] and store.alerts == []


def test_dummy_verify_is_a_real_argon2_run() -> None:
    started = time.perf_counter()
    login_service.dummy_verify("whatever password")
    assert time.perf_counter() - started > 0.01


# ------------------------------------------------- CHK-M2-178 (unit side)


def test_login_failures_alert_at_5_then_every_5(store: Store) -> None:
    clock = FakeClock(NOW)
    add(store, "target")
    for n in range(1, 16):
        clock.at = store.users["target"].next_login_at or NOW  # after the back-off
        with pytest.raises(login_service.LoginFailed):
            login_service.login(
                runtime(clock), username="target", password=WRONG, totp_code=None
            )
        alerted = [d["detail"]["failed_logins"] for k, d in store.alerts]
        assert alerted == [c for c in (5, 10, 15) if c <= n], n
    for _, kw in store.alerts:
        assert kw["action"] == "auth.login_failures" and kw["actor"] == "system"
        assert kw["target"] == "user:1"
        assert "target" not in json.dumps(kw["detail"])  # no username
        assert "wrong password" not in json.dumps(kw)


def test_success_writes_one_login_entry_and_resets(store: Store) -> None:
    add(store, "ok")
    login_service.login(runtime(), username="ok", password=RIGHT, totp_code=None)
    assert [a for a, _ in store.entries] == ["auth.login"]
    (sess,) = store.sessions
    assert sess["kind"] == "session" and sess["expires_at"] == NOW + timedelta(hours=24)


# ------------------------------------------------- CHK-M2-186 (unit side)


class Blocking:
    """A hasher whose verify blocks until released and records concurrency."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.lock = threading.Lock()
        self.inside = 0
        self.peak = 0
        self.done = 0
        self.release = threading.Event()

        def enter() -> None:
            with self.lock:
                self.inside += 1
                self.peak = max(self.peak, self.inside)
            self.release.wait(20)
            with self.lock:
                self.inside -= 1
                self.done += 1

        def verify(stored: str, pw: str) -> bool:
            enter()
            return pw == RIGHT

        def dummy(pw: str) -> None:
            enter()

        monkeypatch.setattr(passwords, "verify_password", verify)
        monkeypatch.setattr(passwords, "dummy_verify", dummy)


def run_threads(fns: list[Callable[[], object]], blocking: Blocking) -> list[object]:
    out: list[object] = [None] * len(fns)

    def wrap(i: int) -> None:
        try:
            out[i] = fns[i]()
        except BaseException as exc:  # noqa: BLE001
            out[i] = exc

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(len(fns))]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and blocking.inside < min(4, len(fns)):
        time.sleep(0.01)
    time.sleep(0.3)  # give any fifth caller the chance to (wrongly) enter
    peak_while_blocked = blocking.peak
    blocking.release.set()
    for t in threads:
        t.join(30)
    out.append(peak_while_blocked)
    return out


@pytest.mark.parametrize("mix", ["dummy", "real", "mixed"])
def test_at_most_four_verifications_at_once_and_none_refused(
    monkeypatch: pytest.MonkeyPatch, mix: str
) -> None:
    blocking = Blocking(monkeypatch)
    fns: list[Callable[[], object]] = []
    for i in range(8):
        use_dummy = mix == "dummy" or (mix == "mixed" and i % 2 == 0)
        if use_dummy:
            fns.append(lambda: login_service.dummy_verify("pw"))
        else:
            fns.append(lambda: login_service.verify_password(HASH, RIGHT))
    result = run_threads(fns, blocking)
    assert result[-1] == 4  # exactly four ran at once while blocked
    assert blocking.peak == 4 and blocking.done == 8
    assert not any(isinstance(r, BaseException) for r in result[:-1])


def test_login_paths_take_the_same_gate(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through login(): unknown, disabled, back-off and real users share 4 slots."""
    add(store, "dis", disabled=True)
    add(store, "slow", next_login_at=NOW + timedelta(seconds=30))
    add(store, "ok")
    blocking = Blocking(monkeypatch)
    names = ["nobody", "dis", "slow", "ok", "nobody2", "ok", "slow", "dis"]

    def attempt(name: str) -> str:
        try:
            login_service.login(
                runtime(), username=name, password=RIGHT, totp_code=None
            )
            return "ok"
        except login_service.LoginFailed:
            return "failed"

    calls: list[Callable[[], object]] = [functools.partial(attempt, n) for n in names]
    result = run_threads(calls, blocking)
    assert result[-1] == 4
    assert result[:-1] == [
        "failed",
        "failed",
        "failed",
        "ok",
        "failed",
        "ok",
        "failed",
        "failed",
    ]


def test_gate_admits_in_arrival_order() -> None:
    gate = login_service._FairSemaphore(1)  # noqa: SLF001
    order: list[int] = []
    gate.__enter__()
    threads = []

    def enter_and_record(i: int) -> None:
        with gate:
            order.append(i)

    for i in range(5):
        t = threading.Thread(target=enter_and_record, args=(i,))
        t.start()
        threads.append(t)
        time.sleep(0.05)
    gate.__exit__(None, None, None)
    for t in threads:
        t.join(5)
    assert order == [0, 1, 2, 3, 4]


# ------------------------------------------------- CHK-M2-182, CHK-M2-185


def all_operations(doc: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in doc["paths"].items():
        for method, op in item.items():
            yield path, method, op


@pytest.mark.parametrize("source", ["committed", "fresh"])
def test_openapi_error_contract(source: str) -> None:
    doc = (
        json.loads(COMMITTED.read_text(encoding="utf-8"))
        if source == "committed"
        else openapi_document()
    )
    # Narrowed 2026-10-23 (lead ruling, TASK-074 option (a)): FastAPI's own
    # request-validation 422 (the one that refers to HTTPValidationError) is
    # never documented, since the app answers 400; the only operation that
    # lists a 422 is the inventory upload, whose decoder really answers 422
    # (TS §3.4 L240, #72 (b)), as problem+json (checked in the loop below).
    assert "HTTPValidationError" not in json.dumps(doc)
    assert "ValidationError" not in json.dumps(doc["components"])
    with_422 = [
        (method, path)
        for path, method, op in all_operations(doc)
        if "422" in op["responses"]
    ]
    assert with_422 == [("put", "/api/v1/agent/{id}/inventory")], with_422
    schemas = doc["components"]["schemas"]
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    problem = schemas["Problem"]
    assert set(problem["properties"]) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
    }
    assert set(problem["required"]) == set(problem["properties"])
    for path, method, op in all_operations(doc):
        assert path.startswith("/api/v1/") or path in ("/healthz", "/readyz"), path
        takes_input = bool(op.get("parameters") or op.get("requestBody"))
        if takes_input:
            content = op["responses"]["400"]["content"]
            assert list(content) == ["application/problem+json"], (method, path)
            assert content["application/problem+json"]["schema"] == {
                "$ref": "#/components/schemas/Problem"
            }
        for status, resp in op["responses"].items():
            if status.startswith(("4", "5")):
                assert list(resp.get("content", {})) == ["application/problem+json"], (
                    method,
                    path,
                    status,
                )


def test_documented_400_matches_what_the_app_returns() -> None:
    """Every operation taking a body answers 400 problem+json for a bad body
    from an authenticated caller (authentication runs first: without a token
    the answer is 401, never 422)."""
    from bitscan_manager.auth.dependencies import current_principal
    from bitscan_manager.auth.principal import Principal
    from bitscan_manager.auth.tokens import TokenKind

    app = create_app(runtime())
    signed_in = Principal(
        user_id=1,
        username="u",
        role="admin",
        kind=TokenKind.SESSION,
        token_id=1,
        totp_verified=True,
        totp_enrolled=True,
        expires_at=NOW + timedelta(hours=24),
    )
    doc = openapi_document()
    # A real peer address: enrol refuses a peer that is not an IP (#55 (d)).
    with TestClient(
        app, raise_server_exceptions=False, client=("10.20.0.1", 1234)
    ) as c:
        for path, method, op in all_operations(doc):
            if not op.get("requestBody"):
                continue
            needs_auth = "401" in op["responses"]
            bad: dict[str, Any] = {
                "content": b"[1, 2]",
                "headers": {"Content-Type": "application/json"},
            }
            app.dependency_overrides.clear()
            if path == "/api/v1/agent/enroll":
                # TASK-067 (decisions 2026-10-23 (4)): the bse_ check runs
                # before the body, so every attempt counts (#55 (c), #59). No
                # token: 401; a well-formed bse_: the bad body is 400. The
                # token is never looked up for a body that fails validation.
                anonymous = c.request(method.upper(), path, **bad)
                assert anonymous.status_code == 401, (method, path)
                assert anonymous.json()["type"] == "unauthorized"
                bse = "bse_" + "A" * 43
                bad["headers"] = {**bad["headers"], "Authorization": f"Bearer {bse}"}
            elif path.startswith("/api/v1/agent/"):
                # bsa_ routes: the token check (a database lookup) runs before
                # the body, so without a token the answer is 401; their 400 for
                # a bad body with a real agent token is checked on PostgreSQL in
                # each route's own test file (TASK-072 to TASK-075).
                anonymous = c.request(method.upper(), path, **bad)
                assert anonymous.status_code == 401, (method, path)
                assert anonymous.json()["type"] == "unauthorized"
                continue
            elif needs_auth and path != "/api/v1/auth/login":
                anonymous = c.request(method.upper(), path, **bad)
                assert anonymous.status_code == 401, (method, path)
                app.dependency_overrides[current_principal] = lambda: signed_in
            resp = c.request(method.upper(), path, **bad)
            assert resp.status_code == 400, (method, path, resp.status_code)
            assert resp.headers["content-type"].startswith("application/problem+json")
            assert resp.json()["type"] == "invalid_request"
            assert resp.status_code != 422
    app.dependency_overrides.clear()


def test_login_and_logout_document_their_refusals() -> None:
    doc = openapi_document()
    login = doc["paths"]["/api/v1/auth/login"]["post"]["responses"]
    logout = doc["paths"]["/api/v1/auth/logout"]["post"]["responses"]
    assert set(login) == {"200", "400", "401", "429", "503"}
    assert set(logout) >= {"204", "401", "403", "429", "503"}
