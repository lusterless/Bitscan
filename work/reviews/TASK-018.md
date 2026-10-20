# TASK-018 REVIEW: migration `m0005` (privileges, `v_plugin`, seeds, initial partitions)

Reviewer: reviewer. Date: 2026-10-20. REQ-025, REQ-026, REQ-027. Spec: TS §5.2 L832-833, L992-1013, L1037-1042; TS §5.3 L1046/L1049; TS §8.6 L1317-1339; `.claude/rules/testing.md` grant probes; security invariants "Authorisation" and "Data handling"; decisions PD-18, #41, #42, #43, #44 and the 2026-10-20 bind-scanner ruling. Inputs: `work/reports/TASK-018-impl.md`, `work/reports/TASK-018-test.md` (PASS; WSL, `CI=true`, 408 passed; whole-schema diff including ACLs: 0 differences), `tests/m1/report.md` CHK-M1-130 to -152, -059-r2, -050-r6, -036-r2, -033-r2.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268). It is reviewed with extra care as M1's security-critical migration.

## What was checked (my own scripts against the spec file)

1. **Privileges, exact copy of TS L992-1013.** I found the block by its heading, removed comments outside string literals, and compared line by line with the static `STATEMENTS`. The privilege, view and `INSERT` lines total 22, all identical.
   - **Defaults:** `ALTER DEFAULT PRIVILEGES FOR ROLE bitscan_owner …` gives app `SELECT, INSERT ON TABLES` and `USAGE ON SEQUENCES`, and retention `SELECT ON TABLES`.
   - **Existing tables:** `GRANT … ON ALL TABLES` and `ON ALL SEQUENCES` mirror the defaults.
   - **Retention:**
     - `DELETE` on exactly `scan, scan_job, scan_result, scan_result_reeval, inventory_snapshot, enrollment_request, user_token, audit_log, package`;
     - `INSERT ON audit_log`, and `USAGE ON SEQUENCE audit_log_audit_id_seq` (checkpoint).
   - **App:**
     - `UPDATE` on exactly the 15 tables in the spec;
     - column `UPDATE (state, dispatched_at, started_at, deadline_at, finished_at) ON scan_job` and `UPDATE (state, finished_at) ON scan`;
     - `DELETE` on exactly `policy_plugin, agent_tag, agent_package, agent_ip_seen, scan_schedule`.
   - **Not granted:**
     - no `UPDATE`, `DELETE` or `TRUNCATE` on `audit_log`, `scan_result` (any partition), `scan_result_reeval` or `bit_import`;
     - no `DELETE` on `scan`, `scan_job`, `agent`, `policy` or `system_schedule`.

   On real PostgreSQL the tester's probe matrix confirms each success or 42501, including through the parent, `scan_result_default`, a monthly partition and a later owner-created table (CHK-M1-130 to -137). The whole-schema diff including table, column and default ACLs shows 0 differences against the reference built from the spec (CHK-M1-150).
