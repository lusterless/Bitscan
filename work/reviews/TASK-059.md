# TASK-059 REVIEW: agent token check service

Reviewer: reviewer. Date: 2026-10-23. REQ-064, REQ-071. Spec: TS §3.2 L185–L191 (held enrolments, the token check, machine-id mismatch, rotation overlap and reuse, expiry), §6.1 L1069–L1070 (`pending_approval` on every route), §8.4 L1290 (mismatch and reuse alerts); #25, #26, #59 (statuses and order), #62 (overlap and reuse), #63 (missing or malformed header; pending re-enrolment mismatch). Rulings (`work/decisions.md`, 2026-10-23): after an unused rotation the previous token is accepted only while `now < last_rotation_at + 30 days`, then 401 `token_expired` (user, on my question). The as-built r1 is accepted: the cap check sits in the expiry position, and a missing `last_rotation_at` is refused. Plan: `work/plans/TASK-059.md` (outcome table). Inputs:
- `work/reports/TASK-059-impl.md`, including revision 1;
- `work/reports/TASK-059-test.md`: PASS for CHK-M3-120 to -127, `manager/tests/test_token_check.py`, and the r1 re-test PASS (CHK-M3-120-r1).

Files reviewed:
- `manager/bitscan_manager/services/enrolment/token_check.py` (about 175 lines);
- `manager/bitscan_manager/services/enrolment/__init__.py` (re-exports);
- the tester's test file.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent token check). This is the first one; the user's second approval is still needed.

## What was checked

- **Order (#59).** The checks run in this order:
  1. token shape (`is_agent_token(raw, AGENT)`), so `bse_`, `bsu_`, `bsk_` and malformed tokens get 401 `unauthorized` without a lookup;
  2. lookup by `token_hash`, then `prev_token_hash`, then `enrollment_request.new_token_hash`;
  3. `enrollment_rejected`;
  4. `token_revoked`;
  5. `token_expired`, including the r1 cap for a previous token after an unused rotation;
  6. `machine_id_mismatch`;
  7. overlap and reuse;
  8. `pending_approval`.

  The `{id}` match and the agent rate limit are TASK-063's. Every 401 sets `counted`; the 403 does not (REQ-064 (8)).
- **Outcome table.** Every row behaves as the plan says:
  - an unknown token gets 401;
  - a rejected request, or a rejected new agent, gets `enrollment_rejected` (#26);
  - revoked and decommissioned agents get `token_revoked` (REQ-064 (7));
  - the token is accepted one second before `expires_at` and refused at it (REQ-064 (5));
  - a missing, malformed or different header revokes the row (current and previous token) and raises one `machine_id_mismatch` alert;
  - for a pending re-enrolment token, a mismatch raises the alert only and the request stays pending (#63);
  - pending new and pending re-enrolment tokens get 403, while the old token keeps working (REQ-064 (3));
  - the previous token is accepted before the new token's first use, then for 10 minutes after it; a use after that revokes both and raises `token_reuse` (#62);
  - the first use of a new token marks the overlap atomically, and a failed check does not start it.
- **Revision 1.** While the rotated-in token is unused (`prev_token_expires_at IS NULL`), the previous token is accepted only while `now < last_rotation_at + 30 days`, otherwise 401 `token_expired`. A missing `last_rotation_at` is refused. This closes the gap I raised: `rotate()` overwrites the old token's own `expires_at`, so without the cap an old token could work past its expiry indefinitely. The ≤ 30-day residual is the user's accepted decision and is documented by the README (TASK-080). TASK-075 keeps `last_rotation_at` on the lost-response retry.
- **Security invariants.**
  - Only the SHA-256 hash is looked up, and the raw token is not kept.
  - Alert detail holds only `{"via": …}`, never a token, hash or header (tested with a canary).
  - Nothing is logged.
  - The check runs on the Clock's `now`.
- **Scope.** Two files, as the task row lists.
- **Tests (my run, Windows).** `test_token_check.py` passes within the 711-test run in the TASK-048 review. ruff and format are clean, and `mypy --strict` is clean (152 files). The fakes satisfy the `Protocol`s, so the test runs without PostgreSQL. Each ordering pair has its own test (revoked before expired and mismatch; expired before mismatch; mismatch before pending; rejected before revoked; and the request-path order). These turn red for CHK-M3-339 to -342 and -344.

## Findings

None.

## Carry-overs (for TASK-063, the dependency)

- Catch `AgentTokenRefused` **inside** the dependency's transaction, so the revoke and the alert written before the raise commit (CHK-M3-340). Then answer with its status and type.
- Feed every `counted` refusal to `record_failed_check(ip)`, answering 429 instead when the IP is over the limit, as M2 does. Feed refusals that carry an `agent_id` to the #65 (d) per-agent 401 window. A 403 is never counted.
- After acceptance, check `{id}` against `caller.agent_id` (403 `forbidden`, not counted), then `allow_agent`, then record the IP, calling `ip_last_seen` first.
- **TASK-075.** Use `caller.via` and `prev_token_expires_at` to tell a lost-response retry (previous token, new unused) from reuse (previous token after the new one was used, even inside the 10 minutes, #62).
