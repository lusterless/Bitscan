# TASK-162 TEST: PASS

Tester: tester-m7d, 2026-10-28. REQ-170 (1) to (5), REQ-163 (1), (3), (5), REQ-174 (2), REQ-177 (upload rows). Spec: TS §6.2 L1103, L1084 (upload is not sensitive: an admin `bsk_` may upload; no TOTP session, no sink gate), §6.3 L1137 and L1138, §6 L1056, §4.1 L522; #57, #98 (d) and (j), #99 (a) to (e), #101, #102 (d); plan `work/plans/TASK-162.md` §2 to §5; the TASK-155 carry (a stale temp file gives 503). Lead ruling 2026-10-28: the parser's decoded `filename` value is the #99 (d) input.

Files under test: `bm/api/user/policy_import.py`, `bm/app.py` (cap entry), `bm/api/user/__init__.py`, `manager/openapi.json`. Product hashes tested (first 16 hex): `policy_import.py` 832b2584a7491aff, `app.py` 8c137ba87e3332dd, `openapi.json` 2eacec4e800031e4.

New tester files:
- `manager/tests/catalog_api.py`, a shared environment for TASK-162 to 164. It runs on a module-own PostgreSQL (`own_migrated_server`) with the real `CatalogService`, start-up sequence, sink gate (switchable sink behind the M2 shipper), auth and rate limiter, plus a temporary bits folder. Only the watcher is stubbed (it never opens).
- `manager/tests/test_policy_import_api_pg.py`, 91 tests.

