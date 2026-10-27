# TASK-151 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-158, REQ-159, REQ-177; SR §3.1 to §3.6, §4.1 BIT007 and BIT015; TS §4.1 L519 to L524, §4.3 L548 to L550; #14, #15, #21, #100 (a), #104, #106; design note D3; plan `work/plans/TASK-151.md` §6 rows 1 to 12. Files under test: `bm/services/importer/store.py` and `store_decide.py`. Test file: `manager/tests/test_import_store_pg.py` (32 tests), as `bitscan_app` on a database of its own; `Candidate` and `RuleKeys` built by the test.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t151, `CI=true`, `-n 0`) | `pytest tests/test_import_store_pg.py` (with the TASK-153 r2 files) | store file 31/32 passed, 1 failed: `test_106_y_in_another_existing_server_file_is_bit007` (my test bug, below) |
| r1 (m7t-t151b) | that node id after the fix | 1/1 passed |
| r2 (m7t-t151c) | `test_fault_after_the_third_plugin_leaves_the_catalog_unchanged` after a second test fix (below) | 2/2 passed |
| static (L) | ruff, ruff format, mypy (CI form) | clean, 269 files |

Test bugs (mine, both fixed; lead confirmed the first, 2026-10-27):
1. #106 (a). The file `a.bit` held X and now names Y, while Y lives in an existing `b.bit`. I expected only BIT007, but the store also reports BIT015 for X's plugin. That is right: X is live, still lists the plugin, and is not displaced because nothing moves, and every failing rule is reported (SR L250).
2. The fault wrapper raised on its first call, so the commit-per-plugin plant (CHK-M7-338) stayed green. The fault now fires after 3 plugin rows counted across calls, and the catalog is read from another connection; 338 is red.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-173 | APP | W | r0 | PASS | SR §1.1 candidate as `x.bit`: every policy, family, plugin and `policy_plugin` column exact (execute `dpkg-query -W -f='${Status}' apparmor 2>/dev/null`, its sha, timeout 30, control_ref `1.3.1.1`, active, sort 1, source_sha256 of the fixture bytes); `v_plugin.display_name` `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`; result v1, 1/0/0, one changed Execute | 2026-10-27 |
| CHK-M7-174 | APP | W | r0 | PASS | identical re-import: `update`, `is_unchanged`, v1, 0/0/0, no changed Execute, same ids; new hash → v2, then v3; `is_unchanged` false for a rename | 2026-10-27 |
| CHK-M7-175 | APP | W | r0 | PASS | override true: file enabled leaves disabled; override false: both change; `reenabled` true only without the override; a file disable is not a re-enable; **race**: an import waiting on an uncommitted PATCH (seen blocked) keeps the PATCH's disabled + override and gets v2 | 2026-10-27 |
| CHK-M7-176 | APP | W | r0 | PASS | reorder 0/0/0 with new sort order; drop 0/0/1 (row kept, retired); one Execute changed 0/1/0 with exactly that changed Execute; mixed file 2/1/1 (#21); family change: a new family row, old kept, plugin follows (updated 1) | 2026-10-27 |
| CHK-M7-177 | APP | W | r2 | PASS | fault after the 3rd plugin, for a new and an existing policy: catalog checksums from another connection unchanged after the caller's rollback | 2026-10-27 |
| CHK-M7-178 | APP | W | r0 | PASS | revival with identical bytes: `revive`, same id, v2, `deleted_at` NULL, override and disabled kept, plugins active (updated 2), schedules still disabled (#14); an upload revival of a server policy goes to `uploaded/policy-<id>.bit` | 2026-10-27 |
| CHK-M7-179 | APP | W | r0 | PASS | upload: insert (`uploaded/policy-<id>.bit`), update, `PolicyManagedOnServer` (id, fixed message, nothing changed); BIT007 when the other server file exists (line 3, `Policy/PolicyName`, names the file; `file_exists` asked about that file only; nothing changed; `apply` on a rejected decision refused); `move_server` when it is gone (same id, new file, `moved_from`, v1 for equal bytes); server file wins over an upload (`move_upload`, `remove_after_commit` the upload, then a later upload gets `PolicyManagedOnServer`); `Target` refuses mismatched kind and path; an invalid `PolicyName` gives `rejected` with no extra finding | 2026-10-27 |
| CHK-M7-181 | APP | W | r0, r1 | PASS | #106: (a) BIT007 + BIT015 naming X, nothing changed; (b) Y uploaded → `move_upload`, X soft-deleted (`deleted/<id>`), the upload to remove; (c) Y deleted → revived at the file, X deleted; (d) Y absent → rename in place, same id, `renamed_from`, membership kept, the committed `scan` row still points at it | 2026-10-27 |
| CHK-M7-182 | APP | W | r0 | PASS | BIT015 for a live listing owner (line, `Plugin[3]/PluginId`, names owner and uuid; nothing changed); no BIT015 when the owner is deleted or dropped it, and the claim moves `owner_policy_id` (the deleted owner's membership row kept, #104 (c)); none for self or the displaced X; findings in document order | 2026-10-27 |
| CHK-M7-183/184 | APP | W | r0 | PASS | no `policy` row ever deleted (count +2 after inserts, a move and a displacement); `imported_at` moves on every import, `updated_at` only on a change (#104 (d)); revival with identical Executes carries no changed Execute (pinned; question with the user via main) | 2026-10-27 |
| CHK-M7-335 | APP | W | plant: `check_ownership` returns `()` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-338 | APP | W | plant: COMMIT after each plugin | PASS (red) | 2 failed (after test fix 2; green before it) | 2026-10-27 |
| CHK-M7-369 (store half) | APP | W | plants: (s) override reset after the update; (v) version + 1 on an identical-hash update | PASS (red) | (s) 3 failed incl. the PATCH race; (v) 2 failed | 2026-10-27 |
| CHK-M7-151-a | APP | W | plant: `file_exists` ignored (always move) | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-151-b | APP | W | plant: no `PolicyManagedOnServer` | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-151-c | APP | W | plant: `displaced_id` never set | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-151-d | APP | W | plant: `is_unchanged` ignores the hash | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-e | APP | W | plant: displaced policy counted for BIT015 | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-151-f | APP | W | plant: every plugin listed as a changed Execute | PASS (red) | 4 failed | 2026-10-27 |
| CHK-M7-151-g | APP | W | plant: upload copy not reported for removal | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-151-h | APP | W | plant: no rename in place | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-i | APP | W | plant: BIT015 ignores "still lists it" | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-j | APP | W | plant: upload of a deleted name not revived | PASS (red) | 2 failed | 2026-10-27 |
| static | CODE | L | ruff (no SQL in either file), format, mypy | PASS | clean | 2026-10-27 |

## Revision 2 (#100 (a) widened by the user, 2026-10-27: `ChangedExecute.reason` ∈ new, changed, reactivated)

Updated rows: the changed-Execute assertions of CHK-M7-173 (`new`), -176 (`changed`, and the mixed file's two `new`), and -178 (the revival: both plugins `reactivated`). `test_revival_changed_executes_pinned` is flipped to `test_revival_changed_executes_reactivated` (a revived `cat /etc/shadow` plugin is carried as `reactivated`). New rows: `test_a_retired_plugin_listed_again_is_reactivated` (an active, unchanged plugin stays out) and `test_106_takeover_from_the_displaced_policy_is_not_reactivated`. In (b), Y takes over X's active plugins and none is carried, because the prior state is read before the displaced delete. In (c), the revive of Y carries the listed plugin as `reactivated`.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-173..184-r2 | APP | W | `pytest -n 2 tests/test_import_store_pg.py` (with the TASK-153 r3 files, m7t-t151r2) | PASS | 34/34 passed (the run: 166/166) | 2026-10-27 |
| CHK-M7-151-rv | APP | W | plant: a revive no longer marks plugins reactivated | PASS (red) | 1 failed (#106 (c)) | 2026-10-27 |
| CHK-M7-151-rl | APP | W | plant: a re-listed retired plugin not reactivated | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-or | APP | W | plant: prior state read after the displaced delete | PASS (red) | 1 failed (#106 (b): X's plugins appear reactivated) | 2026-10-27 |

Verdict after revision 2: **PASS**.

## Revision 3 (crash-window ruling, user and lead 2026-10-27; plan §3.3 r3)

New rows:
- `test_a_server_target_refuses_a_path_with_a_slash`: `uploaded/policy-1.bit`, `deleted/1`, `a/b.bit`, `/abs.bit` and `sub/x.bit` each raise `ValueError`.
- `test_a_plain_server_file_name_is_accepted`.
- `test_is_unchanged_for_an_upload_target`: True for an `update` with an equal hash, False with a different hash, and False once the policy is deleted (the decision becomes `revive`).
- `test_is_unchanged_still_compares_the_server_file`: a server file at a new path with an equal hash is a `move_server`, not unchanged.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-174-r3 | APP | W | `pytest -n 2 tests/test_import_store_pg.py tests/test_import_alerts.py tests/test_import_alerts_pg.py` (m7t-t151r3) | PASS | 42/42 store (the run 103/103), 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-151-sl | APP | W | plant: server target accepts a `/` path | PASS (red) | 5 failed (all except the first case, which an earlier check catches) | 2026-10-27 |
| CHK-M7-151-up | APP | W | plant: upload target compared by `source_file` (r2 behaviour) | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-uh | APP | W | plant: `is_unchanged` ignores the hash | PASS (red) | 2 failed | 2026-10-27 |

Verdict after revision 3: **PASS**.
