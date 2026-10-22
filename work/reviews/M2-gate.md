# M2 GATE REVIEW: auth core and API plumbing (closing check)

Reviewer: reviewer. Date: 2026-10-22. Scope: TASK-023 to TASK-047, REQ-034 to REQ-059 (`work/tasks.md` "M2 gate", G1 to G6, G16, G18, G25 to G29). Inputs: every `work/reviews/TASK-0{23..47}.md`, `work/decisions.md` (2026-10-21 and 2026-10-22 rows), `tests/m2/report.md` (gate rows and "M2 closing"), `README.md`.

Verdict: APPROVED (M2 exit gate). One follow-up is still running and does not block: the re-run of the security mutation table (CHK-M2-320-349-gate).

## 1. Task reviews

All 25 M2 reviews are APPROVED. Three needed a second round, and each round-1 should-fix is fixed and re-tested:

| Task | Round-1 should-fix | Fixed by |
| --- | --- | --- |
| TASK-034 | the outage gate failed open on any non-`DeliveryError` failure | revision 1 |
| TASK-039 | TOTP replacement skipped the sign-in back-off (user ruling (c)) | revision 1 |
| TASK-043 | a `null` in a `PATCH /users` body ran the action | revision 1 |

TASK-033's two pre-review should-fixes (short writes; damage dropping queued entries) were fixed before its TEST step. **No should-fix is open in any M2 review.**

Second approval from the user (TS §8.2) is recorded for all twelve auth tasks: TASK-028 to 031, 037 to 043 and 046 (decisions 2026-10-22).

## 2. Decisions applied or carried over

Each M2 decision row (2026-10-21 and 2026-10-22) was checked against the code:

| Decision | Applied in | Checked |
| --- | --- | --- |
| PD-19 runtime packages; no OTel SDK or OIDC library | TASK-023 locks | lock contents |
| Telemetry off in `create_app()` | `app.py` `TELEMETRY_OFF` (`auto_configure: False`) | grep and G29 |
| #57: HSTS one year; MB = MiB | `app.py` | TASK-024 |
| #48 types; 413 `too_large`; `about:blank` where #48 has none | `api/problems.py` | TASK-026 |
| OpenAPI error contract: no 422; problem+json; documented refusals | `app.py` `_problem_openapi` | `openapi.json` has 0 × `"422"` |
| Validation `detail` never echoes client-chosen strings | `api/problems.py` `_declared` / `_field` | TASK-026 probe |
| Sign-in memory bound: 4 slots, fair; dummy, real and new-hash work all gated | `auth/login.py` `VERIFY_GATE`; `password_change.py`; `api/user/users.py` POST | no `passwords.verify_password` or `dummy_verify` call outside `login.py`; both `hash_password` call sites run under the gate (`password_change.py:40`; `users.py` POST via `VERIFY_GATE`) |
| `DatabaseUnavailable` and `VaultUnavailable` map to 503 | `app.py` handlers | grep |
| Database time bounds: keepalives, `tcp_user_timeout` and `statement_timeout` 5 min | `cli/serve.py` `bounded_dsn` | grep |
| uvicorn `access_log=False`, `log_config=None`, no `limit_concurrency`, `proxy_headers=False` | `cli/serve.py` | grep; CHK-M2-263a |
| Graceful SIGTERM exits 0 | `cli/serve.py` `_Server.capture_signals` | G27 |
| Failed minute flush: hold in order, at most 10,000, drain and prune anyway | `cli/serve.py` `FailedCheckFlusher` | CHK-M2-263b |
| Vault client closed on shutdown; `trust_env=False` for vault and sink | `cli/serve.py`, `auth/vault.py`, `sink_transport.py` | grep |
| Sink: `syslog+tls://` and `https://`; one entry per POST | `sink_transport.py` | TASK-032 |
| TASK-033 `fchmod(0o600)` folded into TASK-034 | `disk_queue.py` `_owner_only` | grep |
| #54 (b): the failed-token alert above 20, once an hour per IP | `api/ratelimit.py` | TASK-036 |
| 429-answered failed checks count (with the correction: every token is checked first) | `auth/dependencies.py` | TASK-037 |
| #53 (i): an admin `bsk_` without TOTP gets 403, not counted, not revoked at reset (user kept it) | `auth/principal.py`, `dependencies.py` | TASK-037, TASK-041 |
| `/readyz` checks only after `ping()`, bounded | `api/health.py:96` | grep |
| TASK-042 lock order: admins before the target | `services/users/accounts.py:209`, `:238` | grep |
| TASK-042: one alert per event; `admin_created` only from the CLI | `accounts.py`, `cli/users.py` | TASK-042, TASK-046 |
| TASK-039 (c): replacement failures count; back-off respected (also TASK-040) | `totp_enrol.py`, `password_change.py` | TASK-039, TASK-040 |
| TASK-043: one change per PATCH; 201; disable only through DELETE; null bodies refused | `api/user/users.py` | TASK-043 round 2 |
| TASK-041 follow-up: the `admin_totp` marker on `POST /api-tokens` | `api_tokens.py:54` | CHK-M2-216-r043 |
| No part of a DSN in stderr or logs | `db/pool.py` `DriverLogFilter`; `cli/users.py` `configure_logging` | CHK-M2-035a, -263c, -269a |
| `route_caps` default (TASK-024 nit) | `app.py:161` | grep |
| G5 plant too small for the current code; a larger plant is the evidence, threshold unchanged (lead ruling 2026-10-22) | gate record | CHK-M2-303 |

