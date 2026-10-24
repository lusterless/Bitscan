# TASK-067 REVIEW: `POST /api/v1/agent/enroll`

Reviewer: reviewer. Date: 2026-10-23. REQ-068, REQ-065, REQ-077. Spec: TS §6.1 L1062 (enrol takes a `bse_` token), §3.2 L182–L188 (atomic token use with expiry, revocation, CIDR and `uses < max_uses`; the held, auto-approved and re-enrolment outcomes; only the SHA-256 is stored, the token is shown once), §6.3 L1136 (10 per minute per source IP on `/agent/enroll`; failed token checks per IP), §6.5 L1161 (Enrol contract), §8.4 L1291 (enrolments per hour per token); #25 (b), #36, #55 (c), (d), #59, #60, #61, #64, #71. Rulings (`work/decisions.md`, 2026-10-23):
- the TASK-067 rulings: `TotpEnrolRequest` rename; a held re-enrolment records no IP; about 310 lines and the `app.py` and `dependencies.py` touches accepted;
- windows built once in `create_app()` and marked only on commit;
- r1: one `peer_key()` for every route group, touching two second-approved M2 auth files.

Plan: `work/plans/TASK-067.md`. Inputs:
- `work/reports/TASK-067-impl.md`, including revision 1;
- `work/reports/TASK-067-test.md`: round 1 FAIL (CHK-M3-204-scope: a zoned IPv6 peer → 500), then round 2 PASS (1178 passed in WSL including G25 and the M2 login, users and rate-limit suites; 7 of 7 r1 plants red; 23 of 23 round 1 plants red).

Files reviewed:
- `manager/bitscan_manager/services/enrolment/enrol.py`;
- `manager/bitscan_manager/api/agent/enrol.py`;
- `manager/bitscan_manager/api/agent/__init__.py` (`AgentWindows`, router include);
- `manager/bitscan_manager/api/agent/dependencies.py` (windows, `failed_check`, `peer_key`);
- `manager/bitscan_manager/app.py` (windows built in `create_app()`);
- new `manager/bitscan_manager/api/peer.py`;
- the M2 files `manager/bitscan_manager/api/user/auth.py` and `manager/bitscan_manager/auth/dependencies.py`;
- `manager/openapi.json`;
- the tester-c tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; enrolment, agent routes and the two auth files). This is the first one; the user's second approval is still needed.

## What was checked