2. **View and grant:** `CREATE VIEW v_plugin AS SELECT p.*, f.family_name || ' - ' || p.plugin_name AS display_name FROM plugin p JOIN family f USING (family_id); GRANT SELECT ON v_plugin TO bitscan_app;` are identical to TS L1038-1041 (CHK-M1-135).
3. **`system_schedule` seed:** identical to TS L832-833: `('inventory', 21600), ('offline_sweep', 60), ('retention', 86400)`.
4. **Settings:**
   - Inserted with `op.bulk_insert` on a `sa.table` with a `JSONB` column, so the values are bound parameters. No JSON text appears in any SQL string, and the static `STATEMENTS` compile byte-identically with 0 binds.
   - Six keys in TS §8.6 table order, with bare numbers `365, 300, 7, 2, 50` and a 5-element list for `redaction_patterns` (#42).
   - There is no `inventory_interval_s` row (it lives in `system_schedule`, L1327), and no key that disables inventory.
   - **`REDACTION_PATTERNS` are byte-identical to TS L1332-1336.** I read them from the spec's text fence and compared them as Python strings. All five compile with RE2. The tester checks the decoded JSON round-trip on PostgreSQL (CHK-M1-141, -142).
5. **Partitions:**
   - They are created last, after the default privileges and the `ON ALL TABLES` grants.
   - The UTC month boundaries come from `datetime.now(UTC)` via `month_starts`, which normalises non-UTC input. My check covered 2026-10-20 (Oct to Feb), 2026-11-30 (Nov to Mar) and 2026-12-31 23:59:59 (Dec to Apr), so the December rollover is correct.
   - Names are `scan_result_YYYY_MM` (#43).
   - The DDL is composed with `psycopg.sql.SQL(...).format(sql.Identifier(name), sql.Literal(low), sql.Literal(high))`. It renders as `CREATE TABLE "scan_result_2026_10" PARTITION OF scan_result FOR VALUES FROM ('2026-10-01 00:00:00+00:00'::timestamptz) TO ('2026-11-01 00:00:00+00:00'::timestamptz)`. There is no f-string or string-built SQL, and no input from outside the code. The only `noqa` in the file is `E501`; S608 is not suppressed.
   - The DDL runs on Alembic's own connection and transaction, so it executes as `bitscan_owner`.
   - The tester confirms exactly four contiguous partitions, with owner `bitscan_owner`, default ACLs, routing and an empty default (CHK-M1-143 to -146).
6. **Re-run and idempotence:** not a problem, and no change is needed.
   - Alembic applies `m0005` exactly once per database, recorded in `alembic_version`, and a second `db migrate` is a no-op (CHK-M1-050-r6).
   - If the first migrate happens in a later month, `m0005` creates that month plus the next three, which is still correct.
   - Creating later months, and tolerating partitions that already exist, belongs to `db maintain` (TASK-019). Per #43 it finds partitions by their bounds, not by name.
   - `m0005` must not be changed to "create if missing": that would edit an applied, forward-only migration.
7. **Scoped bind-trap scanner** (`tests/test_db_migrate.py:260-321`, the lead's ruling):
   - only two named constants, `REDACTION_PATTERNS` and `SETTINGS`, are exempt, and only in `m0005_privileges_seeds.py`;
   - the exemption is dropped automatically if either name appears in `execute`, `text`, `exec_driver_sql` or `.format` arguments, an f-string, or `%`/`+`;
   - every other string literal in every migration is still scanned;
   - this is necessary, because the patterns themselves contain `(?:AKIA`, which `text()` would turn into a bind.
8. **Forward-only and lint:**
   - `revision = "m0005"`, `down_revision = "m0004"`, and `downgrade()` only raises;
   - each `noqa: E501` sits on a literal holding a spec line over 88 characters (the three `ALTER DEFAULT` lines, the `UPDATE` and column-`UPDATE` grants, the app `DELETE` grant, and redaction pattern 2);
   - ruff, format and `mypy --strict` are clean (36 files);
   - 7 mutations of m0005 each turn a test red. The 2 equivalent mutants (dropping `GRANT SELECT ON v_plugin`; partitions before the grants) are genuinely unobservable, because the default privileges and `ON ALL TABLES` give the same ACL.

## Findings

1. **nit (test, defence in depth).** The scanner's exemption follows names, so an alias such as `x = SETTINGS; op.execute(x[0][0])` would keep the exemption, because `x` is not an allowed name. This is acceptable: the scanner is a backstop and review is the control for migration SQL. If wanted, drop the exemption whenever an allowed name appears anywhere except as an argument to `op.bulk_insert`.
2. **note.** The partition months come from the migrating host's clock. Hosts must be NTP-synced (TS §3.3), and `db maintain` (TASK-019) creates any later months it finds missing, so a skewed clock at the first migrate is corrected by maintenance.
3. **note (spec topic for `main`; also tester-b's TP-M1-02 observation 4).** On PostgreSQL 15 and later, PUBLIC keeps `USAGE` on schema `public`, so the spec's `GRANT USAGE ON SCHEMA public TO bitscan_app, bitscan_retention` has no visible effect. `CREATE` stays refused (CHK-M1-137-pg16). This is not a defect, but if the owner wants `USAGE` limited to the named roles, that needs a spec decision, because it would add a `REVOKE` the spec does not list.
