# TASK-066 REVIEW: enrolment tokens (CRUD `/api/v1/enrollment-tokens`)

Reviewer: reviewer. Date: 2026-10-23. REQ-067, REQ-063. Spec:
- TS §3.2 L181: `max_uses` 1–10,000; expiry default 24 h; optional `allowed_cidrs`; `auto_approve` default off; a token with auto-approve or more than 100 uses alerts.
- TS §6.2 L1084: managing enrolment tokens is a sensitive action, TOTP session only and API tokens refused.
- TS §6.2 L1116: CRUD, admin, TOTP session.
- TS §5.3 L1051: refused during the audit-sink outage.
- TS §5.2 L748–L759: `CIDR[]`, hash only.
- TS §8.4 L1290.

Decisions: #68 (bodies, expiry 1–720 h, 1–64 CIDRs), #71 (one entry per event, `enrolment_token_risky`); lead ruling W3 (2) (size accepted, 312 lines). Plan: `work/plans/TASK-067.md` ("Enrolment tokens"). Inputs:
- `work/reports/TASK-066-impl.md`, including "Revision 1";
- `work/reports/TASK-066-test.md`: round 1 FAIL (CHK-M3-191 scope-id CIDR → 500; CHK-M3-195 two concurrent DELETEs → two entries), then PASS on revision 1 (69 API tests plus repository and route-walk tests; 152 passed in WSL; 19 of 19 plants red).

Files reviewed:
- `manager/bitscan_manager/services/enrolment/enrolment_tokens.py` (new);
- `manager/bitscan_manager/api/user/enrolment.py` (new);
- `manager/bitscan_manager/api/user/__init__.py` (mount);
- `manager/openapi.json`;
- revision 1's addition to the approved TASK-052 `manager/bitscan_manager/repositories/enrolment.py` (`revoke_active_token`);
- the tester-b tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; enrolment). This is the first one; the user's second approval is still needed.

## What was checked

- **Authorisation (security invariants "Authorisation").** Every method (`POST`, `GET` list, `GET /{token_id}`, `DELETE /{token_id}`) uses `require_totp_session()` (admin, TOTP-verified session, `sink_gate=True`):
  - an admin `bsk_` gets 403 `totp_session_required`, and so do an unverified session and an operator's `bsk_`;
  - operator and viewer sessions get 403;
  - during the sink outage the answer is 503 `audit_sink_unavailable`;
  - the route walk sees the markers.

  Plants CHK-M3-328 and -329 are red. There is no PATCH, and no CLI command was added (decisions 2026-10-20).
- **Spec conformance.**
  - `CreateToken` has `extra="forbid"` and these fields:
    - `max_uses` StrictInt 1–10,000, default 1;
    - `expires_in_hours` 1–720, default 24;
    - `allowed_cidrs` 1–64 strings or null;
    - `auto_approve` StrictBool, default false (CHK-M3-336 red).
  - The answer is 201 with the #68 keys. The `bse_` token appears **only** in that response.
  - List and read items have no `token` or `token_hash` field, and the repository row does not select the hash.
  - Only `token_hash(token)` is stored (CHK-M3-325 red).
  - Lists are `{items, next_cursor}` keyset pages. An unknown id gets 404 `not_found`.
  - `DELETE` sets `revoked_at` and keeps the row, answering 204 whether or not it was already revoked.
- **Alerts and audit (#71).**
  - Create writes one `enrollment_token.create` entry.
  - With auto-approve or `max_uses` > 100, that same entry is the `enrolment_token_risky` alert, with `detail.risky` flagging both causes. 100 without auto-approve is a plain entry.
  - Revoke writes one `enrollment_token.revoke` entry.
  - No detail holds the token or its hash.
- **Revision 1, check 1 (anything PostgreSQL `cidr` refuses gets 400 before a write).** `check_cidrs` parses each entry with `ipaddress.ip_network(c, strict=True)` and stores `str()` of the result, which is canonical `address/prefix` text. I probed the forms Python accepts:
  - netmask and hostmask notation, IPv4-mapped IPv6, upper case, a bare address and `/08` all become canonical forms (`10.0.0.0/8`, `::ffff:a00:0/104`, `fe80::/64`, `10.0.0.0/32`), which PostgreSQL accepts;
  - host bits, leading zeros, surrounding whitespace, a trailing newline, a signed prefix and non-ASCII digits are refused by Python;
  - the IPv6 scope id is the only accepted input whose text survives `str()` unchanged, and revision 1 refuses any entry containing `%`.

  So everything that reaches the `CAST(… AS cidr[])` is valid `cidr` text, and every refusal is `InvalidCidrs` → 400 `Invalid request: body.allowed_cidrs`, raised before anything is written.
- **Revision 1, check 2 (one revoke entry).** `revoke_active_token` runs `UPDATE … SET revoked_at = now WHERE token_id = %s AND revoked_at IS NULL` and returns `rowcount == 1`. Under READ COMMITTED, a second concurrent UPDATE waits for the row lock, re-checks `revoked_at IS NULL` after the first commits, and changes nothing. The service writes the audit entry **only** when that call returned True. The tester's barrier test (both callers past the existence check) shows exactly one entry.
- **The approved TASK-052 file.** The addition is one parameterised UPDATE, using the UPDATE grant on `enrollment_token` that TS §5.2 gives, with no DELETE. The approved methods are unchanged, and `test_enrolment_repo_pg.py` was re-run in WSL.
- **OpenAPI (G6).** My re-export is byte-identical. The document has `/api/v1/enrollment-tokens` (GET, POST) and `/api/v1/enrollment-tokens/{token_id}` (GET, DELETE), with problem+json refusals and no 422.
- **Tests (my run, Windows).** `test_enrolment_tokens_api_pg.py`, `test_enrolment_repo_pg.py`, `test_auth_dependencies.py`, `test_security_m2.py` and `test_openapi.py`: 12 passed, 146 skipped (PostgreSQL; run in WSL by tester-b). ruff and format are clean, and `mypy --strict` is clean on the whole tree (172 files).

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/repositories/enrolment.py` (`EnrolmentRepo.revoke_token`, TASK-052). Since revision 1, nothing calls it: the service uses `revoke_active_token`, and `grep` finds no other caller. Remove it in a later touch of that file, or keep it only if TASK-077 or a later task needs it.

## Carry-overs

- **TASK-067.** Enrolling with a revoked, expired, exhausted or out-of-CIDR token answers 401 `unauthorized` and changes nothing (CHK-M3-200). Convert an IPv4-mapped peer before the CIDR check (TASK-052 carry-over).
- **TASK-070** edits `api/user/enrolment.py` next. Its routes use the same `require_totp_session()` for approve and reject, and `require_role("admin")` for the `GET /enrollment-requests` list (TS §6.2: admin, session or API token).
