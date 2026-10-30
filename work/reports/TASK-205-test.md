# TASK-205 TEST: PASS (r1)

Tester: tester-m9b, 2026-10-30. Full rigor; lead's second look (PD-39). REQ-212 (1), REQ-220 (2), REQ-221, REQ-222 (3), (4), REQ-227 (2); TS §6.2 L1119, L1122, L1084, §6.3 L1133–L1138, §6.4 L1146–L1155, §8.4 L1290, §3.3 L213; #3, #48, #122 (a)–(g), #123, #129 (b). Code under test: `bm/api/user/scans.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (impl-manager-m9, `work/reports/TASK-205-impl.md`, incl. r1: the target is parsed before the idempotency digest). Test file: `manager/tests/test_scans_api_pg.py` (new). Plan rows: CHK-M9-240 to -246.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scans_api_pg.py` (8-file batch, r1 tree) | **12/12 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| security | `tests/test_security_m9.py tests/test_invariants_m3.py tests/test_openapi.py tests/test_contract_agent.py` | 622/622 passed (G6, G34 with the seven operations) |
| plants | 4 | 4/4 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-240 | PASS | operator and admin, each with a session and with an API token → 202 with exactly `{scan_id, state: "queued", policy_version, jobs}`; the scan row is `requested_by` the caller, `manual`. A viewer → 403 `forbidden`; a `bsa_` token, no token and a revoked token → 401; nothing written |
| CHK-M9-241 | PASS | unknown policy → 404 `not_found`; disabled → 409 `conflict` "The policy is disabled."; deleted → 409 "The policy is deleted."; only a decommissioned agent → 422 `about:blank` "The target resolves to no host."; `{all: false}`, two keys, `policy_id` as a string, no `policy_id`, an extra `plugins`/`execute`/`command`/`payload`/`eval_spec` key, and `execute` inside the target → 400 `invalid_request` (no input echoed); 1 MiB + 1 → 413 `too_large`; scan, job, result and audit counts unchanged. Exactly 1 MiB → 202 |
| CHK-M9-242 | PASS | `{all: true}` + `bsk_` → 202, the `scan.create` entry carries `alert` true and `alert_kind` `all_hosts_scan_api_token`, the counter +1, the fake sink receives it after one shipper cycle; a session and tags + `bsk_` → 202, no alert |
| CHK-M9-243 | PASS | cancel: viewer 403; `bsa_` 401; operator 200 `{scan_id, state: "cancelled", cancelled_jobs: 3}` (queued, dispatched, and running after a start notice); a repeat → `cancelled_jobs: 0`; unknown 404; `x`, `123`, short and long ids → 400. The cancelled queued job is never pulled; posts for the cancelled dispatched and running jobs → 409, nothing stored |
| CHK-M9-244 | PASS | `api/user/scans.py` imports no repository and no psycopg (AST; also `test_security_m9.py`) |
| CHK-M9-245 | PASS | a repeat with the same key and body → the same 202 body, no second scan row and no second `scan.create` entry; the same key with another body → 409 `conflict` "Idempotency-Key was used with a different request."; another user's same key → its own scan. Keys of 256 characters, with `\x01`, with a tab, and empty → 400; 255 characters → 202. **r1:** `{"agents": [NaN]}` with a key → 400, not 500 |
| CHK-M9-246 | PASS | a snapshot with U+0000 in `execute` → 500 `about:blank`, fixed detail with no input, nothing written |
| CHK-M9-364 | PASS (red) | operator → viewer in the dependency → 2 failed |
| CHK-M9-365 | PASS (red) | the token check removed (any caller, incl. `bsa_` and none) → 7 failed |
| CHK-M9-382 | PASS (red) | `extra="ignore"` → 1 failed (the refusal row: an `execute` key accepted) |
| CHK-M9-367 (route) | PASS (red) | the store bypassed → 1 failed (a second scan on repeat) |

## Acceptance (TASK-205 row)

REQ-221 (1)–(5), REQ-222 (4), REQ-212 (1), REQ-220 (2) → the rows above. `manager/openapi.json` re-export byte-identical (G6 green).

## Notes (no defect)

- `POST /scans` validates its declared body before the token check, as the existing user routes do, so a malformed body with a bad token gets 400, not 401. With a valid body, each token case is 401. The impl report mentions this. No 401 from this suite depends on body order.
