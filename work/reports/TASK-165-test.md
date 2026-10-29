# TASK-165 TEST: PASS

Tester: tester-m7, 2026-10-28. REQ-173 (1) to (4), REQ-174 (2); TS §6.2 L1107 (`/imports`, admin, session or API token), §6.3 L1133 to L1139 (problem+json, opaque cursor, limit up to 500, integer catalog keys, RFC 3339 UTC), §6 L1056 (user routes take only `bsu_` and `bsk_`), §5.2 L694 to L707 and SR §3.5 (the twelve `bit_import` columns); #98 (h), (i), #48. Files under test: `bm/api/user/imports.py`, `bm/api/user/__init__.py`, `manager/openapi.json`. New test file `manager/tests/test_imports_api_pg.py` (81 tests) on the M2 users-API environment (real sink gate, real rate limiter). Rows are written through the TASK-149 repository as `bitscan_app`. No existing test needed changes: the route walk G34 already lists `GET /imports`, and its query-parameter pin holds (the new file also pins `/imports` to exactly `limit` and `cursor`).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7-t165`, label `m7t-t165`, `CI=true`, `-n 2`) | `pytest tests/test_imports_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_imports_repo_pg.py` | 142/142 passed, 0 failed, 0 errors, 0 skipped |
| plants (W, `-n 2`, each in `/root/bstest-m7-mut-<id>`, removed after) | `pytest tests/test_imports_api_pg.py` | see the plant rows |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on the new file | clean |

Containers of every run were removed (0 left by label).

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-258 (1) | APP | W | r0 | PASS | REQ-173 (1): N + 1 rows with `limit` N (1, 2, 5) walk the whole table once each, strictly newest first across pages, mine in descending id order, total equals `count(*)`; the order key is `import_id`, not `imported_at` (a later id with an earlier time comes first); the default page is 50 (the 50 newest of 51); `limit=500` accepted; `0`, `501`, `-1`, `a`, `1.5`, ``, `1e2` → 400 `invalid_request`; unknown query parameters (`outcome`, `mode`) change nothing and the OpenAPI operation has exactly `limit` and `cursor` (#98 (h) no filters) | 2026-10-28 |
| CHK-M7-258 (2) | APP | W | r0 | PASS | Every item's keys are exactly the twelve DDL columns in table order (checked against `SELECT *`); every value equals the stored row (success with version 7, counts 3/2/1 and `imported_by`; rejected with NULL version and user; skipped with `[]`); `import_id` is a JSON integer; `imported_at` matches RFC 3339 with `Z` and equals the stored time. `errors` equals the stored jsonb exactly for the four-finding set (null line and element, escaped text, U+202E, emoji, `Plugin[5000]/Execute/@timeout`, line 2^31 − 1), for 2,000 findings in order, and for `[]`; each finding has exactly `line, element, code, message` | 2026-10-28 |
| CHK-M7-258 (3) | APP | W | r0 | PASS | Admin session and admin `bsk_` → 200; operator and viewer, session and API → 403 `forbidden` (also with a cursor); admin without TOTP, restricted session and API token → 403 `totp_enrolment_required` | 2026-10-28 |
| CHK-M7-258 (4) | APP | W | r0 | PASS | Nine hostile `file_name` values come back byte-identical as `application/json`: `<script>`, U+202E, the #99 (d) U+FFFD form, `../../etc/x.bit`, quotes, backslash and `%00`, raw U+0001/U+001F/U+007F, 255 × U+1F6E1 (1,020 bytes), the empty name, leading and trailing spaces. A full walk leaves the `bit_import` checksum unchanged (read-only) | 2026-10-28 |
| CHK-M7-258 cursor | APP | W | r0 | PASS | Tampered (first, middle and last character flipped, truncated, one character appended, `==` padding, swapped case, inner space, `+/` alphabet, empty, `x`, non-ASCII, 513 characters) → 400 `invalid_request`; signed with the manager's key but the wrong shape (`"5"`, `true`, `false`, 0, −1, 2^63, 2^64, 10^30, `[5]`, `[5, 6]`, `[]`, `null`, an object, 1.5, 5.0) → 400; the bounds 1, 2, 2^63 − 1 → 200 (key 1 gives `{"items": [], "next_cursor": null}`); real cursors from `/audit-log`, `/users` and `/policies`, and signed integer cursors of the scopes `audit_log`, `users`, `policies`, `agents` and `` → 400. No 500 in any case | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, a `bsa_` whose hash is stored on an enrolled `online` agent, no token, garbage `bsu_` and `bsk_`, and `Basic` → 401 `unauthorized` problem+json with no items; the 600-per-minute user limit applies (600th request 200, 601st 429 `rate_limited`) | 2026-10-28 |
| CHK-M7-281 | APP | W | r0 (`test_invariants_m3.py`) | PASS | The route walk has `GET /api/v1/imports` and nothing else new; no request schema carries a command; the query-parameter pin holds | 2026-10-28 |
| G6 | CODE | W | r0 (`test_openapi.py`) | PASS | A fresh export is byte-identical to `manager/openapi.json`, and two exports are byte-identical; the operation documents 401, 403 and 429 as problem+json and its item schema lists the twelve columns in order, all required, `import_id` integer | 2026-10-28 |
| CHK-M7-165-rbac | APP | W | plant: `require_role("admin")` → `"operator"` | PASS (red) | 2 failed: `test_operator_and_viewer_get_403[operator-session]`, `[operator-api]` | 2026-10-28 |
| CHK-M7-165-token | APP | W | plant: the auth dependency removed from the route | PASS (red) | 13 failed, among them every `test_agent_tokens_and_bad_tokens_get_401` case, the stored-agent-token case, the rate-limit case and every 403 case | 2026-10-28 |
| CHK-M7-165-shape | APP | W | plant: `_before` returns the decoded key without the shape check | PASS (red) | 15 failed: each wrong-shape case (500 for `true`, `false`, 2^63, 2^64, 10^30, lists and the object; 200 for `"5"`, 0, −1, `null`, 1.5, 5.0) | 2026-10-28 |
| CHK-M7-165-scope | APP | W | plant: on a scope mismatch, fall back to decoding as `audit_log` | PASS (red) | 2 failed: `test_a_cursor_from_another_list_is_400[/api/v1/audit-log]`, `test_a_signed_int_cursor_of_another_scope_is_400[audit_log]` | 2026-10-28 |
| CHK-M7-165-tamper | APP | W | plant: the HMAC comparison removed from `decode_cursor` (`api/pagination.py`) | PASS (red) | 5 failed: the flip, swapped-case and empty cases (200 or 500 instead of 400) | 2026-10-28 |

## Acceptance

TASK-165 row: "Through the API on PostgreSQL: REQ-173 (1)–(4) hold and `bsa_` gets 401" — (1) CHK-M7-258 (1), (2) CHK-M7-258 (2), (3) CHK-M7-258 (3), (4) CHK-M7-258 (4); `bsa_` and `bse_` 401 CHK-M7-282; OpenAPI byte-stable G6. Every security row (RBAC, token type, cursor tamper, shape and scope) has a plant that went red.

## Notes (no defect)

- `decode_cursor` (M2, `api/pagination.py`) unpacks the payload as `[scope, key]` after the HMAC check. A payload of another length would raise and give 500, but only someone holding the per-process key can produce one, so it is not reachable from outside. Not a TASK-165 finding.
