# TASK-075 REVIEW: agent token rotation (`POST /api/v1/agent/{id}/token/rotate`)

Reviewer: reviewer. Date: 2026-10-23. REQ-071. Spec: TS §6.1 L1067 (new agent token only inside the rotation window), §3.2 L190–L191 (window `issued_at + max(TTL − 30 d, TTL ÷ 2)`; at most once per 24 h counting only rotations whose new token was used; the overlap; the lost-response retry; reuse revokes both and alerts; a rotation from an IP not seen for 7 days alerts; after `expires_at` every call gets 401 `token_expired`), §6.5 L1188 (Rotate response), §8.4 L1290; #60 (no body or `{}`), #62. Rulings (`work/decisions.md`, 2026-10-23):
- #62 confirmed;
- the TASK-059 r1 30-day cap on the old token after an unused rotation;
- "TASK-075 rotation rulings": the 24 h check comes before the window check, and the lost-response retry applies the new-IP rule (revision 1).

Plan: `work/plans/TASK-059.md` ("Rotation"). Inputs:
- `work/reports/TASK-075-impl.md`, including revision 1;
- `work/reports/TASK-075-test.md` (PASS on r1: `manager/tests/test_rotation_api_pg.py` with clock control; 23 of 23 plants red, CHK-M3-343 and -344 included).

Files reviewed:
- `manager/bitscan_manager/services/enrolment/rotation.py` (new, about 160 lines);
- `manager/bitscan_manager/api/agent/rotate.py` (new, about 90 lines);
- `manager/bitscan_manager/api/agent/__init__.py` (router include, `RotateRequest` documented);
- `manager/openapi.json`;
- the tester-e tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent token rotation). This is the first one; the user's second approval is still needed.

## What was checked