**Carry-overs recorded for later milestones (not M2 defects):**
- **M3:** the body-cap registry is exact-path, so the templated agent routes need template matching (TASK-024). The metrics route, if it sits at the root, must be added to `HealthPath` in `web/src/api/client.ts` (TASK-047). The clock-skew alert (TS §8.4) moves to M3 with the heartbeat.
- **Upgrades:** re-run G27 on a uvicorn upgrade (TASK-045 relies on 0.54's `ssl_context_factory` and `capture_signals`). Re-check the psycopg DEBUG line on a psycopg upgrade (residual 2 below).
- **Planning:** update the G5 plant in `work/tasks.md` to a size that still turns the gate red at today's coverage, so the next milestone's gate does not need a ruling.

## 3. Accepted residual risks

1. **`db maintain` clock skew** (decisions 2026-10-20, gap check). A forward skew smaller than the partition window plus one month passes all three drop guards, so partitions inside retention can be dropped up to about 5 months early. The TS §8.4 clock-skew alert would close it; it needs the M3 heartbeat, so this **stays open through M2**.
2. **psycopg DEBUG line** (TASK-046 review, accepted by the user 2026-10-22). `psycopg/transaction.py:144` embeds the connection `repr` (host, user, database) in its DEBUG message text, which `DriverLogFilter` cannot rewrite. It is unreachable at the levels in use (`serve` INFO, CLI WARNING). Re-check on a psycopg upgrade.
3. **syslog has no receipt** (TASK-032 review; decisions 2026-10-21 "Audit sink guidance"). Over `syslog+tls://` a frame counts as delivered once written, so entries in buffers at a connection break can be lost and are not resent. The README tells operators to prefer `https://`, or to watch for `audit_id` gaps.
4. **Vault token lifecycle** (TASK-030 review; user decision 2026-10-21). There is no renewal: an expired OpenBao token makes TOTP sign-in and enrolment answer 503 until the token file is replaced and `serve` is restarted. The README advises a periodic or non-expiring token limited to the Transit paths.
5. **Smaller accepted limits**, all recorded in their reviews:
   - a frozen database server whose network still answers is bounded only by `statement_timeout` (TASK-045);
   - the role is read in a transaction just before the route's own (TASK-037);
   - a CLI alert increments the CLI process's counter, not `serve`'s (TASK-035, TASK-046);
   - `ATTEMPT_S` can overrun by one slow batch (TASK-034).

## 4. README matches the code

- **Variables.** The configuration table lists exactly the 11 `BITSCAN_*` names the loader reads (`config/startup.py`), with formats that match `auth/vault.py`, `sink_transport.py` and `BITSCAN_LISTEN` parsing. It says `serve` never reads `BITSCAN_MIGRATE_DSN_FILE`, which matches `cli/serve.py`.
- **Commands.** `serve`, `users create-admin | create-api-token [--name] [--days] | reset-totp`, `db migrate`, `db maintain`. `bits rebuild` is a stub, as `cli/__init__.py` routes it, and the exit codes (0, 1, 2) match `cli/users.py`.
- **Behaviour.** The README says what the code does on these points: HTTPS only with TLS 1.2+; SIGHUP reload; SIGTERM exiting 0; JSON logs with no query strings; the health routes and their 503 details; the sink guidance; the OpenBao token guidance; sign-in (24 h, 8 h idle, back-off, 10 per minute per address); the password and username rules.
- **Status line and "## API" section (my should-fix, closed 2026-10-22).** The status line used to list only sign-in and sign-out. impl-manager rewrote it to list everything M2 delivers, and added an "## API" section. I checked that section against the code:
  - **General:** bearer prefixes; problem+json errors with 400 for invalid input; `Z` timestamps; `limit` 1–500, default 50; cursors reset on restart.
  - **Sign-in:** the response fields; 24 h maximum and 8 h idle; back-off with no hard lock; 10 attempts a minute per address; the restricted admin session.
  - **TOTP enrolment:** two calls; the pending secret held for 10 minutes; a re-issued verified session; failed replacements counted.
  - **Password change:** 204; every session ends; API tokens are kept.
  - **API tokens:** session only; admins need a TOTP session; 1–365 days, default 90; shown once; an API token may revoke itself.
  - **`/users`:** an admin TOTP session; API tokens refused; the 15-minute sink refusal; viewer or operator on create; exactly one change per PATCH with the documented values; DELETE disables; the promotion, last-admin and revocation rules.
  - **Limits:** 600 a minute per user; 429 after 20 failed token checks a minute.

  Three corrected statements also match the code: `serve` loads the certificate and key and exits 2 on a bad pair (`make_tls_context`); `serve` exits 2 on configuration errors; no part of a DSN is logged. The section is user-guide content only, with no task ids and no secrets in the examples.

## 5. Gate results (G1 to G6, G16, G18, G25 to G29)

The tester's rows are in `tests/m2/report.md`. Each gate is green on the clean tree and red on its planted violation:

| Gate | Row | Clean | Plant → red |
| --- | --- | --- | --- |
| G1 ruff | CHK-M2-300 | exit 0 | f-string SQL (S608); `import re` (TID251) |
| G2 format | CHK-M2-301 | 121 files formatted | misformatted line |
| G3 mypy | CHK-M2-302 | 121 files clean | untyped function |
| G4 hashed locks | CHK-M2-G4 | both locks install | altered argon2-cffi hash refused |
| G5 coverage | CHK-M2-303 | 97.13 % (Windows) | a 120-statement untested function gives 83.47 %, exit 1 (lead ruling; the defined 20-statement plant is too small; 85 % unchanged) |
| G6 OpenAPI | CHK-M2-304 | export byte-identical | a route without re-export |
| G16 client | CHK-M2-G16 | byte-identical | stale `schema.d.ts`; hand-edited `openapi.json` |
| G18 full suite | CHK-M2-305 | WSL, `CI=true`: **1520 passed, 0 skipped**, services 99.32 % | the G28 plant: 2 failed |
| G25 security | CHK-M2-G25 | 41 passed | TOTP-session dependency removed from PATCH; `bsa_` accepted; prefix-kind check removed |
| G26 shipper | CHK-M2-G26 | L 29, W 35 passed | 15-minute check removed; ack before the sink accepted |
| G27 serve | CHK-M2-G27 | 36 passed | TLS minimum 1.0; SIGHUP handler removed |
| G28 canary | CHK-M2-G28 | passed | `Authorization` header logged |
| G29 telemetry | CHK-M2-G29 | 3 passed | `telemetry=` removed |

The M2 security suite (`manager/tests/test_security_m2.py`, CHK-M2-290 to -294) covers TS §8.3's auth Security row on the real routes:
- agent tokens are refused on every user route;
- API tokens are refused for sensitive actions, token creation and TOTP changes;
- the end-to-end chain reaches the sink as one chain (CLI, sign-in, enrolment, user, API token);
- the canary sweep over the whole flow is clean;
- no raw token is at rest in any text column.

G7 to G15 are unchanged since M0 and green.

**My own run on the final tree (Windows):** ruff, format and `mypy --strict` are clean on 121 files. The suite has 1033 passed and 451 skipped (pg and Linux-only, reported as such), with G5 at 97.13 %. The G6 export is byte-identical.

**Not run locally, left to CI on the PRs:**
- the `git diff --exit-code` forms of G6 and G16 (the branch is uncommitted);
- G8 golangci-lint on Linux;
- G17 `systemd-analyze verify` with built binaries (the units are unchanged in M2);
- G18 and G25 to G28 on GitHub runners.

**Follow-up (non-blocking):** CHK-M2-320-349-gate. Every security mutation row already turned red in the TEST step of the task that owns its code. Eight were re-planted red at the gate, and the rest are being re-run against the final tree. If any of them stays green, that is a test defect to fix before merge, not a gate reversal.

## 6. For the user before the PRs are opened

- **The `db maintain` clock-skew residual** stays open until M3. It is the one residual that can lose data inside retention.
- **CI must be green.** CI checks are advisory on this plan (decisions 2026-10-21), so merge only when every check on each M2 PR is green. That especially means the `git diff --exit-code` forms of G6 and G16, G17, and G18 and G25 to G28 on the runners, which have not run on a committed head yet.
- **The security mutation re-run** (CHK-M2-320-349-gate) should be complete before merge.
- **Merge order.** M2 lands as stacked PRs, with no migration in M2 (REQ-033 is not exercised). Use merge commits, as decided for M1, so child PRs keep a valid base.
