# TASK-074 REVIEW: `PUT /api/v1/agent/{id}/inventory`

Reviewer: reviewer. Date: 2026-10-23. REQ-076, REQ-066. Spec: TS §6.1 L1066 (`?job_id=` completes an inventory job), L1072 (the manager re-checks every cap), §3.4 L239 (at most one upload without `job_id` per agent per 10 minutes, 429), L240 (limits; refused uploads are 413 or 422 and audit-logged), L241–L243 (ingest), L244 (a dispatched job whose upload is refused with 413 or 422 fails; a later upload with that `job_id` is still stored as an unscheduled snapshot), §6.5 L1186, §6.3 L1138 (10 MB gzip / 64 MB decompressed); #72 (a)–(f). Rulings (`work/decisions.md`, 2026-10-23):
- TASK-073/074 may touch `app.py` (`RouteCap` registry, documented self-read bodies);
- option (a) for the OpenAPI 422: a route-declared 422 stays, FastAPI's validation 422 goes;
- TASK-048 r1 carry-over: CHK-M3-016 validates `raw` against `components/schemas/RawValue` with the whole document as root;
- the tester's two notes are accepted by the lead.

Inputs:
- `work/reports/TASK-074-impl.md`;
- `work/reports/TASK-074-test.md` (PASS: `manager/tests/test_inventory_api_pg.py` and the updated shared suites, 148 tests; 22 of 22 plants red, CHK-M3-358, -360 and -361 included).

Files reviewed:
- `manager/bitscan_manager/services/inventory/upload.py` (new, about 140 lines);
- `manager/bitscan_manager/api/agent/inventory.py` (new, 87 lines);
- `manager/bitscan_manager/api/agent/__init__.py` (`new_packages` window, router include, `InventoryBody` in `documented_request_bodies`);
- `manager/bitscan_manager/app.py` (the inventory `RouteCap`; the OpenAPI 422 rule);
- `manager/openapi.json`;
- the tester-e tests.

The route also uses `agent_uuid()` and `content_coding()` in `api/agent/dependencies.py`. They are part of TASK-083, already in this working tree, and are reviewed under TASK-083. Here I checked only that the route calls them as ruled: hyphenated UUIDs only, and case-insensitive coding.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent routes). This is the first one; the user's second approval is still needed.

## What was checked

- **Order and caps (REQ-066).**
  1. `current_agent`.
  2. `?job_id` must be a hyphenated UUID (400 otherwise) and is set as the log context `job_id`.
  3. `Content-Encoding` must be gzip, else 400 plus one `agent.inventory_refused {reason: not_gzip}` entry, with the job left to the sweep (#72 (a), (c)).
  4. `read_capped` under the after-auth `RouteCap` (inventory, 10 MiB): 0 bytes are read before a 401 (an 11 MiB body with a bad token gets 401, no entry, job untouched). Over 10 MiB as sent gets 413 `too_large` with `Connection: close` and one entry, and a dispatched job it named is failed.
- **`job_id` cases (#72 (d)).** `classify` runs before any decoding:
  - this agent's `dispatched` inventory job completes, through `JobRepo.complete` in the ingest's transaction, effective only while still dispatched;
  - `failed` or `completed` is stored as unscheduled, with the job unchanged (TS §3.4 L244);
  - unknown, another agent's, compliance, `queued`, `expired`, `cancelled` or `running` gets 409 `job_not_acceptable` with one entry, and nothing is decoded or stored.
- **10-minute window (#72 (e), REQ-076 (3)).** Only the unscheduled cases ask `allow_unscheduled_inventory`, before decoding. A refusal is 429 `rate_limited` with `Retry-After` and nothing is decoded. A dispatched job is exempt. 9 min 59 s gives 429 and 10 min gives 204.
- **Decode and ingest.**
  - `decode_inventory` (TASK-060) runs in the threadpool. A refusal is answered with `exc.status` and **`exc.type`**, never the internal `reason`, and writes one entry `{reason, status, job_id}`. A 413 or 422 fails a dispatched job, while a 400 leaves it to the sweep.
  - `ingest` (TASK-064) runs with the once-per-process burst window and `tx.on_commit`. `AgentGone` gives 401 `token_revoked` and rolls back.
  - The answer is 204 with no body.
  - Audit details never hold a body, a package or `raw`.
- **Tester-e's notes (lead accepted). I agree with both.**
  1. A body refused before decoding (413 as sent, `not_gzip`) does not start the window. #72 (e) starts it "when such an upload reaches decoding", so the literal reading is right, and such refusals cost no decompression.
  2. A sweep that fails the job between `classify` and the ingest leaves the job `failed` while the upload is stored. That is exactly TS §3.4 L244's "a later upload carrying that `job_id` is still stored".
- **OpenAPI (G6, REQ-060 (1)).**
  - My re-export is byte-identical.
  - The operation documents 204, 400, 401, 403, 409, 413, 422, 429 and 503. Its `requestBody` refers to `#/components/schemas/InventoryBody`.
  - The inventory upload is the **only** operation with a 422, and `HTTPValidationError` appears nowhere (option (a)).
  - `InventoryBody`, `OsInfo`, `PackageItem` and `RawValue` are present, with `os_info.uptime_s` at the exact `maximum: 9007199254740991`.
  - The TASK-048 carry-over is met: CHK-M3-016 validates the `raw` fixtures, nested NUL keys and values included, against `RawValue` with the whole `openapi.json` as the validation root.
- **Security invariants (REQ-088).** No route or parameter disables or skips inventory. Nothing is logged except by reason word. No connection besides the database.
- **Tests (my run, Windows).** `test_inventory_api_pg.py`, `test_contract_agent.py`, `test_body_caps.py`, `test_agent_auth_pg.py`, `test_login.py`, `test_openapi.py`, `test_inventory_decode.py` and `test_inventory_ingest.py`: 771 passed, 173 skipped (PostgreSQL; run in WSL by tester-e), 0 failed. The shadowed body-cap tests and the narrowed 422 contract are fixed. ruff and format are clean, and `mypy --strict` is clean on the whole tree (207 files).

## Findings

None.

## Notes

- **M6.** Decoding runs in the 40-thread pool. Concurrent large valid uploads cost several hundred MiB each while parsing (TASK-060 review). Per agent this is bounded by the 10-minute window plus its dispatched jobs. Measure it in the load test.
- **TASK-080 (README).** Document the upload contract: gzip required, the caps and statuses, the `job_id` cases, and the 10-minute limit.