- **Route.**
  - `current_agent` runs first: token check (401 `token_expired` after `expires_at`, and after the 30-day cap for a previous token, REQ-071 (7)), `{id}`, the 30-per-minute limit, IP recording, and `ip_last_seen` read before this call's `record_ip`.
  - The body is read by the route only after that, under the 1 MiB `BodyLimit`. It accepts an empty body or `{}` and refuses `null`, `[]`, `{"a": 1}`, a string or non-JSON with 400 (#60, fixture `rotate/request_invalid_null`).
  - The service runs in the threadpool, in one transaction. `RotationRefused` is caught inside it, so a revoke or an alert commits before the answer.
  - The answer is exactly `agent_token`, `issued_at`, `expires_at`. The new token is returned once, and only its SHA-256 is stored.
- **Service (agent row locked).**
  - Revoked or missing row: 401 `token_revoked`.
  - **Previous token after the new token was used, even inside the 10-minute overlap:** reuse. It revokes both (`token_revoked_at`), writes one `token_reuse` alert and answers 401 (#62; CHK-M3-344 red).
  - **Previous token while the new one is unused:** the lost-response retry. `replace_unused_token` issues a fresh token, so the unused one stops working, and `last_rotation_at` is kept, so neither the 24 h rule nor the 30-day cap moves. It writes one `agent.token_rotate {retry: true}` entry and applies the new-IP rule (r1 (2)).
  - **Current token, in order (r1 (1)):**
    - a used rotation within 24 h answers 429 `rate_limited` with `Retry-After` to the end of the 24 h and no window alert (REQ-071 (5)). An unused one does not count.
    - then `now < window_opens(issued_at, expires_at)`, with TTL being the presented token's own lifetime, answers 403 `forbidden` plus one `rotation_outside_window` alert (CHK-M3-343 red). TTL 365 opens on day 335 and TTL 60 on day 30 (REQ-071 (1), (2)).
    - otherwise `rotate()` moves the old hash to `prev_token_hash` and sets `last_rotation_at = now`, writes one `agent.token_rotate {retry: false}` entry, and gives the new token the **current** `agent_token_ttl_days` (REQ-071 (8)).
  - **New-IP alert:** on a successful rotation or retry, if the source IP was never seen for this agent or last seen more than 7 days ago, one `rotation_new_ip` alert is written. 6 days writes nothing and 8 days alerts (REQ-071 (6)).
  - Every entry has actor and target `agent:<id>`, and none holds a token or hash.
- **OpenAPI (G6).**
  - My re-export is byte-identical.
  - The operation documents an optional `RotateRequest` body and a 200 `RotateResponse` that requires exactly its three keys, with `additionalProperties: false`. Refusals 400, 401, 403, 429 and 503 are problem+json, with no 422.
  - **All six TS §6.1 agent operations are now in the document**, and nothing else is under `/api/v1/agent/` (REQ-060 (1), REQ-062 (1)).
- **Security invariants.** The `bsa_` dependency is the only way in. Tokens are stored only as hashes and never written to an entry or a log.
- **Tests (my run, Windows).** `test_rotation_api_pg.py`, `test_token_check.py`, `test_contract_agent.py`, `test_contract_fixtures.py`, `test_agent_auth_pg.py` and `test_openapi.py`: 721 passed, 70 skipped (PostgreSQL; run in WSL by tester-e). ruff and format are clean, and `mypy --strict` is clean on the whole tree (207 files).

## Findings

None block approval.

1. **nit (tester-e note 1; recommend a lead decision)**, `manager/bitscan_manager/services/enrolment/rotation.py:103-139`. The caller's `via` is decided by the token check in an earlier transaction. If two rotations with the same current token arrive together, the second waits for the row lock, then sees the first's new `token_issued_at`, whose window opens about 335 days later. So it answers 403 **and writes a false-positive `rotation_outside_window` alert**. Only a buggy or duplicated client does this, but it adds noise to a security alert.

   Optional fix: after locking, check that the presented token is still the row's current token (`row.token_hash == caller.agent.token_hash`). If it is not, refuse without the window alert: either 401 as an unknown token, or handle it as the previous-token case under the same rules.
2. **note (tester-e note 2), no action.** The new-IP alert fires only on a successful rotation or retry. A refused attempt is not a rotation in the TS §3.2 L190 sense, so this is the right reading.

## Carry-overs

- **TASK-080 (README).** Document rotation:
  - the window;
  - the 24 h rule;
  - the 10-minute overlap and reuse detection;
  - the lost-response retry;
  - the accepted ≤ 30-day residual for an old token after an unused rotation (user ruling, TASK-059 r1).
- **M4 (Go agent).** Rotate only from inside the window. Retry a lost response with the old token. Switch to the new token at once. Never send rotations concurrently.

## Revision 2 (2026-10-23, user ruling "TASK-075 revision 2 ordered", from finding 1)

Verdict for revision 2: APPROVED. **Two approvals required**; the user's second approval is still needed for r2.

Inputs:
- `work/reports/TASK-075-impl.md` "Revision 2";
- `work/reports/TASK-075-test.md` "Revision 2" (PASS: 168 passed in WSL, 0 skipped; 28 of 28 plants red, including "no post-lock re-check", the "unused" condition dropped, and the new-IP rule skipped on the redirect).

- **Finding 1 is resolved.** After the row lock, `rotate_token` checks whether the presented "current" token has just become the previous one with the new token still unused. The test is: the locked row's `token_hash` differs from the caller's, its `prev_token_hash` equals the caller's hash, and `prev_token_expires_at` is null.
  - If so, the call takes the lost-response retry path: a fresh token through `replace_unused_token` (whose `WHERE` re-guards this state), a `{"retry": true}` entry, no window alert and no 24 h check, `last_rotation_at` kept, and the 7-day new-IP rule still applied.
  - Only stored SHA-256 hashes are compared.
  - Two concurrent rotations therefore give one rotation plus retries (tested with the row held `FOR UPDATE` until both wait: 4 × 200, one rotation, three retries), and no false `rotation_outside_window` alert.
- **The boundary the lead accepted.** If the concurrent rotation's new token was **used** before the waiting call got the lock, the call stays on the current-token path and the 24 h rule answers 429, with no alert and no revoke. **I agree it is the conservative answer.** The waiting call's token passed the check while it was still current, so treating it as reuse would revoke a working agent's new token over a race of its own duplicated request. The agent keeps its new token, and real reuse later (an old-token call after the new one was used) still revokes both and alerts (#62).
- **Gates (my run, Windows).** `test_rotation_api_pg.py`, `test_token_check.py`, `test_alerts.py` and `test_contract_agent.py`: 663 passed, 49 skipped (PostgreSQL; WSL by tester-f). ruff and format are clean, `mypy --strict` is clean (210 files), and the OpenAPI export is byte-identical (no document change).
