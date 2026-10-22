# TASK-026 REVIEW: problem details, cursor pagination, timestamps

Reviewer: reviewer. Date: 2026-10-21. REQ-038. Spec: TS §6.3 L1133 (problem details), L1134 (cursor pagination, limit at most 500), L1139 (RFC 3339 UTC); TS §7.1 L1212 (400), L1215 (`{items, next_cursor}`); #47 (d), #48, #52; decisions 2026-10-21 (413 `too_large`, `about:blank`, "Lead rulings on TASK-026 TEST questions", "OpenAPI error contract"). Inputs: `work/reports/TASK-026-impl.md` (revisions 1 and 2), `work/reports/TASK-026-test.md` (PASS in round 3, CHK-M2-040 to -046, 14 of 14 mutations red).

Files reviewed:
- `manager/bitscan_manager/api/__init__.py` (empty);
- `api/problems.py`, `api/pagination.py`, `api/timestamps.py`;
- the `app.py` changes: `problems.install`, the 413 body from `problem_body`, and `route_caps` defaulting to an empty mapping.

Verdict: APPROVED

TASK-026 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **RFC 9457 shape.** Every handler goes through `problem_response`, so each body has exactly `type, title, status, detail, instance`. `instance` is `request.url.path`, with no query. The content type is `application/problem+json`. The 500 handler sends fixed text only. The `type` values follow #48, plus `too_large` and `about:blank` as the lead ruled. Because the security layer wraps `ServerErrorMiddleware` (TASK-024), the 500 still carries the headers.
- **No client text in `detail` (REQ-038 (2), (3)), as the tester asked me to check.** `_declared` (`problems.py:103`) collects only names the route declares: the body type, and the query, header, cookie and path parameters of the route and every dependency. `_field` (`:132`) stops at the first part of the error location that is not declared. I probed shapes beyond the tester's set, with a canary in each: a discriminated union with a bad tag and with a bad inner field; an `int | list[int]` union; `dict[str, int]` keys; a list of dicts; a field aliased `Alias` sent under its Python name; a non-object body; malformed JSON; an extra query parameter alongside a missing header. No canary appeared in any `detail`. Unions and discriminated unions stop at `<field>: invalid key`, which is less precise but safe.
- **Pagination.** The limit is 1 to 500 with a default of 50. Anything else is a validation error and gets 400. The cursor is base64url of a 16-byte HMAC-SHA256 tag plus `[scope, key]`, under a key that is random per process. Only the exact canonical encoding is accepted, the tag is compared with `hmac.compare_digest`, and the scope must match. This is a server-side integrity tag on an opaque cursor, not the `.bit` or job signing the owner ruled out. `page_of` uses the `limit + 1` row to decide `next_cursor`. #52 BIGSERIAL keys are JSON integers.
- **Timestamps.** `UtcDatetime` refuses naive input and always serialises as `…Z` in UTC (REQ-038 (5)).
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 74 files. The suite has 767 passed and 229 skipped (pg), G5 is at 97.73 %, and the OpenAPI export has no diff. The tester's WSL run had 996 passed and 0 skipped.
- **Scope.** 5 files and about 225 lines of code, slightly over the ~200 guide. Accepted: `timestamps.py` (19 lines) was added at the lead's ruling, and the declared-name walk is the price of REQ-038 (3).

## Findings

None block approval.

1. **carry-over to TASK-038 (decisions 2026-10-21, "OpenAPI error contract").** The FastAPI-generated OpenAPI still lists 422 `HTTPValidationError` for routes with a body or query, while the app answers 400 problem+json. TASK-038 removes 422, documents the 400 and route refusals, and adds a test that no route in `manager/openapi.json` lists 422. I will check it there.
2. **nit.** `pagination.py:73`: `found_scope, key = json.loads(payload)` runs only after the tag has verified, so the payload is always one `encode_cursor` wrote. If a future change ever let an unverified payload through, a malformed one would give a 500 here. A `try/except (ValueError, TypeError)` mapping to the same 400 would make the function total.
3. **nit.** Malformed JSON gives `detail` `Invalid request: body.<n>`, where `<n>` is the character offset of the parse error from FastAPI's `loc`. It is not client text, but it reads oddly. `body: invalid JSON` would be clearer.
4. **note, no change.** Cursors stop working when the manager restarts (`_KEY` is per process). The impl report records this, and it is acceptable with one manager instance (TS §2.1).
