# TASK-161 IMPL: profiles service and routes

Implementer: impl-manager-m7c. REQ-168, REQ-169, REQ-174, REQ-178. Risk: low, but under the security rule for RBAC and alert plants, and a user second look per PD-35 (`PATCH` re-enables profiles). Spec: TS §6.2 L1100-L1102 (routes and roles), §4.3 L546-L548 (list, admin status toggle, override), §8.4 L1290 (re-enable alert), §6.3 (pagination, plain text); open questions #9, #98 (a)-(c), (i), (k), #101, #104 (d).

## Files

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/profiles.py` | new: `list_profiles`, `get_profile`, `change_status` | 87 |
| `manager/bitscan_manager/api/user/policies.py` | new: the three routes and their models | 170 |
| `manager/bitscan_manager/api/user/__init__.py` | `policies.router` included | +2 |
| `manager/openapi.json` | re-exported with `python -m bitscan_manager.app manager/openapi.json` | +674, insertions only |

This is 259 hand-written lines, over the ~200 limit; about 50 of them are the #98 (a)/(b) response fields. main kept it as one task (option (a), 2026-10-27): a split would need a second `openapi.json` export and a second route hand-off (PD-24). main rated it high risk, with the user's second look (PD-35).

**Reviewer focus (main):**
1. The list cursor is decoded and validated before the varchar and bigint casts, so a crafted cursor gives 400, never 500 (`_after`).
2. A PATCH re-enable goes through TASK-153's `status_change` alert, `policy_reenabled`, only on disabled → enabled.
3. RBAC: viewer for both GETs, admin (session or API token) for PATCH; `bsa_` and `bse_` are refused by the user router.
4. The audit target is always `policy:<id>`, well under the 255 characters of `audit_log.target`.
5. The `openapi.json` diff is additions only.

## Routes

- `GET /api/v1/policies` (viewer, `require_role("viewer")`):
  - Query: `?status=enabled|disabled` (any other value, `deleted` included, is a validation 400) plus `limit` and `cursor`.
  - It lists non-deleted policies (#9) as `{items, next_cursor}` of `PolicyItem` (#98 (a), field order as listed), ordered by `policy_name`, then `policy_id`.
  - The cursor holds `[policy_name, policy_id]` and is HMAC-checked by `decode_cursor`, then validated before PostgreSQL casts it (reviewer-m7's TASK-150 carry-over, builder checklist 1). The name must be a `str` of 1-128 characters with no U+0000; the id an `int` (not `bool`) of 1 to 2^63−1. Anything else gets 400 `invalid_request` "Invalid request: query.cursor".
- `GET /api/v1/policies/{id}` (viewer): `PolicyDetailItem` is the item plus `deleted_at` and `plugins` in `sort_order`. Each plugin has `{plugin_uuid, sort_order, display_name, plugin_name, control_ref, plugin_description, execute, execute_sha256, operator, expected_result, timeout_s, state, updated_at}`, with `display_name` from `v_plugin` (#98 (b)). A deleted policy is returned with `deleted_at` (#9); an unknown id gets 404 `not_found`.
- `PATCH /api/v1/policies/{id}` (admin, session or API token, `require_role("admin")`; a restricted admin session is refused by that dependency as on other admin routes):
  - The body is exactly `{"policy_status": "enabled"}`, `{"policy_status": "disabled"}` or `{"status_overridden": false}`. `extra="forbid"` and `StrictBool` apply, so `{"status_overridden": 0}`, `true`, `null`, both keys, an empty body, `{"execute": …}` and an unknown status are all 400.
  - It answers 200 with the item, 404 `not_found` for an unknown id and 409 `conflict` "The policy is deleted." for a deleted one (#98 (c), (k)).
  - The sink is woken on commit, as on the other audited routes.
- `{id}` path: `Path(pattern="^[0-9]{1,20}$")`, ASCII digits only, so `+1`, `1.0`, `1_0`, ` 1` and `abc` are 400 (REQ-169 (3)). Pydantic's own `int` would take `+1`, `1.0` and `1_0`. A digit string that no `bigint` can hold (`0`, or over 2^63−1) gets 404, never a 500. The OpenAPI document shows the parameter as a string with that pattern; `policy_id` in bodies stays a JSON integer (#98 (i)).
- No route here edits plugins or commands, queues a job, runs anything or touches files. Viewers see `execute`, which is catalog content (#98 (b)). Nothing here carries stdout or stderr.

## Service (`services/importer/profiles.py`)

- `list_profiles(conn, *, limit, status, after)` and `get_profile(conn, policy_id)` call `catalog_admin.list_page` and `catalog_admin.detail` (TASK-150). `get_profile` raises `PolicyNotFound`.
- `change_status(tx, policy_id, change, *, actor, now)` does the following, with `change` one of `"enabled" | "disabled" | "clear_override"`:
  - It locks the row (`catalog_admin.lock`, `FOR UPDATE`) and decides on that state: unknown raises `PolicyNotFound`; deleted raises `PolicyAlreadyDeleted`.
  - It then calls `set_status` or `clear_override` and re-reads `item`.
  - It writes one `policy.status_change` entry through TASK-153's `status_change(…, by="patch")` and `emit`, in the same transaction. That entry is the `policy_reenabled` alert only when the effective status goes from `disabled` to `enabled` (#101). Every PATCH writes the entry, a no-op included.
  - There is no catalog lock: the row lock serialises against an import, whose UPDATE keeps the override itself (TS §4.3 L548, TASK-151).
- `PolicyNotFound` and `PolicyAlreadyDeleted` are the TASK-152 exceptions (`services/importer/delete.py`), re-exported, so delete and status share one meaning.
- Layering is api → services → repositories. The handler only parses the id, the cursor and the one-change body, and maps exceptions to problems.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager/bitscan_manager` and `ruff format --check manager/bitscan_manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 267 source files.
- G6: two exports are byte-identical. The `openapi.json` diff is insertions only: the three operations, plus `PolicyItem`, `PolicyDetailItem`, `PolicyPluginItem`, `PatchPolicy` and `Page_PolicyItem_`, with no component-name clash. The app adds the 400 entry itself; there is no 422.
- Unit spot-checks of `_after` and `_policy_id`: the cases above (`True` as the id, 2^63, an empty name, U+0000, a 129-character name, the wrong shape, another list's cursor) give 400; `0` and 20 nines give 404.

## For the tester (tester-m7, TP-M7-21, `manager/tests/test_policies_api_pg.py`, PostgreSQL)

- REQ-168 (1)-(5) and REQ-169 (1)-(5) as written. `bsa_` and `bse_` get 401 on all three operations (REQ-174 (2)).
- The route walk (G34) gains exactly these three operations.
- The existing pins on OpenAPI paths and components will see the new entries.
- Depends on 152's `delete.py` (the exceptions) and 153's `alerts.status_change` and `emit`; both are in your queue.
- Builder checklist: (1) the cursor and id plants above; (4) PATCH takes its body like `users` and `settings` PATCH (role dependency, declared body), so a bad body with a bad token is 400, as on those routes; (12) every problem `detail` is fixed text; (13) the export is stable.
