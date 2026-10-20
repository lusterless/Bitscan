# TASK-014 REVIEW: migration `m0001` (extensions and policy catalog)

Reviewer: reviewer. Date: 2026-10-20. REQ-021, REQ-020. Spec: TS §5.2 L638-707 (the DDL is the schema, CLAUDE.md), TS §5.3 L1046 (Alembic, forward-only, as `bitscan_owner`), TS §5.1 L625-629; decisions PD-18 (split into `m0001` to `m0005`), #40 (reference database), #41. Inputs: `work/plans/TASK-014.md`, `work/reports/TASK-014-impl.md`, `work/reports/TASK-014-test.md` (PASS; WSL, `CI=true`, 293 passed), `tests/m1/report.md` CHK-M1-070 to -074, -053-r2, -059, -022, -023-r2, -058-r2, -050-r2.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268).

## What was checked

- **Verbatim against the spec, by my own script.** I read TS L638-707 from the spec file, removed each `--` comment outside string literals plus trailing whitespace and blank lines, and compared the result line by line with the joined `STATEMENTS`. The 63 lines are identical, so only SQL comments were removed. That covers:
  - the 3 extensions;
  - the 3 types, with `plugin_operator`'s 14 labels in spec order;
  - every column, type, `NOT NULL`, `DEFAULT`, `CHECK` (`timeout_s BETWEEN 1 AND 600`, the `mode` and `outcome` sets), PK and UNIQUE;
  - the FKs, with `ON DELETE CASCADE` only on `policy_plugin.policy_id`;
  - the composite PK.
- **Nothing extra:** no grants, seeds, extra indexes, `SET ROLE`, `RESET` or `search_path`. Grants come in TASK-018.
- **No bind or format traps:**
  - 11 static string literals, with no f-strings, `%` or `.format`;
  - no `:` or `%` anywhere in the SQL;
  - `text(stmt).compile(dialect=postgresql.psycopg)` gives 0 bind parameters for all 11;
  - the tester's bind-trap scanner (CHK-M1-059) and its plants are red.
- **Forward-only:** `revision = "m0001"`, `down_revision = None`, a typed `upgrade()`, and `downgrade()` only raises `NotImplementedError("forward-only (TS §5.3)")`. This follows the `env.py` convention (CHK-M1-053-r2).
- **Created as `bitscan_owner`:**
  - the migration runs on TASK-013's connection after `SET ROLE bitscan_owner` and the `current_user` check;
  - on real PostgreSQL, every new object is owned by `bitscan_owner` and `db migrate` reruns as a no-op (CHK-M1-050-r2).
- **`CREATE EXTENSION IF NOT EXISTS` as `bitscan_owner`:** safe. After the Bootstrap the three extensions exist, so PostgreSQL skips them with a NOTICE, and `db migrate` exits 0 on the TLS test container (CHK-M1-050-r2).
- **E501 `noqa`:** it sits after the closing quotes of the last literal, which holds the 91-character spec line. Ruff applies a `noqa` on a multi-line string only to that string, so it covers only that literal, and there is no config change.
- **Tests:** `test_schema_catalog.py` (written from the spec before the migration was read) and `schema_diff.py` (#40: the reference is extracted from the spec at test time into a separate `bitscan_ref` database) cover REQ-021 (1) to (5):
  - diff-equality;
  - enum label order;
  - `timeout_s` 0, 601 and -1 rejected, 1 and 600 accepted, default 60;
  - the `mode` and `outcome` sets;
  - the defaults;
  - UNIQUE (23505), FKs (23503) and the cascade.

  7 mutations of m0001 each turn a test red.
- **Gates:** ruff and format are clean, and `mypy --strict` reports no issues in 25 files.

## Findings

None blocking.

1. **note, for TASK-015 to TASK-018.** The impl report's bind demo shows that a JSON literal such as `'{"all":true}'` becomes a bind parameter when passed through `text()`. Later migrations with JSON or `::` casts must keep the bind-trap scanner green, and review will check each one.
