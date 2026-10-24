# TASK-079 IMPL report: `GET /api/v1/metrics`

REQ: REQ-086. Spec: TS §8.4 L1288–L1289, §2.3 L118; #5, #70 (user ruling 2026-10-23: `GET /api/v1/metrics`, normal bearer check, minimum role viewer; `HealthPath` unchanged). Depends on TASK-056 and TASK-078 (OpenAPI order).

## Files (4)

- `manager/bitscan_manager/services/audit/metrics.py`: adds the protocols `FleetCounts` and `QueueCounts`, and `scrape(agents, jobs) -> bytes`.
- `manager/bitscan_manager/api/user/metrics.py`: new, 45 lines.
- `manager/bitscan_manager/api/user/__init__.py`: mounts the router.
- `manager/openapi.json`: re-exported, byte-stable.
  - Adds `GET /api/v1/metrics`. Its 200 is documented as `text/plain; version=0.0.4; charset=utf-8` with a string schema; refusals 401, 403, 429, 503 are problem+json.
  - Every path in the document still starts with `/api/v1/`, except `/healthz` and `/readyz`, so `HealthPath` needs no change (TASK-081).

## Behaviour

- `require_role("viewer")`: any signed-in role, session or API token (#70; a scraper uses a viewer API token). No token gives 401, as on every user route.
- **At scrape time**, in one read-only transaction, `scrape()`:
  1. Sets `bitscan_agents{status}` for each of the six `agent_status` values from `AgentRepo.count_by_status()`. A status no agent has is set to 0, so every status is always exported.
  2. Sets `bitscan_jobs_queued` from `JobRepo.count_queued()`.
  3. Returns `generate_latest(REGISTRY)`.
- The registry holds these metrics:
  - `bitscan_alerts_total{kind}`: 28 kinds, from zero;
  - `bitscan_agents{status}`;
  - `bitscan_heartbeat_latency_seconds`: histogram, observed by the heartbeat route;
  - `bitscan_jobs_queued`;
  - `bitscan_jobs_expired_total`: increased by the sweep on commit.

  Import failures and the plugin ERROR rate arrive with M7 and M11.
- **Content type:** `prometheus_client` 0.26's `CONTENT_TYPE_LATEST` names text format 1.0.0, while `generate_latest()` writes the classic 0.0.4 format. The route therefore sends `CONTENT_TYPE_PLAIN_0_0_4`, which matches the body and which every Prometheus version parses.
- **Labels are bounded:** only `kind` (a fixed set), `status` (the six enum values) and `le` (the fixed histogram buckets). There is no hostname, token or agent id.
- The response carries the app's security headers, like every response.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (103 files).
- `pytest -q`: 2182 passed. The 9 failures are the known TASK-074 test-file updates (`test_login` ×2, `test_body_caps` ×7).
- **Probe**: `create_app()` with M2's `current_principal` overridden by a viewer API-token principal, and fake counts of online 7, offline 2, queued 4.

  | Check | Result |
  | --- | --- |
  | status and content type | 200, `text/plain; version=0.0.4; charset=utf-8` |
  | `bitscan_agents` | online 7, offline 2, the other four statuses 0 |
  | `bitscan_jobs_queued` | 4 |
  | after 3 latency observations and 2 expired jobs | histogram `_count` 3.0, `bitscan_jobs_expired_total` 2.0 |
  | security headers | present |
  | label names used | `kind`, `le`, `status` |
  | no token | 401 |

- Through the API on PostgreSQL (TP-M3-33, gauges against real counts): **NOT RUN locally**; WSL.

## Deviations

None.
