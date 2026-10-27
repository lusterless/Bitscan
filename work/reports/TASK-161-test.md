# TASK-161 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-168 (1) to (5), REQ-169 (1) to (5), REQ-174 (2), REQ-178; TS §6.2 L1100 to L1102, §4.3 L546 to L548, §6.3, §6 L1056; #9, #98 (a) to (c), #101. Files under test: `bm/services/importer/profiles.py`, `bm/api/user/policies.py`, `bm/api/user/__init__.py`, `manager/openapi.json`. New test file `manager/tests/test_policies_api_pg.py` (59 tests) on the M2 users-API environment (real sink gate and shipper). Policies are built through the TASK-151 store. One tester-owned pin updated: `test_invariants_m3.py::test_no_query_parameter_can_switch_inventory_off`. It now pins `GET /policies` to exactly {`limit`, `cursor`, `status`} (TS §6.2 L1100), and the general set is unchanged.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t161, `CI=true`, `-n 2`) | `pytest tests/test_policies_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_catalog_repo_pg.py` | 152/154 passed, 2 failed: `test_non_json_body_is_400` (my test bug: `headers` passed twice) and the route-walk query pin (the expected new `status` parameter) |
| r1 (m7t-t161b) | those two node ids after the fixes | 2/2 passed |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-251 | APP | W | r0 | PASS | REQ-169: of 3 enabled, 2 disabled (one by override) and 1 deleted, the list holds 5, `enabled` 3, `disabled` 2; `status` `deleted`, `ENABLED`, `` and a list → 400; N + 1 with limit N (1, 2, 5), each once in name order; limit 0, 501, `a`, garbage cursors and a `/users` cursor → 400; item keys exactly #98 (a) in order, integer ids, `Z` timestamps, `plugin_count`; detail = item + `deleted_at` + `plugins` (#98 (b) keys in order, file order, `display_name` `<family> - <plugin>`, `execute` visible to a viewer); a deleted policy's detail shows `deleted_at` and its plugins (#9); `abc`, `+1`, `1.0`, `1_0`, `-1`, ` 1`, `1e3`, 21 digits, `١` → 400; `0`, 2^62, 2^63, 20 nines → 404; hostile text byte-identical as JSON; viewer session and `bsk_` → 200 | 2026-10-27 |
| CHK-M7-250 | APP | W | r0, r1 | PASS | REQ-168: each body sets the stated columns, for an admin session and an admin `bsk_`; the response is the item; every PATCH writes one `policy.status_change` (`by` patch, actor `user:<id>`); 14 other bodies (`status_overridden` true, `execute`, both keys, `{}`, `on`, `Enabled`, nulls, `"false"`, `0`, an extra key, a list, a string, `null`) and a non-JSON body → 400, nothing changed and no entry; a re-enable by PATCH and an override cleared onto an enabled file each raise one `policy_reenabled`; a disable, a no-op and a clear onto a disabled file raise none; deleted → 409 `conflict` with no entry; unknown and `0` → 404; viewer and operator (session and API) → 403 `forbidden`; a restricted admin session → 403 `totp_enrolment_required`; a file import after a PATCH disable stays disabled (version 2); PATCH never changes a plugin row | 2026-10-27 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token and a garbage `bsu_` → 401 problem+json on all three operations, and nothing is audited | 2026-10-27 |
| CHK-M7-281 | APP | W | r0, r1 (`test_invariants_m3.py`) | PASS | the route walk has the three operations; no request schema carries a command; the query-parameter pin is updated as above | 2026-10-27 |
| G6 | CODE | W | `test_openapi.py` (r0) | PASS | the export is byte-identical to `manager/openapi.json` | 2026-10-27 |
| CHK-M7-161-rbac | APP | W | plant: PATCH role lowered to operator | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-353 | APP | W | plant: re-enable decided from the new row (never alerts) | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-361 | APP | W | plant: `execute` added to the PATCH body | PASS (red) | 3 failed: G6 export differs, and `test_no_request_schema_carries_a_command` (G34) flags `PATCH /policies/{id}` `execute` | 2026-10-27 |
| route-group plant | — | — | — | NOT RUN (by design) | the token-prefix check is per router in the M2 code, not in this task; the rows above prove it on these routes | 2026-10-27 |
