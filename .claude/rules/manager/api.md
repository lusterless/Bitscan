---
paths:
  - "manager/**/api/**"
  - "manager/bitscan_manager/*.py"
---

# Manager API

Spec: TS §6 (routes, auth, conventions, agent wire contract) and §3.2 (enrolment and tokens). The route table in TS §6.2 is the RBAC source of truth. `.claude/rules/manager/auth-and-users.md` also loads for `api/user/`, and `.claude/rules/manager/enrolment-and-tokens.md` for `api/agent/`.

- One versioned REST API at `/api/v1`, JSON over HTTPS only (TLS 1.2+), every call with a bearer token. The OpenAPI 3.1 document is generated from code. There is no OIDC or external identity provider. Internal steps use database credentials, never a user or agent token.
- Handlers only validate, authorise and call services (`api → services → repositories`).

## Route groups

- Agent routes live under `/api/v1/agent/` and accept only `bsa_` tokens, plus `bse_` on `POST /agent/enroll`. User routes accept only `bsu_` and `bsk_` tokens. Each group is its own router with its own token dependency.
- Agent endpoints are exactly the six in TS §6.1. On agent routes:
  - the `{id}` in the path must match the token's agent (otherwise 403);
  - an agent awaiting approval gets 403 `pending_approval`;
  - a machine-id header mismatch gets 401 and revokes the token.
- Heartbeat responses carry only `job_pull_seconds`, `max_parallel_plugins` and `server_time`, never jobs or commands.
- `GET /agent/{id}/jobs` returns at most 10 queued jobs for that agent and marks them `dispatched`; the rest wait. Inventory jobs have `kind: "inventory"` and no `plugins` or `redaction_patterns`.
- Accept a result only for a job addressed to that agent, within `dispatched_at` + 7 days, for plugin ids in that job. Return 409 otherwise and audit-log it. A second result for the same plugin is ignored and counted in `duplicates`.
- Re-check every size cap on the server; never trust the agent's own limits:
  - inventory: 10 MB gzip, 64 MB decompressed, 50,000 rows, field lengths, `raw` ≤ 256 KB;
  - result batch: 1.5 MB after decompression;
  - `.bit`: 5 MB;
  - other JSON: 1 MB.

  Larger bodies get 413; decompress as a stream with hard caps.
- Agent-route error `type` values (TS §6.5) are exactly: `pending_approval`, `enrollment_rejected`, `token_revoked`, `token_expired`, `machine_id_mismatch`, `job_not_acceptable`, `too_large`, `rate_limited`. User routes also use 409 `policy_managed_on_server` (TS §4.1, §4.3).

## User routes (TS §6.2 table)

- TOTP-verified session only (API tokens refused): `DELETE /policies/{id}`, `POST /policies/rebuild` (async, returns a task id), `POST /agents/{id}/revoke`, `POST /enrollment-requests/{id}/approve` and `/reject`, CRUD `/enrollment-tokens`, `POST /scans/{id}/reevaluate`, CRUD `/users` (delete means disable) and `PATCH /settings`; all admin.
- Session only, any signed-in user: `POST /auth/totp/enrol`, `POST /auth/password` (current password required), `POST /api-tokens` (viewer).
- Admin, session or API token: `PATCH /policies/{id}`, `POST /policies/import` (one `.bit`, `bsu_` or `bsk_`), `GET /tasks/{id}`, `/imports`, `/enrollment-requests`, `/settings`, `/audit-log`. Only admins create or update policies, and there is no route that edits plugins or commands.
- Operator: `PUT /agents/{id}/tags`, `POST /scans`, `POST /scans/{id}/cancel`, CRUD `/scan-schedules`. Viewer: `GET` and `DELETE /api-tokens` (your own tokens) and the other `GET` routes in the table. No role: `POST /auth/login` and `/auth/logout`.
- **Open spec question:** whether an API token may itself call `DELETE /api-tokens`; the TS §6.2 row has no "session only" marker (`work/open-questions.md` #8).
- Lists (TS §6.2): `GET /policies` takes `?status=enabled`; `GET /scans` filters by policy, host, state and date; `GET /scans/{id}/results` and `/results.csv` filter by status and host; `GET /agents` returns hosts with status, OS, last heartbeat and inventory.
- `GET /scans/{id}/results` and `/results.csv` include `stdout` and `stderr` only for operator and admin. They use the latest re-evaluation per job and plugin and return both `result` and `original_result`.
- Policies: `PATCH` with `{"policy_status": …}` sets `status_overridden = true`; `{"status_overridden": false}` restores `policy_status` from `file_status`. Re-enabling a disabled policy alerts. `DELETE` of a server-folder policy returns 409 `policy_managed_on_server`.
- A scan of a disabled policy returns 409. A scan of a deleted policy must be refused too: no jobs can be built from it (TS §3.3, §4.3).
- **Open spec question:** which status a scan of a deleted policy returns (404 or 409).
- **Open spec question:** whether `GET /policies` lists deleted policies; TS §4.3 says only that a deleted policy disappears from selection (`work/open-questions.md` #9).
- `POST /scans` returns 202 with `{scan_id, state, policy_version, jobs}` (TS §6.4). An all-hosts scan started with an API token alerts.
- There is no endpoint to disable inventory or to run an ad-hoc command.

## Conventions (TS §6.3)

- Errors use RFC 9457 problem details (`type`, `title`, `status`, `detail`, `instance`). Lists use cursor pagination (`?limit=50&cursor=…`, `limit` up to 500).
- `POST /scans` honours `Idempotency-Key`. `/policies/import` is `multipart/form-data` with one `file` field.
- Rate limits:
  - 30 requests/min per agent;
  - 600 requests/min per user;
  - 10 requests/min per IP on `/auth/login` and `/agent/enroll`;
  - 20 failed token checks/min per IP, counting failed attempts only; valid-token requests are never throttled. Failed checks go to `audit_log` as one aggregated entry per IP per minute.
- Response headers: HSTS, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. No CORS: never send `Access-Control-Allow-*`.
- Timestamps are RFC 3339 UTC; IDs are UUID strings except catalog surrogate keys. Agent payloads follow TS §6.5 exactly; the OpenAPI JSON Schemas are shared with the Go agent.
- Package search (TS §7.1):
  - filters combine with AND;
  - `q` with `name`, or `version_op` without `version`, returns 400;
  - `q` needs at least 3 characters;
  - `status` defaults to `installed`;
  - responses are `{items, next_cursor}`; `group_by` pages hold at most 500 groups.
- **Open spec question:** TS §8.4 names `/healthz` and `/readyz` but not their prefix or authentication, and gives no route for the Prometheus metrics, while TS §2.3 says every call carries a bearer token (`work/open-questions.md` #5).
- Health: `/healthz` is liveness; `/readyz` fails unless the DB is reachable, migrations are current and the `system_schedule` rows (including `inventory`) are present.
- Alerts are audit entries with `detail.alert = true` plus the metric `bitscan_alerts_total{kind}`. TS §8.4 lists which events alert.

Tests (TS §8.3): Integration (every endpoint, `/readyz` with the `inventory` row missing, TS §3.4), Contract (agent route schemas), Security (tokens on the wrong route group, API tokens on TOTP-session routes, non-admin policy upload and delete, first result wins under concurrent retries).
