# TASK-191 TEST: PASS (revision 2)

**Revision 2 (2026-10-30).** `_zone()` now also requires an exact, case-sensitive match in a cached `zoneinfo.available_timezones()` set (`cron.py` sha256 `69735ddd45ff1887…`; impl report "Revision 2"). Re-runs: the failing test alone on L, `test_refused_zones['utc ']`: **1/1 passed**. Then the shared code's tests (`test_cron.py` + the `next_fire` property), with three refusal rows added (`utc`, `UTC `, `europe/london`): **L 110/110, W 110/110**, 0 failed, 0 errors, 0 skipped. Plant CHK-M9-073a (the known-zones check removed, on L): red, 3 failed (`test_refused_zones['utc ']`, `['utc']`, `['UTC ']`). r2 changes only `_zone()`, so the r1 DST and weekday plants below still stand. CHK-M9-073 is now PASS on L and W. The r1 text below is kept as the record.

---

## Record of revision 1: FAIL (1 Windows-only row; the DST rows pass)

Tester: tester-m9, 2026-10-30. Full rigor (cron and time zone, high risk). REQ-223; TS §4.4 L557, §5.2 L851–L852, §2.1 L103; #128 (a)–(c); DST per the **user decision** (decisions 2026-10-30, "DST behaviour for scheduled scans", relayed by `main`): shift the gap and run the repeat once (at the first occurrence), as standard cron does. Code under test: `bm/services/scheduler/cron.py` **revision 1** (impl-manager-m9, `work/reports/TASK-191-impl.md` "Revision 1"; sha256 `4e6eb1d67c9d4a8d…`), on APScheduler 3.11.3 (locked). Test files (new): `manager/tests/test_cron.py`, and `test_next_fire_strictly_increasing` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-067 to -074, -085. Every expected fire time was worked out by hand from crontab(5) and the IANA rules (Europe/London 2026-03-29 and 2026-10-25; America/New_York 2026-11-01).

## Failing test (expected vs actual)

