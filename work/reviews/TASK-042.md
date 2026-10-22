# TASK-042 REVIEW: users service

Reviewer: reviewer. Date: 2026-10-22. REQ-052, REQ-041, REQ-055. Spec: TS §6.2 L1085–L1091, L1125; TS §5.3 L1050; TS §8.4 L1290. Decisions: #7, #50, #53, and #56 (d) with the ASCII-only answer; 2026-10-21 "Lead rulings on TASK-042" (one task; any raise of a role writes one `role_granted`; `admin_created` only from the CLI); 2026-10-22 (user confirmed #53 (d) as built). Plan: `work/plans/TASK-042.md`. Inputs: `work/reports/TASK-042-impl.md`, `work/reports/TASK-042-test.md` (PASS; TP-M2-20 unit tests plus the pg race and rollback).

Files reviewed: `manager/bitscan_manager/services/users/accounts.py`, `manager/bitscan_manager/services/users/__init__.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Lock order (my TASK-031 carry-over).** `change_role` and `disable_user` call `lock_active_admins()` before `get_for_update(target)` (`accounts.py:209-210`, `:238-239`). With one global order, the mutual-demotion race cannot deadlock. Under READ COMMITTED the second locker re-evaluates the `NOT disabled` / `role = 'admin'` filter and sees one admin left, so the last-admin guard refuses it. The tester showed on PostgreSQL that two admins demoting each other leave one active admin.
- **Rules (REQ-052).**
  - `create_user` allows viewer or operator only (#53 (f)). Passwords go through `hash_password`, so the REQ-041 length rules apply. A duplicate username becomes `UserRuleError(duplicate)` with no change.
  - Usernames are 1–64 ASCII letters, digits and `._@-`, case-sensitive (#56 (d)). `é`, Cyrillic `а` and full-width letters are refused (my TASK-031 note).
  - Promotion to admin needs TOTP (`needs_totp`). Lowering or disabling the last active admin gives `last_admin`, self included (#53 (h)).
  - Any role change revokes sessions (#53 (c)), and any lowering also revokes API tokens (#53 (d)). The tester's point: lowering a non-admin also revokes their API tokens. That follows #53 (d) ("any lower role") and TS §6.2 L1085 ("demoting a user … revokes every API token"), and the user confirmed it on 2026-10-22.
  - Disabling revokes both kinds and never deletes the row (TS §5.3 L1050). Re-enabling leaves revoked tokens revoked (#53 (g)).
  - A TOTP reset clears both TOTP columns and revokes sessions; resetting your own is refused, and the CLI is allowed (`actor_id=None`).
  - "Revoke a user's tokens" covers both kinds (#53 (e)).
- **Audit and alerts (REQ-052 (8), REQ-055).** Each change writes exactly one entry through `TxAudit`, in the caller's transaction, so a rollback leaves neither the change nor the entry; the tester covered this on pg. Alerts are `user_created`, `role_granted` (every raise, a promotion to admin included), `admin_created` (CLI only) and `totp_reset`, which matches the lead's ruling with no double alert. No `detail` holds a password, hash or seed.
- **Layering.** `UserStore`, `TokenStore` and `AuditSink` are protocols, so the unit tests need no PostgreSQL. `accounts.py` is at 100 % coverage.
- **Gates (my run).** ruff, format and `mypy --strict` are clean. `test_users_service.py` passes, and G5 is at 97.10 %.
- **Scope.** 2 files, about 240 lines after formatting, over the ~200 guide. Accepted, per the lead's ruling: create, change and disable share the admin lock and the last-admin guard, and splitting them would duplicate that logic. Each function is short.

## Findings

None block approval.

1. **nit.** `reset_totp` (`:259-275`) alerts and revokes sessions even when the user has no TOTP enrolled. The alert then reports a reset that changed nothing. Either make it a no-op without an alert when `totp_secret_enc` is already NULL, or keep the behaviour and say so in the TASK-043 response. The spec does not decide this.
2. **nit.** `create_user` hashes the password (about 70 ms of Argon2id) before the duplicate check. This costs time only on a 409, on an admin-only route. Fine.
3. **note for TASK-043.** `UserRow` holds `password_hash` and `totp_secret_enc` (hidden from `repr`). The `/users` response models must list their fields explicitly (`user_id, username, role, disabled, totp_enrolled, created_at`, #47 (c)) and never serialise `UserRow` directly (REQ-052 (9)). The TASK-043 review will check this.
4. **note for TASK-043.** `UserRuleError(not_found)` must give the same 404 whether the id does not exist or is out of range. `Rule` values must not leak into `detail` beyond the fixed text #48 sets for `conflict`.

## For the user (second approval)

The one behaviour I asked you to confirm is settled: on 2026-10-22 you confirmed #53 (d) as built. Lowering any user's role, operator to viewer included, revokes all of that user's sessions and API tokens. Nothing else needs a decision.
