# TASK-077 IMPL report: agent tags and revoke

REQ: REQ-082. Spec: TS §6.2 L1084 and L1112–L1113, §3.2 L191, §5.2 L742–L746; #68, #71, #73 (c). It depends on TASK-051, 056 and 076, all approved or in test. **Two approvals** (revoke; TS §8.2).

## Files (3)

- `manager/bitscan_manager/services/agents/admin.py`: new, about 90 lines.
- `manager/bitscan_manager/api/user/agents.py`: adds `PUT /{id}/tags` and `POST /{id}/revoke`, about 75 lines.
- `manager/openapi.json`: re-exported and byte-stable. It adds:
  - `PUT /api/v1/agents/{id}/tags`, with `TagsBody` and `TagsItem`; answers 200, 400, 401, 403, 404, 429, 503;
  - `POST /api/v1/agents/{id}/revoke`; answers 204, 400, 401, 403, 404, 429, 503.

## Behaviour

**`PUT /api/v1/agents/{id}/tags`** uses `require_role("operator")`: operator or admin, session or API token. A viewer gets 403 `forbidden`.
- Body `TagsBody {tags: [StrictStr]}` (`extra="forbid"`, at most 32 items).
- The service checks the #68 rules **before anything is written**: 0–32 tags, all distinct, each 1–64 characters from `A–Z a–z 0–9 . _ : -`. The check is set membership, with no regex. Failure gives 400 `Invalid request: body.tags` and nothing changes.
- With the agent row locked, the whole set is replaced: DELETE plus INSERT in the same transaction (TASK-051 `replace_tags`), so it is all or nothing.
- One `agent.tags_set` entry is written (actor `user:<id>`, target `agent:<id>`, detail `{old, new}`).
- The answer is 200 `{tags}`, sorted. `[]` clears the set. An unknown or non-UUID id gets 404.

**`POST /api/v1/agents/{id}/revoke`** uses `require_totp_session()`: admin with a TOTP-verified session, sink gate. An admin `bsk_` or an unverified session gets 403 `totp_session_required`; during the sink outage it is 503 `audit_sink_unavailable`.
- With the agent row locked: if `token_revoked_at` is NULL, `revoke(agent_id, now)` sets it, and one `agent.revoke` entry is written. The token check reads the row's `token_revoked_at` for the current **and** the previous token (TASK-059), so both then get 401 `token_revoked`.
- If already revoked, `revoked_at` is kept and no second entry is written.
- The answer is 204 either way; an unknown agent gets 404.
- **The status is unchanged** (#73 (c)): the host goes `offline` and is decommissioned by age. A re-enrolment of that machine-id is held for approval (TASK-067, REQ-068 (4)).

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (101 files).
- `pytest -q`: 2182 passed. The 9 failures are the known TASK-074 test-file updates.
- Service probe (fakes):

  | Case | Result |
  | --- | --- |
  | set `["prod-web", "db"]` | `["db", "prod-web"]` and one entry `{old: [], new: [...]}` |
  | clear | `[]` and one entry |
  | a duplicate, 65 characters, empty, a space, `é`, 33 tags, `<script>` | each refused |
  | `a.b:c-d_e`, `X1` | accepted |
  | revoke twice | one revoke call, one `agent.revoke` entry |
  | unknown agent | not found |

- Through the API on PostgreSQL (TP-M3-31): **NOT RUN locally**; WSL.

## Deviations

None.
