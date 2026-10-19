---
paths:
  - "manager/**/services/audit/**"
---

# Audit log, sink, alerts and metrics

Spec: TS §5.3 (audit log integrity), §8.4 (observability and alerts), §8.6 (`BITSCAN_AUDIT_SINK`). Table: `audit_log` (TS §5.2).

## Audit chain

- `audit_log` is append-only and hash-chained: every insert takes `pg_advisory_xact_lock(hashtext('audit_log'))`, sets `prev_hash` to the previous entry's `row_hash`, and `row_hash` = SHA-256 of `prev_hash` and the entry. The app can never UPDATE or DELETE it.
- Retention deletes old entries only after writing an `audit.checkpoint` entry with the id and `row_hash` of the last deleted entry, so the chain verifies from there.
- Every change (RBAC, settings, imports, deletes, decisions) is audited. Failed token checks are one aggregated entry per IP per minute.

## Sink (`BITSCAN_AUDIT_SINK`, syslog or HTTPS)

- Stream every entry to the sink as it is written.
- Wire format: open, see `.claude/rules/manager/config-and-cli.md` (`work/open-questions.md` #24).
- If the sink is unreachable: queue entries on disk in `/var/lib/bitscan/audit-queue`, alert at once, and after 15 minutes of outage refuse sensitive actions (TS §6.2) until the queue drains.

## Alerts

- Every alert is an audit entry with `detail.alert = true` (so it reaches the sink) and increments `bitscan_alerts_total{kind}`.
- Immediate: policy imported (carry every changed `Execute`; flag paths matching `shadow`, `.ssh`, `.pem`, `.key`, `token` or `credentials`), rebuilt or deleted; disabled policy re-enabled; API token created; TOTP enrolled, replaced or reset; user created, role granted or admin created; settings or redaction list changed; a default redaction pattern removed; runner helper enabled or disabled on a host; agent token revoked for machine-id mismatch or token reuse; rotation outside its window or from an IP not in `agent_ip_seen` for the last 7 days; enrolment token created with `auto_approve` or more than 100 uses; re-enrolment approved; all-hosts scan started with an API token; audit sink unreachable; rows in the default `scan_result` partition.
- Threshold: > 5 % agents offline; any `.bit` import rejected; catalog integrity check failed; job queue age > 1 h; repeated 401s from one agent or IP; more than `enrolment_alert_per_hour` enrolments on one token; floods of 409 result posts; clock skew > 5 min; a heartbeating host whose inventory is older than twice the interval; one agent adding more than 1,000 previously unseen packages in a day.
- **Open spec question:** "repeated 401s" and "floods of 409 result posts" have no numeric threshold in TS §8.4; ask before choosing one.
- The login "repeated failures alert" threshold (TS §6.2) is an open question: see `.claude/rules/manager/auth-and-users.md`.

## Logs and metrics

- Structured JSON logs with `request_id`, `agent_id` and `job_id`; never stdout, stderr or tokens.
- Prometheus metrics: agents by status, heartbeat latency, jobs queued/expired, import failures, plugin ERROR rate, and `bitscan_alerts_total{kind}`.

Tests (TS §8.3): Integration (chain verification across a checkpoint; concurrent writers; fake sink outage queues, alerts and blocks sensitive actions after 15 minutes; each alert writes `detail.alert = true`; TS §5.3, §8.4).
