# TASK-191 REVIEW: cron and time zone (pure)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-223. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-191-impl.md` (revisions 1 and 2): one new file, `manager/bitscan_manager/services/scheduler/cron.py` (202 lines).

TEST: PASS on r2 (`work/reports/TASK-191-test.md`). 110/110 on Windows (L) and Linux (W). All plants are red: CHK-M9-368, -369, -370, -386 (the plan's per-number rename), -386a (repeat dedupe dropped), -387 and -073a (known-zones check dropped).

Spec read: TS §4.4 L557, §5.2 L851–L852, §2.1 L103; #128 (a)–(c); decisions 2026-10-30 "DST behaviour for scheduled scans" (user), "M9 early rulings" (2).

My re-run (Windows): `test_cron.py`, `test_idempotency.py` and the `next_fire` property give 144/144. ruff and `mypy --strict` are clean on the file.

## Checks
1. **crontab(5) syntax (#128 (a)).**
   - Five fields, ASCII only (so Unicode digits that `isdigit()` would take are refused first), at most 64 characters.
   - `*`, lists, ranges, steps only on `*` or a range, and month and weekday names.
   - `@` macros, `?`, `L`, `W`, `#` and seconds are refused.
2. **Weekday translation.** The field is expanded to the set of days crontab(5) means, then handed to APScheduler as names. That is correct, and the departure from the plan's per-number rename is justified: CHK-M9-386 shows the rename gets `*/2` and `0-3` wrong. 0 and 7 both mean Sunday.
3. **Both day fields restricted are refused** (#128 (a)). The test is `!= "*"`, so `*/2` in day of month also counts as restricted. That is stricter than Vixie's `DOM_STAR` rule, and safe: APScheduler's AND semantics are never silently applied where crontab(5) would OR.
4. **Never fires (#128 (c)).** The cron must fire within 5 × 366 days of a fixed reference, which covers the 29 February case (CHK-M9-069).
5. **Time zone (#128 (b)).**
   - The name must be in the exact, case-sensitive `available_timezones()` set (r2). This closes the Windows case-insensitive lookup (`utc `).
   - The shape checks refuse `localtime`, a leading `/`, `..`, a backslash and anything over 64 characters.
   - Errors name the field only.
6. **DST per the user ruling.**
   - Spring gap: APScheduler's shifted run is kept.
   - Autumn repeat: `_repeated()` drops a fire whose local time has `fold == 1` with a different offset, so only the first occurrence runs.
   - The loop is bounded (one step per fire inside the repeated hour) and `next_fire` stays strictly after `after` (CHK-M9-074, -085).

## Findings
None blocking or should-fix.

1. nit, `cron.py:18-19`: "Pure … no I/O" isn't quite true. `available_timezones()` and `ZoneInfo()` read tzdata files (once, cached). This is unavoidable and harmless, but the docstring could say "no I/O apart from reading tzdata". No change required.
2. Note for TASK-208 (README): with "repeat once", a sub-hourly schedule has no run during the repeated hour (tester's recorded row). The README should say so.
