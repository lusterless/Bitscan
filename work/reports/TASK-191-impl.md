# TASK-191 IMPL: cron and time zone (pure)

Implementer: impl-manager-m9. REQ-223. Risk high. Spec: TS §4.4 L557, §5.2 L851–L852, §2.1 L103. Answers applied: #128 (a)–(c); decisions 2026-10-30 "M9 early rulings" (2) for the DST rows.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/scheduler/cron.py` (new, 173 lines) | `InvalidSchedule`, `Schedule`, `parse_schedule()`, `next_fire()` |

No file outside the task's list was changed. APScheduler 3.11.3 (locked) `CronTrigger`; `zoneinfo` (Windows through the locked `tzdata`).

## Interface (as plan TASK-203 §2)

```python
CRON_MAX: Final = 64; TIMEZONE_MAX: Final = 64
class InvalidSchedule(ValueError):        # message "Invalid request: cron|timezone"
    field: Literal["cron", "timezone"]
@dataclass(frozen=True)
class Schedule: cron: str; timezone: str; trigger: CronTrigger
def parse_schedule(cron: str, timezone: str) -> Schedule
def next_fire(schedule: Schedule, after: datetime) -> datetime   # strictly after, UTC
```

## Behaviour

- **Time zone, checked first:** refused when it is empty, over 64 characters, not printable ASCII, `localtime`, starts with `/`, contains `..` or a backslash, or `ZoneInfo()` raises `ZoneInfoNotFoundError`, `ValueError` or `OSError` (for example a directory name like `America`).
- **Cron:**
  - At most 64 ASCII characters, exactly 5 whitespace-separated fields.
  - Each field is a comma list of items. An item is `*`, `n` or `n-m`, with an optional `/step` (step ≥ 1) **only after `*` or a range**.
  - Values are decimal numbers within the field's bounds: minute 0–59, hour 0–23, day 1–31, month 1–12, weekday 0–7. Month names `jan`–`dec` and weekday names `sun`–`sat` are accepted, case-insensitive. A range needs first ≤ last.
  - Everything else is refused: `@…`, `?`, `L`, `W`, `#`, `last`, `1st mon`, seconds and a sixth field.
