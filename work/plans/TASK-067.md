# TASK-067 plan: enrolment tokens, enrolment, approval and rejection

Covers TASK-052 (enrolment repository), TASK-066 (enrolment tokens), TASK-067 (`POST /agent/enroll`) and TASK-070 (requests, approve, reject). REQs: REQ-063, REQ-067 to REQ-069, REQ-077. Owner: impl-manager. **Two approvals for TASK-066, TASK-067 and TASK-070.** Tests: TP-M3-06, TP-M3-20, TP-M3-21, TP-M3-24; mutation rows CHK-M3-322, 324 to 329, 332 to 337, 365, 370, 371.

**Blocked on #59** (refusal statuses), **#60** (enrol body), **#61** (per-hour alert), **#64** (re-enrolment details), **#26** (rejected re-enrolment), **#68** (route bodies), **#71** (audit and alert names), **#36** (first inventory job).

## Spec quotes

- TS §3.2 L181: "An admin creates an **enrolment token** (`bse_` prefix) in the UI with `max_uses` (1 = single use, up to 10,000), an expiry (default 24 h), optional `allowed_cidrs`, and `auto_approve` (default off). … Creating a token with `auto_approve` or more than 100 uses alerts."
- L183: "not expired or revoked, source IP inside `allowed_cidrs` if set, and `uses < max_uses` (incremented atomically with `UPDATE … WHERE uses < max_uses RETURNING`). It returns `agent_id` (UUID), a new **agent token** … and the token's `issued_at` and `expires_at` … The manager stores only the token's SHA-256 hash."
- L185–L188: held unless `auto_approve` and a new machine-id; "A re-enrolment onto an existing machine-id is always held, even with `auto_approve`; on approval it re-links to the existing `agent` row (history kept) and revokes the old token"; held new: `agent` row `awaiting_approval` with the token hash; held re-enrolment: existing `agent_id` returned, hash in `enrollment_request`; rejected: "the request is kept for the record; a new agent row is set to `decommissioned` (never deleted); the agent receives 401 `enrollment_rejected` and stops."
- TS §6.2 L1084: approving enrolment requests and managing enrolment tokens are sensitive actions (TOTP session, never API tokens). L1114–L1116 route table.

## Atomic use of a `bse_` token (TASK-052)

```sql
UPDATE enrollment_token SET uses = uses + 1
WHERE token_hash = %(hash)s AND uses < max_uses AND revoked_at IS NULL AND expires_at > %(now)s
  AND (allowed_cidrs IS NULL OR %(ip)s::inet <<= ANY (allowed_cidrs))
RETURNING token_id, auto_approve
```

One statement, so concurrent enrolments cannot pass `max_uses` (the row lock serialises the increments; CHK-M3-332). Zero rows → one refusal for every cause (#59: 401 `unauthorized`, counted as a failed check). The refusal does not say which condition failed.

## Enrolment (TASK-067), one transaction after the atomic use

1. `SELECT … FROM agent WHERE machine_id = %s FOR UPDATE`.
2. **No row, `auto_approve`:** insert `agent` (`status = 'enrolled'`, hostname, version, token hash, `token_issued_at = now`, `token_expires_at = now + agent_token_ttl_days`, `last_seen_ip`); audit `agent.enrol`; `queue_first_inventory` (#36). Response `status: "enrolled"`.
3. **No row, no `auto_approve`:** insert `agent` (`status = 'awaiting_approval'`, same token columns); insert `enrollment_request` (`kind = 'new'`, `new_token_hash` = the same hash, `token_expires_at`, `source_ip`, `os_pretty_name`, version, hostname, machine-id, token id); audit. Response `awaiting_approval`.
4. **Row exists (any status, any token):** insert `enrollment_request` (`kind = 'reenrol'`, `agent_id` = existing); the `agent` row is not changed (CHK-M3-337). Response with the existing `agent_id`, `awaiting_approval`.
5. **Race:** two first enrolments of one new machine-id: the second insert hits `agent.machine_id` UNIQUE; the transaction is retried once and then takes branch 4. The `uses` increment of the failed attempt is kept (it was a real enrolment attempt; the retry does not increment again).
6. The response token is generated before step 1 and returned once; only its hash is written (REQ-063). The per-token #61 window is fed after commit.

Rate limit: `limits.allow_enrol(ip)` before anything else (10 per minute per IP, every attempt counts, REQ-065 (2)).

## Decisions (TASK-070), one transaction with the request row locked

| Request | Approve | Reject |
| --- | --- | --- |
| `new`, agent `awaiting_approval` | agent `enrolled`; request `approved`, `decided_by`, `decided_at`; audit; #36 first job | request `rejected`; agent `decommissioned` and `token_revoked_at = now`; audit |
| `reenrol` | agent: `token_hash` = request hash, `token_issued_at` = `requested_at`, `token_expires_at` = request's, `token_revoked_at`, `prev_token_hash`, `prev_token_expires_at`, `last_rotation_at` cleared, `hostname` and `agent_version` from the request, status `enrolled` (#64); request `approved`; `reenrolment_approved` alert; #36 first job | request `rejected`; agent row unchanged (#26) |
| already decided | 409 `conflict` | 409 `conflict` |
| request token already expired | 409 `conflict` (#64 (e)) | allowed |

Two concurrent decisions: the `FOR UPDATE` on the request and the `decision IS NULL` re-check give one success and one 409 (REQ-069 (5)). The agent row is locked after the request row in every path (one lock order).

## Matches for the list (TASK-052, TASK-070)

`matches` = agents other than the request's own whose `machine_id` equals the request's, or whose `hostname` equals it (exact match; `ix_agent_hostname_trgm` is not needed for equality). For a `reenrol` request the existing agent is the request's own and is shown as `agent_id`, not in `matches`; a second, different agent with the same hostname is listed. This is how a cloned image shows up (TS §3.2 L192).

## Enrolment tokens (TASK-066)

Create (body #68) → `bse_` generated (TASK-050), hash stored, `created_by` = admin id; one `enrollment_token.create` audit entry; if `auto_approve` or `max_uses > 100`, one `enrolment_token_risky` alert (detail flags both) instead of a second plain entry (one entry per event, decisions 2026-10-21 TASK-042 ruling). Delete → `revoked_at = now` if not already set (204 either way), audit. All routes use `require_totp_session()` (admin, sink gate).

## Edge cases

- The source IP is the TCP peer (#55 (d)); IPv4-mapped IPv6 peers (`::ffff:10.0.0.1`) are converted to IPv4 before the CIDR check, so a `10.0.0.0/8` entry still matches.
- `allowed_cidrs` entries are validated as network addresses at create time (PostgreSQL `CIDR` refuses host bits, so the API checks first and answers 400 rather than letting the database raise).
- No route lets a `bse_` token do anything but enrol, and enrolment never accepts a `bsa_` (CHK-M3-322).
- Enrolment writes no `os_info`: `os_id` and `os_version_id` are validated and dropped (#60); the first inventory fills `os_info`.
