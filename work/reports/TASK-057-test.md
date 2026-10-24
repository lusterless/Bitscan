# TASK-057 TEST report: agent rate limits

**Verdict: PASS** (2026-10-23, tester). REQ-065 (1), (2) and REQ-076 (3) at the limiter level. Plan checks: CHK-M3-110 to -114. Code tested: `bm/api/ratelimit.py`, `bm/runtime.py` (`work/reports/TASK-057-impl.md`).

## Tests changed
- `manager/tests/test_ratelimit.py`: 11 new tests (37 in the file), using a fake clock and a thread race.
- `manager/tests/test_runtime.py`: the shared `FakeLimits` gained the four protocol methods (permissive). The protocol change had made mypy fail at five call sites.

## Commands (L)
- `PY -m pytest tests/test_ratelimit.py` → 37 passed. ruff, format and `mypy --strict` clean on the whole tree.
- Full suite: 1319 passed, 498 skipped (no PostgreSQL part in this task); 2 expected TASK-056 failures in `test_alerts.py`.
- Plants (throwaway copies; control 37 passed): 11 of 12 red:
  - CHK-M3-364;
  - limit 31;
  - CHK-M3-365;
  - enrolment on the sign-in counter;
  - CHK-M3-358;
  - window 9 min;
  - boundary `<=`;
  - refusals restart the window;
  - inventory windows never pruned;
  - agent minutes never pruned;
  - retry-after floored.

  The 12th, "agent counter stored in the user dict", stays green. It is an equivalent mutant: agent keys are UUIDs and user keys are ints, so they cannot collide and behaviour does not change.

## Acceptance criteria
- "the 31st request of one agent, the 11th enrol from one IP and a second unscheduled upload within 10 minutes are refused while other keys pass": CHK-M3-110, -111, -112 PASS.
- "the retry-after value is the seconds to that window's end": CHK-M3-110, -111 (minute windows), CHK-M3-112 (10-minute window) PASS.
- "keys are dropped after their window": CHK-M3-113 PASS.
- The route-level 429 with `Retry-After` is tested in TASK-063, TASK-067 and TASK-074 (CHK-M3-163, -207, -257).

## Note
- The unscheduled window is measured from the last allowed attempt; refused (429) attempts do not move it. That matches #72 (e) as long as the caller asks only when an upload reaches decoding. TASK-074 TEST checks that through the route (CHK-M3-257).
