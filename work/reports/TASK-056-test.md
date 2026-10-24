# TASK-056 TEST report: M3 alert kinds, threshold windows, metric definitions

**Verdict: PASS** (2026-10-23, tester). REQ-065, REQ-070, REQ-073, REQ-075, REQ-079 (window shapes) and REQ-086 (definitions, bounded labels). Plan checks: CHK-M3-100 to -105. Code tested: `bm/services/audit/{alerts,thresholds,metrics,__init__}.py` (`work/reports/TASK-056-impl.md`).

## Tests
- `manager/tests/test_thresholds.py`: 19 tests (fake clock, a thread race; the agent statuses are read from the spec DDL).
- `manager/tests/test_alerts.py`: updated. The two M2 tests that TASK-056 supersedes now check the #50 and #71 lists and the REQ-086 registry (45 passed).

## Commands (L)
- `PY -m pytest tests/test_thresholds.py tests/test_alerts.py` → 64 passed. Full L suite: 1816 passed, 0 failed.
- Plants (throwaway copies; control 64 passed): 13 of 14 red. The 14th (the lock removed from `SlidingCount.add`) stays green. Under CPython's GIL a 20-thread race on `add` does not interleave badly enough to show it, so the thread test cannot detect a missing lock without a deterministic interleave. I record this as a limit of the test, not a defect; the lock is in the code. The `agent_id` label plant is red at import (the module's own pre-creation call fails), not in the label test itself.

## Acceptance criteria
- "a window raises once when its count first exceeds the threshold, not again inside the period, again after it": CHK-M3-100 PASS.
- "a re-arm window raises again only after the value went back to or below the threshold": CHK-M3-102 PASS.
- "every #71 kind is accepted by `raise_alert` and exported from zero": CHK-M3-103 PASS.
- "the new metrics have bounded labels only": CHK-M3-104 PASS.
