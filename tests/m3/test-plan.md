# M3 test plan (agent API and scheduler, inventory only)

Owner: tester. Written 2026-10-23 from `work/tasks.md` "M3 agent API and scheduler (inventory only)" (acceptance tests, TP-M3-00 to TP-M3-35, M3 gate G1 to G6, G16, G18, G25 to G34, the security mutation table CHK-M3-320 to -374), `work/requirements.md` REQ-060 to REQ-090, the plans `work/plans/TASK-048.md`, `-049`, `-059`, `-060`, `-061`, `-067`, the TS sections they cite (§2.3, §3.2 to §3.4, §5.2, §6, §6.1 to §6.3, §6.5, §8.1, §8.3, §8.4, §8.6) and the answers agreed by the user on 2026-10-23 (`work/decisions.md`; `work/open-questions.md` #25, #26, #33, #36, #37, #59 to #73, PD-21 to PD-24), before any M3 implementation existed (`bm/api/agent/` was absent when this plan was written). Results go to [report.md](report.md) (written by `main` from the tester's messages if the harness blocks the tester).

`bm/` means `manager/bitscan_manager/`.

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = the real app: `create_app(runtime)` served by the ASGI test client against a real PostgreSQL, or the real `bitscan-manager` process (`serve`).
- Where: **L** = Windows 11 + Git Bash, `PY` = `manager/.venv/Scripts/python.exe`, run from `manager/`. **W** = WSL2 Ubuntu 24.04 with Docker, run only by the tester, one run at a time, through `%TEMP%\tester2_<name>.sh` launched with `MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/Users/kaiquan.koh/AppData/Local/Temp/tester2_<name>.sh`; working copy `/root/bitscan-tester` (tree copied without `.venv`, `node_modules`, `__pycache__`), venv `/root/venv-m2` rebuilt from the hashed dev lock after TASK-058 (plus `pip install --no-deps --no-build-isolation -e .`), `CI=true`, `RYUK_CONTAINER_IMAGE` pinned, every run under `timeout`, containers removed afterwards. Linux-only files also run as the non-root user `bstester` (docker group). **CI** = GitHub Actions only. On L every `pg` test is "not run: Docker unavailable"; the W run is the evidence.
- PostgreSQL checks use the M1 harness: Bootstrap from the spec, `db migrate` through the CLI, then connections only as `bitscan_app` (and `bitscan_retention`, `bitscan_migrate`). **As owner** = a test-only statement as `bitscan_migrate` + `SET ROLE bitscan_owner`, used only to build states the app cannot (a compliance `scan_job` row, a row in `scan_result_default`, a short `offline_sweep` interval).
- **Fake clock** = the M2 `Clock`; every time rule (token expiry, rotation window and overlap, rate windows, the 10-minute upload window, status ages, `pickup_by`, the 30-minute inventory failure, alert windows) is tested by moving it, never by sleeping.
- **Canary** = `CANARY-<16 hex>`; M3 adds `bsa_` and `bse_` tokens built around a canary body, inventory package names, `raw` values, results `stdout`/`stderr` and heartbeat `last_error` (REQ-087). The sweep helper is `manager/tests/canary.py` (M2).
- **Refused** on an agent route = the #59 status and `type`, and a row snapshot of `agent`, `agent_ip_seen`, `agent_tag`, `enrollment_token`, `enrollment_request`, `os_info`, `agent_package`, `package`, `inventory_snapshot`, `scan_job`, `audit_log` before and after is equal except an entry the criterion names (a failed-check count, an alert, a revoke). On a user route: the #48 status and `type` as in M2.
- **Alert entry** = one `audit_log` row with `detail.alert = true` (JSON `true`) and `detail.alert_kind` = the #71 kind; `bitscan_alerts_total{kind}` rises by one after commit only.
- **Planted violations** are made in a throwaway copy (`$TEMP/m3-mut-<id>` on L, `/root/bitscan-mut` on W), never in the tree; the unmodified copy must be green; "red" = non-zero exit **and** the named test fails for the planted reason.
- Expected values come from the spec and the answered questions below, never from the implementation. Where an answer leaves a point open the check says so and `main` is asked; a check is never adapted to the code.
- Every route task's TEST re-runs: the contract test against `manager/openapi.json` (TP-M3-02 document half, CHK-M3-016), the OpenAPI error contract (CHK-M3-017), G6 (CHK-M3-304) and the route walk of TP-M3-35 (CHK-M3-300).

## Expected values (spec and answered questions)

| Item | Expected | Source |
| --- | --- | --- |
| Agent statuses and `type` | 401 `unauthorized`, one body, for a missing, malformed or unknown token, a user token (`bsu_`, `bsk_`), a `bse_` on a `bsa_` route, a `bsa_` on enrol, and every refused `bse_` (expired, revoked, outside `allowed_cidrs`, exhausted, unknown; no hint which); 401 `enrollment_rejected`, `token_revoked`, `token_expired`, `machine_id_mismatch`; 403 `pending_approval`; 403 `forbidden` (foreign `{id}`; rotation outside the window); 400 `invalid_request` (malformed body, parameter or header, missing `Content-Encoding: gzip` on inventory); 409 `job_not_acceptable`; 413 `too_large`; 422 `about:blank` (inventory field, row-count, duplicate and hash refusals); 429 `rate_limited` with `Retry-After` (whole seconds to the window end); 503 `about:blank` (database down) | #59, #62, #72; TS §6.5 L1190 |
| Check order | header and prefix → hash lookup (current, previous, pending request) → `enrollment_rejected` → `token_revoked` → `token_expired` → `machine_id_mismatch` → `pending_approval` → `{id}` → 30-per-minute agent limit | #59; plan TASK-059 outcome table |
| Failed checks | every 401 on an agent route counts toward the 20-per-minute per-IP limit and its aggregated `auth.token_check_failed` entry (with user-route failures from that IP); 403 and 429 never count; a valid `bsa_` from a limited IP passes | #59; TS §6.3 L1136; M2 decisions "Correction to M2 test-plan answers (3)" |
| Missing or malformed `X-Bitscan-Machine-Id` | same as a different machine-id: 401 `machine_id_mismatch`, token revoked, alert; for a pending re-enrolment token: 401 and alert, request stays pending | #63 |
| Size caps | 1 MiB = 1,048,576; inventory 10,485,760 as sent, 67,108,864 decompressed; result batch 1,572,864 as sent and after decompression; other agent and user routes 1,048,576; `os_info.raw` 262,144 bytes of compact UTF-8 JSON (413) | TS §6.3 L1138, §3.4 L240; #57 (b); #72 (b) |
| Inventory refusals | 413 for byte limits (gzip body, decompressed size, `raw`); 422 for more than 50,000 packages, field limits, duplicate `(name, version, architecture)`, `list_sha256` mismatch; 400 for no `Content-Encoding: gzip`, bad gzip, invalid UTF-8 or JSON | #72 (a), (b), (c), (f); #33 |
| `list_sha256` | lowercase hex SHA-256 of the concatenation of the lines `name\tversion\tarchitecture\tstatus\n`, UTF-8, sorted by bytes; recomputed by the manager | TS §6.5 L1186; #33; plan TASK-060 step 4 |
| Tokens | `bsa_` / `bse_` + 43 characters `[A-Za-z0-9_-]` (no `=`), 47 in total, body = base64url of 32 CSPRNG bytes; stored hash = lowercase hex SHA-256 of the whole string | TS §6.2 L1083; #56 (a); REQ-063 |
| Wire contract | field table of `work/plans/TASK-048.md` (#60): strings bounded in code points; `machine_id` `^[0-9a-f]{32}$`; RFC 3339 timestamps with an offset (naive refused), output UTC `Z`; UUID strings; unknown keys refused in every body; integers strict (no booleans, floats or numeric strings); `runner_helpers` 0 to 8 distinct `^[a-z][a-z0-9_-]{0,31}$`; `ip_addresses` 0 to 256 `INET` texts; empty `source` stored as NULL; `started_at`, `finished_at` required; rotate takes no body (`{}` or empty), anything else 400 | #60 |
| Job body | inventory: exactly `job_id`, `agent_id`, `kind` = `inventory`, `pickup_by`; compliance: those with `kind` = `compliance` plus `plugins` (1 to 5,000 items of exactly `plugin_uuid`, `execute` (non-empty), `timeout_s` 1 to 600) and `redaction_patterns` (0 to 50 strings); `additionalProperties: false`; never `operator`, `expected_result`, `expected`, `eval_spec` | TS §6.5 L1165–L1182; REQ-060 (1); #60 |
| Settings | `agent_token_ttl_days` 365 (60–730); `job_pull_seconds` 300 (60–3,600); `decommission_after_days` 7 (0–365); `redaction_patterns` the five TS §8.6 defaults (at most 50, RE2); `max_parallel_plugins` 2 (1–8); `enrolment_alert_per_hour` 50 (1–10,000); `inventory_interval_s` 21,600 (3,600–86,400, in `system_schedule`). JSON: bare numbers, an array of five strings in spec order | TS §8.6 L1317–L1339; #42 |
| Rate limits | 30 requests per minute per agent over all its routes; enrol 10 per minute per source IP, every attempt counting; at most one unscheduled inventory upload per agent per 10 minutes (no `job_id`, or a `failed` or `completed` job's id), the window starting when the upload reaches decoding, accepted or not; the `dispatched` case exempt | TS §6.3 L1136, §3.4 L239; #55 (c); #72 (e) |
| Inventory `job_id` cases | `dispatched` (own, inventory): completes it (`completed`, `finished_at`); `failed`: stored as unscheduled, job stays `failed`; `completed`: stored as unscheduled; unknown, another agent's, compliance, `queued`, `expired`, `cancelled`: 409 `job_not_acceptable`, audit entry, nothing stored; non-UUID: 400. A 413 or 422 naming a `dispatched` job fails it with one `agent.inventory_refused` entry; a 400 is audit-logged and leaves the job to the 30-minute sweep | #72 (c), (d); TS §3.4 L244 |
| Rotation | window from `issued_at + max(TTL − 30 d, TTL ÷ 2)` (TTL = the presented token's own `expires_at − issued_at`) to `expires_at`; outside: 403 `forbidden` + `rotation_outside_window`; a second rotation within 24 h of a **used** one: 429 `rate_limited`, `Retry-After` to the end of the 24 h; old token valid for normal calls until 10 min after the new token's first use (first call that passes the check), any use after that revokes both + `token_reuse`; rotate with the old token before the new one is used = lost-response retry (fresh token, the unused one dies, old still works); after the new one was used = reuse even inside the 10 min; new-IP alert when the IP is not in `agent_ip_seen` for the agent within 7 days | TS §3.2 L190; #62 |
| Status | `online` if age < 10 min; `stale` 10 to 30 min inclusive; `offline` > 30 min; age from `last_heartbeat_at`, else `enrolled_at` (or the approval time); a heartbeat sets `online` at once; decommission when age > `decommission_after_days` days (0 = never), with `token_revoked_at`, one `agent.decommission` entry (actor `system`); `online`/`stale`/`offline` changes not audited; revoke does not change status | TS §3.3 L218, L220; #25; #73 |
| Inventory queueing | one global run at start-up and then every `interval_s`; an interval change picked up within one `offline_sweep` interval; one job per agent not `decommissioned` or `awaiting_approval` with no inventory job in `queued`, `dispatched` or `running`; payload exactly the four keys, `pickup_by` = `created_at` + 24 h; also one job when an agent becomes `enrolled` (auto-approve or approval) | TS §3.4 L230; #36; #67 |
| Audit actions (#71) | actor `agent:<agent_id>` for agent-route events, otherwise #50 (b). `enrollment_token.create`, `enrollment_token.revoke`, `agent.enrol` (detail: token id, kind, status, request id), `enrollment_request.approve`, `enrollment_request.reject`, `agent.token_rotate`, `agent.token_reuse`, `agent.machine_id_mismatch`, `agent.runner_helpers_change`, `agent.revoke`, `agent.tags_set`, `agent.decommission`, `agent.result_refused`, `agent.inventory_refused`, `settings.change`, `alert.<kind>` for threshold alerts. Heartbeats, pulls and accepted uploads are not audited. `detail` never holds a token, stdout, stderr or package list | #71 |
| Alert kinds (#71) | `enrolment_token_risky` (one per token, detail flags auto-approve and over-100), `enrolments_per_hour`, `reenrolment_approved`, `machine_id_mismatch`, `token_reuse`, `rotation_outside_window`, `rotation_new_ip`, `runner_helper_changed`, `settings_changed`, `redaction_default_removed`, `clock_skew`, `agents_offline`, `job_queue_age`, `inventory_stale`, `new_packages_burst`, `result_409_flood`, `agent_auth_failures`, `default_partition_rows`; one entry per event | #71 |
| Alert windows | in memory, reset on restart. Clock skew > 5 min: once per agent per hour while it lasts. Offline share: denominator = agents not `decommissioned` or `awaiting_approval`; fire when the share goes above 5 %, re-arm only after ≤ 5 %. Stale inventory (> 2 × interval, online host): once per agent until its next upload; base `enrolled_at` / approval time. Agent 401s: more than 20 in a minute for tokens resolving to one agent, once per agent per hour. New packages: more than 1,000 new `package` rows created by one agent's uploads in a rolling 24 h, once per agent per 24 h. 409 flood: more than 20 in 10 minutes from one agent, once per agent per hour. Default partition: once when rows first appear, again only after it was empty. Queue age: oldest `queued` job whose agent is `online` older than 1 h, at most once per hour. Enrolments per hour: every successful enrolment counts, sliding 60 min per token, alert when the count exceeds the setting, at most once per token per hour | #54 (c), #61, #65, #66 |
| User-route bodies | as #68 (enrolment tokens, requests, agents, packages, tags, revoke, settings, audit log), lists `{items, next_cursor}`, BIGSERIAL ids integers | #68, #52 |
| Snapshot | items `{name, version, architecture, status}`; an upgrade or status change = old line in `removed`, new in `added`; first snapshot lists all in `added`; `collected_at` = receive time; `GET /agents/{id}` `last_snapshot: {snapshot_id, collected_at, package_count, added, removed}` or null | #69 |
| Metrics | `GET /api/v1/metrics`, normal bearer check (`bsu_`/`bsk_`), minimum role viewer, Prometheus text; `HealthPath` unchanged | #70 |
| Re-enrolment | approval updates `hostname`, `agent_version`; token columns from the request (`requested_at`, request `token_expires_at`); status `enrolled`; `token_revoked_at`, `prev_*`, `last_rotation_at` cleared; requests decided independently; an expired request token cannot be approved (409); rejection leaves the existing agent row unchanged, new token gets 401 `enrollment_rejected` | #26, #64 |

## Gate map

| Gate | Checks |
| --- | --- |
| G1 ruff (S608, `re` ban) | CHK-M3-306 |
| G2 ruff format | CHK-M3-307 |
| G3 mypy --strict | CHK-M3-308 |
| G4 pip --require-hashes (both locks) | CHK-M3-001, CHK-M3-002, CHK-M3-309 |
| G5 coverage gate (L, unit only) | CHK-M3-310 |
| G6 OpenAPI export diff | CHK-M3-304 (and the last row of every route task) |
| G16 web client regeneration | CHK-M3-298, CHK-M3-311 |
| G18 full W/CI run, 0 skipped | CHK-M3-312 |
| G25 M2 security suite re-run | CHK-M3-313 (with CHK-M3-323) |
| G26 M2 shipper suite re-run | CHK-M3-314 |
| G27 `serve` + scheduler on Linux | CHK-M3-230 to -234, CHK-M3-315 |
| G28 canary | CHK-M3-302, CHK-M3-366 |
| G29 telemetry | CHK-M3-233, CHK-M3-316 |
| G30 contract | CHK-M3-010 to -019 |
| G31 agent security | CHK-M3-160 to -169, CHK-M3-301, CHK-M3-303, mutation rows marked G31 |
| G32 decoder fuzz | CHK-M3-130 to -139 |
| G33 sweep, queue, fleet alerts | CHK-M3-140 to -146, CHK-M3-180 to -188, CHK-M3-210 to -214 |
| G34 invariants | CHK-M3-300, CHK-M3-305 |

## TP-M3-01 Contract fixtures (REQ-061; PD-22)

Location: `manager/tests/contract/fixtures/`, one folder per route (`enrol`, `heartbeat`, `jobs`, `results`, `inventory`, `rotate`), files `<direction>_<valid|invalid>_<name>.json`, and `manifest.json` listing every file with its route, `direction` (`request` / `response`), `valid` (bool), constraint `class` (invalid only: `extra_key`, `missing_key`, `wrong_type`, `over_length`, `bad_uuid`, `bad_timestamp`, `enum`, `range`, `format`) and a short spec reason. Written from TS §6.5 and the #60 field table only. Large fixtures (5,000 plugins, 50,001 packages) are built in the test from a named base fixture and listed in the manifest as `generated`. The one fake token is `bsa_` + 43 fixed characters (REQ-061 (5)); the enrol request carries no token (the `bse_` travels in the header). Inventory fixtures are uncompressed JSON; the tests gzip them.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-010 | CODE | REQ-061 (1), (2), (5) | Manifest test: every file is listed and every entry exists; each route has ≥ 1 valid request and ≥ 1 valid response fixture (rotate request `{}`), including both Job variants, `{"jobs": []}`, the start notice `{"results": [], "final": false}`, an inventory with zero packages and one with multi-arch packages; every body has ≥ 1 invalid fixture of each constraint class that applies to it (table in `manifest.json`); every string matching `bs[aeku]_` in any fixture equals the one fake token; each valid inventory fixture's `list_sha256` equals the value computed in the test from the TS §6.5 text, and the `hash_mismatch` fixture's does not | — | L |

## TASK-048 Agent wire contract (REQ-060, REQ-061, REQ-088; TP-M3-02; G30)

Tests in `manager/tests/test_contract_agent.py`. Models from `bm/api/agent/schemas.py`, names as in the plan interface (`EnrolRequest`, `EnrolResponse`, `HeartbeatRequest`, `HeartbeatResponse`, `JobsResponse`, `ResultsRequest`, `ResultsResponse`, `InventoryBody`, `RotateResponse`). JSON Schema checks use `jsonschema` (Draft 2020-12 validator) with a format checker asserting `date-time` (RFC 3339 §5.6 with a required offset) and `uuid` (RFC 9562 hyphenated form).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-011 | CODE | REQ-061 (3), REQ-060 (4) | Every valid fixture parses with its model (`model_validate_json` on the file bytes) and every invalid one raises `ValidationError` | `extra="forbid"` removed from the heartbeat request (CHK-M3-345 family); a field renamed | L |
| CHK-M3-012 | CODE | REQ-061 (3) | Every valid fixture validates against the model's JSON Schema (`model_json_schema()`, validation mode for requests, serialization mode for responses) and every invalid one fails it; model and schema agree on every fixture | schema `additionalProperties` dropped | L |
| CHK-M3-013 | CODE | REQ-060 (1) | Walk of the `JobsResponse` schema (all `$defs` reachable): exactly two Job variants; the inventory variant's properties are exactly `job_id`, `agent_id`, `kind`, `pickup_by`, all required, `kind` const/enum `inventory`; the compliance variant's exactly those plus `plugins` and `redaction_patterns`, all required, `kind` `compliance`; plugin items exactly `plugin_uuid`, `execute`, `timeout_s`; every object has `additionalProperties: false`; no property named `operator`, `expected_result`, `expected` or `eval_spec` anywhere | `operator` added to the plugin item (CHK-M3-346) | L |
| CHK-M3-014 | CODE | REQ-060 (2), REQ-088 (4) | `HeartbeatResponse` schema properties are exactly `job_pull_seconds`, `max_parallel_plugins`, `server_time`, all required, `additionalProperties: false` | `jobs` key added (CHK-M3-345) | L |
| CHK-M3-015 | CODE | REQ-060 (3) | Results item schema properties are exactly the TS §6.5 L1184 nine keys; `error` allows exactly null, `spool_overflow`, `runner_unavailable`; `results` `maxItems` 50; response exactly `accepted`, `duplicates` | `maxItems` 51 | L |
| CHK-M3-016 | CODE | REQ-060 (1), (5), REQ-061 (3) | Document half (re-run in every agent route task's TEST): each agent operation in `manager/openapi.json` resolves its request and success-response schema, and every fixture for that route validates (valid) or fails (invalid) against it; at the M3 head all six operations exist under `/api/v1/agent/` | route schema not the model | L |
| CHK-M3-017 | CODE | REQ-060 (5) | Each agent operation documents its #59 refusal statuses as `application/problem+json` with exactly the five problem keys; no operation lists 422 for request validation (the inventory 422 is the decoder's, documented as problem+json); no `HTTPValidationError` schema | default 422 left | L |
| CHK-M3-018 | CODE | REQ-060 | `AGENT_PROBLEM_TYPES` holds exactly the eight TS §6.5 values (plus the documented #59 generic values if the plan's constant includes them) | a value missing | L |
| CHK-M3-019 | CODE | REQ-088 (1) | No request model in `bm/api/agent/` has a field named `command`, `script`, `execute` or `plugins` (only the compliance Job response does) | `command` added to the heartbeat request | L |

## TASK-049 Body caps by template and after-auth mode (REQ-066; TP-M3-03)

Tests in `manager/tests/test_body_caps.py`. Test routes are added in the test only, at `/api/v1/agent/{id}/inventory`, `/api/v1/agent/{id}/jobs/{job_id}/results` and `/api/v1/agent/{id}/heartbeat`, with concrete paths built from random UUIDs. Byte counts are taken by a counting `receive` (raw ASGI drive), as CHK-M2-017.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-030 | CODE | REQ-066 (1) | Normal mode on templated caps: inventory 10,485,760 bytes reaches the route intact, 10,485,761 gets 413 `too_large` problem; results 1,572,864 / 1,572,865; heartbeat and an unregistered path 1,048,576 / 1,048,577 | exact-path lookup (CHK-M3-360) | L |
| CHK-M3-031 | CODE | REQ-066 (2) | For each cap: `Content-Length` over the cap (body generator counting pulls), a lying low `Content-Length`, and a chunked body without `Content-Length`: at most cap + 1 bytes pulled | cap checked on the header only | L |
| CHK-M3-032 | CODE | REQ-066 (3) | After-auth mode: a test route with a dependency that refuses (401) runs before any body byte is pulled (counter 0) and returns 401 even for an over-cap body; with the dependency passing, the route's capped reader gets 413 for cap + 1 (both `Content-Length` and chunked) after at most cap + 1 bytes, and the route ran (it can audit; recorded by the test route) | after-auth mode answering 413 from the middleware (CHK-M3-361) | L |
| CHK-M3-033 | CODE | REQ-066 (5), REQ-037 (5) | At app creation: two caps for one template, an unknown class, a limit one byte above its class maximum each raise `ValueError` | duplicate check removed | L |
| CHK-M3-034 | CODE | REQ-066 (6), REQ-037 | User routes keep 1 MiB (an M2 route: 1,048,577 → 413); the M2 cap tests in `test_app_hardening.py` stay green | — | L |
| CHK-M3-035 | CODE | REQ-066 | A path that only resembles a template (`/api/v1/agent/x/y/inventory`, a trailing slash, a different method if the registry is per method) gets the default cap, not 10 MiB | template compiled without anchors | L |

## TASK-050 `bsa_` and `bse_` tokens (REQ-063; TP-M3-04)

Tests in `manager/tests/test_tokens.py` (extended). Oracles with `hashlib`, `base64`, `re`-free checks.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-040 | CODE | REQ-063 (1) | 10,000 tokens of each agent kind: distinct, prefix `bsa_` / `bse_`, length 47, body `^[A-Za-z0-9_-]{43}$`, no `=`, decodes to 32 bytes; matched end to end by TS §8.6 pattern 3 (RE2) | padded; 31 bytes | L |
| CHK-M3-041 | CODE | REQ-063 (1) | CSPRNG: patched `os.urandom` / `secrets.token_bytes` value appears as the body; patched `random` functions that raise do not break generation | `random.randbytes` | L |
| CHK-M3-042 | CODE | REQ-063 (2) | Hash = `sha256(whole token).hexdigest()`, lowercase, 64 characters, known answer for `bsa_` + 43 × `A` | body-only hash | L |
| CHK-M3-043 | CODE | REQ-063 (4) | Agent parser asked for `bsa_` accepts a well-formed `bsa_`, refuses `bse_`, `bsu_`, `bsk_`, `BSA_`, no prefix, prefix only, bodies of 42 and 44, `=`, `+`, `/`, space, non-ASCII, NUL, a 10 kB string (without hashing); likewise for `bse_` | parser accepting either agent prefix (CHK-M3-320 at the unit level) | L |
| CHK-M3-044 | CODE | REQ-063 (4), REQ-040 (4) | The M2 user parser still refuses well-formed `bsa_` and `bse_` tokens; CHK-M2-060 to -063 stay green | `bsa_` added to user prefixes | L |

## TASK-051 Agent repository (REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082; TP-M3-05)

Tests in `manager/tests/test_agent_repo_pg.py` (marker `pg`), all as `bitscan_app`, fake `now` passed as a parameter.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-050 | CODE | TASK-051 acceptance | Every function runs as `bitscan_app` with only the TS §5.2 grants (no 42501): insert, lookup by token hash, by previous-token hash, by machine-id, status update, token update, rotation update, heartbeat update, `agent_ip_seen` upsert and last-seen lookup, tag replace, list, detail, sweep selects | — | W |
| CHK-M3-051 | CODE | REQ-064 | Lookups by an unknown hash, previous hash and machine-id return none; lookups take a hash, never a raw token (signature and a statement-capture wrapper) | — | W |
| CHK-M3-052 | CODE | REQ-071 (6), #25 | `agent_ip_seen` upsert: first call sets `first_seen_at` = `last_seen_at` = now; a later call moves `last_seen_at` and keeps `first_seen_at`; the last-seen lookup returns the previous value before the upsert (the rotation's 7-day rule) and none for a new IP; IPv4 and IPv6 values | `first_seen_at` overwritten | W |
| CHK-M3-053 | CODE | REQ-082 (1) | Tag replace is all-or-nothing: replacing with a set containing a value the database refuses (65 characters) leaves the old set; replace with `[]` clears | delete committed before insert fails | W |
| CHK-M3-054 | CODE | REQ-078 (1), (4) | The status update touches only agents whose current status is in the statuses it names (an `awaiting_approval` and a `decommissioned` agent untouched); returns the number changed | status filter dropped | W |
| CHK-M3-055 | CODE | G1 | `ruff check` (S608) green; an f-string SQL plant in `bm/repositories/agents.py` is red (CHK-M3-306) | f-string SQL | L |

## TASK-052 Enrolment repository (REQ-067, REQ-068, REQ-069; TP-M3-06)

Tests in `manager/tests/test_enrolment_repo_pg.py` (marker `pg`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-060 | CODE | REQ-068 (2) | 20 threads, each its own connection, use one `max_uses` 5 token at once (barrier): exactly 5 succeed, `uses` = 5; repeated 5 times | `AND uses < max_uses` removed (CHK-M3-332) | W |
| CHK-M3-061 | CODE | REQ-068 (1) | Expired (at `expires_at` exactly and after), revoked, exhausted and unknown tokens and a source IP outside `allowed_cidrs`: none returned, `uses` unchanged | expiry (CHK-M3-333), revocation (CHK-M3-334), CIDR (CHK-M3-335) condition removed | W |
| CHK-M3-062 | CODE | REQ-068 (5) | CIDRs: an IPv4 source inside an IPv4 entry, an IPv6 source inside an IPv6 entry, a mixed list, an IPv4-mapped IPv6 source (`::ffff:10.0.0.1`) against `10.0.0.0/8` (per the TASK-067 plan), `allowed_cidrs` NULL accepts any source | — | W |
| CHK-M3-063 | CODE | REQ-069 (5) | Two concurrent decisions on one pending request (deterministic interleave: A holds `FOR UPDATE`, B blocks): exactly one succeeds, B sees it decided | decision without the row lock or re-check | W |
| CHK-M3-064 | CODE | REQ-069 (1) | Matches: every other agent with the same hostname or the same machine-id is listed (cloned image: two hosts one machine-id; two hosts one hostname); the request's own agent is not in `matches` | hostname-only match | W |
| CHK-M3-065 | CODE | TASK-052 acceptance | Request insert, lookup by `new_token_hash` (unknown → none), pages by state (`pending`, `decided`, `all`), token revoke (`revoked_at`) and pages; all as `bitscan_app`; S608 | — | W |

## TASK-053 Inventory repository (REQ-075, REQ-081; TP-M3-07)

Tests in `manager/tests/test_inventory_repo_pg.py` (marker `pg`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-070 | CODE | REQ-075 (5) | 50,000 distinct packages inserted in batches as `bitscan_app` (time recorded, no gate); the call reports 50,000 new; a second call with the same list reports 0 new and returns the same ids; no UPDATE on `package` is issued (statement capture; the grant would refuse it anyway) | `ON CONFLICT DO UPDATE` | W |
| CHK-M3-071 | CODE | REQ-075 (6) | Two connections insert the same new package at once (barrier): one `package` row, both get its id | select-then-insert | W |
| CHK-M3-072 | CODE | REQ-075 (2) | `agent_package` upsert keeps `first_seen_at` and moves `last_seen_at`, `status`, `installed_size_kb` | `first_seen_at` reset | W |
| CHK-M3-073 | CODE | REQ-075 (3) | Delete-not-listed removes exactly the agent's rows not in the given set, leaves other agents' rows and every `package` row | deletes across agents | W |
| CHK-M3-074 | CODE | REQ-075, REQ-081 | `os_info` upsert replaces every column; snapshot insert and "latest" (by `collected_at`, then id); one agent's package page ordered by name, architecture, version, each row once across pages | — | W |

## TASK-054 Job repository (REQ-072, REQ-076 to REQ-079; TP-M3-08)

Tests in `manager/tests/test_jobs_repo_pg.py` (marker `pg`). A compliance row is planted as owner.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-080 | CODE | REQ-077 (5) | Insert an inventory job: `payload` = exactly `{job_id, agent_id, kind: "inventory", pickup_by}` with `payload.job_id` = row id, `payload.agent_id` = row agent, `pickup_by` = `created_at` + 24 h (payload to the second, `Z`) | payload id generated separately | W |
| CHK-M3-081 | CODE | REQ-072 (1), (3), (4) | Pull for agent A with 12 queued own jobs, plus B's job, a `dispatched`, a `completed`, a job with `pickup_by` = now (and 1 s past) and a compliance row: returns 10 oldest first, all marked `dispatched` with `dispatched_at` = now; next pull returns 2; then none | limit 11 (CHK-M3-348); agent filter (CHK-M3-347); `pickup_by`/`queued` (CHK-M3-349); kind filter (CHK-M3-351) | W |
| CHK-M3-082 | CODE | REQ-072 (2) | Two concurrent pulls by one agent (two connections, barrier, 20 jobs, repeated): no job returned twice, union = 20 | lock and re-check removed (CHK-M3-350) | W |
| CHK-M3-083 | CODE | TASK-054 acceptance | Grant probes as `bitscan_app`: UPDATE of `agent_id`, `payload`, `scan_id`, `kind` refused (42501); every repository update touches only the TS §5.2 progress columns (statement capture) | — | W |
| CHK-M3-084 | CODE | REQ-078 (3) | For a given `now`: expire touches exactly `queued` jobs with `pickup_by <= now` (`finished_at` set); stale-inventory failure touches exactly inventory jobs `dispatched` with `dispatched_at <= now − 30 min`; boundaries at 29 min 59 s and 30 min 1 s; returns counts; no row created | 30 hours (G33 plant) | W |
| CHK-M3-085 | CODE | REQ-077 (2), REQ-079 (2) | Open-job check true for `queued`, `dispatched`, `running` inventory jobs and false for `completed`, `failed`, `expired`, `cancelled`; oldest queued age counts only jobs of `online` agents (#66) | — | W |
| CHK-M3-086 | CODE | REQ-076 | Lookup for an agent returns the job only when it belongs to that agent; complete and fail set state and `finished_at` | — | W |

## TASK-055 Runtime settings (REQ-083, REQ-088; TP-M3-09)

Tests in `manager/tests/test_settings_service.py` (L) and `manager/tests/test_settings_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-090 | APP | REQ-083 (1), #42 | On a freshly migrated database the typed read returns exactly the seven TS §8.6 defaults, `inventory_interval_s` 21,600 read from `system_schedule` (changed there as owner → the read follows) and the five redaction patterns byte for byte | interval read from `setting` | W |
| CHK-M3-091 | CODE | REQ-083 (2) | Pure validation: every numeric key at its minimum and maximum passes; one below and one above fail; `true`, `1.5`, `"300"`, `null` fail; an unknown key fails, including `inventory_enabled`, `inventory_disabled`, `enabled`; an empty patch fails (#68: non-empty subset) | range off by one | L |
| CHK-M3-092 | CODE | REQ-083 (2) | A patch mixing one valid and one invalid key fails as a whole (nothing returned as applied) | per-key apply | L |
| CHK-M3-093 | CODE | REQ-083 (3), REQ-088 (2) | `inventory_interval_s` 3,599 and 86,401 fail, 3,600 and 86,400 pass; no value (0, negative, null) disables inventory | range check removed (CHK-M3-354, red in TASK-062 TEST as a 500) | L |
| CHK-M3-094 | CODE | REQ-088 (2) | No key, constant or model field in `bm/services/settings/` or `bm/repositories/settings.py` names an inventory switch (`inventory_enabled` and similar; text scan plus the validator) | `inventory_enabled` accepted (CHK-M3-352) | L |
| CHK-M3-095 | CODE | TASK-055 | The settings repository updates `setting` and `system_schedule` only through the columns TS §5.2 grants; no DELETE on `system_schedule` (statement capture as `bitscan_app`) | — | W |

## TASK-056 Alert kinds, threshold windows, metrics (REQ-065, REQ-070, REQ-073, REQ-075, REQ-079, REQ-086; TP-M3-10)

Tests in `manager/tests/test_thresholds.py` (L) and `manager/tests/test_alerts.py` (extended).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-100 | CODE | TASK-056 acceptance | Sliding-count window, fake clock: with threshold N, counts 1 … N raise nothing, N + 1 raises once; more events inside the period raise nothing; after the period another excess raises again; events older than the window no longer count (window 60 s, 10 min, 24 h variants) | raise at N; raise per event | L |
| CHK-M3-101 | CODE | TASK-056 | Once-per-period window (per key): raises at the first excess, not again within the period, again after; keys independent | shared key | L |
| CHK-M3-102 | CODE | TASK-056, #65 (b), (g) | Re-arm window: raises when the value first exceeds the threshold; staying above raises nothing; dropping to exactly the threshold re-arms; exceeding again raises again | re-arm only below threshold | L |
| CHK-M3-103 | CODE | REQ-079 (5), #71 | Every #71 kind is accepted by `raise_alert` (one entry, `detail.alert` true, `alert_kind`), an unknown kind refused; every kind is exported at 0 in `bitscan_alerts_total{kind}` before any alert; the counter rises only after commit | kind missing | L |
| CHK-M3-104 | CODE | REQ-086 (3) | New metrics (agents by status, heartbeat latency, jobs queued, jobs expired) are in the shared registry; label names and values bounded: `status` only from the agent status enum, `kind` only from the alert kinds; no label named or valued like a hostname, agent id or token | `agent_id` label | L |
| CHK-M3-105 | CODE | REQ-086 | Windows and counters hold no unbounded state: after the window passes and the clock moves, 10,000 distinct keys are dropped (size accessor) | keys never dropped | L |

## TASK-057 Agent rate limits (REQ-065, REQ-076; TP-M3-11)

Tests in `manager/tests/test_ratelimit.py` (extended), fake clock.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-110 | CODE | REQ-065 (1) | 30 requests of agent A allowed, the 31st refused with retry-after = seconds to the window end; agent B unaffected; next window allowed | limit removed (CHK-M3-364) | L |
| CHK-M3-111 | CODE | REQ-065 (2) | 10 enrol attempts from IP X allowed, the 11th refused; IP Y unaffected; next window allowed; the enrol counter is separate from the M2 sign-in counter (10 sign-ins plus 10 enrolments from one IP all allowed) | shared counter; limit removed (CHK-M3-365) | L |
| CHK-M3-112 | CODE | REQ-076 (3), #72 (e) | Unscheduled upload: first allowed; a second at 9 min 59 s refused with retry-after 1; at 10 min allowed; per agent | window 9 min; removed (CHK-M3-358) | L |
| CHK-M3-113 | CODE | REQ-065 | Keys are dropped after their window (size accessor back to 0 after 10,000 agents and IPs) | — | L |
| CHK-M3-114 | CODE | REQ-065 | The extended `RateLimits` protocol is implemented by the runtime limiter and by the test fakes (mypy on the test module); the M2 rate-limit tests stay green | — | L |

## TASK-058 Dev-only test libraries (REQ-061, REQ-074; TP-M3-12)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-001 | CODE | TASK-058, G4 | Fresh 3.12 venvs (bundled pip): `pip install --require-hashes -r manager/requirements-dev.txt` exits 0 on L and on W; `python -c "import jsonschema, hypothesis"` exits 0 | — | L, W |
| CHK-M3-002 | CODE | G4 | A copy of the dev lock with one `hypothesis` hash altered by one character: install exits non-zero with the hash message | altered `hypothesis` hash | L |
| CHK-M3-003 | CODE | TASK-058 | `manager/requirements.txt` byte-identical to `HEAD` (`git diff --exit-code`); `tests/test_lock_files.py` green (runtime lock has neither package; dev lock is a superset) | `hypothesis` in the runtime lock | L |
| CHK-M3-004 | CODE | TASK-058 | The command recorded in the dev-lock header, rerun with its cutoff in a temp folder, reproduces the dev lock byte for byte | hand-edited lock | L (needs PyPI) |
| CHK-M3-005 | CODE | TASK-058 | Every Linux-applicable line of the dev lock has a matching wheel hash for cp312 manylinux x86_64 and aarch64 (M1 proxy script), in particular the new packages and their dependencies | — | L (needs PyPI) |

## TASK-059 Agent token check (REQ-064, REQ-071; TP-M3-13)

Tests in `manager/tests/test_token_check.py` (L), fake repositories and clock.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-120 | CODE | REQ-064 (1) | Each row of the plan outcome table (unknown, rejected request, rejected new agent, revoked, expired, mismatch, missing header, malformed header, pending new, pending re-enrolment, mismatch on a pending request, previous before first use, overlap, after overlap, first use of the new token, decommissioned) gives exactly its status, `type`, `counted` and side effect (revoke, alert, `prev_token_expires_at`) | — | L |
| CHK-M3-121 | CODE | #59 order | States that match several rows (revoked and expired; expired and mismatching; revoked and pending) give the earlier row's answer | order swapped | L |
| CHK-M3-122 | CODE | REQ-064 (5) | Accepted 1 s before `token_expires_at`, refused at it with `token_expired` | `<` vs `<=`; one day late (CHK-M3-342) | L |
| CHK-M3-123 | CODE | REQ-064 (2), #63 | Mismatch: one revoke, one `machine_id_mismatch` alert, then the same token with the right header gets `token_revoked`; missing and malformed headers behave the same | no revoke (CHK-M3-340); missing header accepted (CHK-M3-341) | L |
| CHK-M3-124 | CODE | REQ-064 (8) | `pending_approval` is never counted; every 401 is | pending counted | L |
| CHK-M3-125 | CODE | REQ-071 (4), #62 | Previous token at 9 min 59 s after the new token's first use accepted; at 10 min refused with `token_revoked`, both tokens revoked, one `token_reuse` alert | reuse accepted (CHK-M3-344) | L |
| CHK-M3-126 | CODE | REQ-064 (6), (7) | `awaiting_approval` agent's token → 403 `pending_approval` (CHK-M3-339); decommissioned agent → 401 `token_revoked` | — | L |
| CHK-M3-127 | CODE | REQ-087 | Canary token: no log record, exception text or `repr` holds it or its hash | token logged | L |

## TASK-060 Inventory decoder (REQ-074; TP-M3-14; G32)

Tests in `manager/tests/test_inventory_decode.py` and `manager/tests/test_inventory_fuzz.py` (hypothesis; profile with a fixed `max_examples` and `deadline` so CI time is bounded).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-130 | CODE | REQ-074 (5) | Each valid TP-M3-01 inventory fixture, gzipped, decodes to exactly its values (empty `source` → None) | — | L |
| CHK-M3-131 | CODE | REQ-074 (3) | `list_sha256` of each fixture equals the test's independent computation; a package list given in reverse order hashes the same | trusted agent hash (CHK-M3-357) | L |
| CHK-M3-132 | CODE | REQ-074 (1) | Decompressed exactly 67,108,864 bytes passes the cap stage; 67,108,865 → 413 after at most cap + 1 decompressed bytes (counting wrapper around the decompressor output) | whole-body decompress (CHK-M3-355) | L |
| CHK-M3-133 | CODE | REQ-074 (1) | Gzip bomb (about 1 MiB of gzip expanding to 1 GiB of zeros, built in the test): 413 within the bound; peak traced memory (`tracemalloc`) under 256 MiB; time recorded | — | L |
| CHK-M3-134 | CODE | REQ-074 (2), #72 | 50,001 packages → 422 (with no package returned); 50,000 passes; each over-length field (each package field, each `os_info` string) → 422; `raw` of 262,145 compact bytes → 413 and 262,144 passes; a duplicate `(name, version, architecture)` → 422; hash mismatch → 422 | row check after returning packages; row check removed (CHK-M3-356) | L |
| CHK-M3-135 | CODE | REQ-074, #72 (c) | Not gzip, truncated gzip, gzip with trailing garbage, invalid UTF-8, invalid JSON, JSON that is not an object: each the #72 400 refusal | trailing data accepted | L |
| CHK-M3-136 | CODE | REQ-074 (4) | Property: random bytes, random gzip of random bytes, truncations of a valid body at random offsets, random JSON (hypothesis `recursive`), deep nesting (100,000 levels), invalid UTF-8: only `InventoryRefused` (or a complete `DecodedInventory`) ever comes out; never another exception, never partial data | bare `json.loads` RecursionError | L |
| CHK-M3-137 | CODE | REQ-087 | Refusal reasons are fixed words; a canary package name, version and `raw` value appear in no refusal, log or `repr` | input echoed in `reason` | L |
| CHK-M3-138 | CODE | TASK-060 | `gunzip_capped` used by the results path: 1,572,865 decompressed → refusal after at most cap + 1 bytes | — | L |

## TASK-061 Inventory queueing (REQ-077, REQ-088; TP-M3-15)

Tests in `manager/tests/test_inventory_queue_pg.py` (marker `pg`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-140 | APP | REQ-077 (1) | Agents in every status: one run queues exactly one job each for `enrolled`, `online`, `stale`, `offline`, none for `decommissioned`, `awaiting_approval` | `offline` skipped (G33 plant) | W |
| CHK-M3-141 | APP | REQ-077 (2) | A second run adds nothing while jobs are `queued`, `dispatched` or `running`; once `completed`, `failed`, `expired` (and `cancelled`), the next run queues again | — | W |
| CHK-M3-142 | APP | REQ-077 (3) | Two runs at once (threads, barrier, repeated 10 times), and a run concurrent with `queue_first_inventory`: one open job per agent | advisory lock removed | W |
| CHK-M3-143 | APP | REQ-077 (5) | Payload exactly four keys, `pickup_by` = `created_at` + 24 h | — | W |
| CHK-M3-144 | APP | REQ-077 (6), #36 | `queue_first_inventory` queues one job unless one is open | — | W |
| CHK-M3-145 | CODE | REQ-088 (2) | No parameter, setting or flag skips the run (signature check; a planted `inventory_enabled` read is red, CHK-M3-352) | as stated | L |
| CHK-M3-146 | CODE | REQ-080 (5) | The scheduler package opens no network client (CHK-M3-305 static check subset) | `httpx` import | L |

## TASK-062 Settings routes (REQ-083, REQ-088; TP-M3-16)

Tests in `manager/tests/test_settings_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-150 | APP | REQ-083 (1), (5) | `GET /api/v1/settings` by an admin `bsk_` and an admin session: the seven keys with the defaults; an operator and a viewer: 403 | — | W |
| CHK-M3-151 | APP | REQ-083 (2), (3) | PATCH with each key at its minimum and maximum succeeds (200, all keys returned) and reads back; `inventory_interval_s` in `system_schedule` | — | W |
| CHK-M3-152 | APP | REQ-083 (2) | Out-of-range, wrong-type, unknown-key (`inventory_enabled`), empty and mixed bodies: 400 `invalid_request`, nothing changed, no audit entry | per-key apply; range check only in the database (CHK-M3-354: 3,599 answered 500) | W |
| CHK-M3-153 | APP | REQ-083 (4) | One successful PATCH writes exactly one `settings.change` entry and one `settings_changed` alert entry holding old and new values (one entry per event per #71: if the plan merges them, ask) | — | W |
| CHK-M3-154 | APP | REQ-083 (5) | PATCH refused for an admin `bsk_` (403 `totp_session_required`), an unverified admin session, operator and viewer sessions, and any session while the sink gate refuses (503) | `require_role` (CHK-M3-331); `sink_gate=False` (CHK-M3-328) | W |
| CHK-M3-155 | APP | REQ-083 (6) | After `agent_token_ttl_days` changes, existing agents' `token_expires_at` unchanged | — | W |
| CHK-M3-156 | CODE | G6, REQ-060 (5) | OpenAPI re-export clean; error contract (CHK-M3-017 style for the user routes) | — | L |

## TASK-063 Agent router and `bsa_` dependency (REQ-062, REQ-064, REQ-065, REQ-066, REQ-087; TP-M3-17)

Tests in `manager/tests/test_agent_auth_pg.py` (W). A test app with one `bsa_` route behind the real dependency; real `agent` and `enrollment_request` rows.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-160 | APP | REQ-062 (2) | No header, `Basic`, `Token`, empty bearer, two `Authorization` headers, token only in query or cookie, valid admin `bsu_` and `bsk_`, a valid `bse_` of a live enrolment token, unknown `bsa_`, unknown prefix: 401 `unauthorized`, one byte-identical body | `bse_` accepted (CHK-M3-320); user parser (CHK-M3-321) | W |
| CHK-M3-161 | APP | REQ-064 (1) | revoked, expired, mismatch, missing machine-id header, pending new, pending re-enrolment, rejected new, rejected re-enrolment: exactly the #59 outcome | — | W |
| CHK-M3-162 | APP | REQ-064 (6) | Agent A's token on B's path: 403 `forbidden`, not counted, B's rows unchanged | `{id}` match removed (CHK-M3-338) | W |
| CHK-M3-163 | APP | REQ-065 (1) | 31st request of one agent in a minute: 429 `rate_limited` + `Retry-After`; another agent unaffected; next minute accepted | — | W |
| CHK-M3-164 | APP | REQ-065 (3), REQ-062 (4) | 20 bad agent tokens from one IP → 401, the 21st → 429; a valid `bsa_` from that IP still 200; one aggregated entry counting all 21 together with user-route failures from that IP | failures not counted (CHK-M3-362); valid token 429 (CHK-M3-363) | W |
| CHK-M3-165 | APP | REQ-065 (4), #65 (d) | More than 20 401s in a minute for tokens resolving to one agent: one `agent_auth_failures` alert; no second within the hour | — | W |
| CHK-M3-166 | APP | #25 | An accepted call sets `agent.last_seen_ip` and upserts `agent_ip_seen`; a refused one does not | — | W |
| CHK-M3-167 | APP | REQ-087 (1) | Records written during an accepted request carry its `agent_id` (and `job_id` on a job route); canary sweep of tokens over the whole matrix | `Authorization` logged (CHK-M3-366) | W |
| CHK-M3-168 | APP | REQ-066 (3) | After-auth routes: over-cap body with an invalid token → 401 (no byte read); with a valid token → 413 | — | W |
| CHK-M3-169 | CODE | REQ-062 (1) | Route walk: every operation under `/api/v1/agent/` other than enrol carries the agent dependency; the router is mounted at `/api/v1/agent` with no user dependency; database down → 503 `about:blank`, not counted | — | L, W |

## TASK-064 Inventory ingestion (REQ-075; TP-M3-18)

Tests in `manager/tests/test_inventory_ingest.py` (L, fakes) and `manager/tests/test_inventory_ingest_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-170 | APP | REQ-075 (1) | First upload of N packages: one `os_info` row (`collected_at` = fake now), N `agent_package` rows, one snapshot with all N in `added`, `removed` empty; `last_inventory_at` = now | — | W |
| CHK-M3-171 | APP | REQ-075 (2) | Same list again: `os_info` replaced, `last_inventory_at` moved, no new snapshot, `agent_package` unchanged | snapshot on every upload | W |
| CHK-M3-172 | APP | REQ-075 (3), #69 | One upgrade and one removal: one snapshot, `added` = new line of the upgrade, `removed` = old line of the upgrade and the removed line; the removed `agent_package` row gone, its `package` row kept; a status change counts as old in `removed`, new in `added` | — | W |
| CHK-M3-173 | APP | REQ-075 (4) | A failure forced after the package insert (fake or trigger-free injection in the repo wrapper): no change for that agent (`os_info`, `agent_package`, snapshot, `last_inventory_at`); `package` rows from that attempt also rolled back | commit between steps | W |
| CHK-M3-174 | APP | REQ-075 (6) | Two agents upload the same new package at once: one `package` row | — | W |
| CHK-M3-175 | APP | REQ-075 (7), #65 (e) | 1,000 new packages in 24 h: no alert; 1,001: one `new_packages_burst`; more within 24 h: none; packages already in the fleet do not count | alert at 1,000 | L, W |
| CHK-M3-176 | CODE | G5 | The G5 plant for M3 lives here (owner notes); sized at the gate | — | L |

## TASK-065 `offline_sweep` core (REQ-078; TP-M3-19; G33)

Tests in `manager/tests/test_sweep_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-180 | APP | REQ-078 (1) | Ages 9 min 59 s, 10 min, 29 min 59 s, 30 min, 30 min 1 s → `online`, `stale`, `stale`, `stale`, `offline` | `<=` at 10 min | W |
| CHK-M3-181 | APP | REQ-078 (1), #25 | Never-heartbeat agent aged from `enrolled_at` (and from the approval time) | — | W |
| CHK-M3-182 | APP | REQ-078 (2), #73 (b) | `decommission_after_days` 7: offline for 7 days + 1 s → `decommissioned`, `token_revoked_at` set, its token then 401 `token_revoked`, one `agent.decommission` entry (actor `system`); exactly 7 days → not yet; setting 0 → never | never decommissions; no revoke (CHK-M3-369) | W |
| CHK-M3-183 | APP | REQ-078 (3) | Queued past `pickup_by` → `expired`; inventory dispatched 30 min 1 s → `failed` with `finished_at`; 29 min 59 s unchanged; no job row created | retry row (CHK-M3-373); 30 h (G33) | W |
| CHK-M3-184 | APP | REQ-078 (4) | `awaiting_approval` and `decommissioned` agents untouched by the status step | — | W |
| CHK-M3-185 | APP | REQ-078 (5) | One step forced to fail: the others applied; the next sweep completes | one transaction for all | W |
| CHK-M3-186 | APP | REQ-078 (6), #73 (d) | Status changes `online`/`stale`/`offline` write no audit entry | — | W |
| CHK-M3-187 | APP | REQ-086 (2) | Jobs-expired counter rises by the number expired, after commit | — | W |
| CHK-M3-188 | APP | REQ-078 | 10,000 agents: sweep duration recorded (no gate) | — | W |

## TASK-066 Enrolment tokens API (REQ-067, REQ-063; TP-M3-20)

Tests in `manager/tests/test_enrolment_tokens_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-190 | APP | REQ-067 (1) | `POST {}` → 201: `max_uses` 1, `expires_at` = now + 24 h, `allowed_cidrs` null, `auto_approve` false, `uses` 0; exact #68 keys; token format CHK-M3-040 | `auto_approve` default true (CHK-M3-336) | W |
| CHK-M3-191 | APP | REQ-067 (2) | `max_uses` 0, 10,001, `expires_in_hours` 0, 721, an invalid CIDR, a CIDR with host bits, 65 CIDRs, an empty list (if #68 requires 1 to 64), wrong types: 400, no row | — | W |
| CHK-M3-192 | APP | REQ-067 (3), REQ-063 (2), (5) | Token in the create response only; list and `GET /{token_id}` contain neither the token nor `token_hash`; stored hash = SHA-256 of the token | raw token stored (CHK-M3-325) | W |
| CHK-M3-193 | APP | REQ-067 (4) | `auto_approve: true` → one `enrolment_token_risky` alert; `max_uses: 101` → one; both → one entry flagging both; `max_uses: 100` without auto-approve → none; one `enrollment_token.create` entry each | — | W |
| CHK-M3-194 | APP | REQ-067 (5) | Every method refused for an admin `bsk_`, an unverified admin session, operator and viewer sessions; every method refused while the sink gate refuses | `bsk_` creates (CHK-M3-329); sink gate off (CHK-M3-328) | W |
| CHK-M3-195 | APP | REQ-067 (6) | `DELETE` → 204, again 204; row kept with `revoked_at`; one `enrollment_token.revoke` entry; enrolling with it refused (in TASK-067 TEST) | — | W |

## TASK-067 `POST /api/v1/agent/enroll` (REQ-068, REQ-065, REQ-077; TP-M3-21)

Tests in `manager/tests/test_enrol_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-200 | APP | REQ-068 (1), REQ-062 (2) | Expired, revoked, outside CIDR, exhausted, unknown `bse_`, a `bsa_`, `bsu_`, `bsk_`, no header: 401 `unauthorized`, one body; no row changes; `uses` unchanged; counted as failed checks | `bsa_` accepted (CHK-M3-322) | W |
| CHK-M3-201 | APP | REQ-068 (2) | 20 concurrent enrolments from 20 machine-ids on a 5-use token: exactly 5 succeed, `uses` 5 | (CHK-M3-332 through the API) | W |
| CHK-M3-202 | APP | REQ-068 (3) | New + auto-approve: agent `enrolled`, no request, `status: "enrolled"`, one inventory job (#36); new without: agent `awaiting_approval` with the hash, one `kind = 'new'` request, no job; existing machine-id: existing `agent_id`, `kind = 'reenrol'` request holding the hash, agent row unchanged; `token_expires_at` = `issued_at` + TTL; response validates against the Enrol schema and fixtures | — | W |
| CHK-M3-203 | APP | REQ-068 (4) | Re-enrolment with an auto-approve token is held; existing agent's token hash, status, tags, `os_info` unchanged; old token still works | approved at once (CHK-M3-337) | W |
| CHK-M3-204 | APP | REQ-068 (5) | IPv6 source and a mixed IPv4/IPv6 CIDR list | — | W |
| CHK-M3-205 | APP | REQ-068 (6), #61 | `enrolment_alert_per_hour` 3: the 4th enrolment on one token within 60 min writes one `enrolments_per_hour` alert; the 5th none | — | W |
| CHK-M3-206 | APP | REQ-068 (7), REQ-063 (2), (3) | One `agent.enrol` entry per enrolment (detail token id, kind, status, request id; no token); stored hash = SHA-256 of the returned token; no column holds the raw token | raw `bsa_` stored (CHK-M3-324) | W |
| CHK-M3-207 | APP | REQ-065 (2) | 11th attempt from one IP in a minute: 429 (successes and failures count); another IP passes | limit removed (CHK-M3-365) | W |
| CHK-M3-208 | APP | REQ-060 | Request fixtures through the route: every valid one 200/201 (as the Enrol contract says), every invalid one 400 `invalid_request`; G6 and CHK-M3-016/-017 re-run | — | W, L |

## TASK-068 Fleet threshold alerts (REQ-079; TP-M3-22)

Tests in `manager/tests/test_fleet_alerts_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-210 | APP | REQ-079 (1), #65 (b) | 100 eligible agents: 5 offline → nothing; 6 → one `agents_offline`; still 6 next sweep → nothing; back to 5 then 6 → another; decommissioned and awaiting agents not in the denominator | — | W |
| CHK-M3-211 | APP | REQ-079 (2), #66 | Oldest queued job of an online agent 1 h + 1 s old → one `job_queue_age`; exactly 1 h → none; an offline agent's 23 h old job → none; at most one per hour | — | W |
| CHK-M3-212 | APP | REQ-079 (3), #65 (c) | Online agent with `last_inventory_at` 2 × interval + 1 s old → one `inventory_stale`; exactly 2 × interval → none; offline agent → none; again only after its next upload | — | W |
| CHK-M3-213 | APP | REQ-079 (4), #65 (g) | A row inserted as owner into `scan_result_default` → one `default_partition_rows`; repeated sweeps none; emptied then a new row → another | — | W |
| CHK-M3-214 | APP | REQ-079 (5) | Each alert one entry with its kind; `bitscan_alerts_total{kind}` rises after commit only | — | W |

## TASK-069 Redaction-pattern setting (REQ-084; TP-M3-23)

Tests in `manager/tests/test_settings_redaction_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-215 | APP | REQ-084 (1) | 50 valid patterns stored; 51, an RE2-invalid pattern (`(a)\1`, `(?=a)`), a non-string item: 400, no change | — | W |
| CHK-M3-216 | APP | REQ-084 (2) | Removing default pattern 3 writes one `redaction_default_removed` alert plus the settings alert | — | W |
| CHK-M3-217 | APP | REQ-084 (4) | The five defaults read back byte for byte after GET and PATCH round trips | escaping changed | W |
| CHK-M3-218 | CODE | REQ-084 (3), G1 | No stdlib `re` (G1 plant `import re` in `bm/services/settings/redaction.py`) | as stated | L |

## TASK-070 Enrolment requests (REQ-069, REQ-077; TP-M3-24)

Tests in `manager/tests/test_enrolment_requests_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-220 | APP | REQ-069 (1) | List (default `pending`, `decided`, `all`) shows hostname, `source_ip`, `os_pretty_name` and matches (cloned image; shared hostname); exact #68 item keys | — | W |
| CHK-M3-221 | APP | REQ-069 (2), #36 | Approve new: agent `enrolled`, token passes, one inventory job | — | W |
| CHK-M3-222 | APP | REQ-069 (3), #64 | Approve re-enrolment: old token 401, new works, `agent_id`, tags, `os_info`, packages unchanged, `hostname` and version from the request, token columns per #64 (b), one `reenrolment_approved` alert, one inventory job | — | W |
| CHK-M3-223 | APP | REQ-069 (4), #26 | Reject new: agent row kept, `decommissioned`, token 401 `enrollment_rejected`; reject re-enrolment: agent row unchanged, old token works, new token 401 `enrollment_rejected` | reject leaves `awaiting_approval` (CHK-M3-370) | W |
| CHK-M3-224 | APP | REQ-069 (5), #64 (e) | Second decision 409; two concurrent decisions one success; approving a request whose token expired 409 | — | W |
| CHK-M3-225 | APP | REQ-069 (6) | Approve and reject refused for an admin `bsk_`, an unverified session, an operator session and during the sink gate; `GET` works with an admin `bsk_`, refused for an operator | `require_role("admin")` (CHK-M3-326); verified check skipped (CHK-M3-327); operator allowed (CHK-M3-371); sink gate off (CHK-M3-328) | W |
| CHK-M3-226 | APP | REQ-069 | One audit entry per decision | — | W |

## TASK-071 Scheduler in `serve` (REQ-080; TP-M3-25; G27, G29)

Tests in `manager/tests/test_serve_scheduler_linux.py` (W, also as `bstester`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-230 | APP | REQ-080 (1) | Real `serve` with a 2 s `offline_sweep` interval set as owner: the sweep runs repeatedly (status changes observed) and inventory jobs are queued at start-up | — | W |
| CHK-M3-231 | APP | REQ-080 (1) | A run that raises (made to fail by a test hook or a revoked grant in a copy) is logged by type only and the next run happens | — | W |
| CHK-M3-232 | APP | REQ-080 (2) | Overlapping runs never execute at once (a slow run longer than the interval; instrumented counter of concurrent runs ≤ 1) | `max_instances` > 1 | W |
| CHK-M3-233 | APP | REQ-080 (3), (4) | `SIGTERM` exits 0; no run starts after the pool closed; G29 telemetry checks pass on the final `create_app()`; runtime lock has no OTel SDK or exporter | pool closed before the scheduler stops (G27 plant) | W |
| CHK-M3-234 | APP | #67 | An interval change through `PATCH /settings` takes effect within one sweep interval | — | W |

## TASK-072 Heartbeat (REQ-070, REQ-086, REQ-088; TP-M3-26)

Tests in `manager/tests/test_heartbeat_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-235 | APP | REQ-070 (1) | Response exactly three keys, current settings; after `PATCH job_pull_seconds` the next heartbeat returns the new value; `server_time` = fake clock in RFC 3339 UTC | `jobs` key (CHK-M3-345) | W |
| CHK-M3-236 | APP | REQ-070 (2), #73 (a) | `last_heartbeat_at`, `last_seen_ip`, `agent_version` stored; `enrolled`, `stale`, `offline` → `online` at once | — | W |
| CHK-M3-237 | APP | REQ-070 (3) | `runner_helpers` `[]` → `["capread"]`: one `agent.runner_helpers_change` entry and one `runner_helper_changed` alert; same list again: nothing | no audit/alert (CHK-M3-368) | W |
| CHK-M3-238 | APP | REQ-070 (4), #65 (a) | `clock` 5 min 1 s off (both directions) → one `clock_skew` alert holding both times; exactly 5 min → none; a second skewed heartbeat within the hour → none; manager clock 150 days ahead of three agents → each first heartbeat alerts | alert removed (CHK-M3-367) | W |
| CHK-M3-239 | APP | REQ-070 (5) | No `scan_job` row created or changed | — | W |
| CHK-M3-240 | APP | REQ-070 (6), REQ-087 (1), #25 (a) | `last_error` (canary) is never in an audit entry, an agent row or the response; as #25 (a) allows, it is in exactly one INFO log record, which carries the request's `agent_id` (corrected 2026-10-23: the draft said "or log record", which contradicts the agreed #25 (a)); every record of the request carries the `agent_id`; no token is logged | — | W |
| CHK-M3-241 | APP | REQ-086 (2) | 3 heartbeats → latency histogram count 3 | — | W |
| CHK-M3-242 | APP | REQ-060 | Heartbeat request fixtures through the route (valid 200, invalid 400); G6, CHK-M3-016/-017 | — | W, L |

## TASK-073 Job pull and results (REQ-072, REQ-073, REQ-087, REQ-088; TP-M3-27)

Tests in `manager/tests/test_jobs_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-245 | APP | REQ-072 (1), (5) | 12 queued → 10 oldest first, then 2, then `{"jobs": []}`; each dispatched once; empty pull changes nothing | — | W |
| CHK-M3-246 | APP | REQ-072 (2) | Concurrent pulls never share a job | (CHK-M3-350 via the API) | W |
| CHK-M3-247 | APP | REQ-072 (3), (4) | Another agent's, non-`queued`, past-`pickup_by` and an owner-planted compliance job (with `eval_spec`) never returned; no response has `eval_spec`, `operator`, `expected` | (CHK-M3-346, -347, -349, -351) | W |
| CHK-M3-248 | APP | REQ-072 (6) | Every pull response validates against the job-pull schema and the fixture shape | — | W |
| CHK-M3-249 | APP | REQ-073 (1), (2) | A valid batch for an own inventory job, an unknown job, another agent's job, and a start notice: each 409 `job_not_acceptable`, one `agent.result_refused` entry without stdout/stderr, no `scan_result` row, no job state change | 200 or a stored row (CHK-M3-359) | W |
| CHK-M3-250 | APP | REQ-073 (3), REQ-066 (1), (4) | Malformed body 400; 1,572,865 bytes as sent 413; gzip body decompressing to 1,572,865 bytes 413 after at most cap + 1 decompressed bytes | — | W |
| CHK-M3-251 | APP | REQ-073 (4), #54 (c) | 20 refused posts in 10 min → no alert; 21 → one `result_409_flood`; more within the hour → none | — | W |
| CHK-M3-252 | APP | REQ-073 (5), REQ-087 (1) | Canary stdout/stderr never in any log record; records carry `agent_id` and `job_id` | stdout logged (CHK-M3-366) | W |
| CHK-M3-253 | APP | REQ-060 | Results request fixtures through the route (valid → 409 in M3, invalid → 400); G6, CHK-M3-016/-017 | — | W, L |

## TASK-074 Inventory upload route (REQ-076, REQ-066; TP-M3-28)

Tests in `manager/tests/test_inventory_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-255 | APP | REQ-076 (1) | Dispatched job's id → 204, job `completed`, `finished_at` set, data stored | — | W |
| CHK-M3-256 | APP | REQ-076 (2) | Failed job's id → 204, stored, job stays `failed`; completed job's id → 204, stored | — | W |
| CHK-M3-257 | APP | REQ-076 (3), #72 (e) | Unscheduled uploads 9 min 59 s apart: second 429 + `Retry-After`; 10 min apart: both 204; a refused (413/422/400) unscheduled upload also starts the window; a dispatched-job upload is exempt | limit removed (CHK-M3-358) | W |
| CHK-M3-258 | APP | REQ-076 (4) | Over-cap (10,485,761 as sent) upload naming a dispatched job → 413, job `failed`, one `agent.inventory_refused` entry; same for a 422 cause (hash mismatch) | after-auth removed (CHK-M3-361) | W |
| CHK-M3-259 | APP | REQ-076 (5) | Unknown, another agent's, compliance (owner-planted), `queued`, `expired`, `cancelled` job ids → 409 `job_not_acceptable`, audit entry, nothing stored | — | W |
| CHK-M3-260 | APP | REQ-076 (6), #72 (a), (c) | Non-UUID `job_id` → 400; no `Content-Encoding: gzip` → 400; malformed gzip/JSON → 400, audit entry, job left `dispatched` | — | W |
| CHK-M3-261 | APP | REQ-066 (1) | A valid 2 MiB (as sent) inventory → 204; exactly 10,485,760 bytes passes the cap stage | template matching removed (CHK-M3-360) | W |
| CHK-M3-262 | APP | REQ-087 | Canary package names and `raw` values in no log record | body logged | W |
| CHK-M3-263 | APP | REQ-060 | Inventory fixtures through the route (valid → 204, invalid → 400/413/422 per #72); G6, CHK-M3-016/-017 | — | W, L |

## TASK-075 Token rotation (REQ-071; TP-M3-29)

Tests in `manager/tests/test_rotation_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-265 | APP | REQ-071 (1) | TTL 365: rotate at day 334 + 23 h 59 min 59 s → 403 `forbidden` + `rotation_outside_window`; at day 335 → 200, Rotate schema, `expires_at` = now + current TTL | window removed (CHK-M3-343) | W |
| CHK-M3-266 | APP | REQ-071 (2) | TTL 60: refused at day 29 d 23 h 59 min 59 s, accepted at day 30 | — | W |
| CHK-M3-267 | APP | REQ-071 (3) | Lost response: second rotate with the old token → another token; the first new token then 401; old still works | — | W |
| CHK-M3-268 | APP | REQ-071 (4), #62 | Old token at 9 min 59 s after the new token's first use → 200; at 10 min → 401 `token_revoked`, both revoked, one `token_reuse` alert; rotate with the old token after first use → reuse | (CHK-M3-344) | W |
| CHK-M3-269 | APP | REQ-071 (5) | Second rotation within 24 h after a used one → 429 + `Retry-After` to the end of 24 h; after an unused one → allowed | — | W |
| CHK-M3-270 | APP | REQ-071 (6) | Never-seen IP → one `rotation_new_ip`; last seen 6 days ago → none; 8 days → one | — | W |
| CHK-M3-271 | APP | REQ-071 (7) | After `expires_at` rotate → 401 `token_expired` | (CHK-M3-342) | W |
| CHK-M3-272 | APP | REQ-071 (8) | TTL change applies only to tokens issued or rotated afterwards | — | W |
| CHK-M3-273 | APP | REQ-060, #60 | Rotate with an empty body and `{}` → 200; `{"x": 1}` → 400; one `agent.token_rotate` entry, no token in it; G6, CHK-M3-016/-017 | — | W, L |
| CHK-M3-273-r2 | APP | REQ-071, #62 | Added 2026-10-23 (user ruling, "TASK-075 revision 2 ordered"): two rotates with the same current token, both checked before either rotates (agent row held `FOR UPDATE` until both wait), give one rotation and one lost-response retry: both 200, no `rotation_outside_window`, the 7-day new-IP rule applied; four simultaneous rotates are one rotation and three retries; a waiting call whose concurrent rotation's new token was already used issues nothing (429) | no post-lock re-check | W |

## TASK-076 Fleet read routes (REQ-081; TP-M3-30)

Tests in `manager/tests/test_agents_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-275 | APP | REQ-081 (1), (2) | Viewer `bsk_` reads `/agents`, `/agents/{id}`, `/agents/{id}/packages` with exactly the #68 fields (and `last_snapshot` #69); no token → 401; unknown id → 404 | — | W |
| CHK-M3-276 | APP | REQ-081 (3) | Paging N + 1 agents and packages with `limit=N` returns each once (N ∈ {1, 2, 50}) | — | W |
| CHK-M3-277 | APP | REQ-081 (4) | `<script>` hostname, package name and `raw` value come back verbatim as JSON strings | — | W |
| CHK-M3-278 | APP | REQ-081 (5), REQ-063 (5) | No response holds `token_hash`, `prev_token_hash` or any token (canary tokens and their hashes swept) | — | W |

## TASK-077 Tags and revoke (REQ-082; TP-M3-31)

Tests in `manager/tests/test_agents_admin_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-280 | APP | REQ-082 (1), #68 | Operator sets `["prod-web", "db"]` then `[]`; 33 tags, a 65-character tag, a bad character, a duplicate: 400, no change; viewer 403 | viewer allowed (CHK-M3-372) | W |
| CHK-M3-281 | APP | REQ-082 (2) | After revoke: current and previous token 401 `token_revoked`; a re-enrolment of that machine-id is held; status unchanged (#73 (c)) | — | W |
| CHK-M3-282 | APP | REQ-082 (3) | Revoke refused for an admin `bsk_`, unverified session, during the sink gate; 204 again on repeat | `bsk_` revokes (CHK-M3-330); sink gate off (CHK-M3-328) | W |
| CHK-M3-283 | APP | REQ-082 (4) | One `agent.tags_set` / `agent.revoke` entry per change | — | W |

## TASK-078 Audit-log route (REQ-085; TP-M3-32)

Tests in `manager/tests/test_audit_log_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-285 | APP | REQ-085 (1) | Admin `bsk_` pages through every entry once, newest first; operator 403 | — | W |
| CHK-M3-286 | APP | REQ-085 (2) | Items are the eight columns; the chain re-verifies from the returned items with `compute_row_hash` | — | W |
| CHK-M3-287 | APP | REQ-085 (3) | The route writes nothing (row count and newest id unchanged) | — | W |

## TASK-079 Metrics route (REQ-086; TP-M3-33)

Tests in `manager/tests/test_metrics_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-290 | APP | REQ-086 (1), #70 | `GET /api/v1/metrics` with a viewer `bsk_`: Prometheus text (`text/plain; version=0.0.4` or the client library's type) holding `bitscan_alerts_total`, agents by status, heartbeat latency, jobs queued, jobs expired; no token → 401; a `bsa_` → 401 | — | W |
| CHK-M3-291 | APP | REQ-086 (2) | Agents-by-status gauge and jobs-queued gauge equal database counts at scrape time; histogram and expired counter move as REQ-086 (2) | — | W |
| CHK-M3-292 | APP | REQ-086 (3) | No label value is a hostname, token, agent id or other unbounded value (labels parsed from the text) | — | W |

## TASK-080 README (REQ-090) and TASK-081 web (REQ-089; TP-M3-34)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-295 | CODE | REQ-090 (2) | README M3 sections: no real token, DSN or secret, no task id or process note (text scan) | — | L |
| CHK-M3-296 | APP | REQ-090 (1) | Added 2026-10-23 (lead ruling, "REQ-090 (1) README walk-through"): a real `serve` in WSL (HTTPS, PostgreSQL, fake OpenBao and sink, real clock); every request the README documents for M3 (first `bse_` with an admin TOTP session, enrolment tokens, enrol, held, approve and reject, heartbeat, job pull, results, inventory upload and its `job_id` cases, hosts, tags, settings, rotation, revoke, re-enrolment, machine-id, expiry, metrics with a viewer token, audit log re-verified from `detail_text` as the README describes, scheduler, limits, SIGTERM, logs) is sent and its answer compared with the README text; every row recorded (`tests/m3/readme-walk-080.md`); also as `bstester`. File `manager/tests/test_readme_walk_linux.py` | — | W |
| CHK-M3-298 | CODE | REQ-089 (1), G16 | After `npm run gen:api`, `manager/openapi.json` and `web/src/api/` byte-identical (hash before and after), no file added | `openapi.json` changed without regeneration | L, CI |
| CHK-M3-299 | CODE | REQ-089 (2), (3) | `client.test.ts`: `UserPathsArePrefixed` passes and fails on a planted unprefixed path; a type-level call to `GET /api/v1/agents` compiles; `npm run typecheck`, `lint`, `test` pass | as stated | L |

## TASK-082 Every attempt counts on enrol and sign-in (REQ-065, REQ-068, REQ-047; TP-M3-36)

Added 2026-10-23 (user-ordered follow-up; decisions 2026-10-23 "TASK-067 second approval given" and "TASK-082 design", option (B)). Tests in `manager/tests/test_attempt_limits_pg.py` (W); M2 suites re-run.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-380 | APP | REQ-065 (2), REQ-047, #55 (c) | On `POST /api/v1/agent/enroll` and `POST /api/v1/auth/login`, 11 attempts from one IP within a minute with a non-JSON, malformed-JSON, truncated, invalid-UTF-8 or binary body: 10 × 400 `invalid_request` (one identical body), then 429 `rate_limited` with `Retry-After` to the minute's end and the security headers; nothing written; another IP not limited; the next minute open | limit back in a dependency (after the body parse) | W |
| CHK-M3-381 | APP | REQ-065 (2), REQ-068 (1) | Malformed and well-formed attempts share one count: after 10, a correct password gets 429 and no session; a valid `bse_` and body get 429, `uses` unchanged, no agent; the sign-in and enrol limits are separate; a malformed enrol is not a failed token check | — | W |
| CHK-M3-382 | APP | TASK-082 design | The limit is decided before FastAPI parses the body: after 10 attempts the 11th is 429 whatever its body (malformed, valid-shaped, empty); a body over 1 MiB is still 413 from the M2 body-cap middleware, which buffers every normal-mode body before any route (REQ-037; so bytes are read from the client in all cases, corrected 2026-10-23: the draft's "0 bytes pulled" cannot hold for normal-mode routes) | limit after the body parse (K1) | W |
| CHK-M3-383 | CODE | REQ-060 (5), G6 | Only these two operations use the limit-first route class; the enrol `bse_` marker is intact; `requestBody` of each refers to `LoginRequest` / `EnrolRequest`, required, no 422; the login operation and its schemas equal the M2 head export (`git show HEAD:manager/openapi.json`, evidence); G6 | — | L, W |
| CHK-M3-384 | APP | REQ-047 | M2 sign-in suites (`test_login.py`, `test_login_pg.py`), G25 (`test_auth_dependencies.py`, `test_security_m2.py`) and the TASK-067 enrol suite re-run green | — | W |

## M3 security and invariants suite and gate (TP-M3-35; G31, G34)

Tests in `manager/tests/test_security_m3.py` (W) and `manager/tests/test_invariants_m3.py` (L).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-300 | CODE | REQ-088 (1), REQ-062 (1) | Route walk of `create_app()`: every operation is a TS §6.1 or §6.2 route, a health route or `GET /api/v1/metrics`; exactly six under `/api/v1/agent/`; no request schema anywhere has `command`, `script`, `execute` or `plugins`; no query parameter or setting disables inventory. Re-run in every route task | `POST /api/v1/agents/{id}/run` (CHK-M3-353) | L |
| CHK-M3-301 | APP | REQ-062 (2), (3), TS §8.3 Security | Wrong route group on every route: user tokens on all six agent routes → 401; real-row `bsa_` and `bse_` on every user route → 401 | (CHK-M3-320, -321, -322, -323) | W |
| CHK-M3-302 | APP | REQ-087 (2), G28 | Canary sweep over the API chain below plus failures: no `bsa_`/`bse_` token, stdout, stderr, package name or `raw` value in any log record, stdout or stderr, and `last_error` only in its one #25 (a) INFO record; tokens appear only in their one creating response | (CHK-M3-366) | W |
| CHK-M3-303 | APP | REQ-063 (3) | After 20 enrolments, 5 rotations and 5 enrolment tokens: no text, char or JSON column of any table (as owner) contains any issued token | (CHK-M3-324, -325) | W |
| CHK-M3-305 | CODE | REQ-088 (3), REQ-080 (5) | Static check: no HTTP or raw-socket client (`httpx`, `requests`, `urllib.request`, `http.client`, `socket`, `aiohttp`, `ssl.wrap_socket`) imported in `services/agents`, `services/enrolment`, `services/jobs`, `services/scheduler`, `services/inventory` | `httpx` call in `bm/services/agents/heartbeat.py` (CHK-M3-374) | L |
| CHK-M3-317 | APP | REQ-060 to REQ-088 | API chain: create `bse_` (TOTP session) → enrol held → approve → heartbeat → pull the inventory job → upload → `GET /agents/{id}` shows `os_info` and the snapshot → rotate → use the new token → revoke → both tokens 401 | — | W |
| CHK-M3-304 | CODE | G6 | Export then diff and untracked check; an agent route added in `bm/api/agent/heartbeat.py` without re-export is red | as stated | L |
| CHK-M3-306 | CODE | G1 | ruff exit 0; f-string SQL in `bm/repositories/agents.py` and `import re` in `bm/services/settings/redaction.py` red | as stated | L |
| CHK-M3-307 | CODE | G2 | format check exit 0; misformatted line in `bm/api/agent/dependencies.py` red | as stated | L |
| CHK-M3-308 | CODE | G3 | mypy exit 0; untyped function in `bm/services/inventory/decode.py` red | as stated | L |
| CHK-M3-309 | CODE | G4 | both locks in fresh venvs; altered `hypothesis` hash red (CHK-M3-002) | as stated | L, CI |
| CHK-M3-310 | CODE | G5 | coverage ≥ 85 % from unit tests on L; the owner-notes plant in `bm/services/inventory/ingest.py` (size `> covered / 0.85 − S`, computed from the clean report) red | as stated | L |
| CHK-M3-311 | CODE | G16 | CHK-M3-298 at the M3 head | as stated | L, CI |
| CHK-M3-312 | CODE | G18 | `cd /root/bitscan-tester/manager && CI=true /root/venv-m2/bin/python -m pytest --cov=bitscan_manager/services --cov-fail-under=85 -rs`: all pass, 0 skipped, no container left | any G25 to G34 plant | W, CI |
| CHK-M3-313 | APP | G25 | `tests/test_auth_dependencies.py tests/test_security_m2.py` green with real agent rows | M2 prefix-kind check removed (CHK-M3-323) | W |
| CHK-M3-314 | CODE | G26 | M2 shipper suites unchanged and green | M2 plants | L, W |
| CHK-M3-315 | APP | G27 | `tests/test_serve_linux.py tests/test_serve_scheduler_linux.py` as `bstester` | pool closed before the scheduler stops | W |
| CHK-M3-316 | CODE | G29 | `tests/test_app_hardening.py -k telemetry` | `telemetry=` removed | L |

### Gate additions (2026-10-23, at the M3 gate)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M3-318 | CODE | G5 (user ruling (a), 2026-10-23) | Windows unit tests through the services' Protocol seams for the modules G5 found covered only by PostgreSQL tests: `services/enrolment/{enrol,enrolment_tokens,requests,rotation}.py`, `services/agents/{heartbeat,fleet,admin}.py`, `services/jobs/pull.py`, `services/scheduler/fleet_alerts.py`, `services/settings/store.py` (`apply_patch`), asserting the outcomes the PostgreSQL tests assert (`tests/test_enrolment_services_unit.py`, `tests/test_fleet_services_unit.py`). `services/inventory/upload.py` has no seam and stays PostgreSQL-covered (lead ruling; refactor carried to M4) | the G5 plant of CHK-M3-310 | L |
| CHK-M3-319 | CODE | TASK-084 | Every `bitscan_manager` module (Alembic `env.py` and versions excluded) imports first in a fresh `python -I` interpreter, from the tree under test (`tests/test_module_imports.py`) | the `services.inventory` import cycle restored (module-level `ingest` import in `api/agent/__init__.py`) | L, W |

## Security mutation table (CHK-M3-320 to -374)

The rows are those of `work/tasks.md` "M3 security mutation table". Each is planted in a throwaway copy during the TEST step of the task that owns the code (column "Run in"), must turn the named check red for the planted reason, and is re-planted against the final tree at the gate (CHK-M3-320-374-gate). Rows whose code lands in several tasks are run in the last of them.

| Id | Plant (summary) | Must turn red | Run in |
| --- | --- | --- | --- |
| CHK-M3-320 | agent dependency accepts `bse_` | CHK-M3-160, -301 (unit: CHK-M3-043) | TASK-063 |
| CHK-M3-321 | agent dependency uses the user parser | CHK-M3-160, -301 | TASK-063 |
| CHK-M3-322 | enrol accepts `bsa_` | CHK-M3-200, -301 | TASK-067 |
| CHK-M3-323 | M2 prefix-kind check removed with real agent rows | CHK-M3-313 | TASK-063 (and gate) |
| CHK-M3-324 | raw `bsa_` in `agent.token_hash` | CHK-M3-206, -303 | TASK-067 |
| CHK-M3-325 | raw `bse_` in `enrollment_token.token_hash` | CHK-M3-192, -303 | TASK-066 |
| CHK-M3-326 | approve guarded by `require_role("admin")` | CHK-M3-225 | TASK-070 |
| CHK-M3-327 | TOTP-verified check skipped on approve and reject | CHK-M3-225 | TASK-070 |
| CHK-M3-328 | `sink_gate=False` on approve, reject, revoke, enrolment tokens, `PATCH /settings` | CHK-M3-154, -194, -225, -282 | TASK-062, 066, 070, 077 |
| CHK-M3-329 | admin `bsk_` creates an enrolment token | CHK-M3-194 | TASK-066 |
| CHK-M3-330 | admin `bsk_` revokes an agent | CHK-M3-282 | TASK-077 |
| CHK-M3-331 | admin `bsk_` patches settings | CHK-M3-154 | TASK-062 |
| CHK-M3-332 | `AND uses < max_uses` removed | CHK-M3-060, -201 | TASK-052, 067 |
| CHK-M3-333 | expiry condition removed | CHK-M3-061, -200 | TASK-052, 067 |
| CHK-M3-334 | revocation condition removed | CHK-M3-061, -200 | TASK-052, 067 |
| CHK-M3-335 | `allowed_cidrs` condition removed | CHK-M3-061, -200 | TASK-052, 067 |
| CHK-M3-336 | `auto_approve` defaults to true | CHK-M3-190 | TASK-066 |
| CHK-M3-337 | re-enrolment with auto-approve approved at once | CHK-M3-203 | TASK-067 |
| CHK-M3-338 | `{id}` match removed | CHK-M3-162 | TASK-063 |
| CHK-M3-339 | `awaiting_approval` token gets 200 on `GET /jobs` | CHK-M3-126, -161 | TASK-059, 063 |
| CHK-M3-340 | mismatch answers 401 without revoking | CHK-M3-123, -161 | TASK-059, 063 |
| CHK-M3-341 | missing `X-Bitscan-Machine-Id` accepted | CHK-M3-123, -161 | TASK-059, 063 |
| CHK-M3-342 | expiry check one day late | CHK-M3-122, -271 | TASK-059, 075 |
| CHK-M3-343 | rotation window check removed | CHK-M3-265 | TASK-075 |
| CHK-M3-344 | old-token use after the overlap accepted | CHK-M3-125, -268 | TASK-059, 075 |
| CHK-M3-345 | heartbeat response gains `jobs` | CHK-M3-014, -235 | TASK-048, 072 |
| CHK-M3-346 | job payload gains `operator`, or `eval_spec` copied into a pull | CHK-M3-013, -247 | TASK-048, 073 |
| CHK-M3-347 | agent filter removed from the pull | CHK-M3-081, -247 | TASK-054, 073 |
| CHK-M3-348 | pull limit 11 | CHK-M3-081, -245 | TASK-054, 073 |
| CHK-M3-349 | `pickup_by` or `state = 'queued'` condition removed | CHK-M3-081, -247 | TASK-054, 073 |
| CHK-M3-350 | row lock and state re-check removed | CHK-M3-082, -246 | TASK-054, 073 |
| CHK-M3-351 | M3 kind filter removed | CHK-M3-081, -247 | TASK-054, 073 |
| CHK-M3-352 | `inventory_enabled` honoured or accepted | CHK-M3-094, -145, -152, -300 | TASK-055, 061, 062 |
| CHK-M3-353 | `POST /api/v1/agents/{id}/run` added | CHK-M3-300 | any route task, gate |
| CHK-M3-354 | `inventory_interval_s` range check removed from the service | CHK-M3-093, -152 | TASK-055, 062 |
| CHK-M3-355 | whole-body decompress without cap | CHK-M3-132, -133 | TASK-060 |
| CHK-M3-356 | 50,000-row check removed | CHK-M3-134 | TASK-060 |
| CHK-M3-357 | agent's `list_sha256` trusted | CHK-M3-131, -134 | TASK-060 |
| CHK-M3-358 | 10-minute unscheduled limit removed | CHK-M3-112, -257 | TASK-057, 074 |
| CHK-M3-359 | results route answers 200 or stores a row | CHK-M3-249 | TASK-073 |
| CHK-M3-360 | template matching removed | CHK-M3-030, -261 | TASK-049, 074 |
| CHK-M3-361 | after-auth mode removed | CHK-M3-032, -258 | TASK-049, 074 |
| CHK-M3-362 | failed `bsa_` checks not counted | CHK-M3-164 | TASK-063 |
| CHK-M3-363 | valid `bsa_` from a limited IP gets 429 | CHK-M3-164 | TASK-063 |
| CHK-M3-364 | 30-per-minute agent limit removed | CHK-M3-110, -163 | TASK-057, 063 |
| CHK-M3-365 | 10-per-minute enrol limit removed | CHK-M3-111, -207 | TASK-057, 067 |
| CHK-M3-366 | token or results stdout logged | CHK-M3-167, -252, -302 | TASK-063, 073 |
| CHK-M3-367 | clock-skew alert removed | CHK-M3-238 | TASK-072 |
| CHK-M3-368 | `runner_helpers` change without audit or alert | CHK-M3-237 | TASK-072 |
| CHK-M3-369 | sweep never decommissions, or without revoking | CHK-M3-182 | TASK-065 |
| CHK-M3-370 | reject leaves the agent `awaiting_approval` | CHK-M3-223 | TASK-070 |
| CHK-M3-371 | approve allowed for an operator session | CHK-M3-225 | TASK-070 |
| CHK-M3-372 | viewer allowed on tags | CHK-M3-280 | TASK-077 |
| CHK-M3-373 | sweep creates a retry row for a failed inventory job | CHK-M3-183 | TASK-065 |
| CHK-M3-374 | HTTP client call in a service | CHK-M3-305 | any service task, gate |

## Questions for `main`

Asked 2026-10-23 with TP-M3-01; answers recorded here when they arrive.

1. UUID strings in agent bodies: is only the RFC 9562 hyphenated form (8-4-4-4-12, what JSON Schema `format: uuid` checks) valid, so the 32-hex no-hyphen and `urn:uuid:` forms that Python's `UUID` accepts are invalid? The fixture `heartbeat/request_invalid_uuid_no_hyphens.json` assumes yes.
2. Nullable keys (`os_*`, `last_pull_at`, `current_job_id`, `last_error`, `exit_code`, `error`, `source`, `installed_size_kb`): required-but-nullable, or optional? The fixtures always send every key and use only non-nullable keys for "missing key"; no fixture depends on the answer, but the Go agent needs it.
3. Is the TS §3.3 L214 "at most 10 jobs" also a `maxItems: 10` on `jobs` in the contract? No fixture depends on it.

## Not tested in M3

Everything the M3 coverage matrix in `work/tasks.md` marks uncovered: the Go agent and the Go half of the contract test (M4), `GET /agents/{id}/scans` (M9), result acceptance beyond 409 (M9/M11), retention (M11), the 10,000-agent load and VM end-to-end tests (M6), redaction fixtures (M10). Durations recorded at 10,000 agents (CHK-M3-188) and for 50,000 packages (CHK-M3-070) carry no gate (testing.md open question on performance gates).
