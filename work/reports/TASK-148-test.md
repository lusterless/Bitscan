# TASK-148 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-158, REQ-159; SR §3.1 to §3.4, §3.6 steps 1 to 5; TS §5.2 (catalog DDL and grants); #14, #21, #100 (a), #104 (b), (d), (e); D3. Files under test: `bm/repositories/catalog.py` and `bm/repositories/catalog_plugins.py` (the lead's split). Checks CHK-M7-150 to -157, plants CHK-M7-336, -375 to -377 and the D3 / version plants. Test file: `manager/tests/test_catalog_repo_pg.py` (50 tests), as `bitscan_app` on a database of its own (`own_migrated_server`), each test in a rolled-back transaction unless it needs a second connection.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| clean (W, label m7t-t148, `CI=true`, `-n 0`) | `pytest tests/test_catalog_repo_pg.py` | 50/50 passed, 0 failed, 0 skipped, leftover-own 0 |
| static (L) | ruff, ruff format, mypy (CI form) | clean, 248 files |

## Checks

| Check | Result |
| --- | --- |
| CHK-M7-150 grants: UPDATE and no DELETE on family, policy, plugin; DELETE and no UPDATE on policy_plugin; nothing on bit_import. Family upsert: same name gives the same id and keeps `created_at`; exact match (case and trailing space differ); two concurrent upserts agree on one row (the second waits for the first) | PASS |
| CHK-M7-151 `insert_policy` (v1, `policy_status` = `file_status`, no override, timestamps = now); `next_policy_id` then insert as an upload path; lookups by name, source file and id, deleted rows included, exact match; each lookup holds `FOR UPDATE` (a second connection's NOWAIT fails, then succeeds after); `update_policy`: identical values keep `version` and `updated_at` while `imported_at` moves; a changed hash adds exactly 1 each time; the override table (4 cases: an override never re-enabled by the file); revival adds 1 for identical bytes and keeps the override (#14); rename in place keeps the id; every stored column moves `updated_at`; unknown id gives None; UNIQUE name and source_file enforced | PASS |
| CHK-M7-152 `owners_of`: owner lists it / owner dropped it / owner deleted / new id absent; "owner lists" means the owner itself (another policy listing it does not count); empty input | PASS |
| CHK-M7-153 #21: first upsert all added; identical upsert returns nothing and keeps `updated_at`; each of 8 changed columns (name, control_ref to NULL and to another value, description, execute + sha, timeout, operator, expected) gives exactly one "updated"; owner change, family change and `retired → active` each count as updated; mixed file 2 added / 2 updated with the unchanged one absent; 1,001 plugins (3 batches) as one batch; `current_plugins` | PASS |
| CHK-M7-154 membership: 1-based order, reorder, remove, add, empty; other policies untouched | PASS |
| CHK-M7-155 retire: exactly {listed only by a deleted policy, listed by nobody}; one listed by both a live and a deleted policy stays active; an already retired row is untouched; nothing deleted; a deleted policy's `policy_plugin` rows kept (#104 (a)); a second call returns [] | PASS |
| CHK-M7-156 hostile text (SQL quotes, `%s`/`%(now)s`, `<script>`, RTL/zero-width/BOM, emoji, C0 and DEL) round-trips byte-identical through policy, family, plugin and owners; boundary lengths 128/255/32/16,384/4,000 characters fit; timeout 601 hits the CHECK; microsecond timestamps stored exactly | PASS |
| CHK-M7-157 / -336 ruff S608 clean on both files; a planted f-string is red in `catalog.py` (L106) and in `catalog_plugins.py` (L123) | PASS |

## Plants (W, throwaway copies)

| Plant | Red |
| --- | --- |
| CHK-M7-375 upsert without `IS DISTINCT FROM` | 3 failed |
| CHK-M7-376 retire ignores `deleted_at` | 1 failed |
| CHK-M7-377 BIT015 "owner lists" ignores the owner | 1 failed |
| D3 `CASE` removed in `update_policy` (override ignored on a file update; reviewer-m7's request; also the TASK-148 half of CHK-M7-369) | 3 failed (`test_update_status_respects_the_override[True-…]` × 2, revival) |
| revival does not add 1 | 1 failed |
| version + 1 on every update | 5 failed |
| "inserted" read from `xmax = 0` instead of the snapshot CTE | green: an **equivalent mutant** (the alternative the impl report names); not a gap |

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-150..156 | APP | W | `pytest -q -n 0 tests/test_catalog_repo_pg.py` (m7t-t148) | PASS | 50/50 passed, 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-157 | CODE | L | `ruff check` on both files | PASS | clean | 2026-10-27 |
| CHK-M7-336 | CODE | L | plant f-string in `catalog.py` and in `catalog_plugins.py` (throwaway copies), `ruff check` | PASS (red) | S608 at catalog.py:106 and catalog_plugins.py:123, exit 1 each | 2026-10-27 |
| CHK-M7-375 | APP | W | plant: upsert without IS DISTINCT FROM | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-376 | APP | W | plant: retire ignores deleted_at | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-377 | APP | W | plant: owners_of ignores the owner in owner_lists | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-369 (148 half) | APP | W | plants: D3 CASE removed / revival without +1 / +1 always | PASS (red) | 3 / 1 / 5 failed | 2026-10-27 |
| CHK-M7-148-xmax | APP | W | plant: inserted from xmax = 0 | NOT RUN as a plant (equivalent mutant) | 50 passed: same semantics as the snapshot CTE, which the impl report names as the alternative | 2026-10-27 |

## Revision 1 (`retired_among`, for the #100 (a) widening)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-153-r1 | APP | W | `pytest -n 2 tests/test_catalog_repo_pg.py` (m7t-t161) | PASS | 52/52 passed. New: `test_retired_among_returns_only_the_retired_ids` (retired, active and unknown ids mixed: only the retired come back; none for active and unknown); `test_retired_among_empty_input_runs_no_statement` (a connection that refuses any statement: empty set, no query) | 2026-10-27 |
| CHK-M7-148-ra | APP | W | plant: state filter dropped | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-148-rb | APP | W | plant: state filter inverted (`active`) | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-336-r1 | CODE | L | plant: f-string query in `retired_among` | PASS (red) | S608 at catalog_plugins.py:53 | 2026-10-27 |

Verdict after revision 1: **PASS**.
