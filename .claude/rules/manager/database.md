---
paths:
  - "manager/**/db/**"
  - "manager/**/repositories/**"
  - "manager/**/migrations/**"
  - "manager/**/services/retention/**"
  - "**/*.sql"
---

# Database rules

Table map: TS §5.1. Schema, grants and bootstrap: TS §5.2 (implement the DDL exactly: types, tables, columns, defaults, indexes, view). Data rules: TS §5.3. Catalog columns: SR §3. Read them before changing a table, a grant or a query that writes.

## Migrations

- Alembic, forward-only (no downgrade), one migration per PR, reviewed. No manual DDL in production.
- `bitscan-manager db migrate` runs as `bitscan_migrate` with `SET ROLE bitscan_owner`. The first migration seeds `system_schedule` and the default settings and creates `scan_result` partitions for the current month plus the next three.

## Roles and grants

- `bitscan_owner` (no login) owns every table. Migrations and `db maintain` connect as `bitscan_migrate` and run `SET ROLE bitscan_owner`, so new tables and partitions are owned by `bitscan_owner`. `bitscan_migrate` runs migrations and partition maintenance only.
- `bitscan_app` gets `SELECT, INSERT` on every table by default (default privileges cover partitions created later) and `USAGE` on sequences. UPDATE or DELETE exists only where TS §5.2 grants it explicitly. A migration that adds a table must add any UPDATE or DELETE grant it needs.
- `bitscan_app` UPDATE: `policy`, `family`, `plugin`, `agent`, `enrollment_token`, `enrollment_request`, `os_info`, `agent_package`, `agent_ip_seen`, `scan_schedule`, `setting`, `system_schedule`, `app_user`, `user_token`, `task`. DELETE: `policy_plugin`, `agent_tag`, `agent_package`, `agent_ip_seen`, `scan_schedule`.
- `bitscan_app` must never UPDATE, DELETE or TRUNCATE `audit_log`, `scan_result` (or any partition), `scan_result_reeval` or `bit_import`.
- `bitscan_app` must never DELETE `scan`, `scan_job`, `agent`, `policy` or `system_schedule`.
- On `scan_job`, the app may UPDATE only `state, dispatched_at, started_at, deadline_at, finished_at`. On `scan`, only `state, finished_at`.
- `bitscan_retention` may SELECT everything (also via default privileges), may DELETE only from `scan`, `scan_job`, `scan_result`, `scan_result_reeval`, `inventory_snapshot`, `enrollment_request`, `user_token`, `audit_log` and `package`, and may INSERT `audit.checkpoint` rows into `audit_log` (with `USAGE` on `audit_log_audit_id_seq`).
- Bootstrap (once, superuser, before the first migration): `bitscan_owner` NOLOGIN; `bitscan_app`, `bitscan_retention` LOGIN; `bitscan_migrate` LOGIN IN ROLE `bitscan_owner`; database `bitscan` owned by `bitscan_owner`, `REVOKE ALL … FROM PUBLIC`, CONNECT only for app, retention and migrate; schema `public` owned by `bitscan_owner`, with `USAGE` for app and retention; extensions created there.
- Never weaken these grants to make code work. Change the code instead, for example `INSERT … ON CONFLICT DO NOTHING` and then a SELECT, because the app has no UPDATE on `package`.
- The role split guards against bugs and injection in the API, not against a compromise of the whole manager (both DSNs live in its process).

## Invariants the database enforces

