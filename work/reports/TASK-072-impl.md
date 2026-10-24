# TASK-072 IMPL report: heartbeat

REQ: REQ-070, REQ-086, REQ-088. Spec: TS §6.1 L1063, §6.5 L1163, §3.3 L202, L206 and L211–L212, §3.7 L484, §8.4 L1290–L1291; #25, #65 (a), #71, #73 (a). Depends on TASK-051, 055, 056 and 063, all approved. **Two approvals** (TS §8.2).

Carry-overs applied:
- the clock-skew alert fires when the skew exceeds 5 min, at most once per agent per hour, and is marked fired only after commit;
- the window is built once in `create_app()`;
- a helper change is audited and alerts;
- the status follows #73 (`online` at once);
- the #25 fields;
- the latency metric;
- the response holds exactly the three keys;
- no job row is touched.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/agents/heartbeat.py` | new, 117 lines |
| `manager/bitscan_manager/services/agents/__init__.py` | new, re-exports |
| `manager/bitscan_manager/api/agent/heartbeat.py` | new, 64 lines |
| `manager/bitscan_manager/api/agent/__init__.py` | `AgentWindows.clock_skew: OncePerPeriod[UUID]` (1 h), built in `build_agent_windows`; the heartbeat router is included |
| `manager/openapi.json` | re-exported and byte-stable; adds `POST /api/v1/agent/{id}/heartbeat` with `HeartbeatRequest` and `HeartbeatResponse` (exactly three properties, `additionalProperties: false`), plus 400, 401, 403, 429 and 503 as problem+json |

**Export order:** TASK-067's export came first, and TASK-070's will follow both.

## Behaviour

**Route.**
- `Depends(current_agent)` from TASK-063 handles the token, `{id}`, the 30-per-minute limit and IP recording (#25 (b)).
- The body is `HeartbeatRequest` (TASK-048). The answer is `HeartbeatResponse(job_pull_seconds, max_parallel_plugins, server_time)`, from the current settings and the Clock.
- `bitscan_heartbeat_latency_seconds` observes the handler's own duration on success. That covers the transaction and settings read, not the token check.

**Service `heartbeat(...)`, one transaction.**
1. `agents.get(lock=True)`, so concurrent heartbeats judge a helper change once.
2. `record_heartbeat(now, agent_version, helpers)` (TASK-051) sets `last_heartbeat_at`, `agent_version` and `runner_helpers` (stored as sent). An `enrolled`, `stale` or `offline` agent becomes `online` at once (#73 (a)).
3. **Helpers:** if the helper set differs from the stored one (compared as sets, so order alone is no change), one entry is written: `runner_helper_changed` alert, action `agent.runner_helpers_change`, actor and target `agent:<id>`, detail `{old, new}`. This follows #71's "one entry per event", as `settings_changed` does in TASK-062, so it is both the audit entry and the alert of REQ-070 (3).
4. **Clock skew:** if `|clock − now|` is more than 5 minutes (exactly 5 min is no alert) and the per-agent `OncePerPeriod` is due, one `clock_skew` alert is written. Detail: `agent_clock`, `server_time`, `skew_s`. Both times are kept, so a manager-wide skew can be told apart from one host's. `skew.mark` is registered **on commit**.
5. **#25 (a):**
   - `last_error` (at most 1,024 characters, from the contract) is logged at INFO as `agent last_error`, with the request's `agent_id` in the record. It never goes to the audit log.
   - `uptime_s`, `spool_bytes`, `last_pull_at` and `current_job_id` are validated and dropped.
6. If the agent row is missing, `AgentGone` is raised and the route answers 401 `token_revoked`.

No job is read, queued or changed, and no connection is opened besides the database.

## Local gates (Windows)

- ruff and ruff format: pass. `mypy --strict`: clean for `bitscan_manager`. The only errors are in tester-c's in-progress `tests/test_login.py:518`.
- `pytest -q`: 2164 passed, 950 skipped, 3 failed, all in test files:
  - `tests/test_login.py::test_documented_400_…`: the documented-400 walk now also hits heartbeat, which answers 401 before body validation, as enrol does. This is the known update.
  - `tests/test_contract_agent.py::test_document_fixtures_against_openapi`:
    - the same `schema_gap` marking as for enrol;
    - **a contract defect found here and reported to the lead**: FastAPI exports every `minimum`/`maximum` as a float, so `2^63 − 1` becomes `9.223372036854776e18` = 2^63. The document then accepts `uptime_s = 2^63`, which the model refuses. Options are with the lead. The recommendation is to lower the three int64 bounds to 2^53 − 1 in `schemas.py` (TASK-048).
- **Service probe** with fakes and a real `OncePerPeriod`:

  | Case | Result |
  | --- | --- |
  | plain heartbeat | answer (300, 2, now); nothing written |
  | `[]` → `["capread"]` | one `runner_helper_changed` alert, `{old: [], new: ["capread"]}` |
  | the same list again | nothing |
  | skew of exactly 5 min | nothing |
  | 5 min 1 s, rolled back (hook not run) | alert |
  | −5 min 1 s, committed | alert, `skew_s` −301.0 |
  | again within the hour | nothing |
  | an hour later | alert |
  | `job_pull_seconds` patched to 600 | 600 in the answer; `server_time` = the Clock |
  | `last_error` | logged with the agent_id in the record |
  | manager clock 150 days ahead of three agents | each agent's first heartbeat alerts (3) |

- Through the API on PostgreSQL (TP-M3-26): **NOT RUN locally**; WSL.

## Deviations

None in this task's code. The contract defect above is a TASK-048 question for the lead.
