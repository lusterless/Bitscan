# TASK-163 TEST: PASS

Tester: tester-m7d, 2026-10-28. REQ-171 (1) to (4); REQ-167 (1) to (3) seen through the route; REQ-174 (2); REQ-177 (delete rows). Spec: TS §6.2 L1104 (admin, TOTP session), L1084, §4.3 L550, §5.3 L1051, §6 L1056; #1 (agreed: also refused during a sink outage), #9, #98 (e) and (k), #101 (`policy.delete`, `policy_deleted`), #102 (d).

File under test: `bm/api/user/policies.py` (the `DELETE /{id}` route; hash prefix 87b774b41036de02), plus `manager/openapi.json` from the combined W8 regeneration.

New tester file: `manager/tests/test_policy_delete_api_pg.py` (27 tests), on the shared `manager/tests/catalog_api.py` environment (see `work/reports/TASK-162-test.md`). That environment has the real catalog service and start-up, the real sink gate and auth, and a module-own PostgreSQL. Fixture scans, jobs and schedules are written as owner.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` = the tree under test) | the TASK-162 r0 command, which includes `tests/test_policy_delete_api_pg.py`, `tests/test_policies_api_pg.py`, `tests/test_openapi.py` and `tests/test_invariants_m3.py` | 586/588 passed, 2 failed (`test_app_hardening.py`, TASK-162's cap value, fixed there; 2/2 and 53/53 on re-run), 0 errors, 0 skipped. Of these, 27/27 are in this file and every `test_policies_api_pg.py` test passed |
| plants (W, `-n 0`, throwaway copy, file restored after each) | `pytest tests/test_policy_delete_api_pg.py -k <rows>` | 7/7 plants red |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every subprocess (`db migrate`) imported the tree under test through `PYTHONPATH`, so the shared-venv editable install was not used.
- No container was left behind.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-271 REQ-171 (1) 204 / REQ-167 (1) | APP | W | r0 | PASS | Setup: a policy uploaded through the route, with owner-written jobs `queued`, `dispatched` and `running` and two schedules (one enabled). An admin TOTP session gets 204 with an empty body. Then: the row is kept with `deleted_at` set and `source_file` `deleted/<id>`; every plugin is `retired`; only the queued job is `cancelled`, with `finished_at` set, while `dispatched` and `running` are unchanged; both schedules have `enabled = false`; `uploaded/policy-<id>.bit` is gone; exactly one `policy.delete` entry is written (actor `user:<id>`, target `policy:<id>`, `alert: true`, `alert_kind` `policy_deleted`); `bitscan_alerts_total{policy_deleted}` rises by 1. An unrelated policy is unchanged | 2026-10-28 |
| CHK-M7-271 REQ-167 (3) | APP | W | r0 | PASS | After the delete, `GET /policies?limit=500` no longer lists it, and `GET /policies/{id}` gives 200 with `deleted_at` and `source_file` `deleted/<id>` (#9). A re-upload of the same name revives the same `policy_id` | 2026-10-28 |
| CHK-M7-271 REQ-171 (1) refusals | APP | W | r0 | PASS | Each refusal leaves the catalog, `bit_import`, task, job and schedule checksums and the bits tree unchanged. Admin `bsk_`: 403 `totp_session_required`. An admin session without TOTP verification: 403. Operator and viewer sessions: 403 `forbidden`. Operator and viewer `bsk_`: 403 | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized`, with nothing changed | 2026-10-28 |
| CHK-M7-271 REQ-171 (2) | APP | W | r0 | PASS | 14:59 into a sink outage the delete is still allowed (204). At 15:00, 503 `audit_sink_unavailable`, nothing changed and the policy not deleted. After the queue drains, the same delete gives 204 (#1) | 2026-10-28 |
| CHK-M7-271 REQ-171 (3) | APP | W | r0 | PASS | A server-folder policy (imported by the start-up reconcile) gives 409 `policy_managed_on_server` with the fixed detail. Nothing changed, the server file is still there, and there is no `policy_deleted` alert | 2026-10-28 |
| CHK-M7-271 REQ-171 (4) | APP | W | r0 | PASS | Unknown ids (max + 1000, `0`, 2^63 − 1, 2^63, 10^19): 404 `not_found` with nothing changed. A second delete of a deleted policy: 409 `conflict` with no second alert. `abc`, `+1`, `-1`, `1.0`, `1e3`, ` 1`, `0x10` and 21 digits: 400 `invalid_request` | 2026-10-28 |
| CHK-M7-271 503 | APP | W | r0 | PASS | Before the start-up ends: 503 `about:blank`, `Retry-After: 10`, the fixed #102 (d) detail, nothing changed. With no catalog service: 503 `about:blank` | 2026-10-28 |
| CHK-M7-271 OpenAPI | CODE | W | r0 | PASS | 204 with no content; 400, 401, 403, 404, 409 and 503 as problem+json; no request body. G6 byte-identical (`test_openapi.py`) | 2026-10-28 |
| CHK-M7-341 | APP | W | plant: `TOTP_ADMIN` → `require_role("admin")` | PASS (red) | 2 failed: `test_an_admin_api_token_is_refused_totp_session_required` and the sink-gate row | 2026-10-28 |
| CHK-M7-343 | APP | W | plant: `require_totp_session(sink_gate=False)` | PASS (red) | 1 failed: `test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains` | 2026-10-28 |
| CHK-M7-346 | APP | W | plant: `require_totp_session("operator")` | PASS (red) | 1 failed: `test_operator_and_viewer_are_refused[operator-session]` | 2026-10-28 |
| CHK-M7-163-auth | APP | W | plant: the auth dependency replaced by a fixed admin principal | PASS (red) | 10 failed: every wrong-group 401, the API-token row, every operator and viewer row | 2026-10-28 |
| CHK-M7-163-409 | APP | W | plant: `PolicyAlreadyDeleted` mapped to 404 | PASS (red) | 1 failed: `test_an_unknown_id_is_404_and_an_already_deleted_one_is_409` | 2026-10-28 |
| CHK-M7-163-managed | APP | W | plant: `PolicyManagedOnServer` swallowed (204) | PASS (red) | 1 failed: `test_a_server_folder_policy_is_409_and_nothing_changes` | 2026-10-28 |
| CHK-M7-163-starting | APP | W | plant: `Retry-After` dropped | PASS (red) | 1 failed: the start-up row | 2026-10-28 |

## Acceptance

TASK-163 row: "Through the API on PostgreSQL: REQ-171 (1)–(4) hold and REQ-167 (1) is seen through the route."
- REQ-171 (1): CHK-M7-271 (1) 204 and refusals, CHK-M7-282.
- REQ-171 (2): CHK-M7-271 REQ-171 (2).
- REQ-171 (3): CHK-M7-271 REQ-171 (3).
- REQ-171 (4): CHK-M7-271 REQ-171 (4).
- REQ-167 (1): CHK-M7-271 REQ-167 (1). REQ-167 (3) is also held.

The security plants all went red: API token (CHK-M7-341), sink gate (CHK-M7-343), role (CHK-M7-346) and token group.

## Notes (no defect)

- The TOTP-session check runs before the role check, so an operator or viewer `bsk_` gets 403 `totp_session_required`, not `forbidden`. REQ-171 (1) asks only for 403 there, and the tests assert only the status.
- REQ-167 (2), (4) to (6) are TASK-152's and were tested there. Through this route the re-upload revival keeps the same `policy_id`.
