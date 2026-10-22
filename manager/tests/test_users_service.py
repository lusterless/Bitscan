"""REQ-052, REQ-041, REQ-055: the users service with fake stores (TASK-042).

Checks CHK-M2-220 to CHK-M2-227 of tests/m2/test-plan.md. Expected values:
TS §6.2 L1085-L1091 (role change, disable and TOTP reset end sessions;
disabling, demoting or revoking a user's tokens revokes their API tokens; the
last active admin cannot be disabled or demoted; promotion to admin needs
TOTP), #53 (a)-(h), #56 (d) with the user's answer (ASCII letters only), #50
(actions, actor, alert kinds), #7 (POST /users takes the password).
"""

import json
from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from bitscan_manager.auth.passwords import PasswordRejected, verify_password
from bitscan_manager.repositories.users import DuplicateUsername, UserRow
from bitscan_manager.services.users.accounts import (
    Rule,
    TxAudit,
    UserRuleError,
    change_role,
    check_username,
    create_admin,
    create_user,
    disable_user,
    enable_user,
    get_user,
    list_users,
    reset_totp,
    revoke_user_tokens,
)

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
PW = "a good password!"


class Users:
    def __init__(self) -> None:
        self.rows: dict[int, UserRow] = {}
        self.calls: list[str] = []

    def add(
        self,
        role: str = "viewer",
        totp: bool = False,
        disabled: bool = False,
        name: str | None = None,
    ) -> int:
        uid = len(self.rows) + 1
        self.rows[uid] = UserRow(
            uid,
            name or f"u{uid}",
            "$argon2id$x",
            "vault:v1:c" if totp else None,
            5 if totp else None,
            role,
            disabled,
            0,
            None,
            NOW,
        )
        return uid

    def insert_user(
        self, username: str, password_hash: str, role: str, now: datetime
    ) -> int:
        self.calls.append("insert")
        if any(r.username == username for r in self.rows.values()):
            raise DuplicateUsername
        uid = len(self.rows) + 1
        self.rows[uid] = UserRow(
            uid, username, password_hash, None, None, role, False, 0, None, now
        )
        return uid

    def get(self, user_id: int) -> UserRow | None:
        return self.rows.get(user_id)

    def get_for_update(self, user_id: int) -> UserRow | None:
        self.calls.append(f"get_for_update:{user_id}")
        return self.rows.get(user_id)

    def list_page(self, limit: int, after_id: int | None) -> list[UserRow]:
        ids = sorted(i for i in self.rows if after_id is None or i > after_id)
        return [self.rows[i] for i in ids[:limit]]

    def lock_active_admins(self) -> list[int]:
        self.calls.append("lock_admins")
        return sorted(
            i for i, r in self.rows.items() if r.role == "admin" and not r.disabled
        )

    def set_role(self, user_id: int, role: str) -> bool:
        self.calls.append(f"set_role:{user_id}:{role}")
        self.rows[user_id] = replace(self.rows[user_id], role=role)
        return True

    def set_disabled(self, user_id: int, disabled: bool) -> bool:
        self.calls.append(f"set_disabled:{user_id}:{disabled}")
        self.rows[user_id] = replace(self.rows[user_id], disabled=disabled)
        return True

    def clear_totp(self, user_id: int) -> bool:
        self.calls.append(f"clear_totp:{user_id}")
        self.rows[user_id] = replace(
            self.rows[user_id], totp_secret_enc=None, totp_last_step=None
        )
        return True


class Tokens:
    def __init__(self) -> None:
        self.revoked: list[tuple[int, frozenset[str]]] = []

    def revoke_for_user(
        self, user_id: int, kinds: Collection[str], now: datetime
    ) -> int:
        assert now == NOW
        self.revoked.append((user_id, frozenset(kinds)))
        return 3


