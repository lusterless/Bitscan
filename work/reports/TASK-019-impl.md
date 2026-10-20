# TASK-019 IMPL report: `bitscan-manager db maintain`

REQ: REQ-028. Spec: TS §5.3 L1047 (keep three future months, drop whole partitions past retention, as `bitscan_migrate` with `SET ROLE bitscan_owner`), TS §8.7 L1437–L1480 (maintain unit: only `BITSCAN_MIGRATE_DSN_FILE`). Decisions: #43 (UTC months, `scan_result_YYYY_MM`, found by bounds), #44 (drop when the upper bound is ≥ 400 days before now; refuse over default-partition rows; the alert is not here). It also folds in the TASK-013 `_scrub` nit (decisions 2026-10-20). Plan: `work/plans/TASK-019.md`.

## Files (3)

- `manager/bitscan_manager/db/maintain.py` (new, 186 lines with docstrings). The interface is the plan's: `MonthRange`, `MaintainPlan`, `plan_partitions(now, existing)` (pure), `run_maintain(dsn, now=None)`. It also has `MaintainError`, plus the pure helpers `month_range(lower)` and `parse_bound(name, bound)`.
- `manager/bitscan_manager/cli/__init__.py`:
  - adds `db maintain`, and both `db` commands share the configuration step (`_db`);
  - the help epilog lists both commands;
  - `SecretStr` is a type-only import, so the CLI still imports nothing heavy at start-up.
- `manager/bitscan_manager/db/__init__.py` (the TASK-013 nit):
  - `_scrub(message, dsn)` becomes `dsn_secrets(dsn)` plus `scrub(message, secrets)`;
  - `run_migrations` computes `secrets` once, **before** the `try`;
  - `dsn_secrets` never raises: an unparsable DSN returns `None`, and `scrub` then replaces the whole message with `the DSN is not a valid PostgreSQL DSN`. psycopg's parse error quotes a fragment of the DSN, so replacing the full DSN string would not be enough.

Size: about 186 + 65 changed lines, over the plan's estimate of 160. Splitting would separate the CLI wiring from the function it calls. Lead: tell me if you want that.

## Behaviour

