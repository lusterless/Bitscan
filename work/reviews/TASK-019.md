# TASK-019 REVIEW: `bitscan-manager db maintain` (monthly partition maintenance)

Reviewer: reviewer. Date: 2026-10-20. REQ-028. Spec: TS §5.3 L1047 (three future months; drop whole partitions past retention; as `bitscan_migrate` with `SET ROLE bitscan_owner`), TS §8.7 L1437-1480 (maintain unit, `BITSCAN_MIGRATE_DSN_FILE` only); `.claude/rules/manager/database.md` "Partitions and retention"; decisions #43 (UTC months, `scan_result_YYYY_MM`, found by bounds) and #44 (drop when the upper bound is at least 400 days before now; refuse over default rows). Files: `manager/bitscan_manager/db/maintain.py` (186 lines), `cli/__init__.py`, `db/__init__.py` (the TASK-013 `_scrub` nit). Inputs: `work/plans/TASK-019.md`, `work/reports/TASK-019-impl.md`, `work/reports/TASK-019-test.md` (PASS; WSL, `CI=true`, 430 passed; 6 of 7 mutations red, 1 equivalent), `tests/m1/report.md` CHK-M1-170 to -179, -055-r2.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268). The open question in finding 1 is for the owner and does not block M1.

## What was checked

- **Destructive path (`maintain.py:56-64`, `67-103`, `158-159`):**
  - **What can be dropped.** Only partitions of `public.scan_result`, read from `pg_inherits`/`pg_class` by bound (`pg_get_expr(relpartbound)`) under `TimeZone = 'UTC'` and `DateStyle = 'ISO, YMD'`.
    - `DEFAULT` is never in the plan;
    - any bound that is not exactly one UTC calendar month aborts the whole run before anything changes. I checked MINVALUE, a two-month range, a `+02`-aligned month, a naive timestamp, garbage, and a quote-injection-shaped bound: all give `MaintainError`.
  - **Drop rule.** `upper <= now - 400 days`, so a current or future partition (upper bound after `now`) can never be dropped. A hand-made partition is dropped only if it is exactly one UTC month and past retention, which is the #43 "by bounds" rule.
  - **Check at 2026-10-20 (cutoff 2025-09-15):** it drops exactly 2025-01 to 2025-08, keeps 2025-09 onward, and creates only the missing 2027-01.
  - **Clock:**
    - the CLI passes no `now`, so `datetime.now(UTC)`;
    - a non-UTC `now` is normalised (UTC+14 on 1 November local gives October);
    - moving the clock backward drops nothing;
    - the window is always 4 months and is never empty, and with no existing partitions it creates exactly 4.
  - **Names.** Created names are `strftime("scan_result_%Y_%m")` of a computed month. Dropped names come from the catalog. Both are quoted with `sql.Identifier`.
- **Refusal over default-partition rows (#44):**
  - a parameterised `SELECT EXISTS (… WHERE job_created_at >= %s AND job_created_at < %s)` per month to create;
  - only a boolean is read, and the message names `scan_result_default` and the month, with no row data;
  - PostgreSQL's own `CheckViolation` is caught as a backstop (the tester's one equivalent mutant).
- **Atomic:**
  - planning, the refusal check, every `CREATE` and every `DROP` run inside one `conn.transaction()`;
  - `_Refused`, or any other exception, rolls the whole thing back;
  - the session settings and `SET ROLE` are committed before the transaction, and `SET ROLE` is checked with `current_user = 'bitscan_owner'`.
