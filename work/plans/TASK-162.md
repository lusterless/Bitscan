# TASK-162 plan: upload route `POST /api/v1/policies/import`

Planner: planner-m7, 2026-10-27, from design note D5 (`work/tasks.md`, M7). Risk: high (importer; two approvals). Files:
- `manager/bitscan_manager/api/user/policy_import.py` (new);
- `manager/bitscan_manager/app.py` (cap entry);
- `manager/bitscan_manager/api/user/__init__.py` (router);
- `manager/openapi.json` (re-export).

Depends on TASK-139 (`python-multipart`) and TASK-160 (`CatalogService.upload`). Answers applied: #57, #98 (d), (j), #99, #102 (d), PD-33 (a).

## 1. Spec

- TS §6.2 L1103: `POST /policies/import`, "Upload one `.bit` file", minimum role admin.
- TS §6.2 L1084: "Policy upload is not a sensitive action: an admin's API token may upload."
- TS §6.3 L1137: "`/policies/import` takes `multipart/form-data` with one file field, `file`."
- TS §6.3 L1138: "`.bit` 5 MB … Larger bodies get 413."
- TS §4.1 L522: "The manager ignores the client's file name. It parses and validates the upload in memory … The client's file name is kept only as metadata in `bit_import.file_name`."

## 2. Body cap (`app.py`)

