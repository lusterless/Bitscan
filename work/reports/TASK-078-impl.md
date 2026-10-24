# TASK-078 IMPL report: `GET /api/v1/audit-log`

REQ: REQ-085. Spec: TS §6.2 L1127, §5.3 L1051, §5.2 L981–L990; #38, #68. Depends on TASK-077 (OpenAPI order only).

## Files (4)

- `manager/bitscan_manager/repositories/audit_log.py`: adds `page_newest_first(conn, limit, before_id)`, a parameterised `SELECT … detail::text, at … ORDER BY audit_id DESC LIMIT %s` with keyset `audit_id < before_id`. It is read-only.
- `manager/bitscan_manager/api/user/audit_log.py`: new, 70 lines.
- `manager/bitscan_manager/api/user/__init__.py`: mounts the router.
- `manager/openapi.json`: re-exported and byte-stable. It adds `GET /api/v1/audit-log` → `Page[AuditItem]`; refusals 400, 401, 403, 429, 503.

**Layering note.** The task's file list has no service module, and the read has no logic. The route therefore calls the repository function directly; there is nothing to put in a service.

## Behaviour

- `require_role("admin")`: an admin session or an admin API token (TS §6.2: "admin", no TOTP marker). Operators and viewers get 403 `forbidden`.
- **Newest first** (#68), `{items, next_cursor}`. The cursor carries the last `audit_id` (M2 HMAC envelope), and the next page is `audit_id < cursor`, so each entry comes back exactly once. There are no filters.
- **Items are the eight columns:** `audit_id, actor, action, target, detail, at, prev_hash, row_hash`.
  - `detail` is `json.loads` of PostgreSQL's own `detail::text`, the string the chain hashes (#38). The object keeps jsonb's key order.
  - `at` is serialised as `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC (`UtcDatetime`), which is exactly the `at_text` form that is hashed.
  - A client can therefore re-verify each item: `compute_row_hash(prev_hash, HashInput(audit_id, actor, action, target, json.dumps(detail, ensure_ascii=False) if detail is not None else None, at))`. Python's default `json.dumps` separators (`", "`, `": "`) match jsonb's text output.
- The route writes nothing. Its transaction only reads.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (102 files).
- `pytest -q`: 2182 passed. The 9 failures are the known TASK-074 test-file updates.
- Through the API on PostgreSQL (TP-M3-32, including the `compute_row_hash` re-verification on real rows): **NOT RUN locally** (no PostgreSQL on Windows); WSL.
  - **For the tester:** if a stored `detail` holds a number whose jsonb text differs from Python's `repr`, for example `1e20` stored as `100000000000000000000`, the `json.dumps` re-serialisation would not match. No M3 writer stores such numbers; it is noted in case the check meets one.

## Deviations

None.

## Revision 1

This revision follows the lead's ruling of 2026-10-23 in `work/decisions.md`, "Audit-log items carry `detail_text`" (option (b), on tester-e's TASK-078 question).

- **`detail_text` on every item:** each `GET /api/v1/audit-log` item now also has `detail_text`. It is PostgreSQL's own `detail::text`, the exact string the chain hashed, or null when `detail` is null. It sits next to the parsed `detail`, which is unchanged.
- **Why:** a client can now re-verify `row_hash` byte for byte with `compute_row_hash`, even for floats. jsonb writes `1e-07` as `0.0000001`, so re-serialising `detail` does not reproduce the hashed text.
- **Source:** the repository already returned this text (`page_newest_first`, row index 4), so there is no SQL change.

## Revision 1: files

- `manager/bitscan_manager/api/user/audit_log.py`: the `AuditItem.detail_text: str | None` field (required, nullable) and the module docstring.
- `manager/openapi.json`, re-exported. The only diff against the previous export (after TASK-075 r1 and TASK-083) is `AuditItem.properties.detail_text` (`string | null`) plus `detail_text` in `required`. A second export is byte-identical.
- **Export order:** 078's export comes before 079's in the OpenAPI order. This export is taken from the full current tree, so it also carries 079's metrics route. The file is a single snapshot with no ordering conflict, but the tester should re-check 079's OpenAPI assertions against it.
- **`README.md`**, the file TASK-080 owns: the audit-log bullet now lists `detail_text` in the item shape. The re-verification steps now hash `detail_text` and `at` as returned, compactly and without escaping non-ASCII, and warn not to re-serialise `detail`.

## Revision 1: gates (Windows)

- ruff, format and `mypy --strict` are green.
- The audit-log test files pass: 70 passed, 1095 skipped (the PostgreSQL tests skip without Docker).
- **Not run:** the PostgreSQL suites. Only the tester runs them, in WSL.
- Any test that compares an item's keys to exactly eight now sees nine.
