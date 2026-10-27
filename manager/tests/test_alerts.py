"""REQ-055 (1)-(3): alerts as audit entries plus bitscan_alerts_total (TASK-035).

Checks CHK-M2-135 to CHK-M2-138 of tests/m2/test-plan.md. TS §8.4 L1289
(every alert is an audit entry with detail.alert = true and counts in
bitscan_alerts_total{kind}), #50 (c) (kinds; detail.alert_kind), #5 (no
metrics route in M2). The PostgreSQL half (commit and rollback through
AppDatabase) runs in tests/test_alerts_pg.py.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from prometheus_client import generate_latest

from bitscan_manager.app import create_app
from bitscan_manager.services.audit import alerts as alerts_module
from bitscan_manager.services.audit.alerts import ALERT_KINDS, raise_alert
from bitscan_manager.services.audit.metrics import REGISTRY

M2_KINDS = {
    "api_token_created",
    "totp_enrolled",
    "totp_replaced",
    "totp_reset",
    "user_created",
    "role_granted",
    "admin_created",
    "audit_sink_unreachable",
    "login_failures",
    "token_check_failures",
}
# M3 (TASK-056): the #71 kinds, agreed 2026-10-23.
M3_KINDS = {
    "enrolment_token_risky",
    "enrolments_per_hour",
    "reenrolment_approved",
    "machine_id_mismatch",
    "token_reuse",
    "rotation_outside_window",
    "rotation_new_ip",
    "runner_helper_changed",
    "settings_changed",
    "redaction_default_removed",
    "clock_skew",
    "agents_offline",
    "job_queue_age",
    "inventory_stale",
    "new_packages_burst",
    "result_409_flood",
    "agent_auth_failures",
    "default_partition_rows",
}
# M7 (TASK-153): the #101 catalog kinds, approved 2026-10-27 (a move is not an alert).
M7_KINDS = {
    "policy_imported",
    "policy_import_rejected",
    "policy_deleted",
    "policy_rebuilt",
    "policy_reenabled",
    "catalog_integrity_failed",
}
SPEC_KINDS = M2_KINDS | M3_KINDS | M7_KINDS
# REQ-086 (TS §8.4 L1288): the registry the #70 route serves.
REGISTRY_FAMILIES = {
    "bitscan_alerts",
    "bitscan_agents",
    "bitscan_heartbeat_latency_seconds",
    "bitscan_jobs_queued",
    "bitscan_jobs_expired",
    "bitscan_import_failures",  # M7 (#101)
}


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def lock_chain(self) -> None:
        self.calls.append("lock")

    def head_row_hash(self) -> str | None:
        return self.rows[-1]["row_hash"] if self.rows else None

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
        return len(self.rows) + 1, "2026-10-21T10:00:00.000000Z", detail_json

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
        self.rows.append(
            {
                "audit_id": audit_id,
                "actor": actor,
                "action": action,
                "target": target,
                "detail": detail_text,
                "prev_hash": prev_hash,
                "row_hash": row_hash,
            }
        )


class FakeTx:
    def __init__(self) -> None:
        self.hooks: list[Callable[[], None]] = []

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)

    def commit(self) -> None:
        for hook in self.hooks:
            hook()
        self.hooks = []

    def rollback(self) -> None:
        self.hooks = []


def count(kind: str) -> float:
    value = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind})
    return 0.0 if value is None else value


# ------------------------------------------------------------ CHK-M2-135


def test_kinds_are_exactly_the_50_and_71_lists() -> None:
    """#50 (c) for M2, #71 for M3 (CHK-M3-103) and #101 for M7 (CHK-M7-185);
    one union, no other kind."""
    from bitscan_manager.services.audit.alerts import (
        M2_ALERT_KINDS,
        M3_ALERT_KINDS,
        M7_ALERT_KINDS,
    )

    assert set(M2_ALERT_KINDS) == M2_KINDS
    assert set(M3_ALERT_KINDS) == M3_KINDS
    assert set(M7_ALERT_KINDS) == M7_KINDS
    assert set(ALERT_KINDS) == SPEC_KINDS
    assert len(ALERT_KINDS) == 34


@pytest.mark.parametrize("kind", sorted(SPEC_KINDS))
def test_alert_writes_one_entry_with_alert_true_and_its_kind(kind: str) -> None:
    repo, tx = FakeRepo(), FakeTx()
    raise_alert(
        repo,
        tx.on_commit,
        kind=kind,
        actor="user:7",
        action="user.create",
        target="user:9",
        detail={"username_id": 9, "nested": {"a": [1]}},
    )
    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert (row["actor"], row["action"], row["target"]) == (
        "user:7",
        "user.create",
        "user:9",
    )
    detail = json.loads(row["detail"])
    assert detail["alert"] is True  # JSON true, not "true"
    assert detail["alert_kind"] == kind
    assert detail["username_id"] == 9 and detail["nested"] == {"a": [1]}
    assert repo.calls == ["lock"]  # the chain append path, under the chain lock


@pytest.mark.parametrize(
    "kind", ["", "API_TOKEN_CREATED", "Policy_Imported", "policy_moved", "x"]
)
def test_unknown_kind_is_refused_and_nothing_is_written(kind: str) -> None:
    repo, tx = FakeRepo(), FakeTx()
    with pytest.raises(ValueError):
        raise_alert(repo, tx.on_commit, kind=kind, actor="system", action="a.b")
    assert repo.rows == [] and tx.hooks == []


@pytest.mark.parametrize(
    "detail",
    [{"alert": False}, {"alert_kind": "user_created"}, {"alert": True, "x": 1}],
)
def test_detail_cannot_override_the_alert_keys(detail: dict[str, object]) -> None:
    repo, tx = FakeRepo(), FakeTx()
    with pytest.raises(ValueError):
        raise_alert(
            repo,
            tx.on_commit,
            kind="totp_reset",
            actor="system",
            action="user.totp_reset",
            detail=detail,
        )
    assert repo.rows == [] and tx.hooks == []


def test_no_detail_still_has_the_two_keys() -> None:
    repo, tx = FakeRepo(), FakeTx()
    raise_alert(
        repo, tx.on_commit, kind="admin_created", actor="cli:root", action="user.create"
    )
    assert json.loads(repo.rows[0]["detail"]) == {
        "alert": True,
        "alert_kind": "admin_created",
    }


# ------------------------------------------------------------ CHK-M2-136


def test_counter_rises_by_one_only_when_the_hook_runs() -> None:
    kind = "role_granted"
    before = count(kind)
    repo, tx = FakeRepo(), FakeTx()
    raise_alert(
        repo, tx.on_commit, kind=kind, actor="user:1", action="user.role_change"
    )
    assert count(kind) == before  # not at call time
    assert len(tx.hooks) == 1
    tx.commit()
    assert count(kind) == before + 1
    others = {k: count(k) for k in SPEC_KINDS - {kind}}
    raise_alert(
        repo, tx.on_commit, kind=kind, actor="user:1", action="user.role_change"
    )
    tx.commit()
    assert count(kind) == before + 2
    assert {k: count(k) for k in SPEC_KINDS - {kind}} == others


def test_counter_does_not_move_on_rollback() -> None:
    kind = "totp_enrolled"
    before = count(kind)
    tx = FakeTx()
    raise_alert(
        FakeRepo(), tx.on_commit, kind=kind, actor="user:2", action="auth.totp_enrol"
    )
    tx.rollback()
    tx.commit()
    assert count(kind) == before


def test_failed_append_registers_no_hook() -> None:
    class Broken(FakeRepo):
        def insert(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("insert failed")

    tx = FakeTx()
    with pytest.raises(RuntimeError):
        raise_alert(
            Broken(),
            tx.on_commit,
            kind="user_created",
            actor="user:1",
            action="user.create",
        )
    assert tx.hooks == []


# ------------------------------------------------------------ CHK-M2-137


def test_every_kind_is_exported_from_zero_in_the_shared_registry() -> None:
    text = generate_latest(REGISTRY).decode()
    assert "# TYPE bitscan_alerts_total counter" in text
    for kind in SPEC_KINDS:
        assert f'bitscan_alerts_total{{kind="{kind}"}}' in text
    names = {m.name for m in REGISTRY.collect()}
    # REQ-055 (3) is superseded by REQ-086: the M3 metrics share this registry
    assert names == REGISTRY_FAMILIES


def test_registry_is_not_the_global_default() -> None:
    from prometheus_client import REGISTRY as DEFAULT

    assert REGISTRY is not DEFAULT
    assert (
        DEFAULT.get_sample_value("bitscan_alerts_total", {"kind": "user_created"})
        is None
    )


def test_no_metrics_route_in_create_app() -> None:
    paths = {getattr(r, "path", "") for r in create_app().routes}
    assert not any("metric" in p for p in paths)


def test_module_reexports_nothing_unexpected() -> None:
    assert callable(alerts_module.raise_alert)


def test_every_kind_is_exported_at_zero_before_any_alert() -> None:
    """In a fresh process, importing the module exports all ten kinds at 0."""
    import subprocess
    import sys

    code = (
        "from prometheus_client import generate_latest\n"
        "import bitscan_manager.services.audit.alerts\n"
        "from bitscan_manager.services.audit.metrics import REGISTRY\n"
        "print(generate_latest(REGISTRY).decode())\n"
    )
    out = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    for kind in SPEC_KINDS:
        assert f'bitscan_alerts_total{{kind="{kind}"}} 0.0' in out.stdout
