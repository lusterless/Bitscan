"""TP-M7-12 (TASK-153): M7 alert kinds, the import-failure counter and the
importer alert builders (REQ-162, REQ-165 to REQ-168).

CHK-M7-185 to -188 (tests/m7/test-plan.md). Expected values: TS §8.4 L1288 to
L1291 (import failures metric; every alert an audit entry with
``detail.alert = true`` counted in ``bitscan_alerts_total{kind}``; the import
alert carries every changed Execute and flags shadow, .ssh, .pem, .key, token,
credentials), TS §4.1 L530, §5.2 L699 (``bit_import.mode``), and the approved
answers #100 (a) to (d), #101 (actions, kinds, actors, metric), #103 (up to 100
differences), #23 (a move is audited, not alerted). The PostgreSQL half (one
entry per import in the right transaction, the fake sink) is TASK-154's.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from prometheus_client import generate_latest

from bitscan_manager.services.audit.alerts import ALERT_KINDS, raise_alert
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.importer import alerts as ia
from bitscan_manager.services.importer.model import Code, Finding

M7_KINDS = {
    "policy_imported",
    "policy_import_rejected",
    "policy_deleted",
    "policy_rebuilt",
    "policy_reenabled",
    "catalog_integrity_failed",
}
MODES = ("auto", "manual", "rebuild")


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def lock_chain(self) -> None:
        pass

    def head_row_hash(self) -> str | None:
        return self.rows[-1]["row_hash"] if self.rows else None

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
        return len(self.rows) + 1, "2026-10-27T12:00:00.000000Z", detail_json

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
                "actor": actor,
                "action": action,
                "target": target,
                "detail_text": detail_text,
                "detail": None if detail_text is None else json.loads(detail_text),
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


def alerts(kind: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind})
    return 0.0 if v is None else v


def failures(mode: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_import_failures_total", {"mode": mode})
    return 0.0 if v is None else v


@dataclass(frozen=True)
class Change:
    plugin_uuid: UUID
    plugin_name: str
    execute: str
    execute_sha256: str
    reason: str = "new"


def change(execute: str, name: str = "1.1 - Check", reason: str = "new") -> Change:
    import hashlib

    digest = hashlib.sha256(execute.encode()).hexdigest()
    return Change(uuid4(), name, execute, digest, reason)


def imported_event(changes: list[Change], **kw: Any) -> ia.AuditEvent:
    base: dict[str, Any] = {
        "policy_id": 7,
        "policy_name": "CIS Ubuntu 24.04 Level 1 - Server",
        "version": 2,
        "mode": "manual",
        "file_sha256": "a" * 64,
        "source_file": "uploaded/policy-7.bit",
        "plugins_added": 1,
        "plugins_updated": 2,
        "plugins_retired": 0,
        "renamed_from": None,
        "revived": False,
        "changed_executes": changes,
    }
    base.update(kw)
    return ia.imported(**base)


def emit_once(event: ia.AuditEvent, actor: str = "system") -> tuple[FakeRepo, FakeTx]:
    repo, tx = FakeRepo(), FakeTx()
    ia.emit(repo, tx.on_commit, event, actor=actor)
    assert len(repo.rows) == 1  # one entry per event (#100 (d))
    return repo, tx


# CHK-M7-185: kinds and export from zero ------------------------------------------


def test_m7_kinds_are_the_101_list_and_registered() -> None:
    from bitscan_manager.services.audit.alerts import M7_ALERT_KINDS

    assert set(M7_ALERT_KINDS) == M7_KINDS
    assert M7_KINDS <= set(ALERT_KINDS)
    assert "policy_moved" not in ALERT_KINDS and "policy_move" not in ALERT_KINDS


def test_m7_kinds_and_modes_are_exported_at_zero_in_a_fresh_process() -> None:
    code = (
        "from prometheus_client import generate_latest\n"
        "import bitscan_manager.services.importer.alerts\n"
        "from bitscan_manager.services.audit.metrics import REGISTRY\n"
        "print(generate_latest(REGISTRY).decode())\n"
    )
    out = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    for kind in M7_KINDS:
        assert f'bitscan_alerts_total{{kind="{kind}"}} 0.0' in out.stdout, kind
    assert "# TYPE bitscan_import_failures_total counter" in out.stdout
    for mode in MODES:
        assert f'bitscan_import_failures_total{{mode="{mode}"}} 0.0' in out.stdout
    assert out.stdout.count("bitscan_import_failures_total{") == 3  # no other mode


def test_raise_alert_still_refuses_an_unknown_kind() -> None:
    repo, tx = FakeRepo(), FakeTx()
    for kind in ("policy_moved", "Policy_Imported", "policy_imported "):
        with pytest.raises(ValueError):
            raise_alert(repo, tx.on_commit, kind=kind, actor="system", action="x")
    assert repo.rows == [] and tx.hooks == []


def test_registry_text_exposes_import_failures() -> None:
    text = generate_latest(REGISTRY).decode()
    assert "bitscan_import_failures_total" in text


# CHK-M7-186: the policy_imported alert and its flags -----------------------------


def test_imported_shape_carries_every_changed_execute_in_full() -> None:
    long = "cat /etc/os-release #" + "x" * 16000
    changes = [change("dpkg-query -W apparmor"), change(long), change("id -u")]
    ev = imported_event(changes, renamed_from="Old name", revived=True)
    assert (ev.action, ev.kind, ev.target) == (
        "policy.import",
        "policy_imported",
        "policy:7",
    )
    d = dict(ev.detail)
    assert d == {
        "policy_id": 7,
        "policy_name": "CIS Ubuntu 24.04 Level 1 - Server",
        "version": 2,
        "mode": "manual",
        "file_sha256": "a" * 64,
        "source_file": "uploaded/policy-7.bit",
        "plugins_added": 1,
        "plugins_updated": 2,
        "plugins_retired": 0,
        "renamed_from": "Old name",
        "revived": True,
        "changed_executes": [
            {
                "plugin_uuid": str(c.plugin_uuid),
                "plugin_name": c.plugin_name,
                "execute": c.execute,
                "execute_sha256": c.execute_sha256,
                "reason": c.reason,
                "flags": [],
            }
            for c in changes
        ],
    }
    repo, _ = emit_once(ev, actor="user:12")
    row = repo.rows[0]
    assert (row["actor"], row["action"], row["target"]) == (
        "user:12",
        "policy.import",
        "policy:7",
    )
    assert row["detail"]["alert"] is True
    assert row["detail"]["alert_kind"] == "policy_imported"
    stored = [c["execute"] for c in row["detail"]["changed_executes"]]
    assert stored == [c.execute for c in changes]  # in full, in order (#100 (b))
    assert len(stored[1]) == len(long)


def test_imported_with_no_changed_executes_has_an_empty_list() -> None:
    ev = imported_event([])
    assert ev.detail["changed_executes"] == []


@pytest.mark.parametrize(
    ("execute", "word"),
    [
        ("cat /etc/shadow", "shadow"),
        ("cat ~/.ssh/id_rsa", ".ssh"),
        ("cat /etc/ssl/private/x.pem", ".pem"),
        ("cat x.key", ".key"),
        ("cat /run/token", "token"),
        ("cat /etc/credentials", "credentials"),
        ("awk -F: '{print $2}' /etc/SHADOW", "shadow"),
        ("ls /root/.SSH", ".ssh"),
        ("openssl x509 -in /etc/ssl/certs/A.PEM", ".pem"),
        ("cat server.Key", ".key"),
        ("cat /var/lib/Token", "token"),
        ("cat ~/.aws/CREDENTIALS", "credentials"),
    ],
)
def test_each_flag_word_is_found_case_insensitively(execute: str, word: str) -> None:
    assert ia.flags(execute) == [word]
    ev = imported_event([change(execute)])
    assert ev.detail["changed_executes"][0]["flags"] == [word]  # type: ignore[index]


@pytest.mark.parametrize(
    "execute",
    [
        "dpkg-query -W -f='${Status}' apparmor 2>/dev/null",
        "grep -E '^PermitRootLogin' /etc/ssh/sshd_config",
        "stat -c %a /etc/ssh/ssh_host_ed25519_key",
        "sysctl -n kernel.randomize_va_space",
        "findmnt --task 1 -no OPTIONS /tmp",
        "systemctl is-enabled ssh",
    ],
)
def test_plain_commands_have_no_flags(execute: str) -> None:
    assert ia.flags(execute) == []


def test_several_words_are_listed_in_spec_order_once() -> None:
    cmd = "cat /run/token /etc/shadow ~/.ssh/a.pem /etc/shadow x.key credentials"
    assert ia.flags(cmd) == ["shadow", ".ssh", ".pem", ".key", "token", "credentials"]
    assert ia.FLAG_WORDS == ("shadow", ".ssh", ".pem", ".key", "token", "credentials")


def test_import_alert_counts_once_on_commit_and_not_on_rollback() -> None:
    before = alerts("policy_imported")
    repo, tx = emit_once(imported_event([change("id")]))
    assert alerts("policy_imported") == before  # nothing before COMMIT
    tx.commit()
    assert alerts("policy_imported") == before + 1
    repo2, tx2 = emit_once(imported_event([change("id")]))
    tx2.rollback()
    tx2.commit()
    assert alerts("policy_imported") == before + 1


# CHK-M7-187: the other builders -------------------------------------------------

CANARY = "CANARY-finding-message-3e1f"


def findings() -> list[Finding]:
    return [
        Finding(5, "Policy/PolicyStatus", Code.BIT003, f"bad {CANARY}"),
        Finding(14, "Policy/PluginsGroups/Plugin[1]/PluginId", Code.BIT004, CANARY),
        Finding(20, "Policy/PluginsGroups/Plugin[2]/PluginId", Code.BIT004, CANARY),
        Finding(11, "Policy/PluginsGroups/Plugin[1]/PluginName", Code.BIT101, CANARY),
    ]


def test_rejected_shape_target_and_no_finding_text() -> None:
    ev = ia.rejected(
        import_id=41,
        mode="auto",
        file_name="cis.bit",
        file_sha256="b" * 64,
        policy_id=None,
        findings=findings(),
    )
    assert (ev.action, ev.kind, ev.target) == (
        "policy.import_rejected",
        "policy_import_rejected",
        "cis.bit",
    )
    assert dict(ev.detail) == {
        "import_id": 41,
        "mode": "auto",
        "file_name": "cis.bit",
        "file_sha256": "b" * 64,
        "policy_id": None,
        "finding_count": 4,
        "codes": ["BIT003", "BIT004", "BIT101"],
    }
    repo, tx = emit_once(ev)
    assert CANARY not in repo.rows[0]["detail_text"]  # findings stay in bit_import
    matched = ia.rejected(
        import_id=42, mode="manual", file_name="", file_sha256="c" * 64,
        policy_id=9, findings=findings()[:1],
    )  # fmt: skip
    assert matched.target == "policy:9"
    unnamed = ia.rejected(
        import_id=43, mode="manual", file_name="", file_sha256="c" * 64,
        policy_id=None, findings=findings()[:1],
    )  # fmt: skip
    assert unnamed.target is None


@pytest.mark.parametrize("mode", MODES)
def test_count_failure_adds_one_per_mode_on_commit_only(mode: str) -> None:
    before = {m: failures(m) for m in MODES}
    tx = FakeTx()
    ia.count_failure(tx.on_commit, mode)  # type: ignore[arg-type]
    assert {m: failures(m) for m in MODES} == before  # not before COMMIT
    tx.commit()
    assert failures(mode) == before[mode] + 1
    assert all(failures(m) == before[m] for m in MODES if m != mode)
    rb = FakeTx()
    ia.count_failure(rb.on_commit, mode)  # type: ignore[arg-type]
    rb.rollback()
    rb.commit()
    assert failures(mode) == before[mode] + 1


@pytest.mark.parametrize("mode", ["Auto", "watch", "", "rebuild "])
def test_count_failure_refuses_an_unknown_mode(mode: str) -> None:
    tx = FakeTx()
    with pytest.raises(ValueError):
        ia.count_failure(tx.on_commit, mode)  # type: ignore[arg-type]
    assert tx.hooks == []


def test_rejected_alert_and_its_count_together() -> None:
    a0, f0 = alerts("policy_import_rejected"), failures("auto")
    repo, tx = FakeRepo(), FakeTx()
    ev = ia.rejected(
        import_id=1, mode="auto", file_name="x.bit", file_sha256="d" * 64,
        policy_id=None, findings=findings(),
    )  # fmt: skip
    ia.emit(repo, tx.on_commit, ev, actor="system")
    ia.count_failure(tx.on_commit, "auto")
    tx.commit()
    assert (alerts("policy_import_rejected"), failures("auto")) == (a0 + 1, f0 + 1)
    assert repo.rows[0]["detail"]["alert_kind"] == "policy_import_rejected"


@pytest.mark.parametrize(
    "reason",
    ["deleted through the API", "file removed", "file now holds another policy"],
)
def test_deleted_shape(reason: str) -> None:
    ev = ia.deleted(
        policy_id=3,
        policy_name="P",
        source_file="uploaded/policy-3.bit",
        reason=reason,  # type: ignore[arg-type]
    )
    assert (ev.action, ev.kind, ev.target) == (
        "policy.delete",
        "policy_deleted",
        "policy:3",
    )
    assert dict(ev.detail) == {
        "policy_id": 3,
        "policy_name": "P",
        "source_file": "uploaded/policy-3.bit",
        "reason": reason,
    }


def test_move_is_audited_but_not_an_alert() -> None:
    before = {k: alerts(k) for k in M7_KINDS}
    ev = ia.moved(policy_id=4, from_file="uploaded/policy-4.bit", to_file="x.bit")
    assert (ev.action, ev.kind, ev.target) == ("policy.move", None, "policy:4")
    repo, tx = emit_once(ev)
    assert tx.hooks == []  # no counter hook
    assert repo.rows[0]["detail"] == {"from": "uploaded/policy-4.bit", "to": "x.bit"}
    tx.commit()
    assert {k: alerts(k) for k in M7_KINDS} == before


@pytest.mark.parametrize(
    ("before", "after", "alert"),
    [
        ("disabled", "enabled", True),
        ("enabled", "disabled", False),
        ("enabled", "enabled", False),
        ("disabled", "disabled", False),
    ],
)
@pytest.mark.parametrize("by", ["patch", "file"])
def test_status_change_alerts_only_on_a_reenable(
    before: str, after: str, alert: bool, by: str
) -> None:
    ev = ia.status_change(
        policy_id=5, policy_name="P", before=before, after=after,  # type: ignore[arg-type]
        status_overridden=by == "patch", by=by,  # type: ignore[arg-type]
    )  # fmt: skip
    assert ev.action == "policy.status_change" and ev.target == "policy:5"
    assert ev.kind == ("policy_reenabled" if alert else None)
    assert dict(ev.detail) == {
        "policy_id": 5,
        "policy_name": "P",
        "from": before,
        "to": after,
        "status_overridden": by == "patch",
        "by": by,
    }
    n0 = alerts("policy_reenabled")
    repo, tx = emit_once(ev, actor="user:1")
    tx.commit()
    assert alerts("policy_reenabled") == n0 + (1 if alert else 0)
    assert ("alert" in repo.rows[0]["detail"]) is alert


def test_rebuilt_shape() -> None:
    tid = uuid4()
    ev = ia.rebuilt(
        task_id=tid, state="succeeded", files_imported=2, files_rejected=1,
        deleted_policy_ids=[4, 9], plugins_retired=3,
        removed_leftovers=["uploaded/policy-9.bit", "uploaded/policy-4.bit"],
    )  # fmt: skip
    assert (ev.action, ev.kind, ev.target) == (
        "bits.rebuild",
        "policy_rebuilt",
        f"task:{tid}",
    )
    assert dict(ev.detail) == {
        "task_id": str(tid),
        "state": "succeeded",
        "files_imported": 2,
        "files_rejected": 1,
        "deleted_policy_ids": [4, 9],
        "plugins_retired": 3,
        # crash-window ruling (user, 2026-10-27): in the given order
        "removed_leftovers": ["uploaded/policy-9.bit", "uploaded/policy-4.bit"],
    }
    repo, _ = emit_once(ev, actor="cli:root")
    assert repo.rows[0]["actor"] == "cli:root"


def test_integrity_failed_lists_the_first_100_and_the_total() -> None:
    diffs = [ia.Difference(f"policy:{i}", "sha256") for i in range(150)]
    ev = ia.integrity_failed(diffs)
    assert (ev.action, ev.kind, ev.target) == (
        "catalog.integrity_check",
        "catalog_integrity_failed",
        None,
    )
    assert ev.detail["difference_count"] == 150
    listed = ev.detail["differences"]
    assert listed == [{"subject": f"policy:{i}", "check": "sha256"} for i in range(100)]
    one = ia.integrity_failed([ia.Difference("a.bit", "file has no policy")])
    assert one.detail == {
        "difference_count": 1,
        "differences": [{"subject": "a.bit", "check": "file has no policy"}],
    }
    with pytest.raises(ValueError):
        ia.integrity_failed([])  # a clean catalog raises nothing


def test_every_event_is_valid_json_without_nul_or_lone_surrogates() -> None:
    bad = "a\x00b\ud800c.bit"
    events = [
        imported_event([change("id")], source_file=bad),
        ia.rejected(
            import_id=1,
            mode="auto",
            file_name=bad,
            file_sha256="e" * 64,
            policy_id=None,
            findings=findings(),
        ),  # fmt: skip
        ia.deleted(
            policy_id=1, policy_name="P", source_file=bad, reason="file removed"
        ),
        ia.moved(policy_id=1, from_file=bad, to_file=bad),
        ia.integrity_failed([ia.Difference(bad, "missing file")]),
    ]
    for ev in events:
        repo, _ = emit_once(ev)
        text = repo.rows[0]["detail_text"]
        assert "\x00" not in text and "\\u0000" not in text
        text.encode("utf-8")  # no lone surrogate (jsonb would refuse it)
        assert "a�b�c.bit" in text
    rej = events[1]
    assert rej.target == "a�b�c.bit"


def test_builders_never_log(caplog: pytest.LogCaptureFixture) -> None:
    command = "cat /etc/shadow # CANARY-exec-77"
    with caplog.at_level("DEBUG"):
        repo, tx = emit_once(imported_event([change(command)]))
        tx.commit()
    assert "CANARY-exec-77" not in caplog.text


# TASK-153 r2 (reviewer-m7): audit_log.target is VARCHAR(255) (TS §5.2).


@pytest.mark.parametrize("n", [250, 255, 300])
def test_rejected_fallback_target_fits_the_column_and_detail_keeps_it_whole(
    n: int,
) -> None:
    name = "uploaded/" + "a" * n + ".bit"
    ev = ia.rejected(
        import_id=1, mode="manual", file_name=name, file_sha256="f" * 64,
        policy_id=None, findings=findings(),
    )  # fmt: skip
    assert ev.target is not None
    assert len(ev.target) <= 255 and name.startswith(ev.target)
    assert len(ev.target) == min(len(name), 255)
    assert ev.detail["file_name"] == name


def test_rejected_target_counts_characters_not_bytes() -> None:
    name = "é" * 300 + ".bit"
    ev = ia.rejected(
        import_id=1, mode="manual", file_name=name, file_sha256="f" * 64,
        policy_id=None, findings=findings(),
    )  # fmt: skip
    assert ev.target == "é" * 255 and ev.detail["file_name"] == name


# TASK-153 r3: #100 (a) widened (user, 2026-10-27): new, changed and reactivated.


def test_each_entry_carries_its_reason_in_the_101_key_order() -> None:
    changes = [
        change("id -u", reason="new"),
        change("uname -r", reason="changed"),
        change("cat /etc/shadow", reason="reactivated"),
    ]
    raw = imported_event(changes).detail["changed_executes"]
    assert isinstance(raw, list)
    entries: list[dict[str, Any]] = raw
    assert [list(e) for e in entries] == [
        ["plugin_uuid", "plugin_name", "execute", "execute_sha256", "reason", "flags"]
    ] * 3
    assert [e["reason"] for e in entries] == ["new", "changed", "reactivated"]
    assert entries[2]["flags"] == ["shadow"]
    assert entries[2]["execute"] == "cat /etc/shadow"


# TASK-153 r4: the crash-window ruling (user, 2026-10-27): a rebuild lists the
# uploaded/ leftovers of deleted policies it removed.


def test_rebuilt_with_no_leftovers_lists_an_empty_list() -> None:
    ev = ia.rebuilt(
        task_id=uuid4(), state="failed", files_imported=0, files_rejected=0,
        deleted_policy_ids=[], plugins_retired=0, removed_leftovers=(),
    )  # fmt: skip
    assert ev.detail["removed_leftovers"] == []
    assert ev.detail["deleted_policy_ids"] == []


def test_rebuilt_leftover_paths_are_storable() -> None:
    bad = "uploaded/a" + chr(0) + "b" + chr(0xD800) + ".bit"
    ev = ia.rebuilt(
        task_id=uuid4(), state="succeeded", files_imported=1, files_rejected=0,
        deleted_policy_ids=[1], plugins_retired=0,
        removed_leftovers=("uploaded/policy-1.bit", bad),
    )  # fmt: skip
    repo, _ = emit_once(ev)
    text = repo.rows[0]["detail_text"]
    assert chr(0) not in text
    text.encode("utf-8")  # no lone surrogate
    fffd = chr(0xFFFD)
    assert repo.rows[0]["detail"]["removed_leftovers"] == [
        "uploaded/policy-1.bit",
        "uploaded/a" + fffd + "b" + fffd + ".bit",
    ]


def test_rebuilt_requires_the_leftovers_keyword() -> None:
    with pytest.raises(TypeError):
        ia.rebuilt(  # type: ignore[call-arg]
            task_id=uuid4(), state="succeeded", files_imported=0, files_rejected=0,
            deleted_policy_ids=[], plugins_retired=0,
        )  # fmt: skip
