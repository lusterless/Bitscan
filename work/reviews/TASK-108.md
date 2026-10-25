# TASK-108 REVIEW: status and kind enums in the user-route contract

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (UI contract). Not a two-approval task: PD-29 (a) leaves the M2 role fields unchanged.

Scope reviewed:
- `manager/bitscan_manager/api/user/agents.py` and `manager/bitscan_manager/api/user/enrolment.py`;
- the matching `enum` lines in `manager/openapi.json` (`work/reports/TASK-108-impl.md`).

Sources: TS §5.2 L709 (`agent_status`), L763 (`kind` CHECK), L774 (`decision` CHECK), REQ-117 and PD-29 (a).

TEST: PASS (`work/reports/TASK-108-test.md`, CHK-M5-001..005 and -359). The M3 agents and enrolment-request suites pass unchanged, and the plant that sets `status` back to `str` is red.

## Checks
1. Spec:
   - `AgentStatus` lists exactly the six enum values in DDL order.
   - `kind` is `new` or `reenrol`.
   - `decision` is `approved`, `rejected` or null.
   - `AgentDetailItem` inherits from `AgentItem`, and `MatchItem` reuses the same alias.
   - The roles stay strings, as PD-29 (a) says.
2. Contract: `openapi.json` has the `agent_status` enum on 4 schemas and `kind` and `decision` as enums. No component was renamed.
3. Re-run by the reviewer:
   - `ruff check` and `ruff format --check` on `manager` pass.
   - `mypy --strict` passes on 110 files.
   - A fresh export of the OpenAPI document is byte-identical to `manager/openapi.json` (G6).
4. Scope: 2 source files and the re-export, about 15 lines. There is no import cycle: `agents.py` does not import `enrolment.py`.

## Findings
None. G16 (`schema.d.ts`) stays behind until TASK-122, as the impl report says.
