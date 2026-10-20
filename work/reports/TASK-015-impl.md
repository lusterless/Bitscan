# TASK-015 IMPL report: migration m0002 (fleet and inventory)

REQs: REQ-022, REQ-029. Spec: TS §5.2 L709–L825 (verbatim), TS §7.2 (versions compared as `debversion`), TS §5.3 L1046. Plan: `work/plans/TASK-014.md` (split table, row `m0002_fleet_inventory`).

## File (1)

- `manager/bitscan_manager/db/migrations/versions/m0002_fleet_inventory.py` (159 lines, mostly SQL): `revision = "m0002"`, `down_revision = "m0001"`. `STATEMENTS` holds 15 static string literals, run in order with `op.execute`. `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

## What it creates, in spec order

`agent_status`; `agent`, `ix_agent_status`, `ix_agent_hostname_trgm`; `agent_ip_seen`; `agent_tag`; `enrollment_token`; `enrollment_request`; `os_info`; `package`, `ix_package_name_trgm`, `ix_package_name_debver`; `agent_package`, `ix_agent_package_pkg`; `inventory_snapshot`. That is the type, the nine tables and the five indexes; BIGSERIAL sequences come with `enrollment_token`, `enrollment_request`, `package` and `inventory_snapshot`.

The block ends at L825. `system_schedule` (L827 onwards) is not included; it belongs to m0004. There are no grants, seeds or extra indexes.

## How the text was produced

The same one-off script as for m0001 was run on L709–L825. It removes `--` comments with their leading whitespace, trailing whitespace and blank lines, and splits at lines ending in `;`. Its guards:
- the block starts at the `-- ===== Fleet =====` line and ends at `);`, with `CREATE TABLE system_schedule` after the blank line;
- no `--` sits inside a string literal (the code part of each line has an even number of `'`);
- no `%`, no `\`, and no `:` except in `::`.

One statement, `CREATE TYPE agent_status AS ENUM (…)` (L710, 110 characters), is kept verbatim with `# noqa: E501` after that literal only.

## Checks run (Windows, offline)

| Check | Result |
| --- | --- |
| Migration lines == comment-stripped spec L709–L825 | True (106 lines) |
| `sa.text(stmt).compile(dialect=postgresql.psycopg)` bind parameters | none in any statement |
| Alembic `as_sql` output | every statement unchanged; `(version::debversion)` intact; no `%%` |
| Script directory | head `m0002`, chain `m0002 → m0001` |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (26 files) | pass |
| Real PostgreSQL (diff-equal to TS §5.2, REQ-022 cases, the 500-pair `debversion` suite, `EXPLAIN` on `ix_package_name_debver`) | **NOT RUN by me** (WSL root runs are blocked for me); the tester's harness covers it |

## For the tester

- After `db migrate`, stdout is `m0002`. An already-migrated `m0001` database upgrades to `m0002` only.
- Still no ACLs beyond the owner's, so REQ-022 and REQ-029 cases run as `bitscan_owner` until m0005.
- `gen_random_uuid()` (the `agent_id` default) is built into PostgreSQL 13 and later; `gin_trgm_ops` needs `pg_trgm`, and `::debversion` needs `debversion`, both from m0001 and the Bootstrap.
