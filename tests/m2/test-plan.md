# M2 test plan (auth core and API plumbing)

Owner: tester. Written 2026-10-21 from `work/tasks.md` "M2 auth core and API plumbing" (acceptance tests, TP-M2-00 to TP-M2-25, M2 gate G1 to G6, G16, G18, G25 to G29), `work/requirements.md` REQ-034 to REQ-059, the TS sections they cite (§2.3, §5.3, §6, §6.2, §6.3, §8.1, §8.3, §8.4, §8.6, §8.7) and the answers in `work/decisions.md` (2026-10-21, "M2 breakdown approved"), before any M2 implementation was read. Results go to [report.md](report.md) (written by `main` from the tester's messages).

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = the real app: `create_app(runtime)` served over HTTP by the ASGI test client against a real PostgreSQL, or the real `bitscan-manager` process (`serve`, `users …`).
- Where: **L** = Windows 11 + Git Bash (`$P;` = the PATH line from `work/m0-brief.md`; `PY` = `manager/.venv/Scripts/python.exe`, run from `manager/`). **W** = WSL2 Ubuntu 24.04 with Docker, run only by the tester, one run at a time, through `%TEMP%\tester2_<name>.sh` launched with `MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/Users/kaiquan.koh/AppData/Local/Temp/tester2_<name>.sh`; working copy `/root/bitscan-tester` (tree copied without `.venv`, `node_modules`, `__pycache__`), a fresh venv `/root/venv-m2` from the hashed dev lock plus `pip install --no-deps --no-build-isolation -e .` from `manager/`, `CI=true`, `RYUK_CONTAINER_IMAGE` pinned, `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`. The venv is recreated whenever a lock changes. **CI** = GitHub Actions only. On L every `pg` test is "not run: Docker unavailable"; the W run is the evidence.
- PostgreSQL checks use the M1 harness (REQ-032): Bootstrap from the spec, `db migrate` through the CLI, connections only as `bitscan_app`, `bitscan_retention`, `bitscan_migrate`. M2 adds no superuser statement. Rows that `bitscan_app` cannot change (deleting a `system_schedule` row, changing `alembic_version`) are changed as `bitscan_owner` (`bitscan_migrate` + `SET ROLE bitscan_owner`).
- **Fake clock** = the TASK-025 `Clock`; every time rule is tested by moving it, never by sleeping. **Canary** = a unique random string (`CANARY-<16 hex>`) planted as a password, token, TOTP seed, TOTP code, DSN password, vault token or vault response body. A **canary sweep** searches captured log records (all levels, all loggers, formatted), stdout, stderr, every response body and header, exception `str`/`repr`/args and the whole chain (`__cause__`, `__context__`, formatted traceback) and `repr` of runtime and client objects. The sweep helper is `manager/tests/canary.py` (TP-M2-05) and is reused by every later task.
- "Refused" = the request changes nothing (row snapshot of `app_user`, `user_token`, `audit_log` before and after is equal, except an entry the criterion names) and gets the #48 status and `type`.
- Planted violations: made in a throwaway copy of the tree (`$TEMP/m2-mut-<id>` on L, `/root/bitscan-mut` on W), never in the tree. Each planted check also runs on the unmodified copy (must be green). "Red" = non-zero exit **and** the named test or message fails for the planted reason. Mutations are listed per task and collected in the [security mutation table](#security-mutation-table).
- Re-test rows in the report use suffixes (`-rN`, `-ctl`).
- Expected values come from the spec and the answered questions below, never from the implementation. Where an answer leaves a point open, the check says so and `main` is asked; the check is never adapted to the code.

## Expected values (spec and answered questions)

| Item | Expected | Source |
| --- | --- | --- |
| Statuses and problem `type` | 401 `unauthorized` (every token or sign-in failure, one body); 403 `forbidden` (role); 403 `session_required` (API token on a session-only route); 403 `totp_session_required` (API token or unverified session on a TOTP-session route); 403 `totp_enrolment_required` (restricted admin session); 503 `audit_sink_unavailable` (15-minute refusal); 429 `rate_limited` with `Retry-After` (seconds to window end), but back-off answers like a failed sign-in (401); 400 `invalid_request` (every validation error); 409 `conflict` (detail names the rule); 404 `not_found` (another user's token id); 413 `too_large` on user routes too; an admin's `bsk_` token while the admin has no TOTP: 403 `totp_enrolment_required`, **not** counted as a failed check | #48; decisions 2026-10-21 "M2 test-plan answers" (1); 413 ruling |
| Problem body | exactly `type`, `title`, `status`, `detail`, `instance`; `Content-Type: application/problem+json`; `instance` = path without query | TS §6.3 L1133; REQ-038 |
| HSTS | `Strict-Transport-Security: max-age=31536000` byte for byte | #57 (a) |
| CSP | `default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'` byte for byte | TS §6.3 L1140 |
| Size caps | 1 MB = 1,048,576 bytes; default JSON 1,048,576; `.bit` 5,242,880; result batch 1,572,864; inventory 10,485,760 gzip / 67,108,864 decompressed | TS §6.3 L1138; #57 (b) |
| Tokens | prefix + 43 characters of `[A-Za-z0-9_-]`, no `=`, 47 in total; body = base64url of 32 CSPRNG bytes; stored `token_hash` = lowercase hex SHA-256 of the whole string including the prefix | TS §6.2 L1083; #56 (a) |
| Passwords | 12 to 1,024 Unicode code points, no normalisation (UTF-8 as typed); Argon2id PHC `$argon2id$v=19$m=65536,t=3,p=4$…` | TS §6.2 L1087; #56 (b), (c) |
| Usernames | case-sensitive exact match; 1 to 64 characters; ASCII letters `A-Z` `a-z`, digits and `._@-` only; no whitespace, no non-ASCII letter | #56 (d); decisions 2026-10-21 "M2 test-plan answers" (4) |
| TOTP | HMAC-SHA1, 6 digits, 30 s, current step ± 1; seed 20 random bytes, base32; any user with TOTP enrolled must give a code at sign-in and gets `totp_verified = true` | #49 (a), (c) |
| TOTP enrolment | two calls on `POST /auth/totp/enrol`: start returns `{secret, otpauth_uri}` (replacement needs `current_password` and `current_code`); the pending seed is in memory only, bound to the session, 10 min; confirm `{totp_code}` stores the seed through the vault and re-issues the session | #49 (b) |
| Sessions | `expires_at` = issue + 24 h; refused 8 h after last use | TS §6.2 L1080 |
| API tokens | default 90 days, 1 to 365, optional name ≤ 64; `bsk_` may call `DELETE /api-tokens/{token_id}` for its own tokens | TS §6.2 L1081; REQ-051; #8 |
| Back-off | after n consecutive failures `next_login_at` = failure time + min(2^(n−1), 900) s; attempts during back-off are not checked and not counted, answered with the same 401 after a dummy hash | REQ-048 (3); #55 (a), (b) |
| Rate limits | `/auth/login` 10 per minute per IP counting every request; 600 per minute per user over all tokens; 20 failed token checks per minute per IP, counting failures only; every token is checked first, even from an IP over the failed-token limit: a valid token from a limited IP passes with no 429, an invalid one gets 429 (not 401) and still counts toward the aggregated `count` and the alert detail; source IP = TCP peer, `X-Forwarded-For` and `Forwarded` ignored | TS §6.3 L1136; #55 (c), (d), (e); decisions 2026-10-21 "M2 test-plan answers" (3) as corrected by decisions 2026-10-21 "Correction to M2 test-plan answers (3)" |
| Alert thresholds | `login_failures`: an account reaches 5 consecutive failures, then each further 5 (10, 15, …); `token_check_failures`: an IP passes the 20-per-minute limit, at most one alert per IP per hour | #54 (a), (b) |
| Audit | actions `auth.login`, `auth.logout`, `auth.password_change`, `auth.totp_enrol`, `auth.totp_replace`, `auth.token_check_failed`, `api_token.create`, `api_token.revoke`, `user.create`, `user.role_change`, `user.disable`, `user.enable`, `user.totp_reset`, `user.tokens_revoke`, `audit.sink_unreachable`, `audit.sink_recovered`; actor `user:<user_id>`, `cli:root`, `system`; alerts `detail = {"alert": true, "alert_kind": <kind>, …}` with kinds `api_token_created`, `totp_enrolled`, `totp_replaced`, `totp_reset`, `user_created`, `role_granted`, `admin_created`, `audit_sink_unreachable`, `login_failures`, `token_check_failures`; failed sign-ins are not audited one by one; aggregated failed-check `detail` = `{"ip", "window_start", "count"}`; `detail` never holds a password, token, code or seed | #50 |
| Bodies | login `{username, password, totp_code?}` → `{token, expires_at, role, totp_enrolled, totp_verified}`; logout no body, 204; `POST /api-tokens` `{name?, expires_in_days?}` → `{token_id, token, name, expires_at}`; list items `{token_id, name, created_at, expires_at, last_used_at, revoked_at}`; `DELETE /api-tokens/{token_id}` 204; `GET/POST /users`, `GET/PATCH/DELETE /users/{user_id}`; `PATCH` any of `{role}`, `{disabled: false}`, `{totp: null}`, `{revoke_tokens: true}`; `POST` `{username, password, role?}`; user items `{user_id, username, role, disabled, totp_enrolled, created_at}`; every list `{items, next_cursor}`; CLI `--name`, `--days` (1–365, default 90) | #47 |
| Ids | BIGSERIAL ids are JSON integers and decimal path segments | #52 |
| Revocation effects | (a) password change ends all sessions, including the presenting one; (b) own TOTP replacement ends other sessions, caller gets the re-issued one; (c) any role change, promotion included, ends sessions; (d) a demotion is any lower role; (e) "revoke a user's tokens" revokes API tokens and sessions; (f) `POST /users` cannot create an admin; (g) re-enable through `PATCH {disabled: false}`, audited; (h) self disable or demote follows the last-admin rule, a TOTP reset needs another admin; (i) an admin's API tokens are refused while the admin has no TOTP | #53 |
| Initial password | `create-admin` prompts twice on a TTY (hidden, must match, ≥ 12), with no TTY reads one line from stdin; never argv or environment. `POST /users` takes it in the body; no forced change | #7 |
| Vault | OpenBao, Vault-compatible Transit API: `POST <BITSCAN_VAULT_ADDR>/v1/transit/encrypt/<BITSCAN_TOTP_KEY_REF>` and `…/decrypt/<key>`, token auth with the token from `BITSCAN_VAULT_TOKEN_FILE`, TLS verified against the system CA store | decisions 2026-10-21 (1); #24 |
| Vault down | `serve` starts and logs; sign-in of a user with TOTP and TOTP enrolment fail with 503, no fallback; users without TOTP unaffected; `/readyz` does not check the vault | #58 |
| Sink | `syslog+tls://host:port`: RFC 5424 message, RFC 5425 octet-counted framing, server certificate verified; `https://…`: one audit entry per POST as one JSON object, and a 2xx acknowledges exactly that entry; plain `udp`, `tcp`, `http` (and syslog without TLS) refused at start-up | decisions 2026-10-21 (2) and "M2 test-plan answers" (2); #24 |
| Delivery | `serve` alone ships committed rows in `audit_id` order (CLI and later retention entries included); within 5 s of commit while the sink is up; at-least-once, duplicates keep `audit_id` and `row_hash`; the outage start is stored in the queue folder and survives restarts; "drained" = queue empty and cursor at the newest committed entry | #51 |
| Health | `/healthz` and `/readyz` outside `/api/v1`, no token, no rate limit, security headers sent; 200 body `{"status": "ok"}`; 503 problem naming `db`, `migrations` or `system_schedule` and nothing else | #5 |
| OpenAPI | not served (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` 404) | #34 |

## Gate map

| Gate | Checks |
| --- | --- |
| G1 ruff (S608, `re` ban) | CHK-M2-090, CHK-M2-300 |
| G2 ruff format | CHK-M2-301 |
| G3 mypy --strict | CHK-M2-007, CHK-M2-302 |
| G4 pip --require-hashes | CHK-M2-001, CHK-M2-002 |
| G5 coverage gate (local, unit only) | CHK-M2-303 |
| G6 OpenAPI export diff | CHK-M2-304 (and the last row of every route task) |
| G16 web client regeneration | CHK-M2-280 |
| G18 full W/CI run, 0 skipped | CHK-M2-305 |
| G25 Security suite (auth) | CHK-M2-150 to -166, CHK-M2-290 to -294 |
| G26 shipper and gate | CHK-M2-120 to -133 |
| G27 serve TLS and `SIGHUP` | CHK-M2-250 to -258 |
| G28 canary | CHK-M2-050 to -056, CHK-M2-293 |
| G29 telemetry | CHK-M2-010, CHK-M2-011 |

## TASK-023 Runtime dependencies (REQ-034; TP-M2-01)

| Id | Type | REQ | Check and command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-001 | CODE | REQ-034 (1), G4 | Fresh `python -m venv` (bundled pip): `pip install --require-hashes -r manager/requirements.txt`; second fresh venv for `requirements-dev.txt`; both exit 0, no sdist build | — | L, W |
| CHK-M2-002 | CODE | REQ-034 (1), G4 | Copies of each lock: the installed `argon2-cffi` (and `argon2-cffi-bindings`) wheel hash altered by one character; an unpinned line appended: each install exits non-zero with the pip hash or pin message | altered Argon2id hash | L |
| CHK-M2-003 | CODE | REQ-034 (1) | Linux wheel-hash proxy (M1 script): every Linux-applicable line of both locks downloaded for cp312 manylinux x86_64 and aarch64; each SHA-256 is in that line's hashes (in particular `argon2-cffi-bindings`, `psycopg-pool`, `uvicorn`, `httpx`, `prometheus-client`) | — | L (needs PyPI) |
| CHK-M2-004 | CODE | REQ-034 (2) | In the runtime venv: `python -c "import uvicorn, argon2, httpx, psycopg_pool, prometheus_client; from argon2 import low_level"` exits 0; `argon2.PasswordHasher().hash('x' * 12)` starts `$argon2id$` | — | L, W |
| CHK-M2-005 | CODE | REQ-034 (3), (5), PD-19 | `tests/test_lock_files.py` (updated): the runtime lock contains `uvicorn`, `argon2-cffi`, `httpx`, `psycopg-pool`, `prometheus-client`; it contains none of `pytest`, `pytest-cov`, `ruff`, `mypy`, `testcontainers`, `coverage`, `hatchling`; neither lock contains `opentelemetry-sdk`, any `opentelemetry-exporter-*`, `opentelemetry-instrumentation*`, nor an OIDC or identity-provider library (`authlib`, `oauthlib`, `requests-oauthlib`, `python-jose`, `joserfc`, `oic`, `pyoidc`, `msal`, `python-keycloak`, `fastapi-users`); the runtime lock has no `uvloop`, `httptools`, `watchfiles`, `websockets` (uvicorn without extras, PD-19 (a)), no `hvac` and no `pyotp` (PD-19 (f), (g)); httpx moved, not duplicated; the dev lock is a superset with the same versions | `opentelemetry-sdk` or `pytest` added to the runtime lock (test red) | L |
| CHK-M2-006 | CODE | REQ-034 (4) | Rerun the command recorded in each lock header (with its `--exclude-newer` cutoff) in a temp dir; `cmp` with the committed lock: byte-identical. A moved cutoff is reported as a dependency update | hand-edited lock | L (needs PyPI) |
| CHK-M2-007 | CODE | REQ-034, G3 | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` exit 0; the existing suite is green (L: `pg` skipped; W: 0 skipped) | — | L, W |

## TASK-024 `create_app()` hardening (REQ-035, REQ-036, REQ-037; TP-M2-02)

Tests in `manager/tests/test_app_hardening.py`. Command: `PY -m pytest tests/test_app_hardening.py`. Test routes are added to an app built by `create_app()` in the test only (never in product code) to provoke each status.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-010 | CODE | REQ-035 (1), G29 | In a subprocess with `FASTAPI_OTEL_AUTO_CONFIGURE=true`, `OTEL_TRACES_EXPORTER=otlp`, `OTEL_METRICS_EXPORTER=otlp`, `OTEL_LOGS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:<port>` (a local TCP listener that records accepts): build `create_app()`, send 20 requests; no accept within 5 s; `opentelemetry.sdk` not in `sys.modules`. Control: the listener accepts a plain test connection (so it can observe one) | telemetry settings removed from `create_app()` | L |
| CHK-M2-011 | CODE | REQ-035 (2), G29 | The same with every OTel variable unset | as above | L |
| CHK-M2-012 | CODE | REQ-035 (3), #34 | `GET /docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`: 404, problem body, security headers | `docs_url` default restored | L |
| CHK-M2-013 | CODE | REQ-035 (4), REQ-036 (4) | CORS preflight `OPTIONS` with `Origin: https://evil.example`, `Access-Control-Request-Method: POST` on `/`, a test route, `/healthz` and (from TASK-038) `/api/v1/auth/login`: no response header starting `Access-Control-Allow-`; also no such header on a normal `GET` with an `Origin` | `CORSMiddleware(allow_origins=["*"])` added | L |
| CHK-M2-014 | CODE | REQ-036 (1), (2) | Responses with 200, 204, 401, 403, 404, 405, 413, 422, 429, 500 (a test route raising `RuntimeError`, client with `raise_server_exceptions=False`) and 503: each carries the four headers exactly once (`response.headers.get_list`), HSTS and CSP byte for byte as in the table | headers added only in a route dependency, or not on the 500 path | L |
| CHK-M2-015 | CODE | REQ-036 (3) | A test route that sets its own `Content-Security-Policy: default-src *` and a duplicate `Referrer-Policy`: the response still has exactly the spec value, once each | `setdefault` instead of overwrite | L |
| CHK-M2-016 | CODE | REQ-037 (1), #57 (b) | POST to a test route that reads the body: 1,048,576 bytes passed on (handler sees exactly that length); 1,048,577 bytes get 413 | cap 1,000,000 or 1,048,577 | L |
| CHK-M2-017 | CODE | REQ-037 (2) | Raw ASGI drive (custom `receive`): `Content-Length: 5000000` with a body generator that counts bytes pulled: 413, the handler never runs, at most 1,048,577 bytes pulled; a `Content-Length` that lies low (declares 10, sends 2 MB) is still cut off at cap + 1 | cap checked only on `Content-Length` | L |
| CHK-M2-018 | CODE | REQ-037 (3) | Chunked body without `Content-Length` (ASGI `more_body` chunks of 64 KiB, 2 MB total): 413, reading stops after ≤ cap + 1 bytes (counter), handler never runs | cap checked only on `Content-Length` | L |
| CHK-M2-019 | CODE | REQ-037 (4), 413 ruling | The 413 body is problem details (five keys, status 413, `type` `too_large`, `instance` = path) with the four headers | plain-text 413 | L |
| CHK-M2-020 | CODE | REQ-037 (5) | The cap registry (as named in the TASK-024 report) accepts each TS §6.3 class at exactly its value (table above); registering 1 byte above the value for its class, or an unknown class, raises at `create_app()` | registry validation removed | L |
| CHK-M2-021 | CODE | REQ-006 (1) narrowed, G6 | `manager/tests/test_app.py` and `test_openapi.py` (updated where the M0 assertions are superseded): export still deterministic; OpenAPI unchanged by TASK-024 | — | L |

## TASK-025 Runtime contract and app pool (REQ-044, REQ-055, REQ-056; TP-M2-03)

Tests in `manager/tests/test_runtime.py` (L) and `manager/tests/test_db_pool_pg.py` (W, marker `pg`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-030 | CODE | TASK-025 acceptance | A `Runtime` built only from test fakes (fake clock, database, cipher, gate, limits) type-checks under `mypy --strict` (a typed test module included in the mypy run) | a Protocol method signature changed in the fake | L |
| CHK-M2-031 | CODE | REQ-055 (2) | Unit with a fake transaction: on-commit hooks run in registration order after commit, not at all after rollback or after an exception in the body; a hook that raises does not undo the commit and is logged by type only (no message text) | hooks run before commit | L |
| CHK-M2-032 | CODE | REQ-044 | The fake clock is timezone-aware UTC; `SystemClock().now()` is aware UTC | naive datetime | L |
| CHK-M2-033 | CODE | TASK-025 acceptance | PostgreSQL: a pool from a `bitscan_app` DSN gives connections whose `session_user` is `bitscan_app`, `rolsuper` false, `transaction_isolation` `read committed`, not autocommit; an `audit_log` append (M1 `append_entry`) inside `transaction()` commits and is visible from another connection; with an exception in the body it is not | autocommit pool | W |
| CHK-M2-034 | CODE | REQ-055 (2) | PostgreSQL: on-commit hooks fire after a real COMMIT and never after ROLLBACK | — | W |
| CHK-M2-035 | CODE | REQ-039, REQ-019 (8) | DSN with a canary password pointing to a closed port and to a wrong password: `transaction()` and `ping()` fail with the scrubbed error / `False`; canary sweep (message, chain, `repr`, logs incl. `psycopg.pool` logger) finds nothing; `ping()` never raises | driver error re-raised `from exc` | W |
| CHK-M2-035a | CODE | REQ-039; decisions 2026-10-22 (TASK-046 ruling (a)) | DSN whose `host` (with the real `hostaddr`), `user`, `dbname` and `password` are canaries, refused by PostgreSQL: `DatabaseUnavailable` reads `database unavailable: <type>` with no chain; at least one psycopg record is captured; no canary and no libpq `port N` text in the error, its traceback, or any captured record's message, arguments or exception | the TASK-025 scrub-only filter (driver text kept); `psycopg.pool` missing from the filtered loggers; libpq text kept in `DatabaseUnavailable` | W |
| CHK-M2-036 | CODE | REQ-056 | `ping()` returns `True` on the migrated database and within ~2 s `False` when the server is paused | — | W |
| CHK-M2-037 | CODE | TASK-025 | Nested `transaction()` on one thread raises (plan edge case) | — | L or W |

## TASK-026 Problem details and pagination (REQ-038; TP-M2-04)

Tests in `manager/tests/test_problems.py`, `manager/tests/test_pagination.py`.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-040 | CODE | REQ-038 (1) | Unknown path (404), wrong method (405), validation error (bad JSON body, missing field, wrong type, bad query param: 400 `invalid_request`), 413, `HTTPException` 401/403/409/429/503 from test routes, unhandled exception (500): each `application/problem+json`, keys exactly the five, `status` = HTTP status, `instance` = path without query string (request sent with `?a=CANARY`) | FastAPI default `{"detail": …}` handler left for one class | L |
| CHK-M2-041 | CODE | REQ-038 (2) | Canary sweep over all error bodies: a test route raising `RuntimeError("CANARY…")`, a psycopg-style error whose text holds a DSN with a canary password, a validation error on a field whose value is a canary token, a header `Authorization: Bearer <canary>`: no body contains the canary, a traceback marker (`Traceback`, `File "`), `SELECT`, `postgresql://` or `password=` | 500 detail = `str(exc)` | L |
| CHK-M2-042 | CODE | REQ-038 (3) | A validation error names the field (`loc` path or field name in `detail`) and never its value (value is a canary); status 400. A client-chosen string never appears in `detail` (decisions 2026-10-21 "Lead rulings on TASK-026 TEST questions" (1)): a dict key under a declared field and an undeclared extra key on an `extra="forbid"` model, each a canary, are absent; the path keeps declared field names and list indexes only and reports the first client-chosen key generically | value echoed (FastAPI `input`); raw `loc` joined, echoing dict or extra keys | L |
| CHK-M2-043 | CODE | REQ-038 (4) | Pagination helper on a test list route over a fake source of N + 1 items: `limit` absent → 50; 1 and 500 accepted; 0, 501, `-1`, `abc`, `1.5`, `""` → 400; walking `limit=N` returns every item once, in a stable order, `next_cursor` null exactly on the last page; N in {1, 2, 49, 50, 500}; empty source → `{"items": [], "next_cursor": null}` | off-by-one at the page edge | L |
| CHK-M2-044 | CODE | REQ-038 (4) | Cursor tampering: a cursor with one character flipped, truncated, base64 garbage, a valid cursor from another list route (foreign), and a hand-built cursor without the integrity part (as far as the format allows): each 400; a cursor never exposes raw SQL or a DSN | cursor accepted without its check | L |
| CHK-M2-045 | CODE | REQ-038 (5) | The shared UTC timestamp type in `bm/api/` (decisions 2026-10-21 "Lead rulings on TASK-026 TEST questions" (2)): an aware UTC value serialises with `Z`; a +08:00 and a −05:00 value serialise as the same instant in UTC with `Z`; microseconds kept; a naive datetime is refused; the output parses with `datetime.fromisoformat`. Re-run on every timestamp in the TASK-038, -041 and -043 responses with the PostgreSQL session `TimeZone` set to `Asia/Singapore` (CHK-M2-174, -211, -233) | local time zone output | L |
| CHK-M2-046 | CODE | REQ-038, #52 | BIGSERIAL ids appear as JSON integers (not strings) in the helper's output | ids as strings | L |

## TASK-027 JSON logs (REQ-039; TP-M2-05)

Tests in `manager/tests/test_request_log.py`; helper `manager/tests/canary.py`. Logs are captured at the handler the app installs (JSON lines), not only through `caplog`.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-050 | CODE | REQ-039 (1) | Three requests: each yields ≥ 1 record that `json.loads` parses with keys `request_id`, `agent_id`, `job_id` (`agent_id`, `job_id` null); `request_id` equal within a request (including records logged from inside the handler), distinct between requests (also under 20 concurrent requests) | `request_id` in a global, not per request | L |
| CHK-M2-051 | CODE | REQ-039 (2), (3), G28 | Canaries in `Authorization: Bearer`, a `Cookie` header, a custom header, the query string and a JSON and a raw body: no record contains any of them; access record holds method, path without query, status, duration and no header value | `Authorization` header logged | L |
| CHK-M2-052 | CODE | REQ-039 (4) | Handler raising `RuntimeError` with a local variable holding a canary and a body holding another: one record with the exception type and `request_id`; no canary, no locals, no body | `logger.exception` with locals or body | L |
| CHK-M2-053 | CODE | REQ-039 | 413 and 404 paths are logged with status and no body | — | L |
| CHK-M2-054 | CODE | REQ-039 (2) | The canary helper itself: planted canary in a log record, a body, a chained exception and a `repr` is found (the sweep can fail) | sweep that ignores chains | L |
| CHK-M2-055 | CODE | REQ-039 | Records logged outside a request (start-up) still parse as JSON and carry the three keys (null `request_id` allowed) | — | L |
| CHK-M2-056 | CODE | REQ-039 (2) full sweep | M2-wide sweep run at TASK-045/046 and at the gate (CHK-M2-293) | — | W |

## TASK-028 Token and password primitives (REQ-040, REQ-041; TP-M2-06)

Tests in `manager/tests/test_tokens.py`, `manager/tests/test_passwords.py`. Oracles are written in the test with `hashlib`, `base64` and `argon2.low_level`, independent of the implementation.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-060 | CODE | REQ-040 (1), #56 (a) | 10,000 tokens of each kind: all distinct, start with `bsu_` / `bsk_`, total length 47, body matches `^[A-Za-z0-9_-]{43}$`, no `=`, `urlsafe_b64decode(body + "=")` is 32 bytes; the whole token is matched by TS §8.6 pattern 3 (`\bbs[aeku]_[A-Za-z0-9_-]{20,}`, RE2) from end to end | padded token; 31 bytes | L |
| CHK-M2-061 | CODE | REQ-040 (1) | CSPRNG: with `os.urandom` (and `secrets.token_bytes`) patched to return a known 32-byte value, the token body is exactly its base64url; `random` module not used (patched `random.getrandbits`/`random.randbytes` to raise, generation still works) | `random.randbytes` | L |
| CHK-M2-062 | CODE | REQ-040 (2) | `hash` of a token = `hashlib.sha256(token.encode()).hexdigest()` (whole string, prefix included), lowercase, 64 chars; known-answer: `bsu_` + 43 × `A` hashes to the value computed in the test | hash of the body only; uppercase hex; SHA-1 | L |
| CHK-M2-063 | CODE | REQ-040, REQ-044 (1) | Prefix parsing: `bsu_` → session, `bsk_` → api; refused: `bsa_…`, `bse_…`, `BSU_…`, `bsx_…`, no prefix, prefix only, body 42 or 44 chars, body with `=`, `+`, `/`, space, non-ASCII, NUL; a 10 kB string is refused without hashing (hash function spy not called) | `bsa_` accepted | L |
| CHK-M2-064 | CODE | REQ-041 (1), #56 (c) | `hash_password` output matches `^\$argon2id\$v=19\$m=65536,t=3,p=4\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+$`; recomputing with `argon2.low_level.hash_secret_raw(password.encode('utf-8'), salt, time_cost=3, memory_cost=65536, parallelism=4, hash_len=len(hash), type=Type.ID)` from the decoded salt gives the stored hash | argon2i; m=8192; t=1 | L |
| CHK-M2-065 | CODE | REQ-041 (3), (4) | Verify succeeds only for the exact password (not with a trailing space, other case, NFC/NFD variant, truncation); two hashes of one password differ (salt) | — | L |
| CHK-M2-066 | CODE | REQ-041 (2), #56 (b) | Length rule, counted in code points: 11 ASCII refused, 12 accepted; 11 × `😀` (44 bytes) refused, 12 accepted; `é` counts 2; 1,024 accepted, 1,025 refused; no normalisation (NFC and NFD forms are different passwords) | `len(pw.encode())`; upper bound missing | L |
| CHK-M2-067 | CODE | REQ-048 (2) | Dummy verify: runs one Argon2id verification with the same parameters (counting wrapper around the hasher's verify; timing within 0.5× to 2× of a wrong-password verify over 5 runs, reported, not gated); always returns false | dummy that returns without hashing | L |
| CHK-M2-068 | CODE | REQ-041 (5) | Canary sweep: hashing, verifying and refusing a canary password logs nothing containing it or its hash | — | L |

## TASK-029 TOTP core (REQ-042; TP-M2-07)

Tests in `manager/tests/test_totp.py`. Seed for the vectors: ASCII `12345678901234567890` (RFC 6238 Appendix B, SHA1).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-070 | CODE | REQ-042 (1), #49 (a) | Appendix B SHA1 vectors: T = 59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000 give 8-digit `94287082`, `07081804`, `14050471`, `89005924`, `69279037`, `65353130` and 6-digit `287082`, `081804`, `050471`, `005924`, `279037`, `353130` (leading zeros kept); step = floor(T / 30) | dynamic truncation off by one; SHA-256 | L |
| CHK-M2-071 | CODE | REQ-042 (2), (4) | Fake clock at step s: codes of s − 1, s, s + 1 accepted and return their own step (newest when two match); s − 2 and s + 2 refused; boundaries at T = 30k − 1 and 30k | window ± 2 | L |
| CHK-M2-072 | CODE | REQ-042 (4) | Refused without HMAC work: 5 and 7 digits, `12345a`, ` 123456`, `123456 `, `123 456`, `１２３４５６` (full-width digits), `١٢٣٤٥٦` (Arabic-Indic), `""`, `None`, 10 kB string | `str.isdigit()` accepts full-width digits | L |
| CHK-M2-073 | CODE | REQ-042 (5) | Constant time: with `hmac.compare_digest` wrapped by a spy, every verification of a well-formed code calls it exactly 3 times (2 × window + 1), whatever step matches or none; no `==` path (a code matching the first candidate still makes 3 calls) | `==` comparison; early return on first match | L |
| CHK-M2-074 | CODE | #49 (a) | Seed is 20 bytes from the CSPRNG (patched `os.urandom` respected); base32 has no padding; provisioning URI is `otpauth://totp/<issuer>:<username>?secret=…&issuer=…` with `algorithm=SHA1`, `digits=6`, `period=30` present or defaulted, username percent-encoded; the URI round-trips the seed | 16-byte seed | L |
| CHK-M2-075 | CODE | REQ-042 | Naive datetime refused (`ValueError`) | naive accepted | L |

## TASK-030 Vault cipher (REQ-043; TP-M2-08)

Tests in `manager/tests/test_vault.py`, fake server `manager/tests/fake_vault.py`: an HTTPS server on 127.0.0.1 with a test CA generated at test time (no committed key), implementing the two Transit routes with its own encryption (ciphertext `vault:v1:<opaque>`), recording every request; modes good, 403, 500, malformed JSON, missing `data`, wrong base64, slow (beyond timeout), closed port, untrusted certificate (another CA), wrong host name.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-080 | CODE | REQ-043 (1), decisions (1) | encrypt then decrypt round-trips 20 random seeds; requests are `POST <addr>/v1/transit/encrypt/<key ref>` with `plaintext` = base64 of the seed and `…/decrypt/<key ref>`; the token is sent as `X-Vault-Token` (or `Authorization: Bearer`) | — | L |
| CHK-M2-081 | CODE | REQ-043 (1) | The ciphertext contains no form of the seed: raw bytes (latin-1), hex (both cases), base32 (padded and not), base64, base64url | ciphertext = base64(seed) | L |
| CHK-M2-082 | CODE | REQ-043 (2) | Untrusted certificate and wrong host name: refused, no request reaches the handler, nothing returned; the client trusts the test CA only through the documented mechanism (system store via `SSL_CERT_FILE` or the parameter in the TASK-030 report) | `verify=False` | L |
| CHK-M2-083 | CODE | REQ-043 (3) | Vault-token canary sweep over logs, errors, chains and `repr` of the cipher and its HTTP client, on success and each failure mode; the token appears only in the request headers the fake recorded | `repr` shows the token | L |
| CHK-M2-084 | CODE | REQ-043 (4), #58 | Closed port, 403, 500, malformed JSON, missing `data`, bad base64, timeout: each raises the one documented vault error within the configured timeout (+1 s); the message, chain and logs hold no seed, no token and no response-body canary | response body in the message | L |
| CHK-M2-085 | CODE | REQ-043 | The cipher implements the TASK-025 `TotpCipher` protocol (mypy) and opens no connection at construction (patched socket) | connect on init | L |

## TASK-031 User repositories (REQ-044, REQ-048, REQ-051, REQ-052; TP-M2-09)

Tests in `manager/tests/test_user_repos_pg.py` (marker `pg`), all as `bitscan_app`.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-090 | CODE | G1 | `ruff check manager` passes with S608; in a copy, an f-string SQL in `bm/repositories/users.py` is red | f-string SQL | L |
| CHK-M2-091 | CODE | TASK-031 acceptance | Every repository function runs as `bitscan_app` with only the TS §5.2 grants (no 42501): create user, find by username (exact, case-sensitive: `Admin` ≠ `admin`), find by id, set role, set disabled, set password, set/clear TOTP, record failure, reset failures, claim TOTP step, insert session and API token, find active token by hash, touch, revoke one, revoke by user and kind, list by user, lock active admins | — | W |
| CHK-M2-092 | CODE | REQ-042 (3) | Concurrent claim of the same step: deterministic interleave: A claims step s in an open transaction, B's claim of s runs in a thread and blocks; A commits; B returns "not claimed". Also 10 threads × same step: exactly one success. A step equal to or lower than the stored one is never claimed | check-then-update (SELECT then UPDATE) | W |
| CHK-M2-093 | CODE | REQ-048 (3), (4) | 10 concurrent failure records on one user: `failed_logins` = 10 exactly; `next_login_at` = now + min(2^(n−1), 900) s with `now` passed as a parameter (fake clock), checked for n = 1 … 12 and n = 100 (900 s), and after 40,000 failures `failed_logins` stays within SMALLINT (no error) | read-modify-write in Python | W |
| CHK-M2-094 | CODE | REQ-044 | Token lookup is by `token_hash` only and returns the row with its user (kind, revoked, expires, last used, user disabled, role, TOTP enrolled); no function takes a raw token (signature check + a token string never reaches SQL: statement log via `pg_stat_statements` absent, so a statement-capture wrapper on the connection) | lookup by raw token | W |
| CHK-M2-095 | CODE | REQ-051 (7) | Inserting an API token with `totp_verified = true` is impossible through the repository (CHECK or parameter absent) | — | W |
| CHK-M2-096 | CODE | REQ-052 (5) | Admin-row locking: A locks active admins (`FOR UPDATE`) in an open transaction; B's lock waits (seen in `pg_locks`) until A commits | no lock | W |

## TASK-032 Sink transports (REQ-053; TP-M2-10)

Tests in `manager/tests/test_sink_transport.py`, fakes in `manager/tests/fake_sink.py`: a TLS syslog server that parses RFC 5425 frames (`MSG-LEN SP SYSLOG-MSG`) and RFC 5424 headers (`<PRI>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID SD MSG`), and an HTTPS server recording POST bodies; both with a test CA and modes good, untrusted cert, wrong host name, 500, close mid-stream, accept-and-hang.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-100 | CODE | REQ-053 (1), #24 | syslog+tls: each record arrives as one frame whose `MSG-LEN` equals the byte length of the message; the header has version `1` and a valid RFC 3339 timestamp; `MSG` is JSON carrying every `audit_log` column (`audit_id`, `actor`, `action`, `target`, `detail`, `at`, `prev_hash`, `row_hash`); non-ASCII detail survives (length counted in bytes) | LF framing; length in characters | L |
| CHK-M2-101 | CODE | REQ-053 (1), #24, decisions 2026-10-21 "M2 test-plan answers" (2) | https: exactly one audit entry per POST, the body one JSON object (not an array) carrying every column, `Content-Type: application/json`; n entries give n POSTs in `audit_id` order; a 2xx acknowledges exactly that entry (a sink that answers 2xx for entry k and 500 for k + 1 leaves k + 1 unacknowledged and resent); a 500 is a delivery error | 500 treated as success; batch in one POST; one 2xx acknowledging several entries | L |
| CHK-M2-102 | CODE | REQ-053 (3) | The delivered fields re-hash with the M1 `compute_row_hash` to the delivered `row_hash`, for records with null target and null detail, non-ASCII, and nested detail | `detail` re-serialised so the hash no longer matches | L |
| CHK-M2-103 | CODE | REQ-053 (4) | Untrusted certificate and wrong host name fail the send for both transports (no record accepted by the fake) | `CERT_NONE` / `check_hostname=False` | L |
| CHK-M2-104 | CODE | REQ-053 (4), decisions (2) | Refused when the transport is built (configuration error naming `BITSCAN_AUDIT_SINK`, value not echoed if it holds userinfo): `udp://h:514`, `tcp://h:514`, `syslog://h:514`, `syslog+tcp://h:514`, `http://h/x`, `HTTP://h/x`, `ftp://h`, `file:///tmp/x`, `h:514`, `""`, `syslog+tls://` (no host); accepted: `syslog+tls://h:6514`, `https://h/x`, `HTTPS://h/x` per URL rules | `http://` accepted | L |
| CHK-M2-105 | CODE | TASK-032 acceptance | Closed port and accept-and-hang server: the send raises the delivery error within the configured timeout + 1 s; the error text holds no record content | no timeout | L |
| CHK-M2-106 | CODE | REQ-039 | Canary in a record's `detail` never appears in logs or the delivery error | record content logged | L |

## TASK-033 Disk queue (REQ-054; TP-M2-11)

Tests in `manager/tests/test_disk_queue.py` (`tmp_path`).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-110 | CODE | REQ-054 (1) | Records come back in append order after the queue object is recreated (restart); 25,000 records across segment boundaries keep order | — | L |
| CHK-M2-111 | CODE | REQ-054 (1) | Acknowledged records are not returned again, also after recreation; partial ack keeps the rest; ack beyond the tail empties it | — | L |
| CHK-M2-112 | CODE | REQ-054 (6) | A file cut mid-record (every byte offset inside the last record), a last line with a bad checksum, and a cut-off record followed by a later valid append: every earlier record returned, the cut-off one never, later appends readable | partial line parsed as a record | L |
| CHK-M2-113 | CODE | REQ-054 (1), TS §8.7 L1344 | Linux: the folder is created 0700 and every record and state file 0600, also with umask 022 in the test process; an existing folder with group or other write is refused (if the TASK-033 report says so) or reported | files 0644 | W |
| CHK-M2-114 | CODE | REQ-054 (5), #51 (c) | State file (cursor, `outage_since`, alerted) round-trips across recreation; written atomically (a crash simulated between temp write and rename leaves the old state readable) | state written in place | L |
| CHK-M2-115 | CODE | REQ-054 | Durability calls: `os.fsync` called on the file (and folder on Linux) per append (spy) | no fsync | L, W |

## TASK-034 Shipper and outage gate (REQ-053, REQ-054; TP-M2-12; G26)

Tests in `manager/tests/test_shipper.py` (fakes: tail, transport with up/down switch, clock; real `DiskQueue` in `tmp_path`) and `manager/tests/test_shipper_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-120 | CODE | REQ-053 (1) | Sink up: entries sent in `audit_id` order, each once; gaps in ids (rolled-back appends) do not stall | — | L |
| CHK-M2-121 | CODE | REQ-054 (1) | Sink down: new entries are in the queue folder; a new shipper over the same folder (restart) sends them in order once the sink is back and the queue is then empty | records kept only in memory | L |
| CHK-M2-122 | CODE | REQ-054 (2), REQ-055 | Exactly one `audit_sink_unreachable` alert per outage (action `audit.sink_unreachable`, `detail.alert` true, kind `audit_sink_unreachable`), raised at the first failed delivery; 100 further failed cycles raise none; a second, later outage raises a second one; recovery writes `audit.sink_recovered` without `alert` | alert per failed cycle | L |
| CHK-M2-123 | CODE | REQ-054 (3), TS §5.3 | Fake clock: `refusing()` false at 0 s and at 14 min 59.999 s after the first failed delivery, true at exactly 15 min 0 s and later | `>` instead of `>=`; 16 min | L |
| CHK-M2-124 | CODE | REQ-054 (3) | Drain: sink back with records queued: `refusing()` stays true until the queue is empty **and** the cursor has reached the newest committed entry; then false; a sink that accepts one batch and fails again keeps it true | outage cleared on first success | L |
| CHK-M2-125 | CODE | REQ-054 (5), #51 (c) | Restart during an outage (new shipper, same folder, clock +10 min): `refusing()` true at 15 min after the **original** first failure, not 15 min after restart | `outage_since` not persisted | L |
| CHK-M2-126 | CODE | REQ-054 (1), G26 | A record is removed from the queue only after the transport accepted it: transport that raises after receiving (fake records receipt then raises) → the record is still queued and sent again (duplicate with same `audit_id`, `row_hash`, REQ-053 (1)) | ack before send success | L |
| CHK-M2-127 | CODE | REQ-053 (2) | PostgreSQL: an entry appended in a rolled-back transaction never reaches the fake sink; committed neighbours do | send from inside `append_entry` | W |
| CHK-M2-128 | CODE | REQ-053 (6), #51 (b) | PostgreSQL: an entry written by another process/connection (CLI path, no wake) arrives within 5 s via the poll | wake-only, no poll | W |
| CHK-M2-129 | CODE | REQ-053 (5), #51 (e) | PostgreSQL: with the sink up, an in-process committed entry arrives within 5 s of commit (measured over 20 entries, max reported) | — | W |
| CHK-M2-130 | CODE | REQ-053 (1) | Crash between queue append and send (shipper killed, new one started): the entry is sent, possibly twice, never zero times; duplicates carry identical `audit_id` and `row_hash` | — | L |
| CHK-M2-131 | CODE | REQ-054, plan edge case | Database down while the sink is up is not an outage (`refusing()` stays false, no alert); disk-queue write failure is treated as the TASK-034 report states | db error counted as sink outage | L |
| CHK-M2-132 | CODE | REQ-039 | Shipper logs hold counts and id ranges only (canary in `detail` absent) | — | L |
| CHK-M2-133 | CODE | REQ-054 (1), TASK-033 hardening folded into TASK-034 | Linux: a stale `.state.json.tmp` and `.acked.json.tmp` pre-created at 0644 (and 0666 under umask 000), then `save_state` and `ack`: `state.json` and `acked.json` end 0600; a stale empty segment file at 0644 that the queue then writes to ends 0600; the CHK-M2-113 cases stay green | `fchmod` removed (the 2026-10-21 probe gave 0644) | W |

## TASK-035 Alerts (REQ-055; TP-M2-13)

Tests in `manager/tests/test_alerts.py`.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-135 | CODE | REQ-055 (1), #50 | `raise_alert` writes exactly one audit entry through the given transaction, with `detail.alert` true (JSON `true`, not `"true"`), `detail.alert_kind` = the kind, caller detail keys kept; an unknown kind is refused | `alert` as a string | L |
| CHK-M2-136 | CODE | REQ-055 (2) | `bitscan_alerts_total{kind}` (read with `registry.get_sample_value`) rises by exactly 1 after the commit hook runs, 0 before it, and 0 after a rollback | counter incremented at call time | L |
| CHK-M2-137 | CODE | REQ-055 (3), #5 | The counter is in a registry object a later route can serve (`generate_latest(registry)` contains `bitscan_alerts_total{kind="…"}`); no metrics route is mounted in `create_app()` (route walk: no `/metrics`) | — | L |
| CHK-M2-138 | CODE | REQ-055 (1) | Each M2 alert kind in the table is accepted, and each later task's alert uses one of them (cross-checked in that task) | — | L |

## TASK-036 Rate limiter and failed-check aggregator (REQ-047; TP-M2-14)

Tests in `manager/tests/test_ratelimit.py` (fake clock).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-140 | CODE | REQ-047 (1), #55 (c) | 10 sign-in attempts from IP A in one minute allowed, the 11th refused; IP B unaffected; in the next window allowed again; successful and failed attempts both count | limit 11; only failures counted | L |
| CHK-M2-141 | CODE | REQ-047 (2) | 600 requests of user 1 allowed, 601st refused, across calls made for two different tokens of that user; user 2 unaffected; next window allowed | per-token key | L |
| CHK-M2-142 | CODE | REQ-047 (3) | 20 failed checks from IP A → blocked from the 21st; `failed_check_blocked(A)` does not affect `allow_user` for a valid user from A | valid requests counted as failures | L |
| CHK-M2-143 | CODE | REQ-047 (4), #50 (e) | Aggregator: failures at minutes m and m + 2 from IP A, m from IP B: flushing after m + 3 emits exactly three entries (`auth.token_check_failed`, `detail` `{"ip", "window_start", "count"}` with the right counts and RFC 3339 UTC `window_start`), none for m + 1; failed checks answered 429 by the failed-token limit count too: 25 bad requests in one minute (20 × 401, 5 × 429) give `count` 25 and the alert detail carries 25 (decisions 2026-10-21 "M2 test-plan answers" (3)); flush is idempotent (second flush emits nothing); a flush before the minute ends emits nothing for that minute unless forced (shutdown flush, REQ-057 (6)) | one entry per failure; 429-answered requests not counted | L |
| CHK-M2-144 | CODE | REQ-047 (6), #54 (b); decisions 2026-10-21 "Lead ruling on #54 (b)" | Exactly 20 failed checks from one IP in a minute: no `token_check_failures` alert; the 21st: exactly one alert; further failures in the same hour (that minute and later minutes): no second alert; after 60 min another; a second IP has its own alert. Requests answered 429 by the failed-check limit count toward the 21 (20 recorded then 1 more while blocked gives the alert) | alert at 20 (off by one); alert per minute; 429-answered requests not counted | L |
| CHK-M2-145 | CODE | REQ-047 (7) | After the window passes, the keys for that window are dropped (internal size back to 0 after 10,000 distinct IPs and a clock move; observed through the size accessor in the TASK-036 report or memory growth bound) | counters never dropped | L |
| CHK-M2-146 | CODE | #55 (e), #48 | Refusals give a `Retry-After` value = whole seconds to the end of the window (1 … 60) | — | L |

## TASK-037 Auth dependencies (REQ-044, REQ-045, REQ-046, REQ-047; TP-M2-15; G25)

Tests in `manager/tests/test_auth_dependencies.py` (marker `pg` for the matrix; route walk on L). A test app from `create_app(runtime)` adds one test route per dependency (`require_role` viewer/operator/admin, `require_session`, `require_session(allow_restricted)`, `require_totp_session`), plus the real M2 routes once they exist. Tokens and users are inserted as `bitscan_app`; the fake clock and a fake sink gate are injected.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-150 | APP | REQ-044 (1) | On every M2 user route and each test route: no header, `Basic`, `Token`, `Bearer` with empty token, two `Authorization` headers, token in query string or cookie only, unknown well-formed `bsu_`/`bsk_`, unknown prefix: 401 `unauthorized` with one byte-identical body for all causes | header scheme case-sensitive or query token read | W |
| CHK-M2-151 | APP | REQ-044 (1), TS §8.3 Security | `bsa_` and `bse_` tokens refused (401) on every user route, (a) when their SHA-256 is in `agent.token_hash` / `enrollment_token.token_hash`, and (b) when their SHA-256 is planted in `user_token.token_hash` of a live `api` and a live `session` row (so only the prefix check can refuse them) | `bsa_` accepted by the prefix parser | W |
| CHK-M2-152 | APP | REQ-040 (4) | A `bsu_` string whose hash is on an `api` row, and a `bsk_` string on a `session` row: 401 | prefix–kind check removed | W |
| CHK-M2-153 | APP | REQ-044 (2) | Fake clock: session accepted 7 h 59 min after last use, refused at 8 h 0 min; a session used every 59 min is accepted at 23 h 59 min and refused at 24 h 0 min after issue (expires_at) | idle rule removed; idle measured from `created_at` | W |
| CHK-M2-154 | APP | REQ-044 (3) | API token accepted 1 s before `expires_at`, refused at `expires_at` and after `revoked_at` is set | `<` vs `<=` at `expires_at` | W |
| CHK-M2-155 | APP | REQ-044 (4) | After `app_user.disabled = true`, every session and API token of that user gets 401 on the next request | disabled not checked | W |
| CHK-M2-156 | APP | REQ-044 (5), REQ-045 (3) | Viewer's API token gets 403 on the operator test route; role set to operator in another connection and committed; the same token passes on the next request; demoted again → 403 | role cached on the principal or token | W |
| CHK-M2-157 | APP | REQ-044 (6) | Each accepted request moves `last_used_at` (within the 60 s write-skip slack if the report documents one; the idle test above still holds) | — | W |
| CHK-M2-158 | APP | REQ-045 (1) | For each test route and M2 route: every lower role 403 `forbidden`; the minimum role and above not refused by the role check | `>=` vs `>` on the role order | W |
| CHK-M2-159 | CODE | REQ-045 (2), REQ-046 (6) | Route walk over `create_app()`: every route under `/api/v1/` except `POST /api/v1/auth/login` carries a role requirement (dependency marker); every `/api/v1/users` route carries the TOTP-session dependency; health routes outside the walk; a route added in a copy without a dependency makes the walk red | one route without a dependency | L |
| CHK-M2-160 | APP | REQ-046 (a), (2) | `bsk_` of each role on `require_session` routes (and, once present, `/auth/totp/enrol`, `/auth/password`, `POST /api-tokens`): 403 `session_required`, nothing changed | session-only check dropped | W |
| CHK-M2-161 | APP | REQ-046 (b), (1), (3), (5) | `require_totp_session`: admin `bsk_` → 403 `totp_session_required` even while the same admin holds a verified session; admin session with `totp_verified = false` → 403 `totp_session_required`; operator and viewer verified sessions → 403 `forbidden`; admin verified session passes | API token accepted on a TOTP-session route | W |
| CHK-M2-162 | APP | REQ-046 (c), REQ-054 (3) | Fake gate `refusing() = true`: `require_totp_session` → 503 `audit_sink_unavailable`, handler not run; an admin `bsk_` still gets 403 (the more basic reason first); `require_role` and `require_session` routes unaffected | gate not consulted | W |
| CHK-M2-163 | APP | REQ-046 (d), (4) | Admin without TOTP, password-only session (`totp_verified = false`): 403 `totp_enrolment_required` on every route except the two `allow_restricted` ones (`/auth/totp/enrol`, `/auth/logout`), including `GET /api-tokens` and the viewer test route | `allow_restricted` default true | W |
| CHK-M2-164 | APP | #53 (i), decisions 2026-10-21 "M2 test-plan answers" (1) | An admin's `bsk_` token while the admin has no TOTP: 403 `totp_enrolment_required` on every route, nothing changed, and **not** counted as a failed check (21 such requests from one IP never give 429; no `auth.token_check_failed` count for them); after TOTP is enrolled again it works on non-TOTP-session admin routes | admin API token accepted without TOTP; answered 401; counted as a failed check | W |
| CHK-M2-165 | APP | REQ-047 (3); decisions 2026-10-21 "Correction to M2 test-plan answers (3)" | From one IP: 20 bad-token requests → 401, the 21st bad one → 429 `rate_limited` with `Retry-After`. Every token is checked first: once the IP is over the limit, a valid `bsu_` and a valid `bsk_` from it still pass (200, never 429) and are never counted (20 valid + 20 bad then 1 bad → 429 only at the 21st bad); an invalid token from the limited IP gets 429, not 401, and is added to that minute's aggregated count; another IP is unaffected | valid tokens counted; a limited IP's valid token gets 429 (blocked before the token is checked) | W |
| CHK-M2-166 | APP | REQ-047 (2) | 601st request of one user in a minute across two tokens → 429; another user unaffected | — | W |
| CHK-M2-167 | CODE | REQ-039 | Canary sweep over the whole matrix: no token, hash or header value in any log | token logged at DEBUG | W |

Note to CHK-M2-164: answered by `main` 2026-10-21 (decisions 2026-10-21 "M2 test-plan answers" (1)): 403 `totp_enrolment_required`, not a failed check.

## TASK-038 Sign-in and sign-out (REQ-048, REQ-042, REQ-047, REQ-035; TP-M2-16)

Tests in `manager/tests/test_login.py` (unit, counting hasher, fakes) and `manager/tests/test_login_pg.py` (API on PostgreSQL, fake vault, fake clock). Each case uses its own source IP (ASGI `client`) so the per-IP limit does not mix cases, except where the limit is tested.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-170 | APP | REQ-048 (1) | Unknown username, disabled user, wrong password, admin missing code, admin wrong code, reused code, non-admin with TOTP missing code (#49 (c)), attempt during back-off: all 401, byte-identical bodies and identical header sets (except date) | distinct `detail` per cause | W |
| CHK-M2-171 | CODE | REQ-048 (2) | Counting hasher: unknown user, disabled user and back-off each run exactly one Argon2id verification (against the dummy hash); a wrong password runs one; success runs one | dummy verify removed from one path | L |
| CHK-M2-172 | APP | REQ-048 (3), #55 (a) | Fake clock: failures n = 1 … 12 (moving the clock past `next_login_at` each time): `next_login_at` = failure time + 1, 2, 4, …, 512, 900, 900 s; the correct password 1 s before `next_login_at` → 401 and `failed_logins` unchanged; at `next_login_at` it succeeds, `failed_logins` = 0, `next_login_at` NULL | attempt during back-off counted or password checked | W |
| CHK-M2-173 | APP | REQ-048 (4) | 100 failures of an admin: sign-in still possible 15 min after the last failure; `failed_logins` has not overflowed | hard lock | W |
| CHK-M2-174 | APP | REQ-048 (5), #47 (a) | Success: response `{token, expires_at, role, totp_enrolled, totp_verified}` (exact keys), token format per CHK-M2-060; the row has `kind = 'session'`, `expires_at = created_at + 24 h` exactly, `totp_verified` true for a user with TOTP and a fresh code, false for an admin without TOTP; the token works on the next request; every timestamp in the body ends in `Z` and is UTC with the session `TimeZone` set to `Asia/Singapore` (CHK-M2-045) | `expires_at` 8 h | W |
| CHK-M2-175 | APP | REQ-042 (2), (3) | Admin with TOTP: a fresh code → verified session; the same code again → 401; a code of an older step after a newer one was used → 401; two concurrent sign-ins with one code on two connections → exactly one 200 | step claim removed | W |
| CHK-M2-176 | APP | REQ-046 (d) | Admin without TOTP: password-only sign-in → session that passes only `/auth/totp/enrol` and `/auth/logout` (CHK-M2-163 on the real token) | — | W |
| CHK-M2-177 | APP | REQ-047 (1) | 11th `POST /auth/login` from one IP in a minute → 429 problem with `Retry-After` and the headers; another IP passes; next minute passes | limiter not called | W |
| CHK-M2-178 | APP | REQ-048 (7), #54 (a), #50 | Consecutive failures 4 → no alert; 5 → one `login_failures` alert (target the user, no username typed by a stranger, no password); 6–9 none; 10 → second; success resets the count; unknown usernames never alert or write audit; a successful sign-in writes one `auth.login` entry, a logout one `auth.logout` | alert per failure | W |
| CHK-M2-179 | APP | REQ-048 (6) | Logout revokes only the presenting session (another session of the user still works); the revoked token → 401; logout with a `bsk_` → 403 `session_required` and the token still works; logout by a restricted admin session works (204) | logout revokes all | W |
| CHK-M2-180 | APP | REQ-048 (8), REQ-041 (5) | Login responses never contain `password_hash`, `totp_secret_enc`, a token hash, or the password (canary sweep over bodies and logs) | — | W |
| CHK-M2-181 | APP | #58 | Vault down: sign-in of a user with TOTP → 503 (not 401, no fallback, `failed_logins` unchanged); a user without TOTP signs in normally | 401 or bypass when the vault fails | W |
| CHK-M2-182 | APP | REQ-035 (5), G6 | `manager/openapi.json` re-exported: every user path starts with `/api/v1/`; the committed file equals the export | route without prefix | L |
| CHK-M2-183 | APP | REQ-047 (5), #55 (d) | 11 sign-ins from one TCP peer with 11 different `X-Forwarded-For` and `Forwarded` values: the 11th is 429 | proxy headers honoured | W |
| CHK-M2-184 | APP | REQ-038 (3) | Malformed login body (missing field, wrong type, 2 MB body): 400 / 413 problem, no user lookup, no failure counted | — | W |
| CHK-M2-187 | APP | REQ-038 (1), REQ-056; decisions 2026-10-22 (DatabaseUnavailable during token resolution) | Database unreachable while a token is resolved (pool pointed at a closed port, and the pausable proxy paused): every user route and `POST /api/v1/auth/login` answer 503 problem `about:blank` within the pool bound, never 500 and never 401; the response has no DSN, host or driver text; nothing is counted as a failed token check (the IP is not blocked after 25 such requests) | `DatabaseUnavailable` left to the 500 handler; treated as a failed check (401) | W |
| CHK-M2-186 | CODE | REQ-048 (2); decisions 2026-10-21 "sign-in memory bound" | A hasher that blocks inside verify and records the peak number of verifications running at once: 8 concurrent sign-ins (wrong password, correct password, unknown user and back-off mixed) never exceed 4 at once; the 5th to 8th wait and then complete with their normal outcome (200 or the identical 401, never 429 or 503); the unknown-user dummy verification and the back-off dummy verification take the same semaphore as the real one (8 concurrent unknown-user sign-ins also peak at exactly 4, and a mix of 4 real plus 4 unknown never exceeds 4 together) | semaphore removed (peak 8); only the real path takes it (unknown-user peak above 4, or mixed peak above 4) | L (unit), W (through the API) |
| CHK-M2-185 | CODE | REQ-038 (1), (3), #48; decisions 2026-10-21 "OpenAPI error contract" | `manager/openapi.json` (the committed file, and a fresh export that must equal it): no operation lists a `422` response, and no `HTTPValidationError` / `ValidationError` schema remains in `components`. Every operation with a request body or a query or path parameter documents a `400` response whose content is `application/problem+json` with a schema of exactly `type`, `title`, `status`, `detail`, `instance`. Cross-check against the running app: for each such route, a request with an invalid body or parameter gets 400 `application/problem+json`, never 422, so the document matches what the app returns. Re-run in every later route task (TASK-039 to TASK-044) as part of its G6 row | a route added with FastAPI's default 422 response left in the document; the 400 documented as `application/json` | L |

## TASK-039 TOTP enrolment and replacement (REQ-049, REQ-043; TP-M2-17)

Tests in `manager/tests/test_totp_enrol.py` (API on PostgreSQL with the fake vault; W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-190 | APP | REQ-049 (1) | `bsk_` token of any role on both enrol calls: 403 `session_required`; nothing pending, nothing stored | — | W |
| CHK-M2-191 | APP | REQ-049 (2), REQ-046 (4) | Restricted admin: start → `{secret, otpauth_uri}`; confirm with a code from that secret → new token with `totp_verified = true`; the old token → 401; the new one can call `/users` (from TASK-043; until then the TOTP-session test route); the new session's `expires_at` is not later than the old one's (24 h maximum kept) | re-issue extends the 24 h | W |
| CHK-M2-192 | APP | REQ-049 (3) | Replacement with no password, wrong password, no code, wrong code, reused code: refused, `totp_secret_enc` and `totp_last_step` unchanged, the old seed still signs in | replacement without password | W |
| CHK-M2-192a | APP | REQ-048 (3), (7), REQ-049 (3); decisions 2026-10-22 (TASK-039 ruling (c): failed replacement attempts count) | (1) A replacement start with a reused code (used at sign-in), then a wrong password, then a wrong code, the clock moved past each back-off: each answers 403 `forbidden` and raises `failed_logins` to 1, 2, 3 with `next_login_at` = failure time + 1, 2, 4 s. (2) During back-off, a replacement start with the correct password and a correct code: 403, exactly one Argon2id verification (a counting hasher; the dummy check), `failed_logins`, `next_login_at` and `totp_last_step` unchanged, nothing stored. (3) Five consecutive replacement failures raise exactly one `login_failures` alert (`auth.login_failures`, `failed_logins` 5) | the old "not counted" behaviour (round 1 code); back-off not checked; password checked during back-off | W |
| CHK-M2-193 | APP | REQ-049 (4) | Wrong confirmation code: refused; an existing seed unchanged and still valid; the pending seed is discarded (a later right code for it is refused) | seed stored at start | W |
| CHK-M2-194 | APP | REQ-049 (5), REQ-055 | One `totp_enrolled` alert entry for an enrolment, one `totp_replaced` for a replacement (plus `auth.totp_enrol` / `auth.totp_replace` audit), none for a failed attempt | — | W |
| CHK-M2-195 | APP | REQ-049 (6), REQ-043 (1) | `totp_secret_enc` equals the fake vault's ciphertext and holds no form of the seed; the seed never reaches the database before confirm (snapshot after start) | — | W |
| CHK-M2-196 | APP | REQ-049 (7), #53 (b) | A viewer and an operator enrol; a replacement ends the user's other sessions and keeps the re-issued one | — | W |
| CHK-M2-197 | APP | #49 (b) | Pending seed expires after 10 min (fake clock), is bound to the session (another session of the same user cannot confirm it), and is dropped on logout | pending seed per user | W |
| CHK-M2-198 | APP | #58 | Vault down during confirm: 503, nothing stored, old session still valid | — | W |
| CHK-M2-199 | APP | REQ-049, REQ-039 | Canary sweep: the seed, codes and password never in logs, audit `detail` or error bodies; G6 export diff clean | seed in the audit detail | W, L |

## TASK-040 Change own password (REQ-050; TP-M2-18)

Tests in `manager/tests/test_password_change.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-200 | APP | REQ-050 (1) | `bsk_` → 403 `session_required`; hash unchanged | — | W |
| CHK-M2-201 | APP | REQ-050 (2) | Wrong current password → refused (status per the TASK-040 report within #48: 401 or 403, asked if neither), hash and sessions unchanged | — | W |
| CHK-M2-202 | APP | REQ-050 (3), REQ-041 (2) | New password of 11 code points → 400; 1,025 → 400; 12 and 1,024 accepted | — | W |
| CHK-M2-203 | APP | REQ-050 (4), #53 (a) | On success: the new password signs in, the old does not; every session of the user, including the presenting one, → 401; the user's API tokens still work | sessions not ended | W |
| CHK-M2-204 | APP | REQ-050 (5) | One `auth.password_change` audit entry, no password or hash in it (canary) | — | W |
| CHK-M2-205 | APP | REQ-046 (4) | Restricted admin session → 403 `totp_enrolment_required` | — | W |

## TASK-041 API tokens (REQ-051, REQ-040, REQ-046; TP-M2-19)

Tests in `manager/tests/test_api_tokens.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-210 | APP | REQ-051 (1) | Default `expires_at` = creation + 90 days (fake clock, exact); 1 and 365 accepted; 366, 0, −1, `1.5`, `"30"` refused (400); name of 64 accepted, 65 refused | 366 accepted | W |
| CHK-M2-211 | APP | REQ-051 (2), REQ-040 (3) | The create response holds `{token_id, token, name, expires_at}`; the token works on its next request; `GET /api-tokens` items have exactly `{token_id, name, created_at, expires_at, last_used_at, revoked_at}` and no token or hash anywhere in the body; every timestamp in the body ends in `Z` and is UTC with the session `TimeZone` set to `Asia/Singapore` (CHK-M2-045) | hash in list | W |
| CHK-M2-212 | APP | REQ-051 (3), #48 | User B cannot list A's tokens (list shows only B's), and `DELETE /api-tokens/<A's id>` → 404 `not_found` with A's token still working; ids walked from 1 to max+5 | revoke by id without owner check | W |
| CHK-M2-213 | APP | REQ-051 (4) | After `DELETE` (204) the token → 401 on its next request | — | W |
| CHK-M2-214 | APP | REQ-051 (5) | Each creation writes one `api_token_created` alert (and `api_token.create`); a revoke writes `api_token.revoke` | — | W |
| CHK-M2-215 | APP | REQ-051 (6), #8 | `DELETE /api-tokens/{own id}` with a `bsk_` token is allowed (204), including revoking itself | — | W |
| CHK-M2-216 | APP | REQ-051 (7), (8), REQ-046 (e), (2) | A `bsk_` cannot create (403 `session_required`); an admin unverified session cannot create (403 `totp_session_required`); an admin verified session can; viewer and operator sessions can; every API row has `totp_verified = false` | admin without TOTP session creates | W |
| CHK-M2-217 | APP | REQ-040 (5) | After creating 50 tokens (sessions and API), no text column of `user_token`, `app_user` or `audit_log` contains any token string or its body | token in audit detail | W |
| CHK-M2-218 | APP | REQ-054 (4) | Fake gate refusing: `POST /api-tokens` (viewer, and admin verified) and `GET /api-tokens` still work | sink gate on `/api-tokens` | W |
| CHK-M2-219 | APP | REQ-038 (4) | `GET /api-tokens` pagination: 51 tokens with default limit → 50 + cursor, then 1, `next_cursor` null; G6 export diff clean | — | W, L |

## TASK-042 Users service (REQ-052, REQ-041, REQ-055; TP-M2-20 unit part)

Tests in `manager/tests/test_users_service.py` (fake repositories, L) and PostgreSQL parts in `manager/tests/test_users_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-220 | CODE | REQ-052 (1), #56 (d), #53 (f) | Create: Argon2id hash, requested role (viewer default, operator allowed, admin refused per #53 (f)); duplicate username → conflict, no change; username rules (decisions 2026-10-21 "M2 test-plan answers" (4)): 1 and 64 accepted, 0 and 65 refused; `A-Z`, `a-z`, `0-9`, `.`, `_`, `@`, `-` accepted; `a b`, tab, `a/b`, `a:b`, `é`, `ß`, `ä`, Cyrillic `а` (U+0430), full-width `Ａ`, `ǅ` refused; `Ab` and `ab` are different users | case-insensitive duplicate check; `str.isalpha()` accepts Unicode letters | L |
| CHK-M2-221 | CODE | REQ-052 (2) | Disable sets `disabled`, keeps the row, revokes all API tokens and sessions | sessions kept | L |
| CHK-M2-222 | CODE | REQ-052 (3), (4), #53 (c), (d) | Promotion to admin without TOTP → conflict; with TOTP → done, sessions revoked, `role_granted` alert; operator → viewer and admin → operator are demotions: sessions and API tokens revoked; viewer → operator: sessions revoked, API tokens kept | promotion without TOTP | L |
| CHK-M2-223 | CODE | REQ-052 (5) | The last active admin cannot be disabled or demoted (self included, #53 (h)); a disabled admin does not count as active | disabled admins counted | L |
| CHK-M2-224 | CODE | REQ-052 (6), #53 (h) | TOTP reset by another admin clears `totp_secret_enc` and `totp_last_step`, ends sessions, `totp_reset` alert; resetting oneself is refused | self-reset allowed | L |
| CHK-M2-225 | CODE | REQ-052 (7), #53 (e) | Revoke a user's tokens revokes API tokens and sessions, audit `user.tokens_revoke` | — | L |
| CHK-M2-226 | CODE | REQ-052 (8), REQ-055 | Every change writes its audit entry (actions per #50, actor `user:<id>`) and alerts where listed (`user_created`; `role_granted` on any role raise? see note; `totp_reset`); a fake repository that fails after the change forces a rollback: neither change nor entry nor counter increment | entry written in a separate transaction | L |
| CHK-M2-227 | CODE | #53 (g) | Re-enable through the service: `disabled = false`, audited `user.enable`, tokens stay revoked | — | L |
| CHK-M2-228 | CODE | REQ-052 (5) | PostgreSQL: two connections demote the two remaining admins at once (deterministic: A holds the admin lock uncommitted, B's demotion waits, A commits): exactly one succeeds, one active admin remains | guard without the row lock | W |
| CHK-M2-229 | CODE | REQ-052 (8) | PostgreSQL: forced rollback after a role change leaves neither the change nor its audit entry | — | W |

Note to CHK-M2-226: TS §8.4 L1290 says "role granted" alerts; whether every role change or only a raise counts as "granted" is not fixed by #50; the check follows the TASK-042 report and is raised with `main` if the report picks a reading.

## TASK-043 `/users` routes (REQ-052, REQ-046, REQ-054; TP-M2-20 API part)

Tests in `manager/tests/test_users_api_pg.py` (W).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-230 | APP | REQ-052 (1)–(7) | An admin TOTP session does each action through `GET/POST /users`, `GET/PATCH/DELETE /users/{user_id}` with the CHK-M2-220 to -227 effects visible in the database; 409 `conflict` for duplicate, promotion without TOTP, last admin | — | W |
| CHK-M2-231 | APP | REQ-046 (1), (3), (5), REQ-045 (1) | On every `/users` method: admin `bsk_` → 403 (while the same admin holds a verified session), admin unverified session → 403, operator and viewer sessions → 403; nothing changed | TOTP-session dependency removed from one method | W |
| CHK-M2-232 | APP | REQ-054 (3), (4) | Real shipper over a fake sink switched off, fake clock: at 14 min 59 s `/users` works; at 15 min every `/users` method → 503 `audit_sink_unavailable` and changes nothing; sign-in and `/api-tokens` work throughout; after the sink is back and the queue drained, `/users` works again | gate check removed | W |
| CHK-M2-233 | APP | REQ-052 (9) | No `/users` response (list, read, create, patch) contains `password_hash`, `totp_secret_enc`, a token hash or a password; items have exactly the #47 keys; every timestamp in the body ends in `Z` and is UTC with the session `TimeZone` set to `Asia/Singapore` (CHK-M2-045) | hash in the response | W |
| CHK-M2-234 | APP | REQ-052 (6) | After a TOTP reset through the API, that admin's next sign-in gets the restricted session | — | W |
| CHK-M2-235 | APP | REQ-038 (4) | `GET /users` pagination walk; unknown `user_id` → 404; non-integer id → 400 | — | W |
| CHK-M2-236 | APP | G6 | Export diff clean; every `/users` path under `/api/v1/` | — | L |

## TASK-044 Health routes (REQ-056, REQ-036; TP-M2-21)

Tests in `manager/tests/test_health_pg.py` (W) and unit cases in `manager/tests/test_health.py` (L).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-240 | CODE | REQ-056 (1), #5 | `/healthz` 200 `{"status": "ok"}` with the database unreachable (pool pointing to a closed port), no token needed | `/healthz` pings the database | L |
| CHK-M2-241 | APP | REQ-056 (2) | `/readyz` 200 `{"status": "ok"}` on a freshly migrated database | — | W |
| CHK-M2-242 | APP | REQ-056 (3), TS §8.3 Integration | `/readyz` 503 when: the database is unreachable (`db`); `alembic_version` changed to another revision as `bitscan_owner` (`migrations`); the `inventory` row deleted as `bitscan_owner` (`system_schedule`); likewise `offline_sweep` and `retention`; each restored between cases | `inventory` row not checked | W |
| CHK-M2-243 | APP | REQ-056 (4) | Each 503 body is problem details naming only the failed check; canary sweep: no DSN, host name, port, role name or driver message | driver message in `detail` | W |
| CHK-M2-244 | APP | REQ-056 (5) | Neither route writes: `pg_stat_database.xact_commit` aside, row counts and `pg_stat_user_tables` `n_tup_ins/upd/del` unchanged across 50 calls; the statement capture shows only `SELECT` | — | W |
| CHK-M2-245 | APP | REQ-056 (6), REQ-036 | Both routes (200 and 503) carry the four headers; no token required; `Authorization` with a bad token does not turn them into 401 and is not counted as a failed check; 100 calls in a minute never 429 (#5: no rate limit) | rate limit applied | W |
| CHK-M2-246 | CODE | REQ-056, #5 | `/healthz` and `/readyz` are not under `/api/v1` and are outside the REQ-045 route walk; `/api/v1/healthz` → 404 | — | L |
| CHK-M2-247 | CODE | TASK-025 plan | `create_app(runtime)` lifespan starts and stops the lifecycle once each; `create_app()` with no runtime still exports OpenAPI; a route that needs the runtime with none set gives a 503 problem | — | L |
| CHK-M2-248 | CODE | G6 | Export diff clean | — | L |
| CHK-M2-249 | APP | REQ-056 (3), (4); decisions 2026-10-21 (readyz bound) | Database paused while the app holds open pooled connections (the TASK-025 pausable TCP proxy, and once as a probe with a real `docker pause`): `/readyz` answers 503 problem `db` (or the first failing check) within 5 s, three times in a row, and never hangs. The migrations and `system_schedule` checks are also bounded: with the proxy pausing only after `ping()` has succeeded, so the stall hits the revision or schedule query, `/readyz` still answers 503 within 5 s. Every request runs under a 15 s watchdog in the test, so a hang fails as red, not as a stuck run. `/healthz` stays 200 meanwhile; after the resume `/readyz` is 200 again. The WSL script wraps each pytest in `timeout 120` | revision/schedule queries run on a pooled connection with no client-side bound (the CHK-M2-036 round-1 pattern) | W |

## TASK-045 `bitscan-manager serve` (REQ-057, REQ-039, REQ-047, REQ-053; TP-M2-22; G27)

Tests in `manager/tests/test_serve_linux.py` (W, Linux only; skipped with "not run: Linux only" on L, never silently), certificates from `manager/tests/certs.py` (test CA and leaf certificates generated at test time). The real `bitscan-manager serve` runs as a subprocess on a free port against the migrated container, a fake vault and a fake HTTPS sink.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-250 | APP | REQ-057 (1) | Each of the eight serve variables unset, and set to an invalid value (non-TLS DSN, unreadable file, bad listen, plain sink `http://`): exit non-zero before binding (port still free; nothing listens), stderr names each variable; canary sweep of stdout/stderr | binds before validating | W |
| CHK-M2-251 | APP | REQ-057 (2), G27 | TLS 1.2 and 1.3 handshakes succeed (`ssl.SSLContext` pinned to each version, verifying the test CA); TLS 1.0 and 1.1 fail with a server-side protocol alert. Control: the same 1.0/1.1 client (with `@SECLEVEL=0`) completes a handshake with a control server that allows 1.0, so the refusal is the manager's | TLS minimum lowered to 1.0 | W |
| CHK-M2-252 | APP | REQ-057 (2) | A plain-HTTP request to the port gets no HTTP response with an app status (no `HTTP/1.1 200`, no security headers); the process keeps serving TLS | — | W |
| CHK-M2-253 | APP | REQ-057 (3), G27 | Replace cert and key with a new pair, `SIGHUP`: new connections see the new certificate (fingerprint), PID unchanged, listening socket inode unchanged (`/proc/<pid>/fd` and `/proc/net/tcp`), an open keep-alive connection is not dropped | `SIGHUP` handler removed | W |
| CHK-M2-254 | APP | REQ-057 (3) | `SIGHUP` with an unreadable key, a mismatched pair, and a truncated certificate: old certificate kept, process alive, one error log record with no key material (canary planted in the bad key file) | process exits or swaps to a broken context | W |
| CHK-M2-255 | APP | REQ-057 (4) | `/healthz` over TLS carries the four headers | — | W |
| CHK-M2-256 | APP | REQ-057 (5), #55 (d) | 11 sign-ins from 127.0.0.1 with different `X-Forwarded-For` / `Forwarded` → the 11th 429; the access log shows no forwarded address | uvicorn proxy headers on (its default trusts 127.0.0.1) | W |
| CHK-M2-257 | APP | REQ-057 (6), REQ-047 (4) | 3 failed token checks in the current minute, then `SIGTERM` before the minute ends: the process exits 0 within 10 s; one `auth.token_check_failed` entry with `count` 3 is in `audit_log`; with the sink down, the queue folder files are still there and unchanged after exit | flush missing on shutdown | W |
| CHK-M2-258 | APP | REQ-057 (7) | `BITSCAN_MIGRATE_DSN_FILE` pointing to an unreadable file: `serve` starts and answers `/healthz` | — | W |
| CHK-M2-259 | APP | REQ-057 (8), REQ-008 | `tests/test_cli.py` updated: `serve` is a real command; `bits rebuild` and unknown commands keep the M0 behaviour (non-zero, no `BITSCAN_*` read, no database module imported) | — | L |
| CHK-M2-260 | APP | #58 (a) | Vault unreachable at start: `serve` starts, logs one error, `/healthz` and `/readyz` 200; sign-in of a TOTP user 503 | serve refuses to start | W |
| CHK-M2-261 | APP | REQ-053 (4), #24 | `BITSCAN_AUDIT_SINK` = `udp://…`, `tcp://…`, `http://…`: `serve` exits non-zero before binding, naming the variable | — | W |
| CHK-M2-262 | APP | REQ-053 (5), (6) | While `serve` runs with the fake sink up: a sign-in's audit entry arrives within 5 s; an entry written by a separate `bitscan-manager users …` process arrives too | — | W |
| CHK-M2-263 | APP | REQ-039 (2) | Canary sweep over the `serve` run (stdout, stderr, JSON log lines): no DSN, vault token, TLS key, password or token | access log with query string | W |
| CHK-M2-263a | APP | REQ-039 (2), (4); decisions 2026-10-21 (reviewer's TASK-027 point) | The real `bitscan-manager serve` (uvicorn) as a subprocess: a request whose query string holds a canary, and a request to a route that raises with a canary in its exception message (a test-only route mounted through the documented test hook, or an existing route provoked to raise per the TASK-045 report; asked if none exists). Neither canary appears anywhere in the process's stdout or stderr, including uvicorn's own `uvicorn.access` and `uvicorn.error` loggers; the app's JSON access record still appears with the path only | uvicorn `access_log` left on; uvicorn's default `log_config` left in place | W |
| CHK-M2-263b | CODE | REQ-047 (4), (7); reviewer request (TASK-036 review); decisions 2026-10-21 user decision (2) | `serve`'s minute flusher with a fake clock and a fake audit writer: (a) the write for minute m fails (database unreachable, or the append raises): the flusher keeps running, the limiter is still drained and pruned (`size()` back to 0 after the window), and the failure is logged by type only; (b) the write for minute m + 1 works: both minutes' `auth.token_check_failed` entries, and the `token_check_failures` alert raised in minute m, are written in order (m's entries before m + 1's, each entry once, alert with `detail.alert = true`); (c) with writes failing long enough to hold more than 10,000 entries: exactly 10,000 are kept, the oldest dropped first, and a log record gives the dropped count as a number only (no IP, window or other content; canary IPs swept); when writes work again the 10,000 newest are written in order | entries dropped on a failed write; no cap (held list grows past 10,000); newest dropped instead of oldest; dropped IPs logged; flusher thread dies on the first failed write; drain skipped after a failure | L (unit), W |
| CHK-M2-263c | APP | REQ-039 (2); decisions 2026-10-22 (TASK-046 ruling (a): any DSN content on stderr or in the logs is a defect) | The real `serve` with an app DSN whose `host`, `user` and `password` are canaries (`hostaddr` the real address, `sslmode=require`) so PostgreSQL refuses it: `/readyz` 503, sign-in 503, several pool reconnect attempts; then neither canary nor libpq's `port N` text appears anywhere in stdout or stderr, and every line is JSON | the TASK-025 scrub-only pool log filter (secrets removed, the rest of the driver text kept) | W |
| CHK-M2-264 | CODE | README | README "Starting the app" names the eight variables and `SIGHUP` reload as TS §8.6/§8.7 state; no secret value in examples | — | L |

## TASK-046 Server CLI `users …` (REQ-058; TP-M2-23)

Tests in `manager/tests/test_cli_users_pg.py` (W) and `manager/tests/test_cli.py` (L). The DSN path is pointed at a temporary file through the mechanism in the TASK-046 report; one APP run on W also uses the real `/etc/bitscan/secrets/app.dsn` in the WSL distribution (created, then removed).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-265 | APP | REQ-058 (1) | `create-admin alice`: row with role `admin`, `totp_secret_enc` NULL, Argon2id hash per CHK-M2-064; existing username → non-zero, no change; first sign-in → restricted session | — | W |
| CHK-M2-266 | APP | REQ-058 (2), #7 | On a pseudo-terminal (`pty`): prompts twice with echo off; mismatch → non-zero, no row; 11 code points → non-zero; matching 12 → created. With no TTY: one line from stdin. A `--password` argument → non-zero (unknown option); `BITSCAN_ADMIN_PASSWORD`, `PASSWORD` and similar in the environment are ignored (empty stdin still fails) | password taken from argv or env | W (pty), L (non-TTY) |
| CHK-M2-267 | APP | REQ-058 (3), REQ-040 | `create-api-token bob`: stdout is exactly one token line (format CHK-M2-060) and no other secret; the database holds only its SHA-256; it works on the API; `--days 365` accepted, `--days 366` and `0` refused; `--name` of 65 refused; default 90 days; unknown and disabled users → non-zero, no row | token printed twice or logged | W |
| CHK-M2-268 | APP | REQ-058 (4) | `reset-totp carol`: `totp_secret_enc` and `totp_last_step` NULL, her sessions revoked, `totp_reset` alert | sessions kept | W |
| CHK-M2-269 | APP | REQ-058 (5), REQ-019 (5) | DSN file missing, unreadable, empty, `sslmode=disable` or no `sslmode`: non-zero, message names the file path, no canary from the DSN on any stream (an unreadable file is a folder, since the CLI runs as root and `chmod 0` does not stop root) | DSN in the error | W, L |
| CHK-M2-269a | APP | REQ-058 (5); decisions 2026-10-22 (TASK-046 ruling (a)) | A well-formed TLS DSN whose `user` and `password` are canaries, refused by PostgreSQL: exit 1, stdout empty, stderr says `database error (<type>)`, and neither canary appears on either stream, including the `psycopg.pool` connection-failure records | exception text printed (`dsn-in-error`); the TASK-025 scrub-only pool log filter | W |
| CHK-M2-270 | APP | REQ-058 (6) | A `sys.addaudithook` recorder (`socket.connect`, `socket.getaddrinfo`) in the CLI subprocess: only the PostgreSQL host and port are contacted (no vault, no sink). libpq connects in C and raises no Python audit event, so a probe connect made after the command must be recorded (the recorder works), and the token row proves PostgreSQL was reached | CLI sends to the sink | W |
| CHK-M2-271 | APP | REQ-058 (7), #50, #51 | Each command writes its audit entry with actor `cli:root` and alert (`admin_created` for create-admin, `api_token_created`, `totp_reset`); while `serve` runs they reach the fake sink (CHK-M2-262) | — | W |
| CHK-M2-272 | APP | REQ-058 (8) | Unknown `users` subcommands and `users` alone: non-zero, no database module imported, no `BITSCAN_*` read (M0 recorder) | — | L |
| CHK-M2-273 | CODE | README | README "Users" section documents the three commands, the prompt rule (#7) and the DSN path, without a secret in examples | — | L |

## TASK-047 Web client (REQ-059; TP-M2-24)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-280 | CODE | REQ-059 (1), G16 | G6 export, then `cd web && npm run gen:api`, then `git diff --exit-code -- manager/openapi.json web/src/api/` plus the untracked check: clean. Locally, while the branch is uncommitted, the same is shown by hashing `manager/openapi.json` and every file under `web/src/api/` before and after the export and `gen:api` (byte-identical, no file added or removed) | `manager/openapi.json` changed without regeneration | L, CI |
| CHK-M2-281 | CODE | REQ-059 (2), #5 | Every M2 user path in `web/src/api/schema.d.ts` starts with `/api/v1/`; `/healthz` and `/readyz`, if present, are outside it | — | L |
| CHK-M2-282 | CODE | REQ-059 (3) | `web/src/api/client.test.ts`: `client.ts` has no absolute origin (`http://`, `https://`, `//host`), `baseUrl` is `""`; a type-level call `client.POST("/api/v1/auth/login", { body: { username, password } })` compiles and a wrong path (`/auth/login`) fails under `// @ts-expect-error`; `npm run typecheck`, `npm run lint`, `npm test` pass | `baseUrl: "/api/v1"` (paths doubled) | L |

## M2 Security suite and gate (TP-M2-25; G25, G28)

Tests in `manager/tests/test_security_m2.py` (W), run on every PR touching auth (TS §8.3).

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M2-290 | APP | REQ-044 (1), TS §8.3 | Wrong route group: `bsa_` and `bse_` on every M2 user route → 401 (agent routes are M3; the user-token-on-agent-route half stays uncovered, see the coverage matrix) | — | W |
| CHK-M2-291 | APP | REQ-046, TS §8.3 | API tokens refused for every M2 sensitive action (`/users` all methods), token creation (`POST /api-tokens`) and TOTP changes (`/auth/totp/enrol` both calls), for each role; the reusable TOTP-session dependency is the one on `/users` (route walk) | — | W |
| CHK-M2-292 | APP | REQ-044 to REQ-058 | End to end: `users create-admin` (CLI) → sign-in (restricted) → enrol → TOTP sign-in → `POST /users` → `POST /api-tokens` → `DELETE /api-tokens/{id}` → logout, against `serve` with the fake HTTPS sink: every committed `audit_log` entry arrives in `audit_id` order, re-hashes to its `row_hash`, and the delivered stream verifies as one chain with the M1 verifier (each `prev_hash` = previous `row_hash`) | — | W |
| CHK-M2-293 | APP | REQ-039 (2), REQ-041 (5), REQ-043 (3), G28 | Full canary sweep over CHK-M2-292 plus failed sign-ins, a TOTP replacement, a password change, vault errors and `serve` start/stop: no canary in any log record, stdout, stderr, response body, audit `detail` or sink payload (except the one-time token responses and CLI stdout, which must contain exactly their own token) | `Authorization` header logged in `bm/api/request_log.py` | W |
| CHK-M2-294 | APP | REQ-040 (5), REQ-022 (2) | After CHK-M2-292: no raw token in any text column of the whole database (every table and text/jsonb column scanned as `bitscan_owner`) | — | W |
| CHK-M2-300 | CODE | G1 | `ruff check manager` exit 0; in a copy: f-string SQL in `bm/repositories/users.py` (S608) and `import re` in `bm/auth/totp.py` (TID251) are each red | as stated | L |
| CHK-M2-301 | CODE | G2 | `ruff format --check manager` exit 0; one misformatted line in `bm/auth/dependencies.py` is red | as stated | L |
| CHK-M2-302 | CODE | G3 | mypy exit 0; an untyped function in `bm/auth/login.py` is red | as stated | L |
| CHK-M2-303 | CODE | G5 | `cd manager && PY -m pytest --cov=bitscan_manager/services --cov-fail-under=85` exits 0 on L from unit tests alone (`pg` skipped); a planted untested 20-statement function in `bm/services/users/accounts.py` is red | as stated | L |
| CHK-M2-304 | CODE | G6 | OpenAPI export then `git diff --exit-code -- manager/openapi.json` plus the untracked check; a route added in `bm/api/user/users.py` without re-export is red | as stated | L |
| CHK-M2-305 | CODE | G18 | `cd /root/bitscan-tester/manager && CI=true /root/venv-m2/bin/python -m pytest --cov=bitscan_manager/services --cov-fail-under=85 -rs`: every test passes, **0 skipped**, coverage ≥ 85 %, no container left behind | any of G25 to G29 planted | W; CI |
| CHK-M2-306 | CODE | all M2 | The same on L (`CI` unset): unit tests pass, `pg` and Linux-only tests skipped with their reasons (reported, not counted as pass) | — | L |

## Security mutation table

Each row is planted in a throwaway copy, one at a time; the named checks must turn red for the planted reason, and the unmodified copy must be green. These run in the TEST step of the task that owns the code, and all of them again at the M2 gate (G25 to G29).

| Id | Rule (spec) | Mutation | Must turn red | Where |
| --- | --- | --- | --- | --- |
| CHK-M2-320 | Token prefix per router (TS §6 L1056, §2.3) | `bsa_` (then `bse_`) added to the accepted user prefixes | CHK-M2-063, -151, -290 | L, W |
| CHK-M2-321 | Prefix matches row kind (REQ-040 (4)) | kind comparison removed from token resolution | CHK-M2-152 | W |
| CHK-M2-322 | Wrong scheme or token location (REQ-044 (1)) | token also read from `?token=` or a cookie; scheme compared case-sensitively off | CHK-M2-150 | W |
| CHK-M2-323 | API token refused on TOTP-session routes (TS §6.2 L1084) | `require_totp_session` replaced by `require_role("admin")` on `PATCH /users/{user_id}` | CHK-M2-159, -231, -291 | L, W |
| CHK-M2-324 | Verified session required (TS §6.2 L1084) | `totp_verified` check dropped from `require_totp_session` | CHK-M2-161, -231 | W |
| CHK-M2-325 | Session-only routes (TS §6.2 L1085) | session check removed from `POST /api-tokens`, then from `/auth/totp/enrol` | CHK-M2-160, -190, -216, -291 | W |
| CHK-M2-326 | Restricted admin session (TS §6.2 L1089) | `allow_restricted=True` on `GET /api-tokens` | CHK-M2-163, -176 | W |
| CHK-M2-327 | 15-minute sink refusal (TS §5.3 L1051) | (a) `>=` → `>`; (b) 15 → 16 min; (c) `outage_since` not loaded from the state file; (d) outage cleared on the first successful send; (e) gate not consulted in `require_totp_session` | (a), (b) CHK-M2-123; (c) CHK-M2-125; (d) CHK-M2-124; (e) CHK-M2-162, -232 | L, W |
| CHK-M2-328 | Queue acknowledged only after the sink accepted (TS §5.3) | ack before the transport returns | CHK-M2-126 | L |
| CHK-M2-329 | Committed entries only (REQ-053 (2)) | send from inside `append_entry` | CHK-M2-127 | W |
| CHK-M2-330 | Constant-time code comparison (REQ-042 (5)) | (a) `hmac.compare_digest` → `==`; (b) early return on first match | CHK-M2-073 | L |
| CHK-M2-331 | SHA-256 only at rest (TS §6.2 L1083) | (a) raw token stored in `token_hash`; (b) hash over the body without the prefix; (c) uppercase hex; (d) BLAKE2b-256 | (a) CHK-M2-217, -294; (b)–(d) CHK-M2-062 | L, W |
| CHK-M2-332 | No secret in logs (TS §8.4 L1287, §5.3 L1052) | (a) `Authorization` header in the access record; (b) query string in the path; (c) password in a failed-sign-in log line; (d) vault token in the client `repr`; (e) DSN in the pool error; (f) traceback with locals | (a), (b) CHK-M2-051, -293; (c) CHK-M2-180, -293; (d) CHK-M2-083; (e) CHK-M2-035; (f) CHK-M2-052 | L, W |
| CHK-M2-333 | Argon2id parameters (TS §6.2 L1087, #56 (c)) | (a) `Type.I`; (b) m = 8192; (c) t = 1; (d) min length 11; (e) length counted in UTF-8 bytes; (f) dummy verify removed from the unknown-user path | (a)–(c) CHK-M2-064; (d), (e) CHK-M2-066; (f) CHK-M2-067, -171 | L |
| CHK-M2-334 | TOTP step used once (TS §6.2 L1087) | (a) claim condition `totp_last_step < step` changed to `totp_last_step <= step` (a reused step accepted); (b) condition removed; (c) check in Python then plain UPDATE; (d) replacement's current code not claimed | (a), (b) CHK-M2-092, -175; (c) CHK-M2-092 (deterministic interleave); (d) CHK-M2-192 | W |
| CHK-M2-335 | Role read each request (TS §6.2 L1081) | role taken from a value cached with the token | CHK-M2-156 | W |
| CHK-M2-336 | Session lifetimes (TS §6.2 L1080) | idle rule removed; `expires_at` = 8 h; re-issue after enrolment gets a fresh 24 h | CHK-M2-153, -174, -191 | W |
| CHK-M2-337 | Failed-check limit counts failures only (TS §6.3 L1136) | valid-token requests counted | CHK-M2-142, -165 | L, W |
| CHK-M2-338 | Source IP is the TCP peer (#55 (d)) | `proxy_headers=True` in `serve` / `X-Forwarded-For` read | CHK-M2-183, -256 | W |
| CHK-M2-339 | Headers and no CORS (TS §6.3 L1140) | header middleware skipped on the 500 path; `CORSMiddleware` added | CHK-M2-014, -013 | L |
| CHK-M2-340 | Body cap (TS §6.3 L1138) | cap checked on `Content-Length` only | CHK-M2-017, -018 | L |
| CHK-M2-341 | Telemetry off (decisions 2026-10-20) | telemetry settings removed | CHK-M2-010 | L |
| CHK-M2-342 | Vault TLS (REQ-043 (2)) | `verify=False` | CHK-M2-082 | L |
| CHK-M2-343 | Sink TLS and plain transports (REQ-053 (4)) | `CERT_NONE`; `http://` accepted | CHK-M2-103, -104, -261 | L, W |
| CHK-M2-344 | TLS 1.2 minimum and `SIGHUP` (TS §6 L1056, §8.7 L1343) | minimum lowered to TLS 1.0; `SIGHUP` handler removed | CHK-M2-251, -253 | W |
| CHK-M2-345 | Password never from argv or environment (#7) | `--password` option added | CHK-M2-266 | L, W |
| CHK-M2-346 | Last active admin (TS §6.2 L1090) | guard without the row lock | CHK-M2-228 | W |
| CHK-M2-347 | Alert counted on commit only (REQ-055 (2)) | counter incremented at call time | CHK-M2-136 | L |
| CHK-M2-348 | No stack trace or secret in error bodies (REQ-038 (2)) | 500 `detail` = `str(exc)`; validation error echoes `input` | CHK-M2-041, -042 | L |
| CHK-M2-349 | Same failure response (TS §6.2 L1086) | wrong password `detail` differs from unknown user | CHK-M2-170 | W |

## Questions for `main` (answered 2026-10-21, decisions.md "M2 test-plan answers")

1. CHK-M2-164: 403 `totp_enrolment_required`, not counted as a failed check.
2. CHK-M2-101: one audit entry per POST as one JSON object; a 2xx acknowledges exactly that entry.
3. CHK-M2-143, -165: requests answered 429 by the failed-token limit count toward the aggregated failed-check count and its alert detail. Corrected (decisions 2026-10-21 "Correction to M2 test-plan answers (3)"): the token is always checked first; a valid token from a limited IP passes with no 429.
4. CHK-M2-220: ASCII letters `A-Z` and `a-z` only.

Also ruled: the 413 `type` is `too_large` on user routes (CHK-M2-019); the TASK-033 stale-tmp hardening (`fchmod`) is folded into TASK-034 and re-tested there (CHK-M2-133).

## Not tested in M2

Everything the M2 coverage matrix in `work/tasks.md` marks uncovered: agent routes and user tokens on them (M3), `bse_`/`bsa_` issue, `/settings`, `/audit-log`, the metrics route (#5), the clock-skew alert, UI screens (M5), folder and user creation by the installer (#6). G7 to G17 are unchanged and stay green in CI; G16 is checked only at the M2 gate (PD-20).
