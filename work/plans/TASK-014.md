# TASK-014 plan: the initial migration set (TASK-014 to TASK-018)

REQs: REQ-020 to REQ-027. Owner: impl-manager. Chain: `m0001` (TASK-014) → `m0002` (TASK-015) → `m0003` (TASK-016) → `m0004` (TASK-017) → `m0005` (TASK-018). One migration per PR (TS §5.3 L1046). Tests: TP-M1-05 to TP-M1-12. Conventions (file names, `revision`, `downgrade()` raising, no `alembic.ini`): `work/plans/TASK-013.md` step 6.

## Spec quotes

- TS §5.2 L637–L1014 (DDL), L1037–L1042 (view). `.claude/CLAUDE.md`: "The DDL in TS §5.2 is the schema. Alembic migrations must reproduce it exactly, including grants."
- TS §5.3 L1046: "The first migration seeds `system_schedule` and the default settings, and creates `scan_result` partitions for the current month and the next three." PD-18 (user, 2026-10-20): the initial set is several migrations, and the seeding and partitions go in the last one. The schema-diff test compares the **final** schema.
- TS §5.2 L916: "Must stay empty: the first migration creates monthly partitions for the current month and the next three (§5.3)".
- TS §8.6 L1319–L1336: the default settings and the five redaction patterns, "exactly as written".

## The split

Each migration copies its spec lines **verbatim**: same statement order, same column order, same constraint text. SQL comments are left out (they do not reach the catalog; see the `:word` hazard in TASK-013). A migration splits a statement only where this table says so.

| Migration | Task | Spec lines | Creates | FK targets (must already exist) | Est. LOC |
| --- | --- | --- | --- | --- | --- |
| `m0001_catalog` | TASK-014 | L638–L707 | extensions `pg_trgm`, `pgcrypto`, `debversion` (no-ops after the Bootstrap, L1029); types `policy_status`, `plugin_state`, `plugin_operator`; tables `family`, `policy`, `plugin`, `policy_plugin`, `bit_import` (with their BIGSERIAL sequences) | in-file only: `policy`→`family`; `plugin`→`family`, `policy`; `policy_plugin`→`policy`, `plugin` | 95 |
| `m0002_fleet_inventory` | TASK-015 | L709–L825 | type `agent_status`; `agent` + `ix_agent_status`, `ix_agent_hostname_trgm`; `agent_ip_seen`; `agent_tag`; `enrollment_token`; `enrollment_request`; `os_info`; `package` + `ix_package_name_trgm`, `ix_package_name_debver`; `agent_package` + `ix_agent_package_pkg`; `inventory_snapshot` | in-file only: `agent_*`, `os_info`, `inventory_snapshot`→`agent`; `enrollment_request`→`agent`, `enrollment_token`; `agent_package`→`agent`, `package`. Needs `pg_trgm` and `debversion` (`m0001`) | 140 |
| `m0003_scanning` | TASK-016 | L842–L938 | types `scan_state`, `check_result`; `scan_schedule`; `scan`; `scan_job` + `ix_job_pending`; `scan_result` (PARTITION BY RANGE) + `scan_result_default`; function `scan_result_check_job()`; trigger `scan_result_job_check`; `scan_result_reeval` | `policy`, `plugin` (`m0001`); `agent` (`m0002`); in-file `scan`→`scan_schedule`; `scan_job`→`scan`, self; `scan_result`, `scan_result_reeval`→`scan_job` | 120 |
| `m0004_system` | TASK-017 | L827–L831 (`system_schedule`, **without** the INSERT at L832–L833), L835–L840 (`setting`), L941–L990 | `system_schedule`; `setting`; `task`; type `user_role`; `app_user`; `user_token` + `ix_user_token_active`; `audit_log` (+ `audit_log_audit_id_seq`) | in-file only: `user_token`→`app_user` | 80 |
| `m0005_privileges_seeds` | TASK-018 | L993–L1013; L1038–L1041; L832–L833; TS §8.6 L1319–L1336; TS §5.3 L1046 | 3 default-privilege rules; table and sequence grants; `v_plugin` + its grant; seed rows of `system_schedule` and `setting`; 4 monthly `scan_result` partitions | everything above | 130 |

Why `system_schedule` and `setting` sit in `m0004` and not `m0002`: TS §5.1 L633 puts them in the "System" area, and their seed must go in the last migration (PD-18). They have no FKs, so either place is valid.

