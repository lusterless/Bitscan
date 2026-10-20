# TASK-014 IMPL report: migration m0001 (extensions and policy catalog)

REQs: REQ-021, REQ-020. Spec: TS §5.2 L638–L707 (verbatim), TS §5.3 L1046 (Alembic, forward-only, as `bitscan_owner`). Plan: `work/plans/TASK-014.md` (split table, row `m0001_catalog`). Conventions: `work/plans/TASK-013.md` step 6 and the `env.py` docstring.

## File (1)

- `manager/bitscan_manager/db/migrations/versions/m0001_catalog.py` (about 110 lines, mostly SQL): `revision = "m0001"`, `down_revision = None`. `STATEMENTS` is a tuple of 11 static string literals. `upgrade()` runs each with `op.execute`. `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

## What it creates, in spec order

- Extensions `pg_trgm`, `pgcrypto`, `debversion` (`IF NOT EXISTS`; no-ops after the Bootstrap, TS §5.2 L1029).
- Types `policy_status`, `plugin_state`, `plugin_operator`.
- Tables `family`, `policy`, `plugin`, `policy_plugin`, `bit_import` (BIGSERIAL sequences come with them).

No grant, no index beyond the spec's PK and UNIQUE constraints, and no seed. Grants are TASK-018.

## How the text was produced (exact copy)

A one-off script read TS §5.2 L638–L707 from the spec file. It removed each `--` comment and its leading whitespace, removed trailing whitespace and blank lines, split statements at the line ending in `;`, and wrote them as literals. Column alignment, case, the spacing inside `ENUM (...)` and the trailing `;` are kept as in the spec. The script first checked that no `--` sits inside a string literal: the four hits were `DEFAULT ''` and `DEFAULT '1.0'` followed by a comment.

One spec line (`outcome … CHECK (outcome IN ('success','skipped','rejected'))`, 91 characters) is over ruff's 88. It is kept verbatim, with ruff's multi-line-string `# noqa: E501` after that literal's closing quotes; there is no config change.

## Bind-parameter and `%` safety (proved offline)

- After comment removal, L638–L707 contain no `:` and no `%`.
- `sa.text(stmt).compile(dialect=postgresql.psycopg)` gives zero bind parameters for all 11 statements.
- Alembic `as_sql` output (a `MigrationContext` with `dialect_name="postgresql"`, running `upgrade()`) contains every statement unchanged, with no `%%` and no `:word`.
- Demos, for TASK-015 to TASK-018 (none applies to m0001):
  - `'1.0'::debversion` stays as is, with no bind;
  - `'{"all":true}'` becomes bind `true` (compiled `%(true)s`), so that statement must not go through `text()` unescaped;
  - `'a\:b'` reaches the driver as `a:b`.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| Migration lines == comment-stripped spec L638–L707 | True (63 lines) |
| Bind parameters / emitted SQL unchanged | none / yes |
| Alembic script directory | head `m0001`, `down_revision None`; `downgrade()` raises `NotImplementedError` |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (23 files) | pass |
| **Real PostgreSQL** (`db migrate` creates the objects owned by `bitscan_owner`; extensions are no-ops as the owner; a rerun is a no-op) | **NOT RUN by me.** WSL root runs were blocked by the auto-mode classifier in TASK-013, so I did not retry. The tester's harness covers it (TP-M1-05) |

## For the tester

- After `db migrate`, the CLI prints `m0001` (it was `base`), and `alembic_version` holds `m0001`.
- Objects to expect in `public`, all owned by `bitscan_owner`:
  - tables `family`, `policy`, `plugin`, `policy_plugin`, `bit_import`;
  - sequences `family_family_id_seq`, `policy_policy_id_seq`, `bit_import_import_id_seq`;
  - the PK and UNIQUE indexes;
  - the 3 enum types;
  - and `alembic_version`.
- No ACLs beyond the owner's yet, so constraint tests must run as `bitscan_owner` (plan "Data the tests need").
- The extension statements run as `bitscan_owner`. Already created by the Bootstrap, they should be skipped with a NOTICE. If PostgreSQL instead refuses `CREATE EXTENSION IF NOT EXISTS debversion` for a non-superuser even when it exists, that is a finding for me.
