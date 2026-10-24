# TASK-072 REVIEW: heartbeat (`POST /api/v1/agent/{id}/heartbeat`)

Reviewer: reviewer. Date: 2026-10-23. REQ-070, REQ-086, REQ-088. Spec: TS §6.1 L1063 (the response carries only configuration), §6.5 L1163 (heartbeat contract; a skew between `clock` and `server_time` over 5 minutes alerts), §3.3 L202, L206, L211–L212 (nothing in a heartbeat response can make the agent run anything), §3.7 L484 (helper reporting), §8.4 L1290–L1291 (helper enabled or disabled alerts; clock skew); #25 (a) (unstored fields dropped; `last_error` to the JSON log only), (b) (IP recorded by the dependency), #65 (a) (skew alert at most once per agent per hour), #71 (one entry per event), #73 (a) (`online` at once). Rulings: windows built once and marked on commit (2026-10-23). Inputs:
- `work/reports/TASK-072-impl.md`;
- `work/reports/TASK-072-test.md` (PASS: CHK-M3-235 to -242, -169-072, -235-mut; `manager/tests/test_heartbeat_api_pg.py`, 89 tests; 18 of 18 plants red).

Files reviewed:
- `manager/bitscan_manager/services/agents/heartbeat.py` (new, 117 lines);
- `manager/bitscan_manager/services/agents/__init__.py`;
- `manager/bitscan_manager/api/agent/heartbeat.py` (new, 64 lines);
- `manager/bitscan_manager/api/agent/__init__.py` (`clock_skew` window, router include);
- `manager/openapi.json`;
- the tester-d tests.

TASK-048 revision 2 is reviewed with it, in `work/reviews/TASK-048.md`.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent routes). This is the first one; the user's second approval is still needed.

## What was checked

- **Route.**
  - `Depends(current_agent)` (TASK-063) does the `bsa_` check, the `{id}` match, the 30-per-minute limit and IP recording. The corrected route walk sees its marker (CHK-M3-169-072).
  - The body is `HeartbeatRequest` (TASK-048: unknown keys refused, a `jobs` key refused).
  - The answer is `HeartbeatResponse` with exactly `job_pull_seconds`, `max_parallel_plugins` and `server_time`, taken from the current settings and the Clock (CHK-M3-345 red). After `PATCH /settings` the next heartbeat returns the new value (REQ-070 (1)).
- **Service (one transaction).**
  - It locks the agent row, then `record_heartbeat` sets `last_heartbeat_at`, `agent_version` and `runner_helpers`. An `enrolled`, `stale` or `offline` agent becomes `online` at once (#73 (a)).
  - A helper-set change writes one `runner_helper_changed` alert entry with `{old, new}`: the audit entry and the alert in one, per #71 and the TASK-062 precedent. Resending the same set writes nothing (REQ-070 (3); CHK-M3-368 red). Sets are compared, so a reordered list is no change; this reading is reasonable, though not asserted.
  - A skew of more than 5 minutes (exactly 5 min is silent) writes one `clock_skew` alert holding both times and `skew_s`, at most once per agent per hour. The window is marked only on commit (REQ-070 (4); CHK-M3-367 red). A manager 150 days ahead alerts each agent's first heartbeat.
  - `last_error` is logged at INFO with the request's `agent_id` and never audited. `uptime_s`, `spool_bytes`, `last_pull_at` and `current_job_id` are validated and dropped (#25 (a)).
  - No job row is read or changed (REQ-070 (5), REQ-088).
- **Metric (REQ-086).** `bitscan_heartbeat_latency_seconds` observes the handler's duration on success only, with no labels.
- **Security invariants.** No job, command or anything executable in the response. No connection other than the database. No token in any audit detail or log.
- **OpenAPI (G6).** My re-export is byte-identical. The operation documents 200, 400, 401, 403, 429 and 503 (no 422). `HeartbeatResponse` requires exactly its three keys, with `additionalProperties: false`.
- **Scope.** Four files plus the export, as the task row lists.
- **Tests (my run, Windows).** ruff and format are clean, and `mypy --strict` is clean on the whole tree (200 files). In my combined run of the heartbeat, contract, body-cap, agent-auth, OpenAPI and login files, 718 passed, 114 skipped (PostgreSQL; run in WSL by tester-d) and 9 failed. All 9 are inventory body-cap cases and the documented-error walk, broken by the in-progress TASK-073/074 inventory route in the same working tree. As the lead noted, they are TASK-074 TEST updates and do not touch this task's code.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/agents/heartbeat.py:87-89`. `AgentGone` covers only a missing row, which never happens, because agents are never deleted. If the agent is revoked or decommissioned between the token check and this transaction, the heartbeat is still recorded and the agent may become `online`. TASK-064 refuses on `token_revoked_at` under the row lock for the same race. Optional fix: refuse when `row.token_revoked_at is not None`.
2. **nit (for the lead, same class as TASK-082)**, `manager/bitscan_manager/api/agent/heartbeat.py:147-153`. The declared JSON body is parsed before `current_agent`, so a non-JSON body to a `bsa_` route answers 400 without a token check, and it doesn't count as a failed token check. It costs at most a 1 MiB parse with no database work. Consider whether the TASK-082 route class should also cover the `bsa_` routes that take JSON (heartbeat, results). The after-auth inventory route reads raw and is not affected.

## Carry-overs

- **M4 (Go agent).** `last_error` is written to the manager's application log (#25 (a)), so the agent must never put plugin stdout or stderr, or any token, in it (security invariants "Secrets and output").
- **TASK-079.** The agents-by-status gauge and the latency histogram are scraped from the same registry.