One existing test was updated:
- `manager/tests/test_app_hardening.py`: the `bit` class value is now `5 * MIB + 64 * 1024` and its "+1" refusal case moved with it. Both follow #99 (a) and plan §2, the approved change in this task. The file part stays capped at 5 MiB, and the new suite tests that cap at the route. No gate was lowered.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH=/root/bstest-m7d/manager`) | `pytest tests/test_policy_import_api_pg.py tests/test_policy_delete_api_pg.py tests/test_rebuild_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_body_caps.py tests/test_policies_api_pg.py tests/test_imports_api_pg.py tests/test_app.py tests/test_app_hardening.py tests/test_module_imports.py` | 586/588 passed, 2 failed, 0 errors, 0 skipped |
| r0 failures (test bug) | `test_app_hardening.py::test_cap_classes_are_the_spec_values`, `::test_registry_refuses_bad_entries_at_app_creation[bit+1]`. Expected the old `bit` value of 5 MiB; actual 5 MiB + 64 KiB (#99 (a)) | fixed in the test (above) |
| r1 (W) | the two failing node ids | 2/2 passed |
| r2 (W) | `pytest tests/test_app_hardening.py` (shares the cap fixtures) | 53/53 passed |
| plants (W, `-n 0`, throwaway copy `/root/bstest-m7d-mut`, each file restored after) | `pytest tests/test_policy_import_api_pg.py -k <rows>` | 16/16 plants red (rows below) |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every run set `PYTHONPATH` to the tree under test, so the `db migrate` subprocess (the only console-script call) imported that tree and not the shared venv's editable install. I checked this: a subprocess under the same environment reports `/root/bstest-m7d/manager/bitscan_manager`. Plants ran with `PYTHONPATH=/root/bstest-m7d-mut/manager`. No re-run is needed for the shared-venv hazard.
- No test container was left behind (`docker ps -a` shows none of mine).

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-262 (1) | APP | W | r0 | PASS | REQ-170 (1), #98 (d). Admin session and admin `bsk_` each get 200; the keys are exactly `import_id, outcome, policy_id, policy_name, policy_version, plugins_added, plugins_updated, plugins_retired, errors` in that order, with integer ids, version 1, 2 added, 0 updated, 0 retired and `errors` `[]`. The `bit_import` row has mode `manual`, outcome `success`, `imported_by` = the caller, the client `file_name` and the file SHA-256. The file is stored only as `uploaded/policy-<id>.bit`, byte-identical, and `source_file`/`source_sha256` match. There is one `policy.import` entry (actor `user:<id>`, target `policy:<id>`, `alert: true`), and `policy_imported` rises by 1. The SR §1.1 example uploads; the same bytes again give `success` (manual never skips) with the version unchanged; a changed file gives version + 1, same id, and the stored file is replaced | 2026-10-28 |
| CHK-M7-262 (1) rejected | APP | W | r0 | PASS | `content/bit003-on.bit` gives 200 `rejected`, policy fields null, `errors` equal to the stored row (four keys each), mode `manual`, nothing on disk, `policy_import_rejected` + 1. BIT003 and BIT016 come back together in line order. `warnings-only.bit` gives `success` with BIT101 and BIT103 in `errors` (#110). `rm -rf /tmp/x` gives BIT102 with nothing stored. An empty part gives a recorded BIT001 rejection | 2026-10-28 |
| CHK-M7-262 REQ-163 (3) | APP | W | r0 | PASS | A rejected re-upload of a live policy leaves the catalog checksums, jobs, schedules and tasks unchanged, adds only its `bit_import` row, and leaves `uploaded/policy-<id>.bit` byte-identical | 2026-10-28 |
| CHK-M7-262 REQ-163 (5) | APP | W | r0 | PASS | After the start-up reconcile imports a server-folder file, an upload with that `PolicyName` gets 409 `policy_managed_on_server` with the fixed detail. There is no `bit_import` row, no file and no catalog change. Exactly one audit entry is written (`policy.import_refused`, actor `user:<id>`, no alert), and the alert counters are unchanged (#99 (e)) | 2026-10-28 |
| CHK-M7-262 REQ-170 (2) | APP | W | r0 | PASS | A valid file of exactly 5,242,880 bytes gives `success` and is stored byte-identical. 5,242,881 bytes gives 413 `too_large` with `Connection: close`, no `bit_import` row, no audit entry and nothing on disk (#99 (b)). A body of exactly 5,308,416 bytes (small part plus an epilogue) gives 200; 5,308,417 gives 413 with no row. A 6 MiB `Content-Length` gives 413 with 0 bytes pulled; a 6 MiB chunked body gives 413 after the crossing chunk (5,308,416 < pulled ≤ + 64 KiB) | 2026-10-28 |
| CHK-M7-262 token first | APP | W | r0 | PASS | No token, `bsa_`, `bse_`, a garbage `bsk_`, viewer `bsk_` and operator `bsk_`, each with a 6 MiB body declared by `Content-Length` or sent chunked: 401 or 403 with **0 body bytes pulled** (raw ASGI receive counter) | 2026-10-28 |
| CHK-M7-262 other caps | APP | W | r0 | PASS | `PATCH /policies/{id}` with a 1 MiB + 1 JSON body gives 413. `POST /scans`, `POST /policies/rebuild` and `POST /users` with a 2 MiB body give 413. The policy is unchanged | 2026-10-28 |
| CHK-M7-262 REQ-170 (3) | APP | W | r0 | PASS | 23 malformed bodies each give 400 `invalid_request` with exactly the fixed detail "The body must be multipart/form-data with one part named file.": a JSON body, `text/plain`, `multipart/mixed`, no Content-Type, no boundary, an empty boundary, a 71-byte boundary, the wrong boundary, no closing boundary, two `file` parts, an extra field before or after, a part named `files` or `FILE`, no Content-Disposition, `attachment`, no `name`, 17 headers, an 8,193-byte header value, no parts, an empty body, garbage, and a raw CR in the filename. A canary placed in the body and in the file name is in neither the response nor any log record (`canary.sweep`). There is no `bit_import` row, no audit entry and no file. Accepted edges (200 `success`): a 70-byte boundary, `Multipart/Form-Data` with a quoted boundary, `Form-Data` disposition, 16 headers, an 8,192-byte header value, the part's own `Content-Type: image/png` ignored, no part Content-Type, an epilogue. A standard `httpx` `files=` upload works, also with CR, LF, `"`, NUL and `../../x` names | 2026-10-28 |
| CHK-M7-262 REQ-163 (1) | APP | W | r0 | PASS | Each of the 23 `bits/tests/hostile_names.json` names without a raw CR (names and raw-byte hex entries: `../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, 5,000 characters, NUL, LF, `<script>`, U+202E, `C:\Windows\x.bit`, `con.bit`, `.tmp-1-<64 zeros>`, `policy-1.bit`, empty, `  .bit`, BEL, DEL, 300 × é, `ff fe`, `c3 28`, `ed a0 80`) is uploaded with a fresh policy. The bits tree afterwards is exactly `{uploaded/policy-<id>.bit: data}`. `file_name` equals the #99 (d) form computed by the test (UTF-8 with replacement, C0 and DEL to U+FFFD, 255 characters), with no control character, and `source_file` is `uploaded/policy-<id>.bit`. No name over 6 characters reaches a log line. A missing name is stored as `""`. Per the lead ruling, `C:\Windows\x.bit` is stored as `x.bit` and `a\"b.bit` as `a"b.bit` | 2026-10-28 |
| CHK-M7-262 REQ-170 (4) | APP | W | r0 | PASS | Operator and viewer, each with a session and with `bsk_`: 403 `forbidden`, nothing changed and no audit entry. An admin without TOTP (restricted session, and API token): 403 `totp_enrolment_required`. An admin `bsk_` uploads during a 16-minute sink outage (upload is not sensitive, L1084) | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized` problem+json, with nothing changed | 2026-10-28 |
| CHK-M7-262 503 | APP | W | r0 | PASS | A catalog service whose start-up has not ended gives 503 `about:blank`, `Retry-After: 10`, detail "The catalog is starting; retry shortly.", with no row and no file; with no token it still gives 401 first. No catalog service gives 503 `about:blank`. A stale `uploaded/.tmp-<id>-<sha>` gives 503 `about:blank` "The policy file could not be stored; retry shortly.", no `bit_import` row (#98 (j)), the planted file untouched, the stored file still v1, and the policy row unchanged | 2026-10-28 |
| CHK-M7-262 in memory | APP | W | r0 | PASS | `tempfile.SpooledTemporaryFile`, `TemporaryFile`, `NamedTemporaryFile`, `mkstemp`, `mkdtemp`, `starlette.formparsers.SpooledTemporaryFile`, `python_multipart.FormParser`, `File` and `Request.form` are all patched to raise. A 2 MiB upload still gives `success` | 2026-10-28 |
| CHK-M7-262 REQ-170 (5) | CODE | W | r0 | PASS | The request body is `multipart/form-data`, required, with exactly `file: {type: string, format: binary}`, `required: [file]` and `additionalProperties: false`, and no parameters. 400, 401, 403, 409, 413 and 503 are problem+json. `ImportResult` has the #98 (d) keys in order, `additionalProperties: false`, and `outcome` enum `success`/`rejected` | 2026-10-28 |
| G6 | CODE | W | r0 (`test_openapi.py`) | PASS | A fresh export is byte-identical to `manager/openapi.json`, and two exports are byte-identical | 2026-10-28 |
| CHK-M7-281 | APP | W | r0 (`test_invariants_m3.py`) | PASS | The route walk passes with the M7 operations | 2026-10-28 |
| CHK-M7-324 (a) | APP | W | plant: the `/api/v1/policies/import` `RouteCap` removed (back to 1 MiB) | PASS (red) | 3 failed: the exactly-5-MiB part, the exact body cap, the 6 MiB refusal | 2026-10-28 |
| CHK-M7-324 (b) | APP | W | plant: `bit` class raised to 6 MiB | PASS (red) | 2 failed: the body cap + 1 accepted; the 6 MiB `Content-Length` not refused unread | 2026-10-28 |
| CHK-M7-324 (c) | APP | W | plant: part cap `MAX_BIT_BYTES + 1` | PASS (red) | 1 failed: `test_a_part_one_byte_over_5_mib_is_413_with_no_row_and_nothing_on_disk` | 2026-10-28 |
| CHK-M7-345 | APP | W | plant: `require_role("operator")` | PASS (red) | 3 failed: operator session and `bsk_` 403 rows, and the operator token-first row | 2026-10-28 |
| CHK-M7-162-auth | APP | W | plant: the auth dependency replaced by a fixed admin principal | PASS (red) | 16 failed: every wrong-group 401, every token-first row, operator and viewer 403, the admin-without-TOTP rows | 2026-10-28 |
| CHK-M7-162-first | APP | W | plant: a dependency reads `request.body()` before the auth dependency | PASS (red) | 6 failed: every `test_no_body_byte_is_read_before_the_token_and_role_check` case | 2026-10-28 |
| CHK-M7-162-echo | APP | W | plant: the 400 detail appends the body | PASS (red) | 22 failed: the malformed cases (canary found) | 2026-10-28 |
| CHK-M7-162-log | APP | W | plant: `log.warning("upload from %s", client_name)` | PASS (red) | 16 failed: every hostile name over 6 characters and the canary row | 2026-10-28 |
| CHK-M7-358 | APP | W | plant: `uploads.py` names the stored file after the client name (sanitised to stay in the folder, a harmless payload) | PASS (red) | 21 failed: both admin-upload rows and the hostile-name rows | 2026-10-28 |
| CHK-M7-162-spool | APP | W | plant: `await request.form()` (Starlette's spooling parser) | PASS (red) | 1 failed: `test_the_upload_is_parsed_in_memory` | 2026-10-28 |
| CHK-M7-162-case | APP | W | plant: `kind.lower()` dropped | PASS (red) | 1 failed: `test_the_accepted_edges_of_the_multipart_rules` | 2026-10-28 |
| CHK-M7-162-oserror | APP | W | plant: the `OSError` → 503 branch removed | PASS (red) | 1 failed: the stale-temp row | 2026-10-28 |
| CHK-M7-162-starting | APP | W | plant: `Retry-After` dropped from the start-up 503 | PASS (red) | 1 failed: the start-up row | 2026-10-28 |
| CHK-M7-162-409 | APP | W | plant: `PolicyManagedOnServer` mapped to 400 | PASS (red) | 1 failed: the server-folder row | 2026-10-28 |
| CHK-M7-162-sensitive | APP | W | plant: `require_totp_session()` on the upload (over-restrictive) | PASS (red) | 2 failed: the admin `bsk_` upload and the sink-outage upload | 2026-10-28 |

## Acceptance

TASK-162 row: "Through the API on PostgreSQL: REQ-170 (1)–(5) and REQ-163 (1) and (5) hold; nothing is spooled to disk while parsing (a `tempfile` spy); every other route keeps its 1 MiB cap."
- REQ-170 (1): CHK-M7-262 (1), rejected.
- REQ-170 (2): CHK-M7-262 REQ-170 (2), token first.
- REQ-170 (3): CHK-M7-262 REQ-170 (3).
- REQ-170 (4): CHK-M7-262 REQ-170 (4), CHK-M7-282.
- REQ-170 (5): CHK-M7-262 REQ-170 (5), G6.
- REQ-163 (1): CHK-M7-262 REQ-163 (1).
- REQ-163 (5): CHK-M7-262 REQ-163 (5).
- REQ-163 (3) is also held: CHK-M7-262 REQ-163 (3).
- Spool spy: CHK-M7-262 in memory. Other caps: CHK-M7-262 other caps.

Every security row has a plant that went red: RBAC (CHK-M7-345), token type (auth plant), token before body, body cap (CHK-M7-324 a to c), no echo, no log, client name as path (CHK-M7-358).

## Notes (no defect)

- **python-multipart's reading of `filename`:** it drops an IE-style Windows path (`C:\Windows\x.bit` → `x.bit`) and unescapes quoted pairs. The lead ruled this conforming on 2026-10-28 (RFC 7578 §4.2), and the tests expect it.
- **A preamble before the first boundary is refused with 400.** RFC 2046 allows one, but #99 (c) does not ask for it, browsers do not send one, and the refusal is safe. An epilogue after the closing boundary is accepted.
- **A raw CR inside the part header** (for example in the filename) is malformed multipart and gets 400. Standard clients percent-encode CR, LF and `"` (httpx sends `%0D`), and those names are stored as metadata only.
- **`test_security_m7.py` (TP-M7-30) is not written here.** It belongs to the M7 gate. The upload security rows are in `test_policy_import_api_pg.py`, ready to be referenced.
