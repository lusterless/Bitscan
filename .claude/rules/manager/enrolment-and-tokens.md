---
paths:
  - "manager/**/services/enrolment/**"
  - "manager/**/api/agent/**"
  - "manager/**/services/agents/**"
---

# Enrolment, agent tokens, rotation and the agent fleet

Spec: TS §3.2 (enrolment, approval, token check, rotation), §2.3 (token table), §6.5 (wire contract). Tables: `agent`, `agent_ip_seen`, `enrollment_token`, `enrollment_request` (TS §5.2).

## Enrolment tokens (`bse_`)

- Only an admin creates them, from a TOTP session: `max_uses` 1–10,000 (default 1 = single use), a required expiry (default 24 h), optional `allowed_cidrs` (NULL = any source), `auto_approve` default off. A token may be shared by many installs, for example in an org install script; a multi-use token should have `max_uses` = expected host count and `allowed_cidrs` set (UI hint, not a hard rule).
- Creating a token with `auto_approve` or more than 100 uses alerts. More than `enrolment_alert_per_hour` enrolments on one token alerts.

## `POST /agent/enroll`

- Enrolment checks: not expired or revoked, source IP in `allowed_cidrs` if set, and the atomic `max_uses` increment (`UPDATE … WHERE uses < max_uses RETURNING`). Return `agent_id`, the `bsa_` token (shown once), `issued_at` and `expires_at`, and `status` (`enrolled` or `awaiting_approval`). Each agent gets its own `bsa_` token; store only its SHA-256 hash.
- Hold the enrolment in `enrollment_request` for approval unless the token has `auto_approve` and the machine-id is new. A re-enrolment onto an existing machine-id is always held, even with `auto_approve`.
  - Held new enrolment: create the `agent` row with `status = 'awaiting_approval'` and `token_hash` = the new token's hash.
  - Held re-enrolment: return the existing `agent_id`; keep the new token hash in `enrollment_request.new_token_hash` (usable only after approval); the token check looks there to answer 403 `pending_approval`.
  - Approve (admin, TOTP session): a re-enrolment re-links to the existing `agent` row, keeping history, and revokes the old token; approving a re-enrolment alerts.
  - Reject: keep the request; set a new agent row to `decommissioned` (never delete it); the agent gets 401 `enrollment_rejected`.
- The approval API returns hostname, source IP, OS, and any agent with the same hostname or machine-id (cloned images show up this way).

## Agent token check (every agent route)

- Missing, unknown, revoked or expired token: 401 (revoked and expired tokens use `token_revoked` and `token_expired`). Awaiting approval: 403 `pending_approval` on every route.
- Valid token with a different `X-Bitscan-Machine-Id`: 401 `machine_id_mismatch`, revoke the token and alert.
- Heartbeat: alert when `clock` and `server_time` differ by more than 5 minutes; store `runner_helpers`, and audit-log and alert on any change.

## Lifetime and rotation (TS §3.2 step 7)

- Lifetime is `agent_token_ttl_days` (default 365, range 60–730); a change applies only to tokens issued or rotated after it.
- Rotation (`POST /agent/{id}/token/rotate`):
  - only inside the window that starts at `issued_at + max(TTL − 30 d, TTL ÷ 2)`, and at most once per 24 h, counting only rotations whose new token was then used; a rotation outside the window alerts;
  - the old token stays valid until the new one is first used, plus 10 minutes (`prev_token_hash`, `prev_token_expires_at`);
  - if the old token retries because the response was lost, issue a fresh new token and discard the unused one;
  - after the new token is used, using the old token revokes both and alerts;
  - a rotation from a source IP not in `agent_ip_seen` for the last 7 days alerts.
- The rotation window ends at `expires_at`: after it every call, including rotate, gets 401 `token_expired` (TS §3.2 steps 6 and 8), and the host must re-enrol.
- Agent fleet (`services/agents/`): `POST /agents/{id}/revoke` (admin, TOTP session) revokes the token and forces re-enrolment; `PUT /agents/{id}/tags` is operator. Status (`online`/`stale`/`offline`) and decommission are set by `offline_sweep` (TS §3.3; see `.claude/rules/manager/jobs-and-scans.md`).

Tests (TS §8.3): Integration (enrolment checks, concurrent `max_uses`, approval and rejection, rotation window and reuse with clock control), Security (tokens on the wrong route group, API tokens refused for approve/reject/revoke/enrolment tokens), End-to-end (enrol → approve enrolment → heartbeat).
