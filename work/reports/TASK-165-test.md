# TASK-165 TEST: PASS

Tester: tester-m7-165, 2026-10-27. REQ-173 (1) to (4), REQ-174 (2); TS §6.2 L1107 (`GET /imports`, admin), §6 L1056 (user routes take only `bsu_`/`bsk_`), §6.3 L1133 to L1141 (problem+json, cursor paging, max 500, catalog keys as integers, RFC 3339 UTC, stored text untrusted), §5.2 L694 to L707 (`bit_import`); #98 (h), (i), #110, #53 (i), #48. Files under test: `bm/api/user/imports.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (plus TASK-149's `repositories/imports.py` through the route). New test file `manager/tests/test_imports_api_pg.py` (79 tests) on the M2 users-API environment (real auth, sink gate, rate limiter), with a module-owned PostgreSQL (`own_migrated_server`) and `bit_import` truncated as owner before each test, so page contents are asserted exactly. Tests were derived from the spec and the answers first; the code was read only for the cursor-key branch.

## Runs (Linux container, `CI=true`, Ryuk pinned)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 | `pytest -n 2 tests/test_imports_api_pg.py` | 77/78 passed, 1 failed, 0 errors, 0 skipped: `test_bad_limit_is_400[50 ]` (test bug: the shared `page_params` accepts `"50 "` as 50 on every list; not this task; case removed) |
| r1 | `pytest -n 0 tests/test_imports_api_pg.py::test_bad_limit_is_400` | 7/7 passed |
| r2 | `pytest -n 4 tests/test_imports_api_pg.py tests/test_imports_repo_pg.py tests/test_policies_api_pg.py tests/test_audit_log_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_auth_dependencies.py tests/test_app.py` | 258/258 passed, 0 failed, 0 errors, 0 skipped |
| r3 | `pytest -n 4 tests/test_imports_api_pg.py` (after adding the 2 prefix-vs-hash tests) | 79/79 passed |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (283 files) |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-258 (1) | APP | W | r2, r3 | PASS | N + 1 rows with `limit=N` (N = 1, 2, 3, 7, 500): pages `[N newest], [oldest]`, each once, strictly by `import_id` desc, `next_cursor` null on the last page; exactly N rows → one page, cursor null; empty → `{"items": [], "next_cursor": null}`; default limit 50 (51 rows); order is `import_id`, not `imported_at` (clock stepped back); rows added between pages do not appear on page 2; limit `0`, `501`, `-1`, `a`, `1.5`, ``, `1e2` → 400 `invalid_request`; unknown parameters (`outcome`, `mode`, `file_name`, `status`, `order`, `sort`, `before`) are ignored and never filter (#98 (h), as `test_package_query.py`) | 2026-10-27 |
| CHK-M7-258 cursor | APP | W | r2, r3 | PASS | tampered cursors (MAC byte, payload byte, truncated, appended, padding, space, `x`, `W10`, `!!!!`, `%00`, 512 × `A`) → 400; 513 chars → 400; real `/users` and `/api-tokens` cursors → 400; validly signed integer cursors of scopes `audit_log`, `policies`, `users`, `agents`, `api_tokens`, `Imports`, `` → 400; signed `imports` keys `True`, `False`, 0, -1, -2^63, 2^63, 2^64, 10^30, `"5"`, `""`, `[5]`, `[]`, null, 1.5, `{}` → 400, never 500; keys 1 (empty page) and 2^63-1 (all rows) → 200 | 2026-10-27 |
| CHK-M7-258 (2) | APP | W | r2, r3 | PASS | every item has exactly the 12 `bit_import` columns; `import_id`, `policy_version`, the three counts and `imported_by` are JSON integers, nulls for a system/skipped row; `imported_at` ends `Z` and equals the stored instant; every mode × outcome round-trips; `errors` equals the stored `jsonb` and the inserted list (BIT003, BIT101, BIT103, BIT001 with null line/element), warnings kept on a success (#110), 2,000 findings returned whole | 2026-10-27 |
| CHK-M7-258 (3) | APP | W | r2, r3 | PASS | admin `bsu_` and admin `bsk_` → 200; operator and viewer (session and API) → 403 `forbidden` with no item in the body; admin without TOTP (session and API) → 403 `totp_enrolment_required` (#53 (i)) | 2026-10-27 |
| CHK-M7-258 (4) | APP | W | r2, r3 | PASS | a hostile `file_name` (HTML/JS, `../`, formula prefixes, CR LF tab, bidi, ESC, DEL, C0, `%00`) and hostile `element`/`message` come back byte-identical as JSON; `application/json` with `nosniff` | 2026-10-27 |
| CHK-M7-282 | APP | W | r2, r3 | PASS | `bsa_`, `bse_`, no token, garbage `bsu_`/`bsk_`, a revoked admin token → 401 problem+json with no data; a `bsa_`/`bse_` string whose hash is stored as an admin API token is still 401 (prefix decides the group); 600 requests in a minute pass and the 601st is 429 `rate_limited`, and the next window passes; POST/PUT/PATCH/DELETE on `/imports` and `/imports/{id}` → 404/405 with nothing changed; GETs write no `bit_import` or `audit_log` row | 2026-10-27 |
| CHK-M7-281 | APP | W | r2 (`test_invariants_m3.py`) | PASS | the route walk passes with `GET /imports` (already in the spec allow-list); no query parameter can switch inventory off | 2026-10-27 |
| G6 | CODE | W | r2 (`test_openapi.py`) and `test_openapi_documents_the_route_…` | PASS | export byte-identical to `manager/openapi.json`; the path has only `get`, parameters exactly `limit` (1..500, default 50) and `cursor`; 400/401/403/429 are problem+json; `ImportItem` has the 12 columns, all required, `import_id` integer, `mode`/`outcome` enums as the DDL CHECKs | 2026-10-27 |

## Plants (scratch copies under `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/t165/`, `bitscan_manager` plus `tests` copied, run from the copy with `PYTHONPATH` set)

Control: a probe test printed `bitscan_manager.__file__` inside the copy, and the unchanged copy ran 79/79 passed.

| Plant | Result | Failing tests |
| --- | --- | --- |
| p1 RBAC loosened: `require_role("operator")` | red | 2 failed (operator session and API get 200) |
| p2 cursor scope check removed in `decode_cursor` | red | 8 failed (real `/users` cursor, 7 foreign-scope cursors) |
| p3 `bsa_`/`bse_` parsed as `bsk_` in `parse_user_token` | red | 2 failed (prefix-vs-hash tests) |
| p4 order flipped (`ORDER BY import_id ASC`) | red | 14 failed |
| p5 cursor key bounds/type check removed in `_before` | red | 15 failed (500 instead of 400) |
| p6 order by `imported_at DESC, import_id DESC` | red | 1 failed |
| p7 warnings (BIT101/BIT103) dropped from `errors` | red | 2 failed |
| p8 no look-ahead row (`limit` instead of `limit + 1`) | red | 9 failed |

8/8 plants red.

## Findings for the reviewer

- None against TASK-165. The route matches #98 (h), (i) and REQ-173.
- Note (not this task): the shared `page_params` accepts `limit=50 ` (trailing space) as 50 on every list (pydantic lax int). The spec does not forbid it; recorded, not tested.
- In p3, an unknown `bsa_` token is 401 even with the prefix check removed, because the hash lookup fails. Only the hash-present test shows the prefix check, so it is kept as a security row.
