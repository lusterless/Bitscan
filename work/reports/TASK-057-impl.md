# TASK-057 IMPL report: agent rate limits

REQ: REQ-065, REQ-076. Spec: TS §6.3 L1136, §3.4 L239; #72 (e), #55 (c). Recommended second look.

## Files (2)

- `manager/bitscan_manager/api/ratelimit.py`: about 50 lines added.
- `manager/bitscan_manager/runtime.py`: 9 lines added (the `RateLimits` protocol).

## What changed

New constants: `AGENT_PER_MIN = 30`, `ENROL_PER_MIN = 10`, `UNSCHEDULED_INVENTORY_EVERY = 10 min`.

New `RateLimiter` methods, which are also on the `RateLimits` protocol:
- `allow_agent(agent_id: UUID) -> bool`: 30 per agent per fixed UTC minute, the same window as M2 `allow_user`. The 31st request in a minute is refused, and other agents are not affected.
- `allow_enrol(ip: str) -> bool`: 10 per IP per fixed UTC minute. Every attempt counts (#55 (c)).
- `allow_unscheduled_inventory(agent_id) -> bool`: True if the agent's last **allowed** unscheduled upload was at least 10 minutes ago. The window then restarts from now. A refused attempt does not move it, so a retrying agent gets in 10 minutes after its last accepted try. Per #72 (e) the caller asks only when an unscheduled upload reaches decoding; uploads completing a dispatched job are exempt and never ask.
- `unscheduled_inventory_retry_after(agent_id) -> int`: whole seconds until that window ends, at least 1.
- For the minute limits, `Retry-After` is still computed from the Clock in the dependency, as in M2 (`retry_after()` and `_retry_after`), so I added no per-limit method for them.

Memory and pruning:
- `drain()` (the flusher, every minute) prunes the agent and enrol tables of past minutes, and the inventory entries older than 10 minutes. So keys are dropped once their window has passed.
- `size()` counts the three new tables.

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: passes for `bitscan_manager`. It **fails on the test fakes**, because the protocol now has four more methods: `tests/test_runtime.py:110`, `tests/test_login.py:143`, `tests/test_health.py:96` and `:262`, and `tests/test_health_pg.py:39` (`FakeLimits` is not a `RateLimits`). Those are test files, so adding the four methods to the fakes is the tester's change.
- `pytest -q`: 1198 passed, 451 skipped. The 2 failures are the expected `test_alerts.py` ones from TASK-056.
- Scratch probe with a fake clock:

  | Check | Result |
  | --- | --- |
  | requests 1–30 of one agent | allowed |
  | the 31st | refused; `retry_after()` 50 at :10 |
  | another agent | allowed |
  | the 11th enrol from one IP | refused |
  | another IP | allowed |
  | next minute | both allowed again |
  | unscheduled upload, then another 9 min 59 s later | refused, retry-after 1 |
  | another agent, same moment | allowed |
  | 10 min 0 s after the first | allowed |
  | after 11 more minutes and `drain()` | `size()` 6 → 0 |

## Deviations

None.