| Test | Where | Expected | Actual |
| --- | --- | --- | --- |
| `tests/test_cron.py::test_refused_zones['utc ']` | **L (Windows) only**; W passes | `InvalidSchedule`, `field == "timezone"`: `utc ` is not an IANA name (#128 (b): unknown names 400) | accepted. On Windows `ZoneInfo('utc ')`, `ZoneInfo('utc')` and `ZoneInfo('UTC ')` all load, while `ZoneInfo('europe/london')` is refused (checked directly) |

**Diagnosis:** a product gap on the local platform. `_zone()` accepts any name `ZoneInfo()` can open. On Windows, the locked `tzdata` resources sit on a case-insensitive file system that ignores trailing spaces, so non-IANA spellings resolve. G66 runs "local; WSL; CI", so the row cannot be dropped. Sent to impl-manager-m9 with a suggested fix: require an exact `name in zoneinfo.available_timezones()`, or compare with `str(ZoneInfo(name))`. Waiting for r2, after which only this test is re-run on L and W.

## DST history

- **r0** (APScheduler as is) against ruling (2) "skip the gap, the repeat once": 2 rows red. Spring: fired 03-29 01:30Z (shifted). Autumn: fired twice (00:30Z and 01:30Z). Reported to `main`, and the test was not adjusted.
- **User decision**: shift the gap and run the repeat once. The two rows were changed to it, as `main` instructed (spring: once at 01:30Z = 02:30 BST; autumn: once at 00:30Z, the first occurrence).
- **r1**: `next_fire()` drops a fire whose local time is the second occurrence (fold 1 with a different offset). All DST rows pass. The plant "dedupe dropped" fires twice and goes red (CHK-M9-386a).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | `pytest tests/test_cron.py tests/test_jobs_property.py::test_next_fire_strictly_increasing`, code r0 | 100/102 passed, 2 failed (the r0 DST rows), 0 errors, 0 skipped |
| r1 (W) | same, code r1, DST rows per the user decision, plus 5 new DST rows | **107/107 passed**, 0 failed, 0 errors, 0 skipped |
| r1-L (Windows, worktree venv, `CI=true`, `-n 0`) | the 8 M9 unit and property files | 675/676 passed, **1 failed** (`test_refused_zones['utc ']`), 0 errors, 0 skipped |
| plants (W, on r1) | 7 plants in `/root/bstest-m9-mut-<id>` (removed after each) | 7/7 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

## Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-067 | CODE | W, L | r1 | PASS | `0 3 * * 0`, `7`, `sun`, `SUN` in UTC → the Sundays 2026-11-01 … 11-29 at 03:00Z. In Asia/Kolkata → Saturdays 21:30Z (Sunday 03:00 IST). `0 3 * * 1` → Mondays | 2026-10-30 |
| CHK-M9-068 | CODE | W, L | r1 | PASS | Weekday sets over 21 days for 18 fields: `1-5`/`mon-fri`; `5-7` = Fri–Sun; `0-5` = Sun–Fri; `0-3` = Sun–Wed; `0,6`, `6,7`, `sat,sun`; `*/2` = Sun, Tue, Thu, Sat; `1-5/2` = Mon, Wed, Fri; `0-6`, `0-7`, `*` = all; `7` and `0` = Sun; `3`, `6`, `2,4` | 2026-10-30 |
| CHK-M9-069 | CODE | W, L | r1 | PASS | `*/15`; `jan`/`1`/`JAN` → 2027-01-01, 2028-01-01; the 31st only in 31-day months; `0 0 29 2 *` → 2028-02-29, 2032-02-29 (accepted: fires within 5 years); `0 9-17/4`; `30 6 1,15`; New York noon 16:00Z → 17:00Z after 2026-11-01 | 2026-10-30 |
| CHK-M9-070 | CODE | W, L | r1 | PASS | `0 9 * * *` Asia/Kolkata → 03:30Z daily; UTC, Etc/UTC → 09:00Z | 2026-10-30 |
| CHK-M9-071 | CODE | W, L | r1 | PASS | Europe/London: `30 2` spring 03-29 → once at 01:30Z, autumn 10-25 → once at 02:30Z. `30 1` spring → [03-28 01:30Z, **03-29 01:30Z** (shifted), 03-30 00:30Z]. `30 1` autumn → [**10-25 00:30Z** (once), 10-26 01:30Z, 10-27 01:30Z]. Asked from 00:30Z or 00:45Z on 10-25 → 10-26 01:30Z (the GMT repeat is not a fire). `*/15 1` → 00:00, 00:15, 00:30, 00:45Z then 10-26 01:00Z. `*/30 *` from 10-24 23:50Z → 00:00, 00:30, 02:00, 02:30Z. Spring `*/30 *`: distinct, strictly increasing, includes 01:00Z (02:00 BST). A UTC schedule is unchanged on those days | 2026-10-30 |
| CHK-M9-072 | CODE | W, L | r1 | PASS | 37 refusals, all with `field == "cron"` (six/four fields, empty, `@daily`, `@reboot`, both day fields ×3, never fires ×3, out of range ×8, `?`, `L`, `#`, `W`, `5L`, `last`, `*/0`, `5/10`, `5-1`, `sat-sun`, bad names, an Arabic-Indic digit, `1,,2`, `1-`). 64 characters accepted, 65 refused | 2026-10-30 |
| CHK-M9-073 | CODE | W: PASS; **L: FAIL** | r1, r1-L | **FAIL (L)** | W: all 11 bad zones refused with `field == "timezone"`, the 5 good ones accepted, messages fixed. L: `utc ` accepted (see "Failing test") | 2026-10-30 |
| CHK-M9-074 | CODE | W, L | r1 | PASS | At a fire time exactly → the next; −1 µs and −1 s → the fire; +1 µs → the next; aware UTC; independent of the `after` zone; `* * * * *` steps by one minute; a naive `after` → `ValueError` | 2026-10-30 |
| CHK-M9-085 | CODE | W, L | r1 | PASS | 400 random crons × 6 zones (incl. Lord_Howe 30-minute DST, Kathmandu +05:45) × instants 2026–2030: 10 successive fires strictly increasing, UTC | 2026-10-30 |
| CHK-M9-368 | CODE | W | plant on r1: weekday field passed raw | PASS (red) | 20 failed: the Sunday rows (`0` → Monday, `7` refused), Kolkata Sunday, `test_monday`, 14 `test_weekday_field` rows, one refused-cron row | 2026-10-30 |
| CHK-M9-369 | CODE | W | plant on r1: both day fields accepted | PASS (red) | 4 failed: `test_refused_crons` for the three both-day-field crons, `test_messages_are_fixed` | 2026-10-30 |
| CHK-M9-370 | CODE | W | plant on r1: `CronTrigger(timezone=UTC)` | PASS (red) | 10 failed: Kolkata ×4, New York, the London `30 2` and `30 1` rows, the `*/15` repeat row | 2026-10-30 |
| CHK-M9-386 | CODE | W | plant on r1: per-number weekday rename (the plan's wording) | PASS (red) | 9 failed: `test_weekday_field` for `0-5`, `0-3`, `*/2`, `1-5/2`, `0-6`, `0-7`, and 3 refused-cron rows. This confirms the impl's set expansion is needed | 2026-10-30 |
| CHK-M9-386a | CODE | W | plant on r1: the repeat dedupe dropped (`if not _repeated(...)` → `if True`) | PASS (red) | 4 failed: `test_london_0130_autumn_repeat_fires_once`, `…_repeat_seen_from_inside_the_repeated_hour`, `…_every_15_minutes_through_the_repeat`, `…_every_30_minutes_across_the_repeated_hour` (fires twice) | 2026-10-30 |
| CHK-M9-387 | CODE | W | plant on r1: `next_fire` may return the instant itself | PASS (red) | 47 failed, including `test_next_fire_is_strictly_after`, `test_every_minute_moves_forward` and the G67 property. The fire helpers now assert progress, so the plant fails fast (the r0 attempt hung in an unbounded helper loop: a test robustness gap, fixed) | 2026-10-30 |
| CHK-M9-383 | CODE | L | plant: `import re` | PASS (red) | ruff TID251 (see the TASK-186 report) | 2026-10-30 |

## Acceptance (TASK-191 row: "REQ-223 (1)–(4) hold, the DST rows recording APScheduler 3.11's answer")

- (1) → CHK-M9-067, -068. (2) Kolkata → CHK-M9-070; DST → CHK-M9-071 (r1 meets the user decision; APScheduler's raw answer is recorded under "DST history"). (3) → CHK-M9-072 and CHK-M9-073 (**red on Windows**). (4) → CHK-M9-074, -085.

## Recorded, not asserted

- Any run of blanks separates fields (crontab(5)).
- `5/10` (a step on one value) is refused; crontab(5) defines steps only on ranges and `*`.
- With "repeat once", a sub-hourly schedule has no run during the repeated GMT hour (for `*/30`, 01:00Z and 01:30Z are skipped). This follows from the decision; the README is TASK-208's to update (DST is not described there yet).
