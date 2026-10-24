# TASK-079 REVIEW: `GET /api/v1/metrics`

Reviewer: reviewer. Date: 2026-10-23. REQ-086. Spec: TS §8.4 L1288 (agents by status, heartbeat latency, jobs queued and expired; import failures and plugin ERROR rate come in M7 and M11), L1289 (`bitscan_alerts_total{kind}`), §2.3 L118 (every call carries a bearer token); #70 (user, 2026-10-23: `GET /api/v1/metrics`, normal bearer check, minimum role viewer; `HealthPath` unchanged). Inputs:
- `work/reports/TASK-079-impl.md`;
- `work/reports/TASK-079-test.md` (PASS: `manager/tests/test_metrics_api_pg.py` and `test_metrics_scrape.py`; 3 of 3 plants red).

Files reviewed:
- `manager/bitscan_manager/services/audit/metrics.py` (`scrape`, `FleetCounts`, `QueueCounts`);
- `manager/bitscan_manager/api/user/metrics.py` (new, 40 lines);
- `manager/bitscan_manager/api/user/__init__.py`;
- `manager/openapi.json`;
- the tester-e tests.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Decision conformance (#70).**
  - `GET /api/v1/metrics` with `require_role("viewer")`: any signed-in role, session or API token. No token gets 401.
  - It is a user route, so agent tokens are refused (M2 route-group check). It answers with the app's security headers.
  - `HealthPath` needs no change, since the only paths outside `/api/v1/` are still `/healthz` and `/readyz`.
- **Metrics (REQ-086).**
  - At scrape time, in one read-only transaction, `bitscan_agents{status}` is set for all six statuses from `count_by_status()` (absent ones set to 0), and `bitscan_jobs_queued` from `count_queued()`. Both equal database counts, which the tester checks against real rows.
  - The registry also serves `bitscan_alerts_total{kind}` (28 kinds), `bitscan_heartbeat_latency_seconds` (observed by TASK-072) and `bitscan_jobs_expired_total` (raised by TASK-065 on commit).
  - Labels are only `kind`, `status` and `le`, never a hostname, token or agent id (REQ-086 (3)).
- **Content type.** `text/plain; version=0.0.4; charset=utf-8` (`CONTENT_TYPE_PLAIN_0_0_4`). This matches what `generate_latest()` writes; prometheus_client 0.26's `CONTENT_TYPE_LATEST` would claim format 1.0.0. That is a correct choice, and it is documented in the OpenAPI 200.
- **Concurrency.** Two simultaneous scrapes each set the gauges before generating, so the worst case is a scrape that shows the other's counts, which are equally fresh. Acceptable.
- **OpenAPI (G6).** My re-export is byte-identical. The operation lists 200 (text) plus problem+json 401, 403, 429 and 503.
- **Tests (my run, Windows).** See the TASK-077 review: 80 passed, 128 skipped; ruff, format and `mypy --strict` (209 files) are clean.

## Findings

None.

## Carry-overs

- **TASK-081.** Regenerate the web client. Check that `HealthPath` is unchanged and that the `UserPathsArePrefixed` guard passes with the new routes.
- **TASK-080 (README).** The metrics section names the route, the viewer API token for scrapers, and the metric families.
