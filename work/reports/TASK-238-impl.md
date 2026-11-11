# TASK-238 IMPL: audit retention repository

Implementer: impl-manager-b, 2026-11-08. REQ-276. Spec: TS §5.3 L1049 (`audit_log` after 3 years), L1051 (`bitscan_retention` may delete and insert checkpoints), L1053 (checkpoint before delete); TS §5.2 L983–L992 (`audit_log`), L1002–L1006 (grants). Open items: #39 (checkpoint keys), #150 (d). Plan: `work/plans/TASK-242.md` §3. High risk (the user's second look, PD-47).

## Files (1 new file, about 55 lines)

- `manager/bitscan_manager/repositories/retention_audit.py` (new). Every function runs in the caller's transaction, never commits, and uses parameterised statements only:
  - `oldest(conn, n) -> list[tuple[int, datetime]]`: `SELECT audit_id, at FROM audit_log ORDER BY audit_id LIMIT %s`. `n < 1` raises `ValueError`, and a non-timestamp `at` raises `TypeError`.
  - `row_hash(conn, audit_id) -> str`: `SELECT row_hash FROM audit_log WHERE audit_id = %s`. A missing id raises `LookupError("audit entry not found")`.
  - `delete_through(conn, audit_id) -> int`: `DELETE FROM audit_log WHERE audit_id <= %s`, returning the row count. It raises `RuntimeError` on an autocommit connection, because the checkpoint and the delete must commit together (TS §5.3 L1053).

## Behaviour the tester should know

- The checkpoint is not written here. TASK-242 appends it through `services.audit.chain.append_entry(PgAuditRepo(conn), …)`, which takes the chain lock, before `delete_through`, in the same transaction (plan §4 step 7).
- The `<= N` delete removes the whole prefix only because `N` comes from `rules.audit_prefix` over `oldest()`. That function walks from the lowest id and stops at the first entry that isn't older. A delete by `at` would leave a hole (CHK-M11-348). This module offers no such statement.
- Grants: as `bitscan_retention`, all three functions work (SELECT and DELETE on `audit_log`). As `bitscan_app`, `delete_through` is refused (`InsufficientPrivilege`): the app has no DELETE on `audit_log`.
- Nothing is logged. Error texts are fixed words.

## Deviations

None from plan §3. One addition: the autocommit guard on `delete_through`, the same pattern as M8's `reeval.lock_scan`.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check manager && ruff format --check manager`: all checks passed.
- `mypy --strict` on the new modules: no issues. The whole-tree run gives the 12 errors already on main, in untouched files (see `TASK-236-impl.md`).
- PostgreSQL tests are the tester's (`manager/tests/test_retention_repo_pg.py`, TP-M11-06, WSL).

## Builder checklist

Items 1–3, 5, 6, 13 and 16 don't apply (no client input, version, route, OpenAPI or audit target). 8 and 9: the chain lock is taken by `append_entry` in the service. 11 and 12: nothing is logged, and the error texts are fixed.
