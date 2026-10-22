# TASK-028 REVIEW: token and password primitives

Reviewer: reviewer. Date: 2026-10-21. REQ-040 (1), (2), REQ-041, plus the parser part of REQ-044 (1) and the dummy-verify part of REQ-048 (2). Spec: TS §6.2 L1083 (256 random bits, base64url, prefix, only SHA-256 stored), L1087 (Argon2id, at least 12 characters); TS §2.3; TS §5.2 (`user_token.token_hash`, `app_user.password_hash`); TS §8.6 L1334 (token redaction pattern); #56 (a) to (c). Plan: `work/plans/TASK-041.md`, section TASK-028. Inputs: `work/reports/TASK-028-impl.md` (revision 1), `work/reports/TASK-028-test.md` (PASS in round 2, CHK-M2-060 to -068, 16 of 16 mutations red).

Files reviewed: `manager/bitscan_manager/auth/tokens.py`, `manager/bitscan_manager/auth/passwords.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Token format (REQ-040 (1)).** A token is the prefix plus base64url of `secrets.token_bytes(32)` with no padding: 43 characters, 47 in total (#56 (a)). The tester confirmed that 10,000 tokens of each kind are distinct and fully match the TS §8.6 pattern with RE2.
- **Storage (REQ-040 (2)).** `token_hash` (`tokens.py:37`) is the lowercase SHA-256 hex of the whole string, prefix included. Only this module defines user-token prefixes.
- **Prefix parsing (REQ-044 (1), parser part).** `parse_user_token` (`:40`) accepts only `bsu_` and `bsk_` followed by exactly 43 base64url characters. It refuses `bsa_`, `bse_`, unknown prefixes, padding and non-ASCII, without a regex.
- **Passwords (REQ-041).** Argon2id with the RFC 9106 low-memory profile (m = 64 MiB, t = 3, p = 4), recorded in the PHC string. The salt is random. Length is 12 to 1,024 code points with no normalisation (#56 (b)). `verify_password` never raises; it returns False for a mismatch or a malformed hash. Each rejection message names the rule, never the value.
- **Exception chains (tester round 1, fixed).** `PasswordRejected` is now raised outside the `except` block. The old `from None` only hid the context: `__context__` still held the `UnicodeEncodeError`, whose `.object` was the whole password. The fix is right, and the round-1 test catches the old form.
- **Timing (REQ-048 (2)).** `dummy_verify` runs one real verification against a cached hash made with the same parameters. The tester showed it really verifies, with a counting wrapper.
- **Security invariants.** No logging, no stdlib `re`, randomness only from `secrets`. No token or password is ever in a message, `repr` or chain.
- **Gates (my run).** ruff, format and `mypy --strict` are clean, and `test_tokens.py` plus `test_passwords.py` pass.
- **Scope.** 2 files, about 80 lines.

## Findings

None block approval.

1. **note for the user (second approval): sign-in memory. Placed in TASK-038 by the lead (decisions 2026-10-21).** Each verification allocates 64 MiB. Sign-in needs no token, so a burst of concurrent sign-ins from many IPs could reach the 40-thread FastAPI pool and about 2.5 GiB. The per-IP limit of 10 per minute does not bound that across many IPs. TASK-038 adds a semaphore of 4 around every Argon2id verification, real or dummy; waiters queue and are not refused, and the parameters stay as you approved them. I will check it in the TASK-038 review.
2. **note.** `token_hash` encodes as UTF-8, so it would also hash a non-ASCII string. The callers hash only strings that `parse_user_token` accepted (ASCII only), or tokens from `new_token`. TASK-037 must parse before hashing, and TASK-037's review will check that order.

## For the user (second approval)

Please look at finding 1: memory under sign-in load, handled in TASK-038. Nothing else needs a decision.
