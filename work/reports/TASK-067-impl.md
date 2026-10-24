# TASK-067 IMPL report: `POST /api/v1/agent/enroll`

REQ: REQ-068, REQ-065, REQ-077. Spec: TS §6.1 L1062, §3.2 L183–L188, §6.3 L1136, §6.5 L1161, §8.4 L1291; #25 (b), #36, #55 (c), (d), #59, #60, #61, #64, #71. Plan: `work/plans/TASK-067.md`. Depends on TASK-052, 055, 056, 057, 061, 063 and 066, all approved. **Two approvals** (TS §8.2).

Lead rulings folded in (2026-10-23):
- every in-process threshold window is built once in `create_app()`;
- a window is marked as fired only after its alert commits, both for the TASK-063 `agent_auth_failures` window and for the enrolments window.

Carry-overs applied:
- IPv4-mapped peers are normalised to IPv4 before `use_token` (`source_ip()`);
- every refused `bse_` gets 401 `unauthorized` and changes nothing.

**Open: a ruling is asked of the lead.** The OpenAPI component name clash with M2's `api/user/auth.py::EnrolRequest`, see "Open point". Hand-off waits for it.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/enrolment/enrol.py` | new, about 210 lines |
| `manager/bitscan_manager/api/agent/enrol.py` | new, 100 lines |
| `manager/bitscan_manager/api/agent/__init__.py` | `AgentWindows`, `build_agent_windows(clock)`, `AUTH_FAILURES_PER_MIN`; `build_agent_router()` includes the enrol router |
| `manager/bitscan_manager/manager/openapi.json` | re-exported; a second export is byte-identical |
| `manager/bitscan_manager/app.py` (TASK-049/063 file) | `create_app(runtime)` sets `app.state.agent_windows = build_agent_windows(runtime.clock)` (lead ruling) |
| `manager/bitscan_manager/api/agent/dependencies.py` (TASK-063 file) | the windows ruling, below |

The last two files are outside the task's file list, required by the lead's ruling. The reviewer should read them; tester-b should re-run `tests/test_agent_auth_pg.py`.

Changes in `dependencies.py`:
- `agent_windows(request)` reads `app.state` and answers 503 if the windows are missing.
- The `agent_auth_failures` window now uses `count_and_check`, then `tx.on_commit(mark_fired)`.
- `failed_check(runtime, ip, type_)` is factored out for enrol to use.
- `bearer_token` and `retry_after` are now public names.

## Route

