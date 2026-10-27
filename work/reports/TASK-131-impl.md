# TASK-131 IMPL: host-list cursors carry only ids (#89)

REQ-143; plan `work/plans/TASK-131.md`; TS §6.3 L1134, §6.2 L1108/L1110, §5.2. impl-manager, 2026-10-26.

## What changed (4 files, +102 / -43)

- `manager/bitscan_manager/repositories/agents.py`: the signature is now `list_page(limit, after_id: UUID | None)`. When `after_id` is set, the method first runs `SELECT hostname, agent_id FROM agent WHERE agent_id = %s` in the caller's transaction and raises `AnchorGone` (from `repositories.packages`) if no row comes back. The M3 page query is unchanged: `(hostname, agent_id) >` anchor, same order.
- `manager/bitscan_manager/repositories/inventory.py`: the signature is now `package_page(agent_id, limit, after_package_id: int | None)`. The anchor comes from `package` (not `agent_package`): `SELECT name, architecture, version FROM package WHERE package_id = %s`. If no row comes back, it raises `AnchorGone`. The M3 page query is unchanged, including `version::debversion` then `version`. `agent_packages()` (`package_page(id, None, None)`) still works.
- `manager/bitscan_manager/services/agents/fleet.py`: the `FleetAgents.list_page` and `FleetInventory.package_page` Protocols, `list_agents(..., after_id)` and `agent_packages(..., after_package_id)` are renamed and retyped to match. `AnchorGone` passes through.
- `manager/bitscan_manager/api/user/agents.py`:
  - `_cursor()` is replaced by two functions. `_agent_cursor()` accepts only `[s]` where `s` is a string and `str(UUID(s)) == s`, which is the exact lowercase hyphenated form the route writes. `_package_cursor(scope, …)` accepts only `[n]` where `type(n) is int` (so a JSON boolean fails) and `0 <= n <= 2^63 - 1`. Anything else gets 400 `invalid_request` "Invalid request: query.cursor". Before this change, a cursor with a bad agent id answered 404. Now it answers 400.
  - Each route wraps its transaction in `except AnchorGone` and answers 400 with the same fixed detail, as `/packages/search` does.
  - The cursor is built from the last row (`[str(agent_id)]` or `[package_id]`) through `page_of` over the rows, and the items are converted afterwards. No field is added to `AgentItem` or `AgentPackageItem`.
  - The scopes stay `"agents"` and `"agent_packages:{agent_id}"`.

SQL is fixed text with `%s` placeholders only. No migration, no index, no new grant: `bitscan_app` already has SELECT on `agent` and `package`.

## Checks run (Windows, M3 venv against this tree)

- `ruff check manager`: clean. `ruff format --check manager`: clean.
- `mypy --strict --config-file manager/pyproject.toml manager`: 4 errors, all in tester-owned tests that call the old tuple signatures:
  - `manager/tests/test_inventory_repo_pg.py:384, 421, 453` (`package_page(a, n, after)` with a `(name, arch, version)` tuple)
  - `manager/tests/test_agent_repo_pg.py:487` (`list_page(2, after)` with a `(hostname, agent_id)` tuple)
  - Source code has no errors.
- `python -m bitscan_manager.app <tmp>` run twice: both exports are byte-identical to `manager/openapi.json` (G6). The OpenAPI file did not change.

## For the tester (TP-M6-07, G53)

- These tests must move to the id form (old form → new form):
  - `test_agent_repo_pg.py::test_list_page_items_and_keyset_paging`: pass the last row's `agent_id`.
  - `test_inventory_repo_pg.py::test_package_page_order_and_keyset`, `::test_package_page_uses_debian_version_order` and `::test_package_page_debian_order_within_name_and_architecture`: pass the last row's `package_id`.
  - `test_fleet_services_unit.py` L209/L230: the fakes' parameter is named `after`. That's positional and type-checks, so a rename is optional.
  - Any M3 route test that decodes cursor content must now expect `[agent_id]` or `[package_id]`.
- The anchor-gone path for `/agents` can't happen in practice, because `bitscan_app` has no DELETE on `agent` and cursors are HMAC-signed. It is still handled (400). For packages, delete the `package` row as `bitscan_retention` (plan: M11 prune) to get 400.
- Plants: CHK-M6-333 (hostname back in the cursor), CHK-M6-334 (an f-string anchor query triggers S608), CHK-M6-335 (remove one `except AnchorGone` and the route answers 500), CHK-M6-336 (the scope check stays in `decode_cursor`).
- Files changed outside the task list: none.
