"""Schedule cron and time zone (TS §4.4 L557, §5.2 `scan_schedule.cron`,
`timezone`, §2.1 L103; REQ-223; open questions #128 (a)–(c)).

The cron is five-field crontab(5): minute, hour, day of month, month, day of
week, with `*`, lists, ranges, steps on `*` or a range, and month and weekday
names; no seconds, no `@` macros, nothing APScheduler adds (`last`, `1st
mon`, ...). APScheduler 3 differs from crontab(5) in two ways (#128 (a)):
- it numbers weekdays from Monday = 0, while crontab(5) has Sunday = 0 or 7;
  the weekday field is therefore expanded here to the set of days crontab(5)
  means (also for steps and ranges from 0, where a per-number rename would
  change the days) and handed over as weekday names;
- it fires when day of month AND day of week match, crontab(5) when either
  does if both are restricted; a cron restricting both is refused, so the
  two never differ.

DST (user ruling, decisions 2026-10-30): the spring gap keeps APScheduler
3.11's shifted run; a repeated fall-back wall time runs once, at its first
occurrence (`next_fire` drops the second). Pure: the
instant is an argument; no I/O, no logging. Errors name the field only.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

CRON_MAX: Final = 64  # scan_schedule.cron VARCHAR(64)
TIMEZONE_MAX: Final = 64  # scan_schedule.timezone VARCHAR(64)
_FIELDS: Final = ("minute", "hour", "day", "month", "day_of_week")
_BOUNDS: Final = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 7),  # crontab(5): 0 and 7 are Sunday
}
_MONTHS: Final = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
_DAYS: Final = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # crontab(5) order
# A cron that fires is checked to fire within this span of a fixed instant
# (#128 (c)); every five-field cron accepted here repeats within 4 years.
_FIRES_WITHIN: Final = timedelta(days=5 * 366)
_REFERENCE: Final = datetime(2000, 1, 1, tzinfo=UTC)


class InvalidSchedule(ValueError):
    def __init__(self, field: Literal["cron", "timezone"]) -> None:
        super().__init__(f"Invalid request: {field}")
        self.field: Literal["cron", "timezone"] = field


@dataclass(frozen=True)
class Schedule:
    cron: str
    timezone: str
    trigger: CronTrigger


def _value(text: str, field: str) -> int:
    if text.isdigit():
        number = int(text)
    elif field == "month" and text.lower() in _MONTHS:
        number = _MONTHS.index(text.lower()) + 1
    elif field == "day_of_week" and text.lower() in _DAYS:
        number = _DAYS.index(text.lower())
    else:
        raise InvalidSchedule("cron")
    low, high = _BOUNDS[field]
    if not low <= number <= high:
        raise InvalidSchedule("cron")
    return number


def _ranges(text: str, field: str) -> Iterator[range]:
    """Each list item of one field as a range, checked to crontab(5)."""
    for item in text.split(","):
        base, slash, step_text = item.partition("/")
        step = 1
        if slash:
            if not step_text.isdigit() or int(step_text) < 1:
                raise InvalidSchedule("cron")
            step = int(step_text)
        if base == "*":
            first, last = _BOUNDS[field]
        elif "-" in base:
            low_text, _, high_text = base.partition("-")
            first, last = _value(low_text, field), _value(high_text, field)
            if first > last:
                raise InvalidSchedule("cron")
        elif slash:  # a step needs `*` or a range
            raise InvalidSchedule("cron")
        else:
            first = last = _value(base, field)
        yield range(first, last + 1, step)


def _weekdays(text: str) -> str:
    """The crontab(5) weekday field as APScheduler weekday names."""
    days = {n % 7 for r in _ranges(text, "day_of_week") for n in r}  # 7 is Sunday
    # APScheduler order is Monday first: crontab(5) day d is index (d + 6) % 7.
    return ",".join(_DAYS[d] for d in sorted(days, key=lambda d: (d + 6) % 7))


@cache
def _known_zones() -> frozenset[str]:
    """The IANA names the host's zoneinfo (or the locked tzdata) holds, read
    once. An exact, case-sensitive match: on Windows a resource lookup also
    loads `utc` or `UTC ` through the case-insensitive file system."""
    return frozenset(available_timezones())


def _zone(name: str) -> ZoneInfo:
    if (
        not 1 <= len(name) <= TIMEZONE_MAX
        or not name.isascii()
        or not name.isprintable()
        or name == "localtime"
        or name.startswith("/")
        or ".." in name
        or "\\" in name
        or name not in _known_zones()
    ):
        raise InvalidSchedule("timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise InvalidSchedule("timezone") from None


def parse_schedule(cron: str, timezone: str) -> Schedule:
    """The validated schedule, or InvalidSchedule naming `cron` or
    `timezone`."""
    zone = _zone(timezone)
    if len(cron) > CRON_MAX or not cron.isascii():
        raise InvalidSchedule("cron")
    parts = cron.split()
    if len(parts) != len(_FIELDS):
        raise InvalidSchedule("cron")
    fields = dict(zip(_FIELDS, parts, strict=True))
    if fields["day"] != "*" and fields["day_of_week"] != "*":
        raise InvalidSchedule("cron")  # #128 (a): both day fields restricted
    for name in ("minute", "hour", "day", "month"):
        for _ in _ranges(fields[name], name):
            pass  # checks only; APScheduler reads these fields as crontab(5) does
    if fields["day_of_week"] != "*":
        fields["day_of_week"] = _weekdays(fields["day_of_week"])
    try:
        trigger = CronTrigger(timezone=zone, **fields)
    except ValueError:
        raise InvalidSchedule("cron") from None
    first = trigger.get_next_fire_time(None, _REFERENCE)
    if first is None or first > _REFERENCE + _FIRES_WITHIN:
        raise InvalidSchedule("cron")  # #128 (c): never fires
    return Schedule(cron=cron, timezone=timezone, trigger=trigger)


def _repeated(fire: datetime, zone: ZoneInfo) -> bool:
    """True for the second occurrence of a local wall time that happens twice
    (the fall-back hour): fold 1 of an ambiguous local time."""
    local = fire.astimezone(UTC).astimezone(zone)  # fold set correctly
    return local.fold == 1 and local.replace(fold=0).utcoffset() != local.utcoffset()


def next_fire(schedule: Schedule, after: datetime) -> datetime:
    """The next fire time strictly after `after`, in UTC. DST (user ruling,
    decisions 2026-10-30): a local time skipped by the spring gap keeps
    APScheduler's shifted run; a local time repeated on the fall-back day runs
    once, at its first occurrence."""
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be time-zone aware")
    zone = ZoneInfo(schedule.timezone)
    start = after
    while True:
        fire = schedule.trigger.get_next_fire_time(
            None, start + timedelta(microseconds=1)
        )
        if fire is None:
            raise ValueError("the schedule does not fire again")
        result: datetime = fire.astimezone(UTC)
        if result <= start:
            raise ValueError("the schedule did not move forward")
        if not _repeated(result, zone):
            return result
        start = result  # the wall time already ran at its first occurrence
