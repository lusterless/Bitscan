# TASK-151 IMPL: import store algorithm (SR §3.6)

Implementer: impl-manager-m7c. REQ-158, REQ-159, REQ-177. Risk high (importer; two approvals). Plan: `work/plans/TASK-151.md` (D3). Spec: SR §3.6 steps 1-5, SR §4.1 BIT007 and BIT015; TS §4.1 L522 and L524, §4.3 L548-L550, §5.2 grants. Answers applied: #14, #15 (ordering is the caller's), #21, #100 (a), #104, #106.

## Files

| File | Non-blank lines | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/store.py` (new) | 186 | The plan §2 types, `in_server_folder`, `apply` |
| `manager/bitscan_manager/services/importer/store_decide.py` (new) | 101 | `decide`, `check_ownership`, `is_unchanged` |

It is split as plan §7 foresees (main agreed, 2026-10-27). One file came to 248 code lines, about 100 of them the types. `store_decide` imports the types from `store`, never the reverse. Callers use `store_decide.decide`, `store_decide.check_ownership`, `store_decide.is_unchanged` and `store.apply`. It stays one task id.

No migration, no repository change. It uses the W1 repository API exactly as plan §4 lists it (`catalog`, `catalog_plugins`, `catalog_admin.soft_delete_effects`), plus `quote` and `plugin_path` from `model.py`.

## Interface

Types (frozen, slotted dataclasses), as plan §2, with one change:
- `CandidatePlugin`, `Candidate`, `Target`, `Decision`, `ChangedExecute` and `StoreResult` have the plan's fields.
- `Target.__post_init__` refuses a server target without `source_file` and an upload with one (`ValueError`).
- `Decision.findings` defaults to `()`.
- `PolicyManagedOnServer(policy_id)` is an `Exception` whose message is the fixed code `policy_managed_on_server`; `.policy_id` holds the id.
- **Change (accepted by main, 2026-10-27; planner-m7 told to update plan §2 and the TASK-144 row):** `RuleKeys.plugin_ids` is `tuple[RuleId, ...]`, with `RuleId(plugin_uuid, line, index)`. The plan's `(UUID, line)` carries no plugin index, but plan §3.2 needs the BIT015 element `Policy/PluginsGroups/Plugin[n]/PluginId`. TASK-144 builds `RuleId` with the plugin's 1-based position.
- `in_server_folder(source_file)` is public because `store_decide` uses it: true unless the path starts with `uploaded/` or `deleted/` (plan §3.1).

Functions (each takes the caller's open connection; none commits, locks the catalog, audits or touches files):
- `decide(conn, rules, target, file_exists) -> Decision` locks `byname` first (`policy_by_name_for_update`), then, for a server target, `byfile` (`policy_by_source_file_for_update`, live rows only). It follows the plan §3.1 tables row for row:
  - upload: live in the server folder raises `PolicyManagedOnServer`; live in `uploaded/` is `update`; deleted is `revive`; none is `insert`.
  - server `S`: `byname` at `S` is `update`. A live `byname` at another server file that `file_exists` is `rejected` with BIT007 at `policy_name_line` (element `Policy/PolicyName`). If that file is gone it is `move_server`. Live in `uploaded/` is `move_upload`; deleted is `revive`. With no `byname`, a live `byfile` is `rename`, otherwise `insert`.
  - `displaced_id` = `byfile` (X) for `revive`, `move_upload` and `move_server` when X exists (#106). It can never equal `byname`, because `byname`'s `source_file` is not `S` in those cases.
- `check_ownership(conn, decision, rules) -> tuple[Finding, ...]`: one `owners_of` query covers all ids. Each conflict gives BIT015 at the `<PluginId>` line, in document order, with the message `PluginId <uuid> belongs to policy "<name>".` (the name through `quote`). The deciding policy and the displaced policy never conflict; a deleted owner, or one that no longer lists the plugin, is claimed.
- `is_unchanged(decision, target) -> bool` is the `auto` skip of plan §3.3.
- `apply(conn, decision, cand, target, now) -> StoreResult`, in the order of plan §3.4:
  1. Soft-delete the displaced policy (`soft_delete_effects`; None raises `LookupError`).
  2. Upsert the family.
  3. Insert the policy (`next_policy_id` first, so an upload's `uploaded/policy-<id>.bit` is known) or update it (`update_policy` does the version, override `CASE`, `deleted_at` and `updated_at` rules itself).
  4. Read `current_plugins`, then `upsert_plugins`: added = inserted, updated = returned and not inserted (#21).
  5. `replace_membership`.
  6. `retire_unreferenced`.
  - `changed_executes` = every candidate plugin whose stored `execute_sha256` was absent or different (#100 (a)), in document order.
  - `renamed_from` (rename), `moved_from` (both moves), `revived`, and `reenabled` (old row `disabled`, new row `enabled`).
  - `remove_after_commit` = the old `uploaded/…` path on `move_upload`; `deleted_policy_ids` = the displaced id.
  - A `rejected` decision raises `ValueError`; a row gone under the lock raises `LookupError`. Both are internal errors for the caller (#98 (j)).

Readings of the plan, for the reviewer:
1. A BIT007 rejection sets `Decision.policy_id` to the policy matched by name. The rejected alert (TASK-154 §5) can then target it, and `check_ownership` does not add BIT015 for plugins that this same-named policy owns. The file is rejected by BIT007 in any case.
2. With an invalid `PolicyName` (`rules.policy_name` None), `check_ownership` returns `()`. This applies plan §3.1 "no extra finding": without a name the deciding policy is unknown, so every one of its own plugins would read as a conflict.
3. `reenabled` compares the locked old row with the returned row. A revival of a deleted row stored as `disabled` with no override, by a file saying `enabled`, therefore counts as a re-enable (#101: any change of the effective status from disabled to enabled).

## Static gates (Windows, `manager/.venv`)

- `ruff check` and `ruff format --check` on the new files: pass (S608: no SQL here at all).
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 260 source files.
- Import smoke check: both modules import with no cycle; `Target("upload", "x.bit", …)` raises `ValueError`; `in_server_folder` gives True for `a.bit` and False for `uploaded/…` and `deleted/…`; a `store.ChangedExecute` feeds `alerts.imported` (TASK-153's Protocol) and gets its flags.

## For the tester (tester-m7, TP-M7-11, `manager/tests/test_import_store_pg.py`, PostgreSQL as `bitscan_app`)

- Build `Candidate` and `RuleKeys` directly, with `RuleId(uuid, line, index)`. `Target("server", "x.bit", sha)` or `Target("upload", None, sha)`.
- `file_exists` is a plain callable taking the stored relative path; use a fake.
- Plan §6 rows 1 to 12 apply unchanged. For row 5 (a fault after the third plugin), wrap `catalog_plugins.upsert_plugins` or the connection, because `apply` sends at most 500 plugins per statement: a 3-plugin file is one statement.
- No statement here deletes from `policy`. The only DELETE is `replace_membership`'s `policy_plugin` delete.

## Revision 2 (#100 (a) widened by the user, decisions 2026-10-27)

- `ChangedExecute` gains `reason: ChangeReason`, which is `Literal["new", "changed", "reactivated"]` and is defined in `services/importer/alerts.py` so that the store and the alert share one type. `store.py` now imports from `alerts.py`, with no cycle.
- `apply` reads the prior plugin state with `catalog_plugins.current_plugins` (sha) and `catalog_plugins.retired_among` (TASK-148 r1, impl-manager-m7b). It does this **before step 1** (the #106 displaced soft delete), in the caller's transaction under the catalog lock (main, 2026-10-27).
  - Without that ordering, the plugins Y takes over from X would look "reactivated", because step 1 retires them first.
- `changed_executes`, in document order, holds each candidate plugin whose first applicable reason is one of:
  - `new`: no stored row;
  - `changed`: the stored `execute_sha256` differs;
  - `reactivated`: the decision is `revive`, or the plugin was `retired` before this import.
  - A plugin that was already active and unchanged is left out.
- Plan rows to re-run: the changed-Execute assertions of CHK-M7-173, 174, 176 and 178 (revival: every listed plugin `reactivated`) and CHK-M7-181 (#106 (b) and (c): plugins taken over from X are not `reactivated` unless they were retired before the import). Add one case for a retired plugin listed again (`reactivated`).
- Gates: ruff and ruff format pass. `mypy --strict --config-file manager/pyproject.toml manager` passes (270 files).

## Revision 3 (crash-window ruling and reviewer-m7's note; plan §3.3 r3, decisions 2026-10-27)

- `store_decide.is_unchanged` now also holds for an upload target (`source_file` None): `update`, old row not deleted, and equal hashes. The `source_file` comparison applies only to server targets. TASK-156 matches an `uploaded/policy-<n>.bit` to that live policy's `source_file` before it calls this.
- `Target.__post_init__` also raises `ValueError` for a server target whose `source_file` contains `/`. So `uploaded/…`, `deleted/…` and subfolder paths never reach the server-folder rows of `decide` (`move_server`, BIT007).
- Checks: `Target("server", "uploaded/policy-1.bit" | "deleted/1" | "a/b.bit", …)` raise and `Target("server", "a.bit", …)` is accepted. For an upload target, `is_unchanged` is True with an equal hash and False with a different one.
- Gates: ruff and ruff format pass. Product code passes CI mypy. The one mypy error is in tester-owned `tests/test_import_alerts.py` L462 and comes from TASK-153 r4 (below), not this revision.
