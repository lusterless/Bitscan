# TASK-080 IMPL: README user guide for M3

## What changed

Only `README.md` at the repository root. This is user-guide content, with no task ids or process notes. No code, test or `openapi.json` change.

- **Status:** now reads M3. It lists the new user routes, the six agent routes and the scheduler. It says the agent package, the web UI and compliance scans do not run yet.
- **Starting the app / Stopping:** `SIGTERM` stops the scheduler first, then the server.
- **API section, new bullets:**
  - enrolment tokens: admin TOTP session; refused for API tokens and after a 15-minute sink outage;
  - enrolment requests: list fields, `matches`, `state` filter, approve and reject;
  - hosts: list, detail and packages fields;
  - tags: 0–32 tags, 1–64 characters, `A–Z a–z 0–9 . _ : -`;
  - revoke;
  - settings: the table of seven keys with defaults and ranges; 400 all-or-nothing; no inventory switch; the `settings_changed` and `redaction_default_removed` alerts;
  - audit log: fields, and how to re-check `row_hash`;
  - metrics: `GET /api/v1/metrics`, viewer API token, text format 0.0.4, the five metric families;
  - limits: the failed-check limit is shared across user and agent routes; 1 MiB default body.
- **New "Enrolling agents" section:**
  - creating the first `bse_` token with a curl example (sign in with TOTP, then `POST /enrollment-tokens`);
  - field ranges and defaults; the token shown once; the shared-token hint;
  - the `enrolment_token_risky` and `enrolments_per_hour` alerts; list, read and revoke;
  - approval: awaiting approval gets 403 `pending_approval`; a known machine-id is always held;
  - approve: new versus re-enrolment; `reenrolment_approved`; an expired request token gets 409;
  - reject: new means decommissioned and 401 `enrollment_rejected`; a rejected re-enrolment leaves the host and its old token as they were, so the host must enrol again;
  - deciding twice gets 409; the first inventory job comes on approval.
- **New "Agent API" section:**
  - the route table, token groups and `X-Bitscan-Machine-Id`;
  - the 401/403 types;
  - limits: 30/min per agent, enrol 10/min per IP with every attempt counted, the shared failed-check limit, 429 `rate_limited` with `Retry-After`;
  - body limits: 1 MiB default; inventory 10 MiB as sent, 64 MiB decompressed, 50,000 packages, `raw` 256 KiB; results 1.5 MiB; 413 versus 422; limits checked after the token, audit-logged, and a named inventory job fails;
  - **residual: keep `os_info.raw` flat, because the decoder refuses nesting deeper than 32 levels;**
  - results answer 409 `job_not_acceptable` in this release;
  - the 10-minute unscheduled-upload window;
  - the heartbeat `clock_skew` and `runner_helper_changed` alerts, and a heartbeat sets the host online;
  - rotation: the window formula, early rotation gets 403 plus an alert, the 24 h rule gets 429, the 10-minute overlap, `token_reuse`, the lost-response retry, `rotation_new_ip`, and 401 `token_expired` after `expires_at`;
  - **residual: while the new token is unused, the old token is accepted for at most 30 days after the rotation.**
- **New "Scheduler" section:**
  - inventory runs at start-up and every `inventory_interval_s`;
  - it is queued for hosts that are not decommissioned or awaiting approval and have no open inventory job;
  - 24 h pick-up; cannot be turned off; an interval change takes effect within a minute;
  - `offline_sweep` every 60 s: status thresholds; never-heartbeated hosts age from enrolment or approval; decommission (0 = never); expiry; the 30-minute inventory failure; no retries;
  - the four fleet alerts;
  - error handling and SIGTERM.

Every statement was checked against the current code:

- `services/enrolment/*`, `services/agents/*`, `services/scheduler/*`, `services/settings/store.py`;
- `services/audit/{chain,metrics}.py`, `services/inventory/{decode,upload}.py`, `api/ratelimit.py`;
- `api/user/{enrolment,agents,settings,audit_log,metrics}.py`, `api/agent/*`, `app.py`.

## Files

- `README.md`

## How to check

- `grep -nE "TASK-|REQ-|CHK-|#[0-9]+" README.md` prints nothing (no task ids or question numbers).
- The sections `## Enrolling agents`, `## Agent API` and `## Scheduler` exist, and the API section has the enrolment, hosts, tags, revoke, settings, audit-log and metrics bullets.
- No gate is affected: there are no Python changes, and `openapi.json` is unchanged.

## Notes for the tester

- No shared files touched; nothing outside README.md.
- The two residuals the rulings asked to document are in the "Agent API" section: the "Bodies" bullet (`raw` flat, 32 levels) and the "Token rotation" bullet (30-day cap).

## Revision 1

This revision covers the reviewer's four README nits, which the lead forwarded. Only `README.md` changed. The README already carried edits from TASK-078 revision 1: `detail_text` in the audit-log item shape and in the re-verification steps.

1. **Inventory 400s ("Bodies"):**
   - A missing `Content-Encoding: gzip` (any letter case) gets 400 `invalid_request`.
   - So does invalid gzip, UTF-8 or JSON, U+0000 or a lone surrogate in any string, and nesting deeper than 32 levels.
   - A 400 is audit-logged but leaves a named job to the 30-minute sweep; a 413 or 422 fails it.
   - Source: `services/inventory/{decode,upload}.py`, `api/agent/inventory.py`.
2. **A held re-enrolment's new token with a wrong machine-id ("Authentication"):** the same 401 `machine_id_mismatch` and alert, but nothing is revoked and the request stays pending. Source: `services/enrolment/token_check.py` `_pending_request`.
3. **Inventory `job_id` classes ("Inventory jobs"):**
   - this agent's dispatched inventory job: the upload completes it;
   - a failed or completed inventory job: stored as an unscheduled upload, with the job unchanged;
   - any other id (unknown, another agent's, compliance, queued, running, expired, cancelled): 409 `job_not_acceptable`, nothing stored;
   - unscheduled uploads count toward the 10-minute window.
   - Source: `services/inventory/upload.py`.
4. **`--cacert <ca.pem>`:** the Enrolling agents section now says to add it to each `curl` command when the manager's certificate comes from a private CA.
5. **Path and query ids (TASK-083 behaviour):** added to "Authentication": the hyphenated 8-4-4-4-12 form only, otherwise 400 `invalid_request`.

`grep -nE "TASK-|REQ-|CHK-|#[0-9]+" README.md` still prints nothing.

## Revision 2

This revision follows the lead's instruction, taken from tester-f's optional wording note. Only `README.md` changed, with one sentence added to the "Token rotation" bullet: "A rotation with the old token after the new one has been used, even within those 10 minutes, counts as reuse: both tokens are revoked and an alert is raised." This matches `services/enrolment/rotation.py`, where the previous token after first use takes the reuse path. The text scan (`grep -nE "TASK-|REQ-|CHK-|#[0-9]+" README.md`) still prints nothing. Beyond that scan, which the gate tester re-runs, no re-test is needed.
