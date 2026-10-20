# TASK-017 IMPL report: migration m0004 (system tables)

REQ: REQ-024. Spec: TS §5.2 L827–L831, L835–L840, L941–L990 (verbatim), TS §5.3 L1046. Plan: `work/plans/TASK-014.md` (split table, row `m0004_system`).

## File (1)

- `manager/bitscan_manager/db/migrations/versions/m0004_system.py` (97 lines, mostly SQL): `revision = "m0004"`, `down_revision = "m0003"`. `STATEMENTS` holds 8 static string literals, run in order with `op.execute`. `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

## What it creates, in spec order

`system_schedule` (L827–L831; no `enabled` column), `setting` (L835–L840), `task`, type `user_role`, `app_user`, `user_token` + partial index `ix_user_token_active`, and `audit_log` (with `audit_log_audit_id_seq`; `prev_hash` and `row_hash` are DDL only).

**Not included:** the `system_schedule` seed INSERT (L832–L833), which goes in m0005 with the other seeds (PD-18, plan step 5). So `system_schedule` and `setting` are empty after m0004. No grants.

## How the text was produced

The same one-off script as before, run on the three ranges in order. Its guards:
- `L827` starts `CREATE TABLE system_schedule (` and `L831` is `);`; `L832`–`L833` is the INSERT (left out); `L835` starts `CREATE TABLE setting (` and `L840` is `);`;
- `L940` is `-- ===== System =====`, `L941` starts `CREATE TABLE task (`, `L990` is `);` and `L992` starts the Privileges section;
- no `--` inside a string literal, and no `INSERT`, `%`, `\` or `:` (not even `::`) in the result.

Comments removed include the `{id}` route and the `…` in the `audit_log.action` comment. Two statements have spec lines over 88 characters (`system_schedule.job_kind`, and `task.state`). Each keeps its text verbatim, with `# noqa: E501` after that literal only.

## Checks run (Windows, offline)

| Check | Result |
| --- | --- |
| Migration lines == comment-stripped spec (three ranges) | True (57 lines); no INSERT |
| Bind parameters (`sa.text().compile`, psycopg dialect) | none |
| Alembic `as_sql` output | every statement unchanged; no `%%` |
| Script directory | chain `m0004 → m0003 → m0002 → m0001` |
| Tester's scanner and forward-only checks (`tests/test_db_migrate.py -k "bind or forward or downgrade or offline"`) | 5 passed, 3 pg skipped |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (31 files) | pass |
| Real PostgreSQL (diff-equal, empty `system_schedule` and `setting`, REQ-024 cases) | **NOT RUN by me** (WSL root runs are blocked for me); the tester's harness covers it |

## For the tester

- `db migrate` prints `m0004`.
- `system_schedule` and `setting` must have 0 rows after m0004. M2's `/readyz` would fail on that, but nothing reads it in M1.
- Constraint cases still run as the owner (no grants until m0005).
