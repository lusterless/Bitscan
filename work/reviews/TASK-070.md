# TASK-070 REVIEW: enrolment requests (list, approve, reject)

Reviewer: reviewer. Date: 2026-10-23. REQ-069, REQ-077. Spec: TS §3.2 L185–L188 (held enrolments; approval re-links a re-enrolment, keeps history and revokes the old token; rejection keeps the request and decommissions a new agent row; the agent gets 401 `enrollment_rejected`), L192 (cloned images show up as matches), §6.2 L1084 (approving enrolments is a sensitive action), L1114–L1115 (list: admin; approve and reject: admin, TOTP session), §8.4 L1290 (re-enrolment approved alerts); #26, #36, #64 (a)–(f), #68, #71. Ruling (`work/decisions.md`, 2026-10-23): a `new` request decided after its re-enrolment twin was approved is rejected without touching the agent, or approved by re-linking. Plan: `work/plans/TASK-067.md` ("Decisions", "Matches"). Inputs:
- `work/reports/TASK-070-impl.md`, including revision 1;
- `work/reports/TASK-070-test.md` (PASS on r1: CHK-M3-220 to -226; 23 tests in WSL; 15 of 15 plants red, CHK-M3-326, -327, -328, -370 and -371 included).

Files reviewed:
- `manager/bitscan_manager/services/enrolment/requests.py` (new, about 175 lines);
- `manager/bitscan_manager/api/user/enrolment.py` (request routes added; the token routes are unchanged);
- `manager/openapi.json`;
- tester-d's test file.

Verdict: APPROVED

**Two approvals required** (TS §8.2; enrolment approval). This is the first one; the user's second approval is still needed.

## What was checked

- **Authorisation (security invariants "Authorisation").**
  - `GET /enrollment-requests` uses `require_role("admin")`: an admin session or `bsk_` is allowed, an operator is refused.
  - Approve and reject use `require_totp_session()` (admin, TOTP-verified session, sink gate). An admin `bsk_`, an unverified session, an operator (CHK-M3-371) and any session during the sink outage are refused (CHK-M3-326 to -328 red).
- **List (REQ-069 (1)).**
  - `?state=pending|decided|all`, keyset pages, with the cursor scoped to its state.
  - Items have the #68 fields plus `matches`: every other agent sharing the hostname or machine-id, so cloned images and shared hostnames are both shown.
  - `new_token_hash` appears in no response model and nowhere in `manager/openapi.json` (REQ-063 (5)).
- **Decision (one transaction, request locked first, then the agent).**
  - A decided request, or a concurrent second decision (`FOR UPDATE` plus the `decision IS NULL` re-check), answers 409 and rolls back. Approval with an expired request token answers 409 (#64 (e)). An unknown id answers 404.
  - **New, agent still `awaiting_approval`:**
    - approve sets `enrolled`, writes one `enrollment_request.approve` entry and queues the first inventory job (#36);
    - reject sets `decommissioned`, revokes the token, keeps the row and writes one reject entry (REQ-069 (4); CHK-M3-370 red).
  - **Re-enrolment, or a `new` request whose agent was already enrolled through its twin (r1 ruling):**
    - approve re-links with the request's hash, `requested_at` and `token_expires_at`, hostname and version, clears `token_revoked_at`, `prev_*` and `last_rotation_at`, and sets `enrolled` (#64 (a)–(c)). The old token is now unknown (401), while id, tags, `os_info` and packages are kept (REQ-069 (3)). The one entry is the `reenrolment_approved` alert, and the first job is queued.
    - reject records the rejection only. The agent and its current token are untouched (#26, r1 (a)).
  - The `first` test uses only the agent's status, so a pending agent whose token was revoked (machine-id mismatch, or a TASK-077 revoke, which leaves the status unchanged, #73 (c)) is approved by status change only, and its token stays revoked. An approval cannot silently undo a security revoke.
  - Audit detail is `{kind, agent_id}`, never a token or hash.
- **Locks.** Request row first, then agent row, in every path. Enrolment locks the token and agent rows and only inserts requests, so no lock cycle exists between enrol and approve.
- **OpenAPI (G6).** The export is byte-stable. It adds the three operations with problem+json refusals, plus `RequestItem` and `MatchItem`.
- **Scope.** Three files, as the task row lists. The size is over the guide, as the plan expected. Splitting the list from the decisions would not simplify review.
- **Tests (my run, Windows).** `test_enrolment_requests_api_pg.py`, `test_enrolment_tokens_api_pg.py`, `test_auth_dependencies.py`, `test_security_m2.py` and `test_openapi.py`: 12 passed, 128 skipped (PostgreSQL; run in WSL by tester-d). ruff and format are clean, and `mypy --strict` is clean on the whole tree (200 files, in the TASK-072 run).

## Findings

None.

## Carry-overs

- **TASK-077.** `POST /agents/{id}/revoke` revokes the token without changing the status (#73 (c)). A held re-enrolment of that machine-id stays held, and its approval re-links as above (REQ-082 (2)).
- **TASK-080 (README).** Document the approval flow: list, approve or reject with a TOTP session, what a rejected re-enrolment does (#26), and cloned images in `matches`.