- `BODY_CAP_CLASSES["bit"]` becomes `5 * MIB + 64 * 1024` (#99 (a): the file part is at most 5 MiB, plus a 64 KiB envelope allowance). Comment it with TS §6.3 L1138 and #99.
- Add `RouteCap("/api/v1/policies/import", "bit", BODY_CAP_CLASSES["bit"], after_auth=True)` to `ROUTE_BODY_CAPS`. With `after_auth`, the token and role check run before a byte of the body is read, so an unauthenticated client cannot make the manager buffer 5 MiB (the inventory route works the same way).
- No other entry changes; every other route keeps the 1 MiB `json` cap (REQ-037).

## 3. Route

```python
router = APIRouter()

@router.post(
    "/policies/import",
    response_model=ImportResult,
    responses=problem_responses([401, 403, 409, 413, 503]),
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {"type": "object", "required": ["file"], "additionalProperties": False,
                   "properties": {"file": {"type": "string", "format": "binary"}}}}}}},
)
async def import_policy(
    request: Request,
    principal: Annotated[Principal, Depends(require_role("admin"))],
    runtime: RUNTIME,
) -> ImportResult:
    body = await read_capped(request)                         # api/agent/bodies.py helper; 413 TooLarge
    part = parse_upload(request.headers.get("content-type", ""), body)   # 400 or 413
    outcome = await run_in_threadpool(runtime.catalog.upload, part.data, part.client_name,
                                      Actor(f"user:{principal.user_id}", principal.user_id))
    return ImportResult.from_outcome(outcome)
```

- `require_role("admin")` accepts an admin `bsu_` session or `bsk_` API token. A restricted admin session gets 403 `totp_enrolment_required` (M2 rule). There is no TOTP-session check: upload is not a sensitive action (TS §6.2 L1084), and no sink gate applies.
- Declare no body parameter, so FastAPI reads nothing before the dependency runs. `read_capped` is reused from `api/agent/bodies.py`; if the reviewer prefers, move it to `api/bodies.py` in this task (one more file is still within 5).
- The blocking work (lock, database, file write) runs in the thread pool and never on the event loop.
- `Retry-After` and every problem body follow the M2 problem machinery (`Problem`).

## 4. `parse_upload(content_type, body)`: in memory (#99 (c))

1. `python_multipart.multipart.parse_options_header(content_type)`: the type must be `multipart/form-data`, with a `boundary` of 1 to 70 bytes (RFC 2046). Anything else is 400 "The body must be multipart/form-data with one part named file."
2. `python_multipart.multipart.MultipartParser(boundary, callbacks)`, then `parser.write(body)` once and `parser.finalize()`. The callbacks are:
   - `on_part_begin`: count parts; a second part is 400 at once.
   - `on_header_field` and `on_header_value` (accumulated), `on_header_end`: store the header with its name lowercased; at most 16 headers of at most 8 KiB each, else 400.
   - `on_part_data(data, start, end)`: append `data[start:end]`; once more than `5 * MIB` bytes have arrived, raise the private `_PartTooLarge` → 413 `too_large` (TS §6.3 L1138), with no `bit_import` row (#99 (b)).
   - `on_end`: mark complete.
   No `UploadFile`, `File()`, `Form()` or `FormParser` is used. Those spool to disk above 1 MiB, and TS L522 wants the upload in memory.
3. After `finalize`, the result must be exactly one part, complete (`on_end` seen). Its `content-disposition` parsed with `parse_options_header` must be `form-data` with `name` exactly `file`. Otherwise 400. The part's own `Content-Type` is ignored. A `MultipartParseError` (or any `python_multipart` exception) is 400. A body missing its closing boundary is 400.
4. `client_name` (#99 (d)): the `filename` parameter of the disposition (bytes), decoded as UTF-8 with `errors="replace"`; then U+0000 to U+001F and U+007F replaced by U+FFFD; then cut to 255 characters. A missing name becomes `""`. `filename*` is ignored. The name is passed on only as metadata. It never reaches a path, a log line or a problem `detail`.
5. An empty file part (0 bytes) is **not** refused here. It is an import, rejected with BIT001 and recorded (REQ-150 (1)).

Every 400 detail is fixed text. None echoes the body, a header value or the file name (REQ-038 (2)).

## 5. Answers

| Case | Status | Body |
| --- | --- | --- |
| Imported (`success`) or rejected by a BIT rule (`rejected`) | 200 | `ImportResult` (#98 (d)) |
| Malformed multipart, wrong part or field, wrong type | 400 `invalid_request` | problem |
| No token, or a `bsa_` or `bse_` token | 401 `unauthorized` | problem (M2) |
| Viewer or operator; restricted admin | 403 `forbidden`; 403 `totp_enrolment_required` | problem |
| Live policy of that name in the server folder | 409 `policy_managed_on_server` | problem, detail "This policy is managed in the server folder; change its file there." |
| Body over 5 MiB + 64 KiB, or part over 5 MiB | 413 `too_large` | problem, `Connection: close` |
| Catalog start-up still running (#102 (d)) | 503 `about:blank` | detail "The catalog is starting; retry shortly.", `Retry-After: 10` |
| Database unavailable, or another internal error (#98 (j)) | 503 `about:blank` | the existing app handler |

`ImportResult` (Pydantic, `extra="forbid"`, exported in OpenAPI):
- `import_id: int`;
- `outcome: Literal["success", "rejected"]` (a manual import is never `skipped`);
- `policy_id: int | None`, `policy_name: str | None`, `policy_version: int | None`;
- `plugins_added: int`, `plugins_updated: int`, `plugins_retired: int`;
- `errors: list[FindingItem]`, where `FindingItem` is `{line: int | None, element: str | None, code: str, message: str}`, exactly as stored in `bit_import.errors`, warnings included (#110).

If `ImportOutcome.import_id` is None (the record transaction failed after a committed import), answer 503 `about:blank` "The import was stored but its record could not be written." and log it. The catalog change stands, and the next GET shows it.

## 6. OpenAPI and client

- The `openapi_extra` request body above, the `ImportResult` schema, and the problem responses. `_problem_openapi` in `app.py` adds the 400 automatically (the operation has a request body).
- Re-export `manager/openapi.json` (G6). The web client is regenerated in TASK-168 (PD-20). TASK-171 sends a `FormData` with one `file` entry through `openapi-fetch` with a `bodySerializer`.

## 7. Tests (TP-M7-23; tester file `manager/tests/test_policy_import_api_pg.py`; the security rows also go in `test_security_m7.py`)

1. An admin session and an admin `bsk_` each upload the SR §1.1 example: 200 `success`, `policy_version` 1, the file at `uploaded/policy-<id>.bit`, and one `bit_import` row with `imported_by` = that user and `file_name` = the client name.
2. A BIT fixture: 200 `rejected` with `errors` equal to the stored row; nothing on disk.
3. Caps: a 5,242,880-byte valid file is accepted. A 5,242,881-byte part is 413 with no row and no file. A 6 MiB body with `Content-Length` is refused unread; a chunked one stops after the crossing chunk. An unauthenticated 6 MiB body gets 401 before any body read (the token check is first: count the bytes the test server received).
4. Malformed requests, each 400 with fixed detail: a JSON body, no boundary, a 71-byte boundary, no closing boundary, two parts, a part named `files`, an extra text field, a 17th header, an 8 KiB + 1 header value.
5. Hostile client names (REQ-163 (1)): `../../etc/passwd`, `/abs.bit`, a name with NUL or CR LF, 5,000 characters, `<script>`, an RTL override, invalid UTF-8 bytes. The file lands only as `uploaded/policy-<id>.bit`; `file_name` holds the #99 (d) form; no name appears in any log line or problem detail.
6. A viewer and an operator get 403. A restricted admin gets 403 `totp_enrolment_required`. `bsa_` and `bse_` get 401.
7. A live server-folder name gives 409 `policy_managed_on_server`, with no row and one `policy.import_refused` entry.
8. A fake `CatalogService` raising the start-up refusal gives 503 with `Retry-After: 10`.
9. No spooling: `tempfile.SpooledTemporaryFile`, `tempfile.NamedTemporaryFile` and `tempfile.TemporaryFile` are patched to fail during the upload, and the upload still succeeds.
10. `GET /api/v1/agents` with a 2 MiB JSON body still gets 413 (the `json` cap is unchanged).
11. G6: the export is byte-identical after a re-run, and the multipart schema has exactly the `file` property.

Plants: CHK-M7-324 (the cap entry removed, or raised past 5 MiB + 64 KiB), -345 (`require_role("operator")`), -358 (the client name used as the stored path) must turn rows 3, 6 and 5 red.

## 8. Budget

About 170 hand-written lines (`policy_import.py` about 150, `app.py` about 10, `__init__.py` 2), plus the regenerated `openapi.json`.
