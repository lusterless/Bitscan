# TASK-165 IMPL: import history route `GET /api/v1/imports`

Implementer: impl-manager-m7. REQ-173, REQ-174. Risk low. Spec: TS §6.2 L1107 (admin, session or API token), §6.3 L1134 (cursor pagination, `limit` up to 500), §6.3 L1139 (catalog keys are integers); SR §3.5 (the `bit_import` columns). Answers applied: #98 (h) (every column, newest first by `import_id`, no filters) and (i) (`import_id` is a JSON integer), and #48 (the error contract). Mirrors the approved TASK-161 routes in `api/user/policies.py`.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/imports.py` (new, 65 non-blank lines) | `ImportFinding`, `ImportItem`, `_before` (cursor check), `list_imports` |
| `manager/bitscan_manager/api/user/__init__.py` | +2 lines: import `imports` and `router.include_router(imports.router)` |
| `manager/openapi.json` (re-exported) | +270 lines, additions only: path `/api/v1/imports` and components `ImportFinding`, `ImportItem`, `Page_ImportItem_` (no name clash) |

## Behaviour

- **RBAC:** `require_role("admin")`, the same dependency as `GET /audit-log` and `PATCH /policies/{id}`, so it takes an admin's session or API token. It sits in the user router, so only `bsu_` and `bsk_` tokens are accepted: `bsa_` and `bse_` get 401, and an operator or viewer gets 403.
- **Items:** every `bit_import` column, in table order: `import_id`, `file_name`, `file_sha256`, `policy_version`, `mode`, `outcome`, `plugins_added`, `plugins_updated`, `plugins_retired`, `errors`, `imported_by`, `imported_at` (RFC 3339 UTC via `UtcDatetime`).
  - `errors` is a list of `{line, element, code, message}`, as the pipeline writes it (warnings included, #110). It comes back equal to the stored JSON. jsonb doesn't keep key order, so only the order of keys inside each item can differ.
  - `file_name` and the other text come back as stored, as JSON strings; nothing is escaped or changed.
- **Order and paging:**
  - `repositories.imports.imports_newest_first(conn, limit + 1, before)` reads newest first by `import_id`, and `page_of` returns `{items, next_cursor}`.
  - The cursor holds the last item's `import_id`, HMAC-checked and scoped `imports` by `decode_cursor`.
  - The decoded key is then shape-checked **before** any PostgreSQL cast (builder checklist 1, as TASK-161): it must be `type(key) is int` and 1 ≤ key ≤ 2^63 − 1. A bool, 0, a negative number, 2^63, a string, a list, a float or a cursor from another list all get 400 `invalid_request` "Invalid request: query.cursor".
  - `limit` (1–500) and `cursor` (≤ 512 characters) are validated by the shared `page_params`.
- **Refusals documented:** 401, 403, 429, 503 as problem+json (400 comes from the app's validation handler, as on the other lists).
- **Layering:** the handler only authorises, checks the cursor and reads. It calls the TASK-149 repository read directly in a read-only transaction, as the approved `GET /audit-log` route does. The task's file list has no service module, and the read has no business logic to put in one. If the reviewer wants a pass-through service such as `services/importer/profiles.py`, it would be a fourth file outside this task's list.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` and `ruff format --check manager`: pass (re-run 2026-10-28 after the TASK-154 split; 281 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 281 source files.
- Main accepted the direct repository read (decisions 2026-10-28, "TASK-154 and TASK-165 rulings": the `GET /audit-log` precedent, no service module).
- `python -m bitscan_manager.app manager/openapi.json` run twice gives byte-identical files (G6). The diff against the previous export is additions only.

## Scratch checks (outside the tree)

- An `ImportRow` with a hostile `file_name` (U+202E, U+FFFD, `<b>`) and one error item validates to an `ImportItem`. `file_name` is unchanged, and the item serialises with exactly the four error keys.
- `_before`: None → None, a good cursor → 42, and each bad key above → 400.

## For the tester (TP-M7-22, `manager/tests/test_imports_api_pg.py`)

- REQ-173:
  - (1) Insert N + 1 rows with `imports.insert_import` and page with `limit=N`.
  - (2) Compare `errors` with the stored jsonb as objects.
  - (3) An operator session gets 403; an admin `bsk_` gets 200.
  - (4) A hostile `file_name` comes back unchanged (U+0000 can't be stored in text; use the #99 (d) form).
- REQ-174 (2): `bsa_` and `bse_` get 401.
- Cursor shape cases as listed above.
- The route walk (G34) gains one operation: `GET /api/v1/imports`.
- No migration, no repository change, no agent-route change.