- **Route and token group (REQ-062).**
  - `enrolment_caller` runs `allow_enrol(peer_key)` first (10 per minute, every attempt that reaches it counts; but see finding 1). Then it requires a well-formed `bse_`.
  - A `bsa_`, `bsu_`, `bsk_`, no token, another scheme, or a non-IP peer gets 401 `unauthorized` through `failed_check`, which counts toward the per-IP limit and answers 429 once the IP is over it (CHK-M3-322 red).
  - A refused `bse_` (unknown, expired, revoked, exhausted, outside `allowed_cidrs`) gets the same 401 and changes nothing (#59).
  - The corrected route walks now iterate `api_routes()`. They find exactly one `POST /api/v1/agent/enroll` carrying the `bse_` marker and no `bsa_` or user dependency, and every other agent operation carrying `bsa_`. This replaces the TASK-063 walk, which was vacuous because it iterated only `app.routes`. My TASK-063 review relied on that walk, and the corrected one now proves the markers.
- **Service (one transaction).**
  1. `use_token` does the whole check and the increment in one statement, so 20 concurrent enrolments on a 5-use token give exactly 5 (CHK-M3-332).
  2. A new `bsa_` is minted. Only its hash is stored (CHK-M3-324 red), and `expires_at = now + agent_token_ttl_days` from the current setting.
  3. `find_by_machine_id(lock=True)` decides the branch:
     - new + `auto_approve`: an `enrolled` agent, its IP recorded, its first inventory job (#36);
     - new held: an `awaiting_approval` agent with the token hash, plus a `kind = 'new'` request holding the same hash;
     - existing machine-id, whatever the token allows: a `kind = 'reenrol'` request, with the agent row untouched and no IP recorded (ruling; CHK-M3-337 red).
  4. A lost insert race (`ON CONFLICT DO NOTHING` returns None) takes the re-enrolment branch in the same transaction, so `uses` rises once.
  5. One `agent.enrol` entry with actor and target `agent:<id>` and detail `{token_id, kind, status, request_id}`, never a token, hash or machine-id.
  6. The #61 window counts per token with the setting passed per call. It writes one `enrolments_per_hour` alert and marks it fired only on commit.

  The response validates against `EnrolResponse` (TS §6.5).
- **Windows (ruling).** `AgentWindows` (per-agent 401s, enrolments per token) are built once in `create_app()`. The TASK-063 `agent_auth_failures` window now uses `count_and_check` plus an on-commit `mark_fired`. A missing window answers 503, which is reachable only without a runtime.
- **Peer address (r1, and the two M2 auth files reviewed as auth changes).**
  - `api/peer.py`: `peer_ip` drops an IPv6 zone (`fe80::1%eth0` → `fe80::1`, which PostgreSQL `inet` accepts; the round 1 500 is fixed). It reports IPv4-mapped peers as IPv4 and returns None for a non-IP peer. It still reads only the TCP peer and no proxy header (#55 (d)).
  - `peer_key` falls back to the peer's own name, then `"unknown"`, as M2 did.
  - `api/user/auth.py` (`login_limit`) and `auth/dependencies.py` (`current_principal`) change exactly one line each, the limiter key and therefore the aggregated entry's `detail.ip`, to `peer_key(request)`. `grep` finds no other `request.client` use in the manager.
  - What moves for M2: a zoned IPv6 peer is keyed without its zone, and an IPv4-mapped peer is keyed as its IPv4 address, so one client has one aggregate across route groups (REQ-065 (3)). Token resolution, roles, TOTP sessions, sign-in back-off, limits and response bodies are unchanged. G25 and the M2 login, users and rate-limit suites are green.
  - The `TotpEnrolRequest` rename changes only the OpenAPI component name; `web/src/api/schema.d.ts` follows at TASK-081.
- **OpenAPI (G6).** My re-export is byte-identical to `manager/openapi.json`. `/api/v1/agent/enroll` has no 422. The components hold `EnrolRequest`, `EnrolResponse` and `TotpEnrolRequest`. The document also holds the TASK-072 heartbeat route, which is in the same working tree.
- **Scope.** About 310 lines plus the ruled touches, accepted by the lead. I don't ask for the split, because the service and route are cohesive and the rulings explain the extra files.
- **Tests (my run, Windows).** `test_enrol_api_pg.py`, `test_agent_auth_pg.py`, `test_auth_dependencies.py`, `test_security_m2.py`, `test_login.py`, `test_openapi.py`, `test_contract_agent.py`, `test_app.py` and `test_problems.py`: 649 passed, 140 skipped (PostgreSQL; run in WSL by tester-c). ruff and format are clean, and `mypy --strict` is clean on the whole tree (183 files).

## Findings

None block approval.

1. **nit (cross-cutting; recommend a lead decision)**, `manager/bitscan_manager/api/agent/enrol.py:264-270`. Because `enroll` declares `body: EnrolRequest`, FastAPI parses the JSON body **before** it solves `enrolment_caller`. I probed it on a minimal app: a non-JSON body is refused with 400 and the dependency never runs. Such attempts therefore count neither toward the 10-per-minute enrol limit nor as failed checks. TS §6.3 L1136 and #55 (c) say every attempt counts.

   Why this is a nit and not a should-fix:
   - the same pre-existing behaviour is in the second-approved M2 `POST /auth/login`;
   - an uncounted attempt costs at most a 1 MiB JSON parse, with no database work and no token check.

   **Fix, if the lead wants it:** have both unauthenticated routes take the body as raw bytes, as the after-auth routes do, and validate it with the model after their limit dependency. Alternatively, count the attempt in a request validation-error hook for those two paths. Either way, add a test that 11 non-JSON enrol attempts from one IP get 429.

## Carry-overs

- **TASK-070.**
  - Approving a re-enrolment re-links with the request's token, `requested_at` and `token_expires_at` (#64).
  - The approval queues the first inventory job (#36).
  - A request whose new token has expired is refused with 409 (#64 (e)).
  - A rejected new agent becomes `decommissioned` with `token_revoked_at`.
- **TASK-072 to 075.** Each re-runs the corrected route walk and the 401/403 matrix on the real route.
