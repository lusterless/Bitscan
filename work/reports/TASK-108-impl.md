# TASK-108 IMPL: status and kind enums in the user-route contract

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-117; PD-29 (a) as approved. TS §5.2 L710 (`agent_status`), L763 (`kind` CHECK), L774 (`decision` CHECK).

## Files

- `manager/bitscan_manager/api/user/agents.py`: adds `AgentStatus = Literal[<the six agent_status values>]`, and `AgentItem.status` is now `AgentStatus`. `AgentDetailItem` inherits it.
- `manager/bitscan_manager/api/user/enrolment.py`:
  - `MatchItem.status` is now `AgentStatus` (imported from `agents.py`).
  - `RequestItem.kind` is `Literal["new", "reenrol"]`.
  - `RequestItem.decision` is `Literal["approved", "rejected"] | None`.
- `manager/openapi.json`: **re-exported** (`python -m bitscan_manager.app manager/openapi.json`).

No behaviour change: the values come from the database enum and CHECK constraints, and pydantic now also validates them on output. `LoginResponse.role` and `UserItem.role` are unchanged, per PD-29 (a). No other file changed.

## Document diff

32 added lines, all `enum` arrays:
- the six `agent_status` values on `AgentItem.status`, `AgentDetailItem.status` and `MatchItem.status`;
- `new` and `reenrol` on `RequestItem.kind`;
- `approved` and `rejected` inside `RequestItem.decision`'s `anyOf` string branch.

No description, component name or other property changed. Two exports were byte-identical (`cmp`), and the file has LF line ends.

## AC mapping

| AC | Status |
| --- | --- |
| (1) the document gives each property exactly those values | done (diff above) |
| (2) the M3 agents and enrolment-request suites pass unchanged | for the tester (TP-M5-01) |
| (3) G6 byte-identical after re-export | two exports compared equal |

## Checks run (from `Bitscan-m5/manager`, M3 venv)

`ruff check`, `ruff format --check` and `mypy --strict` on `bitscan_manager` all pass (107 files). The pydantic mypy plugin leaves `__init__` untyped, so the repository's `str` values need no cast. No tests run.

## For the tester and impl-web

- `web/src/api/schema.d.ts` is now behind `openapi.json` until TASK-122 regenerates it (impl-web), so G16 shows that diff until then.
- The tester's own M3 contract fixtures or snapshot tests that compare `openapi.json` may need their expected copy refreshed.
