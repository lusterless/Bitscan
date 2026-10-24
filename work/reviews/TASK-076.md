# TASK-076 REVIEW: fleet read routes

Reviewer: reviewer. Date: 2026-10-23. REQ-081. Spec: TS §6.2 L1108–L1110 (`GET /agents`, `/agents/{id}` with `os_info`, `/agents/{id}/packages`, viewer), §7.3 L1225 (the host page shows added and removed since the last snapshot), §6.3 L1134 (cursor pagination, max 500), L1139 (UUID ids), L1141 (stored text is untrusted and rendered as plain text); #68 (item fields, order), #69 (`last_snapshot`). Inputs:
- `work/reports/TASK-076-impl.md`;
- `work/reports/TASK-076-test.md` (PASS: `manager/tests/test_agents_api_pg.py`; 7 of 7 plants red).

Files reviewed:
- `manager/bitscan_manager/services/agents/fleet.py` (new, 78 lines);
- `manager/bitscan_manager/api/user/agents.py` (the three GET routes);
- `manager/bitscan_manager/api/user/__init__.py` (mount);
- the `app.py` component-clash guard;
- `manager/openapi.json`;
- the tester-e tests.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Routes (REQ-081).**
  - All three use `require_role("viewer")`: viewer and above, session or API token. No token gets 401.
  - **`GET /agents`:** the #68 items, ordered by `(hostname, agent_id)`, with keyset paging. The cursor holds both keys in the M2 HMAC envelope, so each agent is returned once across pages (REQ-081 (3)). Every status is listed.
  - **`GET /agents/{id}`:** the item plus `machine_id`, `enrolled_at`, `last_seen_ip`, the token times, `os_info` (with `raw` verbatim) or null, and `last_snapshot` (#69: `{snapshot_id, collected_at, package_count, added, removed}`) or null.
  - **`GET /agents/{id}/packages`:** #68 items in name, architecture, Debian-version order (TASK-053 r1). The cursor scope includes the agent id, so another agent's cursor gets 400.
  - An unknown or non-UUID id gets 404 `not_found`.
- **Security invariants.**
  - No response model has `token_hash` or `prev_token_hash`, and no component in the document mentions `token_hash` (REQ-081 (5)).
  - Stored text such as a `<script>` hostname, package names and `raw` is returned as JSON strings, unchanged (REQ-081 (4); the UI renders plain text, TS §6.3).
  - The routes are read-only.
- **`app.py` guard (approved file).** The OpenAPI hook now raises when two models claim one component name, rather than silently keeping the first. That is the defect this task's first draft hit with `PackageItem`. The user model is `AgentPackageItem`, and the contract `PackageItem` is intact. This guards REQ-060 for every later task, which is worth having.
- **OpenAPI (G6).** My re-export is byte-identical. Every path except `/healthz` and `/readyz` is under `/api/v1/` (REQ-089, `HealthPath` unchanged).
- **Scope.** Size is about 307 lines against an estimate of 190, mostly response models. Accepted.
- **Tests (my run, Windows).** See the TASK-077 review: 80 passed, 128 skipped (PostgreSQL; WSL by tester-e); ruff, format and `mypy --strict` (209 files) are clean.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/api/user/agents.py:196-200` (`get_agent`). The detail's `os_id`, `os_version_id` and `os_pretty_name` come from `os_info`, as `GET /agents` does through the join. That is consistent, but it duplicates the nested `os_info` fields. It is harmless; noted for the M5 UI only.
