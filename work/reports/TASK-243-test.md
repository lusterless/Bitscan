# TASK-243 TEST: PASS

Tester: tester-m11c, 2026-11-08. High risk, full rigor, and the user's second look (PD-47). Every security row, boundary and race is planted. REQ-270 (1)–(5) and REQ-271 (1), (3). Spec: TS §6.2 L1086 and L1125, §5.3 L1053, §4.5 L603, §6 and §6.3. Answers: #118 (b), (c), (g), #147 and #148 (no alert, decisions 2026-11-08 (3)). Code under test: `bm/api/user/reevaluate.py` (sha256 `a4f18cd04e8650be…`), by impl-manager-b, `work/reports/TASK-243-impl.md`. M8's `reevaluate_scan` is called unchanged.

Test files:
- `manager/tests/test_reevaluate_api_pg.py` (new): 36 items. CHK-M11-200 to -209, plus -413.
- `manager/tests/test_m11_contract_api_pg.py` (tester-m11b's file, edited with its agreement): the W1 re-evaluate 501 rows are replaced, because on the file's unknown SID an admin TOTP session now reaches the handler and gets 404.
  - `test_reevaluate_admin_session_reaches_the_501` is now **`test_reevaluate_admin_session_reaches_the_handler`**, expecting 404 `not_found`.
  - In `test_reevaluate_sink_gate_at_15_minutes` (name unchanged), the two re-evaluate rows (at 14:59 and after the drain) expect 404 `not_found` where they expected 501 `about:blank`. The 503 row and the read row stay as they were.
  - The docstring records the change. The refusal table is unchanged.

The plan rows are in [the test plan](../../tests/m11/test-plan.md), section "TP-M11-11". The scan under test runs policy version 1 and is then imported to version 2. p0 is the canary plugin (PASS stored, FAIL under v2). p1 is FAIL stored and PASS under v2. p2 is dropped by v2, so it gets no row and `not_in_version` is 1. p3 is an intake ERROR `runner_unavailable`, which stays ERROR. A second scan on the same host must never get a row.

## Runs (W: WSL Ubuntu 24.04, `/root/m11c`, own venv from `requirements-dev.txt --require-hashes`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| G6 | `python -m bitscan_manager.app /tmp/m11c-openapi.json; cmp … manager/openapi.json` | **PASS**: byte-identical, sha256 `126c5429…` for both. This is the G6 run the implementer could not do. |
| 1 | `pytest -n 4 test_reevaluate_api_pg.py test_m11_contract_api_pg.py` | Collection error: xdist saw different parametrize ids, because the canary text was in the ids. Test bug; stable ids added. |
| 2 | same | 126/130 passed, 4 failed, 0 errors, 0 skipped. All four were test bugs: (a) the wake and sink counts were not scoped to the scan, and the module database is shared; (b) `alert_samples` read the default registry, not `services.audit.metrics.REGISTRY`; (c) `admin:unverified` expected `totp_session_required`, but M2 REQ-046 (d) defines an admin session that is not TOTP-verified as restricted, so the answer is 403 `totp_enrolment_required`. |
| 3 | `pytest -n 4 test_reevaluate_api_pg.py` | 35/36 passed, 1 failed (the sink-record filter, same cause as (a)) |
| 4 | `pytest -n 0 test_reevaluate_api_pg.py::test_entry_reaches_the_sink_on_the_wake`, after the fix | 1/1 passed |
| 5 | `pytest -n 6` on the targeted set: `test_reevaluate_api_pg.py` (36), `test_m11_contract_api_pg.py` (94), `test_m11_contract.py` (28), `test_invariants_m3.py` (33), `test_auth_dependencies.py` (33), `test_reevaluate_pg.py` (31), `test_reevaluate_race_pg.py` (7) | **262/262 passed**, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on both test files, from the repository root | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-200 | `test_reevaluate_api_pg.py::test_admin_totp_session_reevaluates`, `::test_entry_reaches_the_sink_on_the_wake`, `::test_each_call_adds_rows_and_the_latest_wins`, `::test_disabled_policy_is_reevaluated` | PASS | An admin TOTP session gets 200 with exactly `{scan_id, policy_id, scan_policy_version: 1, policy_version: 2, rows_added: 3, not_in_version: 1}`. It adds three rows: p0 FAIL, p1 PASS, p3 ERROR `runner_unavailable`, all `policy_version` 2 and `reevaluated_by` the admin. p2 gets no row and the other scan gets none. `scan_result` is byte-unchanged. There is exactly one new audit entry, `scan.reevaluate`, with actor `user:<id>`, target `scan:<id>` and detail exactly the five counts. The wake runs once, after the entry is committed (another session sees it), and one shipper cycle at that moment delivers it to the recording sink. A statement spy sees no UPDATE or DELETE on `scan_result` or `scan_result_reeval`. A second call adds three rows with higher ids. A disabled policy gets 200 (#118 (c)). |
| CHK-M11-201 | `::test_refusal_writes_nothing_and_reads_no_scan[*]` (12 rows) | PASS | Refused: admin `bsk_` 403 `totp_session_required`; operator and viewer `bsk_` 403; operator and viewer sessions 403 `forbidden`; restricted admin and an admin's session that is not TOTP-verified 403 `totp_enrolment_required` (REQ-046 (d)); an expired admin session, a revoked session, no token, `bsa_` and `bse_` 401 `unauthorized`. Each refusal leaves the `scan_result_reeval` and `audit_log` checksums and counts unchanged and wakes nobody. |
| CHK-M11-202 | `::test_sink_outage_gate_at_15_minutes_and_after_the_drain` | PASS | Under clock control: 14 min 59 s gives 200 (rows added). At 15 min the answer is 503 `audit_sink_unavailable`, with both checksums unchanged. After the drain it is 200 again (6 rows in all). |
| CHK-M11-203 | `::test_unknown_scan_is_404_with_fixed_words`, `::test_deleted_policy_is_409_with_fixed_words`, `::test_malformed_id_is_400_for_an_admin[*]` (6), `::test_upper_case_id_is_accepted`, `::test_viewer_on_an_unknown_scan_is_403_not_404` | PASS | The 404 body is exactly `{type: not_found, title, status: 404, detail: "No such scan.", instance}`, and the 409 body is exactly `{type: conflict, …, detail: "The policy is deleted."}`. Neither holds the id, `Traceback`, an exception class, `psycopg` or SQL. Neither writes or wakes. Not-a-uuid, 32-hex, too long, too short, braced and `urn:uuid:` ids are 400 `invalid_request` with nothing written. An upper-case id gets 200. A viewer on an unknown id gets 403, so there is no existence oracle. |
| CHK-M11-204 | `::test_a_body_never_changes_the_answer[garbage,execute,fields]`, `::test_a_2_mib_body_is_refused_before_any_work` | PASS | Garbage, `{"execute": EXEC…, "scan_id": other}` and unrelated fields all give the same 200 and rows. There is one entry with no canary, and the other scan is untouched. 2 MiB of JSON is 413 `too_large` from the M2 body cap, with nothing written. |
| CHK-M11-205 | `::test_two_concurrent_calls_are_serialised` | PASS | With M8's lock held by another session, call A then call B queue on it. A `pg_locks` probe shows 1, then 2 waiters (20 ms polls, 10 s bound). On release both answer 200. Every one of B's reeval ids is above every one of A's. The latest row of each plugin is B's, and the audit actors are A then B. |
| CHK-M11-206 | `::test_reevaluation_raises_no_alert` | PASS | The one new entry has no `detail.alert`. No entry after the call has `detail ->> 'alert' = 'true'`. Every `bitscan_alerts_total{kind}` sample is unchanged (all kinds exported). |
| CHK-M11-207 | `::test_refusal_writes_nothing_and_reads_no_scan[*]` (the spy half) | PASS | For each of the 12 refusals, a statement spy sees no statement naming `scan`, `audit_log` or an advisory lock. Only the token check ran. |
| CHK-M11-208 | `::test_no_canary_or_token_in_answers_logs_or_audit` | PASS | The calls give 200, 404, 409, 403 (API token), 403 (viewer) and 401 (`bsa_`). No OUT, ERR, EXEC or EXP canary and no caller token appears in any answer, log record (message, args and every attribute, at DEBUG; capture proven by the `token accepted` record), audit detail or sink record. |
| CHK-M11-209 | `::test_route_imports_no_repository` | PASS | AST walk of `reevaluate.py` and the module-level imports of every `bm.api` module it reaches: there is no `bitscan_manager.repositories` import, and `services.evaluator.reevaluate` is found. |
| CHK-M11-413 | `::test_reevaluate_scan_has_one_caller` | PASS | REQ-271 (1): an AST scan of `bitscan_manager/` finds `reevaluate_scan` only in `api/user/reevaluate.py` and in its own module. The whole G83 source check stays with TP-M11-15. |
| CHK-M11-233 (replaced rows) | `test_m11_contract_api_pg.py::test_reevaluate_admin_session_reaches_the_handler`, `::test_reevaluate_sink_gate_at_15_minutes` | PASS | 404 `not_found` on the unknown SID at 14:59 and after the drain; 503 at 15 min; the refusal table unchanged (94/94 in the file) |
| G6 | `python -m bitscan_manager.app` + `cmp` | PASS | byte-identical |

## Plants (throwaway copies `/root/m11c/mut-<id>`, each deleted after its row; plants file `/root/m11c/plants-243.json`, log `/root/m11c/plants-243.out.jsonl`)

13 plants: 13 red, 0 survived. Each one ran the whole of `test_reevaluate_api_pg.py` (`-n 4`), and every expected test failed for the planted reason. The clean tree is run 5.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-335 | `require_totp_session()` swapped for `require_role("admin")` | `refusal[admin:api]` (200), sink gate (no 503), canary sweep (the API-token call got 200): 3 |
| CHK-M11-414 | `require_role("admin", allow_restricted=True)` | `refusal[admin:api]`, `[admin:restricted]`, `[admin:unverified]`, sink gate, canary sweep: 5 |
| CHK-M11-336 | `require_totp_session(sink_gate=False)` | sink gate: 1 |
| CHK-M11-337 | `require_totp_session("operator")` | `refusal[operator:session]`: 1 |
| CHK-M11-338 | `wake=runtime.sink_gate.wake` removed | success row (no wake), immediate-delivery row: 2 |
| CHK-M11-410 | the wake called before the service, not on commit | success and delivery rows (the entry was not yet visible), plus the 404 and 409 rows (they woke the shipper): 4 |
| CHK-M11-340 | alert flag added to M8's `scan.reevaluate` detail | no-alert row, success (exact detail), delivery: 3 |
| CHK-M11-407 | the route raises its own alert (`raise_alert`, kind `policy_rebuilt`) | no-alert row, success, adds-rows and body rows (an extra entry): 6 |
| CHK-M11-408 | a `bm.repositories` import added to the route | import-graph row: 1 |
| CHK-M11-409 | the 404 detail echoes the id and the exception name | 404 row: 1 |
| CHK-M11-411 | the `PolicyDeleted` mapping removed (500) | 409 row, canary sweep: 2 |
| CHK-M11-412 | M8's lock taken shared (`pg_advisory_xact_lock_shared`) | concurrency row (no waiter: the calls were not serialised): 1 |
| CHK-M11-413 | a second import of `reevaluate_scan` (in `services/jobs/scan_views.py`) | one-caller row: 1 |

CHK-M11-335 note: the brief expected the no-TOTP rows to turn red under `require_role("admin")`. They don't, because M2's `_gate` refuses a restricted principal (an admin without TOTP, or an admin session that is not TOTP-verified) under every factory unless `allow_restricted` is set. The API-token row and the sink-gate row are what tell `require_totp_session()` apart from `require_role("admin")`. CHK-M11-414 adds `allow_restricted=True`, and the no-TOTP rows go red.

## Acceptance (TASK-243: "Through the API on PostgreSQL: REQ-270 (1)–(5) and REQ-271 (1), (3) hold, each refusal row leaving no `scan_result_reeval` row and no audit entry")

- REQ-270 (1): CHK-M11-200.
- REQ-270 (2): CHK-M11-201, -202, -207.
- REQ-270 (3): CHK-M11-203.
- REQ-270 (4): CHK-M11-205.
- REQ-270 (5): CHK-M11-209.
- REQ-271 (1): CHK-M11-413 (route part).
- REQ-271 (3): CHK-M11-206.
- Also covered: REQ-271 (2) on this route (the spy in CHK-M11-200), #147 (b) (CHK-M11-204), REQ-272 (4) (CHK-M11-208) and G6.

## Notes

- In run 2, an assertion failure printed fixture tokens (test-only tokens on a throwaway container) into `/root/m11c/logs/r243b.log`. Every `bs[uaek]_` string in my logs has since been masked. `run.sh` now uses `--tb=short` and masks tokens after each run.
- Shared fixtures: none edited.
