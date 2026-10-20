# TASK-020 REVIEW: audit chain append

Reviewer: reviewer. Date: 2026-10-20. REQ-030. Spec: TS §5.2 L981-990 (`audit_log`), TS §5.3 L1051 (advisory xact lock, `prev_hash`/`row_hash`), TS §8.1; `.claude/rules/manager/audit-and-alerts.md` "Audit chain", `database.md` "Locks"; decision #38. Plan: `work/plans/TASK-020.md`. Inputs: `work/reports/TASK-020-impl.md`, `work/reports/TASK-020-test.md` (PASS; WSL 523 passed, 0 skipped; mutations lock removed 3 red, SHOW check removed 2 red), `tests/m1/report.md` CHK-M1-200 to -209 and -228.

Files reviewed as they are now, after the TASK-021 step 2 edit: `manager/bitscan_manager/services/audit/chain.py`, `services/audit/__init__.py`, `repositories/__init__.py` (empty), `repositories/audit_log.py` (`AuditError`, `AT_TEXT`, `PgAuditRepo`). `_utc_text`, `ChainRow` and `iter_entries` in the same file belong to TASK-021 and are reviewed there.

Verdict: APPROVED

One approval is enough here (not on the TS §8.2 two-approval list; decisions 2026-10-20).

## What was checked

- **Hash (#38), `chain.py:53-72`.** SHA-256, lowercase hex, over the UTF-8 bytes of `json.dumps([prev_hash, audit_id, actor, action, target, detail_text, at_text], separators=(",", ":"), ensure_ascii=False)`. `detail_text` is hashed as a JSON string, never re-parsed. Genesis is `"0" * 64` (`chain.py:12`). The tester's reference was written independently and has two hand-computed known-answer vectors (CHK-M1-200).
- **Append flow, `chain.py:75-102`:**
  - `detail` is serialised with `allow_nan=False` before any database call;
  - then lock, head, allocate, insert, all inside the caller's transaction, with no commit;
  - the id, the `at` text and the canonical jsonb text all come from the server under the lock (`audit_log.py` `allocate`), so id order is chain order and a stored row re-hashes byte for byte (CHK-M1-203).
- **Lock and isolation, `audit_log.py` `_check_transaction` / `lock_chain`:**
  - `pg_advisory_xact_lock(hashtext('audit_log'))` exactly as TS §5.3 says;
  - autocommit is refused, and so is any isolation other than READ COMMITTED, at both the driver level and through `SHOW transaction_isolation`, so a role or session default is caught too;
  - each refusal comes before the lock and before any write (CHK-M1-207);
  - the mutations show the tests catch both a missing lock and a missing SHOW check (CHK-M1-228).
- **Security invariants:**
  - all SQL is fixed text with bound `%s`, or `psycopg.sql` composition of fixed parts; ruff S608 is not suppressed;
  - no UPDATE or DELETE path, and grants are untouched: app and retention append with their TS §5.2 grants only (CHK-M1-206);
  - no logging, no output, no network (CHK-M1-202, -209);
  - no signing, no secret and no sink (the sink is M2), which matches the owner decisions.
- **Layering.** The pre-review nit (the repository imported `AuditError` from services) is fixed. `AuditError` is now defined in `repositories/audit_log.py` and re-exported from `services.audit` as the same class. The repositories import nothing from services.
- **Gates (re-run by me, Windows):**
  - ruff check and format clean, `mypy --strict` clean on 46 files;
  - `pytest --cov=bitscan_manager/services --cov-fail-under=85`: 366 passed, 164 skipped (pg), 98.15 %.
- **Scope:** 4 files, about 150 lines, within the task's limits.

## Findings

1. **nit. A branch that cannot run.** `repositories/audit_log.py:70-71`: `allocate` raises `AuditError` when `row is None`, which cannot happen for a `SELECT` without `FROM`. Keep it only as the mypy narrowing, or use `assert row is not None`.
2. **note, no change.** `at` is the start time of the writer's transaction (`now()`, the same as the column default). A writer that waited on the lock can therefore carry an `at` earlier than the entry before it. Chain order is `audit_id`, which the verifier uses, so this is consistent with TS §5.2. M2's sink consumers should not assume `at` is monotonic.