class Audit:
    def __init__(self, fail: bool = False) -> None:
        self.entries: list[dict[str, Any]] = []
        self.fail = fail

    def audit(self, actor: str, action: str, target: str, detail: Any) -> None:
        if self.fail:
            raise RuntimeError("audit write failed")
        self.entries.append(
            {
                "actor": actor,
                "action": action,
                "target": target,
                "detail": dict(detail),
                "alert": None,
            }
        )

    def alert(
        self, kind: str, actor: str, action: str, target: str, detail: Any
    ) -> None:
        if self.fail:
            raise RuntimeError("audit write failed")
        self.entries.append(
            {
                "actor": actor,
                "action": action,
                "target": target,
                "detail": dict(detail),
                "alert": kind,
            }
        )


@pytest.fixture
def env() -> tuple[Users, Tokens, Audit]:
    return Users(), Tokens(), Audit()


ALL = frozenset({"session", "api"})
SESSIONS = frozenset({"session"})


# ------------------------------------------------------------ CHK-M2-220


def test_create_user_hashes_and_defaults_to_viewer(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, _, audit = env
    uid = create_user(
        users, audit, actor="user:9", username="alice", password=PW, now=NOW
    )
    row = users.rows[uid]
    assert row.role == "viewer" and row.created_at == NOW
    assert row.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(row.password_hash, PW)
    assert audit.entries == [
        {
            "actor": "user:9",
            "action": "user.create",
            "target": f"user:{uid}",
            "detail": {"role": "viewer"},
            "alert": "user_created",
        }
    ]
    assert PW not in json.dumps(audit.entries)


def test_create_operator_allowed_admin_refused(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, _, audit = env
    uid = create_user(
        users,
        audit,
        actor="user:1",
        username="op",
        password=PW,
        role="operator",
        now=NOW,
    )
    assert users.rows[uid].role == "operator"
    for bad in ("admin", "root", ""):
        with pytest.raises(UserRuleError) as info:
            create_user(
                users,
                audit,
                actor="user:1",
                username=f"x{bad}",
                password=PW,
                role=bad,
                now=NOW,
            )
        assert info.value.rule == Rule.INVALID_ROLE
    assert len(users.rows) == 1 and len(audit.entries) == 1


def test_duplicate_username_is_a_conflict_with_no_entry(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, _, audit = env
    create_user(users, audit, actor="user:1", username="bob", password=PW, now=NOW)
    with pytest.raises(UserRuleError) as info:
        create_user(users, audit, actor="user:1", username="bob", password=PW, now=NOW)
    assert info.value.rule == Rule.DUPLICATE
    assert info.value.__cause__ is None
    assert len(audit.entries) == 1 and len(users.rows) == 1


@pytest.mark.parametrize("name", ["a", "A" * 64, "Ab.c_d@e-f", "0", "user@example.com"])
def test_valid_usernames(name: str) -> None:
    check_username(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "A" * 65,
        "a b",
        "a\tb",
        "a/b",
        "a:b",
        "é",
        "ß",
        "ä",
        "а",
        "Ａ",
        "ǅ",
        "a\n",
        "a+b",
        "a'b",
    ],  # noqa: RUF001  Cyrillic а and full-width Ａ are deliberate
)
def test_invalid_usernames_are_refused(
    env: tuple[Users, Tokens, Audit], name: str
) -> None:
    users, _, audit = env
    with pytest.raises(UserRuleError) as info:
        create_user(users, audit, actor="user:1", username=name, password=PW, now=NOW)
    assert info.value.rule == Rule.INVALID_USERNAME
    assert users.rows == {} and audit.entries == []


def test_usernames_are_case_sensitive(env: tuple[Users, Tokens, Audit]) -> None:
    users, _, audit = env
    a = create_user(users, audit, actor="user:1", username="Ab", password=PW, now=NOW)
    b = create_user(users, audit, actor="user:1", username="ab", password=PW, now=NOW)
    assert a != b


@pytest.mark.parametrize("pw", ["a" * 11, "x" * 1025])
def test_password_rules_apply_on_create(
    env: tuple[Users, Tokens, Audit], pw: str
) -> None:
    users, _, audit = env
    with pytest.raises(PasswordRejected):
        create_user(users, audit, actor="user:1", username="carl", password=pw, now=NOW)
    assert users.rows == {} and audit.entries == []


def test_create_admin_has_no_totp_and_alerts_admin_created(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, _, audit = env
    uid = create_admin(
        users, audit, actor="cli:root", username="root1", password=PW, now=NOW
    )
    row = users.rows[uid]
    assert row.role == "admin" and row.totp_secret_enc is None
    assert [e["alert"] for e in audit.entries] == ["admin_created"]
    assert audit.entries[0]["actor"] == "cli:root"


def test_get_and_list(env: tuple[Users, Tokens, Audit]) -> None:
    users, _, _ = env
    for _ in range(5):
        users.add()
    assert get_user(users, 3).user_id == 3
    with pytest.raises(UserRuleError) as info:
        get_user(users, 99)
    assert info.value.rule == Rule.NOT_FOUND
    assert [u.user_id for u in list_users(users, 2, 2)] == [3, 4]


# ------------------------------------------------------------ CHK-M2-221


def test_disable_keeps_the_row_and_revokes_every_token(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, tokens, audit = env
    users.add("admin", totp=True)
    uid = users.add("operator")
    disable_user(users, tokens, audit, actor="user:1", user_id=uid, now=NOW)
    assert users.rows[uid].disabled is True
    assert tokens.revoked == [(uid, ALL)]
    assert [(e["action"], e["alert"]) for e in audit.entries] == [
        ("user.disable", None)
    ]
    disable_user(users, tokens, audit, actor="user:1", user_id=uid, now=NOW)  # no-op
    assert len(audit.entries) == 1


# ------------------------------------------------------------ CHK-M2-222


def test_promotion_to_admin_needs_totp(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    users.add("admin", totp=True)
    uid = users.add("operator")
    with pytest.raises(UserRuleError) as info:
        change_role(
            users, tokens, audit, actor="user:1", user_id=uid, role="admin", now=NOW
        )
    assert info.value.rule == Rule.NEEDS_TOTP
    assert (
        users.rows[uid].role == "operator"
        and tokens.revoked == []
        and audit.entries == []
    )


@pytest.mark.parametrize(
    ("start", "to", "revoked", "alert"),
    [
        ("operator", "admin", SESSIONS, "role_granted"),
        ("viewer", "operator", SESSIONS, "role_granted"),
        ("viewer", "admin", SESSIONS, "role_granted"),
        ("admin", "operator", ALL, None),
        ("admin", "viewer", ALL, None),
        ("operator", "viewer", ALL, None),
    ],
)
def test_role_change_effects(
    env: tuple[Users, Tokens, Audit],
    start: str,
    to: str,
    revoked: frozenset[str],
    alert: str | None,
) -> None:
    users, tokens, audit = env
    users.add("admin", totp=True)
    users.add("admin", totp=True)  # two admins, so a demotion is allowed
    uid = users.add(start, totp=True)
    change_role(users, tokens, audit, actor="user:1", user_id=uid, role=to, now=NOW)
    assert users.rows[uid].role == to
    assert tokens.revoked == [(uid, revoked)]  # #53 (c), (d)
    (entry,) = audit.entries
    assert (entry["action"], entry["alert"], entry["target"]) == (
        "user.role_change",
        alert,
        f"user:{uid}",
    )
    assert entry["detail"] == {"from": start, "to": to}


def test_same_role_is_a_no_op(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    uid = users.add("operator")
    change_role(
        users, tokens, audit, actor="user:1", user_id=uid, role="operator", now=NOW
    )
    assert tokens.revoked == [] and audit.entries == []


def test_unknown_role_refused(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    uid = users.add()
    with pytest.raises(UserRuleError) as info:
        change_role(
            users, tokens, audit, actor="user:1", user_id=uid, role="root", now=NOW
        )
    assert info.value.rule == Rule.INVALID_ROLE


def test_admins_are_locked_before_the_target_row(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, tokens, audit = env
    users.add("admin", totp=True)
    uid = users.add("admin", totp=True)
    change_role(
        users, tokens, audit, actor="user:1", user_id=uid, role="viewer", now=NOW
    )
    assert users.calls.index("lock_admins") < users.calls.index(f"get_for_update:{uid}")
    other = users.add("operator")
    users.calls.clear()
    disable_user(users, tokens, audit, actor="user:1", user_id=other, now=NOW)
    assert users.calls[:2] == ["lock_admins", f"get_for_update:{other}"]


# ------------------------------------------------------------ CHK-M2-223


def test_last_active_admin_cannot_be_demoted_or_disabled(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, tokens, audit = env
    admin = users.add("admin", totp=True)
    users.add("admin", totp=True, disabled=True)  # a disabled admin does not count
    for to in ("operator", "viewer"):
        with pytest.raises(UserRuleError) as info:
            change_role(
                users,
                tokens,
                audit,
                actor=f"user:{admin}",
                user_id=admin,
                role=to,
                now=NOW,
            )  # self-demotion too, #53 (h)
        assert info.value.rule == Rule.LAST_ADMIN
    with pytest.raises(UserRuleError) as info:
        disable_user(
            users, tokens, audit, actor=f"user:{admin}", user_id=admin, now=NOW
        )
    assert info.value.rule == Rule.LAST_ADMIN
    assert users.rows[admin].role == "admin" and not users.rows[admin].disabled
    assert tokens.revoked == [] and audit.entries == []


def test_one_of_two_admins_may_go(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    a = users.add("admin", totp=True)
    b = users.add("admin", totp=True)
    disable_user(users, tokens, audit, actor=f"user:{a}", user_id=b, now=NOW)
    with pytest.raises(UserRuleError):
        change_role(
            users, tokens, audit, actor="user:x", user_id=a, role="viewer", now=NOW
        )


# ------------------------------------------------------------ CHK-M2-224


def test_totp_reset_by_another_admin(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    a = users.add("admin", totp=True)
    b = users.add("admin", totp=True)
    reset_totp(users, tokens, audit, actor=f"user:{a}", actor_id=a, user_id=b, now=NOW)
    assert (
        users.rows[b].totp_secret_enc is None and users.rows[b].totp_last_step is None
    )
    assert tokens.revoked == [(b, SESSIONS)]
    (entry,) = audit.entries
    assert (entry["action"], entry["alert"]) == ("user.totp_reset", "totp_reset")


def test_totp_reset_of_oneself_is_refused(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    a = users.add("admin", totp=True)
    with pytest.raises(UserRuleError) as info:
        reset_totp(
            users, tokens, audit, actor=f"user:{a}", actor_id=a, user_id=a, now=NOW
        )
    assert info.value.rule == Rule.SELF_RESET
    assert users.rows[a].totp_secret_enc is not None and audit.entries == []


def test_totp_reset_from_the_cli(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    a = users.add("admin", totp=True)
    reset_totp(
        users, tokens, audit, actor="cli:root", actor_id=None, user_id=a, now=NOW
    )
    assert users.rows[a].totp_secret_enc is None
    assert audit.entries[0]["actor"] == "cli:root"


def test_unknown_user_is_not_found_everywhere(env: tuple[Users, Tokens, Audit]) -> None:
    users, tokens, audit = env
    users.add("admin", totp=True)
    calls: list[Callable[[], None]] = [
        lambda: change_role(
            users, tokens, audit, actor="a", user_id=99, role="viewer", now=NOW
        ),
        lambda: disable_user(users, tokens, audit, actor="a", user_id=99, now=NOW),
        lambda: enable_user(users, audit, actor="a", user_id=99),
        lambda: reset_totp(
            users, tokens, audit, actor="a", actor_id=1, user_id=99, now=NOW
        ),
        lambda: revoke_user_tokens(
            users, tokens, audit, actor="a", user_id=99, now=NOW
        ),
    ]
    for call in calls:
        with pytest.raises(UserRuleError) as info:
            call()
        assert info.value.rule == Rule.NOT_FOUND
    assert audit.entries == [] and tokens.revoked == []


# ------------------------------------------------------------ CHK-M2-225


def test_revoke_tokens_revokes_api_tokens_and_sessions(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, tokens, audit = env
    uid = users.add("operator")
    revoke_user_tokens(users, tokens, audit, actor="user:1", user_id=uid, now=NOW)
    assert tokens.revoked == [(uid, ALL)]
    assert audit.entries == [
        {
            "actor": "user:1",
            "action": "user.tokens_revoke",
            "target": f"user:{uid}",
            "detail": {"revoked": 3},
            "alert": None,
        }
    ]


# ------------------------------------------------------------ CHK-M2-226


def test_failed_audit_write_propagates_after_the_change(
    env: tuple[Users, Tokens, Audit],
) -> None:
    """In production the caller's transaction then rolls back both (PG test)."""
    users, tokens, _ = env
    users.add("admin", totp=True)
    uid = users.add("operator")
    with pytest.raises(RuntimeError):
        change_role(
            users,
            tokens,
            Audit(fail=True),
            actor="user:1",
            user_id=uid,
            role="viewer",
            now=NOW,
        )
    with pytest.raises(RuntimeError):
        create_user(
            users, Audit(fail=True), actor="user:1", username="z", password=PW, now=NOW
        )


class Repo:
    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []

    def lock_chain(self) -> None:
        return None

    def head_row_hash(self) -> str | None:
        return None

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
        return len(self.rows) + 1, "2026-10-21T10:00:00.000000Z", detail_json

    def insert(self, *row: Any) -> None:
        self.rows.append(row)


def test_tx_audit_writes_entries_and_registers_the_alert_hook() -> None:
    repo = Repo()
    hooks: list[Callable[[], None]] = []
    sink = TxAudit(repo, hooks.append)
    sink.audit("user:1", "user.disable", "user:2", {})
    sink.alert("user_created", "user:1", "user.create", "user:3", {"role": "viewer"})
    (_, actor, action, target, detail, *_rest) = repo.rows[0]
    assert (actor, action, target, detail) == ("user:1", "user.disable", "user:2", None)
    detail2 = json.loads(repo.rows[1][4])
    assert detail2 == {"alert": True, "alert_kind": "user_created", "role": "viewer"}
    assert len(hooks) == 1  # the counter rises only when the transaction commits


# ------------------------------------------------------------ CHK-M2-227


def test_enable_again_is_audited_and_tokens_stay_revoked(
    env: tuple[Users, Tokens, Audit],
) -> None:
    users, tokens, audit = env
    uid = users.add("viewer", disabled=True)
    enable_user(users, audit, actor="user:1", user_id=uid)
    assert users.rows[uid].disabled is False
    assert tokens.revoked == []  # nothing is un-revoked
    assert [(e["action"], e["alert"]) for e in audit.entries] == [("user.enable", None)]
    enable_user(users, audit, actor="user:1", user_id=uid)  # no-op
    assert len(audit.entries) == 1


def test_exactly_one_alert_per_event(env: tuple[Users, Tokens, Audit]) -> None:
    """Lead rulings on TASK-042: one role_granted per raise (also to admin, never
    an extra admin_created), user_created from create_user, admin_created only
    from create_admin, no grant alert on a demotion."""
    users, tokens, audit = env
    users.add("admin", totp=True)
    uid = create_user(
        users, audit, actor="user:1", username="pat", password=PW, now=NOW
    )
    assert [e["alert"] for e in audit.entries] == ["user_created"]
    audit.entries.clear()
    enc = "vault:v1:" + "c"
    users.rows[uid] = replace(users.rows[uid], totp_secret_enc=enc, totp_last_step=1)
    change_role(
        users, tokens, audit, actor="user:1", user_id=uid, role="admin", now=NOW
    )
    assert [e["alert"] for e in audit.entries] == ["role_granted"]
    audit.entries.clear()
    change_role(
        users, tokens, audit, actor="user:1", user_id=uid, role="viewer", now=NOW
    )
    assert [(e["action"], e["alert"]) for e in audit.entries] == [
        ("user.role_change", None)
    ]
    audit.entries.clear()
    create_admin(users, audit, actor="cli:root", username="boss", password=PW, now=NOW)
    assert [e["alert"] for e in audit.entries] == ["admin_created"]
