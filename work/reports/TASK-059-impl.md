# TASK-059 IMPL report: agent token check service

REQ: REQ-064, REQ-071. Spec: TS §3.2 L185–L191, §6.1 L1069–L1070, §8.4 L1290; #25, #26, #59, #62, #63. Plan: `work/plans/TASK-059.md` (outcome table). Depends on TASK-050, 051, 052 and 056, all approved. **Two approvals** (TS §8.2).

## Files (2)

- `manager/bitscan_manager/services/enrolment/token_check.py`: new, 167 lines.
- `manager/bitscan_manager/services/enrolment/__init__.py`: new, re-exports.

## API

- `check_agent_token(agents, requests, audit, *, raw, machine_id_header, now) -> AgentCaller`.
- On refusal it raises `AgentTokenRefused(status, type, agent_id)`, with `counted = (status == 401)`.
  - `agent_id` is set whenever the token resolved to an agent or a request. That is for the per-agent 401 window, #65 (d).
  - **The caller must catch it inside its transaction**, so the revoke and alert written before the raise are committed. TASK-063's dependency does that.
- `AgentCaller(agent_id, via: "current" | "previous", agent: AgentRow)`.
- Protocols: `AgentLookup`, satisfied by `AgentRepo`; `RequestLookup`, satisfied by `EnrolmentRepo`; and `Alerter`, satisfied by `services.users.TxAudit`. `mypy --strict` confirms all three statically.
- `OVERLAP = 10 min` (#62).

## Order and outcomes (plan table, #59)

1. **Shape:** `raw` is None, or not a well-formed `bsa_` token (`is_agent_token`; so `bse_`, `bsu_` and `bsk_` too) → 401 `unauthorized`.
2. **Lookup:** by the SHA-256 hash, in order: `agent.token_hash` (current), `agent.prev_token_hash` (previous), then `enrollment_request.new_token_hash`. Nothing found → 401 `unauthorized`.
3. **Request path** (a held re-enrolment's new token; row 2, 5, 6b, 11):
   - `rejected` → 401 `enrollment_rejected` (#26). The old row and its token are untouched.
   - `approved` → 401 `unauthorized`. On approval the hash was copied into `agent.token_hash`, so reaching this branch means a later token replaced it.
   - expired → 401 `token_expired`.
   - header mismatch → 401 `machine_id_mismatch`, plus the alert only (#63 for pending re-enrolment tokens). The request stays pending.
   - otherwise → 403 `pending_approval`.
4. **Agent found:**
   - Row 3: current, `decommissioned`, and its own `kind = 'new'` request rejected → 401 `enrollment_rejected`.
   - Row 4: `token_revoked_at` set → 401 `token_revoked`. This covers revoke, decommission (REQ-064 (7)), mismatch, reuse, and the previous token of a revoked row.
   - Row 5: current and `now >= token_expires_at` → 401 `token_expired`. One second before is accepted (REQ-064 (5)).
   - Row 6: the `X-Bitscan-Machine-Id` header is missing, malformed (not exactly 32 lower-case hex characters) or different (#63) → the row is revoked, which ends the current and the previous token, and one `machine_id_mismatch` alert is raised. Answer: 401 `machine_id_mismatch`.
   - Previous token (rows 7–9, #62):
     - `prev_token_expires_at` is NULL (new token unused; the lost-response case) → accepted.
     - `now < prev_token_expires_at` (overlap) → accepted.
     - `now >= prev_token_expires_at` → both tokens revoked, one `token_reuse` alert, 401 `token_revoked`.
   - Row 10: current and `awaiting_approval` → 403 `pending_approval`, not counted.
   - Row 12: current with `prev_token_hash` set and `prev_token_expires_at` NULL (first use after a rotation) → `mark_new_token_used(now + 10 min)`, which is atomic, then accepted.
   - Row 13: otherwise accepted.

**Alerts:** actor `agent:<id>`, target `agent:<id>`, action `agent.machine_id_mismatch` or `agent.token_reuse` (#71), detail `{"via": "current" | "previous" | "request"}`. They never hold a token, hash or header value.

**Time and secrets:** every time rule uses the `now` passed in, from the Clock. Nothing is logged, and no raw token is kept after hashing.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (151 files).
- `pytest -q`: 1926 passed, 704 skipped, 0 failed.
- Scratch probe with fake repositories over the plan's outcome table (22 cases): each gave its status, type and counted flag, and wrote exactly the stated revoke, mark and alert:
  - unknown, missing and `bse_` tokens;
  - rejected request; rejected new; revoked;
  - expired one second before and at `expires_at`;
  - mismatch, missing header and malformed header;
  - pending new; pending re-enrolment; pending re-enrolment with a mismatch;
  - replaced approved request;
  - previous token unused, in the overlap, and after it;
  - first use after a rotation; overlap running; decommissioned; normal.

## For the tester

- Counting failed checks and the per-IP and per-agent limits are TASK-063's job (the dependency). This service only sets `counted`.
- The rotate route (TASK-075) uses `via` to tell a lost-response retry from reuse.

## Deviations

None.

## Revision 1 (user ruling 2026-10-23: cap on an unused rotation)

- **Why:** `rotate()` overwrites `token_expires_at`, and `prev_token_expires_at` stays NULL until the new token's first use. So in the lost-response state the old token had no expiry check at all.
- **Rule:** while the rotated-in token is unused, the previous token is accepted only while `now < last_rotation_at + 30 days`. After that it gets 401 `token_expired`, with the same body and the same failed-check counting as any expiry.
- **Change:** `bm/services/enrolment/token_check.py`.
  - New constant `UNUSED_ROTATION_CAP = timedelta(days=30)`, also exported from the package `__init__`.
  - The check: `via == "previous"` and `prev_token_expires_at IS NULL`, and either `last_rotation_at` is NULL or `now >= last_rotation_at + 30 d`, gives 401 `token_expired`.
  - It sits in the **expiry position of the #59 order**: after `token_revoked` and before `machine_id_mismatch`. So an old token past the cap that also has a wrong header is answered `token_expired`, with no revoke and no alert, exactly as a current token past its `expires_at` is.
  - It fails closed when `last_rotation_at` is NULL. In real data `prev_token_hash` and `last_rotation_at` are always set together by `rotate()` and cleared together by `relink()`.
  - Once the new token has been used, the #62 overlap and reuse rule decides as before, and the cap does not apply.
- **Carry-overs:**
  - TASK-075: the lost-response retry (`replace_unused_token`) must keep `last_rotation_at` unchanged, which it already does, so a retry cannot extend the cap.
  - TASK-080: the README states the residual. An old token can stay usable for at most 30 days after a rotation whose new token is never used.
- **Gates (Windows):** ruff, ruff format and `mypy --strict` pass (152 files).
- **Scratch probe:**

  | Old token, new token unused | Result |
  | --- | --- |
  | rotated 30 d − 1 s ago | accepted |
  | rotated exactly 30 d ago | 401 `token_expired`, counted, nothing revoked |
  | the same with a wrong header | 401 `token_expired` |
  | `last_rotation_at` NULL | 401 `token_expired` |

  An old token inside the overlap, rotated 40 d ago, is accepted, because the overlap rule applies there.
- **Your `tests/test_token_check.py`:** the four revision-1 tests pass (cap boundary, retry not moving the cap, the cap not touching the new token or a used rotation). Two older tests now fail only because their fixture agent has `prev_token_hash` set and `last_rotation_at` left at the default None, a state the repository never produces: `test_previous_token_before_first_use_is_accepted` and `test_mismatch_on_the_previous_token_revokes_the_row`. With a realistic `last_rotation_at`, for example inside the 30 days, both behave as before.
