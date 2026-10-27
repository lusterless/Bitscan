# TASK-165 IMPL: import history route `GET /api/v1/imports`

Implementer: impl-manager-165. REQ-173, REQ-174. Risk: low. Spec: TS §6.2 L1107 (route row, admin), §6.3 (pagination, plain text, catalog keys as integers), §5.2 L694-L707 (`bit_import` DDL); open questions #98 (h), (i), #110.

## Files

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/api/user/imports.py` | new: `ImportItem`, `_before`, `list_imports` | 59 |
| `manager/bitscan_manager/api/user/__init__.py` | `imports` imported (L32) and `imports.router` included (L51) | +2 |
| `manager/openapi.json` | re-exported with `python -m bitscan_manager.app manager/openapi.json` | +228, insertions only |

No file outside this list was changed. `services/importer` was not touched.

## Route

- `GET /api/v1/imports` (`imports.py:60`), `require_role("admin")`: an admin `bsu_` session or `bsk_` API token. Operators and viewers get 403 from that dependency, as on `/audit-log`. It sits in the user router, so `bsa_` and `bse_` get 401 (REQ-174 (2)).
- Query: `limit` (1-500, default 50) and `cursor` only, through the shared `page_params`; no filters (#98 (h)).
- Response: `Page[ImportItem]` = `{items, next_cursor}`. `ImportItem` (`imports.py:32`) has every `bit_import` column in DDL order: `import_id`, `file_name`, `file_sha256`, `policy_version`, `mode`, `outcome`, `plugins_added`, `plugins_updated`, `plugins_retired`, `errors`, `imported_by`, `imported_at`. `import_id` is a JSON integer (#98 (i)); `mode` and `outcome` are the DDL CHECK literals; `imported_at` uses `UtcDatetime` (RFC 3339 UTC); `imported_by` null = system.
- Order: newest first by `import_id`, keyset on `import_id < before`, from TASK-149's `repositories.imports.imports_newest_first(conn, limit + 1, before_id)`. The extra row only tells `page_of` that another page exists.
- Cursor (`_before`, `imports.py:49`): HMAC- and scope-checked by `decode_cursor` (scope `"imports"`), then the key must be an `int` (not `bool`) in 1..2^63−1 before PostgreSQL casts it (builder checklist 1). Anything else gets 400 `invalid_request` "Invalid request: query.cursor", never 500.
- Layering: the handler reads straight from the repository, with no service layer, as `GET /audit-log` does (`api/user/audit_log.py`). It is a plain read with no rules to apply, and the task's file list has no service file.
- Read-only: one read transaction, no audit entry, no alert, no write. Nothing here edits plugins or commands, queues a job, or carries stdout or stderr.

## How REQ-173 is met

1. N + 1 rows with `limit=N`: the first page holds the N newest, and `next_cursor` holds the last item's `import_id`. The second page holds the one remaining row (`import_id < cursor`) with `next_cursor: null`. Every row appears once, strictly newest first, because `import_id` is unique.
2. `errors` is validated as `list[dict[str, Any]]`, so it passes through exactly as `jsonb` returns it: findings with `line`, `element`, `code`, `message`, warnings included (#110). Nothing is filtered, re-ordered or rewritten.
3. `require_role("admin")`: an operator gets 403 and an admin `bsk_` gets 200. There is no TOTP-session requirement, because the route is not a sensitive action.
4. `file_name` is a `str` with no normalisation, returned as a JSON string, so a hostile name (`<script>`, `=cmd|`, `../`, control characters other than U+0000) comes back byte-identical.

## How REQ-174 is met (this route's share)

- (1) The route walk gains exactly one operation, `GET /api/v1/imports`.
- (2) User router only, so `bsa_` and `bse_` get 401.
- (3) No agent route or contract was touched.
- (4) No new repository module; the read reuses TASK-149's parameterised `_PAGE`.
- (5) G6: two exports are byte-identical, and the diff is insertions only: the path, plus the `ImportItem` and `Page_ImportItem_` components. There is no component-name clash and no 422 (the app supplies the 400). Integer bounds: only `limit`'s `maximum: 500`.
- Refusals are documented as problem+json: 401, 403, 429, 503 (plus the app-wide 400).

## Gates (Linux container, `manager/.venv`)

- `ruff check manager && ruff format --check manager`: All checks passed; 279 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 279 source files.
- openapi export run twice: `cmp` identical. `git diff --numstat`: 228 insertions, 0 deletions.
- `pytest -q -p no:cacheprovider -n 4 tests/test_policies_api_pg.py tests/test_imports_repo_pg.py tests/test_app.py` (CI=true, RYUK pinned): 97 passed.
- Spot-check of `_before`: `None` → None, and a valid cursor of 5 → 5. Cursors holding `True`, 0, -1, 2^63, `"5"` or `[5]`, and an `audit_log` cursor, all give 400.

## For the tester (TP-M7-22, `manager/tests/test_imports_api_pg.py`, PostgreSQL)

- REQ-173 (1)-(4) as above. Seed rows with `repositories.imports.insert_import` in separate transactions.
- RBAC: viewer and operator get 403; admin `bsu_` and `bsk_` get 200; `bsa_` and `bse_` get 401; no token gets 401.
- Cursor: a tampered cursor, another list's cursor (for example from `/audit-log` or `/policies`) and a non-base64 cursor each give 400 problem+json. `limit=0` and `limit=501` give 400.
- An empty table gives `{"items": [], "next_cursor": null}`.
- `tests/test_invariants_m3.py:77` already lists `("GET", "/imports")` in the spec allow-list. `tests/test_invariants_m3.py` and `tests/test_openapi.py` pass with the route added (39 passed).
- The route walk (G34) and the OpenAPI pins will see the one new path and the two new components.
