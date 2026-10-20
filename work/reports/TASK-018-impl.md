# TASK-018 IMPL report: migration m0005 (privileges, view, seeds, partitions)

REQs: REQ-025, REQ-026, REQ-027 (part). Spec: TS §5.2 L994–L1013 (default privileges and grants), L1038–L1041 (`v_plugin` and its grant), L832–L833 (`system_schedule` seed), TS §8.6 L1321–L1336 (settings and the five redaction patterns), TS §5.3 L1046 (initial partitions). Decisions: #42 (setting value shape), #43 (UTC partitions, `scan_result_YYYY_MM`). Plan: `work/plans/TASK-014.md` "m0005 statement order".

## File (1)

- `manager/bitscan_manager/db/migrations/versions/m0005_privileges_seeds.py` (about 145 lines): `revision = "m0005"`, `down_revision = "m0004"`. `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

## `upgrade()` order

1. `STATEMENTS`, run in order with `op.execute`, 16 static literals:
   - the 3 `ALTER DEFAULT PRIVILEGES` (L994–L996);
   - the `ON ALL TABLES` / `ON ALL SEQUENCES` grants (L997–L999);
   - the retention grants (L1001–L1004);
   - the app UPDATE, column-UPDATE and DELETE grants (L1007–L1013);
   - `CREATE VIEW v_plugin` and `GRANT SELECT ON v_plugin TO bitscan_app` (L1038–L1041);
   - the `system_schedule` INSERT (L832–L833).

   Only comments are removed, including the L1003 end-of-line comment. `GRANT USAGE ON SCHEMA public` is a Bootstrap statement and is not here.
2. **Settings, bound parameters only.** `op.bulk_insert(sa.table("setting", column("key", String), column("value", JSONB)), rows)`. SQLAlchemy compiles it to `INSERT INTO setting (key, value) VALUES (%(key)s::VARCHAR, %(value)s::JSONB)`, and the values travel as parameters. No JSON and no pattern text appears in any SQL string, and no `:key`-style placeholder exists in the file.
   - Rows in TS §8.6 table order: `agent_token_ttl_days` 365, `job_pull_seconds` 300, `decommission_after_days` 7, `redaction_patterns` (JSON array of the 5 strings), `max_parallel_plugins` 2, `enrolment_alert_per_hour` 50. The numbers are bare JSON numbers (#42).
   - `inventory_interval_s` is not a setting row; it is the `system_schedule` `inventory` row.
   - `updated_by` stays NULL.
3. **Partitions last**, so the default privileges from step 1 give them their ACL.
   - `month_starts(now, 5)` takes `now.astimezone(UTC)`, truncates it to the first instant of the month, and steps whole months with `divmod`, so December rolls over to January.
   - `now` is `datetime.now(UTC)`, an aware UTC instant from the system clock. Neither the database server's `TimeZone` nor the migration host's local zone affects which month is "current" or where the bounds fall (#43).
   - Each of the 4 partitions is created on the migration's own transaction (Alembic's connection → `driver_connection`, a psycopg `Connection`) with `psycopg.sql`: `SQL("CREATE TABLE {} PARTITION OF scan_result FOR VALUES FROM ({}) TO ({})").format(Identifier(name), Literal(low), Literal(high))`. The name comes from `low.strftime("scan_result_%Y_%m")` and is quoted as an identifier. The bounds are typed literals with an explicit `+00:00`, such as `'2026-10-01 00:00:00+00:00'::timestamptz`.
   - DDL cannot take server-side parameters, so psycopg quotes on the client. There is no f-string or `%` SQL, and ruff S608 stays green.

## Checks run (Windows, offline)

| Check | Result |
| --- | --- |
| `STATEMENTS` lines == comment-stripped spec L994–L1013, L1038–L1041, L832–L833 | True (22 lines). Every `noqa: E501` literal has a spec line over 88 characters |
| `REDACTION_PATTERNS` == spec L1332–L1336, byte for byte | True |
| Bind parameters in `STATEMENTS` (`sa.text().compile`, psycopg dialect) | none |
| Settings insert | bound `%(key)s::VARCHAR, %(value)s::JSONB`; keys in spec order; patterns are the spec lines |
| `month_starts` | `2026-10-20Z` → 2026_10…2027_01, upper 2027-02-01Z. `2026-10-31 23:30 -05:00` (already November in UTC) → 2026_11…2027_02. `2026-11-01 01:00 +09:00` (still October in UTC) → 2026_10…2027_01. `2026-12-15Z` → 2026_12, 2027_01, 2027_02, 2027_03 |
| Rendered partition DDL | `CREATE TABLE "scan_result_2026_10" PARTITION OF scan_result FOR VALUES FROM ('2026-10-01 00:00:00+00:00'::timestamptz) TO ('2026-11-01 00:00:00+00:00'::timestamptz)` |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (36 files) | pass |
| **Tester's bind-trap scanner** (`test_migrations_have_no_bind_parameter_traps`) | **FAILS**: it scans every string constant and flags `REDACTION_PATTERNS` (`\b(?:AKIA…`, and `(?:password…`). These strings are data bound through `bulk_insert` and never pass through `text()`. Raised with the tester (below); I did not disguise the constants to get past the scanner |
| Real PostgreSQL (final schema diff with ACLs and default ACLs, grant probes, seed rows, 4 partitions with UTC bounds and default-privilege ACLs, trigger on a new partition) | **NOT RUN by me** (WSL root runs are blocked for me); the tester's harness covers it (TP-M1-10 to TP-M1-12) |

## For the tester

- **Scanner scope.** Please scope `test_migrations_have_no_bind_parameter_traps` to strings that reach `text()`. That means the elements of each module's `STATEMENTS` tuple and any argument of `op.execute` or `sa.text`. Constants passed as bound parameters should not be scanned. Exempting `REDACTION_PATTERNS` by name would also work, but scoping to SQL targets the actual hazard. If you prefer another fix, tell me.
- `db migrate` prints `m0005`.
- `setting.value` for `redaction_patterns` decodes (psycopg returns a Python list) to exactly TS §8.6 L1332–L1336.
- Partition names depend on the UTC month at migration time. Compute the expected names in the test with the same rule, or read them from `pg_inherits` and check the bounds with `pg_get_expr(relpartbound, oid)` in a UTC session.
- From m0005 on, `bitscan_app` has its grants, so REQ-029 runs as the app role (REQ-029 (3)).
