# TASK-061 REVIEW: inventory queueing

Reviewer: reviewer. Date: 2026-10-23. REQ-077, REQ-088. Spec: TS §3.4 L230 (one inventory job per eligible agent with no open inventory job), L237 (the interval can be changed, never turned off), §4.4 L566 (`pickup_by` = creation + 24 h), §6.2 L1129 (no way to disable inventory); #36 (first job when an agent becomes `enrolled`), #67 (cadence). Plan: `work/plans/TASK-061.md` ("Inventory run"). Inputs:
- `work/reports/TASK-061-impl.md`;
- `work/reports/TASK-061-test.md` (PASS: CHK-M3-140 to -146; 19 PostgreSQL tests in WSL plus 5 unit tests; 6 of 6 plants red).

Files reviewed:
- `manager/bitscan_manager/services/scheduler/inventory.py` (new, 37 lines);
- `manager/bitscan_manager/services/scheduler/__init__.py` (re-exports);
- the tester's `test_inventory_queue_pg.py` and `test_inventory_queue.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance.**
  - `run_inventory` passes `now` and `now + 24 h` to the approved TASK-054 statement. That statement holds the eligibility rule (not `decommissioned` or `awaiting_approval`, no inventory job `queued`, `dispatched` or `running`), the four-key payload and the advisory lock. One run therefore gives one job per eligible agent, and two runs at once, or a run and a #36 first-job call, still give one open job per agent.
  - `queue_first_inventory` limits the same statement to one agent.
  - The `InventoryQueue` `Protocol` keeps the service unit-testable without PostgreSQL, as the M3 design rules require.
  - The cadence (#67, REQ-077 (4)) is TASK-071's, as planned.
- **Security invariants (REQ-088).** No setting, parameter or flag can skip or stop a run; the tester's "skip switch" plant is red. The module opens no connection: the static no-client check is in the unit tests, and the `httpx` plant is red.
- **Scope.** Two files, about 40 lines, as the task row lists.
- **Tests (my run, Windows).** 5 unit tests pass, and the 18 PostgreSQL tests skip locally (run in WSL by the tester). ruff, format and `mypy --strict` are clean. The PostgreSQL tests cover every agent status, open and closed job states, two concurrent runs, a run concurrent with a first-job call, and first-job refusals for held and decommissioned agents. They turn red for the G33 plant (offline agents skipped) and for a 23 h window.

## Findings

None.
