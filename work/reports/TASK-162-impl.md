# TASK-162 IMPL: upload route `POST /api/v1/policies/import`

Implementer: impl-manager-m7. REQ-163 (1), (5), REQ-170, REQ-174, REQ-177. Risk high (importer; two approvals). Plan: `work/plans/TASK-162.md` (design note D5). Spec: TS §6.2 L1103, L1084; §6.3 L1137–L1138; §4.1 L522. Answers applied: #57, #98 (d), (j), #99, #102 (d), PD-33 (a). Carry applied: the TASK-155 review's stale-temp `FileExistsError` is a 503.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/policy_import.py` (new, 206 / 181 / 165 lines total / non-blank / code) | `ImportResult`, `UploadPart`, `parse_upload`, the route `import_policy` |
| `manager/bitscan_manager/app.py` | +11 / −1: the `bit` cap is `5 * MIB + 64 * 1024` (#99 (a)), and a `RouteCap("/api/v1/policies/import", "bit", ..., after_auth=True)` |
| `manager/bitscan_manager/api/user/__init__.py` | +2 for this task: `policy_import` imported and its router included |
| `manager/openapi.json` | **Not written by this task.** The lead's speed-up ruling (2026-10-28) says I regenerate it once, after TASK-162, 163 and 164 are all in. Checked locally: a temp export is byte-stable on a second run, and its diff against the current file is additions only (+280, −0). |

Size: 165 code lines plus 13 in the other two files, against an estimate of 170. About 25 are the OpenAPI request-body literal and the `ImportResult` fields.

## How it meets the plan

- **Auth and order:**
  - `require_role("admin")` takes an admin `bsu_` session or `bsk_` API token. A restricted admin session gets 403 `totp_enrolment_required`, the M2 rule.
  - There is no TOTP-session check and no sink gate: upload isn't a sensitive action (TS L1084).
  - The route declares no body parameter, so the token and role check run before a byte is read.
  - `read_capped` (reused from `api/agent/bodies.py`, as the plan says) then reads at most the `bit` cap. A larger `Content-Length` is refused unread; a chunked body stops after the chunk that crosses the cap. Either way the answer is 413 `too_large` with `Connection: close`, and there is no `bit_import` row (#99 (b)).
  - Every other route keeps the 1 MiB `json` cap.
- **`parse_upload(content_type, body)`, in memory (#99 (c)):**
  - The type must be `multipart/form-data`, compared case-insensitively (builder checklist 6), with a `boundary` of 1 to 70 bytes.
  - `python_multipart.multipart.MultipartParser` runs once over the bytes with callbacks: no `UploadFile`, `File()`, `Form()` or `FormParser`, so nothing is spooled to disk.
  - The callbacks allow one part, at most 16 headers (the parser's `max_header_count=16`, plus my own count), and header values of at most 8 KiB (checked exactly in `header_value`; the parser's own line limit is set 1 KiB above).
  - Data over 5 MiB raises `TooLarge` at once (413).
  - After `finalize`, the body must have exactly one complete part, whose `Content-Disposition` is `form-data` (case-insensitive) with `name` exactly `file`.
  - The part's own `Content-Type` is ignored.
  - Any `FormParserError`, a missing closing boundary included, gives 400 `invalid_request` "The body must be multipart/form-data with one part named file." That is fixed text, never echoing the body, a header or the name.
  - An empty part is passed on, and becomes a BIT001 rejection with its row (REQ-150 (1)).
- **Client name (#99 (d)):** `uploads.client_file_name(filename)` decodes UTF-8 with replacement, turns C0, DEL and lone surrogates into U+FFFD, cuts to 255 characters, and gives `""` when missing. `filename*` is ignored; python-multipart drops it. The name is only metadata.
- **The import:** `runtime.catalog.upload(data, client_name, Actor("user:<id>", <id>))` (TASK-160) runs in the thread pool, never on the event loop. Mode `manual`, never skipped.
- **Answers (plan §5):**
  - 200 `ImportResult` (#98 (d)) for `success` and `rejected`. The policy fields are null when rejected, and `errors` hold every finding as stored, warnings included (#110). The `errors` items reuse TASK-165's `ImportFinding` component, so there is one schema for the stored shape and no component-name clash.
  - `CatalogStarting` → 503 `about:blank` "The catalog is starting; retry shortly." with `Retry-After: 10` (#102 (d)).
  - `PolicyManagedOnServer` → 409 `policy_managed_on_server` "This policy is managed in the server folder; change its file there." The pipeline has already written the `policy.import_refused` entry, and there is no row (#99 (e)).
  - `OSError` → 503 `about:blank` "The policy file could not be stored; retry shortly." (#98 (j)). That covers the stale temp's `FileExistsError` from `O_EXCL` (the TASK-155 carry) and any other disk error.
  - `DatabaseUnavailable` → the app's existing 503 handler.
  - A committed import whose record failed (`import_id` None) → 503 `about:blank` "The import was stored but its record could not be written." It is logged, and the catalog change stands.
  - `runtime.catalog` None (tests, export) → 503 "The service is not ready."
- **OpenAPI:**
  - The `multipart/form-data` request body (`file`: binary, required, no other property) comes through `openapi_extra`.
  - Problem responses: 401, 403, 409, 413, 503. The 400 is added by `_problem_openapi` because the operation has a request body.
  - The response is `ImportResult` with `additionalProperties: false`.
- **Layering:** the handler only reads, parses the HTTP body and maps exceptions. The import is `CatalogService.upload`, then the pipeline, then the repositories.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager/bitscan_manager` passes, and `ruff format --check manager` passes (302 files).
- A whole-tree `ruff check manager` currently shows one E501 in tester-m7's in-progress `manager/tests/test_catalog_service_pg.py`.
- `mypy --strict --config-file manager/pyproject.toml manager` reports only 2 errors, also in that test file (`func-returns-value` at L286). Product code is clean.

## Scratch check (outside the tree, `%TEMP%\m7-154-scratch\check_parse.py`; `parse_upload` only; not a test)

- **Accepted:**
  - a valid part (a hostile name with `\x01` and `\xff` becomes `../../etc/pa�ss�wd`);
  - `Multipart/Form-Data` with `content-disposition: Form-Data`;
  - no `filename` (gives `""`);
  - an empty part (0 bytes, passed on);
  - 16 headers;
  - an 8 KiB header value;
  - a 5,242,880-byte part.
- **400:**
  - two parts;
  - `name="files"`;
  - `application/json`;
  - no boundary;
  - a 71-byte boundary;
  - no closing boundary;
  - 17 headers;
  - an 8 KiB + 1 value.
- **413 `too_large`:** a 5,242,881-byte part.
- python-multipart logs its own parse-error line through its logger, for example "Did not find LF character at end of header (found 34)". It names a byte value only, never content.

## For the tester (TP-M7-23, `manager/tests/test_policy_import_api_pg.py`, `test_security_m7.py`)

- Plan §7 rows 1 to 11 apply as written. The `errors` items are TASK-165's `ImportFinding` shape.
- Row 3: the body cap is 5,308,416 bytes (5 MiB + 64 KiB), and the part cap is 5,242,880 bytes.
- Row 8: build the app with a fake `Runtime(catalog=<fake raising CatalogStarting>)`.
- The stale-temp carry: plant `uploaded/.tmp-<id>-<sha>` for the next upload. The answer is 503 `about:blank` with the disk detail, no row, and the planted file untouched.
- **Suggested plants:**
  - declare the body as a parameter, so it is read before auth → row 3's unauthenticated-6 MiB row goes red;
  - use `UploadFile` or `FormParser` → row 9 (no spooling) goes red;
  - drop `kind.lower()` → a mixed-case type gets 400;
  - map `OSError` to 500 → the stale-temp row goes red.

## Open

- `manager/openapi.json`: the single regeneration after TASK-163 and TASK-164 (impl-manager-m7b) are in. Then I merge their router registrations in `api/user/__init__.py`, check that the export is byte-stable and that the diff is additions only, and message tester-m7, impl-web and main.

## The combined W8 OpenAPI regeneration (impl-manager-m7, 2026-10-28)

Done once, after TASK-162, 163 and 164 were all in (the lead's speed-up ruling).
- **`api/user/__init__.py`:** `policy_import` and `rebuild` (TASK-164, `api/user/rebuild.py`, no prefix) are imported and included after `policies`. TASK-163's `DELETE /policies/{id}` is on the existing `policies` router.
- **`manager/openapi.json`:** regenerated with `python -m bitscan_manager.app manager/openapi.json`. A second run is byte-identical (G6).
- **Additions only:**
  - against the pre-W8 working file: 0 lines removed;
  - against HEAD: every HEAD key and value is unchanged (structural walk). The 95 lines `git diff` counts as removed are only JSON commas and braces around appended keys.
- **New in this regeneration:**
  - operations `POST /api/v1/policies/import`, `DELETE /api/v1/policies/{id}`, `POST /api/v1/policies/rebuild` and `GET /api/v1/tasks/{id}`;
  - components `ImportResult`, `RebuildStarted`, `TaskFile`, `TaskResult`, `TaskFailure` and `TaskItem`;
  - every path under `/api/v1/`, apart from `/healthz` and `/readyz`.
- **Gates (whole tree):** `ruff check manager` passes, `ruff format --check manager` passes (304 files), and the CI mypy command gives Success with no issues in 304 source files.
