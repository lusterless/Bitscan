# TASK-164 TEST: PASS

Tester: tester-m7d, 2026-10-28. REQ-172 (1) to (4), REQ-174 (2), REQ-177 (rebuild rows). Spec: TS §6.2 L1084, L1105, L1106, §4.2 L538 to L540, §5.3 L1051, §6 L1056, §6.3; #1, #20, #98 (f), (g), (i), (j), #101 (`bits.rebuild`, `policy_rebuilt`), #102 (d); decisions 2026-10-28 "TASK-157 rulings" (with `not_imported`) and the crash-window ruling (`removed_leftovers`; a deleted policy is never revived by itself).

Files under test: `bm/api/user/rebuild.py` (hash prefix 60416f237ed9c587), the registration in `bm/api/user/__init__.py`, and `manager/openapi.json` from the combined W8 regeneration.

New tester file: `manager/tests/test_rebuild_api_pg.py` (41 tests), on the shared `manager/tests/catalog_api.py` environment. The rebuild runs on the real catalog worker over a temporary bits folder.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` = the tree under test) | the TASK-162 r0 command, which includes `tests/test_rebuild_api_pg.py`, `tests/test_openapi.py` and `tests/test_invariants_m3.py` | 586/588 passed, 2 failed (`test_app_hardening.py`, TASK-162's cap value, fixed there; 2/2 and 53/53 on re-run), 0 errors, 0 skipped. Of these, 41/41 are in this file |
| plants (W, `-n 0`, throwaway copy, file restored after each) | `pytest tests/test_rebuild_api_pg.py -k <rows>` | 9/9 plants red |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every subprocess imported the tree under test through `PYTHONPATH`.
- No container was left behind.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-276 REQ-172 (1) | APP | W | r0 | PASS | **Setup:** the server folder holds `good.bit`, `bad.bit` (BIT003) and `gone.bit` (2 plugins), imported at start-up; one live upload; one policy deleted through the route whose `uploaded/policy-<id>.bit` is then re-planted (an interrupted delete's leftover); `gone.bit` removed; and `uploaded/copy.bit` holding the server policy's name. **While another session holds the catalog lock:** an admin TOTP session gets 202 with exactly `{task_id}` (a hyphenated lowercase UUID). `GET /tasks/{id}` with an admin `bsk_` shows exactly `{task_id, kind: rebuild, state: running, requested_by: <admin>, result: null, started_at (RFC 3339 Z), finished_at: null}`, in that order. **After the lock is released, the task ends `succeeded`** (#20, with a rejected file), and `finished_at` ≥ `started_at`. **`result`** has exactly `files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported`. Each `files` item has `source_file, import_id, outcome, policy_id, policy_version`; the items are `good.bit` (success, its id), `bad.bit` (rejected, null id and version) and `uploaded/policy-<upl>.bit`. `deleted_policy_ids` is `[gone]`, `removed_leftovers` is `["uploaded/policy-<del>.bit"]`, `not_imported` is `["uploaded/copy.bit"]`, and `plugins_retired` ≥ 2. **Effects:** the leftover file is gone and its policy stays deleted, with no import row; the gone policy's `source_file` is `deleted/<id>`. The new `bit_import` rows are exactly the `files` import ids, all mode `rebuild` and `imported_by` the admin. There is one `bits.rebuild` entry (actor `user:<id>`, `alert_kind` `policy_rebuilt`, `removed_leftovers` listed), and `policy_rebuilt` rises by 1. A POST with no body, and one with `{}`, each give 202 and `succeeded`, with `requested_by` stored | 2026-10-28 |
| CHK-M7-276 REQ-172 (2) | APP | W | r0 | PASS | Admin `bsk_`: 403 `totp_session_required`. Restricted admin: 403 `totp_enrolment_required`. An unverified admin session: 403. Operator and viewer sessions: 403 `forbidden`. Operator and viewer `bsk_`: 403. No `task` row is created in any of these cases. Sink gate: at 14:59 a rebuild starts and succeeds; at 15:00, 503 `audit_sink_unavailable` with no task row, while `GET /tasks` still answers; after the drain a rebuild succeeds | 2026-10-28 |
| CHK-M7-276 503 | APP | W | r0 | PASS | Before the start-up ends: 503 `about:blank`, `Retry-After: 10`, the fixed #102 (d) detail, and no task row. With no catalog service: 503 `about:blank` | 2026-10-28 |
| CHK-M7-276 REQ-172 (3) | APP | W | r0 | PASS | Admin `bsk_` and session: 200. Operator and viewer, each with a session and with `bsk_`: 403 `forbidden`, with no task data in the body. A CLI task (`requested_by` NULL) reads `requested_by: null`, `running`, `started_at` equal to the stored time in Z form. Unknown, nil and max UUIDs: 404 `not_found`. `abc`, 32 hex digits, `{…}`, `urn:uuid:…`, one digit too many or too few, a misplaced hyphen, `g`, underscores, `1` and `-1`: 400 `invalid_request`. An upper-case id gives 200 with the lowercase id, never 500 | 2026-10-28 |
| CHK-M7-276 REQ-172 (4) | APP | W | r0 | PASS | A rebuild is started, its worker held inside the rebuild call, and the manager restarted (service stopped, a new start-up sequence run). The task reads `failed` with `result` exactly `{error: <non-empty fixed text without the id>}` and `finished_at` set (REQ-165 (2), #98 (g)) | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | On both the POST and the GET, `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized`, with no task row | 2026-10-28 |
| CHK-M7-276 OpenAPI | CODE | W | r0 | PASS | The POST has no request body or parameters; 202 `RebuildStarted` with only `task_id` (format uuid); 401, 403 and 503. The GET has its path parameter with a pattern; 200 `TaskItem` with the #98 (g) keys in order; `result` refers to a schema with exactly the five result keys; `files` items have the five file keys in order; 400, 401, 403 and 404 are problem+json. G6 byte-identical (`test_openapi.py`); G34 route walk passes (`test_invariants_m3.py`) | 2026-10-28 |
| CHK-M7-342 | APP | W | plant: POST with `require_role("admin")` | PASS (red) | 2 failed: `test_an_admin_api_token_is_refused_totp_session_required` and the sink-gate row | 2026-10-28 |
| CHK-M7-344 | APP | W | plant: `require_totp_session(sink_gate=False)` | PASS (red) | 1 failed: `test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains` | 2026-10-28 |
| CHK-M7-164-role | APP | W | plant: POST `require_totp_session("operator")` | PASS (red) | 1 failed: `test_operator_and_viewer_cannot_start_a_rebuild[operator-session]` | 2026-10-28 |
| CHK-M7-164-get-role | APP | W | plant: GET `require_role("viewer")` | PASS (red) | 4 failed: every `test_only_an_admin_reads_a_task` case | 2026-10-28 |
| CHK-M7-164-auth | APP | W | plant: both dependencies replaced by a fixed admin principal | PASS (red) | 10 failed: every wrong-group case on both routes | 2026-10-28 |
| CHK-M7-164-uuid | APP | W | plant: the UUID path pattern removed | PASS (red) | 11 failed: every non-UUID case | 2026-10-28 |
| CHK-M7-164-leftovers | APP | W | plant: `removed_leftovers` dropped from `TaskResult` | PASS (red) | 2 failed: the full rebuild row and the OpenAPI row | 2026-10-28 |
| CHK-M7-164-not-imported | APP | W | plant: `not_imported` dropped from `TaskResult` | PASS (red) | 2 failed: the full rebuild row and the OpenAPI row | 2026-10-28 |
| CHK-M7-164-starting | APP | W | plant: `Retry-After` dropped | PASS (red) | 1 failed: the start-up row | 2026-10-28 |
| CHK-M7-164-202 | APP | W | plant: `status_code=200` | PASS (red) | 3 failed: the full rebuild row and both body rows | 2026-10-28 |

## Acceptance

TASK-164 row: "Through the API on PostgreSQL: REQ-172 (1)–(4) hold."
- REQ-172 (1): CHK-M7-276 REQ-172 (1).
- REQ-172 (2): CHK-M7-276 REQ-172 (2) and 503.
- REQ-172 (3): CHK-M7-276 REQ-172 (3).
- REQ-172 (4): CHK-M7-276 REQ-172 (4).
- `bsa_`/`bse_` 401: CHK-M7-282. G6 and G34 hold.

Every security plant went red: API token (CHK-M7-342), sink gate (CHK-M7-344), roles on both routes, token group, UUID check.

## Notes (no defect)

- **REQ-172 (4):** a real process kill cannot be done in-process. Instead the worker's rebuild call is held on an event, so the task stays `running` with no catalog change, and the service is stopped and started again. The `failed` state comes from the real start-up sequence (`fail_running_tasks`).
- **`running` is observed deterministically** by holding `pg_advisory_lock(hashtext('catalog'))` from a second session. `start_task` does not take the lock, so the 202 arrives at once.
- **`GET /tasks/{id}` accepts upper-case hex.** The pattern allows `A-F`, and the id is returned lowercase. The spec only says ids are UUID strings.
