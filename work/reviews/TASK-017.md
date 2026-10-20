# TASK-017 REVIEW: migration `m0004` (system tables)

Reviewer: reviewer. Date: 2026-10-20. REQ-024. Spec: TS §5.2 L827-831, L835-840, L941-990; TS §3.4 and §6.2 (inventory cannot be disabled); TS §5.3 L1046; PD-18 (seeds in the last migration). Inputs: `work/plans/TASK-014.md` (split table row `m0004_system`), `work/reports/TASK-017-impl.md`, `work/reports/TASK-017-test.md` (PASS; WSL, `CI=true`, 358 passed, 9 mutations red), `tests/m1/report.md` CHK-M1-096 to -098, -050-r5.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268).

## What was checked

- **Verbatim against the spec, by my own script.** The three spec ranges, in order: L827-831 (`system_schedule`, stopping before the seed `INSERT` at L832-833), L835-840 (`setting`) and L941-990 (`task`, `user_role`, `app_user`, `user_token` with `ix_user_token_active`, `audit_log`). Comments removed outside string literals, with trailing whitespace and blank lines dropped, then compared line by line with the joined `STATEMENTS` (8 statements). Result: 57 lines, identical. Only comments were removed.
- **Inventory cannot be disabled:** `system_schedule` has no `enabled` column, as the spec says (L827 comment; CHK-M1-097).
- **No seeds:** no `INSERT` at all. The `system_schedule` and `setting` defaults go into m0005, per PD-18 and the split table, and both tables are empty at m0004 (CHK-M1-096).
- **No bind or format traps:** all 8 statements compile byte-identically through `text(…).compile(dialect=postgresql.psycopg)`, with 0 bind parameters, no `%`, no f-strings and no `.format`.
- **Nothing extra:** no grants (m0005), and no `SET ROLE`, `RESET` or `search_path`.
- **Forward-only:** `revision = "m0004"`, `down_revision = "m0003"`, and `downgrade()` only raises `NotImplementedError`.
- **E501 `noqa`:** the only lines over 88 characters are 99 characters (`:17`) and 104 characters (`:34`), both spec lines. Each `noqa` sits after its own literal's closing quotes (`:21`, `:40`), so each covers only that literal.
- **Tests** (`test_schema_system.py`, 30 pg cases, written from the spec before the migration was read):
  - REQ-024 (2): the `job_kind` set; `interval_s` 59 and 86401 rejected; inventory 3599 rejected and 3600 accepted.
  - REQ-024 (3): `kind='api'` with `totp_verified` rejected; `token_hash` is `CHAR(64) NOT NULL UNIQUE`; the partial index is `WHERE revoked_at IS NULL`.
  - REQ-024 (4) to (6): the `app_user` defaults and `user_role` label order; the `task` kind and state sets; the `audit_log` hash columns.
  - `conftest.migrate_to()` reaches the m0004-only state as `bitscan_migrate` with `SET ROLE bitscan_owner`, with no superuser.
  - 9 mutations each turn a test red.
  - ruff, format and `mypy --strict` are clean (32 files).

## Findings

None.
