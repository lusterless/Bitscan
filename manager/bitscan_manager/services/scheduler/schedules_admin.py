"""Scan schedule management (TS §6.2 L1124, §4.4 L557, §4.3 L550, §5.2
L846–L857; REQ-224, REQ-227; open questions #122 (h), (i), #128 (d), (h),
(i), #129 (a); plan work/plans/TASK-203.md §4).

Any operator may create, read, change or delete any schedule (#128 (i)).
`policy_id` never changes: a new policy is a new schedule. A schedule of a
deleted policy can be neither created nor enabled (409); a disabled policy is
allowed, its runs are skipped (L557). `next_run_at` is the next fire strictly
after now, computed on create, on a cron or time-zone change and on enable;
disabling leaves it (the tick ignores disabled rows). Each change writes one
audit entry in its transaction, decided with the row locked. A schedule holds
no command text: the target, cron and name are not secret.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from bitscan_manager.repositories import schedules
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.schedules import ScheduleRow
from bitscan_manager.runtime import Tx
from bitscan_manager.services.jobs.queue import PolicyNotFound
from bitscan_manager.services.jobs.targets import Target, parse_target
from bitscan_manager.services.scheduler.cron import (
    InvalidSchedule,
    next_fire,
    parse_schedule,
)
from bitscan_manager.services.users import TxAudit

NAME_MAX: Final = 128  # scan_schedule.name VARCHAR(128)
PATCHABLE: Final = frozenset({"name", "target", "cron", "timezone", "enabled"})


class ScheduleNotFound(Exception):
    """No schedule has this id (404)."""


class ScheduleConflict(Exception):
    """The schedule's policy is deleted (409, #122 (h))."""


class InvalidField(ValueError):
    """A field outside the rules; the message names the field, never the input."""

    def __init__(self, field: str) -> None:
        super().__init__(f"Invalid request: {field}")
        self.field = field


def _name(value: object) -> str:
    """Stored as given: 1–128 characters of storable text (no U+0000, no lone
    surrogate; builder checklist 1)."""
    if not isinstance(value, str) or not 1 <= len(value) <= NAME_MAX or "\x00" in value:
        raise InvalidField("name")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidField("name") from None
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidSchedule("cron" if field == "cron" else "timezone")
    return value


def _request(target: Target) -> dict[str, Any]:
    """The target as stored (#122 (h)): the request, agent ids lowercase; it is
    resolved at each run."""
    if target.kind == "agents":
        return {"agents": [str(a) for a in target.agents]}
    if target.kind == "tags":
        return {"tags": list(target.tags)}
    return {"all": True}


def _deleted(tx: Tx, policy_id: int) -> bool:
    """Read FOR SHARE (TASK-201 r1), so a racing policy delete either commits
    first (seen here: 409) or waits and then disables what this transaction
    wrote (TS §4.3 L550). Taken before any schedule row lock: the delete
    locks the policy and then the schedule rows, so this order cannot
    deadlock with it."""
    state = schedules.policy_state(tx.conn, policy_id, lock=True)
    if state is None:
        raise PolicyNotFound
    return state[1]


def _audit(tx: Tx, user_id: int, action: str, schedule_id: int, detail: Any) -> None:
    audit = TxAudit(PgAuditRepo(tx.conn), tx.on_commit)
    audit.audit(f"user:{user_id}", action, f"scan_schedule:{schedule_id}", detail)


def _when(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def create(
    tx: Tx,
    *,
    name: object,
    policy_id: int,
    target: object,
    cron: object,
    timezone: object = "UTC",
    enabled: object = True,
    user_id: int,
    now: datetime,
) -> ScheduleRow:
    """A new schedule; validated before anything is written."""
    checked_name = _name(name)
    stored = _request(parse_target(target))
    schedule = parse_schedule(_text(cron, "cron"), _text(timezone, "timezone"))
    if not isinstance(enabled, bool):
        raise InvalidField("enabled")
    if _deleted(tx, policy_id):
        raise ScheduleConflict
    row = schedules.insert(
        tx.conn,
        name=checked_name,
        policy_id=policy_id,
        target=stored,
        cron=schedule.cron,
        timezone=schedule.timezone,
        enabled=enabled,
        next_run_at=next_fire(schedule, now),
        created_by=user_id,
    )
    detail = {
        "name": row.name,
        "policy_id": row.policy_id,
        "target": row.target,
        "cron": row.cron,
        "timezone": row.timezone,
        "enabled": row.enabled,
        "next_run_at": _when(row.next_run_at),
    }
    _audit(tx, user_id, "scan_schedule.create", row.schedule_id, detail)
    return row


def update(
    tx: Tx,
    schedule_id: int,
    *,
    changes: Mapping[str, object],
    user_id: int,
    now: datetime,
) -> ScheduleRow:
    """Applies a non-empty subset of name, target, cron, timezone, enabled."""
    if not changes or not PATCHABLE.issuperset(changes):
        raise InvalidField("body")
    values: dict[str, object] = {}
    if "name" in changes:
        values["name"] = _name(changes["name"])
    if "target" in changes:
        values["target"] = _request(parse_target(changes["target"]))
    if "enabled" in changes:
        if not isinstance(changes["enabled"], bool):
            raise InvalidField("enabled")
        values["enabled"] = changes["enabled"]
    enabling = values.get("enabled") is True
    if enabling:  # policy_id never changes, so the unlocked read is stable
        before = schedules.get(tx.conn, schedule_id)
        if before is None:
            raise ScheduleNotFound
        if _deleted(tx, before.policy_id):  # policy FOR SHARE first, then the row
            raise ScheduleConflict
    current = schedules.get(tx.conn, schedule_id, lock=True)
    if current is None:
        raise ScheduleNotFound
    if "cron" in changes or "timezone" in changes or enabling:
        # Checked together, also when only one of the two changes.
        cron = _text(changes.get("cron", current.cron), "cron")
        timezone = _text(changes.get("timezone", current.timezone), "timezone")
        schedule = parse_schedule(cron, timezone)
        if "cron" in changes or "timezone" in changes:
            values["cron"], values["timezone"] = schedule.cron, schedule.timezone
        values["next_run_at"] = next_fire(schedule, now)
    row = schedules.update(tx.conn, schedule_id, values)
    if row is None:  # the row is locked, so it cannot have gone
        raise ScheduleNotFound
    detail = {
        key: _when(row.next_run_at) if key == "next_run_at" else values[key]
        for key in sorted(values)
    }
    _audit(tx, user_id, "scan_schedule.update", schedule_id, detail)
    return row


def delete(tx: Tx, schedule_id: int, *, user_id: int) -> None:
    """Removes the schedule; its scans keep their rows with schedule_id NULL."""
    current = schedules.get(tx.conn, schedule_id, lock=True)
    if current is None or not schedules.delete(tx.conn, schedule_id):
        raise ScheduleNotFound
    detail = {"name": current.name, "policy_id": current.policy_id}
    _audit(tx, user_id, "scan_schedule.delete", schedule_id, detail)


def get(tx: Tx, schedule_id: int) -> ScheduleRow:
    row = schedules.get(tx.conn, schedule_id)
    if row is None:
        raise ScheduleNotFound
    return row


def list_page(tx: Tx, *, limit: int, after_id: int | None) -> list[ScheduleRow]:
    """One page ordered by schedule_id, after the cursor's id."""
    return schedules.page(tx.conn, limit, after_id)
