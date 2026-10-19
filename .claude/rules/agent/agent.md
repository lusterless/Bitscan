---
paths:
  - "agent/cmd/bitscan-agent/**"
  - "agent/internal/agent/**"
  - "agent/internal/inventory/**"
  - "agent/internal/spool/**"
---

# Agent process (`bitscan-agent`)

Spec: TS §3.1–§3.6 (install, enrolment, loops, inventory, jobs, config) and §6.5 (wire contract). Static Go binary, no CGO (TS §2.1, §8.2); modules verified with `go.sum`.

- Runs as user `bitscan` with no capabilities and cannot read root-only files. It is the only network-facing process. It never runs plugin commands itself; it passes whole jobs to the runner over `/run/bitscan/runner.sock`.
- **TLS:** 1.2 or later, preferring 1.3. Verify the manager certificate against the system store, or `ca_file`, and the optional `manager_spki_sha256` pin. Pinning is optional: never fail start-up because no pin is set. Agents have no client certificates. Refuse plain HTTP: `manager_url` must be `https://`, and an `http://` URL is rejected at start-up.
- **Every call:** sends `Authorization: Bearer <bsa_>` and `X-Bitscan-Machine-Id`. Each agent has its own `bsa_` token.
- **Config:** `agent.yaml` keys and defaults are exactly TS §3.6. Its `job_pull_seconds` and `max_parallel_plugins` are used only until the manager sends its values. The agent never writes `agent.yaml`.
- **State:** `/var/lib/bitscan-agent/` (`bitscan:bitscan`, 0700) holds `agent_id`, `token`, `enroll.token` until enrolled, the result spool and the seen job ids.
- **Wire formats:** exactly TS §6.5, generated from or tested against the OpenAPI JSON Schemas shared with the manager. Error `type` values: `pending_approval`, `enrollment_rejected`, `token_revoked`, `token_expired`, `machine_id_mismatch`, `job_not_acceptable`, `too_large`, `rate_limited`.

## Enrolment and token

1. Read `/var/lib/bitscan-agent/enroll.token` and call `POST /api/v1/agent/enroll` with `hostname`, `machine_id` (from `/etc/machine-id`), `agent_version`, `os_id`, `os_version_id` and `os_pretty_name`.
2. Save the `bsa_` token to `token` (0600) and `agent_id` (0644), both owned `bitscan`, along with `issued_at` and `expires_at`. Then delete `enroll.token`.
3. While the response is 403 `pending_approval`, retry with back-off. On 401 (`enrollment_rejected`, `token_revoked` or `token_expired`), stop all loops and log that the host must be re-enrolled.
4. Rotate at `issued_at + max(TTL − 30 days, TTL ÷ 2)` with `POST /api/v1/agent/{id}/token/rotate`. If the rotate response is lost, retry with the old token.

## Loops

- **Heartbeat:** `POST /api/v1/agent/{id}/heartbeat` every 300 s ± 30 s jitter. Send status only (TS §6.5), including the enabled `runner_helpers` every time. Apply `job_pull_seconds` (clamped 60–3,600) and `max_parallel_plugins` (clamped 1–8) from the response. A heartbeat never makes the agent run anything.
- **Job pull:** `GET /api/v1/agent/{id}/jobs` every `job_pull_seconds` ± 30 s. Up to 10 jobs per pull; an empty list means do nothing until the next timer: no extra polling and no collection. Idle target: < 0.1 % CPU and < 30 MB RSS.
- **Accepting a job:** only if it was fetched by this agent over verified TLS, `agent_id` is this host's, `pickup_by` is in the future and no more than 25 h away, and the `job_id` is not among those seen in the last 7 days (kept in the state directory). Start a job before `pickup_by`; it may finish after it.
- **Order:** compliance jobs run one at a time, in pull order. Post an empty results batch (`{"results": [], "final": false}`) when a job starts. Inventory jobs (`kind: "inventory"`, no `plugins` or `redaction_patterns`) run immediately, alongside compliance jobs.
- **Jobs:** never store plugin commands between jobs, and never judge PASS/FAIL; the manager evaluates. If the runner is unavailable (for example no unified cgroup v2), report `runner_unavailable`.
- **Results:** `POST /api/v1/agent/{id}/jobs/{job_id}/results` in batches of at most 50 results and 1.5 MB (gzip allowed, `Content-Encoding: gzip`). The last batch has `"final": true`.
- **Response handling:**
  - 400, 404, 409, 413, 422, or a 403 other than `pending_approval`: drop the batch, log it locally, and report it as `last_error`;
  - any 401 on any loop (including `machine_id_mismatch`): stop all loops and log that the host must be re-enrolled;
  - 403 `pending_approval`: keep the batch and wait with back-off;
  - 429, 5xx and network errors: retry with exponential back-off from 10 s, capped at 5 min, on both loops; results stay in the spool. Nothing else is retried.
- **Spool:** at most 50 MB, holding already-redacted output only. When it is full, drop the oldest results first and report each dropped plugin as ERROR `spool_overflow`.

## Inventory (TS §3.4)

- Collect `os_info` (sources in TS §3.4) and `dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n'` in this process. No runner and no root are needed.
- Upload with `PUT /api/v1/agent/{id}/inventory[?job_id=…]`, gzip compressed. `list_sha256` is the hex SHA-256 of the sorted UTF-8 lines `name\tversion\tarchitecture\tstatus\n`; the manager computes it identically.
- Watch the directory `/var/lib/dpkg/` (inotify `IN_MOVED_TO`, `IN_CLOSE_WRITE` on `status`). Send an unscheduled upload (no `job_id`) when it changes, debounced to once per 10 min.

## Never

- Log plugin output or tokens. Agent logs go to journald.
- Write outside `/var/lib/bitscan-agent`.
- Open a listening socket.
- Add code that executes commands outside the runner.

Tests (TS §8.3): Agent (back-off, spool overflow), Contract (shared JSON Schema fixtures), Security (expired, foreign and replayed jobs; certificate that fails verification or its pin), on Ubuntu 22.04, 24.04 and Debian 12, amd64 and arm64.