`enrolment_caller(request, runtime)` is the `bse_` dependency, marked `bitscan_agent_auth = "bse_"` for the route walk. FastAPI solves it **before the body is validated**. In order:
1. `limits.allow_enrol(ip)`: 10 per minute per source IP, every attempt counted (#55 (c)). Over the limit gives 429 `rate_limited` with `Retry-After`.
2. Bearer and shape: a well-formed `bse_` is required. A `bsa_`, `bsu_` or `bsk_` token, no token, or a peer that is not an IP address gives **401 `unauthorized`**, counted as a failed check (per-IP limit, 429 once over).

The body is `EnrolRequest` (TASK-048); a bad body gives 400. `os_id` and `os_version_id` are validated and not stored (#60).

The service then runs in one transaction. If `EnrolRefused` is raised, `use_token` changed nothing, and the answer is the same 401 `unauthorized`, counted.

The answer is 200 `EnrolResponse`: `agent_id`, `agent_token` (shown once), `issued_at`, `expires_at`, `status`.

## Service (`enrol`, one transaction)

1. `use_token(hash(bse_), ip, now)`: expiry, revocation, `allowed_cidrs` and `uses < max_uses` with the increment, all in one statement (TASK-052). None raises `EnrolRefused` (#59: one refusal for every cause).
2. A new `bsa_` token. Only its hash is stored. `issued_at = now`, `expires_at = now + agent_token_ttl_days`, the current setting.
3. `find_by_machine_id(lock=True)`.
   - **None, `auto_approve`:**
     - insert the agent as `enrolled` (`enrolled_at = now`);
     - `record_ip` (#25 (b));
     - `queue_first_inventory` (#36);
     - status `enrolled`.
   - **None, held:**
     - insert the agent as `awaiting_approval` with the token hash;
     - `record_ip`;
     - a `kind = 'new'` request with the same hash, `token_expires_at`, source IP and so on;
     - status `awaiting_approval`.
   - **Existing machine-id, whatever the token allows:**
     - a `kind = 'reenrol'` request for the existing `agent_id` with the new hash;
     - the **agent row is not touched** (REQ-068 (4));
     - status `awaiting_approval`, with the existing `agent_id`.
   - **Race:** `insert` uses `ON CONFLICT (machine_id) DO NOTHING`. When a concurrent first enrolment won, it returns None, and the locked re-read takes the re-enrolment branch in the same transaction. No retry is needed, and `uses` is incremented once.
4. **One `agent.enrol` entry** (#71): actor and target `agent:<id>`, detail `{token_id, kind, status, request_id}`. No token, hash or machine-id.
5. **Enrolments per hour (#61):** `window.count_and_check(token_id, 1, enrolment_alert_per_hour)`. The window is 60 minutes, sliding, per token. When the count first exceeds the setting, one `enrolments_per_hour` alert entry is written (actor `system`, target `enrollment_token:<id>`) and `mark_fired` is registered on commit. The repeat is at most once per token per hour.

**Reading (please confirm in review):** for a held re-enrolment, the source IP is **not** recorded on the existing agent (`agent_ip_seen`, `last_seen_ip`). REQ-068 (4) requires that row unchanged, and an unapproved and possibly cloned host must not feed the 7-day new-IP rotation alert. #25 (b) "enrolment included" applies here to the new agent rows.

## Open point (asked of the lead): component name clash

The agent `schemas.EnrolRequest` and M2's `api/user/auth.py::EnrolRequest` (the `POST /auth/totp/enrol` body) have the same class name. Once the enrol route is mounted, FastAPI names both components by module path, which renames M2's user component that `web/src/api/schema.d.ts` references. My recommendation is to rename the M2 class to `TotpEnrolRequest`, keeping the agent contract name `EnrolRequest` as TS §6.5 and the fixtures use it. The export in the tree currently has the two long names.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (84 files under it).
- `pytest -q`: 2156 passed, 871 skipped, **7 failed**. All seven are in test files, and none is a product defect:
  - `tests/test_app.py::test_post_enroll_is_404`, `test_doc_and_api_paths_are_not_served[/api/v1/agent/enroll]` and `tests/test_problems.py::…GET-/api/v1/agent/enroll…404` are M0/M2 assertions that the route does not exist. It now exists: GET gives 405, and POST without a runtime gives 503.
  - `tests/test_login.py::test_documented_400_matches_what_the_app_returns` sends a bad body without a token and expects 400. Enrol answers 401 first, by design: the token and the per-IP limit run before the body, so every attempt counts.
  - `tests/test_contract_agent.py::test_document_fixtures_against_openapi` needs the `schema_gap` (model-only) marking that the model test already applies, now that the enrol request is in the document.
- **Service probe** (fake stores):

  | Case | Result |
  | --- | --- |
  | auto-approved | `enrolled`, a `bsa_`, TTL 365 d, stored hash = SHA-256 of the token, one first inventory job, IP recorded, one `agent.enrol` entry, no request |
  | held new | an `awaiting_approval` row plus a `new` request holding the same hash; no job |
  | re-enrolment with an auto-approve token | held, existing `agent_id`, nothing inserted, no IP recorded, no job |
  | refused | nothing inserted, no request, no audit entry |
  | insert race | the `reenrol` branch, with `use_token` called once |
  | per-hour 3, 5 enrolments with hooks dropped (rollback) | alerts on the 4th and 5th |
  | after a committed alert | no further alert |

- **Route probe** (`create_app()` with the service faked):

  | Case | Result |
  | --- | --- |
  | good `bse_` | 200 |
  | `bsa_`, none, `bsu_`-shaped | 401 `unauthorized` |
  | bad body with a good token | 400 |
  | refused `bse_` | 401 |
  | 10 malformed bodies, then a good one from the same IP | 400 × 10, then 429 |
  | another IP | 200 |
  | non-IP peer | 401 |

- PostgreSQL (TP-M3-21: concurrency, the CIDR mix, IPv6, the rows): **NOT RUN locally**; WSL.

## Deviations

The two touched files and the IP reading, both noted above. The size (about 310 hand-written lines in the two new files) is over the guide, as the plan expected for this task. A split would separate the route from its service.

## Rulings applied (lead and user, 2026-10-23)

1. **Name clash, option (a):** `manager/bitscan_manager/api/user/auth.py` (an approved M2 file) renames the class `EnrolRequest` to **`TotpEnrolRequest`** in two places: the class and the `POST /auth/totp/enrol` body annotation. There is no behaviour change, and its JSON fields are unchanged.
   - `openapi.json` was re-exported and is byte-stable. Its components are now `EnrolRequest` (the agent contract), `EnrolResponse`, `EnrolStartResponse` and `TotpEnrolRequest`; there are no module-path names.
   - `/api/v1/auth/totp/enrol` refers to `TotpEnrolRequest`, and `/api/v1/agent/enroll` to `EnrolRequest`.
   - The web types follow at the TASK-081 regeneration.
2. **IP reading confirmed:** a held re-enrolment records no source IP on the existing agent.
3. **Accepted:** the `app.py`/`dependencies.py` touches and the size.

**Gates after the rename:** ruff, ruff format and `mypy --strict` pass (175 files).
- The OpenAPI, TOTP, contract, app, problems and login suites give 630 passed, 5 failed. The 5 failures are exactly the test-file updates listed above:
  - test_app × 2: the route now exists;
  - test_problems × 1: GET answers 405, not 404;
  - test_login: the documented-400 walk, where enrol answers 401 first;
  - test_contract_agent: document schema-gap marking.
- TOTP enrolment tests (`tests/test_totp_enrol.py`) pass.

## Revision: alert actor (lead ruling under #71, 2026-10-23)

The `enrolments_per_hour` alert's actor is now **`agent:<agent_id>`** of the enrolment that crossed the threshold, as #71 rules ("actor `agent:<agent_id>` for agent-route events"). It was `system`. The target stays `enrollment_token:<id>`, and the action stays `alert.enrolments_per_hour`. Only `services/enrolment/enrol.py` changed, one argument. A probe with the 4th enrolment over a per-hour limit of 3 showed the alert with actor `agent:<that enrolment's agent_id>`. Gates: ruff, ruff format and `mypy --strict` pass.

## Revision 1 (tester-c FAIL round 1: CHK-M3-204-scope)

- **Defect:** a link-local IPv6 peer reported with its zone (`fe80::1%eth0`) gave 500. This happened on enrol, in `use_token`'s `CAST(%s AS inet)`, and on every `bsa_` route, in `record_ip`. `source_ip()` kept the zone, and PostgreSQL `inet` has none. CPython reports such a peer this way for a server listening on `::`, so it is reachable in practice.
- **Fix:** `bm/api/agent/dependencies.py`, `source_ip()` only. That function is the single source of the peer for enrol and for every `bsa_` route.
  - The zone is dropped (`host.partition("%")[0]`) before parsing. The address is kept, so a link-local agent still enrols and its IP is recorded without the zone.
  - IPv4-mapped peers are still turned into IPv4. A peer that is not an IP address is still `None`.
- **Probe:**

  | Peer | Result |
  | --- | --- |
  | `fe80::1%eth0` | `fe80::1` |
  | `fe80::1%2` | `fe80::1` |
  | `::ffff:10.0.0.1` | `10.0.0.1` |
  | `10.0.0.1` | `10.0.0.1` |
  | `2001:db8::1` | `2001:db8::1` |
  | `testclient` | `None` |
  | `%eth0` | `None` |
  | `""` | `None` |

- **Gates:** ruff, ruff format and `mypy --strict` pass.
- **For tester-c:** re-run `tests/test_enrol_api_pg.py` and `tests/test_agent_auth_pg.py` (W). The file is TASK-063's, so its suite is re-run here.

### Revision 1, final scope (lead ruling 2026-10-23)

The zone is dropped **before** the IPv4-mapped conversion. The lead asked me to check the M2 user-route path too:
- A zoned peer there reaches **no database cast**.
- It **does reach an audit entry**, in the aggregated `auth.token_check_failed` `detail.ip` (TS §6.3 L1136), and it is the limiter key.
- Unnormalised, one client's failed checks would be keyed `fe80::1%eth0` on user routes and `fe80::1` on agent routes. That breaks REQ-065 (3): one aggregate per IP across both route groups.

So a single normaliser now serves both groups.

**Final r1 files:**

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/peer.py` | **new** module. `peer_ip(request) -> str \| None` returns the normalised address (zone dropped, then IPv4-mapped IPv6 as IPv4), or None if the peer is not an IP. `peer_key(request) -> str` returns `peer_ip`, else the peer as given (for example TestClient's `testclient`, keeping the M2 behaviour), else `"unknown"`. |
| `manager/bitscan_manager/api/agent/dependencies.py` (TASK-063) | `source_ip()` delegates to `peer_ip()`; behaviour is the revision-1 fix |
| `manager/bitscan_manager/api/user/auth.py` (M2) | the sign-in limiter key is `peer_key(request)` |
| `manager/bitscan_manager/auth/dependencies.py` (M2) | the failed-check limiter key and aggregated `detail.ip` are `peer_key(request)` |

**User routes, behaviour change:**
- Only real IP peers change: a zoned IPv6 peer now keys without its zone, and an IPv4-mapped peer keys as IPv4. Both match the agent routes.
- A non-IP peer (`testclient`) and a missing client (`"unknown"`) key exactly as in M2.
- Re-run G25 (`test_auth_dependencies.py`, `test_security_m2.py`) and the M2 login suites.

**Probe:**

| Peer | `peer_ip` | `peer_key` |
| --- | --- | --- |
| `fe80::1%eth0` | `fe80::1` | `fe80::1` |
| `::ffff:10.0.0.1` | `10.0.0.1` | `10.0.0.1` |
| `10.0.0.1` | `10.0.0.1` | `10.0.0.1` |
| `testclient` | None | `testclient` |
| no client | None | `unknown` |

**Gates:**
- ruff, ruff format and `mypy --strict` pass.
- `pytest -q`: 2175 passed and 1 failed. The failure is `test_body_caps.py::test_other_agent_routes_keep_one_mib`, a TASK-072 test that the real heartbeat route now shadows; tester-c is handling it.
- `test_login.py`, `test_auth_dependencies.py` and `test_security_m2.py` pass locally (61 passed, PostgreSQL cases skipped on Windows).
- **r1 follow-up (reviewer nit, lead 2026-10-23):** on the agent side, the failed-check and enrol limiter keys are now `peer_key(request)` instead of `peer_ip(...) or "unknown"`. This applies to `api/agent/dependencies.py` (`authenticate_agent`) and `api/agent/enrol.py` (`enrolment_caller`). A non-IP peer is therefore keyed the same on both route groups. Example: TestClient's `testclient` now keys as `testclient` on agent routes too, no longer `unknown`. `source_ip()`, which feeds storage and the CIDR check, stays `peer_ip()`. Gates pass, and the route probes of TASK-063 and TASK-067 give the same results as before.