- `system_schedule` has no `enabled` column, its rows are seeded by the first migration (`inventory` 21600, `offline_sweep` 60, `retention` 86400), `job_kind` is one of those three, `interval_s` is 60–86,400, and the inventory interval is 3,600–86,400 s.
- `scan_result.job_created_at` must equal `scan_job.created_at`; a trigger rejects anything else.
- `policy.source_file` is UNIQUE (path relative to the bits folder). A deleted policy's `source_file` becomes `deleted/<policy_id>`; `deleted_at` marks a soft delete and the row is kept. `policy` has `policy_status` (effective), `file_status` and `status_overridden` (default false).
- `plugin.owner_policy_id` is NOT NULL; `plugin.timeout_s` defaults to 60 with CHECK 1–600.
- `enrollment_token`: `max_uses` is 1–10,000 (default 1) and `uses <= max_uses` (default 0); `auto_approve` defaults to false; `allowed_cidrs` NULL means any source; `expires_at` is NOT NULL. Increment atomically with `UPDATE … WHERE uses < max_uses RETURNING`.
- Token hashes are `CHAR(64) NOT NULL UNIQUE` SHA-256 values, never tokens: `agent.token_hash`, `enrollment_token.token_hash`, `enrollment_request.new_token_hash`, `user_token.token_hash`. `agent.machine_id` is `CHAR(32) NOT NULL UNIQUE`.
- `agent_status` is `awaiting_approval`, `enrolled` (approved, no heartbeat yet), `online`, `stale`, `offline`, `decommissioned`. `user_role` is `viewer`, `operator`, `admin` (default `viewer`).
- `user_token`: API tokens can never be `totp_verified` (`CHECK (kind = 'session' OR NOT totp_verified)`).
- `scan_job`: `CHECK ((kind = 'compliance') = (scan_id IS NOT NULL))` and `CHECK (kind = 'inventory' OR eval_spec IS NOT NULL)`; `eval_spec` is never sent to agents.
- `scan_result`: `eval_code` CHECK in (0, 1, 2); `result` is a generated column; snapshots `plugin_name_snap`, `execute_snap`, `operator_snap`, `expected_snap` are NOT NULL.
- `package` is UNIQUE (name, version, architecture) with trigram index `ix_package_name_trgm` and `ix_package_name_debver` on `(name, (version::debversion))`.
- `audit_log` is append-only and hash-chained (`prev_hash`, `row_hash`).
- `display_name` is never stored: read it from view `v_plugin` (`family_name || ' - ' || plugin_name`), granted SELECT to `bitscan_app`.
- Users are never deleted, only disabled. `*_by` columns hold `app_user` ids without foreign keys.

## Writing results

- First result wins per host and plugin. Lock the original job row with `SELECT … FOR UPDATE` on `COALESCE(retry_of, job_id)`, skip plugins that already have a result in the original or its retry, then insert (TS §4.4).
- Evaluate and insert the result and its verdict in one statement. `scan_result.result` is a generated column; never write it.
- Re-evaluations add `scan_result_reeval` rows. Original results never change.

## Partitions and retention

- `scan_result` is partitioned by month on `job_created_at`. The first migration creates the current month plus the next three. `db maintain` (daily timer) keeps three future months and drops whole partitions past retention. The default partition must stay empty; rows in it alert.
- Retention (TS §5.3): whole scans (`scan`, `scan_job`, `scan_result`, `scan_result_reeval`) together after 400 days, `inventory_snapshot` after 180 days, decided enrolment requests and expired user tokens after 90 days, `audit_log` after 3 years, inventory jobs 30 days after they finish, and unreferenced `package` rows daily.
- Before deleting `audit_log` rows, write an `audit.checkpoint` entry with the last deleted id and `row_hash`.

## Locks

- Every `audit_log` insert takes `pg_advisory_xact_lock(hashtext('audit_log'))` and sets `prev_hash` and `row_hash`.
- Every import, rebuild and policy delete takes `pg_advisory_lock(hashtext('catalog'))` before its transaction, and releases it after the upload file is renamed or deleted.

## Package versions

- `package.version` is text. Compare it with `version::debversion`, which uses `ix_package_name_debver`. Never compare Debian versions as text.

Tests (TS §8.3): Integration on a freshly migrated database (grant probes in `.claude/rules/testing.md`, including a newly created partition; partition maintenance; trigger and CHECK rejections (TS §5.2); retention deletes and checkpoint (TS §5.3)).
