# TASK-150 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-165, REQ-167, REQ-168, REQ-169; TS §4.3 L546 to L551, §5.2 (DDL, `v_plugin`, grants L1005 to L1013); #9, #98 (a), (b), #103, #104 (a), (b), (d); D3. Files under test: `bm/repositories/catalog_admin.py` and `bm/repositories/catalog_integrity.py` (the lead's split). Checks CHK-M7-165 to -170, plants CHK-M7-337, -365, -381 to -384 and extras. Test file: `manager/tests/test_catalog_admin_repo_pg.py` (24 tests), as `bitscan_app` on a database of its own. Catalog rows are written with plain SQL as `bitscan_app` (independent of TASK-148); scans, jobs, schedules and the agent are written as owner (`manager/tests/catalog_rows.py`).

## Runs

| Run | Command | Count |
| --- | --- | --- |
| clean (W, label m7t-t150, `CI=true`, `-n 0`) | `pytest tests/test_catalog_admin_repo_pg.py` | 24/24 passed, 0 failed, 0 skipped, leftover-own 0 |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

## Checks

| Check | Result |
| --- | --- |
| CHK-M7-165 the list holds 5 of {3 enabled, 2 disabled (one of them by override), 1 deleted}; `enabled` gives 3, `disabled` 2 (effective status); N + 1 with limit N (N = 1, 2, 3, 5), inserted out of order: each once, in (`policy_name`, `policy_id`) order; the item has exactly the #98 (a) fields in order, values exact (`family_name`, `plugin_count` = its own `policy_plugin` rows) and equal to the list row; `item()` returns deleted rows (PATCH answer) and None for unknown | PASS |
| CHK-M7-166 detail: plugins in file order (`sort_order` 1..3, not insertion or uuid order), `display_name` = `<family> - <plugin>` from `v_plugin`, every #98 (b) field in order; hostile text (`<img onerror>`, quotes, backslash, C0, DEL, U+2028, RTL, emoji) byte-identical through the JSON aggregation; `updated_at` exact to the microsecond with any session time zone (Asia/Kathmandu); a deleted policy shows `deleted_at` and keeps its plugins (#104 (a)); unknown is None; no plugins gives `[]` | PASS |
| CHK-M7-167 `set_status` enabled/disabled sets the override; a no-op keeps `updated_at` while a first override moves it; `clear_override` restores `file_status` (both ways) and a no-op keeps `updated_at`; deleted and unknown are refused with nothing changed; `lock()` returns the state under `FOR UPDATE` (a second NOWAIT fails); **D3 race**: a file UPDATE (TASK-148 `update_policy`) waiting on an uncommitted PATCH disable keeps `disabled` + override after the PATCH commits | PASS |
| CHK-M7-168 soft delete with owner-written rows: only the policy's `queued` compliance jobs (the original and a queued retry) → `cancelled` with `finished_at`; `dispatched`, `running`, `completed`, the other policy's queued job and an inventory job unchanged; both enabled schedules disabled (an already disabled one and the other policy's untouched); `deleted_at`, `source_file` `deleted/<id>` and `updated_at` set, statuses and version kept; retired = owned and listed, owned and unlisted, and listed-only-by-it (owner elsewhere); a plugin also listed by a live policy stays active; `policy_plugin` rows kept; the row is still there; the returned ids are exact; a second delete and an unknown id return None and change nothing (checksums); a caller rollback undoes everything (checksums); `bitscan_app` cannot DELETE a policy | PASS |
| CHK-M7-169 `integrity_rows`: non-deleted only; counts 2/0, 3/2 (retired + owned by another), 0/0 for an empty policy; ordered by id; `rejected_files`: only pairs with a `rejected` row (a later `success` for the same pair still counts as rejected history; a success-only pair, another hash for the same name, and a missing file do not); empty input | PASS |
| CHK-M7-170 / -337 ruff S608 clean; a planted f-string is red in `catalog_admin.py` (L160) and in `catalog_integrity.py` (L50) | PASS |

## Plants (W, throwaway copies)

| Plant | Red |
| --- | --- |
| CHK-M7-381 (a) dispatched jobs cancelled too; (b) other policies' jobs cancelled | 1 failed each |
| CHK-M7-382 (a) schedules not disabled; (b) plugins not retired | 1 failed each |
| CHK-M7-383 list includes deleted | 1 failed |
| CHK-M7-384 clear override leaves `policy_status` | 2 failed |
| CHK-M7-365 hard `DELETE FROM policy` (the grant refuses it; the tests see it) | 2 failed (`InsufficientPrivilege`) |
| `set_status` does not set the override | 4 failed (incl. the D3 race) |
| integrity `bad_plugins` ignores the owner | 1 failed |
| `rejected_files` ignores the outcome | 1 failed |

Observation (not a finding): `rejected_files` answers "has a rejected row for this (name, hash)". #103 says "has a `rejected` `bit_import` row for its current hash", so a file rejected once and later imported as a policy's `source_file` is also covered by the first #103 branch. TASK-158 composes the two.

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-165..169 | APP | W | `pytest -q -n 0 tests/test_catalog_admin_repo_pg.py` (m7t-t150) | PASS | 24/24 passed, 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-170 | CODE | L | `ruff check` on both files | PASS | clean | 2026-10-27 |
| CHK-M7-337 | CODE | L | plant f-string in `catalog_admin.py` and `catalog_integrity.py` | PASS (red) | S608 at catalog_admin.py:160 and catalog_integrity.py:50 | 2026-10-27 |
| CHK-M7-381 | APP | W | plants: (a) dispatched cancelled, (b) other policies' jobs | PASS (red) | 1 failed each | 2026-10-27 |
| CHK-M7-382 | APP | W | plants: (a) schedules kept enabled, (b) no retire | PASS (red) | 1 failed each | 2026-10-27 |
| CHK-M7-383 | APP | W | plant: list includes deleted | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-384 | APP | W | plant: clear override keeps policy_status | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-365 (150 half) | APP | W | plant: hard DELETE FROM policy | PASS (red) | 2 failed, InsufficientPrivilege | 2026-10-27 |
| CHK-M7-150-ovr | APP | W | plant: set_status without override | PASS (red) | 4 failed incl. the D3 race | 2026-10-27 |
| CHK-M7-150-int | APP | W | plants: bad_plugins without owner check; rejected_files without outcome | PASS (red) | 1 failed each | 2026-10-27 |