1. **Configuration:** `load_db_config(os.environ)`, the TASK-012 db profile with the same TLS rule. Exit 2 with `db maintain: <variable> …` on a configuration error.
2. **Connection:** a psycopg connection (no SQLAlchemy). `SET ROLE bitscan_owner`, then `current_user` must be `bitscan_owner` (otherwise `MaintainError`). Then `SET TIME ZONE 'UTC'` and `SET DateStyle = 'ISO, YMD'`, and a commit, so the session settings survive the transaction.
3. **One transaction** (`conn.transaction()`):
   - Read the partitions of `public.scan_result` **by bounds**: `pg_inherits` × `pg_class`, `pg_get_expr(relpartbound, oid)`.
   - `parse_bound` skips `DEFAULT`. It parses `FOR VALUES FROM ('…') TO ('…')` with string methods and `datetime.fromisoformat` (stdlib `re` is banned). It requires time-zone-aware values and exactly one UTC calendar month. Anything else (MINVALUE, a two-month range, a non-UTC-aligned month) is refused: `partition '<name>' is not one UTC calendar month; nothing was changed`, exit 1.
   - `plan_partitions(now, existing)`:
     - creates each month of the window (the UTC month of `now` plus the next three) whose start no existing range has, filling gaps inside the window;
     - drops each existing range with `upper <= now - 400 days`, never the default partition, and never a range that is not past retention, so moving the clock back drops nothing.
   - **Refusal over default rows (#44):** for each month to create, a parameterised `SELECT EXISTS (SELECT 1 FROM scan_result_default WHERE job_created_at >= %s AND job_created_at < %s)`. On the first hit, the transaction is rolled back and the run exits 1 with `scan_result_default holds rows in the range of the partition to create for YYYY-MM; nothing was changed`. No row data is read or printed. A `CheckViolation` (23514) from PostgreSQL is caught too, as a backstop, with the same message minus the month.
   - DDL comes only from `psycopg.sql`: `SQL("CREATE TABLE {} PARTITION OF scan_result FOR VALUES FROM ({}) TO ({})").format(Identifier(name), Literal(lower), Literal(upper))` and `SQL("DROP TABLE {}").format(Identifier(name))`. There is no GRANT: new partitions get their ACL from the m0005 default privileges. No DELETE, and no other table is touched.
4. **Clock:** `run_maintain(dsn, now=...)` is the injection point for tests; the CLI passes nothing and so uses `datetime.now(UTC)`.
5. **Output and exit codes:**
   - 0: one `created <name>` / `dropped <name>` line per action, or `nothing to do`;
   - 1: any database failure or refusal (`db maintain: <message>`, scrubbed, no exception chain);
   - 2: configuration error.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check` / `ruff format --check` / `mypy --strict` on `manager/bitscan_manager` (16 files) | pass |
| Tester's `tests/test_db_maintain.py` (unit part) | 12 passed, 7 skipped (pg) |
| `parse_bound` | `+00` month accepted; `DEFAULT` → None; `+05:30`-aligned month, two-month range, `MINVALUE` and a naive timestamp refused |
| `plan_partitions(2026-10-20Z, [])` | `scan_result_2026_10` … `scan_result_2027_01` |
| `dsn_secrets` on two unparsable DSNs (bad IPv6 URI, unterminated quote) | `None`; scrubbed message `the DSN is not a valid PostgreSQL DSN` |
| `run_maintain` with an unparsable DSN / an unreachable host, both with a canary | `MaintainError` with no canary and no `__cause__`/`__context__` |
| `pytest tests/test_cli.py tests/test_db_migrate.py tests/test_db_maintain.py` | 69 passed, 13 skipped, **1 failed: `test_cli.py::test_refused_commands_touch_no_env_socket_or_db[db maintain]`** (stale by design, see below) |
| Real PostgreSQL (clock +2 months, second run no-op, default ACL and 42501 probes, 400-day drop, default-row refusal, CLI canary) | **NOT RUN by me** (WSL root runs are blocked for me); your pg cases in `test_db_maintain.py` cover them |

## Revision 1 (clock guard, amendment to #44; naive clock; run lock)

Files: `db/maintain.py` (+45 lines, 231 now) and `cli/__init__.py` (+3).

- **(a) Clock guard:** checked only when the plan has drops, inside the same transaction, after `SET ROLE` and before any DROP. All drops are refused when either:
  - no existing non-default partition contains `now` (`lower <= now < upper`, from the catalog read before this run's creates);
  - `SELECT EXISTS (SELECT 1 FROM scan_result WHERE job_created_at > %s)` is true. This equals `max(job_created_at) > now`, but partition pruning limits it to current and future partitions, so it never scans 400 days of results.

  When refused:
  - the missing window is **still created**, and the transaction commits;
  - `MaintainPlan.drops_refused` carries the message: `drops refused: <reason with the clock time as YYYY-MM-DDTHH:MM:SSZ>; N partition(s) past retention were kept, check the system clock`;
  - the CLI prints the `created …` lines, then that message on stderr, and **exits 1**;
  - no row data is read or printed.

  `MaintainPlan` gains `drops_refused: str | None = None`, so the two-field form still works. The 400-day rule is otherwise unchanged.
- **(b)** `plan_partitions` and `run_maintain` raise `ValueError("now must be a timezone-aware datetime")` for a naive `now`. In `run_maintain` this is raised before the `try`, so it is a plain `ValueError`, not a `MaintainError`.
- **(c) Run lock:** the transaction starts with `SELECT pg_advisory_xact_lock(hashtext('db_maintain'))`, a key distinct from `audit_log` and `catalog`. The connection is forced to READ COMMITTED. A second, overlapping run **waits**, then reads the catalog the first run committed, and so finds nothing left to do: exit 0, no duplicate CREATE. The lock is released at commit or rollback.
- Checks (Windows):
  - ruff, format and mypy (20 files) pass;
  - the tester's `test_db_maintain.py` + `test_cli.py` give 54 passed, 7 pg skipped;
  - a naive `now` is refused on both entry points;
  - with a stubbed `run_maintain`, a `drops_refused` plan gives exit 1, `created …` on stdout and the message on stderr, while a normal drop gives exit 0.
  - Real PostgreSQL: NOT RUN by me.
- For the tester (pg):
  - a clock +2 years: creates 4, drops 0, exit 1, the message names the clock;
  - a row with `job_created_at` after `now`: drops refused, exit 1;
  - two concurrent runs: one waits on `pg_locks` (advisory, `hashtext('db_maintain')`), both exit 0, and no partition is created twice;
  - a normal past-retention drop still works (exit 0).

## Revision 2: guard (c), the partition gap check (second amendment to #44, user-approved)

Closes the gap the tester and reviewer found (CHK-M1-186). With the clock 24 months fast, run 1 refused the drops but created the skewed window. On run 2, guard (a) passed on that new partition and guard (b) passed, so every in-retention partition was dropped.

- **File:** `manager/bitscan_manager/db/maintain.py` only (README updated in the same revision).
- **New pure function `missing_months(existing) -> list[str]`:** the UTC months (`YYYY-MM`) with no non-default partition between the oldest and the newest existing lower bound. An empty list means no partitions or contiguous ones.
- **`_clock_doubt` guard order:** (a) no partition contains `now`; then **(c)** `missing_months(existing)` is not empty; then (b) a row is later than `now`.
  - `existing` is the catalog read under the run lock, after `SET ROLE`, **before** this run's creates, in the same transaction. Guard (c) is checked only when the plan has drops, like (a) and (b).
- **On refusal:** the window is still created, the transaction commits, `drops=()` and the CLI exits 1. The message reads `drops refused: scan_result partitions are not contiguous at the clock time <YYYY-MM-DDTHH:MM:SSZ>, missing <YYYY-MM, …>; remove stray partitions; N partition(s) past retention were kept, check the system clock`. At most 12 months are listed, then `and K more`, so a stray partition dated far away cannot produce a huge message. No row data is read.
- **Side effect (accepted, fails safe):** if `db maintain` does not run for about 3 months or more, a gap appears, and drops stay refused until an operator checks and fills or removes partitions.
- **Remaining risk (accepted, decisions.md as corrected):** a forward skew of less than the window plus one month passes all three guards. A skewed window that starts in the month right after the real window is contiguous with it, so after one refused run, data can be dropped up to about 5 months early. Only a data-based check or the TS §8.4 clock-skew alert (M2) can detect this. The README states no bound.
- **Checks (Windows):**
  - ruff, format and mypy --strict (21 files) pass;
  - `missing_months`: `[]` for none, for one, and for the 4-month window; window plus months -13 and -12 gives the 11 months in between;
  - full Windows `pytest --cov=bitscan_manager/services --cov-fail-under=85`: 364 passed, 159 skipped, coverage 100 %.
  - Real PostgreSQL: NOT RUN by me.
- **For the tester (pg):**
  - Repro: clock +24 months; run 1 refuses with guard (a) and creates the window; run 2 is now refused by guard (c), naming the missing months; nothing dropped; exit 1 both times.
  - **Existing tests that now hit guard (c):** `test_drops_only_partitions_past_400_days_and_keeps_rows_elsewhere` and `test_clock_inside_the_window_keeps_the_400_day_behaviour` create partitions about 13 months back next to the migration window (current month + 3), with a gap of about 11 months between them. Drops are now refused there. To keep testing the 400-day rule, fill the months between the old partitions and the window.
  - `missing_months` is pure: unit-testable with `month_range`.

## For the tester

- **Stale M0 case:** `test_cli.py::test_refused_commands_touch_no_env_socket_or_db[db maintain]` expects `db maintain` to read no environment. It now reads `BITSCAN_MIGRATE_DSN_FILE`, the same narrowing as `db migrate` in TASK-013. With the variable unset it still exits 2, imports no database module and opens no socket.
- `tests/test_db_maintain.py` currently has ruff E501 and format findings, and one mypy error at line 152 (`run` imported with a different signature). These are in your file.
- The refusal message names `scan_result_default` and the month `YYYY-MM`.
- `parse_bound` is pure: a hand-made partition can be unit-tested without PostgreSQL.