- **No GRANT, no DELETE:** new partitions get their ACL from m0005's default privileges. The tester shows owner `bitscan_owner`, and app 42501 for UPDATE, DELETE and TRUNCATE on a maintained partition (CHK-M1-172, -177). Only partition DDL runs (CHK-M1-174).
- **SQL composition:** `sql.SQL(...).format(sql.Identifier, sql.Literal)` only. There are no f-strings in SQL; the f-strings in the file are messages only. ruff S608 is not suppressed. No stdlib `re`: parsing uses string methods and `datetime.fromisoformat`.
- **Configuration, scrubbing, exit codes:**
  - `load_db_config` applies the TLS DSN rule (#45);
  - `dsn_secrets` is computed before the `try` and never raises;
  - an unparsable DSN replaces the whole message, which fixes the TASK-013 nit;
  - `MaintainError` is raised outside the `except` blocks, so nothing is chained;
  - exit 0 prints `created …`, `dropped …` or `nothing to do`; exit 1 is a database failure or refusal; exit 2 is a configuration error;
  - the CLI's lazy-import rule holds (`SecretStr` is type-only).
- **Gates:** ruff and format are clean, and `mypy --strict` reports no issues in 42 files.
- **Size:** 186 + about 65 changed lines, across 3 files, over the 160-line estimate. Accepted: the CLI wiring belongs with the function it calls, and the `db/__init__.py` part is the earlier review nit. Splitting would not make either easier to review.

## Findings

1. **question for `main` and the owner (not blocking). A clock that jumps forward drops retained data.**
   - The #44 rule trusts the clock completely. In my check, with `now` two years ahead of the real date, `plan_partitions` drops all 24 existing partitions, including those well inside 400 days of the real date.
   - TS §3.3 asks for NTP-synced hosts, but a bad clock on the manager host would make the daily timer delete scan results irreversibly.
   - Suggested guard, which needs the owner's decision because it changes #44:
     - refuse any drop when no existing partition contains `now` (that is, when the run would also have to create the current month), or when `max(job_created_at)` in `scan_result` is later than `now`;
     - in that case, create the window and report "clock check failed, nothing dropped".
2. **nit. A naive `now` is not rejected.** `plan_partitions` with no existing partitions treats it as local time, through `astimezone`. With existing partitions it raises `TypeError`, which rolls back cleanly. Only test injection can pass one, because the CLI always passes an aware UTC time. Fix: raise `ValueError` in `run_maintain` and `plan_partitions` when `now.tzinfo is None`.
3. **nit. Two concurrent runs are not serialised.** The second run fails with a duplicate-table error and rolls back (exit 1), so nothing breaks. The systemd timer gives a single run anyway. A `pg_advisory_xact_lock(hashtext('db_maintain'))` would make that explicit.

## Revision 1 and 2 (2026-10-20)

Reviewer: reviewer (new instance). Scope:
- revision 1: the clock guard (a)/(b), the naive-clock refusal and the run lock, from the first amendment to #44 and findings 1 to 3 above;
- revision 2: guard (c), the partition gap check, from the second amendment to #44, user-approved after CHK-M1-186.

Files: `manager/bitscan_manager/db/maintain.py` (256 lines now), `cli/__init__.py`, and the README `db maintain` bullets (checked by message only). Inputs: `work/reports/TASK-019-impl.md` "Revision 1" and "Revision 2", and `work/reports/TASK-019-test.md` "Revision 1 and Revision 2" (PASS). Each mutation was red: guard (a) 1, guard (b) 2, run lock 2, CLI exit 2, guard (c) 5. Rows: `tests/m1/report.md` CHK-M1-180 to -191, and CHK-M1-240-r2 (clean WSL run, 547 passed, 0 skipped, 100 %).

Revision verdict: **APPROVED** (revisions 1 and 2 together).

### What was checked

- **Naive clock (finding 2, closed).** `_require_aware` (`maintain.py:43-45`) is called from `plan_partitions` (`:66`) and from `run_maintain` (`:245`). In `run_maintain` it runs before the `try`, so a naive `now` is a plain `ValueError` and never reaches the database (CHK-M1-184).
- **Run lock (finding 3, closed).**
  - `pg_advisory_xact_lock(hashtext('db_maintain'))` (`:197`) is the first statement of the transaction;
  - the key is distinct from `audit_log` and `catalog`;
  - the connection is forced to READ COMMITTED (`:183`), so a run that waited reads the catalog the first run committed and plans afresh;
  - the wait is decided in #46. The test sees it deterministically in `pg_locks` (CHK-M1-185), and removing the lock turns 2 tests red.
- **Clock guard (finding 1, closed by both amendments), `_clock_doubt` (`:151-178`):**
  - it is checked only when the plan has drops (`:200`), inside the locked transaction, on `existing`;
  - `existing` is read at `:198`, before this run's creates (main's check);
  - order: (a) no non-default partition contains `now`; then (c) `missing_months(existing)` (`:138-148`) is not empty; then (b) `EXISTS (… job_created_at > %s)`, which is bound and pruned to the current and future months;
  - on refusal: `drop = ()`, the creates still commit, `drops_refused` carries the reason, the clock as `YYYY-MM-DDTHH:MM:SSZ` and the count kept, and the CLI prints the `created` lines on stdout and the reason on stderr, then exits 1 (`cli/__init__.py:44-46`).
- **Gap report (main's check).**
  - it is by month only: `YYYY-MM` strings computed from catalog bounds, at most 12, then `and K more` (`:164-170`);
  - no row data is read;
  - guard (c) refuses before guard (b) issues any query (CHK-M1-191 uses a stub connection that fails on any query).
- **CHK-M1-186 closed.** The second-run scenario (clock +24 months, two runs a day apart) now refuses on run 2 and names the first missing month (CHK-M1-187). The contiguous control still drops exactly the past-retention months (CHK-M1-188). Hand-made 1- and 2-month holes refuse, name each month, and still create the window (CHK-M1-189). The CLI exits 1 on a gap (CHK-M1-190).
- **Invariants unchanged from the first review:** psycopg.sql-only DDL; no GRANT and no DELETE; `SET ROLE bitscan_owner` checked; the DSN is scrubbed; no f-string SQL; S608 not suppressed.
- **Gates (re-run by me, Windows):** ruff and format clean, `mypy --strict` clean on 46 files; 366 passed, 164 pg skipped.
- **README** (`README.md` "`bitscan-manager db maintain`"): the guard list, the window still created, exit 1, the gap side effect and the waiting lock all match the code (reported to impl-manager by message).
- **Size:** about +70 lines over the approved version, in 2 files, each revision within the amendment's scope.

### Findings

1. **note, accepted (decisions.md, second amendment to #44, corrected wording).** A forward skew smaller than the window plus one month leaves a contiguous skewed window. For example, real partitions run to M+3 and run 1 at month M+4 creates M+4 to M+7. That passes all three guards on the next run, so data can be dropped up to about 5 months early. I simulated it: with the real date 2026-10-01 and the clock at 2027-02-28, 5 partitions inside retention are dropped. No guard based only on partitions can tell this from normal operation. The TS §8.4 clock-skew alert (> 5 min, M2) is the detection. No change in M1.
2. **note, accepted (fails safe).** When `db maintain` has not run for about 3 months, a gap appears and drops stay refused until an operator fills or removes partitions. This is documented in the README.