- **Both day fields restricted** (day of month and day of week both other than exactly `*`) → `InvalidSchedule("cron")` (#128 (a)).
- **Weekdays (departure from the plan's wording):** the plan renames each number token (`0→sun … 7→sun`). That is wrong for steps and for ranges from 0:
  - crontab(5) `*/2` means Sun, Tue, Thu, Sat. Given to APScheduler as-is it means Mon, Wed, Fri, Sun.
  - `0-3` would become `sun-wed`, which APScheduler refuses because its Sunday is 6.
  - So the field is expanded to the set of days crontab(5) means (`*` spans 0–7, 7 counts as Sunday, the same as Vixie cron) and passed as a comma list of names in Monday-first order. `5-7` gives `fri,sat,sun`. A field that is exactly `*` is passed as `*`.
- **Never fires:** the trigger must fire within 5 × 366 days of the fixed instant 2000-01-01T00:00Z (#128 (c)). `0 0 30 2 *` takes about 0.3 s for APScheduler to give up on, which is acceptable on create and update.
- **APScheduler parse errors:** any `ValueError` from it becomes `InvalidSchedule("cron")`.
- **`next_fire(after)`:** `get_next_fire_time(None, after + 1 µs)`, converted to UTC and confirmed `> after`. APScheduler rounds a partial second up, so a fire time given as `after` returns the next fire. A naive `after` raises `ValueError`.

## DST: APScheduler 3.11.3's answer differs from #128 (b)'s recommended reading (for `main` and the user)

Observed in a scratch run with `30 1 * * *` in `Europe/London` (ruling (2) rows):
- **Spring gap, 2026-03-29:** 01:30 local does not exist. APScheduler fires at **01:30 UTC (02:30 BST)** that day. It shifts forward rather than skipping. #128 (b) recommends "skipped".
- **Autumn repeat, 2026-10-25:** 01:30 local happens twice. APScheduler fires **twice**, at 00:30 UTC (01:30 BST) and at 01:30 UTC (01:30 GMT). #128 (b) recommends "fires once".

I did not work around either, because the plan says DST is "whatever APScheduler 3.11 does, pinned by TP-M9-07; if it differs … the lead asks". `next_fire` stays strictly increasing in both cases. A fix, if the user wants one, belongs in `next_fire()`.

## For the tester

REQ-223 (1)–(4) rows all behaved as stated in my scratch run, including `Asia/Kolkata` `0 9 * * *` → 03:30 UTC, and every listed refusal (six fields, `@daily`, `0 0 1 * 1`, 65 characters, `0 0 30 2 *`, `61 * * * *`; `Mars/Base`, `localtime`, `../etc/passwd`, 65 characters). Extra refusals worth pinning: `5/10 * * * *` (a step on a single value), `0 0 L * *`, `0 0 ? * *`.

## Plants

- CHK-M9-368: pass the weekday field unchanged.
- CHK-M9-369: remove the both-day-fields check.
- CHK-M9-370: `timezone=UTC` in the `CronTrigger` call.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass. The `apscheduler` import carries `# type: ignore[import-untyped]`, as `runner.py` does.

## Revision 1 (2026-10-30): DST per the user's ruling

Ruling (decisions 2026-10-30, "DST behaviour for scheduled scans"; main's message): **shift the gap, run the repeat once.**

- **Spring gap:** unchanged. A local time the gap skips keeps APScheduler 3.11's shifted run. For `30 1 * * *` in Europe/London that is 2026-03-29 01:30 UTC.
- **Fall-back repeat:** `next_fire()` now drops the second occurrence of a repeated local wall time and returns the next fire after it, so only the first occurrence runs. A fire is "repeated" when its local time has `fold == 1` and the `fold == 0` reading has a different UTC offset. The fold is computed by converting through UTC, not taken from APScheduler's datetime. The loop repeats the skip for every fire inside the repeated hour; for example, `*/30 * * * *` skips 01:00 and 01:30 GMT.
- Scratch-run results:
  - `30 1 * * *` Europe/London from 2026-10-24 12:00Z gives 2026-10-25 00:30Z, then 2026-10-26 01:30Z (01:30 GMT on the 25th is gone).
  - `*/30 * * * *` from 2026-10-24 23:50Z gives 00:00, 00:30, 02:00, 02:30, … UTC.
  - A UTC schedule is unchanged.
  - `next_fire` stays strictly increasing.
- `cron.py`: the docstring was updated, `_repeated()` was added (helper), and `next_fire()` loops; about 20 lines changed. The interface is unchanged.
- **For the tester:** the autumn row now expects one fire on 2026-10-25 (00:30Z), and the next fire after it is 2026-10-26 01:30Z. Also pin a sub-hourly cron across the repeated hour.
- Gates: ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.

## Revision 2 (2026-10-30): exact time-zone names

TEST r1 found one failure, on local Windows only: `test_refused_zones['utc ']`. On Windows, `ZoneInfo('utc ')`, `ZoneInfo('utc')` and `ZoneInfo('UTC ')` all load, because the tzdata resource lookup goes through a case-insensitive file system that also ignores trailing spaces. Linux refuses all three.

Fix: `_zone()` now also requires `name in _known_zones()`. That is `frozenset(zoneinfo.available_timezones())`, read once (`functools.cache`), and the match is exact and case-sensitive. It holds 598 names on this box; `UTC`, `Asia/Kolkata` and `Europe/London` are in it.

Scratch check:
- accepted: `UTC`, `Asia/Kolkata`, `Europe/London`;
- refused with field `timezone`: `utc `, `utc`, `UTC `, `europe/london`, `Mars/Base`, `localtime`.

The interface is unchanged. Gates: ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
