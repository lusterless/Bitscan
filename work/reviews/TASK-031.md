# TASK-031 REVIEW: `app_user` and `user_token` repositories

Reviewer: reviewer. Date: 2026-10-21. REQ-044, REQ-048, REQ-051, REQ-052. Spec: TS §5.2 L951–L979 (`user_role`, `app_user`, `user_token`, grants), TS §6.2 L1076–L1091, TS §5.3 L1050; #56 (d); decisions 2026-10-21 ("M2 test-plan answers"). Inputs: `work/reports/TASK-031-impl.md`; `work/reports/TASK-031-test.md` (PASS, CHK-M2-090 to -096 in `tests/m2/report.md`, `manager/tests/test_user_repos_pg.py` with 31 tests run on PostgreSQL in WSL; 12 of 12 mutations red).

Files reviewed: `manager/bitscan_manager/repositories/users.py`, `manager/bitscan_manager/repositories/user_tokens.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Parameterised SQL only.** Every statement is a fixed string or a `psycopg.sql` composition of fixed parts, with `%s` binds. Ruff S608 is on and passes. Nothing is built from input.
- **Token storage (security invariants).** Only `token_hash` reaches the module. Lookup is `WHERE t.token_hash = %s` on the UNIQUE index (`find_by_hash`). The query is keyed by the SHA-256 of the presented token, so no constant-time comparison is needed in Python. `TokenOwner` and `ApiTokenRow` carry no hash. `totp_enrolled` is derived as `totp_secret_enc IS NOT NULL`, so the ciphertext never leaves `app_user` on the token path. `UserRow.password_hash` and `totp_secret_enc` are `repr=False`.
- **Grants (TS §5.2).** Only SELECT, INSERT and UPDATE on both tables are used, plus `FOR UPDATE` on `app_user`, where `bitscan_app` has UPDATE. There is no DELETE. Tokens end through `revoked_at`, and users are only disabled (TS §5.3 L1050). The tester ran every function as `bitscan_app`.
- **Single use of a TOTP step (REQ-042 (2), (3)).** `claim_totp_step` is one conditional UPDATE (`totp_last_step IS NULL OR totp_last_step < step`). Under READ COMMITTED the second writer waits for the row lock, re-checks against the committed value and gets 0 rows. The tests prove this deterministically (B is shown blocked, then loses), with a 10-way race giving exactly one `True`, and with a rolled-back claim that does not use up the step.
- **Back-off (REQ-048 (3), (4)).** `record_failure` is one UPDATE that gives min(2^(n−1), 900) s from the `now` passed in, not from the database clock. The counter is capped at 1000, and since `smallint + 1` is computed as integer, it is also safe from 32767. Under 10 concurrent failures the result is exactly 1..10 and a final count of 10. All of this is tested.
- **Other.** `insert_user` uses `ON CONFLICT (username) DO NOTHING RETURNING`, so a duplicate does not abort the transaction (tested). `revoke_own_api` returns `False` the same way for an unknown id, another user's token, a session and an already revoked token (REQ-051 (3)). `lock_active_admins` locks in a fixed `user_id` order. The time values come from the caller's clock.
- **Gates (my run, Windows).** ruff and format are clean, and `mypy --strict` is clean. The pg tests skip on Windows. I relied on the tester's WSL run for them, because only the tester runs WSL (decisions 2026-10-21). I read the concurrency tests: each one would fail if the conditional WHERE or the single-statement update were removed.
- **Scope.** 2 files, 247 non-blank lines (about 215 of code), slightly over the ~200 guide. Accepted: the extra lines are the setters that TASK-038 to TASK-042 need, and those tasks' file lists do not include the repositories.

## Findings

None block approval.

1. **note for TASK-042 (lock order; carry-over accepted by the lead, decisions 2026-10-21).** The TASK-042 plan has `change_role` call `get_for_update(target)` first and `lock_active_admins()` second. Suppose two admins A and B demote each other at the same time. T1 holds A's row and waits for B; T2 holds B's row and waits for A. PostgreSQL aborts one of them with `deadlock_detected` (40P01). The last-admin rule still holds, but the loser gets a 500 unless that error is handled. Fix in TASK-042: call `lock_active_admins()` before `get_for_update(target)` everywhere (one global order: active admins by id, then the target), or map 40P01 to a retry. The TASK-042 review will check this.
2. **nit.** `user_tokens.py:88`: the `RuntimeError` for an INSERT … RETURNING that returns no row cannot happen. It works only as mypy narrowing; `assert row is not None` would say so.
3. **note, no change.** `touch` (`user_tokens.py:94`) skips the write when `last_used_at` is less than 60 s old, as the TASK-037 plan says. The idle limit can therefore end up to 60 s early. That is stricter than TS §6.2 (8 h idle), never looser, and it fits the 1-minute margin in REQ-044 (2).
4. **note for TASK-042 (decisions 2026-10-21 (4)).** The repository matches usernames exactly and does not validate them. The new ASCII-only rule (letters A–Z, a–z, plus digits and `._@-`, 1–64 characters) belongs to the users service in TASK-042, and the CLI in TASK-046 reuses it. The TASK-042 review will check that a non-ASCII letter such as `é` is refused at creation.

## For the user (second approval)

Nothing needs a decision. The security-relevant points are the single-statement TOTP claim and back-off updates, lookup by hash only, no DELETE, and secrets hidden from `repr`. All were checked as above.
