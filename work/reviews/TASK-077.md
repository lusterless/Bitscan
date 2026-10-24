# TASK-077 REVIEW: agent tags and revoke

Reviewer: reviewer. Date: 2026-10-23. REQ-082. Spec: TS §6.2 L1084 (revoking agents is a sensitive action: TOTP-verified session, API tokens refused), L1112 (`PUT /agents/{id}/tags`, operator), L1113 (`POST /agents/{id}/revoke`, admin, TOTP session), §3.2 L191 (on 401 `token_revoked` the agent stops; the host must re-enrol), §5.3 L1051 (refused during the sink outage), §5.2 L742–L746 (`agent_tag`, `VARCHAR(64)`); #68 (0–32 distinct tags, 1–64 characters from `[A-Za-z0-9._:-]`; revoke answers 204), #71, #73 (c) (revoke does not change the status). Inputs:
- `work/reports/TASK-077-impl.md`;
- `work/reports/TASK-077-test.md` (PASS: `manager/tests/test_agents_admin_api_pg.py`; 8 of 8 plants red, CHK-M3-328, -330 and -372 included).

Files reviewed:
- `manager/bitscan_manager/services/agents/admin.py` (new, 90 lines);
- `manager/bitscan_manager/api/user/agents.py` (tags and revoke routes);
- `manager/openapi.json`;
- the tester-e tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; revoke). This is the first one; the user's second approval is still needed.

## What was checked

- **Authorisation (security invariants "Authorisation").**
  - `PUT /tags` uses `require_role("operator")`: operator or admin, session or API token. A viewer gets 403 (CHK-M3-372 red).
  - `POST /revoke` uses `require_totp_session()`: admin, TOTP-verified session, sink gate. An admin `bsk_` and an unverified session get 403 `totp_session_required`, and any session during the sink outage gets 503 (CHK-M3-328 and -330 red).
- **Tags (REQ-082 (1)).**
  - The body is `TagsBody` (`extra="forbid"`, at most 32 `StrictStr`).
  - `check_tags` runs **before anything is written**: 0–32, distinct, 1–64 characters, characters only from the #68 set, checked by set membership (no regex). A violation is 400 `Invalid request: body.tags` and nothing changes.
  - With the agent row locked, `replace_tags` deletes and inserts in one transaction, so it is all or nothing (TASK-051).
  - One `agent.tags_set` entry `{old, new}` is written. The answer is the sorted set, `[]` clears it, and an unknown id gets 404.
- **Revoke (REQ-082 (2)).**
  - With the row locked, `revoke` sets `token_revoked_at` only if it is NULL, and one `agent.revoke` entry is written. A second revoke keeps the first time, writes nothing and still answers 204.
  - The token check reads the row's `token_revoked_at` for both the current and the previous token (TASK-059), so both then get 401 `token_revoked`.
  - The status is unchanged (#73 (c)). The host goes offline, is decommissioned by age, and a re-enrolment of that machine-id is held (REQ-068 (4)).
- **OpenAPI (G6).** My re-export is byte-identical. `PUT /api/v1/agents/{id}/tags` lists 200, 400, 401, 403, 404, 429 and 503; `POST …/revoke` lists 204 and the same refusals; there is no 422.
- **Scope.** Three files, as the task row lists.
- **Tests (my run, Windows).** In the combined run of the five TASK-076 to 079 API files with `test_auth_dependencies.py`, `test_security_m2.py`, `test_openapi.py`, `test_alerts.py` and `test_thresholds.py`: 80 passed, 128 skipped (PostgreSQL; run in WSL by tester-e). ruff and format are clean, and `mypy --strict` is clean on the whole tree (209 files).

## Findings

None.

## Note

`{id}` on these user routes is parsed with `uuid.UUID`, which also accepts the 32-hex and `urn:uuid:` forms. The hyphen-only ruling (decisions 2026-10-23) covers agent routes, so this is consistent with the M2 user routes. A non-UUID id gets 404, as there is no such agent.
