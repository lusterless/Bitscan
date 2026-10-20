# TASK-021 REVIEW: audit chain verifier, including checkpoints

Reviewer: reviewer. Date: 2026-10-20. REQ-031. Spec: TS §5.3 L1051 ("so the chain can still be verified from that point"); `.claude/rules/manager/audit-and-alerts.md`; decisions #38 (hash) and #39 (checkpoint rule). Plan: `work/plans/TASK-020.md` "Verifier". Inputs: `work/reports/TASK-021-impl.md` (step 1, revision 1, step 2), `work/reports/TASK-021-test.md` (PASS; WSL 547 passed, 0 skipped; mutations: link check removed 7 unit + 2 pg red, checkpoint id rule removed 1 red, REPEATABLE READ removed 1 red), `tests/m1/report.md` CHK-M1-220 to -230.

Files:
- `manager/bitscan_manager/services/audit/verify.py`
- `repositories/audit_log.py`: `AuditError`, `_utc_text`, `ChainRow`, `_READ_CHAIN`, `iter_entries`
- `services/audit/__init__.py`: re-export
- `services/audit/chain.py`: `AuditError` removed

Verdict: APPROVED

One approval is enough here (decisions 2026-10-20).

## What was checked

- **Rule (`verify.py:73-117`):**
  - the hash is recomputed (#38) before the link is checked;
  - links go through `prev_hash`, never id arithmetic, so rolled-back id gaps pass;
  - only the oldest row may link to genesis, or to a well-formed `audit.checkpoint` of the same chain. The checkpoint is valid only if:
    - it is reached before the first failure (so its own hash and link are verified);
    - its own id is above `last_deleted_id`;
    - `last_deleted_id` is below the oldest id;
    - `last_deleted_row_hash` equals the oldest row's `prev_hash` (#39);
  - `last_deleted_id` must be a real `int` (not bool, string or float), and malformed JSON does not vouch;
  - an empty log gives ok with 0 checked.
- **Revision 1 (my pre-review should-fix, fixed, `verify.py:113-116`):** a definite failure now wins over the "oldest not linked" result. Before the fix, in the normal post-retention shape, a tamper anywhere before the vouching checkpoint was reported as the oldest row with "broken link", against REQ-031 (2). My repro (checkpoint for 4, ids 1 to 4 deleted, actor of 8 changed) now gives (8, `row_hash mismatch`) and is pinned (CHK-M1-229). `ok` is False in both cases, so nothing is weakened.
- **Step 2 read (`audit_log.py:103-127`):**
  - it refuses unless the connection is IDLE;
  - the first statement inside `conn.transaction()` is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`;
  - a server-side cursor runs fixed SQL with no parameters, in batches of 1000, so a 3-year log is never held in memory at once;
  - the `at` text comes from the same `_utc_text` as `allocate`, so the hash input is byte-identical;
  - `verify_chain` (`verify.py:120-126`) wraps the generator in `closing()`, so stopping early rolls back the read and leaves the connection idle (CHK-M1-230);
  - the snapshot is tested by asserting `repeatable read` / read-only mid-walk, with a concurrent append not seen (CHK-M1-224).
- **Layering:** `AuditError` now lives in `repositories/audit_log.py` and is re-exported from `services.audit` as the same class. The repositories import nothing from services, and services depend on repositories, as `api → services → repositories` requires.
- **Security invariants:**
  - read-only; no logging or output;
  - no route or CLI command, because none is in the spec;
  - tampering tests run as `bitscan_owner` through `bitscan_migrate`, and checkpoint deletes as `bitscan_retention`, never as superuser.
- **Gates (re-run by me, Windows):** ruff, format and `mypy --strict` are clean on 46 files. pytest gives 366 passed and 164 skipped (pg), with 98.15 % coverage.
- **Scope:** about 108 + 70 lines across 4 files, matching the plan's split into step 1 and step 2.

## Findings

1. **note, accepted (TS §8.1).** An attacker who can write `audit_log` with correct hashes can rebuild a whole valid chain, because no secret is involved (#38). Two more cases are also undetectable here:
   - deleting entries from the tail;
   - a retention-role holder deleting the oldest entries and appending a matching checkpoint, which is the designed checkpoint operation.

   The external sink (M2) is the control for all three; do not add signing (owner decision).
2. **nit.** A single server-side cursor statement is already one snapshot under READ COMMITTED. The explicit REPEATABLE READ is kept because the plan requires it, and the test asserts it directly. No change.
