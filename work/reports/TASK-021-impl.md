# TASK-021 IMPL report: audit chain verifier (steps 1 and 2)

REQ: REQ-031. Spec: TS §5.3 L1051 (checkpoint before deleting entries, so the chain verifies from that point). Decisions #38 (hash input), #39 (checkpoint rule). Plan: `work/plans/TASK-020.md` "Verifier (TASK-021)". The lead split the task: **step 1 (this report)** is the pure verifier. **Step 2**, after the TASK-020 TEST PASS, adds the read function to `repositories/audit_log.py`. In the same edit, `AuditError` moves into `repositories/audit_log.py` (reviewer TASK-020 pre-review (b)) and `services/audit` re-exports it, keeping the name.

## Step 1 file (1)

- `manager/bitscan_manager/services/audit/verify.py` (108 lines, pure, no database import): `StoredEntry`, `VerifyResult(ok, checked, first_bad_id, reason)`, `verify_rows(rows)`, the constants `CHECKPOINT_ACTION = "audit.checkpoint"`, `HASH_MISMATCH = "row_hash mismatch"`, `BROKEN_LINK = "broken link"`. It reuses `compute_row_hash` and `GENESIS_PREV_HASH` from TASK-020. `chain.py` is unchanged.

## Rule

Rows arrive in ascending `audit_id` order. Gaps are allowed: a rolled-back append uses up a sequence value. Links are checked through `prev_hash`, never by id arithmetic. For each row:
1. Recompute `row_hash` (#38) from the stored fields. A mismatch stops the walk: `(audit_id, "row_hash mismatch")`.
2. From the second row on, `prev_hash` must equal the previous row's `row_hash`; otherwise stop with `(audit_id, "broken link")`.
3. **The oldest row** (the first one) is linked if:
   - its `prev_hash` is the genesis value (64 zeros); or
   - an `audit.checkpoint` row **of this same chain**, walked before the first failure, has `detail` = `{"last_deleted_id": <int>, "last_deleted_row_hash": "<hex>"}`, with `last_deleted_id < oldest.audit_id` and `last_deleted_row_hash == oldest.prev_hash` (#39).
4. (Revision 1) A failure from steps 1–2 is reported as is. Only if the walk completes without one and the oldest row is not linked is the result `(oldest.audit_id, "broken link")`.
5. An empty log gives `ok=True, checked=0`.

`checked` counts the rows walked, including the failing one.

## Checkpoint hardening (forged checkpoints)

- **Only the oldest row** can be validated by a checkpoint. Every later row must link to its predecessor's `row_hash`. A forged checkpoint therefore cannot bridge a gap in the middle: the row after a mid-chain deletion still fails as a `broken link`.
- **The checkpoint must be part of the verified chain.** A checkpoint only counts once its own `row_hash` has been recomputed and its own link checked, that is, if it lies before the first failure. A tampered or unlinked checkpoint (for example `detail` edited to point elsewhere) fails its own hash or link, so it cannot validate the oldest row.
- **Well-formed only:** `detail` must parse as a JSON object. `last_deleted_id` must be a real `int` (not `bool`, string or float), and `last_deleted_row_hash` a string. The checkpoint's own `audit_id` must be greater than `last_deleted_id` (it is written after the rows it records), and `last_deleted_id` must be below the oldest row's id.
- **Remaining risk (accepted, TS §8.1):** whoever can write `audit_log` with correct hashes can rebuild a whole valid chain. Every value is computable without a secret, by design (#38). The protections against that are the least-privilege grants (the app cannot UPDATE or DELETE) and the external sink (M2). The verifier detects edits, deletions and forged checkpoints. It cannot detect a complete, consistent rewrite by an owner-level attacker.

## Checks run (Windows, step 1)

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check`, `mypy --strict` on `manager/bitscan_manager` (21 files) | pass |
| Offline scenarios with `compute_row_hash`-built rows | empty → ok/0. Genesis chain with an id gap → ok. Tampered actor → mismatch at that id. Deleted middle row → broken link at the next id. Oldest linked by a later valid checkpoint → ok. No checkpoint → broken link at the oldest. Checkpoint `last_deleted_id` ≥ oldest id, wrong hash, `"2"` as a string, the checkpoint row itself tampered, a forged checkpoint after a mid-chain gap → each a broken link |
| `pytest --cov=bitscan_manager/services --cov-fail-under=85` | **red (34.65 %) until TP-M1-15 lands**: `verify.py` has 66 statements and no tests yet. `chain.py` and `__init__.py` are at 100 % from TP-M1-14 |

## Revision 1 (reviewer pre-review, should-fix, REQ-031 (2), (3))

Rule 4 above is reversed. **A definite failure now takes priority:** if the walk stops at a `row_hash mismatch` or a `broken link`, that row is reported. `(oldest.audit_id, "broken link")` is returned only when the walk finishes without a failure and nothing linked the oldest row (no genesis, no valid checkpoint). Reason: the walk stops at the first failure, before any later checkpoint that might link the oldest row. Once retention runs (M11), that checkpoint sits near the head, so the old rule blamed every tamper in the body on the oldest row. `ok` is `False` in both cases; nothing is weakened.

- Reviewer repro (10 genesis rows, checkpoint for id 4, ids 1–4 deleted, actor of id 8 changed): now `(False, checked=4, first_bad_id=8, "row_hash mismatch")`. It was `(5, "broken link")`.
- **Test impact:** `test_changed_checkpoint_hash_fails`, first half (checkpoint `detail` edited, hash not redone). The verifier now reports the checkpoint's own id (11) as `row_hash mismatch`, where the test expects the oldest id (5). The second half (forger redoes the hash) still reports the oldest row as `broken link`. `test_forged_checkpoint_after_a_deleted_prefix_and_tail_tamper` can now assert `first_bad_id == remaining[2].audit_id` and `reason == "row_hash mismatch"`.
- Checks: `ruff check`, `ruff format --check`, `mypy --strict` on `manager/bitscan_manager` pass. `tests/test_audit_verify.py` + `test_audit_chain.py`: 60 passed, 1 failed (the assertion above, expected to change).

## Step 2: the PostgreSQL read (after the TASK-020 TEST PASS)

### Files (4, about 70 changed lines)

- `manager/bitscan_manager/repositories/audit_log.py`:
  - **`AuditError` is defined here now** (reviewer TASK-020 pre-review (b)). The repository no longer imports anything from `services`.
  - `_utc_text(expr)` builds `to_char(<expr> AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')` with `psycopg.sql`. `AT_TEXT = _utc_text(now())` is unchanged in what it renders. The read uses `_utc_text(Identifier("at"))`, so append and verify share one server-side text form (#38).
  - `ChainRow`: the tuple `(audit_id, actor, action, target, detail_text, at_text, prev_hash, row_hash)`.
  - `iter_entries(conn)`: a generator yielding `ChainRow`s, in this order:
    1. It refuses with `AuditError("audit chain read needs a connection with no open transaction")` unless `conn.info.transaction_status` is `IDLE`. Otherwise the snapshot would already be fixed by the caller's transaction.
    2. Inside `conn.transaction()` (autocommit or not), the first statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`.
    3. A server-side cursor `audit_chain_read` (`itersize` 1000) runs `SELECT audit_id, actor, action, target, detail::text, to_char("at" AT TIME ZONE 'UTC', …), prev_hash, row_hash FROM audit_log ORDER BY audit_id`. The query is fixed text and has no parameters, so a 3-year log is never loaded into memory at once.
    4. The transaction ends when the generator is exhausted or closed. Closing it early rolls back the read-only transaction.
- `manager/bitscan_manager/services/audit/verify.py`: `verify_chain(conn) -> VerifyResult` runs `with closing(iter_entries(conn))` and feeds `StoredEntry(*row)` into `verify_rows`. It stops at the first failure and closes the read. `verify_rows` is unchanged and still pure.
- `manager/bitscan_manager/services/audit/chain.py`: the `AuditError` class is removed; nothing in `chain.py` raised it.
- `manager/bitscan_manager/services/audit/__init__.py`: re-exports `AuditError` from `repositories.audit_log`. `from bitscan_manager.services.audit import AuditError` still works and is the same class.

The connection's own settings (`isolation_level`, `read_only`) are not changed. The verifier only reads: no logging, no output, no writes. There is no CLI or API route for it; none is in the spec.

### Checks run (Windows, step 2)

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on `manager/bitscan_manager` (21 files) | pass |
| `grep services manager/bitscan_manager/repositories/` | nothing (layering fixed) |
| Rendered SQL (`as_string(None)`) | the read and `AT_TEXT` share one `to_char` pattern, applied to `"at"` and to `now()` |
| `services.audit.AuditError is repositories.audit_log.AuditError` | True |
| `pytest --cov=bitscan_manager/services --cov-fail-under=85` | 366 passed, 164 skipped; coverage 98.15 % (`verify_chain`, 2 lines, is covered only by pg tests) |
| Real PostgreSQL | **NOT RUN by me**; TP-M1-15 pg part (tester) |

### For the tester (pg, TP-M1-15)

- `from bitscan_manager.services.audit.verify import verify_chain`. Call it on a connection with no open transaction (fresh, or after commit or rollback), in autocommit or not. A connection with an open transaction raises `AuditError` before any read.
- CHK-M1-224: hold `verify_chain` mid-walk (for example by wrapping `iter_entries` and appending from a second connection between rows, then continuing). The appended row is not seen, and the result stays `ok`.
- Tamper cases as `bitscan_owner`: `verify_chain` should give the same results as `verify_rows` over your own read.
- After `verify_chain` returns, including on an early failure, the connection is `IDLE` again, with no open transaction.

## For the tester

- Unit-test `verify_rows` with rows built by `compute_row_hash`. Every branch is reachable without PostgreSQL, and the coverage gate needs these tests.
- `StoredEntry` field order is `audit_id, actor, action, target, detail_text, at_text, prev_hash, row_hash`.
- Step 2 is built: see "Step 2" above (`verify_chain`, `iter_entries`, `AuditError` moved).
