"""TP-M9-07: cron and time zone (TASK-191; REQ-223).

TS §4.4 L557, §5.2 L851-L852, §2.1 L103; open questions #128 (a)-(c);
decisions 2026-10-30 "M9 early rulings" (2) for the DST rows. Expected
fire times are worked out from crontab(5) and the IANA rules by hand, not
from the code. CHK-M9-067 to -074.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bitscan_manager.services.scheduler.cron import (
    InvalidSchedule,
    next_fire,
    parse_schedule,
)

# A Wednesday.
REF = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
CANARY = "M9CANARY-" + uuid.uuid4().hex
SUN, MON, TUE, WED, THU, FRI, SAT = 6, 0, 1, 2, 3, 4, 5  # datetime.weekday()


def fires(
    cron: str, tz: str = "UTC", after: datetime = REF, n: int = 5
) -> list[datetime]:
    s = parse_schedule(cron, tz)
    out: list[datetime] = []
    t = after
    for _ in range(n):
        nxt = next_fire(s, t)
        assert nxt > t, "next_fire did not move forward"
        t = nxt
        out.append(t)
    return out


def weekdays(cron: str, tz: str = "UTC", days: int = 21) -> set[int]:
    """Local weekdays the cron fires on over the next `days` days."""
    zone = ZoneInfo(tz)
    s = parse_schedule(cron, tz)
    seen: set[int] = set()
    t = REF
    end = REF + timedelta(days=days)
    for _ in range(10_000):  # bounded: a next_fire that does not advance fails here
        nxt = next_fire(s, t)
        assert nxt > t, "next_fire did not move forward"
        t = nxt
        if t > end:
            return seen
        seen.add(t.astimezone(zone).weekday())
    raise AssertionError("more fires than the bound")


def u(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- CHK-M9-067: weekday 0 and 7 are Sunday ---------------------------------


@pytest.mark.parametrize(
    "cron", ["0 3 * * 0", "0 3 * * 7", "0 3 * * sun", "0 3 * * SUN"]
)
def test_sunday_forms_utc(cron: str) -> None:
    assert fires(cron) == [
        u(2026, 11, 1, 3),
        u(2026, 11, 8, 3),
        u(2026, 11, 15, 3),
        u(2026, 11, 22, 3),
        u(2026, 11, 29, 3),
    ]


@pytest.mark.parametrize("cron", ["0 3 * * 0", "0 3 * * 7", "0 3 * * sun"])
def test_sunday_forms_in_kolkata(cron: str) -> None:
    # 03:00 IST (UTC+05:30) on Sunday = 21:30 UTC on Saturday.
    got = fires(cron, "Asia/Kolkata", n=3)
    assert got == [
        u(2026, 10, 31, 21, 30),
        u(2026, 11, 7, 21, 30),
        u(2026, 11, 14, 21, 30),
    ]
    assert all(t.astimezone(ZoneInfo("Asia/Kolkata")).weekday() == SUN for t in got)


def test_monday() -> None:
    assert fires("0 3 * * 1", n=3) == [
        u(2026, 11, 2, 3),
        u(2026, 11, 9, 3),
        u(2026, 11, 16, 3),
    ]


# --- CHK-M9-068: crontab(5) weekday syntax ----------------------------------


@pytest.mark.parametrize(
    ("dow", "days"),
    [
        ("1-5", {MON, TUE, WED, THU, FRI}),
        ("mon-fri", {MON, TUE, WED, THU, FRI}),
        ("5-7", {FRI, SAT, SUN}),
        ("0-5", {SUN, MON, TUE, WED, THU, FRI}),
        ("0-3", {SUN, MON, TUE, WED}),
        ("0,6", {SUN, SAT}),
        ("6,7", {SAT, SUN}),
        ("sat,sun", {SAT, SUN}),
        ("*/2", {SUN, TUE, THU, SAT}),
        ("1-5/2", {MON, WED, FRI}),
        ("0-6", {SUN, MON, TUE, WED, THU, FRI, SAT}),
        ("0-7", {SUN, MON, TUE, WED, THU, FRI, SAT}),
        ("*", {SUN, MON, TUE, WED, THU, FRI, SAT}),
        ("7", {SUN}),
        ("0", {SUN}),
        ("3", {WED}),
        ("6", {SAT}),
        ("2,4", {TUE, THU}),
    ],
)
def test_weekday_field(dow: str, days: set[int]) -> None:
    assert weekdays(f"0 3 * * {dow}") == days


# --- CHK-M9-069: other fields -----------------------------------------------


def test_minute_step() -> None:
    assert fires("*/15 * * * *", n=5) == [
        u(2026, 10, 28, 12, 15),
        u(2026, 10, 28, 12, 30),
        u(2026, 10, 28, 12, 45),
        u(2026, 10, 28, 13, 0),
        u(2026, 10, 28, 13, 15),
    ]


@pytest.mark.parametrize("cron", ["0 0 1 jan *", "0 0 1 1 *", "0 0 1 JAN *"])
def test_month_name(cron: str) -> None:
    assert fires(cron, n=2) == [u(2027, 1, 1), u(2028, 1, 1)]


def test_31st_only_in_31_day_months() -> None:
    assert fires("0 0 31 * *", n=4) == [
        u(2026, 10, 31),
        u(2026, 12, 31),
        u(2027, 1, 31),
        u(2027, 3, 31),
    ]


def test_february_29_fires_in_leap_years() -> None:
    assert fires("0 0 29 2 *", n=2) == [u(2028, 2, 29), u(2032, 2, 29)]


def test_lists_ranges_and_steps_in_hour_and_day() -> None:
    assert fires("0 9-17/4 * * *", n=4) == [
        u(2026, 10, 28, 13),
        u(2026, 10, 28, 17),
        u(2026, 10, 29, 9),
        u(2026, 10, 29, 13),
    ]
    assert fires("30 6 1,15 * *", n=3) == [
        u(2026, 11, 1, 6, 30),
        u(2026, 11, 15, 6, 30),
        u(2026, 12, 1, 6, 30),
    ]


def test_new_york_follows_its_offset() -> None:
    # 12:00 EDT (UTC-4) until 2026-11-01, then 12:00 EST (UTC-5).
    got = fires("0 12 * * *", "America/New_York", after=u(2026, 10, 30, 0), n=4)
    assert got == [
        u(2026, 10, 30, 16),
        u(2026, 10, 31, 16),
        u(2026, 11, 1, 17),
        u(2026, 11, 2, 17),
    ]


# --- CHK-M9-070: time zone honoured -----------------------------------------


def test_kolkata_0900_is_0330_utc() -> None:
    got = fires("0 9 * * *", "Asia/Kolkata", n=3)
    assert got == [
        u(2026, 10, 29, 3, 30),
        u(2026, 10, 30, 3, 30),
        u(2026, 10, 31, 3, 30),
    ]


def test_default_utc_name() -> None:
    assert fires("0 9 * * *", "UTC", n=1) == [u(2026, 10, 29, 9)]
    assert fires("0 9 * * *", "Etc/UTC", n=1) == [u(2026, 10, 29, 9)]


# --- CHK-M9-071: DST, Europe/London -----------------------------------------
# 2026-03-29: 01:00 GMT -> 02:00 BST (local 01:00-01:59 does not exist).
# 2026-10-25: 02:00 BST -> 01:00 GMT (local 01:00-01:59 happens twice).


def test_london_0230_spring_day_fires_once() -> None:
    # 02:30 BST exists once: 01:30 UTC. The day before is GMT (02:30 UTC).
    got = fires("30 2 * * *", "Europe/London", after=u(2026, 3, 27, 12), n=3)
    assert got == [u(2026, 3, 28, 2, 30), u(2026, 3, 29, 1, 30), u(2026, 3, 30, 1, 30)]


def test_london_0230_autumn_day_fires_once() -> None:
    # 02:30 on 10-25 is GMT (after the fall back): 02:30 UTC.
    got = fires("30 2 * * *", "Europe/London", after=u(2026, 10, 23, 12), n=3)
    assert got == [
        u(2026, 10, 24, 1, 30),
        u(2026, 10, 25, 2, 30),
        u(2026, 10, 26, 2, 30),
    ]


def _record(record_property: Any, label: str, got: list[datetime]) -> None:
    record_property(label, [t.isoformat() for t in got])


def test_london_0130_spring_gap_is_shifted(record_property: Any) -> None:
    """User decision 2026-10-30 ("DST behaviour for scheduled scans"), as
    standard cron: a local time that does not exist that day is shifted
    forward by the gap. 01:30 on 2026-03-29 fires once, at 01:30Z (02:30 BST)."""
    got = fires("30 1 * * *", "Europe/London", after=u(2026, 3, 27, 12), n=3)
    _record(record_property, "spring_gap", got)
    assert got == [u(2026, 3, 28, 1, 30), u(2026, 3, 29, 1, 30), u(2026, 3, 30, 0, 30)]


def test_london_0130_autumn_repeat_fires_once(record_property: Any) -> None:
    """User decision 2026-10-30: a repeated local time runs once, at its first
    occurrence. 01:30 on 2026-10-25 fires at 00:30Z (01:30 BST) only."""
    got = fires("30 1 * * *", "Europe/London", after=u(2026, 10, 24, 12), n=3)
    _record(record_property, "autumn_repeat", got)
    assert got == [
        u(2026, 10, 25, 0, 30),
        u(2026, 10, 26, 1, 30),
        u(2026, 10, 27, 1, 30),
    ]


def test_london_0130_repeat_seen_from_inside_the_repeated_hour() -> None:
    """Asked from between the two occurrences (00:45Z = 01:45 BST, before the
    fall back), the second 01:30 (01:30Z, GMT) is not a new fire."""
    s = parse_schedule("30 1 * * *", "Europe/London")
    assert next_fire(s, u(2026, 10, 25, 0, 30)) == u(2026, 10, 26, 1, 30)
    assert next_fire(s, u(2026, 10, 25, 0, 45)) == u(2026, 10, 26, 1, 30)


def test_london_every_15_minutes_through_the_repeat() -> None:
    """`*/15 1 * * *` London on 2026-10-25: each local 01:xx fires once, at the
    first (BST) occurrence: 00:00, 00:15, 00:30, 00:45Z; then the next day."""
    got = fires("*/15 1 * * *", "Europe/London", after=u(2026, 10, 24, 23, 59), n=5)
    assert got == [
        u(2026, 10, 25, 0, 0),
        u(2026, 10, 25, 0, 15),
        u(2026, 10, 25, 0, 30),
        u(2026, 10, 25, 0, 45),
        u(2026, 10, 26, 1, 0),
    ]


def test_london_every_30_minutes_across_the_repeated_hour() -> None:
    """`*/30 * * * *` London from 2026-10-24T23:50Z: local 01:00 and 01:30 run
    at their BST occurrence (00:00Z, 00:30Z); their GMT repeats (01:00Z,
    01:30Z) do not run; 02:00 GMT is 02:00Z."""
    got = fires("*/30 * * * *", "Europe/London", after=u(2026, 10, 24, 23, 50), n=4)
    assert got == [
        u(2026, 10, 25, 0, 0),
        u(2026, 10, 25, 0, 30),
        u(2026, 10, 25, 2, 0),
        u(2026, 10, 25, 2, 30),
    ]


def test_spring_gap_every_30_minutes() -> None:
    """`*/30 * * * *` London on 2026-03-29: 00:30 GMT (00:30Z), then 02:00 BST
    (01:00Z); the nonexistent 01:00 and 01:30 shift onto 02:00 and 02:30 BST,
    so no instant fires twice and the sequence stays strictly increasing."""
    got = fires("*/30 * * * *", "Europe/London", after=u(2026, 3, 29, 0, 10), n=4)
    assert got[0] == u(2026, 3, 29, 0, 30)
    assert len(set(got)) == len(got)
    assert all(a < b for a, b in zip(got, got[1:], strict=False))
    assert u(2026, 3, 29, 1, 0) in got  # 02:00 BST


def test_utc_schedule_unchanged_on_london_dst_days() -> None:
    assert fires("30 1 * * *", "UTC", after=u(2026, 10, 24, 12), n=2) == [
        u(2026, 10, 25, 1, 30),
        u(2026, 10, 26, 1, 30),
    ]


# --- CHK-M9-072: refused crons ----------------------------------------------

BAD_CRONS = [
    "0 0 3 * * *",
    "0 3 * *",
    "",
    "   ",
    "@daily",
    "@reboot",
    "0 0 1 * 1",
    "0 0 1-5 * mon",
    "0 0 */2 * 1-5",
    "0 0 30 2 *",
    "0 0 31 4 *",
    "0 0 31 2,4,6,9,11 *",
    "61 * * * *",
    "60 * * * *",
    "* 24 * * *",
    "* * 0 * *",
    "* * 32 * *",
    "* * * 0 *",
    "* * * 13 *",
    "* * * * 8",
    "-1 * * * *",
    "0 0 ? * *",
    "0 0 L * *",
    "0 0 * * 1#2",
    "0 0 15W * *",
    "0 0 * * 5L",
    "0 0 last * *",
    "*/0 * * * *",
    "5/10 * * * *",
    "5-1 * * * *",
    "0 0 * * sat-sun",
    "a * * * *",
    "0 0 * * funday",
    "\u0660 * * * *",
    "0 0 1 xyz *",
    "1,,2 * * * *",
    "0 0 * * 1-",
]


@pytest.mark.parametrize("cron", BAD_CRONS, ids=lambda c: repr(c)[:40])
def test_refused_crons(cron: str) -> None:
    with pytest.raises(InvalidSchedule) as info:
        parse_schedule(cron, "UTC")
    assert info.value.field == "cron"
    assert isinstance(info.value, ValueError)


def test_cron_length_bound() -> None:
    # crontab(5) separates fields by any run of blanks: a valid cron padded to
    # exactly 64 characters is accepted, one more blank makes it 65.
    exact = "0" + " " * 56 + "3 * * *"
    assert len(exact) == 64
    assert fires(exact, n=1) == [u(2026, 10, 29, 3)]
    listy = "0,5,10,15,20,25,30,35,40,45,50,55 1,2,3,4,5,6,7,8,9,10,11 * * *"
    assert len(listy) <= 64
    parse_schedule(listy, "UTC")
    with pytest.raises(InvalidSchedule) as info:
        parse_schedule(exact.replace("0 ", "0  ", 1), "UTC")
    assert info.value.field == "cron"


# --- CHK-M9-073: time zones -------------------------------------------------

BAD_ZONES = [
    "Mars/Base",
    "localtime",
    "../etc/passwd",
    "/etc/UTC",
    "/usr/share/zoneinfo/UTC",
    "Europe\\London",
    "",
    "Europe/" + "x" * 58,  # 65 characters
    "America",
    "utc ",
    "utc",  # not the IANA spelling (Windows' file system would resolve it)
    "UTC ",
    "europe/london",
    "Europe/London\x00",
]


@pytest.mark.parametrize("tz", BAD_ZONES, ids=lambda z: repr(z)[:30])
def test_refused_zones(tz: str) -> None:
    with pytest.raises(InvalidSchedule) as info:
        parse_schedule("0 3 * * *", tz)
    assert info.value.field == "timezone"


@pytest.mark.parametrize(
    "tz", ["UTC", "Etc/UTC", "Europe/London", "Asia/Kolkata", "America/New_York"]
)
def test_accepted_zones(tz: str) -> None:
    assert parse_schedule("0 3 * * *", tz).timezone == tz


def test_zone_length_bound() -> None:
    assert len(BAD_ZONES[7]) == 65


def test_messages_are_fixed() -> None:
    for cron, tz in (
        (CANARY + " * * * *", "UTC"),
        ("0 3 * * *", "Mars/" + CANARY),
        ("0 0 1 * 1", "UTC"),
    ):
        with pytest.raises(InvalidSchedule) as info:
            parse_schedule(cron, tz)
        assert CANARY not in str(info.value) and CANARY not in repr(info.value)
        assert str(info.value) in {"Invalid request: cron", "Invalid request: timezone"}


def test_schedule_keeps_what_was_given() -> None:
    s = parse_schedule("0 3 * * 0", "Europe/London")
    assert (s.cron, s.timezone) == ("0 3 * * 0", "Europe/London")


# --- CHK-M9-074: strictly after ---------------------------------------------


def test_next_fire_is_strictly_after() -> None:
    s = parse_schedule("0 3 * * *", "UTC")
    fire = u(2026, 10, 29, 3)
    assert next_fire(s, fire) == u(2026, 10, 30, 3)
    assert next_fire(s, fire - timedelta(microseconds=1)) == fire
    assert next_fire(s, fire + timedelta(microseconds=1)) == u(2026, 10, 30, 3)
    assert next_fire(s, fire - timedelta(seconds=1)) == fire


def test_next_fire_is_utc_aware_and_zone_independent() -> None:
    s = parse_schedule("0 9 * * *", "Asia/Kolkata")
    a = next_fire(s, REF)
    b = next_fire(s, REF.astimezone(timezone(timedelta(hours=-7))))
    assert a == b
    assert a.tzinfo is not None and a.utcoffset() == timedelta(0)


def test_every_minute_moves_forward() -> None:
    s = parse_schedule("* * * * *", "UTC")
    t = REF
    for _ in range(5):
        n = next_fire(s, t)
        assert n == t + timedelta(minutes=1)
        t = n


def test_naive_after_is_refused() -> None:
    with pytest.raises(ValueError):
        next_fire(parse_schedule("* * * * *", "UTC"), datetime(2026, 10, 28, 12))  # noqa: DTZ001