Every FK points backwards (to an earlier migration or earlier in the same file). No migration references a table created later. The chain is linear.

## `m0005` statement order

1. The three `ALTER DEFAULT PRIVILEGES FOR ROLE bitscan_owner …` lines (L994–L996).
2. `GRANT … ON ALL TABLES` and `ON ALL SEQUENCES` (L997–L999). These cover every table from `m0001` to `m0004`, `scan_result_default` and `alembic_version`.
3. The retention grants (L1001–L1004), then the app UPDATE, column-UPDATE and DELETE grants (L1007–L1013), verbatim.
4. `CREATE VIEW v_plugin …; GRANT SELECT ON v_plugin TO bitscan_app;` (L1038–L1041).
5. Seeds:
   - `INSERT INTO system_schedule (job_kind, interval_s) VALUES ('inventory', 21600), ('offline_sweep', 60), ('retention', 86400);` (static, L832–L833).
   - `setting`: six rows with **bound parameters** (`op.get_bind().execute(sa.text("INSERT INTO setting (key, value) VALUES (:key, CAST(:value AS jsonb))"), rows)`). The values are JSON built with `json.dumps`, and their shape follows #42. The patterns are Python raw strings copied from TS §8.6 L1332–L1336. A unit test in TP-M1-11 compares them byte for byte with the spec file. `updated_by` is left NULL ("NULL = seeded by the system", L838).
6. Partitions, created after step 1 so they get their ACL from the default privileges (which TP-M1-11 checks). One static PL/pgSQL `DO` block: set the month boundary time zone (#43, suggested `SET LOCAL TimeZone = 'UTC'`), then for `i` in 0..3 compute `date_trunc('month', now()) + i * interval '1 month'` and `EXECUTE format('CREATE TABLE %I PARTITION OF scan_result FOR VALUES FROM (%L) TO (%L)', name, lo, hi)`. Names per #43, suggested `scan_result_YYYY_MM`. The quoting happens in the server, and no Python string formatting is used (G1, S608).

The final ACL on `v_plugin` is SELECT and INSERT for `bitscan_app` and SELECT for `bitscan_retention`, whatever the order. If the view exists before step 2, `GRANT … ON ALL TABLES` includes views. If it is created after step 1, the default privileges apply. That is what the spec's own DDL produces, so the diff reference (#40) has it too. The INSERT cannot succeed, because a join view is not auto-updatable. It is recorded in open-questions part 5, report only.

## Data the tests need

- Constraint tests before `m0005` run as `bitscan_owner`, because `bitscan_app` has no grants yet. TP-M1-05 to TP-M1-09 are written that way, and TP-M1-10 covers the grants.
- Per-domain diffs (TP-M1-05 to TP-M1-09) compare only the objects that exist so far and leave out ACLs. The final diff (TP-M1-12) compares everything, including ACLs and default ACLs.

## Edge cases

- `scan_result_check_job()` is `LANGUAGE plpgsql` and `SECURITY INVOKER` (the default). When `bitscan_app` inserts a result, the trigger's SELECT on `scan_job` runs as `bitscan_app`, which has SELECT after `m0005`.
- A BEFORE ROW trigger on a partitioned table is cloned to every partition, existing and future. TP-M1-08 checks an insert straight into `scan_result_default`, and TP-M1-13 checks one into a partition made by `db maintain`.
- `result … GENERATED ALWAYS AS (…) STORED`: copy the expression exactly. The diff compares `pg_get_expr(adbin)`.
- `enrollment_token.uses CHECK (uses <= max_uses)` is a column CHECK that names another column. PostgreSQL accepts it as written and stores it as a table check. The diff compares the constraint definition, not where it was written.
- `agent_tag.agent_id` has no `NOT NULL` in the spec (L743), but as a PRIMARY KEY column it becomes NOT NULL anyway. Copy the spec text and let the diff confirm.
- `CREATE EXTENSION IF NOT EXISTS debversion` inside a migration: TASK-013 plan, last edge case.
- `CHAR(64)` versus `VARCHAR`: copy the spec types exactly. `bpchar(64)` is what the catalog shows.

## Not in this set

Retention row deletes (M11), the default-partition alert (#44, M2 or later), and any index or table the spec does not list.
