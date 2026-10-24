# TASK-076 IMPL report: fleet read routes

REQ: REQ-081. Spec: TS §6.2 L1108–L1110, §7.3 L1225, §6.3 L1134, L1139, L1141; #68, #69. Depends on TASK-051, 053 and 072, all approved.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/agents/fleet.py` | new, 78 lines |
| `manager/bitscan_manager/api/user/agents.py` | new, 229 lines; TASK-077 adds tags and revoke here |
| `manager/bitscan_manager/api/user/__init__.py` | mounts the router |
| `manager/openapi.json` | re-exported, byte-stable |
| `manager/bitscan_manager/app.py` (approved file, outside the list) | one guard, below |

**The `app.py` guard.** The OpenAPI hook that adds self-read request bodies (TASK-073) used `setdefault` and silently kept the first schema of a name. This task's first draft named its package item `PackageItem`, the same name as the agent contract's inventory item. `InventoryBody` then referred to the wrong schema. The hook now raises `ValueError("OpenAPI component name … is used twice")` at export when a name is already taken by a different schema, and the user model is named `AgentPackageItem`. In the document, the contract `PackageItem` is intact and `AgentPackageItem` is separate.

Size: about 307 lines against an estimate of 190. Most of it is the #68 and #69 response models.

## Routes (all `require_role("viewer")`: viewer and above, session or API token)

**`GET /api/v1/agents`** returns `Page[AgentItem]`.
- Items have the #68 fields: `{agent_id, hostname, status, agent_version, os_id, os_version_id, os_pretty_name, last_heartbeat_at, last_inventory_at, tags, runner_helpers}`.
- Order is `(hostname, agent_id)`, with keyset paging. The cursor holds `[hostname, agent_id]` in the M2 HMAC envelope.
- Every status is listed, and there are no filters in M3.

**`GET /api/v1/agents/{id}`** returns `AgentDetailItem`: the item plus the following.
- `{machine_id, enrolled_at, last_seen_ip, token_issued_at, token_expires_at, token_revoked_at}`.
- `os_info`: the `os_info` row, or null. It holds `{os_id, os_version_id, os_pretty_name, kernel_release, architecture, cpu_count, memory_mb, ip_addresses, uptime_s, raw, collected_at}`, with `raw` returned verbatim.
- `last_snapshot` (#69): `{snapshot_id, collected_at, package_count, added, removed}`, with items `{name, version, architecture, status}`, or null.
- An unknown id gets 404 `not_found`. A non-UUID id also gets 404, as there is no such agent.

**`GET /api/v1/agents/{id}/packages`** returns `Page[AgentPackageItem]`.
- Items are `{name, version, architecture, status, source_name, installed_size_kb, first_seen_at, last_seen_at}`.
- Order is name, architecture, then version in **Debian order** (TASK-053 `package_page`, `version::debversion` then text).
- The cursor scope includes the agent id, so another agent's cursor gets 400. An unknown agent gets 404.

**No response model has `token_hash` or `prev_token_hash`.** No component in the document has a `*token_hash` property. Stored text (hostname, package names, `raw`) is returned as JSON strings, unchanged.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (100 files).
- `pytest -q`: 2182 passed. The 9 failures are the known TASK-074 test-file updates (`test_login` ×2, `test_body_caps` ×7).
- The contract suite still passes (568).
- **Probe**: `create_app()` with M2's `current_principal` overridden by a viewer API-token principal, and fake repositories.

  | Check | Result |
  | --- | --- |
  | 5 agents paged with `limit=2` | each returned once |
  | a `<script>` hostname | returned verbatim |
  | detail | exactly the #68 keys; the planted `token_hash`/`prev_token_hash` values appear nowhere; `raw` verbatim; snapshot present |
  | unknown id, non-UUID id | 404, 404 |
  | 7 packages paged with `limit=3` | each returned once |
  | another agent's package cursor | 400 |
  | no token | 401 |

- Through the API on PostgreSQL (TP-M3-30): **NOT RUN locally**; WSL.

## Deviations

The `app.py` clash guard, above.
