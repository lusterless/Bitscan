# TASK-057 REVIEW: agent rate limits

Reviewer: reviewer. Date: 2026-10-23. REQ-065, REQ-076. Spec: TS §6.3 L1136 (agent routes 30 req/min per agent; `/agent/enroll` 10 req/min per source IP; valid tokens never throttled by the failed-check limit), §3.4 L239 (one upload without `job_id` per agent per 10 minutes, 429 otherwise); #55 (c) (every attempt counts), #72 (e) (the window starts when an unscheduled upload reaches decoding; the dispatched case is exempt). Inputs:
- `work/reports/TASK-057-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-110 to -114, `manager/tests/test_ratelimit.py` M3 section, `tests/test_runtime.py` fakes; rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/api/ratelimit.py` (about 50 lines added);
- `manager/bitscan_manager/runtime.py` (the `RateLimits` protocol, 9 lines);
- the tester's test changes.

Verdict: APPROVED

Not on the TS §8.2 two-approval list; the M3 owner notes recommend a second look.

## What was checked

- **Spec conformance.**
  - `allow_agent` (30 per agent) and `allow_enrol` (10 per IP, every attempt) use the same fixed UTC-minute windows and `retry_after()` as the M2 limits. Their counters are separate from sign-in, user and failed-check counters, which the tester covers.
  - `allow_unscheduled_inventory` allows when the last allowed upload is at least 10 minutes old, so 9 min 59 s is refused and 10 min 0 s is allowed (REQ-076 (3)).
  - A refused attempt does not move the window. That matches #72 (e): the window starts at the upload that reaches decoding, and a 429 never reaches decoding.
  - `unscheduled_inventory_retry_after` rounds up and is never below 1.
- **Security invariants.** Nothing here throttles a valid token through the failed-check limit; that rule stays in the M2 code path. State is in memory behind one lock (one manager instance, TS §2.1). `drain()` prunes the minute tables and the 10-minute entries, so memory stays bounded: 10,000 agents and IPs drop to 0, as tested. No route, setting or parameter can disable inventory (REQ-088).
- **Scope.** Two files, as the task row lists. `runtime.py` changes once, as the owner notes require.
- **Tests (my run, Windows).** `test_ratelimit.py`, `test_runtime.py`, `test_login.py`, `test_health.py` and `test_auth_dependencies.py`: 104 passed, 27 skipped. ruff and format are clean, and `mypy --strict` is clean on the whole `manager` tree (139 files), so every `RateLimits` fake still satisfies the protocol (CHK-M3-114). The tests pin the 31st and 11th refusals, the exact 9 min 59 s and 10 min boundaries, refusals that do not move the window, thread safety (exactly 30 of 200 concurrent calls allowed) and key pruning. They would turn red for CHK-M3-358, -364 and -365.

## Findings

None.

## Carry-overs (for the consuming tasks)

- **TASK-074.** Ask `allow_unscheduled_inventory` only for the unscheduled cases of #72 (d), with no `job_id` or a `failed` or `completed` job, and only after the `job_id` classification. A `dispatched` job never asks. Ask before decoding, so a refusal decodes nothing.
- **TASK-063 and TASK-067.** `allow_agent` runs after the token check (one count per authenticated call), and `allow_enrol` before anything else on enrol (plan TASK-067).
