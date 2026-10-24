# TASK-052 IMPL report: enrolment repository

REQ: REQ-067, REQ-068, REQ-069. Spec: TS §5.2 L748–L777 (`enrollment_token`, `enrollment_request`) and L994–L1013 (grants), §3.2 L181–L192; #26, #59, #64, #68. Plan: `work/plans/TASK-067.md`.

## Files (1)

- `manager/bitscan_manager/repositories/enrolment.py`: new, 252 lines (217 code). Over the 180 estimate; a ruling was asked of the lead.

## Rows

- `EnrolmentTokenRow`: `token_id`, `max_uses`, `uses`, `auto_approve`, `allowed_cidrs` (as text, or None), `expires_at`, `revoked_at`, `created_by`, `created_at`. It has **no `token_hash`** field, so list and read can never show it (REQ-067 (3)).
- `UsedToken(token_id, auto_approve)`.
- `RequestRow`: every `enrollment_request` column, with `source_ip` through `host()` and `new_token_hash` left out of `repr`.
- `MatchRow(agent_id, hostname, machine_id, status)`.

## Functions (`EnrolmentRepo(conn)`, inside the caller's transaction; only hashes, never tokens)

**enrollment_token:**
- `insert_token(*, token_hash, max_uses, auto_approve, allowed_cidrs, expires_at, created_by, now) -> token_id`. `allowed_cidrs` is cast to `cidr[]`; None means any source. The service validates the CIDRs first (plan, edge cases).
- `use_token(token_hash, source_ip, now) -> UsedToken | None`: **one** statement does the whole check and the increment:

  ```sql
  UPDATE enrollment_token SET uses = uses + 1
  WHERE token_hash = %s AND uses < max_uses AND revoked_at IS NULL AND expires_at > %s
    AND (allowed_cidrs IS NULL OR CAST(%s AS inet) <<= ANY (allowed_cidrs))
  RETURNING token_id, auto_approve
  ```

  The row lock serialises concurrent increments, so 20 concurrent uses of a 5-use token succeed exactly 5 times. Expired, revoked, exhausted, out-of-CIDR and unknown tokens all give None without incrementing, and none of them says which condition failed (#59). An IPv4 address against an IPv6 CIDR (or the reverse) is simply no match. Converting IPv4-mapped IPv6 peers to IPv4 is the service's job (plan).
- `revoke_token(token_id, now) -> bool`: `revoked_at = COALESCE(revoked_at, now)`. The row is kept. The result is True if the token exists, so a second DELETE still answers 204.
- `get_token(token_id)`, `token_page(limit, after_id)`: keyset by `token_id`.

**enrollment_request:**
- `insert_request(*, kind, agent_id, token_id, hostname, machine_id, os_pretty_name, agent_version, new_token_hash, token_expires_at, source_ip, now) -> request_id`.
- `find_by_new_token_hash(hash)`: the column is UNIQUE.
- `get_request_for_update(request_id)`: `FOR UPDATE`, so two concurrent decisions serialise.
- `decide(request_id, decision, decided_by, now) -> bool`: it re-checks `decision IS NULL`, so exactly one decision succeeds. With the lock, the second caller sees the first decision and gets False, which becomes a 409.
- `request_page(state, limit, after_id)`: `state` is `pending` (`decision IS NULL`), `decided` or `all` (#68); keyset by `request_id`.
- `rejected_new_for_agent(agent_id) -> bool`: the agent's own `kind = 'new'` request was rejected. This gives the token check's 401 `enrollment_rejected` for a decommissioned new agent (plan TASK-059 row 3, #26).
- `matches(request) -> list[MatchRow]`: every **other** agent whose `machine_id` or `hostname` (exact match) equals the request's, in `(hostname, agent_id)` order. A cloned image therefore shows up (TS §3.2 L192). For a re-enrolment, the request's own agent is excluded (plan).

**Grants:** both tables have only UPDATE and INSERT here. No DELETE: decided requests are removed by retention (M11).

## Local gates (Windows)

- `ruff check manager` (S608, and no `assert`; a failed `RETURNING` raises `RuntimeError`) and `ruff format --check manager`: pass. `mypy --strict`: pass for `bitscan_manager`.
- `pytest -q`: 1198 passed, 451 skipped (the 2 expected TASK-056 failures aside).
- PostgreSQL: **NOT RUN locally** (Docker unavailable); the SQL has been reviewed but never executed. TP-M3-06 in WSL is the first run.

## Deviations

None.
