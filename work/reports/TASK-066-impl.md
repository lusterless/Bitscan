# TASK-066 IMPL report: enrolment tokens (CRUD `/api/v1/enrollment-tokens`)

REQ: REQ-067, REQ-063. Spec: TS §3.2 L181, §6.2 L1084 and L1116, §8.4 L1290, §5.2 L748–L759; #48, #68, #71. Plan: `work/plans/TASK-067.md` ("Enrolment tokens"). Depends on TASK-050, 052, 056, 059 and 062, all approved. **Two approvals** (TS §8.2). Carry-over applied: a CIDR with host bits is refused with 400 before the insert.

## Files (4)

- `manager/bitscan_manager/services/enrolment/enrolment_tokens.py`: new, 148 lines.
- `manager/bitscan_manager/api/user/enrolment.py`: new, 164 lines. TASK-070 adds the requests routes to this file.
- `manager/bitscan_manager/api/user/__init__.py`: mounts the router.
- `manager/openapi.json`: re-exported. A second export is byte-identical. The new paths are `/api/v1/enrollment-tokens` (GET, POST) and `/api/v1/enrollment-tokens/{token_id}` (GET, DELETE); there is no PATCH.

Size: the two hand-written files total 312 lines, against an estimate of 170. Most of it is the #68 response models and ruff-formatted keyword calls. Please rule on whether it may stay one task.

## Routes (all `require_totp_session()`: admin, TOTP-verified session, sink gate)

- An admin `bsk_` gets 403 `totp_session_required`, and so does an unverified session.
- Operator and viewer sessions get 403 `forbidden`.
- During the 15-minute sink outage the answer is 503 `audit_sink_unavailable`.
- These are the M2 dependency markers, so the route walk sees them.

**`POST`** takes `CreateToken`, with `extra="forbid"` and these fields:

| Field | Type and range | Default |
| --- | --- | --- |
| `max_uses` | `StrictInt` 1–10,000 | 1 |
| `expires_in_hours` | `StrictInt` 1–720 | 24 |
| `allowed_cidrs` | list of 1–64 strings, or null for any source | null |
| `auto_approve` | `StrictBool` | false |

- It answers **201** with `{token_id, token, max_uses, uses, auto_approve, allowed_cidrs, expires_at, created_at}`. The `bse_` token appears **only here**.
- Out-of-range values and wrong types get 400 from the M2 validation handler.
- A CIDR that is not a network address (host bits set, such as `10.0.0.1/8`), not an address at all, or an invalid prefix (`/33`) gets **400** `Invalid request: body.allowed_cidrs`, raised by the service before anything is written.

**`GET`** lists `{items, next_cursor}` in `token_id` order, as keyset pages through the M2 pagination helpers. `GET /{token_id}` returns one item. Items are `{token_id, max_uses, uses, auto_approve, allowed_cidrs, expires_at, created_at, revoked_at, created_by}`. No response model has a `token` or `token_hash` field, and the repository row does not even select the hash.

**`DELETE /{token_id}`** sets `revoked_at = now` if it is not already set, and answers **204** either way. The row is kept. An unknown id gets 404 `not_found`.

## Service

- `check_cidrs`: `ipaddress.ip_network(c, strict=True)` on each entry, stored in canonical form. A bare host address becomes `/32` or `/128`, as PostgreSQL `CIDR` would store it.
- `create_token`:
  - Generates `new_agent_token(ENROLMENT)` and stores only `token_hash(token)`, with `created_by` the admin id and `expires_at = now + hours` (the Clock).
  - Writes **one** entry, action `enrollment_token.create`, actor `user:<id>`, target `enrollment_token:<id>`, detail `{max_uses, auto_approve, allowed_cidrs, expires_at}`.
  - If `auto_approve` is true or `max_uses > 100`, that same entry is written as the **`enrolment_token_risky` alert**, with `detail.risky = {auto_approve, over_100_uses}` (#71: one entry per event, flagging both causes). `max_uses = 100` without auto-approve writes a plain audit entry.
  - No detail ever holds the token or its hash.
- `revoke_token`: returns False for an unknown id. It writes one `enrollment_token.revoke` entry only when it actually revokes; a second delete writes nothing.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (161 files).
- `pytest -q`: 2130 passed, 704 skipped, 0 failed.
- Scratch probe of the service with fakes:

  | Input | Result |
  | --- | --- |
  | defaults | `max_uses` 1, expiry + 24 h, CIDRs null, auto-approve false; a well-formed `bse_` token, and the stored hash equals SHA-256 of the token; a plain audit entry |
  | auto-approve; 101 uses; auto-approve with 500 uses | each one `enrolment_token_risky` alert |
  | 100 uses | a plain audit entry |
  | `10.0.0.1/8`, `nope`, `[]`, 65 entries, `/33` | refused |
  | `10.0.0.1` | normalised to `10.0.0.1/32` |
  | delete | revokes and writes one entry |
  | second delete | true, no new entry |
  | unknown id | false |

  The row is kept with `revoked_at` set, and no token appeared in any entry.
- Through the API on PostgreSQL (TP-M3-20): **NOT RUN locally**; WSL.

## Deviations

None, apart from the size noted above.

## Revision 1 (tester-b FAIL round 1: CHK-M3-191, CHK-M3-195)

1. **CHK-M3-191: an IPv6 scope id gave 500.**
   - Cause: `ipaddress.ip_network("fe80::%eth0/64", strict=True)` accepts a scope id (Python 3.9+), `str()` keeps `%eth0`, and PostgreSQL's `CAST(… AS cidr[])` then fails.
   - Fix: `check_cidrs` refuses any entry containing `%`. The refusal is `InvalidCidrs` → 400 `Invalid request: body.allowed_cidrs`, raised before anything is written.
   - Probe: `fe80::%eth0/64` and `fe80::1%1` are refused; `fe80::/64` and `10.0.0.0/8` are accepted.
2. **CHK-M3-195: two concurrent DELETEs wrote two revoke entries.**
   - Cause: the service read the row without a lock and then revoked unconditionally.
   - Fix: a new repository method, `EnrolmentRepo.revoke_active_token(token_id, now) -> bool`, runs `UPDATE … SET revoked_at = now WHERE token_id = %s AND revoked_at IS NULL` and returns True only for the call that changed the row. The row lock makes the second caller re-check `revoked_at` after the first commits, so it changes nothing.
   - `revoke_token` (service) now checks existence (404) with `get_token`, then audits only when `revoke_active_token` returned True. Both callers still get 204.
   - Probe: two threads, both past `get_token` before either updated (barrier). Both returned found, and exactly **one** `enrollment_token.revoke` entry was written.

**Touched approved file:** `manager/bitscan_manager/repositories/enrolment.py` (TASK-052) gains `revoke_active_token`. The approved `revoke_token`, which keeps an earlier `revoked_at` and returns whether the token exists, is unchanged and still used by nothing else. The reviewer should read the addition; re-run `tests/test_enrolment_repo_pg.py` (W).

The service's `TokenStore` protocol now lists `revoke_active_token` instead of `revoke_token`.

**Gates (Windows):** ruff, ruff format and `mypy --strict` pass (170 files). `pytest -q`: 2159 passed, 827 skipped, 0 failed. OpenAPI export: unchanged.
