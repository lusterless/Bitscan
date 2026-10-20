"""`db maintain` (TS §5.3): monthly scan_result partitions, as bitscan_owner.

Keeps the current UTC month and the next three, and drops whole partitions whose
upper bound is at least 400 days before now (#43, #44). Existing partitions are
found by their bounds, never by name. It deletes no rows. Drops are refused when
the clock looks wrong or the partitions have a gap (amendments to #44).
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg import IsolationLevel, sql
from pydantic import SecretStr

from bitscan_manager.db import OWNER_ROLE, dsn_secrets, scrub

FUTURE_MONTHS = 3
RETENTION = timedelta(days=400)
DEFAULT_PARTITION = "scan_result_default"
_FROM, _TO, _END = "FOR VALUES FROM ('", "') TO ('", "')"


class MaintainError(Exception):
    """Message is safe to print: the DSN and its password are removed."""


@dataclass(frozen=True)
class MonthRange:
    name: str
    lower: datetime
    upper: datetime


@dataclass(frozen=True)
class MaintainPlan:
    create: tuple[MonthRange, ...]
    drop: tuple[str, ...]
    # Set when the clock guard kept every drop; the run then exits 1.
    drops_refused: str | None = None


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")


def _month_start(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def _add_months(start: datetime, months: int) -> datetime:
    years, month_index = divmod(start.month - 1 + months, 12)
    return start.replace(year=start.year + years, month=month_index + 1)


def month_range(lower: datetime) -> MonthRange:
    start = _month_start(lower)
    return MonthRange(start.strftime("scan_result_%Y_%m"), start, _add_months(start, 1))


def plan_partitions(now: datetime, existing: list[MonthRange]) -> MaintainPlan:
    """Pure planner: the missing months of the window, and the expired ranges."""
    _require_aware(now)
    have = {part.lower for part in existing}
    first = _month_start(now)
    window = [month_range(_add_months(first, i)) for i in range(FUTURE_MONTHS + 1)]
    create = tuple(m for m in window if m.lower not in have)
    cutoff = now - RETENTION
    drop = tuple(p.name for p in existing if p.upper <= cutoff)
    return MaintainPlan(create=create, drop=drop)


def parse_bound(name: str, bound: str) -> MonthRange | None:
    """Range of a `FOR VALUES FROM (...) TO (...)` bound; None for DEFAULT.

    Raises MaintainError unless the range is exactly one UTC calendar month
    (a partition made by hand), so the run changes nothing.
    """
    if bound == "DEFAULT":
        return None
    lower = upper = None
    if bound.startswith(_FROM) and bound.endswith(_END) and bound.count(_TO) == 1:
        low_text, high_text = bound[len(_FROM) : -len(_END)].split(_TO)
        try:
            lower = datetime.fromisoformat(low_text)
            upper = datetime.fromisoformat(high_text)
        except ValueError:
            pass
    if lower is None or upper is None or lower.tzinfo is None or upper.tzinfo is None:
        raise MaintainError(
            f"partition {name!r} has bounds that are not UTC timestamps; "
            "nothing was changed"
        )
    expected = month_range(lower)
    if (lower, upper) != (expected.lower, expected.upper):
        raise MaintainError(
            f"partition {name!r} is not one UTC calendar month; nothing was changed"
        )
    return MonthRange(name, lower, upper)


def _existing(conn: psycopg.Connection[tuple[str, str]]) -> list[MonthRange]:
    rows = conn.execute(
        "SELECT c.relname::text, pg_get_expr(c.relpartbound, c.oid)"
        " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
        " WHERE i.inhparent = 'public.scan_result'::regclass"
    ).fetchall()
    parts = (parse_bound(name, bound) for name, bound in rows)
    return [part for part in parts if part is not None]


class _Refused(Exception):
    """Rolls back the transaction when the default partition blocks a create."""


def _blocked_month(
    conn: psycopg.Connection[tuple[str, str]], create: tuple[MonthRange, ...]
) -> str | None:
    """Name (YYYY-MM) of the first month to create that has default-partition rows.

    PostgreSQL would refuse the CREATE anyway; this names the month. No row data
    is read, only whether one exists.
    """
    for part in create:
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM scan_result_default"
            " WHERE job_created_at >= %s AND job_created_at < %s)",
            (part.lower, part.upper),
        ).fetchone()
        if row is not None and row[0]:
            return part.lower.strftime("%Y-%m")
    return None


def missing_months(existing: list[MonthRange]) -> list[str]:
    """UTC months (YYYY-MM) with no partition between the oldest and newest."""
    have = {part.lower for part in existing}
    if not have:
        return []
    month, last, missing = min(have), max(have), []
    while month < last:
        if month not in have:
            missing.append(month.strftime("%Y-%m"))
        month = _add_months(month, 1)
    return missing


def _clock_doubt(
    conn: psycopg.Connection[tuple[str, str]],
    now: datetime,
    existing: list[MonthRange],
) -> str | None:
    """Why drops must wait (amendments to #44), or None. Never reads row data.

    `existing` is read before this run's creates, so a window made at a skewed
    clock by an earlier run shows up as a gap (guard (c)).
    """
    clock = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not any(part.lower <= now < part.upper for part in existing):
        return f"no partition contains the clock time {clock}"
    gap = missing_months(existing)
    if gap:
        shown = ", ".join(gap[:12]) + (f" and {len(gap) - 12} more" if gap[12:] else "")
        return (
            f"scan_result partitions are not contiguous at the clock time {clock},"
            f" missing {shown}; remove stray partitions"
        )
    # Same as max(job_created_at) > now, but pruned to current and future months.
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM scan_result WHERE job_created_at > %s)",
        (now,),
    ).fetchone()
    if row is not None and row[0]:
        return f"scan_result has rows later than the clock time {clock}"
    return None


def _apply(dsn: str, now: datetime) -> MaintainPlan:
    with psycopg.connect(dsn) as conn:
        conn.isolation_level = IsolationLevel.READ_COMMITTED
        conn.execute("SET ROLE bitscan_owner")
        row = conn.execute("SELECT current_user::text").fetchone()
        if row is None or row[0] != OWNER_ROLE:
            raise MaintainError(f"SET ROLE did not give {OWNER_ROLE!r}")
        # Bounds render as ISO text in UTC, which parse_bound() expects.
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute("SET DateStyle = 'ISO, YMD'")
        conn.commit()
        blocked: str | None = None
        refused = False
        try:
            with conn.transaction():
                # A second run waits here, then plans from what the first made.
                conn.execute("SELECT pg_advisory_xact_lock(hashtext('db_maintain'))")
                existing = _existing(conn)
                plan = plan_partitions(now, existing)
                doubt = _clock_doubt(conn, now, existing) if plan.drop else None
                if doubt is not None:
                    plan = replace(
                        plan,
                        drop=(),
                        drops_refused=(
                            f"drops refused: {doubt}; {len(plan.drop)} partition(s)"
                            " past retention were kept, check the system clock"
                        ),
                    )
                blocked = _blocked_month(conn, plan.create)
                if blocked is not None:
                    raise _Refused
                for part in plan.create:
                    conn.execute(
                        sql.SQL(
                            "CREATE TABLE {} PARTITION OF scan_result"
                            " FOR VALUES FROM ({}) TO ({})"
                        ).format(
                            sql.Identifier(part.name),
                            sql.Literal(part.lower),
                            sql.Literal(part.upper),
                        )
                    )
                for name in plan.drop:
                    conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(name)))
        except (_Refused, psycopg.errors.CheckViolation):
            refused = True
    if refused:
        month = f" for {blocked}" if blocked else ""
        raise MaintainError(
            f"{DEFAULT_PARTITION} holds rows in the range of the partition to create"
            f"{month}; nothing was changed"
        )
    return plan


def run_maintain(dsn: SecretStr, now: datetime | None = None) -> MaintainPlan:
    """Create missing partitions and drop expired ones in one transaction.

    `now` is injectable for tests and must be timezone-aware; the CLI uses the
    real UTC clock. If the clock guard keeps the drops, the creates still
    commit and the plan carries `drops_refused`.
    """
    if now is not None:
        _require_aware(now)
    secret = dsn.get_secret_value()
    secrets = dsn_secrets(secret)
    message: str | None = None
    try:
        return _apply(secret, now or datetime.now(UTC))
    except MaintainError as exc:
        message = str(exc)
    except Exception as exc:
        message = scrub(f"{type(exc).__name__}: {exc}", secrets)
    # Raised outside the except blocks, so the original error is not chained.
    raise MaintainError(message)
