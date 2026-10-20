# TASK-020 IMPL report: audit chain append

REQ: REQ-030. Spec: TS §5.2 L981–L990 (`audit_log`), TS §5.3 L1051 (`pg_advisory_xact_lock(hashtext('audit_log'))`, `prev_hash` / `row_hash`), TS §8.1; `.claude/rules/manager/audit-and-alerts.md` "Audit chain"; `database.md` "Locks". Decision #38 (hash input, genesis). Plan: `work/plans/TASK-020.md`.

## Files (4)

- `manager/bitscan_manager/services/audit/chain.py` (pure; no psycopg import, no logging): `GENESIS_PREV_HASH = "0" * 64`, `AuditError`, `HashInput`, `AppendedEntry`, `AuditRepo` (Protocol, exactly the plan's four methods), `compute_row_hash(prev_hash, entry)`, `append_entry(repo, *, actor, action, target=None, detail=None)`.
- `manager/bitscan_manager/services/audit/__init__.py`: re-exports those names.
- `manager/bitscan_manager/repositories/__init__.py`: empty package file.
- `manager/bitscan_manager/repositories/audit_log.py`: `PgAuditRepo(conn)`, the `AuditRepo` over one psycopg connection, and `AT_TEXT`, the server-side UTC text form that the TASK-021 verifier will reuse.

## Hash (#38)

`row_hash = sha256(json.dumps([prev_hash, audit_id, actor, action, target, detail_text, at_text], separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()`. That is lowercase hex.
- `detail_text` is PostgreSQL's own `detail::text`, hashed as a JSON **string** (never re-parsed), or JSON `null`.
- `at_text` is `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC.
- The genesis `prev_hash` is `"0" * 64`.

## Append flow (inside the caller's transaction; the caller commits)

1. `detail` (a Mapping) → `json.dumps(dict(detail), ensure_ascii=False, allow_nan=False)`. This is pure and runs before any database call, so a non-serialisable value or NaN raises before the lock is taken.
2. `lock_chain()` checks the transaction first and **refuses before any statement that changes anything**:
   - `conn.autocommit` → `AuditError("audit append needs a transaction, not autocommit")`;
   - `conn.isolation_level` set to anything but READ COMMITTED → `AuditError("audit append needs READ COMMITTED isolation")`;
   - then `SHOW transaction_isolation` must be `read committed`, which also catches a server or role default of REPEATABLE READ or SERIALIZABLE, with the same error.

   Then it runs `SELECT pg_advisory_xact_lock(hashtext('audit_log'))`.
3. `head_row_hash()`: `SELECT row_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1`; none → genesis.
4. `allocate(detail_json)`: one statement composed with `psycopg.sql`: `SELECT nextval('audit_log_audit_id_seq'), to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), CAST(%s AS jsonb)::text`. The id is allocated under the lock, so id order is chain order. `at` is the server's `now()`, read back, not the Python clock. `detail_text` is PostgreSQL's canonical jsonb text.
5. `compute_row_hash`, then `insert(...)`: `INSERT INTO audit_log (audit_id, actor, action, target, detail, at, prev_hash, row_hash) VALUES (%s, %s, %s, %s, CAST(%s AS jsonb), CAST(%s AS timestamptz), %s, %s)`, all bound.
6. Returns `AppendedEntry(audit_id, prev_hash, row_hash, at_text)` for M2's sink.

No UPDATE or DELETE, no logging, no network, and nothing printed. The function hashes only what it is given; callers own what goes into `detail`. The sink, disk queue and alerts are M2.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check` / `ruff format --check` / `mypy --strict` on `manager/bitscan_manager` (20 files) | pass (S608 green; the SQL is literals or `psycopg.sql` composition) |
| Fake-repo flow | call order `lock → head → alloc → insert`; first `prev_hash` is genesis; entries link; nothing written to stdout or stderr |
| Known answer | `row_hash` equals an independent SHA-256 of the hand-written compact array (including non-ASCII `naïve` and a JSON-string `detail_text`); 64 lowercase hex |
| NULL vs empty | `target` NULL ≠ `""`; `detail` NULL ≠ `"{}"` |
| NaN in detail | `ValueError` before any repo call |
| `pytest --cov=bitscan_manager/services --cov-fail-under=85` | **red until TP-M1-14 lands**: `services/audit` has 35 statements and no tests yet (0 %). 293 passed, 137 skipped |
| Real PostgreSQL (8 × 25 concurrent `bitscan_app` writers, `pg_locks` wait, rollback relink, `bitscan_retention` append, column-limit rejection, autocommit / RR / SERIALIZABLE refusal) | **NOT RUN by me** (WSL root runs are blocked for me); the tester's harness covers it (TP-M1-14) |

## For the tester

- **Coverage gate:** TP-M1-14's unit tests (with a fake `AuditRepo`) must cover `services/audit/chain.py` and `__init__.py` for the 85 % gate to go green again. Every branch is reachable without PostgreSQL.
- `PgAuditRepo` does not commit. Commit or roll back in the test's transaction.
- Refusals raise `AuditError` (from `bitscan_manager.services.audit`) before the lock or the insert.
- A `psycopg.Connection` opened with `isolation_level=IsolationLevel.REPEATABLE_READ`, or a role with `default_transaction_isolation = 'repeatable read'`, is refused. The second case is caught through `SHOW transaction_isolation`.
- Recompute a stored row's hash with `detail::text` and the same `to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`.
