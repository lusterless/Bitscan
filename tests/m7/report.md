# M7 test report

Phase report for M7 (compliance catalog). Each section below is folded by the lead, unchanged, from the tester's per-task report `work/reports/TASK-###-test.md`, because the harness blocks tester sub-agents from writing this file (user ruling 2026-10-27). The per-task report is the source; if they ever differ, it wins. Test plan: `tests/m7/test-plan.md`.

## W1 (folded 2026-10-27)

| Task | Verdict | Tester | Source |
| --- | --- | --- | --- |
| TASK-139 | PASS | tester-m7 | `work/reports/TASK-139-test.md` |
| TASK-140 | PASS | tester-m7 | `work/reports/TASK-140-test.md` |
| TASK-147 | PASS (revision 1 included) | tester-m7 | `work/reports/TASK-147-test.md` |
| TASK-148 | PASS | tester-m7 | `work/reports/TASK-148-test.md` |
| TASK-149 | PASS | tester-m7 | `work/reports/TASK-149-test.md` |
| TASK-150 | PASS | tester-m7 | `work/reports/TASK-150-test.md` |
| TASK-174, 175 | static checks only (CHK-M7-302); verdict waits for G59 after TASK-154 | tester-m7 | `work/reports/TASK-174-impl.md` |

### TASK-139


Tester: tester-m7, 2026-10-27. REQ-185, PD-33 (a). Checks CHK-M7-016 to -019 (tests/m7/test-plan.md).

| Check | Command | Result |
| --- | --- | --- |
| CHK-M7-016 | fresh CPython 3.12 venvs (Windows 3.12.10, WSL 3.12.3): `pip install --require-hashes -r manager/requirements.txt` and `-r manager/requirements-dev.txt`; `python -W error -c "import python_multipart; from python_multipart.multipart import MultipartParser"` | PASS: all four installs exit 0; python_multipart 0.0.32 imports with no warning |
| CHK-M7-017 | recorded `uv pip compile` commands run in place in a throwaway copy, then `cmp` | PASS: both locks byte-identical |
| CHK-M7-018 | `git diff -U0`; tool grep of the runtime lock; `pip list` of the runtime venv | PASS: only `python-multipart==0.0.32` added; no test or lint tool |
| CHK-M7-019 | WSL `CI=true pytest -n 0 tests/test_lock_files.py tests/test_project_config.py tests/test_module_imports.py` | PASS: 139/139 passed, 0 failed, 0 skipped |

The 8 mypy errors from the bare `mypy --strict manager` are a missing pydantic plugin, not this task: the CI form (`--config-file manager/pyproject.toml`) is clean on 248 files.

#### Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-016 | APP | L, W | fresh CPython 3.12 venvs: `pip install --require-hashes -r manager/requirements.txt` and `-r manager/requirements-dev.txt`; `python -W error -c "import python_multipart; from python_multipart.multipart import MultipartParser"` | PASS | Windows 3.12.10 runtime and dev exit 0; WSL 3.12.3 runtime and dev exit 0, editable exit 0; python_multipart 0.0.32, no warning | 2026-10-27 |
| CHK-M7-017 | CODE | L | recorded `uv pip compile` commands (uv 0.13.1) run in place in a throwaway copy, then `cmp` | PASS | both locks byte-identical (runtime b6bf600e…4a26, dev 7dd909a9…c041) | 2026-10-27 |
| CHK-M7-018 | CODE | L, W | `git diff -U0` of pyproject and both locks; tool grep of the runtime lock; `pip list` of the runtime venv | PASS | only `python-multipart==0.0.32` (2 hashes) added; 0 test or lint tools | 2026-10-27 |
| CHK-M7-019 | APP | W | `pytest -q -n 0 tests/test_lock_files.py tests/test_project_config.py tests/test_module_imports.py` (m7t-u1) | PASS | 17 + 10 + 112 = 139/139 passed; whole run 437/437, 0 failed, 0 errors, 0 skipped | 2026-10-27 |

### TASK-140


Tester: tester-m7, 2026-10-27. REQ-152, REQ-155; SR §2, §3.3, §3.5, §4, §4.1; #57, #105 (g). Checks CHK-M7-010 to -014, plants CHK-M7-385, -386 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_model.py` (expected values read from the SR §4.1 table and the TS §5.2 DDL text by the test, not copied from the code).

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W (WSL 24.04, `CI=true`, label m7t-u1, `-n 0`) | `pytest -q tests/test_bit_model.py` (with the TP-M7-01 and TASK-139 files) | 71/71 passed (whole run 437/437), 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 248 files |
| plant 385a | W, throwaway copy | `BIT006` added to `Code` | red: 2 failed |
| plant 385b | W, throwaway copy | BIT101 made Reject | red: 2 failed |
| plant 386 | W, throwaway copy | `PolicyName` limit (1, 129) | red: 2 failed |

#### Acceptance criteria

| Criterion (tasks.md TASK-140) | Check | Result |
| --- | --- | --- |
| every SR §4.1 code has its SR severity | CHK-M7-010 | PASS: 18 codes = SR table; only BIT101 and BIT103 Warn |
| BIT006, BIT009 and BIT018–BIT020 absent | CHK-M7-010 | PASS: refused by `Code` and `Finding` |
| each limit equals its SR §2 value | CHK-M7-011 | PASS: lengths, 5,242,880 bytes, 1–5,000 plugins, timeout 1/600/60, control_ref 32, 14 operators in DDL enum order |
| `Finding` serialises to exactly `{line, element, code, message}` | CHK-M7-012 | PASS: also `quote` (64 chars, C0, DEL and backslash escaped) and `plugin_path` (#105 (g)) |
| frozen dataclasses, `mypy --strict` | CHK-M7-013, -014 | PASS |

Not in this task: the #105 (a) element, depth and attribute caps (35,014 / 16 / 8) are not model constants. They are checked against TASK-141's parser (CHK-M7-026).

#### Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-001..006 | CODE | W | `pytest -q -n 0 tests/test_bit_fixtures.py` (m7t-u1) | PASS | 227/227 passed (TP-M7-01 fixtures: manifest complete, one fixture per code, BIT001 set, SR §1.1 byte-identical, corpora, hostile names, hashes, no CR) | 2026-10-27 |
| CHK-M7-010..013 | CODE | W | `pytest -q -n 0 tests/test_bit_model.py` (m7t-u1) | PASS | 71/71 passed | 2026-10-27 |
| CHK-M7-014 | CODE | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | PASS | clean; 248 files | 2026-10-27 |
| CHK-M7-385 | CODE | W | plants (a) BIT006 added, (b) BIT101 Reject; `pytest tests/test_bit_model.py` | PASS (red) | (a) 2 failed, (b) 2 failed | 2026-10-27 |
| CHK-M7-386 | CODE | W | plant PolicyName (1, 129) | PASS (red) | 2 failed | 2026-10-27 |

### TASK-147


Tester: tester-m7, 2026-10-27. REQ-161, REQ-178; TS §4.1 "Locking"; design note D4. Checks CHK-M7-140 to -145, plants CHK-M7-372 to -374 plus extra plants (tests/m7/test-plan.md). Test file: `manager/tests/test_catalog_lock_pg.py` (17 tests). Waiting is observed through `pg_locks` (a not-granted row for the waiter's backend), never by sleeping for order. Each nested-session row runs its body in a worker thread joined with a timeout, so a self-deadlock fails instead of hanging.

#### Runs (W = WSL 24.04, `CI=true`, `-n 0`, one PostgreSQL 16 container, leftover-own 0)

| Run | Command | Count |
| --- | --- | --- |
| r0 (label m7t-t147) | `pytest tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py` | 43/43 passed (13 + 30), 0 failed, 0 skipped |
| r1 (label m7t-t147r1, after the nested-session guard) | same files plus `tests/test_imports_repo_pg.py` | 69/69 passed (17 lock + 30 pool/runtime + 22 imports), 0 failed, 0 skipped |
| static (L) | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean, 248 files |

#### Checks

| Check | What | Result |
| --- | --- | --- |
| CHK-M7-140 | of two sessions the second waits (seen in `pg_locks`) until the first releases; order a_in, a_out, b_in; a session also waits for a holder in another process (a raw connection, as a CLI would) | PASS |
| CHK-M7-141 | two transactions in one session keep the lock throughout (held between them, while idle), on the same backend pid | PASS |
| CHK-M7-142 | released when the block raises, when a transaction inside raises (the session stays usable), when the connection is closed inside the block, and when the backend is terminated (`pg_terminate_backend`) | PASS |
| CHK-M7-143 | session-level lock on the `hashtext('catalog')` key (bigint form, `objsubid` 1), taken while idle outside a transaction, and the only advisory lock the backend holds | PASS |
| CHK-M7-144 | the connection goes back clean: `max_size=1` pool, a stray `pg_advisory_lock(42)` released, `autocommit` False, 0 advisory locks; existing pool and runtime tests pass; nesting refused (savepoint outside a transaction, transaction in transaction, `db.transaction()` in a session transaction, `db.session()` in `db.transaction()`); a rolled-back savepoint drops its rows **and its on-commit hooks**, and the hooks run only after COMMIT (rows visible to another connection inside the hook); an unreachable database gives `DatabaseUnavailable` with no DSN text and no chained cause | PASS |
| CHK-M7-145 | `Runtime` and the new Protocols under `mypy --strict` (CI form) | PASS |
| r1 rows | a nested `db.session()` inside `session()` + `catalog_lock` raises RuntimeError (no deadlock); the outer session's transaction still works, the lock is free and its connection goes back clean (0 advisory locks); a nested session without the lock is refused too; another thread can open a session while one is open; a session opens again after a normal exit and after an error | PASS |

#### Plants (throwaway copies, imported first through PYTHONPATH)

| Plant | Red |
| --- | --- |
| CHK-M7-372 unlock not in `finally` | 2 failed (block raises; transaction raises) |
| CHK-M7-373 `pg_advisory_xact_lock` instead of the session lock | 5 failed |
| CHK-M7-374 another key (`hashtext('catalog2')`) | 6 failed (incl. the other-process holder) |
| `catalog_lock` a no-op (the TASK-147 half of CHK-M7-356) | 6 failed |
| savepoint keeps a rolled-back savepoint's hooks | 1 failed |
| session release skips `pg_advisory_unlock_all()` | 1 failed (connection back clean) |
| r1: nested-session guard removed | 3 failed (2 caught as a deadlock by the bounded worker, 1 DID NOT RAISE), no hang |

Note (not a finding): `pg_advisory_lock` waits without a bound (no timeout in TS §4.1), as the impl report says. TASK-160's stop path has to account for a waiter.

#### Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-140..145 | APP | W | `pytest -q -n 0 tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py` (m7t-t147) | PASS | 43/43 passed (13 + 30), 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-140..145-r1 | APP | W | same plus `tests/test_imports_repo_pg.py`, after r1 (m7t-t147r1) | PASS | 69/69 passed (17 lock incl. 4 nested-session rows + 30 + 22) | 2026-10-27 |
| CHK-M7-145 | CODE | L | `mypy --strict --config-file manager/pyproject.toml manager` | PASS | no issues, 248 files | 2026-10-27 |
| CHK-M7-372 | APP | W | plant: unlock not in finally | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-373 | APP | W | plant: pg_advisory_xact_lock | PASS (red) | 5 failed | 2026-10-27 |
| CHK-M7-374 | APP | W | plant: key hashtext('catalog2') | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-356 (147 half) | APP | W | plant: catalog_lock a no-op | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-147-sp | APP | W | plant: savepoint keeps rolled-back hooks | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-147-rel | APP | W | plant: session release skips pg_advisory_unlock_all | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-147-nest | APP | W | plant r1: nested-session guard removed; `-k 'nested or another_thread or opens_again'` | PASS (red) | 3 failed (2 as deadlock via the bounded worker, 1 DID NOT RAISE); no hang | 2026-10-27 |

### TASK-148


Tester: tester-m7, 2026-10-27. REQ-158, REQ-159; SR §3.1 to §3.4, §3.6 steps 1 to 5; TS §5.2 (catalog DDL and grants); #14, #21, #100 (a), #104 (b), (d), (e); D3. Files under test: `bm/repositories/catalog.py` and `bm/repositories/catalog_plugins.py` (the lead's split). Checks CHK-M7-150 to -157, plants CHK-M7-336, -375 to -377 and the D3 / version plants. Test file: `manager/tests/test_catalog_repo_pg.py` (50 tests), as `bitscan_app` on a database of its own (`own_migrated_server`), each test in a rolled-back transaction unless it needs a second connection.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| clean (W, label m7t-t148, `CI=true`, `-n 0`) | `pytest tests/test_catalog_repo_pg.py` | 50/50 passed, 0 failed, 0 skipped, leftover-own 0 |
| static (L) | ruff, ruff format, mypy (CI form) | clean, 248 files |

#### Checks

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

#### Plants (W, throwaway copies)

| Plant | Red |
| --- | --- |
| CHK-M7-375 upsert without `IS DISTINCT FROM` | 3 failed |
| CHK-M7-376 retire ignores `deleted_at` | 1 failed |
| CHK-M7-377 BIT015 "owner lists" ignores the owner | 1 failed |
| D3 `CASE` removed in `update_policy` (override ignored on a file update; reviewer-m7's request; also the TASK-148 half of CHK-M7-369) | 3 failed (`test_update_status_respects_the_override[True-…]` × 2, revival) |
| revival does not add 1 | 1 failed |
| version + 1 on every update | 5 failed |
| "inserted" read from `xmax = 0` instead of the snapshot CTE | green: an **equivalent mutant** (the alternative the impl report names); not a gap |

#### Report rows (tests/m7/report.md format)

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

### TASK-149


Tester: tester-m7, 2026-10-27. REQ-160, REQ-166, REQ-173; SR §3.5, §3.6; TS §4.1 L520, §4.2 L540, §5.2; #98 (g), (h), #110. File under test: `bm/repositories/imports.py`. Checks CHK-M7-160 to -164, plants CHK-M7-378 to -380 and extras. Test file: `manager/tests/test_imports_repo_pg.py` (22 tests), as `bitscan_app` on a database of its own.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t149, `CI=true`, `-n 0`) | `pytest tests/test_imports_repo_pg.py tests/test_grants.py` | 47/47 passed (22 + 25 M1 grant probes), 0 failed, 0 skipped |
| r1 (W, label m7t-t147r1) | `tests/test_imports_repo_pg.py` after a **test fix** (the paging walk had no progress bound, so plant 380 looped instead of failing) | 22/22 passed (in the 69/69 run) |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

#### Checks

| Check | Result |
| --- | --- |
| CHK-M7-160 every column written, `imported_at` = now; defaults (no version, counts 0, `imported_by` NULL); `errors` (warnings + rejects + a file-level null finding with `é`, backslash, RTL, tab, LF) round-trip in order; `[]` for none; CHECK refuses unknown or mis-cased mode and outcome; a record committed on another connection survives a sibling catalog rollback; on one pinned connection, tx1 rolls back and tx2 keeps the record (D4); the function never commits the caller's transaction | PASS |
| CHK-M7-161 newest-first walk with `limit + 1` for N = 1, 2, 3, 7: every row once, strictly decreasing, our rows in order, cursor always moves; the first page is newest and the keyset is strict; a page row equals the stored row (hostile `file_name`, `errors`, every column) | PASS |
| CHK-M7-162 task insert (user and CLI), get, finish once (a second finish returns False and changes nothing), unknown id; `fail_running_tasks` fails exactly the running rows with result and `finished_at` and leaves succeeded and failed rows alone; a finish racing the start-up fail changes the row once (the UPDATE waits for the row lock and then skips) | PASS |
| CHK-M7-163 `bitscan_app` cannot UPDATE or DELETE `bit_import`, nor DELETE `task`; the M1 grant probes (`test_grants.py`, 25) pass | PASS |
| CHK-M7-164 ruff S608 clean; a planted f-string is red (L113) | PASS |

#### Plants (W, throwaway copies)

| Plant | Red |
| --- | --- |
| CHK-M7-379 `fail_running_tasks` without `state = 'running'` | 2 failed |
| CHK-M7-380 keyset `import_id <= cursor` | 5 failed ("cursor did not move", duplicates), after the test fix; before the fix it looped (killed, recorded) |
| `finish_task` without the `running` condition | red (`test_task_insert_get_finish`: a second finish returned True) |
| `ORDER BY import_id ASC` | 6 failed |
| CHK-M7-378 (record on the caller's transaction) | not a repository plant: the function takes the caller's connection and never opens a transaction, so "its own transaction" is TASK-154's duty; the D4 rows above (two rollback cases) are the evidence on this side, and CHK-M7-339 is planted at TASK-154 |

#### Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-160..163 | APP | W | `pytest -q -n 0 tests/test_imports_repo_pg.py tests/test_grants.py` (m7t-t149) | PASS | 47/47 passed (22 + 25) | 2026-10-27 |
| CHK-M7-161-r1 | APP | W | `tests/test_imports_repo_pg.py` after the paging-loop bound (test fix) (m7t-t147r1) | PASS | 22/22 passed | 2026-10-27 |
| CHK-M7-164 | CODE | L | `ruff check`; plant f-string in imports.py | PASS | clean; plant S608 at imports.py:113, exit 1 | 2026-10-27 |
| CHK-M7-379 | APP | W | plant: fail_running_tasks without state filter | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-380 | APP | W | plant: keyset <= | PASS (red) | 5 failed after the test fix (first attempt looped: test bug, killed, fixed) | 2026-10-27 |
| CHK-M7-149-fin | APP | W | plant: finish_task without the running condition | PASS (red) | test_task_insert_get_finish failed | 2026-10-27 |
| CHK-M7-149-asc | APP | W | plant: ORDER BY ASC | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-378 | APP | W | record written on the caller's transaction | NOT RUN (moved) | the repository never opens a transaction; planted at TASK-154 as CHK-M7-339; D4 rollback rows pass here | 2026-10-27 |

### TASK-150


Tester: tester-m7, 2026-10-27. REQ-165, REQ-167, REQ-168, REQ-169; TS §4.3 L546 to L551, §5.2 (DDL, `v_plugin`, grants L1005 to L1013); #9, #98 (a), (b), #103, #104 (a), (b), (d); D3. Files under test: `bm/repositories/catalog_admin.py` and `bm/repositories/catalog_integrity.py` (the lead's split). Checks CHK-M7-165 to -170, plants CHK-M7-337, -365, -381 to -384 and extras. Test file: `manager/tests/test_catalog_admin_repo_pg.py` (24 tests), as `bitscan_app` on a database of its own. Catalog rows are written with plain SQL as `bitscan_app` (independent of TASK-148); scans, jobs, schedules and the agent are written as owner (`manager/tests/catalog_rows.py`).

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| clean (W, label m7t-t150, `CI=true`, `-n 0`) | `pytest tests/test_catalog_admin_repo_pg.py` | 24/24 passed, 0 failed, 0 skipped, leftover-own 0 |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

#### Checks

| Check | Result |
| --- | --- |
| CHK-M7-165 the list holds 5 of {3 enabled, 2 disabled (one of them by override), 1 deleted}; `enabled` gives 3, `disabled` 2 (effective status); N + 1 with limit N (N = 1, 2, 3, 5), inserted out of order: each once, in (`policy_name`, `policy_id`) order; the item has exactly the #98 (a) fields in order, values exact (`family_name`, `plugin_count` = its own `policy_plugin` rows) and equal to the list row; `item()` returns deleted rows (PATCH answer) and None for unknown | PASS |
| CHK-M7-166 detail: plugins in file order (`sort_order` 1..3, not insertion or uuid order), `display_name` = `<family> - <plugin>` from `v_plugin`, every #98 (b) field in order; hostile text (`<img onerror>`, quotes, backslash, C0, DEL, U+2028, RTL, emoji) byte-identical through the JSON aggregation; `updated_at` exact to the microsecond with any session time zone (Asia/Kathmandu); a deleted policy shows `deleted_at` and keeps its plugins (#104 (a)); unknown is None; no plugins gives `[]` | PASS |
| CHK-M7-167 `set_status` enabled/disabled sets the override; a no-op keeps `updated_at` while a first override moves it; `clear_override` restores `file_status` (both ways) and a no-op keeps `updated_at`; deleted and unknown are refused with nothing changed; `lock()` returns the state under `FOR UPDATE` (a second NOWAIT fails); **D3 race**: a file UPDATE (TASK-148 `update_policy`) waiting on an uncommitted PATCH disable keeps `disabled` + override after the PATCH commits | PASS |
| CHK-M7-168 soft delete with owner-written rows: only the policy's `queued` compliance jobs (the original and a queued retry) → `cancelled` with `finished_at`; `dispatched`, `running`, `completed`, the other policy's queued job and an inventory job unchanged; both enabled schedules disabled (an already disabled one and the other policy's untouched); `deleted_at`, `source_file` `deleted/<id>` and `updated_at` set, statuses and version kept; retired = owned and listed, owned and unlisted, and listed-only-by-it (owner elsewhere); a plugin also listed by a live policy stays active; `policy_plugin` rows kept; the row is still there; the returned ids are exact; a second delete and an unknown id return None and change nothing (checksums); a caller rollback undoes everything (checksums); `bitscan_app` cannot DELETE a policy | PASS |
| CHK-M7-169 `integrity_rows`: non-deleted only; counts 2/0, 3/2 (retired + owned by another), 0/0 for an empty policy; ordered by id; `rejected_files`: only pairs with a `rejected` row (a later `success` for the same pair still counts as rejected history; a success-only pair, another hash for the same name, and a missing file do not); empty input | PASS |
| CHK-M7-170 / -337 ruff S608 clean; a planted f-string is red in `catalog_admin.py` (L160) and in `catalog_integrity.py` (L50) | PASS |

#### Plants (W, throwaway copies)

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

#### Report rows (tests/m7/report.md format)

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


## W2 to W13 and the M7 gate (folded 2026-10-28)

Folded unchanged by the lead from each per-task report (the source); headings are demoted one level.

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-141 | TASK-141 TEST: PASS (revision 1) | `work/reports/TASK-141-test.md` |
| TASK-142 | TASK-142 TEST: PASS | `work/reports/TASK-142-test.md` |
| TASK-143 | TASK-143 TEST: PASS | `work/reports/TASK-143-test.md` |
| TASK-144 | TASK-144 TEST: PASS | `work/reports/TASK-144-test.md` |
| TASK-145 | TASK-145 TEST: PASS | `work/reports/TASK-145-test.md` |
| TASK-146 | TASK-146 TEST: PASS (revision 1) | `work/reports/TASK-146-test.md` |
| TASK-151 | TASK-151 TEST: PASS | `work/reports/TASK-151-test.md` |
| TASK-152 | TASK-152 TEST: PASS (round 2, on TASK-147 revision 2) | `work/reports/TASK-152-test.md` |
| TASK-153 | TASK-153 TEST: PASS | `work/reports/TASK-153-test.md` |
| TASK-154 | TASK-154 TEST: PASS | `work/reports/TASK-154-test.md` |
| TASK-155 | TASK-155 TEST: PASS (r0 and revision 1) | `work/reports/TASK-155-test.md` |
| TASK-156 | TASK-156 TEST: PASS | `work/reports/TASK-156-test.md` |
| TASK-157 | TASK-157 TEST: PASS (on revision 1) | `work/reports/TASK-157-test.md` |
| TASK-158 | TASK-158 TEST: PASS | `work/reports/TASK-158-test.md` |
| TASK-159 | TASK-159 TEST: PASS (on revision 1); REQ-164 (4) PASS with the TASK-155 r2 and TASK-152 r1 hooks in | `work/reports/TASK-159-test.md` |
| TASK-160 | TASK-160 TEST: PASS (round 2, on revision 1) | `work/reports/TASK-160-test.md` |
| TASK-161 | TASK-161 TEST: PASS | `work/reports/TASK-161-test.md` |
| TASK-162 | TASK-162 TEST: PASS | `work/reports/TASK-162-test.md` |
| TASK-163 | TASK-163 TEST: PASS | `work/reports/TASK-163-test.md` |
| TASK-164 | TASK-164 TEST: PASS | `work/reports/TASK-164-test.md` |
| TASK-165 | TASK-165 TEST: PASS | `work/reports/TASK-165-test.md` |
| TASK-166 | TASK-166 TEST: PASS | `work/reports/TASK-166-test.md` |
| TASK-167 | PASS (round 2, on revision 1; revision 2 is a one-line wording fix, reviewed) | `work/reports/TASK-167-test.md` |
| TASK-168-173 | PASS (web batch TP-M7-29) | `work/reports/TASK-168-173-test.md` |
| TASK-174 | TASK-174 TEST: PASS (G59; a targeted re-run follows TASK-146 r2 approval) | `work/reports/TASK-174-test.md` |
| TASK-175 | TASK-175 TEST: PASS (G59; a targeted re-run follows TASK-146 r2 approval) | `work/reports/TASK-175-test.md` |
| TP-M7-30 | TP-M7-30 TEST (M7 importer security suite): PASS | `work/reports/TP-M7-30-test.md` |
| M7-gate | M7 gate TEST: PASS (TASK-146 r2 deferred; its rows run on r1) | `work/reports/M7-gate-test.md` |

### TASK-141


Tester: tester-m7b, 2026-10-27. REQ-150, REQ-176, REQ-180. Spec: TS §4.1 L516–L517, §8.1 L1251; SR §4, §4.1 BIT001; answers #57, #105 (a), (b), (c), (f), (g). Checks CHK-M7-020 to -028 and plants CHK-M7-320, -321, -322, -323, -347 (tests/m7/test-plan.md). Test files: `manager/tests/test_bit_parse.py`, `manager/tests/test_bit_fuzz.py` and the helper `manager/tests/bit_unit.py`. Implementation: `manager/bitscan_manager/services/importer/parse.py` (impl report `work/reports/TASK-141-impl.md`, including "Revision 1").

#### Rounds

| Round | Verdict | What |
| --- | --- | --- |
| 1 | FAIL | `test_bit_parse.py::test_utf16_without_bom_is_bit001` (6 params). Expected exactly one BIT001 (REQ-150, D1, #105 (f): UTF-8 only). Actual: no finding and a full tree. Repro: `parse_bit(sr_example().decode().encode("utf-16-le"))`. Cause: UTF-16 bytes without a BOM are valid UTF-8 (NUL is valid UTF-8), so the strict decode passed, and expat's `initScan` detects UTF-16 from `3C 00` / `00 3C` even when given `encoding="utf-8"`. The declared-encoding pre-check never ran, because the buffer does not start with the bytes `<?xml`. 270/276 passed. |
| 2 (rev 1) | PASS | Any 0x00 byte is now BIT001 before the decode. 276/276. |

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| round 1 | L | `pytest -q tests/test_bit_parse.py` | 270/276 passed, 6 failed, 0 errors, 0 skipped |
| re-run of the failing test | L | `pytest -q "tests/test_bit_parse.py::test_utf16_without_bom_is_bit001"` | 6/6 passed |
| clean, rev 1 | L | `pytest -q tests/test_bit_parse.py` | 276/276 passed, 0 failed, 0 errors, 0 skipped |
| clean, rev 1 | W | `CI=true pytest -q tests/test_bit_parse.py` | 276/276 passed, 0 skipped |
| fuzz | W | `CI=true pytest -q tests/test_bit_fuzz.py` | 4/4 passed (10,500 generated inputs) |
| fuzz | L | `pytest -q tests/test_bit_fuzz.py` | 4/4 passed |
| dependents | W | `pytest -q tests/test_bit_fixtures.py tests/test_bit_model.py tests/test_bit_structure.py` | 227/227, 71/71, 253/253 passed |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L = Windows 11, `manager/.venv` (CPython 3.12.10). W = WSL2 Ubuntu 24.04.5, kernel 6.18 WSL2, CPython 3.12.3. Copy `/root/bstest-m7b-base` (rsync without `.venv`, `__pycache__`, `.git`), venv `/root/venv-m7b` (`pip install --require-hashes -r manager/requirements-dev.txt` + `--no-deps -e manager`), `CI=true`, no containers (pure unit).

#### Acceptance criteria (tasks.md TASK-141)

| Criterion | Check | Result |
| --- | --- | --- |
| Every BIT001 fixture gives exactly one BIT001: external entity by file and URL, parameter entity, billion laughs, quadratic blow-up, DTD only, UTF-16, ISO-8859-1, invalid UTF-8, not well-formed, empty, 5 MiB + 1 | CHK-M7-020, -023, -025 | PASS: all 35 `bits/tests/bit001` fixtures; DOCTYPE fixtures at the DOCTYPE line with a DTD message; manifest lines (invalid UTF-8 line 5, mismatched tags line 4); messages hold no input text. Also UTF-16 LE/BE without a BOM (3 declarations each), NUL anywhere, 7 non-UTF-8 declarations (ASCII bodies, so only D1 catches them), XML 1.1/2.0, 4 BOMs at line 1, and 6 bad-UTF-8 forms × 4 places at line 7 |
| No file or network access | CHK-M7-021 | PASS: audit hook (`open`, `socket.*`, `urllib.*`, `subprocess.*`, `os.*` exec/spawn/listdir, `ctypes.*`) records nothing; canary content never in the result; a local listener sees no connection (xxe-file, external-dtd-file, xinclude, xxe-url, parameter-entity, external-dtd-url). Guard test: the hook does see a real `open` |
| Defence in depth (all three defusedxml layers) | CHK-M7-320, -322 | PASS: parser built with `forbid_dtd`, `forbid_entities`, `forbid_external` all True (spy). With the DTD layer neutralised, all 6 entity fixtures still get "Entity declarations ..." with no side effects and < 64 MiB. With DTD and entity layers neutralised, xxe-file and xxe-url get "External references ...", with no canary and no connection |
| Under 64 MiB peak memory | CHK-M7-022 | PASS: billion laughs, quadratic blow-up, valid 5 MiB file, 5 MiB of text in one element, 35,015-element cap case: `tracemalloc` peak < 64 MiB, < 2 s each |
| A valid 5 MiB file parses | CHK-M7-023 | PASS: exactly 5,242,880 bytes, no finding; 5,242,881 gives BIT001 with `line` null and the parser never constructed (spy); oversize garbage gets the size rule, not the encoding rule |
| SR §1.1 example tree, lines match the file | CHK-M7-024 | PASS: start-tag lines computed from the text by a separate scanner equal the tree's, in pre-order, for the SR example, all 15 `valid/` fixtures and both samples. `Execute` text is the untrimmed CDATA, `attributes == (("timeout", "30"),)`. CDATA, text and comments joined (comments dropped); predefined entities and char refs decoded; CRLF and a lone CR normalised and counted; attribute order kept; multi-line start tag at the `<` line |
| #105 (a) caps | CHK-M7-026 | PASS: depth 16 ok, 17 BIT002 at the 17th element's line; 35,014 elements ok, 35,015 BIT002 at its line; 5,000 `Plugin` (bare and canonical) ok, 5,001 BIT017 at the 5,001st; 8 attributes ok, 9 BIT002 |
| Namespaces one BIT002 (impl change 1) | CHK-M7-053 (parser half) | PASS: default, prefixed, `xmlns=""`, unbound element and attribute prefix, and the 3 fixtures each give one BIT002 at the declaring line, never BIT001 |
| PIs recorded for TASK-143 | CHK-M7-024 | PASS: `pi_lines` = (3, 5) for an inner and a trailing PI; the declaration not counted; fixtures (7,) and (3,) |
| 10,000 random inputs raise nothing | CHK-M7-027 | PASS: 4,000 random byte strings, 4,000 mutations of the SR example and both samples, 2,500 XML token soups; each returns a `ParseResult` with ≤ 1 finding of BIT001/BIT002/BIT017, `root` None iff there is a finding, a line within the input, < 2 s |
| No `xml`/`lxml` import | CHK-M7-028, -347 | PASS: AST scan of `parse.py` (also no `re`, `subprocess`, `socket`, `urllib`, `http`, `logging`, `time`, `os`, `io`, `pathlib`, … and no `open`/`eval`/`exec` calls) and of every module under `services/importer/` (no `xml`, `lxml`, `re`). No log record and no stdout/stderr for every bit001, bit002 and valid fixture |

#### Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy (no change): ruff clean, `pytest tests/test_bit_parse.py -k "not utf16_without_bom"` green. Plants were run on rev 0, with the known round-1 failure excluded so that each plant's own red test is visible.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-320 | `forbid_external=False` | `test_parser_built_with_all_three_forbids`, `test_external_layer_holds_…` (2) |
| CHK-M7-321 | `forbid_dtd=False` | `test_bit001_fixture_gives_exactly_one_bit001` (dtd-only, dtd-element-decl, external-dtd-file, …), `test_dtd_refused_at_the_doctype_line` |
| CHK-M7-322 | `forbid_entities=False` | spy test, `test_entity_layer_holds_…` (6) |
| CHK-M7-323 | size cap 50 MiB | `test_one_byte_over_is_bit001_and_never_parsed`, `test_oversize_garbage_…` |
| CHK-M7-347 | `import xml.etree.ElementTree` in parse.py | ruff rc 1 (TID251); `test_parser_imports_only_safe_modules`, `test_no_importer_module_imports_xml_or_lxml` |
| extra | declared-encoding check removed | iso-8859-1-ascii, us-ascii fixtures; 7 declaration tests |
| extra | XML version check removed | xml-1.1 fixture; 2 version tests |
| extra | depth `>=` → `>` | depth-17 tests (2) |
| extra | element cap `>` → `>=` | 35,014 / 35,015 tests |
| extra | attribute cap + 1 | `test_8_attributes_accepted_9_refused` |
| extra | plugin cap + 1 | 5,001-plugin tests (2) |
| extra | collector gets a `comment` method | `test_cdata_text_and_comments_joined_in_order` |
| extra | `start_ns` no longer stops | namespace tests, xinclude canary test |
| equivalent | BOM check removed | survives: FF FE / FE FF / 00 00 FE FF are already invalid UTF-8, so the strict decode gives the same BIT001 at line 1 |
| equivalent | UTF-8 error line from `exc.end` | survives: `start` and `end` of a UTF-8 error never span a newline |
| equivalent | expat message quoted whole | survives: without a DTD, expat reports an undefined entity itself, with no name in its text. The code-11 special case is defensive only |

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-020 | CODE | L, W | `pytest -q tests/test_bit_parse.py` (bit001 params) | PASS | 35/35 fixtures, one BIT001 each; rev 0 FAIL on UTF-16 without BOM (6), fixed in rev 1, re-run 6/6 | 2026-10-27 |
| CHK-M7-021 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "never_opened or never_fetched or layer or forbids"` | PASS | audit hook empty, listener silent, canary absent; three defusedxml layers each proven alone | 2026-10-27 |
| CHK-M7-022 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "bombs or 5_mib"` | PASS | peak < 64 MiB, < 2 s | 2026-10-27 |
| CHK-M7-023 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "5_mib or one_byte_over or oversize or empty"` | PASS | 5,242,880 passes; 5,242,881 BIT001, parser not built | 2026-10-27 |
| CHK-M7-024 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "tree or lines or cdata or entities or crlf or pi"` | PASS | lines from the text = tree lines (SR example, 15 valid fixtures, 2 samples) | 2026-10-27 |
| CHK-M7-025 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "utf or declar or bom or xml_other"` | PASS | 8 accepted declarations; non-UTF-8, BOMs, invalid UTF-8 (line 7), UTF-16 no BOM → BIT001 | 2026-10-27 |
| CHK-M7-026 | CODE | L, W | `pytest -q tests/test_bit_parse.py -k "depth or elements or plugins or attributes or namespace"` | PASS | 16/17, 35,014/35,015, 5,000/5,001, 8/9 boundaries; namespaces one BIT002 | 2026-10-27 |
| CHK-M7-027 | CODE | L, W | `pytest -q tests/test_bit_fuzz.py` | PASS | 4/4 (10,500 inputs); W 7.9 s | 2026-10-27 |
| CHK-M7-028 | CODE | L | `pytest -q tests/test_bit_parse.py -k imports` + `ruff check manager` | PASS | AST scan clean; ruff clean | 2026-10-27 |
| CHK-M7-320 | CODE | L | plant `forbid_external=False` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-321 | CODE | L | plant `forbid_dtd=False` | PASS (red) | ≥ 3 failed | 2026-10-27 |
| CHK-M7-322 | CODE | L | plant `forbid_entities=False` | PASS (red) | 7 failed | 2026-10-27 |
| CHK-M7-323 | CODE | L | plant cap 50 MiB | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-347 | CODE | L | plant `import xml.etree.ElementTree` | PASS (red) | ruff rc 1; 2 failed | 2026-10-27 |

#### Notes for main and the reviewer

- Impl change 3 (BIT017 at the 5,001st `Plugin` in the parser) is tested as built. Main accepted it on 2026-10-27 as an amendment to #105 (a), because TS L517 puts the 5,000-plugin limit on the parse step. A 5,001-plugin file therefore reports only BIT017.
- Impl change 4 (8-attribute cap) is in the approved #105 (a).
- The first Windows fuzz run stalled for more than 10 minutes while parse.py was being revised under it. The same suite takes 8 s on W and passes on L, and I found no product cause. I could not stop the stalled process from my session; it has since exited.

### TASK-142


Tester: tester-m7b, 2026-10-27. REQ-152, REQ-153, REQ-154. Spec: SR §2.3 (`PluginId`, `ExpectedResult`), §2.4 (numbers; regex "multiline"; case-sensitive), §3.3 (`control_ref`, 32); TS §4.5 (RE2); security invariants (RE2 for untrusted patterns); answers #13, #17, #109. Checks CHK-M7-040 to -045, plant CHK-M7-325 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_values.py`. Implementation: `manager/bitscan_manager/services/importer/values.py` (impl report `work/reports/TASK-142-impl.md`).

Contract tested as written (impl report, consistent with #17 and SR §2.4): the checks take already-trimmed text, and the importer calls them on `trim_xml(value)`. So `is_number(" 14")` is False and `is_number(trim_xml(" 14 "))` is True.

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | L | `pytest -q tests/test_bit_values.py` | 144/144 passed, 0 failed, 0 errors, 0 skipped |
| clean | W | `CI=true pytest -q tests/test_bit_values.py` | 144/144 passed, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L and W are as in `work/reports/TASK-141-test.md`. W is WSL2 Ubuntu 24.04.5 with CPython 3.12.3, venv `/root/venv-m7b` from the hashed dev lock (google-re2 1.1.20251105).

#### Acceptance criteria (tasks.md TASK-142)

| Criterion | Check | Result |
| --- | --- | --- |
| #13 accept and reject lists | CHK-M7-040 | PASS: 10 accepted (incl. `007`, `-0`, a 51-digit decimal); 45 refused (`1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `+`, `--1`, `+-1`, Arabic-Indic, fullwidth, superscript, inner space, `1,5`, padded forms, U+00A0, …); `parse_number` gives the exact `Decimal` (2^53 + 1 > 2^53, 0.1 == 0.10, 1e-22 > 0). Property: 2,000 strings agree with an independent RE2 oracle of the #13 grammar |
| `(?=x)` and `(a)\1` refused while `^MaxAuthTries\s+[1-4]$` compiles | CHK-M7-041 | PASS: 9 RE2 patterns compile (incl. `(a+)+$`, POSIX class, named group, UTF-8). 15 refused: lookahead, negative lookahead, lookbehind, negative lookbehind, backreference, `[`, `(`, `)`, `a{2,1}`, `*`, `\8`, `(?P=n)`, `a++`, `\Z(`, a lone surrogate. Each raises `PatternError("not a valid RE2 pattern")` with no cause or context chained. Guard: Python `re` does accept `(?=x)`, `(a)\1` and `(?<!a)b`, so the CHK-M7-325 plant is detectable |
| The evaluator's form | CHK-M7-041 | PASS: compiled patterns are multiline (`^`/`$` per line, SR §2.4), `.` does not match a newline, case-sensitive, UTF-8 |
| A 4,000-character pattern within 1 s | CHK-M7-041 | PASS: 4 distinct 4,000-char patterns (no LRU hit), and the nested-repeat and 1,000-deep-group cases, each < 1 s |
| Nothing on stderr | CHK-M7-041 | PASS: `capfd` (fd level) and `caplog` empty across all refused patterns. A fresh subprocess (RE2's first compile) writes 0 bytes to fd 2 and fd 1. Guard: stock `re2.compile('(?=x)')` does write to fd 2 in a fresh process |
| #109 forms | CHK-M7-042 | PASS: the SR §1.1 id, nil, all-f, version/variant 0 and f accepted. Refused: uppercase, mixed case, braces, `urn:uuid:`, 32-hex, 35/37 chars, misplaced hyphens, non-hex `g`, Arabic-Indic and fullwidth digits, underscores, padded, all hyphens, empty. Property: 2,000 inputs (uuids, upper-cased uuids, near-miss text) agree with an RE2 oracle |
| Trimming removes only space, tab, CR, LF (U+00A0 stays) | CHK-M7-043 | PASS: U+00A0, U+2003, U+FEFF, VT, FF, NEL and U+2028 all kept; inner whitespace kept |
| `control_ref` for every REQ-154 (1) case | CHK-M7-044 | PASS: `1.3.1.1 - Ensure…` → `1.3.1.1`; `Ensure` → BIT101; `1.3.` → `1.3`; `1..2` → `1`; `1.3.1.1Ensure` → `1.3.1.1`; leading `.`, `-`, Arabic-Indic, fullwidth and superscript → BIT101; 32 characters kept, 33 → BIT103 (dotted and plain forms); a warning never carries a value; frozen. Property: 3,000 names agree with an RE2 oracle of `[0-9]+(\.[0-9]+)*` |
| No `import re`; the module M8 imports | CHK-M7-045 | PASS: AST imports include `re2`; none of `re`, `regex`, `logging`, `os`, `io`, `subprocess`, `socket`, `pathlib`, `time`, `datetime`, `sys`, `xml`, `lxml`. The 8 helpers are exported |

#### Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy (no change): `pytest tests/test_bit_values.py` green. The control's ruff run showed 7 findings in another builder's in-progress file at copy time; `ruff check manager` on the tree is clean now.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-325 | BIT013 helper compiles with Python `re` (`noqa: TID251`) | `test_non_re2_patterns_refused` ((?=x), (?!x), (?<=a)b, (a)\1, …) |
| extra | `log_errors = True` | both stderr tests |
| extra | `(?m)` dropped | `test_compiled_pattern_is_multiline` |
| extra | RE2 error chained (no `from None`) | `test_non_re2_patterns_refused` (cause/context check) |
| extra | `str.strip()` (all Unicode space) | U+00A0 / U+2003 / U+FEFF trim rows, padded-number test |
| extra | `isdigit` without `isascii` | Arabic-Indic / fullwidth number rows |
| extra | `float()` grammar | `1e3`, `nan`, `inf`, `1_000`, … rows |
| extra | trailing `.` accepted | `5.`, `0.` rows, number oracle |
| extra | uppercase hex accepted | uppercase / mixed-case rows, UUID oracle |
| extra | hyphen anywhere | misplaced-hyphen rows |
| extra | `control_ref` cap `>=` 32 | 32 kept / 33 BIT103 test |
| extra | Unicode `isdigit` in `control_ref` | Arabic-Indic / fullwidth / superscript rows, oracle |
| extra | trailing `.` kept in the reference | `1.3.`, `1..2` rows, 32/33 test |

All 13 plants are red; none survived.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-040 | CODE | L, W | `pytest -q tests/test_bit_values.py -k number` | PASS | 10 accept / 45 reject rows; exact Decimal; 2,000-case oracle | 2026-10-27 |
| CHK-M7-041 | CODE | L, W | `pytest -q tests/test_bit_values.py -k "pattern or re2 or stderr"` | PASS | 9 compile / 15 refused; multiline; < 1 s; fd 2 empty (in process and fresh process); guards prove `re` and stock RE2 differ | 2026-10-27 |
| CHK-M7-042 | CODE | L, W | `pytest -q tests/test_bit_values.py -k uuid` | PASS | 5 accept / 17 reject; 2,000-case oracle | 2026-10-27 |
| CHK-M7-043 | CODE | L, W | `pytest -q tests/test_bit_values.py -k trim` | PASS | 11 rows; only space, tab, CR, LF removed | 2026-10-27 |
| CHK-M7-044 | CODE | L, W | `pytest -q tests/test_bit_values.py -k control_ref` | PASS | 15 rows + 32/33 + oracle 3,000 | 2026-10-27 |
| CHK-M7-045 | CODE | L | `pytest -q tests/test_bit_values.py -k "imports or exports"` + `ruff check manager` | PASS | no `re`; re2 used; helpers exported | 2026-10-27 |
| CHK-M7-325 | CODE | L | plant: Python `re` in `compile_pattern` | PASS (red) | lookaround/backreference rows failed | 2026-10-27 |

### TASK-143


Tester: tester-m7b, 2026-10-27. REQ-151, REQ-176. Spec: SR §2, §2.1–§2.3 (names, order, occurrence), §4 (BIT001/BIT002 first; otherwise every failing rule), §4.1 BIT002 and BIT016; TS §1.4; answers #2, #10, #16, #105 (c), (d), (g). Checks CHK-M7-050 to -057 and plant CHK-M7-334 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_structure.py`. It runs `parse_bit` and then `check` only on a tree, the SR §4 order. Implementation: `manager/bitscan_manager/services/importer/structure.py` (impl report `work/reports/TASK-143-impl.md`).

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | L | `pytest -q tests/test_bit_structure.py` | 253/253 passed, 0 failed, 0 errors, 0 skipped |
| clean | W | `CI=true pytest -q tests/test_bit_structure.py` | 253/253 passed, 0 skipped |
| dependents | L, W | `pytest -q tests/test_bit_parse.py tests/test_bit_fixtures.py` | 276/276, 227/227 passed |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy: no issues in 272 files |

L and W are as in `work/reports/TASK-141-test.md`.

Fixture note: `bit002/miscased-policyName.bit` and `miscased-plugin.bit` had manifest lines [2], which is the header comment line. The builder flagged it; I confirmed it and reported it to tester-m7, who fixed the generator. The rows are now [3, 4] and [10, 11]. The test asserts both findings of each file (missing at the container line, then unknown at the element's line) and that the manifest now agrees.

#### Acceptance criteria (tasks.md TASK-143)

| Criterion | Check | Result |
| --- | --- | --- |
| SR §1.1 tree gives a `ParsedPolicy` with the raw values and their lines | CHK-M7-050 | PASS: every field's text, start-tag line (from the text) and #105 (g) path; `@formatVersion` and `Execute/@timeout` at their element's line. Values are raw (`"  ENABLED\n"`, `" EQUALS "` untrimmed); all 15 valid and 75 content fixtures pass the structure; plugins in document order with a 1-based index; frozen |
| Each REQ-151 (2) fixture tree gets BIT002 at the right line and path, and no `ParsedPolicy` | CHK-M7-051 to -053 | PASS: all 50 `bit002/` fixtures give only BIT002, `parsed` None, the first finding on a manifest line, findings sorted by line. Built from the SR example: each of the 8 required leaves missing (one BIT002 at the parent's line, path of the missing element); `Family` and `PluginsGroups` missing; each of 10 elements duplicated (BIT002 at the second); a second `Family` (#10); each of 9 adjacent pairs swapped; 5 mis-cased names and 3 mis-cased roots (no attributes); wrong root (one finding); empty, self-closing and comment-only `PluginsGroups` (#16); unknown elements in 4 containers at their lines; 11 unknown attributes (incl. `Timeout`, `FormatVersion`, `xml:lang`); non-whitespace text in 4 containers incl. CDATA `x` and `&#160;` (#105 (d)); a child in each of 9 leaves; 4 PI places, with lines; `xml:`-prefixed element |
| Whitespace and comments between elements ignored | CHK-M7-053, -057 | PASS: CR LF, tab, comment and whitespace-only CDATA in a container give no finding |
| Namespaced documents: one BIT002, no second report (main's ask on TASK-141 change 1) | CHK-M7-053 | PASS: `xmlns` on the root, `xmlns:b` on a leaf and `xmlns=""` each give exactly one BIT002 from the parser; `check` never runs on them |
| `formatVersion` `1.1` gets BIT016 | CHK-M7-055 | PASS: `1.1`, `1.00`, empty, `2.0`, ` 1.0`, `1.0 `, `1` each give one BIT016 at line 2, `Policy/@formatVersion`, **with** a `ParsedPolicy` (SR §4: only BIT001/BIT002 stop the content rules). Absent gives `format_version` None; `1.0` passes. The 4 `content/bit016-*` fixtures match their manifest line and element |
| A missing `Operator` gives a `ParsedPolicy` with that field marked missing and no BIT002 (#2) | CHK-M7-054 | PASS: plugin 2 of 3 missing `Operator`, or `ExpectedResult`, or both; only that field is None. `bit010-missing` and `bit011-missing` give no finding. An `ExpectedResult` placed before `Operator` is still BIT002 |
| BIT002 masks BIT003, BIT016, BIT102; BIT001 stops before the structure check | CHK-M7-056 | PASS: `plus-bit003`, `plus-bit016`, `plus-bit102` give only BIT002; a BIT002 fault with `formatVersion="9"` gives only BIT002; a not-well-formed file gives only BIT001 |
| Comments never part of a value | CHK-M7-057 | PASS: comments inside `PolicyName` and between CDATA parts of `Execute` are absent from every value; `valid/comments.bit` |
| Messages (#105 (g)) | — | PASS: a 300-character unknown name is quoted cut to 64 characters, the message stays under 160, and the element is the container path. A bad attribute on plugin 3's `Execute` gives `Policy/PluginsGroups/Plugin[3]/Execute…` at that line |

#### Plants (throwaway copies `%TEMP%\m7b-mut\<id>`, copy imported first through `PYTHONPATH`, asserted)

Control copy: ruff clean; `pytest tests/test_bit_structure.py` green.

| Plant | Change | Red tests |
| --- | --- | --- |
| CHK-M7-334 | a BIT002 other than "missing" still returns a `ParsedPolicy` (content rules would run) | `test_bit002_fixture_…` (attr-on-leaf, child-in-leaf, …) and every `parsed is None` row for those faults |
| extra | order check removed | `order-*` fixtures, swap rows |
| extra | duplicates allowed | `duplicate-*` fixtures, duplicate rows |
| extra | `PluginDescription` optional | missing-PluginDescription fixture and row |
| extra | `Operator` no longer optional | `bit010-missing`, missing-operator-plus-faults, #2 rows |
| extra | empty `PluginsGroups` allowed | empty / self-closing fixtures and rows, miscased-plugin |
| extra | container text check uses `str.strip()` (Unicode) | the `&#160;` row |
| extra | unknown attributes on `Plugin` allowed | unknown-attr-plugin fixture and row |
| extra | children in leaves allowed | child-in-leaf fixture and 9 rows |
| extra | first PI ignored | PI fixtures and rows |
| extra | root name compared case-insensitively | survived at first: the root's `formatVersion` attribute then failed as unknown, masking it. I added `test_miscased_root_without_attributes_is_bit002` (3 params), and the plant is now red |
| extra | BIT016 on a stripped value | ` 1.0`, `1.0 ` rows |
| extra | BIT016 returns no `ParsedPolicy` | the 4 bit016 fixtures through the content-fixture test, `test_bit016_fixtures` |
| extra | unknown children of `PluginsGroups` ignored | miscased-plugin, `<Group/>` row |

All 15 plants are red (one after the added test).

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-050 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "sr_example or raw or valid_and_content or frozen or document_order"` | PASS | raw values, lines and paths; 90 fixtures pass | 2026-10-27 |
| CHK-M7-051 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "missing_required or missing_container"` | PASS | 10 rows, BIT002 at the parent's line with the path | 2026-10-27 |
| CHK-M7-052 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "duplicate or swap or second_family"` | PASS | 10 + 9 + 1 rows | 2026-10-27 |
| CHK-M7-053 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "bit002_fixture or case or root or empty_plugins or unknown or text or leaf or processing or namespace or xml_prefixed"` | PASS | all 50 bit002 fixtures; namespaces one BIT002 | 2026-10-27 |
| CHK-M7-054 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "missing_operator or missing_both or missing_fixtures or expected_before"` | PASS | field None, no BIT002 | 2026-10-27 |
| CHK-M7-055 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "format_version or bit016"` | PASS | 7 values BIT016 with ParsedPolicy; absent / 1.0 pass | 2026-10-27 |
| CHK-M7-056 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k "masks or only_bit002 or bit001_stops"` | PASS | only BIT002 / only BIT001 | 2026-10-27 |
| CHK-M7-057 | CODE | L, W | `pytest -q tests/test_bit_structure.py -k comments` | PASS | comments never in a value | 2026-10-27 |
| CHK-M7-334 | CODE | L | plant: ParsedPolicy kept with non-"missing" BIT002 | PASS (red) | bit002 fixture rows failed | 2026-10-27 |

### TASK-144


Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. Spec: SR §2.1–§2.4 (limits, enums, operators), §3.3 (`control_ref`), §3.5 (finding shape), §4 (every failing rule, in document order), §4.1 (codes and severities); answers #2, #13, #16, #17, #105 (e), (g), #109, #110. Checks CHK-M7-065 to -077, plants CHK-M7-326 and -348 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_validate.py`; fixtures `bits/tests/content/`, `bits/tests/valid/`, `bits/tests/manifest.json`. It runs `parse_bit`, then `structure.check`, then `validate` (the SR §4 order). Implementation: `manager/bitscan_manager/services/importer/validate.py` (impl report `work/reports/TASK-144-impl.md`).

#### Runs

Code under test: `git archive 25d41ec manager bits docs` (the merged head; `git status` shows no product change in the worktree) unpacked to `/root/bstest-m7b-head`. The earlier copy `/root/bstest-m7b-base` differs from it only in CR LF line endings (`diff --strip-trailing-cr` is empty for the test files and corpora).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit_validate.py` | 687/687 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `test_bit_fixtures.py`, `test_bit_model.py`, `test_bit_structure.py`, `test_bit_values.py`, `test_bit_parse.py`, `test_bit_fuzz.py`, `test_module_imports.py`, each alone | 227/227, 71/71, 253/253, 144/144, 276/276, 4/4, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W = WSL2 Ubuntu 24.04.5, kernel 6.18.54 WSL2, CPython 3.12.3, pytest 9.1.1, venv `/root/venv-m7b` (`pip install --require-hashes -r manager/requirements-dev.txt` + `--no-deps -e manager`; both lock files are unchanged by the merge), `CI=true`, no containers (pure unit). L = Windows 11, `manager/.venv`, static gates only (no Python tests on Windows). No product module imports `validate.py` yet (TASK-154 is not built), so the dependents are the unit suites that share its fixtures, model and value helpers.

#### Acceptance criteria (tasks.md TASK-144)

| Criterion | Check | Result |
| --- | --- | --- |
| One fixture per code gets exactly that code with its line and path | CHK-M7-065 | PASS: all 90 valid and content fixtures through parse → structure → validate match their manifest codes, lines and elements; every content code (BIT003, 004, 005, 008, 010–014, 016, 017, 101, 103) has a fixture failing only that code |
| SR §1.1 example: no finding and a `Candidate` equal to the expected normalised values | CHK-M7-066 | PASS: no finding; name, name line 3, description, `enabled`, family `CIS Ubuntu 24.04`, format `1.0`, plugin id, trimmed `Execute` and its SHA-256, `equals`, `install ok installed`, timeout 30, `control_ref` |
| REQ-152 (1) bound table | CHK-M7-067, -071 | PASS: each length at its limit accepted, +1 character refused (BIT017; BIT008 for `Execute` at 16,384), counted in characters with multi-byte `é`; whitespace-only `PolicyName`, `FamilyName`, `PluginName`, `Execute` are empty; descriptions of length 0 pass; trimming (#17) happens before the length check and keeps U+00A0; 5,000 plugins accepted, 5,001 BIT017 |
| Enums and case | CHK-M7-068 | PASS: `ENABLED`/`Disabled` stored lowercase, 9 bad statuses BIT003; all 14 operators in any case stored lowercase; 9 bad operators (`equal`, …) BIT010 |
| `PluginId` | CHK-M7-069 | PASS: 7 #109 forms (uppercase, braces, `urn:uuid:`, 32-hex, …) BIT004; a repeated id BIT005 on each later plugin at its `PluginId` line; a padded id is trimmed |
| `@timeout` (REQ-152 (5)) | CHK-M7-070 | PASS: 7 accepted forms incl. `0600` → 600; 18 refused (`0`, `601`, `30s`, `1.5`, `-1`, `+5`, ` 30`, `30 `, empty, …) BIT017 at `…/Execute/@timeout`; absent → 60 |
| Missing `Operator` / `ExpectedResult` (#2) | CHK-M7-072 | PASS: missing `Operator` in plugin 2 gives BIT010 for `Plugin[2]` plus the file's other faults and no BIT014; missing `ExpectedResult` gives BIT011 |
| BIT012, BIT013, BIT014 | CHK-M7-073 | PASS: 66 numeric rows (#13) for each of the 6 numeric operators, 36 passing; `regex` and `not_regex` refuse `(?=x)`, `(?!x)y`, `(a)\1`, `[`, lookbehind (RE2); BIT014 both directions incl. `empty` with U+00A0 |
| A file with three faults gets all three in line order and no `Candidate` | CHK-M7-074 | PASS: `three-faults.bit` → BIT003, BIT004, BIT012 at lines 6, 14, 25, no `Candidate`; a many-fault file sorted by line; same-line findings keep rule order; every fixture's findings sorted |
| Warnings have Warn severity and never reject | CHK-M7-075 | PASS: `warnings-only.bit` gives BIT101 and BIT103 with Warn severity, `rejects` false, and a `Candidate` (`control_ref` None and a 31-character ref); a warning is listed with an error |
| Messages (#105 (g)) | CHK-M7-076 | PASS: a 5,000-character value is never quoted whole (at most 64 characters), a 16,384-character `Execute` never appears, C0 and DEL escaped; every finding serialises to exactly 4 keys |
| No retired code | CHK-M7-077 | PASS: 180 rows (90 fixtures × 2 views), no BIT006, 009, 018–020 |
| `RuleKeys` whenever the structure passed; `Candidate` only with no Reject finding (`work/plans/TASK-151.md` §2) | — | PASS: `RuleKeys` built on a rejected file; `policy_name` None when invalid, line kept; one `RuleId` per valid distinct id; `Execute` and its SHA-256 trimmed; result frozen; input not mutated |
| G1: no `import re` in `validate.py` | CHK-M7-348 | PASS: AST test plus ruff ban |

#### Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first through `PYTHONPATH`, asserted; runner `%TEMP%\m7b-plants\run_plants.py`, definitions `plants_144.json`, `plants_144b.json`)

Control copy (`CTRL-144`, no-op change): ruff clean; `pytest tests/test_bit_validate.py` green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-326 | BIT013 checked for `regex` only, not `not_regex` | `test_regex_operators_need_an_re2_pattern[(?=x)-not_regex]`, `bit013-bracket`, `bit013-lookbehind` fixtures |
| CHK-M7-348 | `import re` at the top of `validate.py` | ruff rc=1 (banned import), collection error |
| CHK-M7-348b | `import re` after `import hashlib` (module still imports) | ruff rc=1; `test_validate_module_imports_no_re` |
| P144-len-off-by-one | length upper bound `high + 1` | `bit017-*-over-limit` fixtures, `test_rule_keys_policy_name_none_when_invalid` |
| P144-bytes | length counted in UTF-8 bytes | `*-at-limit` fixtures, `test_length_at_limit_…[ExpectedResult]` |
| P144-no-trim | value not trimmed before the length check | `bit014-regex-whitespace`, `bit017-*-whitespace`, `test_same_line_findings_keep_rule_order` |
| P144-unicode-trim | `str.strip()` (Unicode) instead of the #17 trim | `test_nbsp_kept_and_unicode_round_trips`, `test_trimmed_before_the_length_check`, `test_bit014_both_directions[empty-\xa0]` |
| P144-execute-limit | `Execute` bound 16,385 | `bit008-too-long`, `test_execute_bound_16384` |
| P144-status-case | `PolicyStatus` compared case-sensitively | `valid/disabled.bit`, `valid/mixed-case-values.bit`, `test_policy_status_any_case…[ENABLED]` |
| P144-bit005-off | duplicate ids allowed | `bit005-duplicate-id`, `test_duplicate_id_bit005_on_each_later_use` |
| P144-timeout-trim | `@timeout` trimmed | `bit017-timeout-space30`, `test_timeout_refused_is_bit017[ 30]`, `[30 ]` |
| P144-timeout-range | lower bound 0 | `bit017-timeout-0`, `test_timeout_refused_is_bit017[0]`, `[00]` |
| P144-timeout-default | default 30 | `test_timeout_absent_is_60` |
| P144-bit014-flip | BIT014 only for presence operators | `bit014-equals-empty`, `test_bit014_both_directions[equals-]` |
| P144-bit012-off | BIT012 for the first 3 numeric operators only | `bit012-ge`, `-le`, `-lt` fixtures |
| P144-warn-reject | `Candidate` only with no finding at all (warnings reject) | `test_warnings_only_file_has_a_candidate`, `test_control_ref_warnings` |
| P144-candidate-always | `Candidate` built even with Reject findings | `test_rule_keys_built_even_when_rejected`, `test_bad_policy_status_is_bit003` |
| P144-unsorted | findings reversed, not sorted | `test_three_faults_on_three_lines_in_order`, `test_many_faults_…`, `test_duplicate_id_…` |
| P144-sha-untrimmed | SHA-256 of the untrimmed `Execute` | `test_sr_example_has_no_finding_and_the_expected_candidate`, `test_candidate_execute_and_sha_are_trimmed` |
| P144-operator-case | operator stored as written | `test_operator_any_case_stored_lowercase`, `valid/mixed-case-values.bit` |
| P144-bit011-off | missing `ExpectedResult` reported as BIT014 | `bit011-missing`, `test_missing_expected_result_is_bit011` |
| P144-ref-warn-off | BIT103 never raised | `bit103-long-control-ref`, `valid/warnings-only.bit` |
| P144-ruleids-dup | a `RuleId` added for an invalid id | `test_bad_plugin_id_is_bit004` (7 rows) |
| P144-quote-whole | the whole value quoted with `repr` | `test_messages_quote_at_most_64_characters` |

All 24 plants are red; the control is green.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-065 | CODE | W | `pytest -q tests/test_bit_validate.py -k "fixture_codes_lines_and_paths or every_content_code_has_a_fixture"` | PASS | 91/91; 90 fixtures match manifest code, line, element | 2026-10-28 |
| CHK-M7-066 | CODE | W | `pytest -q tests/test_bit_validate.py -k sr_example` | PASS | 1/1; no finding, expected `Candidate` | 2026-10-28 |
| CHK-M7-067 | CODE | W | `pytest -q tests/test_bit_validate.py -k "length_at_limit or whitespace_only or execute_bound or trimmed_before or nbsp"` | PASS | 25/25; at limit pass, +1 refused, characters not bytes | 2026-10-28 |
| CHK-M7-068 | CODE | W | `pytest -q tests/test_bit_validate.py -k "policy_status or operator_any_case or bad_operator or all_14"` | PASS | 28/28 | 2026-10-28 |
| CHK-M7-069 | CODE | W | `pytest -q tests/test_bit_validate.py -k "bad_plugin_id or duplicate_id or padded_plugin_id"` | PASS | 9/9; BIT004 forms, BIT005 on the later plugin | 2026-10-28 |
| CHK-M7-070 | CODE | W | `pytest -q tests/test_bit_validate.py -k timeout` | PASS | 66/66; `0600` → 600, absent → 60 | 2026-10-28 |
| CHK-M7-071 | CODE | W | `pytest -q tests/test_bit_validate.py -k "5000 or 5001"` | PASS | 2/2 | 2026-10-28 |
| CHK-M7-072 | CODE | W | `pytest -q tests/test_bit_validate.py -k "missing_operator or missing_expected"` | PASS | 3/3; BIT010 / BIT011, no BIT014 | 2026-10-28 |
| CHK-M7-073 | CODE | W | `pytest -q tests/test_bit_validate.py -k "numeric_operator or regex_operators or valid_re2 or bit014"` | PASS | 142/142 | 2026-10-28 |
| CHK-M7-074 | CODE | W | `pytest -q tests/test_bit_validate.py -k "three_faults or many_faults or sorted_by_line or same_line"` | PASS | 93/93; lines 6, 14, 25 | 2026-10-28 |
| CHK-M7-075 | CODE | W | `pytest -q tests/test_bit_validate.py -k "warnings_only or warning_listed or control_ref_warnings"` | PASS | 7/7; Warn severity, `Candidate` kept | 2026-10-28 |
| CHK-M7-076 | CODE | W | `pytest -q tests/test_bit_validate.py -k "messages_quote or control_characters or long_execute or four_keys"` | PASS | 93/93 | 2026-10-28 |
| CHK-M7-077 | CODE | W | `pytest -q tests/test_bit_validate.py -k no_retired_code` | PASS | 180/180 | 2026-10-28 |
| CHK-M7-315 (TASK-144 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-326 | CODE | W | plant: BIT013 skipped for `not_regex` | PASS (red) | `not_regex` rows and 2 bit013 fixtures failed | 2026-10-28 |
| CHK-M7-348 | CODE | L, W | plant: `import re` in `validate.py` | PASS (red) | ruff rc=1; `test_validate_module_imports_no_re` failed | 2026-10-28 |

### TASK-145


Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-156. Spec: SR §4.2 ("split into tokens with a POSIX sh lexer"), TS §8.1 (L1244, L1255), §8.3 (the BIT102 lexer unit row); answer #108 (c), (h), (j); design note D2 and `work/plans/TASK-145.md` §5. Token expectations from POSIX XCU §2.3, §2.6.3, §2.7, §2.10. Checks CHK-M7-100, -101, -102, -112; plants CHK-M7-332 (lexer half) and -387 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit102_lexer.py`. Implementation: one task in three files (user ruling 2026-10-27), `shlex_model.py`, `shlex_grammar.py`, `shlex_posix.py` in `manager/bitscan_manager/services/importer/` (impl report `work/reports/TASK-145-impl.md`).

#### Runs

Code under test: `git archive 25d41ec` of `manager`, `bits`, `docs` in `/root/bstest-m7b-head` (no product change in the worktree; the old copy differs only in CR LF).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit102_lexer.py` | 173/173 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `tests/test_bit102.py` (the only consumer, through `bit102.py`); `test_bit_fixtures.py`, `test_bit_model.py`, `test_module_imports.py` | 1160/1160, 227/227, 71/71, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W and L are as in `work/reports/TASK-144-test.md` (WSL2 Ubuntu 24.04.5, CPython 3.12.3, venv `/root/venv-m7b`, `CI=true`; Windows for static gates only).

#### Acceptance criteria (tasks.md TASK-145)

| Criterion | Check | Result |
| --- | --- | --- |
| The REQ-156 (1) table of at least 60 inputs gives the expected tokens | CHK-M7-100 | PASS: 85 table rows (guard: at least 60) give the expected command words, including `echo "rm -rf /"` (one quoted argument), `r''m`, `\rm`, `"r"m` and `r\<newline>m` (the word `rm`), `a;rm`, `a&&rm`, `$(rm x)`, `` `rm x` ``, `<(cat /etc/x)`, `cat <<'EOF'` with a body (data), `cat <<EOF` with `$(id)` in the body (found), `${x:-$(rm y)}` in a here-document (found), `# rm` (comment), `a#b` (a word). Separate tests: 14 redirection rows with descriptor and target (`2>/dev/null`, `>|`, `>>`, `&>`, `2>&1`, `<`, `<>`), assignments before the command, reserved words only in command position (a quoted `"if"` is a word), function names and `for` lists are data, escapes inside double quotes, CR kept literal, line numbers counted |
| Unterminated quotes or substitutions and 9-deep nesting raise the fail-closed error; 8 deep accepted | CHK-M7-101 | PASS: 34 unlexable inputs (unterminated `'`, `"`, `$(`, backtick, `${`, here-document without its end, `)` or `fi` alone, `if x; then y`, `; rm`, NUL, …) raise `ShellSyntaxError` with a line and without quoting the input; 8 nested `$(`, backticks and mixed nesting accepted, 9 refused; `MAX_DEPTH` is 8 and the `depth=` argument counts toward it |
| The module imports nothing that executes | CHK-M7-102 | PASS: AST scan of all three files bans `subprocess`, `os`, `shlex`, `re`, `regex`, `pty`, `ctypes`, `multiprocessing`, `importlib`, `runpy`, `code`, `socket` calls to `eval`/`exec`/`compile`/`__import__`/`open` and the attributes `system`, `popen`, `execv`, `execve`, `spawn`; with `subprocess.Popen` and `os.system` patched to fail, lexing `$(rm -rf /) \`id\` <(cat /etc/shadow) ${x:-$(reboot)}` runs nothing |
| Random strings up to 16,384 characters raise nothing else and finish within 100 ms each | CHK-M7-112 | PASS: Hypothesis, 3,000 shell-piece inputs and 1,000 random texts up to 2,000 characters, 60 repeated units cut to exactly 16,384 characters, plus 10 pathological inputs at the limit (`a;` × 8,192, 2,700 here-document substitutions, 8,000-term arithmetic, …): only `ShellSyntaxError`, each under 100 ms of thread CPU time. The bound helper measures once and, only if that exceeds 100 ms, takes the best of 5, so a GC pause from the test process can't fail it while a super-linear lexer still does |

Over-detection (`[[ ]]`, `(( ))`, `$((`, `time` treated toward rejecting) is accepted by the user's ruling of 2026-10-27 and isn't flagged.

#### Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first, asserted; definitions `%TEMP%\m7b-plants\plants_145_146.json`; each run against `test_bit102_lexer.py` and `test_bit102.py`)

Control copy (`CTRL-145-146`, no-op): ruff clean; both files green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-387 | `$(` recursion dropped (a substitution's script not lexed) | `test_heredoc_quoted_body_is_data_unquoted_is_scanned`; `test_must_reject[echo $(rm x)]`, `[bash -c "$(curl x)"]` |
| CHK-M7-332 (lexer) | `lex` returns an empty script on `ShellSyntaxError` (fail open) | `test_nested_shell_scripts_past_depth_8_fail_closed`, the unlexable rows |
| P145-backtick | backtick script not lexed | `test_8_nested_backticks_accepted_9_refused`; `` echo `rm x` ``, ``sh -c '`id`'`` |
| P145-heredoc-unscanned | unquoted here-document bodies not scanned | `test_heredoc_quoted_body_is_data_unquoted_is_scanned`; `cat <<EOF $(rm -f /etc/x)`, `<<-EOF` |
| P145-heredoc-quoted-scanned | quoted here-document bodies scanned as code | `test_must_pass[cat <<'EOF' … $(rm -rf /)]`, the `<<'EOF'` table row |
| P145-depth9 | `MAX_DEPTH` 9 | `test_max_depth_is_8`, `test_depth_argument_counts`, `test_8_nested_substitutions_accepted_9_refused` |
| P145-dq-noexpand | `$` and backtick inside double quotes not expanded | here-document and `"$(…)"` rows |
| P145-escape-literal | `\x` kept as the two characters | `test_reserved_words_only_in_command_position`; `test_must_reject[\rm x]` |
| P145-reserved-quoted | quoted words taken as reserved words | `test_command_words["if" x]`, `test_reserved_words_only_in_command_position` |
| P145-no-assignments | leading `NAME=value` taken as the command word | `FOO=1 rm x`, `A=1 B=2 rm x` |
| P145-linecont | backslash-newline not removed | `test_command_words[r\<newline>m x]` |
| P145-sq-failopen | unterminated `'` read to the end | `test_fail_closed_error_quotes_no_input`, `test_unlexable_input_…[echo 'abc]`, `test_fail_closed_error_has_the_line` |
| P145-heredoc-eof-open | here-document without its end accepted | `test_unlexable_input_raises_the_fail_closed_error[cat <<EOF]` |
| P145-procsub-dropped | `<( )`/`>( )` kept as a literal | `test_command_words[cat < <(rm x)]`; `cat <(rm x)`, `cat >(rm x)`, `dash -c 'cat <(id)'` |
| P145-param-script | `${…}` scripts dropped | `test_command_words[cat <<EOF ${x:-$(rm y)} EOF]`; every `${x:-$(…)}` context row |

All 15 plants are red; the control is green.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "command_words or table_has or quoted_argument or escaped_and_split or word_boundaries or redirections or assignments or heredoc or reserved or function_names or escapes_inside or digits_not or crlf or lines_are or sr_example"` | PASS | 114/114; 85-row table | 2026-10-28 |
| CHK-M7-101 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "unlexable_input or nested_substitutions or nested_backticks or mixed_nesting or max_depth or depth_argument or fail_closed_error"` | PASS | 45/45; 8 deep accepted, 9 refused | 2026-10-28 |
| CHK-M7-102 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "import_nothing or runs_nothing"` | PASS | 4/4; AST scan of 3 files, nothing executed | 2026-10-28 |
| CHK-M7-112 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "random or long_inputs or pathological"` | PASS | 14/14; only `ShellSyntaxError`, each < 100 ms, up to 16,384 chars | 2026-10-28 |
| CHK-M7-315 (TASK-145 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-332 (lexer) | CODE | W | plant: `lex` fails open | PASS (red) | depth and unlexable rows failed | 2026-10-28 |
| CHK-M7-387 | CODE | W | plant: `$(` recursion dropped | PASS (red) | lexer here-document row and `$(…)` must-reject rows failed | 2026-10-28 |

#### Measurement fix at the M7 gate (tester-m7, 2026-10-28; lead ruling, option (b))

At the M7 gate, `test_pathological_inputs_bounded[seps]` (`"a;" * 8192`) failed against the 100 ms bound (REQ-156 (4)) with 0.103 s, best of five thread-CPU timings, in the G54 batch and again alone. The lexer modules are unchanged since the run above.

**Cause.**
- Inside a pytest test, `sys.gettrace()` and `sys.getprofile()` are None, `sys.monitoring` has no tool registered, and `sys.flags` show no debug or dev mode. No tracer is involved.
- The identical loop measured 55–59 ms inside pytest in one run and 103.5 ms in another, against 56 ms in a plain script. Thread CPU time still scales with core speed and contention on this shared WSL machine (other agents' containers and builds), so the in-process best-of-five has no headroom at 16,384 characters.

**The change (a measurement fix; the 100 ms bound is unchanged).**
- `test_pathological_inputs_bounded` (all ten parameters) still lexes in process for the functional assertions: the right `Script`, or only `ShellSyntaxError`.
- It now times the lexer in a clean `python -I` subprocess of the same venv, importing the tree under test, with no tracer and no test-process heap. It takes the best of 10 thread-CPU timings there and asserts < 100 ms.
- The property tests keep their in-process `_bounded`.

**Evidence.**
- `tests/test_bit102_lexer.py`: **173/173 passed** (W, gate copy).
- A quadratic plant (`len(list(src[:pos]))` per token in `shlex_posix`) → red, 6 of 10 parameters fail under the subprocess timing (`seps`, `args`, `nest8`, `heredoc`, `parens`, `ifs`).

### TASK-146


Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-157, REQ-177, REQ-180. Spec: SR §4.2 (SR L277–L287), §4.1 BIT102, §1.1; TS §3.7 (L505), §8.1 (L1244, L1255), §8.3; answer #108 (a)–(k); lead rulings 2026-10-27 (apt/apt-get/systemctl verbs anywhere among the literal arguments; `<>` is output; `env -S` lexed); user ruling 2026-10-27 (a non-literal command word passes; only its nested scripts are checked); lead ruling 2026-10-28 (c) on `stdbuf`. Checks CHK-M7-115 to -121; plants CHK-M7-327 to -332 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit102.py`; corpora `bits/tests/bit102/must_reject.json` (149 cases) and `must_pass.json` (96 cases). Implementation: `manager/bitscan_manager/services/importer/bit102.py` (impl report `work/reports/TASK-146-impl.md`).

**This report covers revision 1 and is kept for the record. Its review waits for revision 2** (the BIT102 gaps closed by the user on 2026-10-27, decisions "BIT102 gaps closed" and "TASK-146 r2 shape rulings"), which gets its own section below when it is tested.

#### Rounds

| Round | Result | Note |
| --- | --- | --- |
| 1 (2026-10-27) | FAIL | #108 (d) bypass: in a wrapper's short-option cluster whose last letter takes a value, the value hid the command (`sudo -iu root rm x` took `root` as the command). Handed to impl-manager-m7b with the failing parameters of `test_wrapper_option_clusters_do_not_hide_the_command`. |
| r1 (2026-10-27) | PASS | `_option()` reads wrapper options as getopt does (TASK-146-impl.md "Revision 1"). One parameter, `stdbuf -io L rm x`, was disputed; the lead closed it on 2026-10-28 (c): getopt reads `-io` as `-i o` and `rm` never runs, so it isn't expected to be flagged. The test uses `stdbuf -i0 -oL rm x`, which gets BIT102 naming `rm`. |

#### Runs (revision 1)

Code under test: `git archive 25d41ec` of `manager`, `bits`, `docs` in `/root/bstest-m7b-head` (no product change in the worktree; the old copy differs only in CR LF).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit102.py` | 1160/1160 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `test_bit102_lexer.py` (shared lexer), `test_bit_validate.py` (imports `check_execute`), `test_bit_fixtures.py`, `test_bit_model.py`, `test_module_imports.py` | 173/173, 687/687, 227/227, 71/71, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W and L are as in `work/reports/TASK-144-test.md`.

#### Acceptance criteria (tasks.md TASK-146)

| Criterion | Check | Result |
| --- | --- | --- |
| Every case of the REQ-157 (1) must-reject corpus gets BIT102 with the offending token in its message | CHK-M7-115 | PASS: 149/149 cases; each finding is BIT102, Reject, at the caller's line and element, and one message holds the corpus token |
| … also in each context | CHK-M7-116 | PASS: 646 rows, each case marked `contexts` (at least 24) inside 27 contexts: pipeline, `;`, `&&`, `\|\|`, `&`, `( )`, `{ …; }`, `if`, `while`, `until`, `for`, `case`, function body, `$( )`, backticks, `<( )`, `>( )`, `!`, assignment, `"$( )"`, `${x:-$( )}`, unquoted here-document, `bash -c '…'`, `sh -c "…"`, `dash -c '…'`, `sudo`, `env` |
| #108 matching forms | CHK-M7-117 | PASS: 66 rows (`/bin/rm`, `./rm`, `../../bin/rm`, `mkfs.ext4`, `mkfs.xfs`, `env`/`env -i`/`env -u`/`env --`, `busybox`, `sudo` with `-u`, `-uroot`, `--user=`, `doas`, `command`, `command -p`, `builtin eval`, `nice`, `nohup`, `setsid`, `ionice`, `stdbuf`, `timeout` with `-s`/`-k`, `chroot`, stacked wrappers, `FOO=1`, the `sed -i` forms, apt/dpkg/systemctl with options) plus 11 r1 option-cluster rows (`sudo -iu root`, `env -iu FOO`, `timeout -vk 5 10`, `ionice -tc 3`, `doas -nu root`, `nice -n5`, `stdbuf -i0 -oL`, `stdbuf -eL -o L`, …), each naming its token |
| Redirections (#108 (i)) | CHK-M7-118 | PASS: 25 rejected (`> /etc/x`, `>/tmp/../etc/x`, `> "$F"`, `> $HOME/x`, `> /tmpx`, `> /tmp`, `&> /var/x`, `>& /var/x`, `>>`, `>\|`, `2>`, `&>>`, `<>/etc/x`, `/dev/sda`, `/dev/fd/1`, `/tmp/$(id -u)`, `` /tmp/`id` ``, `/dev/null/../x`, …); 18 pass (`/dev/null`, `/dev/stdout`, `/dev/stderr`, `/tmp/out`, `2>&1`, `>&2`, `>&-`, `<>/tmp/x`, input redirections, here-strings) |
| Code-running forms (#108 (f)) | CHK-M7-119 | PASS: 36 rows (`.`, `source`, `eval`, `exec`, `xargs`, `find -exec/-execdir/-ok/-okdir`, `sh ./x.sh`, `bash x`, `sh -s`, bare `sh`, `echo x \| sh`, `sh < x`, `bash -x x.sh`, `bash -c "$(curl x)"`, ``sh -c '`id`'``, `dash -c 'cat <(id)'`, a here-document substitution in `bash -c`, nested `-c`, `env -S` in three spellings); 10 rows of substitutions in data words (`for`, `case`, `select`) and input-redirection targets |
| No case of the must-pass corpus (the SR §1.1 `Execute` included) gets BIT102 | CHK-M7-120 | PASS: 96 corpus cases (the first is the SR §1.1 `Execute`, extracted from the spec block); all 32 `Execute`s of `bits/samples/` read through the real parser; 47 more rows: the lead's false-positive guards (`systemctl status`, `is-enabled`, `show -p`, a verb inside a unit name, `apt list --installed`, `apt-cache policy`, `grep install`), the user's non-literal forms, SR §4.2 read-only uses; `echo "rm"`, `echo firmware` pass while `r''m x` and `\rm x` are rejected (not a substring search) |
| Unlexable input fails closed | CHK-M7-121 | PASS: 13 unlexable inputs give exactly one BIT102 "cannot be checked"; 10 nested `sh -c` levels (past depth 8) are rejected |
| Messages | — | PASS: the token is quoted as written (`r''m`, `"rm"` via `sudo`); a 16,000-character target is never quoted whole and the message stays under 300 characters; C0 escaped; one finding per distinct offence in source order; the caller's line and element are used; Hypothesis, 3,000 inputs: `check_execute` never raises, each under 1 s |

**Accepted residual risk (user ruling 2026-10-27, to be carried into the M7 PR):** a non-literal command word passes BIT102, so `c=rm; "$c" -rf /` is not caught. The must-pass rows `"$c" x`, `${x} y`, `$(echo rm) x`, `$'\x72m' x`, `sh -c "$s"` and `sudo "$c" x` pin that ruling, and `$(rm -rf /) x`, `"$(rm x)" y` and `${x:-$(rm y)} z` prove the nested scripts are still checked. BIT102 is the safety net; the runner sandbox (TS §3.7, M10) is the control.

#### Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first, asserted; definitions `%TEMP%\m7b-plants\plants_145_146.json`)

Control copy (`CTRL-145-146`, no-op): ruff clean; `test_bit102.py` and `test_bit102_lexer.py` green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-327 | substring search over the forbidden words instead of the lexer | `test_not_a_substring_search` (`echo "rm"`), the `sed -i` must-reject rows |
| CHK-M7-328 | path-qualified names not reduced | `/bin/rm`, `/usr/bin/rm`, `./rm`, `/bin/sh -c 'eval x'` |
| CHK-M7-329 (nested) | substitution scripts not checked | `echo $(rm x)`, `` echo `rm x` ``, `cat <(rm x)`, `cat <&$(rm x)` |
| CHK-M7-329 (shell) | `-c` scripts not checked | `test_nested_shell_scripts_past_depth_8_fail_closed`, `sh -c 'rm x'` rows |
| CHK-M7-330 | `WRAPPERS` empty | `env rm x`, `env -i rm x`, `test_message_quotes_the_token_as_written` |
| CHK-M7-331 (any) | every redirect target allowed | `> /etc/x`, `>> /etc/x`, `>\| /etc/x`, `test_message_bounded_and_escaped` |
| CHK-M7-331 (dotdot) | `..` allowed under `/tmp/` | `>/tmp/../etc/x`, `> /tmp/a/../../etc/x` |
| CHK-M7-331 (expansion) | a non-literal target judged by its raw text | `> /tmp/$(id -u)`, `` > /tmp/`id` `` |
| CHK-M7-332 (bit102) | `ShellSyntaxError` branch returns `[]` | the 13 unlexable rows, 9 nested `$(` |
| P146-cluster-r0 | r1 undone: only the first letter of a cluster read | the r1 option-cluster rows (`sudo -iu root`, `doas -nu root`, …) |
| P146-sed | `sed` cluster scan returns nothing | every `sed -i` form, `sudo sed -i` |
| P146-verb-first-only | find actions only at the first argument | `find / -name x -exec …`, `-execdir`, `-ok`, `-okdir` |
| P146-shell-noc | a shell without `-c` allowed | `sh ./x.sh`, `bash /tmp/x`, `dash x.sh`, `bash -x x.sh` |
| P146-subst-in-c | substitution in a `-c` script word allowed | `bash -c "$(curl x)"` |
| P146-dpkg-eq | `--opt=value` not split | `dpkg --purge=x`, `--remove=x`, `--install=x.deb` |
| P146-find | `-execdir` and `-okdir` not refused | those rows |
| P146-mkfs | `mkfs.*` not matched | `mkfs.ext4`, `mkfs.xfs`, `/sbin/mkfs.ext4` |
| P146-envS | `env -S` not lexed | `env -S 'rm x'`, `-S'rm x'`, `--split-string='rm x'` |
| P146-heredoc-in-c | here-document substitution in a `-c` script allowed | `bash -c 'cat <<EOF $(id) EOF'` |
| P146-datawords | data words not walked | `for f in $(rm x)`, `select`, `case` rows |
| P146-redirect-target-scripts | input-redirect target scripts not walked | `cat < <(rm x)`, `cat <<<$(rm x)`, `cat < "$(rm x)"`, `cat <&$(rm x)` |
| P146-ltgt-input | `<>` treated as input | `cat <>/etc/x` |
| P146-nonliteral-reject | a non-literal command word refused (against the user's ruling) | must-pass `"$c" x`, `${x} y`, `$(echo rm) x`, `sudo "$c" x` |

All 23 plants are red; the control is green.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 | CODE | W | `pytest -q tests/test_bit102.py -k "must_reject and not every_context or corpora_sizes"` | PASS | 150/150; 149 cases with token | 2026-10-28 |
| CHK-M7-116 | CODE | W | `pytest -q tests/test_bit102.py -k "every_context or context_count"` | PASS | 647/647; 27 contexts | 2026-10-28 |
| CHK-M7-117 | CODE | W | `pytest -q tests/test_bit102.py -k "108_matching or wrapper_option_clusters"` | PASS | 77/77 | 2026-10-28 |
| CHK-M7-118 | CODE | W | `pytest -q tests/test_bit102.py -k redirections` | PASS | 43/43; 25 rejected, 18 pass | 2026-10-28 |
| CHK-M7-119 | CODE | W | `pytest -q tests/test_bit102.py -k "code_running or data_words"` | PASS | 46/46 | 2026-10-28 |
| CHK-M7-120 | CODE | W | `pytest -q tests/test_bit102.py -k "must_pass or sample_execute or sr_example or read_only or not_a_substring"` | PASS | 177/177; SR §1.1 and 32 sample `Execute`s | 2026-10-28 |
| CHK-M7-121 | CODE | W | `pytest -q tests/test_bit102.py -k "unlexable or past_depth_8"` | PASS | 14/14 | 2026-10-28 |
| CHK-M7-315 (TASK-146 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-327 | CODE | W | plant: substring search | PASS (red) | `test_not_a_substring_search` failed | 2026-10-28 |
| CHK-M7-328 | CODE | W | plant: `/bin/rm` not reduced | PASS (red) | path rows failed | 2026-10-28 |
| CHK-M7-329 | CODE | W | plants: nested and `-c` scripts not checked | PASS (red) | both plants red | 2026-10-28 |
| CHK-M7-330 | CODE | W | plant: wrappers not unwrapped | PASS (red) | `env rm x` rows failed | 2026-10-28 |
| CHK-M7-331 | CODE | W | plants: any target, `..`, non-literal target allowed | PASS (red) | all three red | 2026-10-28 |
| CHK-M7-332 | CODE | W | plants: lexer errors pass (bit102 and lexer halves) | PASS (red) | unlexable and depth rows failed | 2026-10-28 |

#### Revision 2: NOT RUN (stopped by a safety check)

Tester: tester-m7c, 2026-10-28, worktree `Bitscan-m7` (branch `m7-catalog`). This was the single attempt allowed by the decisions row "Overnight pre-authorisation" (1).

**What happened:** while I was still reading context (step 0, before any test was written, run or planted), a safety classifier stopped my response and withheld the rest of it. The last tool call that finished was a read-only search of `work/reports/TASK-144-test.md` for its description of the W/L environments. As instructed, I stopped at once: no retry and no rewording.

**State left behind:** apart from this section, no file was changed. `manager/tests/test_bit102.py`, `bits/tests/bit102/must_reject.json` and `must_pass.json` have no diff, so tester-m7b left no partial r2 edits. `tests/m7/test-plan.md` and `tests/m7/report.md` are unchanged. No WSL copy was made, no tests were run and no plants were made.

**Verdict:** none. TASK-146 r2 TEST stays open, and the item waits for the user (decisions "Overnight pre-authorisation" (1)).

##### Attempt 2: NOT RUN (tester-m7d, 2026-10-28, user-requested "Run task-146 r2")

**What happened:** a safety classifier stopped my response while I was still reading context (step 0). Nothing had been written, run or planted. The tool calls that finished were all read-only:
- `.claude/rules/testing.md`, `manager/importer.md` and the BIT102 part of `manager/bit-format.md`;
- the TASK-146 rows in `work/tasks.md`, and the BIT102 rows in `work/decisions.md` ("BIT102 gaps closed", "TASK-146 r2 shape rulings", "TASK-146 r2 rulings", "TASK-146 r2 vs the remote approval");
- TP-M7-08 and the mutation table in `tests/m7/test-plan.md`;
- `work/reports/TASK-146-impl.md`, this report, `manager/tests/test_bit102.py`, the start and end of both corpora;
- the three product files `bit102.py`, `bit102_wrappers.py` and `bit102_braces.py`.

The stop came after those reads, before I drafted any r2 test row. As the brief says, I stopped at once: no retry and no rewording.

**State left behind:** apart from this subsection, no file was changed. `manager/tests/test_bit102.py`, `bits/tests/bit102/must_reject.json`, `must_pass.json`, `tests/m7/test-plan.md` and `tests/m7/report.md` have no r2 edits. No CHK id was assigned, so the next r2 id is still CHK-M7-388. No WSL copy was made, no test or gate was run, and no plant was made.

**Verdict:** none. TASK-146 r2 TEST stays open and goes back to `main` and the user.

#### Revision 2 deferred; r1 re-confirmed at the M7 gate (tester-m7, 2026-10-29)

The user deferred TASK-146 r2 (decisions "TASK-146 r2 deferred"). `bit102.py` is back to r1, byte-identical to c6b7e13 (sha256 `279291cf…`). `bit102_wrappers.py` and `bit102_braces.py` are removed, and the r2 copies are saved outside the tree.

On a fresh copy (`/root/bstest-m7-r1`, `CI=true`, `PYTHONPATH` pinned, `-n 2`):
- `test_bit102.py` 1,160/1,160 (as above), `test_bit102_lexer.py` 173/173, `test_bit_validate.py` 687/687, `test_bit_fixtures.py` 227/227;
- the pipeline's CHK-M7-191 rows, now with all six BIT102 fixtures, 150/150;
- G59 50/50.

That is **2,447/2,447 passed**, 0 skipped. Whole-tree ruff, format and `mypy --strict` are clean (310 files), with no import of the removed modules. The r1 verdict above stands: **PASS**.
### TASK-151


Tester: tester-m7, 2026-10-27. REQ-158, REQ-159, REQ-177; SR §3.1 to §3.6, §4.1 BIT007 and BIT015; TS §4.1 L519 to L524, §4.3 L548 to L550; #14, #15, #21, #100 (a), #104, #106; design note D3; plan `work/plans/TASK-151.md` §6 rows 1 to 12. Files under test: `bm/services/importer/store.py` and `store_decide.py`. Test file: `manager/tests/test_import_store_pg.py` (32 tests), as `bitscan_app` on a database of its own; `Candidate` and `RuleKeys` built by the test.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t151, `CI=true`, `-n 0`) | `pytest tests/test_import_store_pg.py` (with the TASK-153 r2 files) | store file 31/32 passed, 1 failed: `test_106_y_in_another_existing_server_file_is_bit007` (my test bug, below) |
| r1 (m7t-t151b) | that node id after the fix | 1/1 passed |
| r2 (m7t-t151c) | `test_fault_after_the_third_plugin_leaves_the_catalog_unchanged` after a second test fix (below) | 2/2 passed |
| static (L) | ruff, ruff format, mypy (CI form) | clean, 269 files |

Test bugs (mine, both fixed; lead confirmed the first, 2026-10-27):
1. #106 (a). The file `a.bit` held X and now names Y, while Y lives in an existing `b.bit`. I expected only BIT007, but the store also reports BIT015 for X's plugin. That is right: X is live, still lists the plugin, and is not displaced because nothing moves, and every failing rule is reported (SR L250).
2. The fault wrapper raised on its first call, so the commit-per-plugin plant (CHK-M7-338) stayed green. The fault now fires after 3 plugin rows counted across calls, and the catalog is read from another connection; 338 is red.

#### Report rows (tests/m7/report.md format)

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

#### Revision 2 (#100 (a) widened by the user, 2026-10-27: `ChangedExecute.reason` ∈ new, changed, reactivated)

Updated rows: the changed-Execute assertions of CHK-M7-173 (`new`), -176 (`changed`, and the mixed file's two `new`), and -178 (the revival: both plugins `reactivated`). `test_revival_changed_executes_pinned` is flipped to `test_revival_changed_executes_reactivated` (a revived `cat /etc/shadow` plugin is carried as `reactivated`). New rows: `test_a_retired_plugin_listed_again_is_reactivated` (an active, unchanged plugin stays out) and `test_106_takeover_from_the_displaced_policy_is_not_reactivated`. In (b), Y takes over X's active plugins and none is carried, because the prior state is read before the displaced delete. In (c), the revive of Y carries the listed plugin as `reactivated`.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-173..184-r2 | APP | W | `pytest -n 2 tests/test_import_store_pg.py` (with the TASK-153 r3 files, m7t-t151r2) | PASS | 34/34 passed (the run: 166/166) | 2026-10-27 |
| CHK-M7-151-rv | APP | W | plant: a revive no longer marks plugins reactivated | PASS (red) | 1 failed (#106 (c)) | 2026-10-27 |
| CHK-M7-151-rl | APP | W | plant: a re-listed retired plugin not reactivated | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-151-or | APP | W | plant: prior state read after the displaced delete | PASS (red) | 1 failed (#106 (b): X's plugins appear reactivated) | 2026-10-27 |

Verdict after revision 2: **PASS**.

#### Revision 3 (crash-window ruling, user and lead 2026-10-27; plan §3.3 r3)

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

### TASK-152


Tester: tester-m7, 2026-10-27. REQ-167 (1), (2), (5), (6), REQ-161 (2); TS §4.3 L550, §4.1 L526, §8.4 L1290; #98 (e), #101. File under test: `bm/services/importer/delete.py` (unchanged since round 1). Test file: `manager/tests/test_policy_delete_pg.py` (11 tests), PostgreSQL as `bitscan_app` with a temporary bits folder.

#### Round 1: FAIL

4/11 passed, 7 failed with `AuditError: audit append needs a transaction, not autocommit`. The pinned session's transaction left `conn.autocommit` True, so `PgAuditRepo` refused the delete alert. This is a TASK-147 defect, fixed in TASK-147 revision 2 (session transactions run with autocommit off). `delete.py` did not change.

#### Round 2

| Run | Command | Count |
| --- | --- | --- |
| W (label m7t-t147r2, `CI=true`, `-n 2`) | `pytest tests/test_policy_delete_pg.py` (with the TASK-147 r2 files) | 11/11 passed (the run: 77/77), 0 failed, 0 skipped |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-224 | APP | W | round 1 (m7t-t152b) | FAIL | 4/11; `AuditError` (TASK-147 defect) | 2026-10-27 |
| CHK-M7-224-r2 | APP | W | round 2 (m7t-t147r2) | PASS | REQ-167 (1) through `delete_policy`: owner-written jobs (`queued`, `dispatched`, `running`) and two schedules; only the queued job is cancelled; both schedules disabled; `deleted_at` = the clock, `source_file` `deleted/<id>`; plugins retired; `uploaded/policy-<id>.bit` removed and another upload kept; exactly one `policy.delete` entry (actor `user:1`, `alert = true`, kind `policy_deleted`, `reason` "deleted through the API", the old `source_file`); `bitscan_alerts_total{policy_deleted}` +1; the catalog lock free afterwards. (2) A server-folder policy raises `PolicyManagedOnServer` (its id), with nothing changed (6 table checksums), no alert, its file untouched. Unknown → `PolicyNotFound`; already deleted → `PolicyAlreadyDeleted`, nothing changed. (5) A new policy claims the deleted policy's plugin with no BIT015. (6) The `policy` row count is unchanged | 2026-10-27 |
| CHK-M7-225-r2 | APP | W | round 2 | PASS | a fault before commit (`emit` raising) leaves the row, the checksums, the counter and the upload file as they were, and frees the lock; the core inside a caller's transaction that later raises rolls back with it (checksums, counter); the core without the refusal deletes a server policy with reason "file removed", actor `system`, and never removes its file; a delete waits while another holder has the catalog lock (REQ-161 (2)); two racing deletes give one success, one `PolicyAlreadyDeleted` and exactly one alert; `remove_after_commit` removes only `uploaded/policy-<ASCII digits>.bit` (refuses `x.bit`, `uploaded/../x.bit`, a traversal through a policy name, Arabic-Indic digits, `policy-.bit`, `.tmp-`, `deleted/7`; a symlink is removed without touching its target; a missing file is no error) and logs no path | 2026-10-27 |
| CHK-M7-351 | APP | W | plant: no `emit` (no `policy_deleted`) | PASS (red) | 4 failed | 2026-10-27 |
| CHK-M7-152-s | APP | W | plant: server-folder refusal ignored | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-152-f | APP | W | plant: upload file removed before commit | PASS (red) | 1 failed (fault row: file gone) | 2026-10-27 |
| CHK-M7-356 (152 half) | APP | W | plant: delete without the catalog lock | PASS (red) | 1 failed (did not wait) | 2026-10-27 |
| CHK-M7-152-p | APP | W | plant: path check removed (relative path joined) | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-365 (152 half) | APP | W | hard DELETE / skipped job cancel | covered | planted at the repository (TASK-150: red); the route-path rows above see the cancel and the kept row | 2026-10-27 |

#### Revision 1 (2026-10-28): `OWN_CHANGES.removed(rel)` before each unlink in `remove_after_commit`

On a fresh copy of the tree with r1 (`-n 0`, with the 155 r2, 156 r2 and 159 files): `tests/test_policy_delete_pg.py` **11/11 passed** (95/95 for the four files). The watcher row "an API delete adds nothing beyond its own `policy.delete`" in `work/reports/TASK-159-test.md` passes. The hook can't be seen in behaviour, because the deleted policy's path then belongs to no live policy, so an unhooked delete event does nothing; it is defence in depth. Verdict: **PASS**.

### TASK-153


Tester: tester-m7, 2026-10-27. REQ-162, REQ-165 to REQ-168; TS §8.4 L1288 to L1291, §4.1 L530, §5.2 L699; #23, #100 (a) to (d), #101, #103. Files under test: `bm/services/audit/alerts.py`, `bm/services/audit/metrics.py`, `bm/services/importer/alerts.py`. Checks CHK-M7-185 to -188, mutation row CHK-M7-354 and extra plants. New test file `manager/tests/test_import_alerts.py` (51 tests). Updated tester-owned tests:
- `test_alerts.py`: the #101 kinds, 34 kinds, the `bitscan_import_failures` family. Its unknown-kind example `policy_imported` (now a real kind) is replaced by `Policy_Imported` and `policy_moved`.
- `test_thresholds.py`: the family, type counter, label `mode`, and the REQ-086 (3) label-name pin extended with `mode`, whose values must be exactly `auto`, `manual`, `rebuild`.
- `test_metrics_api_pg.py`: the same label pin with the mode values.

None of these updates weakens a check. Each adds the fixed set #101 approved and asserts its exact values.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t153, `CI=true`, `-n 0`) | `pytest tests/test_import_alerts.py tests/test_alerts.py tests/test_thresholds.py tests/test_alerts_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_fleet_alerts_pg.py` | 152/155 passed, 3 failed, 0 skipped. The 3 failures are existing tests that pin the pre-M7 sets (test updates, not product bugs) |
| r1 (W, label m7t-t153b) | the 3 failing node ids after the test updates: `test_alerts.py::test_unknown_kind_is_refused_and_nothing_is_written`, `test_thresholds.py::test_no_unbounded_label_names_anywhere`, `test_metrics_api_pg.py::test_no_label_holds_an_unbounded_value` | 7/7 passed |
| static (L) | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean (257 files) |

#### Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7`, `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0`, leftover-own 0. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>`, imported first through `PYTHONPATH`.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-185 | CODE | W | r0 (`test_import_alerts.py`, `test_alerts.py`) | PASS | `M7_ALERT_KINDS` = the six #101 kinds, no move kind; union of 34; each M7 kind and each of the 3 modes exported at `0.0` in a fresh process, no other mode; `raise_alert` refuses `policy_moved`, `Policy_Imported`, `policy_imported ` with nothing written; every kind (M7 included) writes one entry with `alert = true` and its kind | 2026-10-27 |
| CHK-M7-186 | CODE | W | r0 | PASS | `policy_imported`: action `policy.import`, target `policy:<id>`, the full detail (incl. `renamed_from`, `revived`), every changed Execute in full and in order (a 16,000-character Execute whole), actor kept; the six words flagged case-insensitively, each alone (12 cases incl. `SHADOW`, `.SSH`, `A.PEM`, `.Key`, `Token`, `CREDENTIALS`); six plain CIS commands (incl. `/etc/ssh/sshd_config`, `ssh_host_ed25519_key`) unflagged; several words listed once in spec order; the count +1 only on commit, none on rollback; the Execute text never in a log record | 2026-10-27 |
| CHK-M7-187 | CODE | W | r0 | PASS | `rejected`: action, kind, target the file name, else `policy:<id>`, else null; distinct codes in first-seen order; finding messages not in the entry (canary); `deleted` with the 3 reasons; `moved` is a plain `policy.move` entry with no alert key and no counter hook; `status_change` alerts only disabled → enabled (8 cases, PATCH and file); `rebuilt` target `task:<uuid>`; `integrity_failed` lists the first 100 of 150 in order with the total, and an empty list is refused; U+0000 and lone surrogates in path fields become U+FFFD, so every entry is UTF-8-encodable JSON | 2026-10-27 |
| CHK-M7-188 | CODE | W | r0 + r1 (`test_thresholds.py`, `test_metrics_api_pg.py`) | PASS | `bitscan_import_failures_total{mode}` is a counter; +1 per mode only on commit and only for that mode; none on rollback; unknown mode (`Auto`, `watch`, ``, `rebuild `) refused with no hook; a rejected alert and its count land together; label names on the wire = {kind, status, le, mode}; mode values exactly the three; the scrape route's samples obey the same | 2026-10-27 |
| CHK-M7-185..188 static | CODE | L | ruff, format, mypy (CI form) | PASS | clean, 257 files | 2026-10-27 |
| CHK-M7-354 | CODE | W | plants: (a) `execute` cut to 64 characters; (b) `flags` always `[]` | PASS (red) | (a) 1 failed; (b) 12 failed | 2026-10-27 |
| CHK-M7-153-case | CODE | W | plant: flags without `casefold` | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-153-word | CODE | W | plant: `token` dropped from `FLAG_WORDS` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-reen | CODE | W | plant: re-enable alert on any status change | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-cnt | CODE | W | plant: failure counted before commit | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-cap | CODE | W | plant: integrity list capped at 10 | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-move | CODE | W | plant: move raised as an alert | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-nul | CODE | W | plant: no U+0000 / surrogate replacement | PASS (red) | 1 failed (`UnicodeEncodeError`) | 2026-10-27 |
| CHK-M7-153-msg | CODE | W | plant: finding messages copied into the rejected entry | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-mode | CODE | W | plant: `rebuild` dropped from `IMPORT_MODES` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-kind | CODE | W | plant: `policy_reenabled` dropped from `M7_ALERT_KINDS` | PASS (red) | 8 failed | 2026-10-27 |

Not here (by design): REQ-162 (4) and (5) on PostgreSQL. That is the alert in the catalog transaction, no alert or count after a rollback, and the entry reaching the fake sink. They run at TASK-154 (G60, CHK-M7-286, -349, -350). The detail keys the implementer chose (rejected, deleted, status_change, rebuilt, integrity) are tested as written; they were sent to main as choices.

#### Round 2 (reviewer-m7 should-fix: `rejected()` fallback target capped at 255 characters, `TARGET_MAX`)

New rows: `test_import_alerts.py::test_rejected_fallback_target_fits_the_column_and_detail_keeps_it_whole` (n = 250, 255, 300: target = the first 255 characters of `uploaded/aaa….bit`, and `detail.file_name` holds the whole name) and `::test_rejected_target_counts_characters_not_bytes` (`é` × 300). New PostgreSQL file `test_import_alerts_pg.py::test_long_name_rejected_alert_is_stored` (the 263-character `uploaded/` name and `é` × 300 + `.bit` are written through `emit` and `PgAuditRepo` into `audit_log`; the stored target is the first 255 characters and the stored detail holds the full name).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-187-r2 | CODE + APP | W | `pytest -q -n 0 tests/test_import_alerts.py tests/test_import_alerts_pg.py` (label m7t-t151, in one run with TASK-151) | PASS | 55/55 + 2/2 passed, 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-153-cut | CODE + APP | W | plant: cut removed (`name or None`) | PASS (red) | 6 failed: 4 unit (length) and both PostgreSQL rows (the insert into `audit_log.target` VARCHAR(255) fails) | 2026-10-27 |
| CHK-M7-153 static | CODE | L | ruff, ruff format, mypy (CI form) | PASS | clean | 2026-10-27 |

Verdict after round 2: **PASS**.

#### Round 3 (#100 (a) widened: each `changed_executes` entry gains `reason`)

Updated: `test_imported_shape_carries_every_changed_execute_in_full` (each entry carries `reason`). New: `test_each_entry_carries_its_reason_in_the_101_key_order` (keys exactly `plugin_uuid, plugin_name, execute, execute_sha256, reason, flags`; reasons new, changed, reactivated in order; a reactivated `cat /etc/shadow` in full with its flag).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-186-r3 | CODE + APP | W | `pytest -n 2 tests/test_import_alerts.py tests/test_import_alerts_pg.py tests/test_alerts.py tests/test_thresholds.py` (with the TASK-151 r2 file, m7t-t151r2) | PASS | 56 + 2 + 51 + 22 = 131/131 passed (the run: 166/166) | 2026-10-27 |
| CHK-M7-153-rr | CODE | W | plant: `reason` dropped from the entry | PASS (red) | 2 failed | 2026-10-27 |

Verdict after round 3: **PASS**.

#### Round 4 (crash-window ruling: `rebuilt(..., removed_leftovers)`)

Updated `test_rebuilt_shape`: two leftover paths are listed in the given order, not sorted. New rows:
- `test_rebuilt_with_no_leftovers_lists_an_empty_list` (`()` gives `[]`).
- `test_rebuilt_leftover_paths_are_storable` (U+0000 and a lone surrogate become U+FFFD; UTF-8-encodable JSON).
- `test_rebuilt_requires_the_leftovers_keyword` (omitting it is a `TypeError`).

Tester note: while editing, a failed edit script of mine truncated the untracked `test_import_alerts.py`. I restored it byte for byte from my WSL copy synced at the m7t-t151r2 run (583 lines) before adding these rows, and checked it. No test was lost.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-187-r4 | CODE + APP | W | same run as TASK-151 r3 (m7t-t151r3) | PASS | 59/59 alerts + 2/2 PostgreSQL | 2026-10-27 |
| CHK-M7-153-lo | CODE | W | plant: leftovers always `[]` | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-lr | CODE | W | plant: leftovers sorted | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-ls | CODE | W | plant: leftovers not through `_storable` | PASS (red) | 1 failed (`UnicodeEncodeError`) | 2026-10-27 |

Verdict after round 4: **PASS**.

### TASK-154


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-150 (4), REQ-155, REQ-157 (3), REQ-160, REQ-162, REQ-176 (2); TS §4.1 L516–L532, §4.2, §4.3, §8.4 L1288–L1291; SR §3.5, §3.6, §4; #23, #98 (j), #99 (b), (e), #100 (a) widened, #101, #106, #110; BIT016 ruling (2026-10-27); the 2026-10-28 TASK-154 rulings. Code under test: `bm/services/importer/pipeline.py` and `pipeline_record.py` (the split). New test files: `manager/tests/test_import_pipeline_pg.py` (216 tests, its own module database, plus a fresh database for the two exact first-import tests) and `manager/tests/test_import_fuzz_pg.py` (1 test, 500 files, its own database). Rows go in through the real `AppDatabase.session()` and `catalog_lock`, with a temporary bits folder. BIT102 is checked only through cases TASK-146 r2 does not change (lead, 2026-10-28): `rm x` is rejected, and the SR and sample Executes pass.

#### Runs

| Run | Command (W, `/root/bstest-m7-t154`, `CI=true`) | Count |
| --- | --- | --- |
| r0 (`-n 2`) | `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | 53/217 passed, 162 failed, 2 errors, 0 skipped. All were test bugs: `errors` key order compared as a list (jsonb doesn't keep key order), and the fresh-server creds folder not created |
| r1 (`-n 2`) | the same two files after the two fixes | **217/217 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (`-n 0`) | `tests/test_import_fuzz_pg.py` after widening its fault handler (any exception from an injected fault is checked for state) | 1/1 passed |
| r3 (`-n 0`) | `tests/test_module_imports.py` (covers the new modules) | 131/131 passed |
| plants | 14 plants in throwaway copies `/root/bstest-m7-mut-<id>` (removed after each), clean copy green first (r1) | 14/14 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on both new files | clean |

The first two plants ran at `-n 2` with 2,772 MB free, under the 3,000 MB floor. That was my error. Every run after that checked memory first and used `-n 0` below 3,000 MB. No container was left by label.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-190 | APP | W | r1 | PASS | Fresh database, the SR §1.1 bytes (manifest sha), server file `cis-ubuntu.bit`, actor `user:7`: exactly one `bit_import` row `{file_name cis-ubuntu.bit, sha, policy_version 1, manual, success, 1/0/0, errors [], imported_by 7, imported_at = clock}`; exactly one audit entry, `policy.import` by `user:7` on `policy:<id>`, `alert true`, `policy_imported`, `changed_executes` = the one plugin (`3f6c2a9e-…`, `1.3.1.1 - Ensure AppArmor is installed`, the trimmed Execute, its sha, `new`, no flags); `bitscan_alerts_total{policy_imported}` +1 and no other counter moves; membership `[(uuid, 1)]` | 2026-10-28 |
| CHK-M7-191 | APP | W | r1 | PASS | 145 rejecting fixtures of `bits/tests/manifest.json` (every Reject code: BIT001–005, 008, 010–014, 016, 017, 102 via `bit102-rm`), PluginIds isolated per test: each gives one `rejected` row (version null, counts 0, mode, file name) whose code set is exactly the manifest's, four keys per finding, ordered by line; exactly one `policy.import_rejected` entry (`policy_import_rejected`, `import_id`, mode, `codes` in row order, `finding_count`); catalog checksums unchanged; `policy_import_rejected` +1 and `bitscan_import_failures_total{mode}` +1 for `auto`, `manual` and `rebuild` each; oversize folder file (data None, #99 (b)) and 5 MiB + 1 bytes → BIT001 rejected; exactly 5,242,880 bytes → success; alert target `policy:<id>` for a matched update, the file name otherwise | 2026-10-28 |
| CHK-M7-192 | APP | W | r1 | PASS | `auto` with an unchanged file: one `skipped` row (current version, counts 0, `[]`), **no** audit entry, no counter, catalog unchanged; `manual` and `rebuild` on the same bytes: `success`, same version, 0/0/0, one `policy.import` with empty `changed_executes`; `auto` imports a changed file (version +1) and retries a rejected one each time (rejected again, never skipped), and skips again on the last successful bytes; `auto` revives a deleted policy instead of skipping it (version +1, #14) | 2026-10-28 |
| CHK-M7-193 | APP | W | r1 | PASS | 25 success fixtures (valid, at-limit, warnings) import with exactly the manifest's warning codes in `errors` and in the outcome (#110), one `policy_imported` each | 2026-10-28 |
| CHK-M7-194 | APP | W | r1 | PASS | `before_commit` raising `OSError`: it was called with the policy id, then nothing committed, no row, no entry, no counter (#98 (j)); a database error inside the store (`replace_membership`): the same; a record failure after a committed success: the catalog stands, `import_id` None, one `policy.import`, `policy_imported` +1, the log has `bit_import record failed: OperationalError` and no name or Execute; a record failure on a rejection propagates with no alert and no count; `after_commit` raising: the success row is still written, then the error propagates; `after_commit` runs after the commit (another connection sees the policy) and before the record | 2026-10-28 |
| CHK-M7-195 | APP | W | r1 | PASS | Read once: with a different file on disk, `import_one` stores the buffer (source sha and Execute from the buffer), and the audit hook sees no open of any path in the bits folder; `prepare` takes only `data`, has no side effects and is deterministic | 2026-10-28 |
| CHK-M7-196 | APP | W | r1 | PASS | Internal errors write no `bit_import` row (store database error, `before_commit` disk error) | 2026-10-28 |
| CHK-M7-197 | APP | W | r1, r2 | PASS | 500 seeded files (seed 20261028; pools of 4 names, 10 ids and 3 server files plus uploads; SR example and samples; half byte-mutated; 10 % with a fault injected late in the store). After each run: unchanged (full row sets of `family`, `policy`, `plugin`, `policy_plugin`) for rejected, skipped, refused and faulted runs. For success, complete against the file as the test reads it with defusedxml: name, family, sha, source file, version rule, membership in document order, owner, `active`, Execute and sha; nothing else changed except a displaced policy (#106) and retirements of plugins no live policy lists. Exactly one row per import, none for refused or faulted. Every branch was reached | 2026-10-28 |
| plan §10 row 4 | APP | W | r1 | PASS | `formatVersion` `2.0` and `1.1` with a bad status → BIT016 and BIT003 in one row (BIT016 ruling); BIT002 with BIT003 → only BIT002; BIT003, BIT007 and BIT015 together in one row; the `db/bit007-*` pair gives BIT007 at `Policy/PolicyName`, then once `a.bit` is gone the move keeps the id and writes `policy.move {from a.bit, to b.bit}` (no alert); the `db/bit015-*` trio gives BIT015 at `Plugin[2]/PluginId`, then after the owner drops the id, the claim moves `owner_policy_id` | 2026-10-28 |
| plan §10 row 5 | APP | W | r1 | PASS | An upload of a server-folder policy raises `PolicyManagedOnServer(policy_id)`, writes no row, and writes exactly one entry `{actor user:3, policy.import_refused, policy:<id>, {policy_id, mode, file_sha256}}` with no alert key; catalog and counters unchanged | 2026-10-28 |
| plan §10 row 7 | APP | W | r1 | PASS | Rebuild of three files in one transaction with `store_in_savepoint`, the second now `rm x`: the pending outcomes are success, rejected, success with no `import_id`; `record` in a second transaction writes three `rebuild` rows (the middle one `["BIT102"]`); the rejected policy's rows, membership and plugin are byte-equal to before; the other two are updated; `policy.import` only for those two (mode `rebuild`), exactly one `policy.import_rejected` and no other entry on the rejected policy; counters `policy_imported` +2, `policy_import_rejected` +1, `fail:rebuild` +1 | 2026-10-28 |
| plan §10 row 8 | APP | W | r1 | PASS | Server file wins over an upload: same id, `source_file` moves, the uploaded copy is deleted from disk, entries `policy.import` then `policy.move {uploaded/policy-<id>.bit → srv.bit}`. Displaced (#106): X deleted (`deleted/<id>`), entries `policy.import`, `policy.move` and `policy.delete` (`policy_deleted`, "file now holds another policy"), counters +1 each. Rename in place keeps the id with `renamed_from`. A file re-enable gives `policy.status_change` `policy_reenabled` by `file`; with the admin override it stays disabled and no re-enable alert is raised. `changed_executes` gives `new` (with the `shadow` flag), then only the `changed` one, then `reactivated` for a retired plugin listed again (#100 (a) widened) | 2026-10-28 |
| REQ-157 (3) entry points | APP | W | r1 | PASS | `rm x` added to a live policy is rejected (BIT102 at `Plugin[2]/Execute`) on server and upload targets in `auto`, `manual` and `rebuild` modes, and in the rebuild savepoint; the SR Execute in a generated file and both `bits/samples` files (fresh database) import with no Reject and no BIT102 | 2026-10-28 |
| actors, lock, logs | APP | W | r1 | PASS | `user:42` → `imported_by` 42; `cli:root` and `system` → NULL; the audit actor is the given string on success and rejection; the caller's catalog lock stays held during `before_commit`, during `after_commit` and after `import_one` returns, and is free after the caller releases it; no Execute, description, name or `rm x` text in any log record across success, BIT102 rejection and BIT003 rejection | 2026-10-28 |
| CHK-M7-333 | APP | W | plant a: `prepare` skips `check_execute` (`pipeline.py`) | PASS (red) | 8 failed: `bit102-rm` fixture, all six `test_rm_is_rejected_on_every_entry_point`, the rebuild row | 2026-10-28 |
| CHK-M7-333 | APP | W | plant b: `store_in_savepoint` drops the BIT102 findings (`pipeline_record.py`) | PASS (red) | 1 failed: `test_rebuild_with_one_file_rejected_keeps_its_rows` (`[] == ['BIT102']`) | 2026-10-28 |
| CHK-M7-339 | APP | W | plant: the rejected `record` written inside tx1 (`pipeline.py`) | PASS (red) | 166 failed: every rejection loses its row with the rollback | 2026-10-28 |
| CHK-M7-340 | APP | W | plant a: `before_commit` `OSError` swallowed, tx1 commits | PASS (red) | 1 failed: `test_before_commit_failure_rolls_back_with_no_row_and_no_alert` (did not raise) | 2026-10-28 |
| CHK-M7-340 | APP | W | plant b: a database error in tx1 suppressed and the transaction committed (`pipeline.py`) | PASS (red) | 2 failed: the fuzz at run 6 (injected fault left a partial import: the catalog differs) and `test_a_database_error_in_the_store_writes_nothing` | 2026-10-28 |
| CHK-M7-349 | APP | W | plant: the `policy_imported` `put` removed (`pipeline_record.py`) | PASS (red) | 36 failed, among them every success fixture, both no-skip modes, the rebuild, move, displaced, rename, re-enable, changed-executes and record-failure rows | 2026-10-28 |
| CHK-M7-350 | APP | W | plant a: the rejected `alerts.emit` removed from `record` | PASS (red) | 163 failed (every rejection row) | 2026-10-28 |
| CHK-M7-350 | APP | W | plant b: `count_failure` removed from `record` | PASS (red) | 163 failed (`fail:<mode>` +1 missing) | 2026-10-28 |
| CHK-M7-369 | APP | W | plant a: `mode == "auto" and` dropped (manual and rebuild skip) | PASS (red) | 2 failed: `test_manual_and_rebuild_never_skip[manual]`, `[rebuild]` | 2026-10-28 |
| CHK-M7-369 | APP | W | plant b: `mode != "auto"` (auto never skips) | PASS (red) | 4 failed: the skip row, both no-skip rows, and the auto retry row | 2026-10-28 |
| CHK-M7-154-ref | APP | W | plant: the refusal re-raised without its `policy.import_refused` entry | PASS (red) | 1 failed: `test_upload_of_a_server_folder_policy_is_refused_without_a_row` | 2026-10-28 |
| CHK-M7-154-read | APP | W | plant: `import_one` re-reads a server file from disk | PASS (red) | 2 failed: `test_the_buffer_is_used_and_the_file_is_never_opened` (open seen), and the oversize folder row | 2026-10-28 |
| CHK-M7-154-lock | APP | W | plant: `import_one` unlocks the catalog at its start | PASS (red) | 1 failed: `test_the_callers_lock_is_held_throughout_and_not_released` (`[True, True, True]`) | 2026-10-28 |
| BIT102 fixtures (r2) | APP | W | — | NOT RUN (by the lead's instruction) | `content/bit102-redirect`, `-systemctl-stop`, `-sed-i`, `-bash-c-subst` and `-unlexable` wait for TASK-146 r2 approval; they are in `R2_PENDING` in the test file and join `REJECTING` on the targeted re-run | 2026-10-28 |
| REQ-162 (5) sink | APP | — | — | NOT RUN (not this task) | Delivery to the fake sink belongs to G60 `test_catalog_alerts_pg.py` (CHK-M7-286); here every entry is checked in `audit_log` with `detail.alert` and its counter | 2026-10-28 |

#### Acceptance (TASK-154 row)

- SR §1.1 example: one `success` row and one `policy_imported` alert → CHK-M7-190.
- Each BIT fixture: its `rejected` row and alert, and no catalog change → CHK-M7-191 (five BIT102 fixtures pending r2, as above).
- An unchanged file in `auto` mode writes only a `skipped` row → CHK-M7-192.
- 500 generated files leave the catalog complete or unchanged → CHK-M7-197.
- A rolled-back import writes no success alert → CHK-M7-194.

Plan flows: move with a displaced policy, server-folder refusal and `policy.import_refused`, failure in the record step and in `after_commit`, rebuild with one file rejected → plan §10 rows 5 to 8 above. Every named plant (333, 339, 340, 349, 350, 369) and three security plants went red.

#### For the lead (no defect; please confirm)

1. **Rejected-alert target.** #101 reads "Target: `policy:<policy_id>`, or the file path for a rejected import". Plan §5 and the approved TASK-153 builder read this as "the matched policy if any, else the file name". My test asserts the plan's reading: a BIT003 update of a live policy targets `policy:<id>`, and an unknown name targets the file name. If #101 means every rejected import targets the file path, that test and TASK-153 need to change.
2. **Skipped row version.** A `skipped` row stores the current `policy_version` (plan §5). SR §3.5 describes the column as "`policy.version` after the import, if it succeeded". The test pins the plan's value.
3. **The `auto` skip comes before the findings** (the impl report's observation, the lead's 2026-10-28 ruling). The tests pin that a rejected file is retried every time and that the last successful bytes skip.

#### Revision 1 (2026-10-28): `policy_version` NULL unless `success`

Ruling: work/decisions.md "TASK-154 test questions" (2), which reads SR §3.5 literally. Product change: `pipeline_record.py` only. A skip no longer carries the old version, and `record` writes `policy_version` only when `outcome = success` (impl report, "Revision 1"). The re-pin was made from the ruling before the r1 code arrived:

- `test_auto_unchanged_writes_only_a_skipped_row` now expects the `skipped` row's `policy_version` to be NULL. The outcome still carries the `policy_id`.
- Rejected rows were already pinned to NULL in `assert_rejected`.
- The fuzz now asserts that every non-success row has a NULL `policy_version`.

Rulings (1) (the rejected-alert target: `policy:<id>` when matched, else the file name) and (3) (the `auto` skip before the findings, TS §4.2) confirm the existing pins. No test changed for them.

| Run | Command (W, `/root/bstest-m7-t154`; only `pipeline_record.py` and the two test files synced, so the BIT102 code is the same as in r1 above) | Count |
| --- | --- | --- |
| r1-1 (`-n 2`, label `m7t-t154r1`) | `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | **217/217 passed**, 0 failed, 0 errors, 0 skipped |
| plants | the record-touching plants again, plus the r1 plant | 4/4 red |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-192 (r1) | APP | W | r1-1 | PASS | `auto` unchanged: one `skipped` row with `policy_version` NULL, mode `auto`, `errors` `[]`, counts 0; no audit entry, no counter, catalog unchanged; `manual` and `rebuild` → `success` with the version | 2026-10-28 |
| CHK-M7-191 (r1) | APP | W | r1-1 | PASS | every rejected row has a NULL `policy_version` (145 fixtures, the mode, oversize, target and DB-rule rows) | 2026-10-28 |
| CHK-M7-197 (r1) | APP | W | r1-1 | PASS | 500 files: every non-success row's `policy_version` is NULL, and the earlier complete-or-unchanged checks still hold | 2026-10-28 |
| CHK-M7-154-r1 | APP | W | plant: the skip carries `old.version` again and `record` writes `pending.policy_version` unconditionally | PASS (red) | 2 failed: `test_auto_unchanged_writes_only_a_skipped_row` (`('skipped', 'auto', 1, [])` vs `None`), and the fuzz at run 97 (an `auto` skip on `f2.bit`) | 2026-10-28 |
| CHK-M7-350 (r1) | APP | W | plants a and b again (`record` changed) | PASS (red) | 163 failed each | 2026-10-28 |
| CHK-M7-339 (r1) | APP | W | plant again (the record inside tx1) | PASS (red) | 167 failed | 2026-10-28 |

Verdict after revision 1: **PASS**. The five BIT102 fixtures are still NOT RUN and wait for TASK-146 r2, as above.

#### Revision 2 (2026-10-28): a rebuild alerts only for a policy whose rows it changed

Ruling: work/decisions.md "TASK-157 rulings" (2) (#23 agreed, REQ-166 (6)). Product change: `pipeline_record.py` only (`_fingerprint`, `_changed`; rebuild mode only). Test changes, made from the ruling:
- **Re-pin:** `test_manual_and_rebuild_never_skip[rebuild]` expected a `policy.import` entry for an unchanged rebuild file. Under the ruling an unchanged rebuild file writes no entry and no count, so it now asserts that, while `[manual]` still expects its entry and count (TS L530).
- **New rows:**
  - `test_a_rebuild_that_changes_nothing_alerts_for_nothing`: three unchanged files through `store_in_savepoint` and `record` → three `success` rows, no entry, no counter, catalog unchanged.
  - `test_each_corruption_gives_exactly_one_policy_imported[execute, membership, retired, status, sha, owner]`, one per owner-made corruption: the REQ-166 (1) four, plus `source_sha256` and `owner_policy_id`. Each gives exactly one `policy.import` for that policy, one `policy_imported` count, and the restored rows (execute, membership, `active`, `policy_status`, owner, sha).

| Run (W, fresh copy `/root/bstest-m7-t154r2`, `-n 2`) | Count |
| --- | --- |
| `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | **224/224 passed**, 0 failed, 0 errors, 0 skipped |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-154-r2 rows | APP | W | run above | PASS | An unchanged rebuild file is `success` with no entry and no count; each of the six corruptions gives exactly one `policy_imported` and is restored; manual stays audited; the rebuild with one file rejected still alerts for its two changed files | 2026-10-28 |
| plant r2a | APP | W | the fingerprint comparison dropped | PASS (red) | 4 failed: the `membership`, `status` and `sha` corruption rows, and the rebuild row (its description-only change is seen only by the fingerprint) | 2026-10-28 |
| plant r2b | APP | W | `_changed` always true | PASS (red) | 2 failed: the unchanged-rebuild row and `never_skip[rebuild]` | 2026-10-28 |
| plant r2c | APP | W | the change gate applied in every mode | equivalent alone (223 passed) | Outside rebuild mode the before fingerprint is None, so the change test is always true. Together with r2d (the fingerprint read in every mode) → red, 1 failed: `never_skip[manual]` (an unchanged manual import lost its entry) | 2026-10-28 |

Verdict after revision 2: **PASS**.

### TASK-155


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-163 (1)–(6), REQ-165 (1); TS §4.1 L522, L526, L528, §8.7 L1344, L1377; #98 (j), #99 (d), (e); the crash-window ruling (2026-10-27). Code under test: `bm/services/importer/uploads.py`, both r0 and revision 1 (`UploadStage` and `staged_upload`, decisions 2026-10-28 "TASK-156 case (c) success"). New test file: `manager/tests/test_uploads_pg.py` (38 tests, Linux only: symlinks, FIFOs, modes, `O_NOFOLLOW`). Its own module database; real `SessionDatabase`, `catalog_lock` and a temporary bits folder (`uploaded/` 0750).

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t155` of the tree with r1, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| u0 | `pytest tests/test_uploads_pg.py` (37 tests) | 37/37 passed |
| u1 | the same, after the FIFO helper got an `unblock` (so a blocked writer can't hold the catalog lock and hang the run; found by plant u1) | 37/37 passed |
| u2 | the same, plus the owner-written live-check row (found by plant u7) | **38/38 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 17 plants in throwaway copies (`/root/bstest-m7-mut-<id>`, removed after each), `-n 0` | 15 red, 2 equivalent mutants (explained below), each covered by a combined plant that went red |
| static (L) | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (whole tree) | clean (289 files, including test_folders_pg.py) |

One run hung: plant u1 made the FIFO case block, and the blocked thread kept the catalog lock. I killed it and removed its container. The helper fix is in u1 above.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-200 | APP | W | u2 | PASS | REQ-163 (1): 14 client names (`../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, 5,000 characters, NUL, CR and LF, tab/U+001F/DEL, `<script>`, U+202E, invalid UTF-8, 300 × `é`, a missing name, empty). For each, a snapshot of the whole temp tree before and after differs only by `bits/uploaded/policy-<id>.bit` holding the bytes. `bit_import.file_name` is the #99 (d) form (UTF-8 with replacement; C0 and DEL → U+FFFD; 255 characters, not bytes; missing → ``). `source_file` is `uploaded/policy-<id>.bit`. `client_file_name` is idempotent, keeps U+00A0 and spaces, and turns a lone surrogate into U+FFFD | 2026-10-28 |
| CHK-M7-201 | APP | W | u2 | PASS | REQ-163 (2): a symlink to an outside file, a dangling symlink, a regular file, or a FIFO at `uploaded/.tmp-<id>-<sha>` → `OSError`, never blocks; no row, no audit entry, no counter, catalog unchanged; the whole tree is unchanged (target untouched, the dangling target never created, the planted entry kept); the stored upload is unchanged. A spy shows the temp open uses `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW` (no `O_TRUNC`) with mode 0600 (TS L522) | 2026-10-28 |
| CHK-M7-202 | APP | W | u2 | PASS | REQ-163 (3): a rejected re-upload (`rm x`) writes its `rejected` row, and the stored file keeps its inode, mtime and bytes; tree and catalog are unchanged. (4) A fault right after the temp write and before the commit (`OSError` and `RuntimeError`) leaves no temp and changes nothing (no row, #98 (j)). A fault between commit and rename: the error propagates; the `success` row is written; the catalog has committed (`source_sha256` is the new hash, `policy_imported` +1); the temp holds the new bytes and the old file remains. A same-bytes re-upload before the restart clashes on `O_EXCL`: `FileExistsError` (internal error, 503 at the route), nothing changes and the left temp is kept (impl reading 2). Then `finish_interrupted` renames it (1 renamed): the file holds the committed bytes, is 0600, and is the only entry | 2026-10-28 |
| CHK-M7-202 order | APP | W | u2 | PASS | The temp is written while another connection still sees the old hash (before the commit). It is renamed when the new hash is visible (after the commit), complete and 0600, while `pg_try_advisory_lock(hashtext('catalog'))` from another session is false (the lock is held through the rename, TS L526). A re-upload replaces the previous file (one entry, new bytes); identical bytes are `success` again (manual, never skipped), with version +1 for changed bytes | 2026-10-28 |
| CHK-M7-203 | APP | W | u2 | PASS | REQ-163 (5): an upload with a server-folder policy's name raises `PolicyManagedOnServer`, writes no row, exactly one `policy.import_refused` entry and no counter; tree unchanged (no file, no temp) | 2026-10-28 |
| CHK-M7-204 | APP | W | u2 | PASS | REQ-163 (6): with the process umask 0 (stricter than the unit's `UMask=0077`), the stored file is a regular file, 0600, uid and gid of the process; `imported_by` 11, mode `manual` | 2026-10-28 |
| CHK-M7-230 (1) | APP | W | u2 | PASS | REQ-165 (1), under the caller's catalog lock: a committed temp → renamed. Deleted: an uncommitted one, a deleted policy's (crash-window), a live server-folder policy's (impl reading 1), a symlink with a valid name to a file holding the committed bytes (target untouched), a FIFO (never blocks), and names not in the form (`.tmp-x`, leading zero, uppercase hex, 63 hex, trailing part, unknown id, `.tmp-`, over 5 MiB). A folder `.tmp-dir` is logged by type and the loop goes on. `notes.txt`, `.hidden`, `policy-999999.bit` and `tmp-1-x` are untouched, and so are the server folder files. `FinishResult(1, 13)`; a second finish gives `(0, 0)`. A row made as owner (deleted, `source_file` still `uploaded/policy-<id>.bit`) is never renamed (the extra live check, impl reading 1) | 2026-10-28 |
| CHK-M7-230 race | APP | W | u2 | PASS | `O_NOFOLLOW` on the finish read (impl reading 4): the temp is listed as a regular file, then swapped for a symlink to a file with the committed bytes before it is opened. The open carries `O_NOFOLLOW \| O_NONBLOCK`, fails, and the temp is deleted (0, 1). The stored upload never becomes a symlink and the outside file is untouched | 2026-10-28 |
| r1 staging | APP | W | u2 | PASS | `staged_upload` discards its temp when the block raises after `before_commit`; after `after_commit`, `discard()` removes nothing; a failed rename is never discarded (the temp is left for the finish); a stage that created nothing discards nothing, including after its own `O_EXCL` failure on someone else's temp; the rename target is the id recorded in `before_commit`, not the outcome's | 2026-10-28 |
| logs | APP | W | u2 | PASS | No client name, policy name, Execute, `rm x` or `.tmp-` path in any log record across success, rejection, the rename fault and the finish; the finish logs only `1 renamed, 0 deleted` | 2026-10-28 |
| #102 (c) | — | — | — | NOT RUN (belongs to TASK-159) | The watcher's record of the manager's own renames and deletions isn't wired in this task (impl reading 3); `after_commit` and `finish_interrupted` are the two places it must cover | 2026-10-28 |
| CHK-M7-357 | APP | W | plant u3: `O_EXCL` and `O_NOFOLLOW` both removed from the temp open | PASS (red) | 7 failed: every symlink, dangling, file and FIFO case (the symlink is followed into its target; the FIFO blocks), the flag spy, the `O_EXCL` clash, the stage row | 2026-10-28 |
| CHK-M7-357 | APP | W | plant u1: `O_EXCL` removed | PASS (red) | 5 failed: the file and FIFO cases, the flag spy, the clash, the stage row | 2026-10-28 |
| CHK-M7-357 | APP | W | plant u2: `O_NOFOLLOW` removed from the temp open | PASS (red) | 1 failed: the flag spy (`193 & 131265`). In behaviour this is an equivalent mutant: `O_CREAT \| O_EXCL` already refuses an existing symlink (POSIX), so only the TS L522 flag pin can see it | 2026-10-28 |
| CHK-M7-357 read | APP | W | plant u4: `O_NOFOLLOW` removed from the finish read | PASS (red) | 1 failed: the swap race (flags `[2048]`) | 2026-10-28 |
| CHK-M7-357 read | APP | W | plant u13: the finish lists with `follow_symlinks=True` | equivalent alone (38 passed) | The read's `O_NOFOLLOW` still refuses the symlink. Combined with u4 → red, 2 failed: the finish row (`(2, 12)`) and the race | 2026-10-28 |
| CHK-M7-359 | APP | W | plant u5 (impl's r1 plant): `discard` ignores `committed` | PASS (red) | 5 failed: the rename-fault row, the finish rows, the logs row, the failed-rename stage row | 2026-10-28 |
| CHK-M7-359 | APP | W | plant u12: the temp renamed into place before the commit | PASS (red) | 9 failed: both before-commit faults, the order row, the rename-fault and finish rows, the stage rows | 2026-10-28 |
| CHK-M7-359 | APP | W | plant u9: the temp written in `after_commit` instead of before the commit | PASS (red) | 10 failed: the planted-path cases now commit before failing, both before-commit faults, the rename fault (no recoverable temp), the order row, the stage rows | 2026-10-28 |
| CHK-M7-358 | APP | W | plant u11: the stored file renamed to the client name (`/` → `_`, kept inside the temp tree) | PASS (red) | 25 failed, among them every hostile-name case 0–11 (cases 12 and 13 have no name) | 2026-10-28 |
| CHK-M7-230 hash | APP | W | plant u6: the finish skips the hash comparison | PASS (red) | 2 failed: `(3, 11)` instead of `(1, 13)`, and the race | 2026-10-28 |
| CHK-M7-230 live | APP | W | plant u7: the finish skips the live check | PASS (red) | First run: 37 passed (equivalent on a consistent catalog, since a soft delete always sets `source_file` `deleted/<id>`). The owner-written row was added, then 1 failed: `test_a_deleted_policy_still_naming_its_upload_is_never_renamed` | 2026-10-28 |
| CHK-M7-230 file | APP | W | plant u8: the finish skips the `source_file` check | PASS (red) | 1 failed: `(2, 12)` (the server-folder policy's temp renamed) | 2026-10-28 |
| CHK-M7-204 | APP | W | plant u10: temp mode 0644 | PASS (red) | 4 failed: the flag spy, the rename fault, the order row, the mode row (420 vs 384) | 2026-10-28 |

#### Acceptance (TASK-155 row)

REQ-163 (1)–(6) → CHK-M7-200 to -204. REQ-165 (1) → CHK-M7-230 (1). The symlink at the temp path, the FIFO and mode 0600 are covered, and so are the faults before the commit and between the commit and the rename: the temp is left there, and the start-up finish renames or deletes it. The impl readings: 1 (the finish's live and `source_file` checks) → CHK-M7-230 (1) and plants u7 and u8; 2 (the `O_EXCL` clash → 503) → CHK-M7-202; 3 (#102 (c)) → NOT RUN, belongs to TASK-159; 4 (`O_NOFOLLOW` really in effect on Linux) → the flag pin and the race, plants u2, u4 and u13+u4. Every security row has a plant that went red.

#### Notes (no defect)

- In the finish, the rename happens after the hash read, so a writer who can change `uploaded/` between the two could swap the entry. `uploaded/` is written only by the manager (0750), so this is the TS §8.1 "whoever controls the manager" case, not a new risk.
- The 503 for the `O_EXCL` clash is the route's mapping (TASK-162). Here the internal error is `FileExistsError` with no row.

#### Revision 2 (2026-10-28): the #102 (c) `wrote` hooks

`OWN_CHANGES.wrote(...)` is recorded just before `os.replace` in `UploadStage.after_commit` (hook #1) and in `finish_interrupted`'s renames (hook #2). On a fresh copy of the tree with r2 (`-n 0`), run together with the 156 r2, 152 r1 and 159 files: `tests/test_uploads_pg.py` **38/38 passed** (95/95 for the four files). The hooks' effect is checked through the watcher in `work/reports/TASK-159-test.md` (CHK-M7-237 (4)). Plant h1 (no record in `after_commit`) → red, 2 failed. Plant h2 (no record in the finish) → red, 1 failed, on the restart-simulating row. Verdict unchanged: **PASS**.

### TASK-156


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-159 (2), (3), (6), REQ-164 (2), REQ-165 (3); TS §4.1 L515, L522, L524, L526, L528, §4.3 L550; SR §4.1 BIT007; #15, #102 (b), #103; the crash-window ruling (2026-10-27); decisions 2026-10-28 "TASK-156 case (c) success" and "TASK-156 staging extension and size"; the lead's 2026-10-28 request (the own-name skip-path must-pass row and the dropped-guard plant). Code under test: `bm/services/importer/folders.py`. New test file: `manager/tests/test_folders_pg.py` (30 tests, Linux only). Its own module database, and each test owns its bits folder. Before each test, the earlier tests' live policies are soft-deleted, so a reconcile neither deletes them nor counts their paths as recorded (#15).

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t156`, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| f0 | `pytest tests/test_folders_pg.py` | 28/30 passed, 2 failed. Both were test bugs: a 256-byte name can't be created on Linux (NAME_MAX), and I had left out the expected `skipped` row of the server file in the refused-copy test |
| f0-r | the two node ids after the fixes | 2/2 passed |
| f1 | the whole file again | **30/30 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 15 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 15/15 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (289 files) |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-208 | APP | W | f1 | PASS | REQ-164 (2), #102 (b), in both folders: `n.txt`, `.n.bit`, `A.BIT`, `n.bit.bak`, `.tmp-1-x`, `sub/s.bit`, a FIFO `f.bit` (never blocks), a symlink `l.bit`, and the names `\xff.bit`, `a\x01.bit` and `a\nb.bit` are never imported and get no row. A 255-byte name imports with `file_name` intact. Each unstorable name writes exactly one fixed log line (6 in total) naming nothing. The whole tree is unchanged except the case (c) relocation of `uploaded/u.bit`. `storable`: 254 bytes accepted; 256 bytes, DEL, C1 (U+009F) and a lone surrogate refused; U+00A0 accepted. Over 255 bytes can only be a unit row, since Linux can't create such a name. An oversize server file is rejected BIT001 with the full-file hash (#99 (b)) | 2026-10-28 |
| CHK-M7-209 | APP | W | f1 | PASS | #15: two new files with one name → the first in byte order (`B.bit` before `a.bit`; `z.bit` before `é.bit`, bytes not locale) imports and the other gets BIT007; a recorded `z.bit` goes before a new `a.bit`. REQ-159 (2): `a.bit` removed and `c.bit` added with its name → same id, `source_file` `c.bit`, no delete, one `policy.move {a.bit → c.bit}`. REQ-159 (3): a server file with an uploaded policy's name → the policy moves, the uploaded copy is deleted, one move entry; a later upload of that name → `PolicyManagedOnServer` (409). A symlink at the old path doesn't keep BIT007 alive | 2026-10-28 |
| CHK-M7-210 | APP | W | f1 | PASS | An unchanged folder (two server files and one upload) writes only `skipped` rows, one per file (`policy_version` NULL, TASK-154 r1), no audit entry, no counter, catalog unchanged, nothing deleted | 2026-10-28 |
| REQ-165 (3) | APP | W | f1 | PASS | A file added while down imports. A server file and an uploaded policy's file both removed → both policies deleted (`deleted/<id>`), `policy.delete` by `system` with reason "file removed" and `policy_deleted` (+2). A file replaced by a symlink counts as removed, and the symlink target is never followed or removed | 2026-10-28 |
| row (i) | APP | W | f1 | PASS | A live upload's unchanged file → one `skipped` row and no alert. Edited in place (own name `policy-<id>.bit`) → `success`, the file still present with its bytes, no error, no `.tmp-`, `source_sha256` updated: the skip-path must-pass row | 2026-10-28 |
| row (ii) | APP | W | f1 | PASS | A deleted policy's leftover `uploaded/policy-<id>.bit` → removed, no `bit_import` row, catalog unchanged, `deleted_at` kept, returned as `Difference("uploaded/policy-<id>.bit", "leftover of an interrupted delete")` | 2026-10-28 |
| row (iii) | APP | W | f1 | PASS | A live policy's upload file with another hash is never treated as a leftover. Its content names a new policy, so it is staged for that one, and the file itself stays as its own `source_file`. A `policy-<n>.bit` whose `n` is a live server-folder policy is "other": refused and kept for #103 | 2026-10-28 |
| row (iv) | APP | W | f1 | PASS | A spy on `import_one` sees every `uploaded/` file as `Target("upload", None)` and every server file as `Target("server", rel)`; `Target("server", "uploaded/…")` raises | 2026-10-28 |
| case (c) | APP | W | f1 | PASS | `uploaded/foreign.bit` with a new name → `success`, stored as `uploaded/policy-<id>.bit` (0600, its bytes), the foreign file removed, the only entry, `source_file` `uploaded/policy-<id>.bit`, row `file_name` `uploaded/foreign.bit`; the next reconcile skips the stored copy. Rejected (`rm x`) and refused (server-folder name) (c) files stay; refused gets `policy.import_refused` and no row; no temp left. A (c) `policy-<n>.bit` inserted as id `n` keeps its file, which is not staged or removed (the own-name path). An `uploaded/` symlink is never imported, and its target is untouched | 2026-10-28 |
| staging extension | APP | W | f1 | PASS | A live (a) file whose content names another policy → that policy is staged to its own `policy-<id>.bit`; the (a) file is kept and its policy stays live | 2026-10-28 |
| read and logs | APP | W | f1 | PASS | A file swapped for a symlink before its read → the open carries `O_NOFOLLOW`, the file isn't imported, there is no row, and it is listed in `not_imported`. No file name, policy name or Execute marker in the logs across server, (c), rejected and leftover files | 2026-10-28 |
| plant f1 | APP | W | a deleted policy classified "live" | PASS (red) | 1 failed: row (ii) | 2026-10-28 |
| plant f2 | APP | W | every name classified "other" | PASS (red) | 3 failed: rows (ii), (iii), the staging extension | 2026-10-28 |
| CHK-M7-363 / (iv) | APP | W | plant f3: `uploaded/` files as server targets | PASS (red) | 6 failed: row (iv), (i), server wins, removed files, case (c), refused copy | 2026-10-28 |
| CHK-M7-363 | APP | W | plant f4: discovery follows symlinks | PASS (red) | 1 failed: the discovery row | 2026-10-28 |
| CHK-M7-363 | APP | W | plant f5: `O_NOFOLLOW` dropped from the read | PASS (red) | 1 failed: the swap race (flags `[2048]`) | 2026-10-28 |
| CHK-M7-363 | APP | W | plants f4 + f5 together | PASS (red) | 3 failed, including an `uploaded/` symlink imported through its target | 2026-10-28 |
| plant f6 | APP | W | deletions before imports | PASS (red) | 1 failed: REQ-159 (2) (deleted `[7]`, not a move) | 2026-10-28 |
| plant f7 | APP | W | #15 sort reversed | PASS (red) | 2 failed: both byte-order rows | 2026-10-28 |
| plant f8 | APP | W | the case (c) unlink skipped | PASS (red) | 2 failed: the discovery tree and case (c) | 2026-10-28 |
| plant f9 | APP | W | the `if not self.staged: return` guard dropped | PASS (red) | 2 failed: row (i) own name and case (c) own name, both `LookupError: committed upload has no temp file` | 2026-10-28 |
| plant f10 | APP | W | delete reason changed | PASS (red) | 1 failed: "file removed" | 2026-10-28 |
| plant f11 | APP | W | `storable` always true | PASS (red) | 6 failed: the discovery row and five `storable` rows | 2026-10-28 |
| plant f12 | APP | W | the leftover not removed | PASS (red) | 1 failed: row (ii) | 2026-10-28 |
| plant f13 | APP | W | `is_bit_file` follows symlinks (`stat`) | PASS (red) | 1 failed: the symlink-counts-as-removed row | 2026-10-28 |
| plant f14 | APP | W | a refused (c) file removed | PASS (red) | 2 failed: row (iii) and the refused-copy row | 2026-10-28 |
| REQ-164 (1), (3)–(5) | — | — | — | NOT RUN (TASK-159) | inotify watcher and its events | 2026-10-28 |

#### Acceptance

TASK-156 row: REQ-164 (2) → CHK-M7-208; REQ-159 (2), (3), (6) and #15 → CHK-M7-209; REQ-165 (3) and the "file removed" reason → REQ-165 (3) row; an unstorable name skipped with one log line and no row → CHK-M7-208; an unchanged folder writes only `skipped` rows → CHK-M7-210; extra tests (i)–(iv) → rows (i)–(iv); the 2026-10-28 rulings → the case (c) and staging-extension rows. The lead's own-name must-pass row → row (i) and case (c) own name, and plant f9 drops the guard → red. Every security row has a plant that went red.

#### Notes (no defect)

- `storable` also refuses C1 controls (U+0080–U+009F). That is stricter than #102 (b) "a control character", and errs toward skipping.
- Plant f13 turned only the symlink-removed row red. The BIT007-with-symlink row stayed green, because the old policy's own file check doesn't decide that case.

#### Gap fix (2026-10-28, after review)

The reviewer found that `test_a_symlink_at_the_old_path_does_not_keep_bit007_alive` stayed green under plant f13. Its symlink pointed at a missing file, so even `stat` saw no regular file. The symlink at the old path `a.bit` now points at a valid `*.bit` regular file holding the same policy. The row asserts: `b.bit` imports with `success` and no BIT007, the policy moves to `b.bit`, and the symlink and its target are left as they were. Only the lstat rule (a symlink never counts as the old file still existing) can make it pass.

| Run (W, fresh copy `/root/bstest-m7-t156g`, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_folders_pg.py::test_a_symlink_at_the_old_path_does_not_keep_bit007_alive` | 1/1 passed |
| plant f13 (`is_bit_file` uses `stat`): that row and `test_a_file_replaced_by_a_symlink_counts_as_removed` | PASS (red): 2 failed. `{'b.bit': ['rejected']}` instead of `success` (BIT007 kept alive through the symlink), and `[] == [2]` (not deleted) |

Static: `ruff check`, `ruff format --check` and `mypy --strict` are clean on the changed file. Verdict unchanged: **PASS**.

#### Revision 1 (2026-10-28): rename only (`_read` → `read_file`, `_Relocate` → `Relocate`)

No test or monkeypatch names either private name, and every plant text still matches the revised `folders.py` exactly once.

| Run (W, fresh copy of the tree with r1, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_folders_pg.py` | **30/30 passed**, 0 failed, 0 errors, 0 skipped |
| plant f5 (`O_NOFOLLOW` dropped, read by `read_file`) | PASS (red): 1 failed, the swap race |
| plant f8 (the `Relocate` unlink skipped) | PASS (red): 2 failed, the discovery tree and case (c) |
| plant f9 (the `Relocate` guard dropped) | PASS (red): 2 failed, the own-name rows (`LookupError`) |

Verdict unchanged: **PASS**.

#### Revision 2 (2026-10-28): `OWN_CHANGES.removed(...)` before both unlinks

`Relocate.after_commit` and the leftover removal record the path just before the unlink; nothing else changed. On a fresh copy of the tree with r2 (`-n 0`, with the 155 r2, 152 r1 and 159 files): `tests/test_folders_pg.py` **30/30 passed**. The watcher rows in `work/reports/TASK-159-test.md` pass with these hooks. They can't be seen in behaviour, because the removed path belongs to no live policy, so an unhooked event does nothing either. Verdict unchanged: **PASS**.

### TASK-157


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-166 (1)–(6); TS §4.2 L540, L542, §4.1 L524, L526, §4.3 L550; #20, #23, #98 (g), (j); decisions "TASK-157 rulings" (1)–(5), TASK-154 r2, the crash-window ruling, "TASK-156 case (c) success"; the lead's r1 must-pass rows and the accepted-exception row (2026-10-28). Code under test: `bm/services/importer/rebuild.py` **revision 1** (staged `uploaded/policy-<id>.bit` targets count as present in the gone-file loop; the blocking defect found by reviewer-m7). New test file: `manager/tests/test_rebuild_pg.py` (17 tests, Linux only). Its own module database; each test owns its folders, and the earlier tests' live policies are soft-deleted first.

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t157` of the tree with r1, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| g0 | `pytest tests/test_rebuild_pg.py` (15 tests then) | 15/15 passed. The copy already had r1 (checked: `work.staged` in the copied `rebuild.py`) |
| g1 | the same, with the r1 must-pass rows and the accepted-exception row in both #15 orders | **17/17 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean |

(The g1 count of 17 counts the accepted-exception row once per parameter: 16 functions, one with 2 cases.)

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-216 | APP | W | g1 | PASS | REQ-166 (1): five policies; four corrupted by the owner (an `execute`, a `policy_plugin` row deleted, a plugin `retired`, `policy_status` flipped without an override), one untouched. The rebuild keeps every `policy_id` (and plugin uuid), restores the membership in order, `enabled`, each plugin's `execute`, `active` and owner. Exactly four `policy.import` entries, on the four corrupted policies, none on the untouched one; one `policy_rebuilt`; `policy_imported` +4 (TASK-154 r2) | 2026-10-28 |
| CHK-M7-217 (2) | APP | W | g1 | PASS | One rejected (`rm x`) of three: its policy row, membership and plugin byte-equal to before; the other two updated. The task is `rebuild`, `succeeded` (#20), `requested_by` 21, `finished_at` set. `result` keys are exactly `files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported`, and each file item is exactly `source_file, import_id, outcome, policy_id, policy_version` (null when rejected). Three `rebuild` rows match the item ids | 2026-10-28 |
| CHK-M7-217 (3) | APP | W | g1 | PASS | Checksums of `agent`, `agent_package`, `os_info`, `scan`, `scan_job`, `scan_result` and `scan_schedule` are unchanged (owner-made agent, scan with queued and running jobs, schedule), and so is `audit_log` up to the entry before the rebuild. `agent_package`, `os_info` and `scan_result` are empty in this database, so they show only that nothing was written | 2026-10-28 |
| CHK-M7-217 (4) | APP | W | g1 | PASS | A removed server file and a removed upload file: both policies deleted (`deleted/<id>`), listed in `deleted_policy_ids` (result and `task.result`), two `policy.delete` with reason "file removed", `policy_deleted` +2. Row counts of `policy`, `plugin` and `family` never go down (no truncation, soft delete only) | 2026-10-28 |
| CHK-M7-217 (5) | APP | W | g1 | PASS | A database error at the third file (after a case (c) file was staged): the result is `failed` with no files, and the task is `failed` with `{"error": "The rebuild failed; the catalog was left unchanged."}` and `finished_at`. Catalog checksums are unchanged, no `bit_import` row (#98 (j)), and exactly one entry, `bits.rebuild` with state `failed`. No other counter moves; `policy_rebuilt` +1. The staged temp is discarded and `foreign.bit` stays. The log has only `rebuild failed: QueryCanceled` | 2026-10-28 |
| CHK-M7-217 (6) | APP | W | g1 | PASS | Exactly one `policy_rebuilt` per rebuild, one `policy_imported` per changed policy (2 of 3; 4 of 5), one `policy_import_rejected` per rejected file, `fail:rebuild` +1. An unchanged rebuild: three `success` rows (never skipped), and the only entry is `bits.rebuild` (no `policy.import`), catalog unchanged. The `bits.rebuild` actor is `user:21`, or `cli:root` with `requested_by` null for the CLI form | 2026-10-28 |
| crash window | APP | W | g1 | PASS | A deleted policy's `uploaded/policy-<id>.bit` is removed, listed in `result.removed_leftovers`, `task.result` and the alert's `removed_leftovers`, gets no row, and the policy stays deleted | 2026-10-28 |
| case (c) and r1 | APP | W | g1 | PASS | `uploaded/foreign.bit` with a new name → live at `uploaded/policy-<id>.bit` with its bytes and sha; `foreign.bit` removed, the only entry; no `policy.delete`, no `policy_deleted`; `deleted_policy_ids` empty in the result and `task.result`. A live case (a) `policy-<n>.bit` whose content names a new policy → the new policy is live at its own `policy-<id>.bit`, the holder stays live with its own file, nothing deleted | 2026-10-28 |
| accepted exception | APP | W | g1 | PASS | `uploaded/foreign.bit` and a server file, both naming the same new policy, in one rebuild. The policy lives in the server file (TS L524), not deleted, with no upload copy and no `.tmp-`. #15 order: `zz.bit` (the upload first) → the upload's copy is staged, then moved; `foreign.bit` removed, `uploaded/` empty. `aa.bit` (the server first) → `uploaded/foreign.bit` is refused as a server-folder copy, listed in `not_imported` and kept for #103 (lead confirmed) | 2026-10-28 |
| refused copy | APP | W | g1 | PASS | Ruling (5): a case (c) copy of a server-folder policy → `not_imported` in the result and `task.result`; no row; the file kept | 2026-10-28 |
| lock | APP | W | g1 | PASS | Another session's `pg_try_advisory_lock(hashtext('catalog'))` is false during the post-commit rename (TS L526). A rebuild started while another session holds the lock waits (task still `running` after 2 s), then ends `succeeded` once it is released | 2026-10-28 |
| logs | APP | W | g1 | PASS | No file name, policy name or Execute marker in the logs across a success and a failure | 2026-10-28 |
| plant b0 (r1) | APP | W | the `work.staged` check dropped | PASS (red) | 3 failed: case (c) relocated, and both r1 must-pass rows (`deleted/<id>` instead of `uploaded/policy-<id>.bit`) | 2026-10-28 |
| plant b1 | APP | W | `classify_upload` skipped (every file "other") | PASS (red) | 2 failed: the leftover row (imported, so revived), and case (a) | 2026-10-28 |
| plant b2 | APP | W | an error swallowed inside the rebuild transaction (commits) | PASS (red) | 2 failed: (5) `succeeded` instead of `failed`, and the log row | 2026-10-28 |
| plant b3 | APP | W | records also written inside the rebuild transaction | PASS (red) | 3 failed: duplicate rows in (2), unchanged and refused rows | 2026-10-28 |
| plant b4 | APP | W | the gone-file loop dropped | PASS (red) | 1 failed: (4) | 2026-10-28 |
| plant b5 | APP | W | recorded files skipped | PASS (red) | 6 failed, among them (1), (2), never-skipped | 2026-10-28 |
| plant b6 | APP | W | the lock released before the renames | PASS (red) | 1 failed: the lock row (`[True]`) | 2026-10-28 |
| plant b7 | APP | W | the leftover not unlinked | PASS (red) | 1 failed: crash window | 2026-10-28 |
| plant b8 | APP | W | no `bits.rebuild` / `policy_rebuilt` | PASS (red) | 6 failed: (1), (2), (5), (6), crash window, CLI actor | 2026-10-28 |
| plant b9 | APP | W | a staged upload not owned by the rollback | PASS (red) | 1 failed: (5) (a `.tmp-` left after the failure) | 2026-10-28 |

#### Acceptance

REQ-166 (1) → CHK-M7-216; (2)–(6) → CHK-M7-217 (2)–(6). Lead's list: one `policy_rebuilt`, a `policy_imported` per changed policy and a `policy_import_rejected` per rejected file → (6); an unchanged file gets no `policy.import` → (6); a database error midway → (5); a leftover → crash window; case (c) → case (c) and r1; `PolicyManagedOnServer` → refused copy; the r1 must-pass rows and the dropped-fix plant b0; the accepted exception in both orders. Every security row has a plant that went red.

#### Notes (no defect)

- In the accepted exception with the upload first, the staged copy is written and then removed within the same rebuild (moved to the server file). The end state is as required.

#### Revision 2 (2026-10-28): the task re-read after taking the lock

Ruling "TASK-158 test questions" (2). Right after taking the catalog lock, `rebuild.run` re-reads its task. If the task is missing or not `running`, it does nothing and returns `failed` with a `reason`. On a fresh copy of the tree with r2 (`-n 0`): `tests/test_rebuild_pg.py` **17/17 passed**, and with the start-up file 32/32. The must-pass race rows are in `test_catalog_startup_pg.py` (see `work/reports/TASK-158-test.md`):
- a task the start-up failed → `failed` with a reason, task still `failed`, no catalog change, no rows, no `bits.rebuild` and no `policy_rebuilt`;
- an unknown task id → the same.

Plant rr (the re-check dropped) → red, 2 failed. Verdict after revision 2: **PASS**.

### TASK-158


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-165 (1)–(4), (6); TS §4.1 L528, §4.2 L540, L542, §8.4 L1291; #27, #98 (g), #102 (d), #103; the crash-window ruling; decisions "TASK-158 test questions" (2026-10-28): (1) a changed `source_sha256` is repaired by the reconcile, with its `policy_imported` alert, and the check then finds nothing; (2) the start-up versus CLI-rebuild race is fixed as TASK-157 r2. Code under test: `bm/services/importer/startup.py` and `integrity.py`, with TASK-157 r2 in the same tree. New test file: `manager/tests/test_catalog_startup_pg.py` (15 tests, Linux only). Its own module database; each test owns its folders, and earlier live policies and running tasks are cleared first.

#### Runs

| Run | Command (W, `-n 0`, `CI=true`) | Count |
| --- | --- | --- |
| s0 (copy `/root/bstest-m7-t158`, before the rulings) | `pytest tests/test_catalog_startup_pg.py -s` | 15/15 passed, plus the race probe printed (below) |
| s1 (fresh copy `/root/bstest-m7-t158b`, with TASK-157 r2) | `pytest tests/test_catalog_startup_pg.py tests/test_rebuild_pg.py`, with the sha row re-pinned to ruling (1) and the race probe turned into two must-pass rows (ruling (2)) | **32/32 passed** (15 start-up and 17 rebuild), 0 failed, 0 errors, 0 skipped |
| plants | 11 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 11/11 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean (298 files) |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-230 order | APP | W | s1 | PASS | The steps run in order: `finish_interrupted`, `fail_running_tasks`, `reconcile`, `check`, then `alert` (only with a difference). Another session's `pg_try_advisory_lock(hashtext('catalog'))` is false at each step, and the lock is free afterwards | 2026-10-28 |
| REQ-165 (1) | APP | W | s1 | PASS | A committed temp is renamed (with the right bytes). An uncommitted temp, `.tmp-x` and a symlink temp are deleted, and the symlink target is untouched. `finished` = (1, 3); afterwards the only entry is `policy-<id>.bit`; no difference | 2026-10-28 |
| REQ-165 (2) | APP | W | s1 | PASS | A `running` task → `failed` with `{"error": "The manager stopped before the task ended."}` and `finished_at` = clock; a `succeeded` task is untouched | 2026-10-28 |
| REQ-165 (3) | APP | W | s1 | PASS | A file removed while down → its policy deleted; a file added → imported; no integrity alert afterwards | 2026-10-28 |
| REQ-165 (4) | APP | W | s1 | PASS | Owner corruptions: a deleted `policy_plugin` row → "its plugin count differs from its file"; a retired plugin → "a listed plugin is not active or not owned by it". One `catalog.integrity_check` entry by `system`: `catalog_integrity_failed`, `difference_count` 2, listing exactly those. A clean catalog (server and upload files) raises none. A refused upload copy → "the file is neither a policy's file nor a rejected import"; a rejected file (it has its `rejected` row) is not reported | 2026-10-28 |
| sha (ruling 1) | APP | W | s1 | PASS | A changed `source_sha256` → the reconcile re-imports the file: one `success` row, version +1, `source_sha256` restored, one `policy.import` (`policy_imported`) on that policy; no difference, no integrity alert | 2026-10-28 |
| crash window | APP | W | s1 | PASS | A deleted policy's leftover upload → removed, still deleted, no row; exactly one difference `{"subject": "uploaded/policy-<id>.bit", "check": "leftover of an interrupted delete"}` in the one alert; a live upload policy untouched. Only live uploads → no alert | 2026-10-28 |
| REQ-165 (6) | APP | W | s1 | PASS | With `session()` refusing twice, `run` retries (`retry_s` 0.05) and returns a report. It logs two lines `catalog start-up failed, retrying: OperationalError`, without the message text. With `stop` set while it waits (`retry_s` 30), it returns None within 2 s | 2026-10-28 |
| carry | APP | W | s1 | PASS | One file's import fails in the first attempt: at that moment the policy whose file is gone is still live (no deletion after a partial import pass). The retry completes: both new files imported and the gone one deleted | 2026-10-28 |
| race (ruling 2, TASK-157 r2) | APP | W | s1 | PASS | `start_task` (CLI), then the start-up marks it `failed`; then `rebuild.run` returns `failed` with a reason. The task stays `failed` with the start-up's error, and the catalog is unchanged although a file changed. There are no `bit_import` rows, no audit entries (no `bits.rebuild`), and no `policy_rebuilt`. An unknown task id gives the same | 2026-10-28 |
| race probe (r0 evidence) | APP | W | s0 | recorded | Before r2: the rebuild ran and committed, and its `bits.rebuild` said `succeeded`. `task.state` stayed `failed` ("The manager stopped before the task ended."), because `finish_task` is once-only. The catalog was consistent (a check afterwards found nothing); only the task row and the audit entry disagreed. This was the defect, fixed in r2 | 2026-10-28 |
| plant s1 | APP | W | the check before the reconcile | PASS (red) | 5 failed: the order, files changed while down alert ("its file is missing", unknown file), the sha row, the unknown and leftover rows | 2026-10-28 |
| plant s2 | APP | W | leftovers dropped from the differences | PASS (red) | 1 failed: crash window | 2026-10-28 |
| plant s3 | APP | W | `fail_running_tasks` skipped | PASS (red) | 3 failed: order, (2), race | 2026-10-28 |
| plant s4 | APP | W | an import error swallowed in the reconcile (a partial pass, then deletions) | PASS (red) | 1 failed: carry | 2026-10-28 |
| plant s5 | APP | W | the alert written for an empty list | PASS (red) | `test_a_clean_catalog_raises_no_alert`: `ValueError`. In the full file the retry rows loop forever (the retry is total) until the run's timeout | 2026-10-28 |
| plant s6 | APP | W | the lock released before the reconcile | PASS (red) | 1 failed: order (lock free at reconcile) | 2026-10-28 |
| plant s7 | APP | W | the plugin-count check off | PASS (red) | 1 failed: (4) | 2026-10-28 |
| plant s8 | APP | W | the plugin-state check off | PASS (red) | 2 failed: order (no alert step), (4) | 2026-10-28 |
| plant s9 | APP | W | rejected files reported as unknown | PASS (red) | 1 failed: the unknown-file row | 2026-10-28 |
| plant rr (157 r2) | APP | W | the task re-check after the lock dropped | PASS (red) | 2 failed: both race rows (`succeeded` instead of `failed`) | 2026-10-28 |

#### Acceptance

REQ-165 (1)–(4), (6) → the rows above; the order (#27, after the reconcile) and one lock → CHK-M7-230 order; #103 → (4) and crash window. REQ-165 (5) (the #102 (d) route answer during start-up) belongs to TASK-160. Rulings (1) and (2) → the sha and race rows, and plant rr drops the r2 re-check. Every security row has a plant that went red.

#### Notes (no defect)

- Impl reading 1 holds: a leftover removed in a failed attempt is missing from the final alert, but it was logged when it was removed.
- Impl reading 2 holds: a permanent error keeps retrying (plant s5 shows the loop); it fails closed.

### TASK-159


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-164 (1)–(5); TS §4.1 L526, L528; #102 (a)–(c); PD-33 (b); decisions "W6 pre-read rulings" (2) (r1: incoming paths first) and "#102 (c) wiring". Code under test: `bm/services/importer/inotify.py`, `watcher.py` (r1) and `own_changes.py`, with the writer hooks from TASK-155 r2, TASK-152 r1 and TASK-156 r2 in the same tree. New test file: `manager/tests/test_watcher_linux_pg.py` (17 tests). It runs only where inotify exists (Linux, W), against a real watcher thread (`poll=0.05`) with its own module database and a temporary folder per test. "Within 5 s" is a bound polled every 50 ms. Checks that nothing happened write a sentinel file afterwards and wait for its row, so no fixed sleeps decide them.

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t159` of the tree with r1 and the hooks, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| w0 | `pytest tests/test_watcher_linux_pg.py` (14 tests) | 14/14 passed |
| w1 | the same, after adding three rows that plants w3, w8 and h2 showed were needed | **17/17 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red (w3, w8 and h2 only after the new rows) |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-237 (1) | APP | W | w1 | PASS | REQ-164 (1): `cp` of `n.bit` into the server folder → a `success` row (`auto`, `imported_by` null) within 5 s; an edit → a second row with version +1; `rm` → the policy deleted within 5 s, one `policy.delete` by `system` with reason "file removed", `policy_deleted` +1. A file `mv`ed in (`IN_MOVED_TO`) imports; an `uploaded/foreign.bit` imports and is relocated to `uploaded/policy-<id>.bit` (case (c)) | 2026-10-28 |
| CHK-M7-237 (3) | APP | W | w1 | PASS | REQ-164 (3): ten chunks written over 2 s into one open file → exactly one row, `success`, the full file's sha, 10 plugins | 2026-10-28 |
| CHK-M7-237 (4) | APP | W | w1 | PASS | REQ-164 (4): two uploads (new, then a replacement) → only their two `manual` rows, no watcher row for the temp write or the rename (hook #1). An API delete adds nothing beyond its own `policy.delete` (hook #3). A start-up finish rename on its own, after a simulated restart cleared the stale record, adds no row (hook #2). An admin edit with another hash within 60 s of our rename is still imported (#102 (c) is by hash) | 2026-10-28 |
| CHK-M7-237 (2) | APP | W | w1 | PASS | REQ-164 (2), #102 (b): `n.txt`, `.n.bit`, `sub/n.bit`, `uploaded/.tmp-1-x`, a symlink `l.bit`, a FIFO `f.bit` and `\xff.bit` → no row; the unstorable name logs its one fixed line | 2026-10-28 |
| r1 mv | APP | W | w1 | PASS | `mv a.bit c.bit` (one batch, `IN_MOVED_FROM` + `IN_MOVED_TO`) → same policy id, `source_file` `c.bit`, exactly one `policy.move`, no `policy.delete` or `policy_deleted`; its queued job stays `queued` and its schedule stays enabled | 2026-10-28 |
| back again | APP | W | w1 | PASS | Delete-then-rewrite in one batch keeps the policy. With the lock held and the watcher seen waiting in `pg_locks` on the delete event, a rewrite before the lock is released → imported, not deleted (no `policy.delete`, no `policy_deleted`) | 2026-10-28 |
| #102 (a) rescan | APP | W | w1 | PASS | `uploaded/` removed and recreated → watched again (a file in it imports). `uploaded/` created after the watcher opened (none at open) → its `IN_CREATE` (`IN_ISDIR`) rewatches it, and a file in it imports | 2026-10-28 |
| failure | APP | W | w1 | PASS | One import raising `OSError` → one line `folder event failed: OSError` (no message text), then a reconcile after `RETRY` (patched to 0.2 s) imports the file | 2026-10-28 |
| lock | APP | W | w1 | PASS | With the catalog lock held elsewhere, a new file gets no row within 1 s; it imports once the lock is released | 2026-10-28 |
| CHK-M7-238 | APP | W | w1 | PASS | REQ-164 (5): with `inotify.available()` false, `open()` returns False after one line and `run()` returns at once (2 lines: one per open attempt). Windows itself is not run | 2026-10-28 |
| #102 (c) unit | CODE | W | w1 | PASS | `OwnChanges`: no hash computed without a record; a same-hash record drops one event, once; another hash isn't dropped; two removals drop two events, then none; a removal expires after 60 s (injected clock) | 2026-10-28 |
| plant w1 | APP | W | `IN_MODIFY` instead of `IN_CLOSE_WRITE` | PASS (red) | 1 failed: the chunked write (several rows) | 2026-10-28 |
| plant w2 | APP | W | the hidden-name test dropped | PASS (red) | 1 failed: `.n.bit` imported | 2026-10-28 |
| plant w3 | APP | W | the `IN_ISDIR` `uploaded` rescan dropped | PASS (red) after the new row | First run 14 passed: the removed folder's `IN_IGNORED` rescans anyway. With the "created after open" row: 1 failed, not within 5 s | 2026-10-28 |
| plant w6 | APP | W | the own-write check dropped | PASS (red) | 2 failed: the upload and API-delete rows (an extra `auto` row) | 2026-10-28 |
| plant w7 (r1) | APP | W | incoming-first order removed | PASS (red) | 1 failed: `mv` deletes the policy (`policy.delete`) and revives it | 2026-10-28 |
| plant w8 | APP | W | the "back again" import removed | PASS (red) after the new row | First run 14 passed: coalescing hides it. With the lock-held row: 2 failed (`policy.delete` written) | 2026-10-28 |
| plant w4 | CODE | W | `drop_write` ignores the hash | PASS (red) | 1 failed: the unit row | 2026-10-28 |
| plant w5 | CODE | W | a match never used up | PASS (red) | 1 failed: the unit row | 2026-10-28 |
| plant h1 (155 r2) | APP | W | `UploadStage.after_commit` records nothing | PASS (red) | 2 failed: the upload and API-delete rows | 2026-10-28 |
| plant h2 (155 r2) | APP | W | the finish rename records nothing | PASS (red) after the new row | First runs passed: the failed upload rename had already recorded the same path and hash just before its call. With the restart-simulating row: 1 failed (a `skipped` row) | 2026-10-28 |

#### Acceptance (TASK-159 row)

REQ-164 (1), (3) and (4) within 5 s → CHK-M7-237 (1), (3), (4). `n.txt`, `.n.bit` and `sub/n.bit` do nothing → CHK-M7-237 (2). No inotify → one line and `run` returns → CHK-M7-238. The lead's r1 row (`mv a.bit c.bit`: same id, no delete alert, no cancelled job, no disabled schedule) → r1 mv. Every security row has a plant that went red.

#### Notes (no defect)

- The removal hooks (TASK-152 r1 `remove_after_commit`, TASK-156 r2 `Relocate` and the leftover) can't be seen in behaviour. The path they remove belongs to no live policy (a deleted policy, a foreign file or a leftover), so the unhooked delete event does nothing either. They are kept as defence in depth.
- The impl's caveat holds: a record made just before a call that then fails can drop one real event at that path within 60 s. In practice that is the finish rename of the same bytes, which is harmless.

#### The three race plants, made deterministic (lead, 2026-10-28)

New rows: `test_an_overflow_triggers_a_rewatch_and_a_full_reconcile`, and `test_our_own_rename_is_recognised_whatever_the_writer_order[record_then_rename, rename_then_record]`.
- The overflow row feeds `_handle` a synthetic `Event(-1, IN_Q_OVERFLOW, "")`; `folders.reconcile` is a spy.
- The writer-order row is a writer stub. It holds the catalog lock across its rename into place, renames the same bytes, and waits until `pg_locks` shows the watcher blocked on the lock. In `rename_then_record` it records only then. With a correct watcher, neither order may give a row.

| Run (W, `/root/bstest-m7-t159`, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_watcher_linux_pg.py` | **20/20 passed**, 0 failed, 0 errors, 0 skipped |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| overflow | APP | W | the run above | PASS | A synthetic `IN_Q_OVERFLOW` → one full reconcile, both folders re-watched, `_handle` returns False | 2026-10-28 |
| plant o1 | APP | W | an overflow event skipped | PASS (red) | 1 failed: the reconcile spy saw no call | 2026-10-28 |
| own change, both orders | APP | W | the run above | PASS | Record-then-rename and rename-then-record, both under the writer's lock: no row. The watcher checks the record after taking the lock | 2026-10-28 |
| plant o2 | APP | W | the own-change check moved before the lock | PASS (red) | 2 failed. `rename_then_record`: an extra `skipped` row, the race reproduced. `record_then_rename`: the watcher drops the event without waiting on the lock, so the harness's wait ends after 5 s (a harness effect, not a row) | 2026-10-28 |
| plant o3 | APP | W | `UploadStage.after_commit` records after its rename | equivalent (20 passed) | The writer holds the catalog lock and the watcher checks only after taking it, so recording after the call is still recognised. The `rename_then_record` row proves this. It goes red only together with o2 (shown above) | 2026-10-28 |
| overflow, real | — | — | — | NOT RUN | A real `IN_Q_OVERFLOW` needs more than `max_queued_events` (16,384) queued events; the synthetic row covers the branch | 2026-10-28 |

Verdict unchanged: **PASS**.

### TASK-160


Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-164, REQ-165 (5) (the CatalogStarting gate; the 503 itself is TASK-162–164's), REQ-172; TS §4.1 L526, L528, §4.2 L540; #102 (d), (e); CHK-M2-257 (SIGTERM within 10 s with the database refusing; TASK-071 r1 ruling). Code under test: `bm/services/importer/service.py` (r1: `STOP_WAIT_S` 2 s per thread), `bm/runtime.py` (`Catalog`, `Runtime.catalog`), `bm/cli/serve.py` (`ServeLifecycle` starts and stops the catalog; `build_runtime`). New test files: `manager/tests/test_catalog_service_pg.py` (11 tests: fakes for the gate, worker and stop; PostgreSQL for the rebuild and lock rows; the real watcher for the reconcile row) and `manager/tests/test_serve_catalog_linux.py` (2 tests, the real `serve`).

#### Rounds

| Round | Run (W, `-n 0` or `-n 2` per the memory floor, `CI=true`) | Count |
| --- | --- | --- |
| 1 (r0) | `test_catalog_service_pg`, `test_serve_catalog_linux`, `test_serve_linux`, `test_serve_scheduler_linux`, `test_runtime` (`-n 2`) | 79/80 passed, **1 failed**: `test_serve_scheduler_linux.py::test_sigterm_with_the_database_refusing_exits_promptly[closed-port]`, 10.3 s against the 10 s bound. A re-run alone gave 10.2 s for `wrong-password`. A plant without the catalog in `ServeLifecycle` passed 2/2, so the catalog's stop caused it: up to 10 s waiting for a thread blocked in `db.session()`. Sent to impl-manager-m7 → **FAIL** |
| 2 (r1) | the failing test by node id | **2/2 passed** |
| 2 (r1) | the whole set above plus `test_cli_bits_pg.py` (TASK-166) (`-n 0`) | **92/92 passed** (80 for this task), 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red |
| static (L) | whole-tree ruff, ruff format, `mypy --strict` (CI form) | clean (304 files) |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-242 gate | APP | W | round 2 | PASS | Until `startup.run` returns, `upload`, `delete` and `start_rebuild` each raise `CatalogStarting`, nothing reaches the importer and the shipper isn't woken. After it returns, each goes through with its arguments, and the shipper is woken after each. The texts are the #102 (d) ones ("The catalog is starting; retry shortly.", `Retry-After` 10). A stop before the start-up ends leaves the gate closed. Without a watcher (open False) the gate still opens | 2026-10-28 |
| watcher order | APP | W | round 2 | PASS | Fakes: `watcher.open`, `startup.run`, `startup.done`, then `watcher.run`. Real watcher: a file written after the start-up reconcile's import pass, before the gate opens, is imported afterwards (queued since the watch was added first) | 2026-10-28 |
| worker | APP | W | round 2 | PASS | Three `start_rebuild` calls return at once: the task row is written on the caller's thread. The rebuilds run one at a time (peak 1) on `catalog-rebuild`. A failing run is logged by type (`rebuild did not start: OSError`, no message) and the next one runs. On PostgreSQL the real start-up imported the folder file, and a started rebuild's task ended `succeeded` with `requested_by` 51 | 2026-10-28 |
| stop | APP | W | round 2 | PASS | With the worker blocked (a fake, and also the real catalog lock held by another session), `stop(wait_s=1)` returns in about 1 s. It logs `catalog thread still running at stop: catalog-rebuild`, the watcher's `run` has returned, and the blocked task stays `running`; the real-lock one finishes once the lock is released. Both threads are daemons. `2 × STOP_WAIT_S ≤ 5` (r1: 2 s), so both joins fit well inside the 10 s SIGTERM bound | 2026-10-28 |
| lifecycle | APP | W | round 2 | PASS | `ServeLifecycle.start`: db, shipper, flusher, scheduler, then catalog. `stop`: catalog first, then scheduler, flusher, shipper, cipher and db | 2026-10-28 |
| CHK-M7-243 | APP | W | round 2 | PASS | Real `serve` with `BITSCAN_BITS_DIR` a temporary folder: the folder file gets its `success` row within 30 s, the log says `catalog ready`, and SIGTERM exits 0. With the database down (a closed port): `/healthz` stays 200 over 3 s, the catalog never becomes ready and the file gets no row, and SIGTERM exits 0 within 15 s | 2026-10-28 |
| CHK-M2-257 | APP | W | round 2 | PASS | The existing gate: SIGTERM within 10 s with the database refusing the login or down, 2/2 on r1 (it failed on r0) | 2026-10-28 |
| plant g1 | APP | W | the gate check removed | PASS (red) | 2 failed: a call before ready succeeded | 2026-10-28 |
| plant g2 | APP | W | ready set before the start-up | PASS (red) | 3 failed | 2026-10-28 |
| plant g3 | APP | W | the watcher opened after the start-up | PASS (red) | 3 failed, among them the real "changed during the reconcile" row (missed) | 2026-10-28 |
| plant g4 | APP | W | unbounded `join()` | PASS (red) | 1 failed: stop did not return within 10 s with the worker blocked | 2026-10-28 |
| plant g5 | APP | W | non-daemon threads | PASS (red) | 1 failed | 2026-10-28 |
| plant g7 | APP | W | the rebuild run on the request thread | PASS (red) | 1 failed: `MainThread` instead of `catalog-rebuild`. The whole file deadlocks against the held lock, so it was run on that row | 2026-10-28 |
| plant g6 | APP | W | `ServeLifecycle.stop` doesn't stop the catalog | PASS (red) | 1 failed: lifecycle order | 2026-10-28 |
| plant g8 | APP | W | `ServeLifecycle.start` doesn't start the catalog | PASS (red) | 2 failed: lifecycle, and `serve` imports nothing | 2026-10-28 |
| plant sw (r1) | APP | W | `STOP_WAIT_S` back to 10 s | PASS (red) | 3 failed: both CHK-M2-257 cases (10.3 s) and the budget pin | 2026-10-28 |

#### Acceptance (TASK-160 row)

- With fakes, refused before and succeeding after → gate.
- A started rebuild runs on the worker and its task ends `succeeded` → worker.
- `ServeLifecycle.stop` stops the watcher and waits for the worker, bounded even with the worker blocked on the lock → stop and lifecycle.
- On Linux, `serve` imports at start-up and `/healthz` stays 200 with the database down → CHK-M7-243.
- REQ-165 (5) → the gate. The watcher opening before the reconcile → watcher order.

Every security row and the gate have a plant that went red.

#### Notes (no defect)

- Without `BITSCAN_BITS_DIR` and with `/var/lib/bitscan/bits` missing, as in the older `serve` tests in WSL, the start-up retries every 10 s and the catalog stays closed. It fails closed, and each retry logs only the error type.
- Shared venv: `/root/venv-m7`'s editable install points at the last folder installed. Console-script subprocesses (`run_cli`) therefore import that tree, not the plant copy. I set `PYTHONPATH` for those plants and told main.

#### Shared-venv check (lead, 2026-10-28)

No TASK-160 row or plant uses the console script. The `serve` rows (g6, g8, CHK-M7-243) start `serve_main` through `python -c` from the tree under test, and the service rows run in-process. The plant results stand. Of my earlier M7 files only `test_cli_bits_pg.py` uses `run_cli` (see TASK-166). The module databases' `db migrate` also uses the console script, but no M7 change touches migrations.

### TASK-161


Tester: tester-m7, 2026-10-27. REQ-168 (1) to (5), REQ-169 (1) to (5), REQ-174 (2), REQ-178; TS §6.2 L1100 to L1102, §4.3 L546 to L548, §6.3, §6 L1056; #9, #98 (a) to (c), #101. Files under test: `bm/services/importer/profiles.py`, `bm/api/user/policies.py`, `bm/api/user/__init__.py`, `manager/openapi.json`. New test file `manager/tests/test_policies_api_pg.py` (59 tests) on the M2 users-API environment (real sink gate and shipper). Policies are built through the TASK-151 store. One tester-owned pin updated: `test_invariants_m3.py::test_no_query_parameter_can_switch_inventory_off`. It now pins `GET /policies` to exactly {`limit`, `cursor`, `status`} (TS §6.2 L1100), and the general set is unchanged.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t161, `CI=true`, `-n 2`) | `pytest tests/test_policies_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_catalog_repo_pg.py` | 152/154 passed, 2 failed: `test_non_json_body_is_400` (my test bug: `headers` passed twice) and the route-walk query pin (the expected new `status` parameter) |
| r1 (m7t-t161b) | those two node ids after the fixes | 2/2 passed |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-251 | APP | W | r0 | PASS | REQ-169: of 3 enabled, 2 disabled (one by override) and 1 deleted, the list holds 5, `enabled` 3, `disabled` 2; `status` `deleted`, `ENABLED`, `` and a list → 400; N + 1 with limit N (1, 2, 5), each once in name order; limit 0, 501, `a`, garbage cursors and a `/users` cursor → 400; item keys exactly #98 (a) in order, integer ids, `Z` timestamps, `plugin_count`; detail = item + `deleted_at` + `plugins` (#98 (b) keys in order, file order, `display_name` `<family> - <plugin>`, `execute` visible to a viewer); a deleted policy's detail shows `deleted_at` and its plugins (#9); `abc`, `+1`, `1.0`, `1_0`, `-1`, ` 1`, `1e3`, 21 digits, `١` → 400; `0`, 2^62, 2^63, 20 nines → 404; hostile text byte-identical as JSON; viewer session and `bsk_` → 200 | 2026-10-27 |
| CHK-M7-250 | APP | W | r0, r1 | PASS | REQ-168: each body sets the stated columns, for an admin session and an admin `bsk_`; the response is the item; every PATCH writes one `policy.status_change` (`by` patch, actor `user:<id>`); 14 other bodies (`status_overridden` true, `execute`, both keys, `{}`, `on`, `Enabled`, nulls, `"false"`, `0`, an extra key, a list, a string, `null`) and a non-JSON body → 400, nothing changed and no entry; a re-enable by PATCH and an override cleared onto an enabled file each raise one `policy_reenabled`; a disable, a no-op and a clear onto a disabled file raise none; deleted → 409 `conflict` with no entry; unknown and `0` → 404; viewer and operator (session and API) → 403 `forbidden`; a restricted admin session → 403 `totp_enrolment_required`; a file import after a PATCH disable stays disabled (version 2); PATCH never changes a plugin row | 2026-10-27 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token and a garbage `bsu_` → 401 problem+json on all three operations, and nothing is audited | 2026-10-27 |
| CHK-M7-281 | APP | W | r0, r1 (`test_invariants_m3.py`) | PASS | the route walk has the three operations; no request schema carries a command; the query-parameter pin is updated as above | 2026-10-27 |
| G6 | CODE | W | `test_openapi.py` (r0) | PASS | the export is byte-identical to `manager/openapi.json` | 2026-10-27 |
| CHK-M7-161-rbac | APP | W | plant: PATCH role lowered to operator | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-353 | APP | W | plant: re-enable decided from the new row (never alerts) | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-361 | APP | W | plant: `execute` added to the PATCH body | PASS (red) | 3 failed: G6 export differs, and `test_no_request_schema_carries_a_command` (G34) flags `PATCH /policies/{id}` `execute` | 2026-10-27 |
| route-group plant | — | — | — | NOT RUN (by design) | the token-prefix check is per router in the M2 code, not in this task; the rows above prove it on these routes | 2026-10-27 |

### TASK-162


Tester: tester-m7d, 2026-10-28. REQ-170 (1) to (5), REQ-163 (1), (3), (5), REQ-174 (2), REQ-177 (upload rows). Spec: TS §6.2 L1103, L1084 (upload is not sensitive: an admin `bsk_` may upload; no TOTP session, no sink gate), §6.3 L1137 and L1138, §6 L1056, §4.1 L522; #57, #98 (d) and (j), #99 (a) to (e), #101, #102 (d); plan `work/plans/TASK-162.md` §2 to §5; the TASK-155 carry (a stale temp file gives 503). Lead ruling 2026-10-28: the parser's decoded `filename` value is the #99 (d) input.

Files under test: `bm/api/user/policy_import.py`, `bm/app.py` (cap entry), `bm/api/user/__init__.py`, `manager/openapi.json`. Product hashes tested (first 16 hex): `policy_import.py` 832b2584a7491aff, `app.py` 8c137ba87e3332dd, `openapi.json` 2eacec4e800031e4.

New tester files:
- `manager/tests/catalog_api.py`, a shared environment for TASK-162 to 164. It runs on a module-own PostgreSQL (`own_migrated_server`) with the real `CatalogService`, start-up sequence, sink gate (switchable sink behind the M2 shipper), auth and rate limiter, plus a temporary bits folder. Only the watcher is stubbed (it never opens).
- `manager/tests/test_policy_import_api_pg.py`, 91 tests.

One existing test was updated:
- `manager/tests/test_app_hardening.py`: the `bit` class value is now `5 * MIB + 64 * 1024` and its "+1" refusal case moved with it. Both follow #99 (a) and plan §2, the approved change in this task. The file part stays capped at 5 MiB, and the new suite tests that cap at the route. No gate was lowered.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH=/root/bstest-m7d/manager`) | `pytest tests/test_policy_import_api_pg.py tests/test_policy_delete_api_pg.py tests/test_rebuild_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_body_caps.py tests/test_policies_api_pg.py tests/test_imports_api_pg.py tests/test_app.py tests/test_app_hardening.py tests/test_module_imports.py` | 586/588 passed, 2 failed, 0 errors, 0 skipped |
| r0 failures (test bug) | `test_app_hardening.py::test_cap_classes_are_the_spec_values`, `::test_registry_refuses_bad_entries_at_app_creation[bit+1]`. Expected the old `bit` value of 5 MiB; actual 5 MiB + 64 KiB (#99 (a)) | fixed in the test (above) |
| r1 (W) | the two failing node ids | 2/2 passed |
| r2 (W) | `pytest tests/test_app_hardening.py` (shares the cap fixtures) | 53/53 passed |
| plants (W, `-n 0`, throwaway copy `/root/bstest-m7d-mut`, each file restored after) | `pytest tests/test_policy_import_api_pg.py -k <rows>` | 16/16 plants red (rows below) |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every run set `PYTHONPATH` to the tree under test, so the `db migrate` subprocess (the only console-script call) imported that tree and not the shared venv's editable install. I checked this: a subprocess under the same environment reports `/root/bstest-m7d/manager/bitscan_manager`. Plants ran with `PYTHONPATH=/root/bstest-m7d-mut/manager`. No re-run is needed for the shared-venv hazard.
- No test container was left behind (`docker ps -a` shows none of mine).

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-262 (1) | APP | W | r0 | PASS | REQ-170 (1), #98 (d). Admin session and admin `bsk_` each get 200; the keys are exactly `import_id, outcome, policy_id, policy_name, policy_version, plugins_added, plugins_updated, plugins_retired, errors` in that order, with integer ids, version 1, 2 added, 0 updated, 0 retired and `errors` `[]`. The `bit_import` row has mode `manual`, outcome `success`, `imported_by` = the caller, the client `file_name` and the file SHA-256. The file is stored only as `uploaded/policy-<id>.bit`, byte-identical, and `source_file`/`source_sha256` match. There is one `policy.import` entry (actor `user:<id>`, target `policy:<id>`, `alert: true`), and `policy_imported` rises by 1. The SR §1.1 example uploads; the same bytes again give `success` (manual never skips) with the version unchanged; a changed file gives version + 1, same id, and the stored file is replaced | 2026-10-28 |
| CHK-M7-262 (1) rejected | APP | W | r0 | PASS | `content/bit003-on.bit` gives 200 `rejected`, policy fields null, `errors` equal to the stored row (four keys each), mode `manual`, nothing on disk, `policy_import_rejected` + 1. BIT003 and BIT016 come back together in line order. `warnings-only.bit` gives `success` with BIT101 and BIT103 in `errors` (#110). `rm -rf /tmp/x` gives BIT102 with nothing stored. An empty part gives a recorded BIT001 rejection | 2026-10-28 |
| CHK-M7-262 REQ-163 (3) | APP | W | r0 | PASS | A rejected re-upload of a live policy leaves the catalog checksums, jobs, schedules and tasks unchanged, adds only its `bit_import` row, and leaves `uploaded/policy-<id>.bit` byte-identical | 2026-10-28 |
| CHK-M7-262 REQ-163 (5) | APP | W | r0 | PASS | After the start-up reconcile imports a server-folder file, an upload with that `PolicyName` gets 409 `policy_managed_on_server` with the fixed detail. There is no `bit_import` row, no file and no catalog change. Exactly one audit entry is written (`policy.import_refused`, actor `user:<id>`, no alert), and the alert counters are unchanged (#99 (e)) | 2026-10-28 |
| CHK-M7-262 REQ-170 (2) | APP | W | r0 | PASS | A valid file of exactly 5,242,880 bytes gives `success` and is stored byte-identical. 5,242,881 bytes gives 413 `too_large` with `Connection: close`, no `bit_import` row, no audit entry and nothing on disk (#99 (b)). A body of exactly 5,308,416 bytes (small part plus an epilogue) gives 200; 5,308,417 gives 413 with no row. A 6 MiB `Content-Length` gives 413 with 0 bytes pulled; a 6 MiB chunked body gives 413 after the crossing chunk (5,308,416 < pulled ≤ + 64 KiB) | 2026-10-28 |
| CHK-M7-262 token first | APP | W | r0 | PASS | No token, `bsa_`, `bse_`, a garbage `bsk_`, viewer `bsk_` and operator `bsk_`, each with a 6 MiB body declared by `Content-Length` or sent chunked: 401 or 403 with **0 body bytes pulled** (raw ASGI receive counter) | 2026-10-28 |
| CHK-M7-262 other caps | APP | W | r0 | PASS | `PATCH /policies/{id}` with a 1 MiB + 1 JSON body gives 413. `POST /scans`, `POST /policies/rebuild` and `POST /users` with a 2 MiB body give 413. The policy is unchanged | 2026-10-28 |
| CHK-M7-262 REQ-170 (3) | APP | W | r0 | PASS | 23 malformed bodies each give 400 `invalid_request` with exactly the fixed detail "The body must be multipart/form-data with one part named file.": a JSON body, `text/plain`, `multipart/mixed`, no Content-Type, no boundary, an empty boundary, a 71-byte boundary, the wrong boundary, no closing boundary, two `file` parts, an extra field before or after, a part named `files` or `FILE`, no Content-Disposition, `attachment`, no `name`, 17 headers, an 8,193-byte header value, no parts, an empty body, garbage, and a raw CR in the filename. A canary placed in the body and in the file name is in neither the response nor any log record (`canary.sweep`). There is no `bit_import` row, no audit entry and no file. Accepted edges (200 `success`): a 70-byte boundary, `Multipart/Form-Data` with a quoted boundary, `Form-Data` disposition, 16 headers, an 8,192-byte header value, the part's own `Content-Type: image/png` ignored, no part Content-Type, an epilogue. A standard `httpx` `files=` upload works, also with CR, LF, `"`, NUL and `../../x` names | 2026-10-28 |
| CHK-M7-262 REQ-163 (1) | APP | W | r0 | PASS | Each of the 23 `bits/tests/hostile_names.json` names without a raw CR (names and raw-byte hex entries: `../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, 5,000 characters, NUL, LF, `<script>`, U+202E, `C:\Windows\x.bit`, `con.bit`, `.tmp-1-<64 zeros>`, `policy-1.bit`, empty, `  .bit`, BEL, DEL, 300 × é, `ff fe`, `c3 28`, `ed a0 80`) is uploaded with a fresh policy. The bits tree afterwards is exactly `{uploaded/policy-<id>.bit: data}`. `file_name` equals the #99 (d) form computed by the test (UTF-8 with replacement, C0 and DEL to U+FFFD, 255 characters), with no control character, and `source_file` is `uploaded/policy-<id>.bit`. No name over 6 characters reaches a log line. A missing name is stored as `""`. Per the lead ruling, `C:\Windows\x.bit` is stored as `x.bit` and `a\"b.bit` as `a"b.bit` | 2026-10-28 |
| CHK-M7-262 REQ-170 (4) | APP | W | r0 | PASS | Operator and viewer, each with a session and with `bsk_`: 403 `forbidden`, nothing changed and no audit entry. An admin without TOTP (restricted session, and API token): 403 `totp_enrolment_required`. An admin `bsk_` uploads during a 16-minute sink outage (upload is not sensitive, L1084) | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized` problem+json, with nothing changed | 2026-10-28 |
| CHK-M7-262 503 | APP | W | r0 | PASS | A catalog service whose start-up has not ended gives 503 `about:blank`, `Retry-After: 10`, detail "The catalog is starting; retry shortly.", with no row and no file; with no token it still gives 401 first. No catalog service gives 503 `about:blank`. A stale `uploaded/.tmp-<id>-<sha>` gives 503 `about:blank` "The policy file could not be stored; retry shortly.", no `bit_import` row (#98 (j)), the planted file untouched, the stored file still v1, and the policy row unchanged | 2026-10-28 |
| CHK-M7-262 in memory | APP | W | r0 | PASS | `tempfile.SpooledTemporaryFile`, `TemporaryFile`, `NamedTemporaryFile`, `mkstemp`, `mkdtemp`, `starlette.formparsers.SpooledTemporaryFile`, `python_multipart.FormParser`, `File` and `Request.form` are all patched to raise. A 2 MiB upload still gives `success` | 2026-10-28 |
| CHK-M7-262 REQ-170 (5) | CODE | W | r0 | PASS | The request body is `multipart/form-data`, required, with exactly `file: {type: string, format: binary}`, `required: [file]` and `additionalProperties: false`, and no parameters. 400, 401, 403, 409, 413 and 503 are problem+json. `ImportResult` has the #98 (d) keys in order, `additionalProperties: false`, and `outcome` enum `success`/`rejected` | 2026-10-28 |
| G6 | CODE | W | r0 (`test_openapi.py`) | PASS | A fresh export is byte-identical to `manager/openapi.json`, and two exports are byte-identical | 2026-10-28 |
| CHK-M7-281 | APP | W | r0 (`test_invariants_m3.py`) | PASS | The route walk passes with the M7 operations | 2026-10-28 |
| CHK-M7-324 (a) | APP | W | plant: the `/api/v1/policies/import` `RouteCap` removed (back to 1 MiB) | PASS (red) | 3 failed: the exactly-5-MiB part, the exact body cap, the 6 MiB refusal | 2026-10-28 |
| CHK-M7-324 (b) | APP | W | plant: `bit` class raised to 6 MiB | PASS (red) | 2 failed: the body cap + 1 accepted; the 6 MiB `Content-Length` not refused unread | 2026-10-28 |
| CHK-M7-324 (c) | APP | W | plant: part cap `MAX_BIT_BYTES + 1` | PASS (red) | 1 failed: `test_a_part_one_byte_over_5_mib_is_413_with_no_row_and_nothing_on_disk` | 2026-10-28 |
| CHK-M7-345 | APP | W | plant: `require_role("operator")` | PASS (red) | 3 failed: operator session and `bsk_` 403 rows, and the operator token-first row | 2026-10-28 |
| CHK-M7-162-auth | APP | W | plant: the auth dependency replaced by a fixed admin principal | PASS (red) | 16 failed: every wrong-group 401, every token-first row, operator and viewer 403, the admin-without-TOTP rows | 2026-10-28 |
| CHK-M7-162-first | APP | W | plant: a dependency reads `request.body()` before the auth dependency | PASS (red) | 6 failed: every `test_no_body_byte_is_read_before_the_token_and_role_check` case | 2026-10-28 |
| CHK-M7-162-echo | APP | W | plant: the 400 detail appends the body | PASS (red) | 22 failed: the malformed cases (canary found) | 2026-10-28 |
| CHK-M7-162-log | APP | W | plant: `log.warning("upload from %s", client_name)` | PASS (red) | 16 failed: every hostile name over 6 characters and the canary row | 2026-10-28 |
| CHK-M7-358 | APP | W | plant: `uploads.py` names the stored file after the client name (sanitised to stay in the folder, a harmless payload) | PASS (red) | 21 failed: both admin-upload rows and the hostile-name rows | 2026-10-28 |
| CHK-M7-162-spool | APP | W | plant: `await request.form()` (Starlette's spooling parser) | PASS (red) | 1 failed: `test_the_upload_is_parsed_in_memory` | 2026-10-28 |
| CHK-M7-162-case | APP | W | plant: `kind.lower()` dropped | PASS (red) | 1 failed: `test_the_accepted_edges_of_the_multipart_rules` | 2026-10-28 |
| CHK-M7-162-oserror | APP | W | plant: the `OSError` → 503 branch removed | PASS (red) | 1 failed: the stale-temp row | 2026-10-28 |
| CHK-M7-162-starting | APP | W | plant: `Retry-After` dropped from the start-up 503 | PASS (red) | 1 failed: the start-up row | 2026-10-28 |
| CHK-M7-162-409 | APP | W | plant: `PolicyManagedOnServer` mapped to 400 | PASS (red) | 1 failed: the server-folder row | 2026-10-28 |
| CHK-M7-162-sensitive | APP | W | plant: `require_totp_session()` on the upload (over-restrictive) | PASS (red) | 2 failed: the admin `bsk_` upload and the sink-outage upload | 2026-10-28 |

#### Acceptance

TASK-162 row: "Through the API on PostgreSQL: REQ-170 (1)–(5) and REQ-163 (1) and (5) hold; nothing is spooled to disk while parsing (a `tempfile` spy); every other route keeps its 1 MiB cap."
- REQ-170 (1): CHK-M7-262 (1), rejected.
- REQ-170 (2): CHK-M7-262 REQ-170 (2), token first.
- REQ-170 (3): CHK-M7-262 REQ-170 (3).
- REQ-170 (4): CHK-M7-262 REQ-170 (4), CHK-M7-282.
- REQ-170 (5): CHK-M7-262 REQ-170 (5), G6.
- REQ-163 (1): CHK-M7-262 REQ-163 (1).
- REQ-163 (5): CHK-M7-262 REQ-163 (5).
- REQ-163 (3) is also held: CHK-M7-262 REQ-163 (3).
- Spool spy: CHK-M7-262 in memory. Other caps: CHK-M7-262 other caps.

Every security row has a plant that went red: RBAC (CHK-M7-345), token type (auth plant), token before body, body cap (CHK-M7-324 a to c), no echo, no log, client name as path (CHK-M7-358).

#### Notes (no defect)

- **python-multipart's reading of `filename`:** it drops an IE-style Windows path (`C:\Windows\x.bit` → `x.bit`) and unescapes quoted pairs. The lead ruled this conforming on 2026-10-28 (RFC 7578 §4.2), and the tests expect it.
- **A preamble before the first boundary is refused with 400.** RFC 2046 allows one, but #99 (c) does not ask for it, browsers do not send one, and the refusal is safe. An epilogue after the closing boundary is accepted.
- **A raw CR inside the part header** (for example in the filename) is malformed multipart and gets 400. Standard clients percent-encode CR, LF and `"` (httpx sends `%0D`), and those names are stored as metadata only.
- **`test_security_m7.py` (TP-M7-30) is not written here.** It belongs to the M7 gate. The upload security rows are in `test_policy_import_api_pg.py`, ready to be referenced.

### TASK-163


Tester: tester-m7d, 2026-10-28. REQ-171 (1) to (4); REQ-167 (1) to (3) seen through the route; REQ-174 (2); REQ-177 (delete rows). Spec: TS §6.2 L1104 (admin, TOTP session), L1084, §4.3 L550, §5.3 L1051, §6 L1056; #1 (agreed: also refused during a sink outage), #9, #98 (e) and (k), #101 (`policy.delete`, `policy_deleted`), #102 (d).

File under test: `bm/api/user/policies.py` (the `DELETE /{id}` route; hash prefix 87b774b41036de02), plus `manager/openapi.json` from the combined W8 regeneration.

New tester file: `manager/tests/test_policy_delete_api_pg.py` (27 tests), on the shared `manager/tests/catalog_api.py` environment (see `work/reports/TASK-162-test.md`). That environment has the real catalog service and start-up, the real sink gate and auth, and a module-own PostgreSQL. Fixture scans, jobs and schedules are written as owner.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` = the tree under test) | the TASK-162 r0 command, which includes `tests/test_policy_delete_api_pg.py`, `tests/test_policies_api_pg.py`, `tests/test_openapi.py` and `tests/test_invariants_m3.py` | 586/588 passed, 2 failed (`test_app_hardening.py`, TASK-162's cap value, fixed there; 2/2 and 53/53 on re-run), 0 errors, 0 skipped. Of these, 27/27 are in this file and every `test_policies_api_pg.py` test passed |
| plants (W, `-n 0`, throwaway copy, file restored after each) | `pytest tests/test_policy_delete_api_pg.py -k <rows>` | 7/7 plants red |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every subprocess (`db migrate`) imported the tree under test through `PYTHONPATH`, so the shared-venv editable install was not used.
- No container was left behind.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-271 REQ-171 (1) 204 / REQ-167 (1) | APP | W | r0 | PASS | Setup: a policy uploaded through the route, with owner-written jobs `queued`, `dispatched` and `running` and two schedules (one enabled). An admin TOTP session gets 204 with an empty body. Then: the row is kept with `deleted_at` set and `source_file` `deleted/<id>`; every plugin is `retired`; only the queued job is `cancelled`, with `finished_at` set, while `dispatched` and `running` are unchanged; both schedules have `enabled = false`; `uploaded/policy-<id>.bit` is gone; exactly one `policy.delete` entry is written (actor `user:<id>`, target `policy:<id>`, `alert: true`, `alert_kind` `policy_deleted`); `bitscan_alerts_total{policy_deleted}` rises by 1. An unrelated policy is unchanged | 2026-10-28 |
| CHK-M7-271 REQ-167 (3) | APP | W | r0 | PASS | After the delete, `GET /policies?limit=500` no longer lists it, and `GET /policies/{id}` gives 200 with `deleted_at` and `source_file` `deleted/<id>` (#9). A re-upload of the same name revives the same `policy_id` | 2026-10-28 |
| CHK-M7-271 REQ-171 (1) refusals | APP | W | r0 | PASS | Each refusal leaves the catalog, `bit_import`, task, job and schedule checksums and the bits tree unchanged. Admin `bsk_`: 403 `totp_session_required`. An admin session without TOTP verification: 403. Operator and viewer sessions: 403 `forbidden`. Operator and viewer `bsk_`: 403 | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized`, with nothing changed | 2026-10-28 |
| CHK-M7-271 REQ-171 (2) | APP | W | r0 | PASS | 14:59 into a sink outage the delete is still allowed (204). At 15:00, 503 `audit_sink_unavailable`, nothing changed and the policy not deleted. After the queue drains, the same delete gives 204 (#1) | 2026-10-28 |
| CHK-M7-271 REQ-171 (3) | APP | W | r0 | PASS | A server-folder policy (imported by the start-up reconcile) gives 409 `policy_managed_on_server` with the fixed detail. Nothing changed, the server file is still there, and there is no `policy_deleted` alert | 2026-10-28 |
| CHK-M7-271 REQ-171 (4) | APP | W | r0 | PASS | Unknown ids (max + 1000, `0`, 2^63 − 1, 2^63, 10^19): 404 `not_found` with nothing changed. A second delete of a deleted policy: 409 `conflict` with no second alert. `abc`, `+1`, `-1`, `1.0`, `1e3`, ` 1`, `0x10` and 21 digits: 400 `invalid_request` | 2026-10-28 |
| CHK-M7-271 503 | APP | W | r0 | PASS | Before the start-up ends: 503 `about:blank`, `Retry-After: 10`, the fixed #102 (d) detail, nothing changed. With no catalog service: 503 `about:blank` | 2026-10-28 |
| CHK-M7-271 OpenAPI | CODE | W | r0 | PASS | 204 with no content; 400, 401, 403, 404, 409 and 503 as problem+json; no request body. G6 byte-identical (`test_openapi.py`) | 2026-10-28 |
| CHK-M7-341 | APP | W | plant: `TOTP_ADMIN` → `require_role("admin")` | PASS (red) | 2 failed: `test_an_admin_api_token_is_refused_totp_session_required` and the sink-gate row | 2026-10-28 |
| CHK-M7-343 | APP | W | plant: `require_totp_session(sink_gate=False)` | PASS (red) | 1 failed: `test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains` | 2026-10-28 |
| CHK-M7-346 | APP | W | plant: `require_totp_session("operator")` | PASS (red) | 1 failed: `test_operator_and_viewer_are_refused[operator-session]` | 2026-10-28 |
| CHK-M7-163-auth | APP | W | plant: the auth dependency replaced by a fixed admin principal | PASS (red) | 10 failed: every wrong-group 401, the API-token row, every operator and viewer row | 2026-10-28 |
| CHK-M7-163-409 | APP | W | plant: `PolicyAlreadyDeleted` mapped to 404 | PASS (red) | 1 failed: `test_an_unknown_id_is_404_and_an_already_deleted_one_is_409` | 2026-10-28 |
| CHK-M7-163-managed | APP | W | plant: `PolicyManagedOnServer` swallowed (204) | PASS (red) | 1 failed: `test_a_server_folder_policy_is_409_and_nothing_changes` | 2026-10-28 |
| CHK-M7-163-starting | APP | W | plant: `Retry-After` dropped | PASS (red) | 1 failed: the start-up row | 2026-10-28 |

#### Acceptance

TASK-163 row: "Through the API on PostgreSQL: REQ-171 (1)–(4) hold and REQ-167 (1) is seen through the route."
- REQ-171 (1): CHK-M7-271 (1) 204 and refusals, CHK-M7-282.
- REQ-171 (2): CHK-M7-271 REQ-171 (2).
- REQ-171 (3): CHK-M7-271 REQ-171 (3).
- REQ-171 (4): CHK-M7-271 REQ-171 (4).
- REQ-167 (1): CHK-M7-271 REQ-167 (1). REQ-167 (3) is also held.

The security plants all went red: API token (CHK-M7-341), sink gate (CHK-M7-343), role (CHK-M7-346) and token group.

#### Notes (no defect)

- The TOTP-session check runs before the role check, so an operator or viewer `bsk_` gets 403 `totp_session_required`, not `forbidden`. REQ-171 (1) asks only for 403 there, and the tests assert only the status.
- REQ-167 (2), (4) to (6) are TASK-152's and were tested there. Through this route the re-upload revival keeps the same `policy_id`.

### TASK-164


Tester: tester-m7d, 2026-10-28. REQ-172 (1) to (4), REQ-174 (2), REQ-177 (rebuild rows). Spec: TS §6.2 L1084, L1105, L1106, §4.2 L538 to L540, §5.3 L1051, §6 L1056, §6.3; #1, #20, #98 (f), (g), (i), (j), #101 (`bits.rebuild`, `policy_rebuilt`), #102 (d); decisions 2026-10-28 "TASK-157 rulings" (with `not_imported`) and the crash-window ruling (`removed_leftovers`; a deleted policy is never revived by itself).

Files under test: `bm/api/user/rebuild.py` (hash prefix 60416f237ed9c587), the registration in `bm/api/user/__init__.py`, and `manager/openapi.json` from the combined W8 regeneration.

New tester file: `manager/tests/test_rebuild_api_pg.py` (41 tests), on the shared `manager/tests/catalog_api.py` environment. The rebuild runs on the real catalog worker over a temporary bits folder.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` = the tree under test) | the TASK-162 r0 command, which includes `tests/test_rebuild_api_pg.py`, `tests/test_openapi.py` and `tests/test_invariants_m3.py` | 586/588 passed, 2 failed (`test_app_hardening.py`, TASK-162's cap value, fixed there; 2/2 and 53/53 on re-run), 0 errors, 0 skipped. Of these, 41/41 are in this file |
| plants (W, `-n 0`, throwaway copy, file restored after each) | `pytest tests/test_rebuild_api_pg.py -k <rows>` | 9/9 plants red |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 309 files formatted; no issues in 309 source files |

- Every subprocess imported the tree under test through `PYTHONPATH`.
- No container was left behind.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-276 REQ-172 (1) | APP | W | r0 | PASS | **Setup:** the server folder holds `good.bit`, `bad.bit` (BIT003) and `gone.bit` (2 plugins), imported at start-up; one live upload; one policy deleted through the route whose `uploaded/policy-<id>.bit` is then re-planted (an interrupted delete's leftover); `gone.bit` removed; and `uploaded/copy.bit` holding the server policy's name. **While another session holds the catalog lock:** an admin TOTP session gets 202 with exactly `{task_id}` (a hyphenated lowercase UUID). `GET /tasks/{id}` with an admin `bsk_` shows exactly `{task_id, kind: rebuild, state: running, requested_by: <admin>, result: null, started_at (RFC 3339 Z), finished_at: null}`, in that order. **After the lock is released, the task ends `succeeded`** (#20, with a rejected file), and `finished_at` ≥ `started_at`. **`result`** has exactly `files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported`. Each `files` item has `source_file, import_id, outcome, policy_id, policy_version`; the items are `good.bit` (success, its id), `bad.bit` (rejected, null id and version) and `uploaded/policy-<upl>.bit`. `deleted_policy_ids` is `[gone]`, `removed_leftovers` is `["uploaded/policy-<del>.bit"]`, `not_imported` is `["uploaded/copy.bit"]`, and `plugins_retired` ≥ 2. **Effects:** the leftover file is gone and its policy stays deleted, with no import row; the gone policy's `source_file` is `deleted/<id>`. The new `bit_import` rows are exactly the `files` import ids, all mode `rebuild` and `imported_by` the admin. There is one `bits.rebuild` entry (actor `user:<id>`, `alert_kind` `policy_rebuilt`, `removed_leftovers` listed), and `policy_rebuilt` rises by 1. A POST with no body, and one with `{}`, each give 202 and `succeeded`, with `requested_by` stored | 2026-10-28 |
| CHK-M7-276 REQ-172 (2) | APP | W | r0 | PASS | Admin `bsk_`: 403 `totp_session_required`. Restricted admin: 403 `totp_enrolment_required`. An unverified admin session: 403. Operator and viewer sessions: 403 `forbidden`. Operator and viewer `bsk_`: 403. No `task` row is created in any of these cases. Sink gate: at 14:59 a rebuild starts and succeeds; at 15:00, 503 `audit_sink_unavailable` with no task row, while `GET /tasks` still answers; after the drain a rebuild succeeds | 2026-10-28 |
| CHK-M7-276 503 | APP | W | r0 | PASS | Before the start-up ends: 503 `about:blank`, `Retry-After: 10`, the fixed #102 (d) detail, and no task row. With no catalog service: 503 `about:blank` | 2026-10-28 |
| CHK-M7-276 REQ-172 (3) | APP | W | r0 | PASS | Admin `bsk_` and session: 200. Operator and viewer, each with a session and with `bsk_`: 403 `forbidden`, with no task data in the body. A CLI task (`requested_by` NULL) reads `requested_by: null`, `running`, `started_at` equal to the stored time in Z form. Unknown, nil and max UUIDs: 404 `not_found`. `abc`, 32 hex digits, `{…}`, `urn:uuid:…`, one digit too many or too few, a misplaced hyphen, `g`, underscores, `1` and `-1`: 400 `invalid_request`. An upper-case id gives 200 with the lowercase id, never 500 | 2026-10-28 |
| CHK-M7-276 REQ-172 (4) | APP | W | r0 | PASS | A rebuild is started, its worker held inside the rebuild call, and the manager restarted (service stopped, a new start-up sequence run). The task reads `failed` with `result` exactly `{error: <non-empty fixed text without the id>}` and `finished_at` set (REQ-165 (2), #98 (g)) | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | On both the POST and the GET, `bsa_`, `bse_`, no token, garbage `bsk_` and `Basic` get 401 `unauthorized`, with no task row | 2026-10-28 |
| CHK-M7-276 OpenAPI | CODE | W | r0 | PASS | The POST has no request body or parameters; 202 `RebuildStarted` with only `task_id` (format uuid); 401, 403 and 503. The GET has its path parameter with a pattern; 200 `TaskItem` with the #98 (g) keys in order; `result` refers to a schema with exactly the five result keys; `files` items have the five file keys in order; 400, 401, 403 and 404 are problem+json. G6 byte-identical (`test_openapi.py`); G34 route walk passes (`test_invariants_m3.py`) | 2026-10-28 |
| CHK-M7-342 | APP | W | plant: POST with `require_role("admin")` | PASS (red) | 2 failed: `test_an_admin_api_token_is_refused_totp_session_required` and the sink-gate row | 2026-10-28 |
| CHK-M7-344 | APP | W | plant: `require_totp_session(sink_gate=False)` | PASS (red) | 1 failed: `test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains` | 2026-10-28 |
| CHK-M7-164-role | APP | W | plant: POST `require_totp_session("operator")` | PASS (red) | 1 failed: `test_operator_and_viewer_cannot_start_a_rebuild[operator-session]` | 2026-10-28 |
| CHK-M7-164-get-role | APP | W | plant: GET `require_role("viewer")` | PASS (red) | 4 failed: every `test_only_an_admin_reads_a_task` case | 2026-10-28 |
| CHK-M7-164-auth | APP | W | plant: both dependencies replaced by a fixed admin principal | PASS (red) | 10 failed: every wrong-group case on both routes | 2026-10-28 |
| CHK-M7-164-uuid | APP | W | plant: the UUID path pattern removed | PASS (red) | 11 failed: every non-UUID case | 2026-10-28 |
| CHK-M7-164-leftovers | APP | W | plant: `removed_leftovers` dropped from `TaskResult` | PASS (red) | 2 failed: the full rebuild row and the OpenAPI row | 2026-10-28 |
| CHK-M7-164-not-imported | APP | W | plant: `not_imported` dropped from `TaskResult` | PASS (red) | 2 failed: the full rebuild row and the OpenAPI row | 2026-10-28 |
| CHK-M7-164-starting | APP | W | plant: `Retry-After` dropped | PASS (red) | 1 failed: the start-up row | 2026-10-28 |
| CHK-M7-164-202 | APP | W | plant: `status_code=200` | PASS (red) | 3 failed: the full rebuild row and both body rows | 2026-10-28 |

#### Acceptance

TASK-164 row: "Through the API on PostgreSQL: REQ-172 (1)–(4) hold."
- REQ-172 (1): CHK-M7-276 REQ-172 (1).
- REQ-172 (2): CHK-M7-276 REQ-172 (2) and 503.
- REQ-172 (3): CHK-M7-276 REQ-172 (3).
- REQ-172 (4): CHK-M7-276 REQ-172 (4).
- `bsa_`/`bse_` 401: CHK-M7-282. G6 and G34 hold.

Every security plant went red: API token (CHK-M7-342), sink gate (CHK-M7-344), roles on both routes, token group, UUID check.

#### Notes (no defect)

- **REQ-172 (4):** a real process kill cannot be done in-process. Instead the worker's rebuild call is held on an event, so the task stays `running` with no catalog change, and the service is stopped and started again. The `failed` state comes from the real start-up sequence (`fail_running_tasks`).
- **`running` is observed deterministically** by holding `pg_advisory_lock(hashtext('catalog'))` from a second session. `start_task` does not take the lock, so the 202 arrives at once.
- **`GET /tasks/{id}` accepts upper-case hex.** The pattern allows `A-F`, and the id is returned lowercase. The spec only says ids are UUID strings.

### TASK-165


Tester: tester-m7, 2026-10-28. REQ-173 (1) to (4), REQ-174 (2); TS §6.2 L1107 (`/imports`, admin, session or API token), §6.3 L1133 to L1139 (problem+json, opaque cursor, limit up to 500, integer catalog keys, RFC 3339 UTC), §6 L1056 (user routes take only `bsu_` and `bsk_`), §5.2 L694 to L707 and SR §3.5 (the twelve `bit_import` columns); #98 (h), (i), #48. Files under test: `bm/api/user/imports.py`, `bm/api/user/__init__.py`, `manager/openapi.json`. New test file `manager/tests/test_imports_api_pg.py` (81 tests) on the M2 users-API environment (real sink gate, real rate limiter). Rows are written through the TASK-149 repository as `bitscan_app`. No existing test needed changes: the route walk G34 already lists `GET /imports`, and its query-parameter pin holds (the new file also pins `/imports` to exactly `limit` and `cursor`).

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m7-t165`, label `m7t-t165`, `CI=true`, `-n 2`) | `pytest tests/test_imports_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_imports_repo_pg.py` | 142/142 passed, 0 failed, 0 errors, 0 skipped |
| plants (W, `-n 2`, each in `/root/bstest-m7-mut-<id>`, removed after) | `pytest tests/test_imports_api_pg.py` | see the plant rows |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on the new file | clean |

Containers of every run were removed (0 left by label).

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-258 (1) | APP | W | r0 | PASS | REQ-173 (1): N + 1 rows with `limit` N (1, 2, 5) walk the whole table once each, strictly newest first across pages, mine in descending id order, total equals `count(*)`; the order key is `import_id`, not `imported_at` (a later id with an earlier time comes first); the default page is 50 (the 50 newest of 51); `limit=500` accepted; `0`, `501`, `-1`, `a`, `1.5`, ``, `1e2` → 400 `invalid_request`; unknown query parameters (`outcome`, `mode`) change nothing and the OpenAPI operation has exactly `limit` and `cursor` (#98 (h) no filters) | 2026-10-28 |
| CHK-M7-258 (2) | APP | W | r0 | PASS | Every item's keys are exactly the twelve DDL columns in table order (checked against `SELECT *`); every value equals the stored row (success with version 7, counts 3/2/1 and `imported_by`; rejected with NULL version and user; skipped with `[]`); `import_id` is a JSON integer; `imported_at` matches RFC 3339 with `Z` and equals the stored time. `errors` equals the stored jsonb exactly for the four-finding set (null line and element, escaped text, U+202E, emoji, `Plugin[5000]/Execute/@timeout`, line 2^31 − 1), for 2,000 findings in order, and for `[]`; each finding has exactly `line, element, code, message` | 2026-10-28 |
| CHK-M7-258 (3) | APP | W | r0 | PASS | Admin session and admin `bsk_` → 200; operator and viewer, session and API → 403 `forbidden` (also with a cursor); admin without TOTP, restricted session and API token → 403 `totp_enrolment_required` | 2026-10-28 |
| CHK-M7-258 (4) | APP | W | r0 | PASS | Nine hostile `file_name` values come back byte-identical as `application/json`: `<script>`, U+202E, the #99 (d) U+FFFD form, `../../etc/x.bit`, quotes, backslash and `%00`, raw U+0001/U+001F/U+007F, 255 × U+1F6E1 (1,020 bytes), the empty name, leading and trailing spaces. A full walk leaves the `bit_import` checksum unchanged (read-only) | 2026-10-28 |
| CHK-M7-258 cursor | APP | W | r0 | PASS | Tampered (first, middle and last character flipped, truncated, one character appended, `==` padding, swapped case, inner space, `+/` alphabet, empty, `x`, non-ASCII, 513 characters) → 400 `invalid_request`; signed with the manager's key but the wrong shape (`"5"`, `true`, `false`, 0, −1, 2^63, 2^64, 10^30, `[5]`, `[5, 6]`, `[]`, `null`, an object, 1.5, 5.0) → 400; the bounds 1, 2, 2^63 − 1 → 200 (key 1 gives `{"items": [], "next_cursor": null}`); real cursors from `/audit-log`, `/users` and `/policies`, and signed integer cursors of the scopes `audit_log`, `users`, `policies`, `agents` and `` → 400. No 500 in any case | 2026-10-28 |
| CHK-M7-282 | APP | W | r0 | PASS | `bsa_`, `bse_`, a `bsa_` whose hash is stored on an enrolled `online` agent, no token, garbage `bsu_` and `bsk_`, and `Basic` → 401 `unauthorized` problem+json with no items; the 600-per-minute user limit applies (600th request 200, 601st 429 `rate_limited`) | 2026-10-28 |
| CHK-M7-281 | APP | W | r0 (`test_invariants_m3.py`) | PASS | The route walk has `GET /api/v1/imports` and nothing else new; no request schema carries a command; the query-parameter pin holds | 2026-10-28 |
| G6 | CODE | W | r0 (`test_openapi.py`) | PASS | A fresh export is byte-identical to `manager/openapi.json`, and two exports are byte-identical; the operation documents 401, 403 and 429 as problem+json and its item schema lists the twelve columns in order, all required, `import_id` integer | 2026-10-28 |
| CHK-M7-165-rbac | APP | W | plant: `require_role("admin")` → `"operator"` | PASS (red) | 2 failed: `test_operator_and_viewer_get_403[operator-session]`, `[operator-api]` | 2026-10-28 |
| CHK-M7-165-token | APP | W | plant: the auth dependency removed from the route | PASS (red) | 13 failed, among them every `test_agent_tokens_and_bad_tokens_get_401` case, the stored-agent-token case, the rate-limit case and every 403 case | 2026-10-28 |
| CHK-M7-165-shape | APP | W | plant: `_before` returns the decoded key without the shape check | PASS (red) | 15 failed: each wrong-shape case (500 for `true`, `false`, 2^63, 2^64, 10^30, lists and the object; 200 for `"5"`, 0, −1, `null`, 1.5, 5.0) | 2026-10-28 |
| CHK-M7-165-scope | APP | W | plant: on a scope mismatch, fall back to decoding as `audit_log` | PASS (red) | 2 failed: `test_a_cursor_from_another_list_is_400[/api/v1/audit-log]`, `test_a_signed_int_cursor_of_another_scope_is_400[audit_log]` | 2026-10-28 |
| CHK-M7-165-tamper | APP | W | plant: the HMAC comparison removed from `decode_cursor` (`api/pagination.py`) | PASS (red) | 5 failed: the flip, swapped-case and empty cases (200 or 500 instead of 400) | 2026-10-28 |

#### Acceptance

TASK-165 row: "Through the API on PostgreSQL: REQ-173 (1)–(4) hold and `bsa_` gets 401" — (1) CHK-M7-258 (1), (2) CHK-M7-258 (2), (3) CHK-M7-258 (3), (4) CHK-M7-258 (4); `bsa_` and `bse_` 401 CHK-M7-282; OpenAPI byte-stable G6. Every security row (RBAC, token type, cursor tamper, shape and scope) has a plant that went red.

#### Notes (no defect)

- `decode_cursor` (M2, `api/pagination.py`) unpacks the payload as `[scope, key]` after the HMAC check. A payload of another length would raise and give 500, but only someone holding the per-process key can produce one, so it is not reachable from outside. Not a TASK-165 finding.

### TASK-166


Tester: tester-m7, 2026-10-28. Full rigor (importer, CLI). REQ-175 (1)–(6); TS §8.7 L1347, §4.2 L540; #107 (a)–(f); the TASK-046 rule (no DSN content in any output); TASK-157 r2 (a task no longer running: nothing runs). Code under test: `bm/cli/bits.py` and `bm/cli/__init__.py`. New test file: `manager/tests/test_cli_bits_pg.py` (12 tests). `bits_main` runs in a subprocess with a temporary DSN file, `manager.env` and folders (`python -c` from the tree under test), and the installed console script runs for `--help`. Its own module database.

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t160r1`, `-n 0`, `CI=true`) | Count |
| --- | --- | --- |
| b0 | `pytest tests/test_cli_bits_pg.py` (with the TASK-160 set) | **12/12 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 7 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 7/7 red. c7 needed `PYTHONPATH` on the plant copy, because the console script imports the venv's editable install, not the copy |
| static (L) | whole-tree ruff, ruff format, `mypy --strict` (CI form) | clean (304 files) |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-290 (1) | APP | W | b0 | PASS | A server file and an `uploaded/` file: exit 0. One line each, `success <rel> policy <id> version 1`, then `rebuild succeeded: 2 files, 0 rejected, 0 policies deleted, 0 plugins retired (task <uuid>)`, three lines in all. The task is `succeeded` with `requested_by` NULL. One `bits.rebuild` (`policy_rebuilt`) by `cli:root`, two `policy.import`, every entry by `cli:root`. The DSN password is in no output. The `uploaded/` file is relocated | 2026-10-28 |
| CHK-M7-290 (2) | APP | W | b0 | PASS | One rejected file: exit 0, the line `rejected bad.bit (1 findings)`, summary `2 files, 1 rejected` (#107 (c)). A removed file prints one `deleted policy <id>` line and the summary counts it | 2026-10-28 |
| CHK-M7-290 (3) | APP | W | b0 | PASS | A non-TLS DSN (`sslmode=disable`), a DSN without `sslmode`, a missing DSN file, a missing folder and a missing `uploaded/` each exit 2. Each writes one `bits rebuild: …` stderr line and empty stdout, with the canary password nowhere, and no task row is written (no database work) | 2026-10-28 |
| CHK-M7-290 (4) | APP | W | b0 | PASS | Started while another session holds the catalog lock: still running after 3 s, and `pg_locks` shows it waiting. After the release it exits 0 with its summary | 2026-10-28 |
| CHK-M7-290 (5) | APP | W | b0 | PASS | With `BITSCAN_DB_DSN`, `BITSCAN_DB_DSN_FILE`, `DATABASE_URL` and `PGPASSWORD` set to working values and the fixed DSN file absent, it exits 2 naming that file. `--dsn`, a folder argument and `--bits-dir` are usage errors (2). #107 (a): without `BITSCAN_BITS_DIR` in the environment it uses the last `BITSCAN_BITS_DIR=` of `manager.env` (quotes removed). The environment wins over it. A `manager.env` that isn't UTF-8 exits 2 without showing its content (canary absent) | 2026-10-28 |
| CHK-M7-290 (6) | APP | W | b0 | PASS | `bitscan-manager --help` lists `bits rebuild` (exit 0); `bits rebuild --help` exits 0; `bits` and `bits nonsense` exit 2. Through the console script with no DSN file: exit 2 naming `/etc/bitscan/secrets/app.dsn`, with no prompt | 2026-10-28 |
| failed and not run | APP | W | b0 | PASS | A database error inside the rebuild (injected) → exit 1, empty stdout, stderr `bits rebuild: The rebuild failed; the catalog was left unchanged. (task <uuid>)`. The database down → exit 1, `bits rebuild: database error (<Type>)`, canary absent. TASK-157 r2: the task failed by a start-up while the CLI waited for the lock → exit 1, `bits rebuild: interrupted by manager start-up; run it again`, empty stdout, no audit entry | 2026-10-28 |
| plant c1 | APP | W | the DSN read from `BITSCAN_DB_DSN_FILE` | PASS (red) | 1 failed: (5) exit 0 instead of 2 | 2026-10-28 |
| plant c2 | APP | W | the `uploaded/` check dropped | PASS (red) | 1 failed: (3), a rebuild of a folder without `uploaded/` ran | 2026-10-28 |
| plant c3 | APP | W | `str(exc)` printed for a database error | PASS (red) | 1 failed: the error-type row (message text and pool detail in the output) | 2026-10-28 |
| plant c4 | APP | W | exit 0 when the task wasn't running | PASS (red) | 1 failed | 2026-10-28 |
| plant c5 | APP | W | exit 1 when files were rejected | PASS (red) | 1 failed: (2) | 2026-10-28 |
| plant c6 | APP | W | `requested_by` a user id | PASS (red) | 1 failed: (1) the task row | 2026-10-28 |
| plant c7 | APP | W | the `--help` line removed | PASS (red, with `PYTHONPATH`) | 1 failed: (6). Without `PYTHONPATH` the console script ran the venv's installed tree and the row stayed green (a harness effect) | 2026-10-28 |

#### Acceptance (TASK-166 row)

REQ-175 (1)–(6) → CHK-M7-290 (1)–(6); #107 (a)–(d) → (1), (2), (5) and "failed and not run". #107 (e), (f) need no row, since the command has no finish, no check and no prompt (seen in (1)). Every security row has a plant that went red.

#### Shared-venv check (lead, 2026-10-28)

`/root/venv-m7`'s editable install points at the last folder installed, so the `bitscan-manager` console script (`run_cli`) imports that tree, not the plant copy. In this file only `test_help_lists_bits_rebuild` and `test_the_cli_entry_point_reaches_bits_main` use the console script. The only plant aimed at them, c7, was re-run with `PYTHONPATH=<plant copy>/manager` and went red. Plants c1–c6 run `bits_main` through `python -c` from the plant copy's folder (checked: the copy's tree is imported), so their results stand.

### TASK-167


**Verdict: PASS (round 2, on TASK-167 r1)**
- Round 1 was FAIL on F1, below. r1 fixed F1 and added the "503 after an upload" line; see "Round 2" at the end.
- The live WSL walk (CHK-M7-305) is still NOT RUN; main decides whether it is needed at the gate.

Tester: tester-m7w. Worktree `Bitscan-m7`, branch `m7-catalog`, `README.md` uncommitted. Windows 11 + Git Bash. Low risk (docs): one test run and one review.
REQ-184. Sources checked against: `manager/openapi.json`, `manager/bitscan_manager/cli/{bits,users,__init__}.py`, `config/startup.py`, `api/user/{policies,policy_import,imports,rebuild}.py` (auth dependencies), `services/importer/folders.py` (name rules, order), SR §4.1–§4.2, TS §4.3, §6.2.

#### Scope
- main scoped this run to a static walk of the new "Policies" section: commands and routes against `openapi.json` and `cli/bits.py`, links, no secrets or ids, and the hard-link line, one row per REQ-184 item.
- The task row's live walk against a WSL manager (CHK-M7-305, REQ-184 acceptance (1)) is **NOT RUN** here. This run is Windows only and the W environment belongs to tester-m7. Behaviour that only a live manager can show is listed under "Not run".

#### Commands
- `python -I deploy/tests/check_md_links.py README.md` → `OK 21 relative links checked, 0 findings`, exit 0.
- `python -I %TEMP%\m7w-scripts\readme_walk.py <worktree>`: a read-only script outside the tree. It extracts the section's routes, field lists, enums, statuses and CLI statements and compares them with the sources. It printed 66 rows: 64 true, 2 false (F1).
- Manual reading of the section against the code paths named above.

#### Rows

| Check | Item | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-306 (a) | Every route and method named in "Policies" exists in `openapi.json` | PASS | named = the 8 M7 operations exactly (GET/PATCH/DELETE `/policies/{id}`, GET `/policies`, POST `/policies/import`, POST `/policies/rebuild`, GET `/imports`, GET `/tasks/{id}`); 0 unknown; the `{policy_id}` and `{task_id}` placeholders match the `{id}` parameters |
| CHK-M7-306 (b) | Every `{field, …}` list matches its schema | PASS | ImportResult (9), PolicyItem (14), detail adds exactly `deleted_at` and `plugins`, ImportItem (12), TaskItem (7), TaskResult (5), TaskFile (5), ImportFinding (4), TaskFailure (1), RebuildStarted `{task_id}` |
| CHK-M7-306 (b) | Enums and PATCH bodies | PASS | `mode` auto/manual/rebuild; ImportItem `outcome` success/skipped/rejected; ImportResult `outcome` success/rejected; `state` running/succeeded/failed; PatchPolicy has only `policy_status` and `status_overridden` |
| CHK-M7-306 (b) | Statuses stated | PASS | import 200/409/413/503; DELETE 204/404/409/503; PATCH 409; rebuild 202/503; all appear in the openapi responses |
| CHK-M7-306 (b) | Who may call what | PASS | PATCH `require_role("admin")` (session or API token); DELETE and POST rebuild `require_totp_session()`; GET `/imports` and `/tasks/{id}` admin; upload admin (API token allowed, TS §6.2 L1084) |
| CHK-M7-306 (c) | `sudo bitscan-manager bits rebuild` and each statement about it | PASS | dispatch in `cli/__init__.py` (`["bits"]` → `bits_main`, subcommand `rebuild`); DSN `/etc/bitscan/secrets/app.dsn` (`APP_DSN_FILE`); actor `cli:root`; folder `BITSCAN_BITS_DIR` → `/etc/bitscan/manager.env` → `/var/lib/bitscan/bits`; `uploaded/` must exist; output lines `success <file> policy <id> version <n>`, `rejected <file> (<n> findings)`, `not imported`, `removed leftover`, `deleted policy <id>`, summary; exit 0/1/2 as in `bits.py` |
| CHK-M7-306 (c) | `curl -F file=@x.bit` example | PASS | `curl -s https://manager.example:8443/api/v1/policies/import -H 'Authorization: Bearer <token>' -F file=@cis-ubuntu-24.04.bit` |
| CHK-M7-306 (c) | Folder rules | PASS | `.bit` suffix, no leading dot, `O_NOFOLLOW`, 255-byte cap (`folders.py` L50–L122); new files ordered by `p.encode("utf-8")` (L257), matching "sorts first byte by byte" |
| CHK-M7-307 | Links resolve | PASS | 21 relative links, 0 findings, including `#policies` and `docs/spec/bit_Schema_Reference.md` |
| CHK-M7-308 | No real token or secret | PASS | 0 hits for `bs[usae]_` + 20 or more chars, private keys or password values in the whole README; the curl uses `<token>` |
| CHK-M7-308 | No task id or process note | PASS | 0 hits in "Policies" for `TASK-`, `REQ-`, `CHK-`, `PD-`, `#nn` question refs, team roles, `work/` or UUIDs; 0 `TASK-`, `CHK-` or `PD-` in the whole README |
| CHK-M7-309 | "don't hard-link files into the bits folder" line | PASS | "**Copy or move files into the folder; don't hard-link files into the bits folder.**" |
| CHK-M7-309 | REQ-184: `.bit` format in brief, pointing at SR | PASS | opening paragraph links SR and its §1.1 example; `<PolicyName>` is the key, file names never are |
| CHK-M7-309 | REQ-184: loading, server folder | PASS | "**The server folder.**" (watcher, start-up, name rules, rename in place, BIT007, order) |
| CHK-M7-309 | REQ-184: upload in the UI or with an admin `bsk_` and `curl -F` | PASS | "Use a session or an admin's `bsk_` API token, or upload in the web UI", plus the curl |
| CHK-M7-309 | REQ-184: what an import does (validation, BIT codes, live at once, alerts) | PASS | "What an import does"; BIT102 examples are all in SR §4.2 L279–L285 |
| CHK-M7-309 | REQ-184: status and the override | PASS | the PATCH bodies; "Later file updates then change only `file_status`" (TS §4.3 L548) |
| CHK-M7-309 | REQ-184: delete | PASS | TOTP session, API token refused, 15-minute sink gate, 204/404/409, `policy_managed_on_server`, revival |
| CHK-M7-309 | REQ-184: rebuild through the API and the CLI | PASS | "Through the API" and "On the server" |
| CHK-M7-309 | **REQ-184: rebuild through the UI** | **FAIL (F1)** | no UI path for rebuild anywhere in the README |
| CHK-M7-309 | REQ-184: import history | PASS | `GET /api/v1/imports` with fields, mode and outcome |
| CHK-M7-309 | REQ-184: #100 audit-sink entry size | PASS | "**Audit-sink entry size.**" (about 10 MiB; syslog often 8 KiB) |
| CHK-M7-309 | **The Web UI section names the M7 screens** | **FAIL (F1)** | "Pages by role" (README L227–L232) still lists only the M5 pages: no Profiles, Upload policy, Import history or Rebuild catalog |

#### F1 (owner: impl-manager-m7b, README; the page names come from impl-web's TASK-173)
- **Expected (REQ-184):** the guide covers "rebuild (UI, API, `sudo bitscan-manager bits rebuild`)".
- **Actual:** the Rebuild section has only "Through the API", "On the server" and "At start-up".
- **Related stale text:** the Web UI section's "Pages by role" table (README L227–L232) shows only Hosts, host detail, Package search, TOTP and Password for every role, and the two Enrolment pages for admins. The UI now also has:
  - **Profiles** and profile detail for every role, with the admin status actions and Delete (TOTP session);
  - **Upload policy**, **Import history** and **Rebuild catalog** for admins (TASK-173; nav labels and hashes in `work/reports/TASK-168-173-impl.md`).
- **Diagnosis:** the impl report says the UI wording was kept generic because the screens were built in parallel. Its line "plus the existing Profiles page" has no matching text: "Profiles" appears nowhere in the Web UI section.
- **Suggested fix (the owner decides wording):** add the four pages to the "Pages by role" table. Add one line in "Rebuild": "In the web UI: **Rebuild catalog** (admin, TOTP-verified session), then confirm; the page follows the task until it succeeds or fails and lists the files." Optionally mention **Upload policy** and **Import history** in their sections.
- **Re-test:** re-run `readme_walk.py` (the two rows) and `check_md_links.py`.

#### Not run (live behaviour; CHK-M7-305, WSL manager)
- That the watcher imports "a few seconds after" a file is written or moved in, and that removal deletes. This needs inotify on Linux.
- That the curl upload, PATCH, DELETE, rebuild and `sudo bitscan-manager bits rebuild` behave as written against a running manager.

The static rows above show that each statement matches the code as built. main decides whether the live walk is still needed at the M7 gate.

#### Observation (no change requested)
"The codes `BIT001`–`BIT017` and `BIT102` reject the file" reads as a range. SR §4.1 L250 retires BIT006 and BIT009, so the range has gaps, but every live code in it is Reject; the statement is true.

#### Round 2 (TASK-167 r1; README sha256 `1a651f0c…88191b`)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-309 rebuild through the UI (F1) | `readme_walk.py` | PASS | "**In the web UI (admin, TOTP-verified session).** On **Rebuild catalog**, press **Rebuild** and confirm…", matching `Rebuild.tsx` and CHK-M7-389 (confirm, one POST, polls to succeeded or failed, then files, not imported, deleted policies, leftovers) |
| CHK-M7-309 Web UI names the M7 screens (F1) | `readme_walk.py` + reading | PASS | "Pages by role": Profiles and profile detail for every role; Upload policy, Import history and Rebuild catalog admin only (matches `ROUTE_ROLES`, CHK-M5-280). The TOTP sentence covers profile delete and rebuild (TS §6.2). The page bullets match CHK-M7-312 to -314 and -388: filter All/Enabled/Disabled; admin Enable or Disable, Clear override, Delete with confirmation; Deleted shows no actions; Imported or Rejected with findings; history newest first |
| CHK-M7-309 upload names the UI page | `readme_walk.py` | PASS | "an admin's `bsk_` API token, or the web UI's **Upload policy** page" (my needle was loosened to this meaning; the wording changed, the item didn't) |
| r1 line: a 503 after an upload | reading against `api/user/policy_import.py` | PASS | the quoted text is the route's `_NOT_RECORDED` (L46), raised as 503 `about:blank` when the catalog committed without its `bit_import` row (L164–L166); "may already be live" is right for it. See N1 |
| All other 306 to 309 rows | `python -I readme_walk.py <worktree>` | PASS | **66/66 true** (routes, field lists, enums, statuses, CLI, no token, task, check or process id, hard-link line) |
| CHK-M7-307 links | `python -I deploy/tests/check_md_links.py README.md` | PASS | `OK 22 relative links checked, 0 findings` (the new `#rebuild` resolves) |

N1 (non-blocking, for the reviewer):
- **Issue:** for the quoted 503, "Check the policy list or the import history" can find the import only in the policy list. That case is by definition the one where the `bit_import` row was not written, so the import history has no entry.
- **Risk:** a reader who checks only the history and re-uploads does no harm; a manual re-import of the same content changes nothing.
- **Clearer wording:** "check the policy list (its version and imported time); this case has no import-history row".

Round 2 verdict: **PASS** (static walk). The live walk (CHK-M7-305) is still NOT RUN; see "Not run".

### TASK-168-173


**Verdict: PASS**

Tester: tester-m7w. Worktree `Bitscan-m7`, branch `m7-catalog`, uncommitted. Windows 11 + Git Bash, from `web/`, after impl-web's message that the start-up-mapping tweak is in. Low risk: one test run and one review for the batch, with planted faults for the security rows only (decisions 2026-10-28 "Speed-up").
REQ-181, REQ-182, REQ-183; PD-34 (a); #98, #99 (d), #102 (d), #110. Spec: TS §1.4 L41, §2.1 L101, §4.3 L546–L551, §6.2 L1084, L1100–L1107, §6.3 L1133–L1141.

#### Totals

| Run | Command (from `web/`) | Result |
| --- | --- | --- |
| Baseline, before any test change | `npx vitest run` | 342/345 passed, 3 failed (CHK-M5-280, expected; REQ-183 (3) adds nav entries), 0 errors, 0 skipped |
| **Final**, after the batch tests | `npx vitest run` | **516/516 passed**, 0 failed, 0 errors, 0 skipped, 0 todo (21 files) |
| M7 rows only (incl. updated CHK-M5-280) | same run, JSON reporter | 169/169 passed |
| Plants | `python -I plants.py <throwaway copy>` | 11/11 plants red; the restored copy runs 516/516 |

Per new or changed test file: `App.test.tsx` 36/36, `problems.test.ts` 68/68, `router.test.ts` 109/109, `sources.test.ts` 15/15 (new), `Profiles.test.tsx` 14/14, `ProfileDetail.test.tsx` 25/25, `PolicyUpload.test.tsx` 15/15, `Imports.test.tsx` 8/8, `Rebuild.test.tsx` 11/11 (all new). No re-runs were needed for product bugs. Test bugs fixed on the way, in my files only: a `FileList` stand-in, a page-3 count, a glob key form, and `setImmediate` typing.

#### Gates

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-319 G12 | `npm run lint` | PASS | exit 0, `--max-warnings 0` |
| CHK-M7-319 G13 | `npm run typecheck` | PASS | exit 0; this includes `UserPathsArePrefixed` in `src/api/client.ts` (REQ-183 (2)) |
| CHK-M7-319 G14 | `npm run format:check` | PASS | "All matched files use Prettier code style!" |
| CHK-M7-319 G15 | `npx vitest run` | PASS | 516/516 |
| CHK-M7-317 G16 | `npm run gen:api` twice, then `cmp` and `sha256sum` against the tree's file | PASS | before = gen1 = gen2 = `9c9eac70…d7a51e`; both `cmp` silent |
| REQ-183 (2) | `node` over `manager/openapi.json` | PASS | exactly 8 M7 operations (GET/PATCH/DELETE `/policies/{id}`, GET `/policies`, POST `/policies/import`, POST `/policies/rebuild`, GET `/imports`, GET `/tasks/{id}`), all under `/api/v1/`; 0 unprefixed paths besides `/healthz`, `/readyz` |

#### Per task

##### TASK-168 `problems.ts` and the client (CHK-M7-311): PASS
`src/app/problems.test.ts` "CHK-M7-311", 33 cases:
- `policy_managed_on_server` gives the server-folder text at 409, 400, 403, 500 and 503.
- The start-up 503 maps only with 503, `about:blank`, the exact detail "The catalog is starting; retry shortly." and a numeric Retry-After (10, 0, 1).
- Each single change falls through to the generic text: status 500 or 502, another type, no Retry-After, no detail, another detail, a trailing space, no final full stop, other case, a prefix. So does an HTTP-date, `1.5`, `-1` or empty Retry-After, checked through `toProblem` with real `Response` headers.
- `audit_sink_unavailable` still wins by type, and unknown types stay generic.
- No message carries response text or an API-token hint.

G16 and REQ-183 (2) are above.

##### TASK-169 Profiles list (CHK-M7-312): PASS
`src/screens/Profiles.test.tsx`:
- **Request and fixture:** `GET /api/v1/policies` with only `limit=50` and Bearer `bsu_`. Column headers and every row match the fixture: name, description, status (Enabled, Disabled, "Disabled (override)"), family, version, plugin count, updated. Server order is kept.
- **Link:** each name links to `#/profiles/<id>` and navigates there.
- **Status filter:** offers exactly All, Enabled and Disabled (no Deleted, #9). Enabled and Disabled send `status=`; All sends none. Changing the filter on page 2 starts again with no cursor.
- **REQ-181 (4):** 121 policies over 3 pages are shown each exactly once, with cursors `null`, `c50`, `c100`; Previous goes back.
- **Hostile text:** a hostile name, description and family render literally and create no `script` or `img`.
- **Refusals:** a 503 shows the banner; a network failure shows unavailable. The list has no admin control.

##### TASK-170 Profile detail (CHK-M7-313): PASS
`src/screens/ProfileDetail.test.tsx`:
- **REQ-181 (1):**
  - Exactly one `GET /api/v1/policies/7`, and all 10 profile fields as listed.
  - Plugins given out of order (sort_order 2, 0, 1) are shown 0, 1, 2. Each heading is exactly `CIS Ubuntu 24.04 - 1.1.n - …` (TS §1.4).
  - Each card shows its description, control, operator, expected result, timeout, plugin id and `Execute` (in `<pre>`, as text). A null `control_ref` shows "none", and a retired plugin shows Retired.
  - "Disabled (override)" shows as such; a 404 shows "Profile not found."
- **REQ-181 (2):** a deleted policy shows Deleted and no button at all, for admin, operator and viewer.
- **REQ-181 (3):**
  - The buttons per state are exact (Disable or Enable, plus Clear override when overridden, plus Delete).
  - Disable sends exactly `{"policy_status":"disabled"}`, Enable `{"policy_status":"enabled"}` and Clear override `{"status_overridden":false}` (`toStrictEqual`), each as one PATCH, `application/json`, Bearer `bsu_`, then a reload. A 409 `conflict` gives "This profile is deleted."
  - Viewer and operator get zero buttons, even with an override set.
- **REQ-182 (2):**
  - Delete opens a confirmation; Cancel sends nothing, and Confirm sends exactly one `DELETE`, with no body, then reloads to Deleted.
  - A 409 `policy_managed_on_server` shows the server-folder text. A 403 `totp_session_required` shows "Sign in again", no `input`, `textarea` or `select`, no "api token" or `bsk_` text, and no retry with another credential.
  - A 503 `audit_sink_unavailable` shows the paused text, and a DELETE 404 shows "Profile not found."
- **Hostile text:** hostile values in every stored text field, including `display_name`, `execute`, `operator` and the delete question, create no element.

##### TASK-171 Upload (CHK-M7-314): PASS
`src/screens/PolicyUpload.test.tsx`:
- **REQ-182 (1), the request:** exactly one `POST /api/v1/policies/import`, Bearer `bsu_`, and a `multipart/form-data; boundary=` type, so no JSON type was set.
  - The `FormData` holds exactly one entry, `["file", "cis.bit", <the chosen bytes>]`; the content has CRLF, a tab and `é`, compared exactly. The file's own name is sent unchanged.
  - With no file there is a note and no request. The form holds one file input (`accept=".bit"`) and no token field.
- **Success and rejection:**
  - Success shows "Imported", "Import 41" and "CIS Ubuntu 24.04 Level 1 - Server, version 3: 2 plugins added, 5 updated, 1 retired.", with a link to `#/profiles/7`. Its warnings are listed (#110).
  - A rejection shows "Rejected" and "the catalog is unchanged", with no link, and every finding's line, element, code and message (null line → "none", null element → "file").
  - A second upload replaces the first outcome.
- **Refusals:** 413 gives the 5 MiB text, 409 `policy_managed_on_server` its text, and the start-up 503 the catalog-starting text. A 403 gives the role text and a network failure gives unavailable.
- **REQ-182 (5):** a hostile policy name, finding element, code and message, and a hostile server detail, render literally.
- **Harness note:** `src/test/harness.ts` now records `contentType` and the `FormData` given to `new Request`. In this test environment, undici serialises a jsdom `FormData` with the filename `blob` and an empty part (probed). The bytes are therefore checked on the `FormData` itself, not on the serialised body; a browser does not do this.

##### TASK-172 Import history (CHK-M7-388) and Rebuild (CHK-M7-389): PASS
`src/screens/Imports.test.tsx`:
- **Request:** `GET /api/v1/imports` with only `limit=50`.
- **Columns:** id, file, mode, outcome, version ("none" when null), "1 / 2 / 3", by ("user 4" or "server"), and time. The server's order is kept (10, 30, 20 stays 10, 30, 20).
- **Findings:** a table of line, element, code and message, or "none".
- **REQ-182 (4):** 120 rows newest first over 3 pages are shown each once.
- **REQ-182 (5):** hostile file names and messages render literally.
- **Refusals:** a 403 shows the role text; a network failure shows unavailable.

`src/screens/Rebuild.test.tsx` (fake `setTimeout`, imported `POLL_MS`):
- **Start:** Cancel sends nothing; Confirm sends one `POST /api/v1/policies/rebuild` with an empty body.
- **REQ-182 (3) polling:**
  - For running, running, succeeded: the first `GET /tasks/{id}` comes at once, none at `POLL_MS - 1`, the second at `POLL_MS` and the third at `2 × POLL_MS`. Then nothing for 10 × `POLL_MS`, the timer count is 0, and the button is enabled again (disabled while running).
  - For running then failed: 2 GETs, then none, and the error text is shown.
  - A refusal while polling, or leaving the screen, stops the polling.
- **Result:** succeeded shows the files table and all five result fields.
- **Start refusals:** a 403 `totp_session_required` shows "Sign in again", no input, no API-token text, exactly one POST with the `bsu_` and no poll. `audit_sink_unavailable` and the start-up 503 show their texts.
- **Hostile text:** hostile `source_file`, leftovers, `not_imported` and failure text render literally.

##### TASK-173 routes, roles, navigation (CHK-M7-390): PASS
- `src/app/router.test.ts`: `#/profiles`, `#/profiles/<id>`, `#/catalog/upload`, `#/catalog/imports` and `#/catalog/rebuild` parse and print back to the same hash. This covers ids 0, `007` (not normalised), 20 digits and 9007199254740993 (above 2^53, kept as a string). 25 malformed hashes give the host list, and `isPolicyId` boundaries hold (21 digits, Arabic-Indic, full-width and superscript digits, a space). The existing ROUTES and formatHash tables now include the new routes.
- `src/app/App.test.tsx` **CHK-M5-280 updated** (REQ-183 (3), checked against TS §6.2 L1100–L1107; Profiles and the profile route are viewer, and upload, `/imports` and rebuild are admin):
  - viewer and operator: Hosts, Package search, **Profiles**, TOTP, Password;
  - admin: Hosts, Package search, **Profiles, Upload policy, Import history, Rebuild catalog**, Enrolment requests, Enrolment tokens, TOTP, Password.
- **CHK-M7-390 (shell part):**
  - Viewer and operator on the three catalog hashes get "This page is not available for your role." and send **no request** to `/policies/import`, `/imports`, `/policies/rebuild` or `/tasks/` (REQ-183 (3)).
  - On Profiles and a profile they see no Enable, Disable, Clear override or Delete, and send no PATCH or DELETE. The detail page marks Profiles as current, with the "Profile detail" crumb.
  - An admin gets the three screens and the actions, and no rebuild is sent until the admin acts. Each M7 nav entry's href is its hash and is marked current there.

#### Security rows

| Check | What | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-392 | Hostile `<script>…<img onerror=…>` in every stored text, rendered inside the shell on Profiles, a profile, Import history, an upload's findings and a rebuild's files | PASS | `container.textContent` holds the literal string; `querySelectorAll("script, img")` is 0 in the container and the document |
| CHK-M7-391 | No `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `createContextualFragment`, `DOMParser`, `document.write`, `srcdoc`, storage, `fetch`, `XMLHttpRequest` or `createClient` outside `src/api/client.ts` | PASS | `src/app/sources.test.ts` scans every product source with comments stripped (the M7 files are asserted present). Also `grep` of the new files: none |
| CHK-M7-393 | The token is never in a URL, a body or storage across Profiles, a PATCH, an upload, Import history and a rebuild with its poll | PASS | every non-login call carries `Bearer bsu_…`; no call URL or body holds it; `watchSecrets` (storage, cookie, IndexedDB, console, history, `location.href`) is empty |
| CHK-M7-390, -313 | Admin-only actions are hidden from viewer and operator | PASS | as above |

##### Plants (each in a throwaway copy, one at a time, file restored after; copy then 516/516)

| Plant | Fault | Red tests (vitest) | Lint (G12) |
| --- | --- | --- | --- |
| CHK-M7-370 | `dangerouslySetInnerHTML` for the description in `ProfileDetail.tsx` | 3 red: CHK-M7-313 (e), CHK-M7-391 "no source uses dangerouslySetInnerHTML", CHK-M7-392 `#/profiles/7` | red (exit 1) |
| CHK-M7-394 | `Findings` writes the message with `Object.assign(el, {innerHTML})` | 4 red: CHK-M7-314 (d), CHK-M7-388 (c), CHK-M7-391 innerHTML, CHK-M7-392 imports | green (exit 0): a form the lint misses, caught by the tests |
| CHK-M7-371a | Rebuild shows an "API token (bsk_)" input on `totp_session_required` | 1 red: CHK-M7-389 (c) 403 | green |
| CHK-M7-371b | Rebuild retries the POST with a `bsk_` Bearer on a 403 | 1 red: CHK-M7-389 (c) 403 | green |
| CHK-M7-395 | Rebuild writes the token (read off a sent request) to `sessionStorage` | 4 red, including CHK-M7-393 and CHK-M7-391 sessionStorage | red |
| CHK-M7-396 | Profile detail puts the token in the page URL (`history.replaceState`) | 9 red; CHK-M7-393 fails on `expect(window.location.href).not.toContain(TOKEN)`, the others on the afterEach leak check | green |
| CHK-M7-397 | Import history sends the token in its query | 1 red: CHK-M7-393 | green |
| CHK-M7-398 | Detail actions for operators (`role !== "viewer"`) | 2 red: CHK-M7-313 (c) operator, CHK-M7-390 operator | green |
| CHK-M7-399 | Detail actions for every role | 4 red: viewer and operator in CHK-M7-313 (c) and CHK-M7-390 | green |
| CHK-M7-400 | `ROUTE_ROLES.rebuild` set to every role | 4 red: CHK-M5-280 viewer and operator, CHK-M7-390 viewer and operator | green |
| CHK-M7-401 | `RouteView` mounts Imports without the role check | 2 red: CHK-M7-390 viewer and operator (a GET `/imports` was sent) | green |

The first runs of CHK-M7-395 to -397 read the token through `currentSession()`, which never exposes it. That planted nothing, and -397 stayed green. The plants were redone to read the real `Authorization` header in an `openapi-fetch` middleware, which is how hostile screen code would get it; all three then went red, as above. Driver: `%TEMP%\m7w-scripts\plants.py` (outside the tree). Copy: `%TEMP%\m7w-plant\web`.

#### Acceptance coverage

| Criterion | Rows |
| --- | --- |
| REQ-181 (1) list and detail render, `sort_order`, hostile text literal | CHK-M7-312 (a), (d); CHK-M7-313 (a), (e); CHK-M7-392 |
| REQ-181 (2) deleted: *Deleted*, no actions | CHK-M7-313 (b) |
| REQ-181 (3) exact REQ-168 bodies; other roles none | CHK-M7-313 (c); CHK-M7-390; plants -398, -399 |
| REQ-181 (4) paging, each once | CHK-M7-312 (c) |
| REQ-182 (1) one `file` part with the bytes; success and rejection display | CHK-M7-314 (a), (b) |
| REQ-182 (2) confirm, one DELETE, 409 text, TOTP prompt | CHK-M7-313 (d); plant -371a/b (same banner path) |
| REQ-182 (3) polling to `succeeded` or `failed` (fake timers), then files | CHK-M7-389 (b) |
| REQ-182 (4) import history each once, newest first | CHK-M7-388 (a), (b) |
| REQ-182 (5) hostile file names and messages | CHK-M7-314 (d), CHK-M7-388 (c), CHK-M7-389 (d), CHK-M7-392 |
| REQ-183 (1) G16 | Gates table |
| REQ-183 (2) `UserPathsArePrefixed` for the 8 operations | Gates table |
| REQ-183 (3) nav per role; admin route as viewer sends no request | CHK-M5-280, CHK-M7-390; plants -400, -401 |
| TASK-168: both types map; unknown generic | CHK-M7-311 |
| TASK-171: 413 and 409 messages | CHK-M7-314 (c) |
| TASK-172: 403 TOTP on rebuild shows sign-in-again | CHK-M7-389 (c) |
| TASK-173: hashes round-trip; exhaustive switch typechecks | CHK-M7-390; G13 |

#### Observations (no change requested)
- `ProfileDetail` shows the API's `display_name` rather than composing `<family_name> - <plugin_name>`. The test asserts the visible heading equals family + " - " + plugin name, so either way would pass. A wrong `v_plugin` would show up there only if the fixture's `display_name` were also wrong; that is manager-side (TASK-161).
- `toProblem` treats a body with no `type` as `about:blank` (M5 behaviour), so a typeless 503 with the exact detail and a Retry-After also maps to the start-up text. This matches RFC 9457's default type.

#### Files (tester-owned)
`web/src/app/App.test.tsx` (CHK-M5-280 updated, M7 rows added), `web/src/app/problems.test.ts`, `web/src/app/router.test.ts`, `web/src/app/sources.test.ts` (new), `web/src/screens/{Profiles,ProfileDetail,PolicyUpload,Imports,Rebuild}.test.tsx` (new), `web/src/test/harness.ts` (`contentType`, `form`), `tests/m7/test-plan.md` (rows CHK-M7-306 to -314, -388 to -401). The `tests/m7/report.md` rows are this file's tables; main folds them in, because the harness blocks my write there.

### TASK-174


Tester: tester-m7, 2026-10-28. Low risk (data, PD-35 second look). REQ-179 (1) to (4); SR §1.1, §2.4 (script rules), §4.2; TS §3.7 L500–L502, §8.6 L1329–L1337 (default redaction patterns, read from the spec text by the test); #111; G59 (`work/tasks.md`). File under test: `bits/samples/cis-ubuntu-24.04-l1-server.bit`. It shares one batch with TASK-175 (`work/reports/TASK-175-test.md`; plan row TP-M7-27). New test file: `manager/tests/test_bits_samples_pg.py` (50 tests). It imports through the TASK-154 pipeline (r1) into fresh databases.

**This run used the current tree, including the untested TASK-146 r2 BIT102 files** (`bit102.py`, `bit102_wrappers.py`, `bit102_braces.py`), because that is the code the samples have to pass (lead, 2026-10-28). A targeted re-run of `tests/test_bits_samples_pg.py` follows once 146 r2 is approved.

#### Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t174` of the current tree, `CI=true`) | Count |
| --- | --- | --- |
| g0 (`-n 2`, label `m7t-t174`) | `pytest tests/test_bits_samples_pg.py` | **50/50 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 5 data plants in throwaway copies of the samples (`/root/bstest-m7-mut-<id>`, removed after each); memory checked each time, `-n 0` below 3,000 MB | 5/5 red |
| static (L) | ruff, ruff format, `mypy --strict` (CI form) on the new file | clean |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-300 | APP | W | g0 | PASS | G59: both samples together in one fresh catalog (manual, server files), each `success` with no Reject finding and no BIT102; every plugin is in `policy_plugin` in file order, owned by its own policy and `active`; `plugins_added` equals the file's count (neither sample claims an id from the other); 2 live policies. Names and ids are distinct across the samples (parsed with defusedxml), and every id is a lowercase 8-4-4-4-12 UUID | 2026-10-28 |
| CHK-M7-301 | APP | W | g0 | PASS | The SR §1.1 example alone in another fresh catalog: `success` with no finding; the fixture equals the spec's code block | 2026-10-28 |
| CHK-M7-302 | CODE | W | g0 | PASS | REQ-179 (3): the 24.04 sample's first `<Plugin>…</Plugin>` source text is byte-identical to the SR §1.1 code block's, read from `docs/spec/bit_Schema_Reference.md`; `PolicyName` is "CIS Ubuntu 24.04 Level 1 - Server". REQ-179 (4): `PolicyDescription` ends with the #111 note; `PolicyStatus` `enabled`; `formatVersion` 1.0; 16 plugins | 2026-10-28 |
| CHK-M7-303 | CODE | W | g0 | PASS | One test per plugin (16 rows below): `Execute` is in CDATA. There is no `xargs`, no `find -exec`/`-execdir`/`-ok`/`-okdir`, no `eval`, no `source`/`.`, no `exec`, no `cd` and no `sudo`/`doas`/`su`. No shell is given a script, and no command runs from `/tmp`, `/var/tmp`, `/dev/shm`, `/home`, `~`, `./` or `$HOME`. There is no `/proc/mounts`, `/etc/mtab` or `mount`, and every `findmnt` line has `--task 1`. No uid-0 command is used (`nft`, `auditctl`, `iptables`, `ip6tables`, `aa-status`, `apparmor_status`, `sshd -T`, `ufw status`, `sysctl -w`), and there are no prompts. The timeout is 1–600. No default redaction pattern matches the `ExpectedResult`, and the five patterns were read from TS §8.6. Text operators expect a short value, not a sentence. The scan's own patterns are shown to fire on 9 bad examples and not on the SR example | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: `rm x` as a 24.04 plugin's Execute | PASS (red) | 1 failed: `test_g59_all_samples_together_in_one_fresh_catalog` (BIT102 at `Plugin[5]/Execute`) | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: a 22.04 plugin id set to a 24.04 one | PASS (red) | 2 failed: G59 (24.04 gets BIT015 at `Plugin[2]/PluginId`) and `test_policy_names_and_plugin_ids_are_distinct_across_the_samples` | 2026-10-28 |
| CHK-M7-303 plants | CODE | W | plants: a `findmnt` without `--task 1`; `nft list ruleset` | PASS (red) | 1 failed each, in the matching per-plugin script-rule row | 2026-10-28 |
| CHK-M7-302 plant | CODE | W | plant: the #111 note removed | PASS (red) | 1 failed: `test_description_note_and_status` | 2026-10-28 |
| G59 after 146 r2 | APP | W | — | NOT RUN yet | Targeted re-run of `tests/test_bits_samples_pg.py` once TASK-146 r2 is approved | 2026-10-28 |

#### Per-plugin script-rule rows (24.04 sample; each is `test_script_rules[cis-ubuntu-24.04-l1-server.bit:<name>]`, g0)

| # | PluginName | PluginId | Operator | Result |
| --- | --- | --- | --- | --- |
| 1 | 1.3.1.1 - Ensure AppArmor is installed | `3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48` | `equals` | PASS |
| 2 | 1.1.1.1 - Ensure cramfs kernel module is not available | `9f232f90-19f8-4b58-b886-65efaf83dd9c` | `regex` | PASS |
| 3 | 1.1.2.1.2 - Ensure nodev option set on /tmp partition | `178cee42-58a3-4f26-a6f6-01dd7671030a` | `regex` | PASS |
| 4 | 1.1.2.2.3 - Ensure nosuid option set on /dev/shm partition | `b0a43662-158b-4806-9481-4202dd531870` | `regex` | PASS |
| 5 | 1.5.1 - Ensure address space layout randomization is enabled | `43bc18fb-2a2d-4d05-b334-f6ab4fefb837` | `eq` | PASS |
| 6 | 1.5.2 - Ensure ptrace_scope is restricted | `b99dbc20-84e1-4e8a-b049-d39cba025e41` | `ge` | PASS |
| 7 | 1.5.4 - Ensure prelink is not installed | `b1d61ee2-cf1a-43ce-97b6-65bfdbbecae2` | `empty` | PASS |
| 8 | 2.2.4 - Ensure telnet client is not installed | `dfa7e395-744b-402f-84ad-585d6367eb45` | `empty` | PASS |
| 9 | 2.4.1.1 - Ensure cron daemon is enabled and active | `284bab45-0ec0-4e76-806c-fe744d4294af` | `equals` | PASS |
| 10 | 3.3.1 - Ensure ip forwarding is disabled | `5a8f31b0-afbb-455c-bee9-dd067dab4ff0` | `regex` | PASS |
| 11 | 4.1.1 - Ensure ufw is installed | `a925949c-5a85-4d67-8457-0b73f415dfb5` | `equals` | PASS |
| 12 | 5.1.1 - Ensure permissions on /etc/ssh/sshd_config are configured | `77f7a15a-4f1e-4a51-9684-75d8999c7473` | `empty` | PASS |
| 13 | 5.1.20 - Ensure sshd PermitRootLogin is disabled | `e5252af6-9d2e-4238-a553-6540e3083549` | `regex` | PASS |
| 14 | 5.4.1.1 - Ensure password expiration is configured | `142a7b43-b2d3-405e-92d2-6d334ef2f2dc` | `le` | PASS |
| 15 | 5.4.2.1 - Ensure root is the only UID 0 account | `37c25aa5-c5f2-44eb-b08e-facd1f96a8c4` | `equals` | PASS |
| 16 | 7.2.2 - Ensure /etc/shadow password fields are not empty | `d9cabf04-a21c-4bf6-904c-115768ca5d9d` | `empty` | PASS |

#### Notes for the reviewer (no defect)

- The script-rule scan is a pattern check, an aid to the review and not a substitute for it. BIT102 is the lexer-based check, and it ran through the import.
- Plugin 16 reads `/etc/shadow`. That is allowed: the runner has `CAP_DAC_READ_SEARCH` (TS L500). It prints only the user names whose password field is empty, or `unreadable`, never a hash, so redaction cannot hide the compared value. Its import alert flags `shadow` (#100 (c)), as it should.
- Plugin 9 uses `systemctl is-enabled` and `is-active`, the read-only uses that SR §4.2 and the D-Bus policy allow.

### TASK-175


Tester: tester-m7, 2026-10-28. Low risk (data, PD-35 second look). REQ-179 (1), (2), (4); #111; G59. File under test: `bits/samples/cis-ubuntu-22.04-l1-server.bit`. It shares one batch, test file and run with TASK-174. The runs, method and the note about the untested TASK-146 r2 BIT102 code are in `work/reports/TASK-174-test.md`. Test file `manager/tests/test_bits_samples_pg.py`; run g0 (W, `-n 2`): **50/50 passed**, 0 failed, 0 errors, 0 skipped.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-300 | APP | W | g0 | PASS | Imported together with the 24.04 sample into one fresh catalog: `success`, no Reject, no BIT102, all 16 plugins its own, in order and `active`. TASK-175's own acceptance: its `PolicyName` ("CIS Ubuntu 22.04 Level 1 - Server") and all 16 plugin ids differ from TASK-174's (the two id sets are disjoint) | 2026-10-28 |
| CHK-M7-302 | CODE | W | g0 | PASS | `PolicyDescription` ends with the #111 note; `PolicyStatus` `enabled`; `formatVersion` 1.0; 16 plugins | 2026-10-28 |
| CHK-M7-303 | CODE | W | g0 | PASS | One script-rule test per plugin (16 rows below), the same rules as in TASK-174's report | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: its first plugin id set to a 24.04 id | PASS (red) | 2 failed: G59 (BIT015) and the distinct-ids test | 2026-10-28 |
| CHK-M7-303 plants | CODE | W | plants: `findmnt` without `--task 1` (plugin 2); `nft list ruleset` (plugin 8) | PASS (red) | 1 failed each, in that plugin's row | 2026-10-28 |
| CHK-M7-302 plant | CODE | W | plant: the #111 note removed | PASS (red) | 1 failed: `test_description_note_and_status[cis-ubuntu-22.04-l1-server.bit]` | 2026-10-28 |
| G59 after 146 r2 | APP | W | — | NOT RUN yet | Targeted re-run once TASK-146 r2 is approved | 2026-10-28 |

#### Per-plugin script-rule rows (each is `test_script_rules[cis-ubuntu-22.04-l1-server.bit:<name>]`, g0)

| # | PluginName | PluginId | Operator | Result |
| --- | --- | --- | --- | --- |
| 1 | 1.1.1.1 - Ensure mounting of cramfs filesystems is disabled | `4ad2762c-4a2e-4cc9-b2d9-aaa07e2dd004` | `regex` | PASS |
| 2 | 1.1.2.2 - Ensure nodev option set on /tmp partition | `b69d9484-b747-49e5-9e18-77286c465462` | `regex` | PASS |
| 3 | 1.5.1 - Ensure address space layout randomization (ASLR) is enabled | `d51aca51-c254-4205-b160-0652821bc7c8` | `eq` | PASS |
| 4 | 1.5.2 - Ensure prelink is not installed | `ee728f4f-4efa-4e79-a1ad-e46310bb58fe` | `empty` | PASS |
| 5 | 1.6.1.1 - Ensure AppArmor is installed | `62a0af59-300a-4530-a7ba-c5cea17b882e` | `empty` | PASS |
| 6 | 2.3.4 - Ensure telnet client is not installed | `107c56a7-2a88-4525-bd10-22df060715cc` | `empty` | PASS |
| 7 | 3.2.2 - Ensure IP forwarding is disabled | `296d3e22-0ecf-469f-9cf1-d6b54df12d60` | `regex` | PASS |
| 8 | 3.3.8 - Ensure TCP SYN Cookies is enabled | `59a56ce7-5eb1-4aa0-a078-f6761b36d69b` | `eq` | PASS |
| 9 | 3.5.1.1 - Ensure ufw is installed | `01b0f9e1-409b-4709-880f-a45e652d16a1` | `equals` | PASS |
| 10 | 5.1.1 - Ensure cron daemon is enabled and running | `9d401969-5f86-4dda-bd55-0006798cd5b7` | `equals` | PASS |
| 11 | 5.2.1 - Ensure permissions on /etc/ssh/sshd_config are configured | `54a418be-5377-4c7d-ad77-f9517dc85b72` | `empty` | PASS |
| 12 | 5.2.7 - Ensure SSH root login is disabled | `6669fc6d-e26c-4e3f-9dcc-1c8bf82f1b5f` | `regex` | PASS |
| 13 | 5.2.18 - Ensure SSH MaxAuthTries is set to 4 or less | `f3774cdb-aa44-4fbe-82c1-4661a6cf5547` | `regex` | PASS |
| 14 | 5.5.1.2 - Ensure password expiration is 365 days or less | `597aaa58-5ea8-44f5-b368-f3ea4e166add` | `le` | PASS |
| 15 | 6.1.1 - Ensure permissions on /etc/passwd are configured | `857797fb-c2a0-4f00-bc7a-50a0f213f39c` | `regex` | PASS |
| 16 | 6.2.2 - Ensure /etc/shadow password fields are not empty | `4631d4ee-b1c7-4912-99e3-f10954d4a101` | `empty` | PASS |

Note (no defect): plugin 16 reads `/etc/shadow` and prints only the user names with an empty password field, or `unreadable`. The same note applies as for TASK-174's 7.2.2.

### TP-M7-30


Tester: tester-m7d, 2026-10-28. REQ-177 (1), (2); CHK-M7-285. Spec: TS §8.3 Security L1283 (importer half), §8.1 L1241, L1251, L1253; §4.1 L522, L530; §6 L1056; §6.2 L1084, L1104, L1105; §5.3 L1051; §8.4 L1289 to L1291; SR §4.1 BIT001, BIT015, BIT102; #1, #99 (b), (d), #100, #101, #102 (b). BIT102 uses only the cases settled before TASK-146 r2 (lead, 2026-10-28): `rm x` is rejected and the shipped samples pass.

**New tester file:** `manager/tests/test_security_m7.py` (16 test functions, 38 cases).
- It runs end to end through the real routes, the real `CatalogService`, start-up sequence, rebuild worker, sink gate and auth.
- It uses a database of the module's own and a temporary bits folder, with the `bits/tests/` fixtures (BIT001 XML set, `db/bit015-*`, `hostile_names` forms) and `bits/samples/*.bit`.

**Helper change:** `manager/tests/catalog_api.py` gained `RecordingSink` and an optional `sink=` argument on `make_env`, so a test can check that alerts reach the sink. Nothing else changed, and the three route suites were re-run on it.

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| d0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` pinned) | `pytest tests/test_security_m7.py` | 37/38 passed, 1 failed, 0 errors, 0 skipped |
| d0 failure (test bug) | `test_agent_tokens_are_refused_on_every_m7_route`. Expected 401; actual 429 `rate_limited`: 24 failed token checks from one IP within a minute crossed the 20/min limit (TS §6.3). Fix: the test clock moves 61 s between token kinds, so at most 8 checks fall in a minute | fixed in the test |
| d1 (W) | that node id | 1/1 passed |
| plants (W, `-n 0`, throwaway copy `/root/bstest-m7d-mut`, every edited file restored after each, copy deleted after) | `pytest tests/test_security_m7.py -k <rows>` | 24/24 plants red |
| r0 (W, clean tree re-synced) | `pytest tests/test_security_m7.py tests/test_policy_import_api_pg.py tests/test_policy_delete_api_pg.py tests/test_rebuild_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py` | 236/236 passed, 0 failed, 0 errors, 0 skipped |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 312 files formatted; no issues in 312 source files |

- **Product files under test** (sha256 prefix): `openapi.json` 2eacec4e800031e4, `parse.py` 509307590fc318d5, `folders.py` 2fd4a1340dbabac1, `uploads.py` 4acc0e2d09cc385c, `pipeline.py` 2cc75d132d4f0fa3, `alerts.py` 3bbf0e48cc0d0c24, `bit102.py` fee8ac5e396ad920, `store_decide.py` 4db7c583f00a3dfd, `auth/dependencies.py` 1dfc6ef504308e33.
- **Subprocess imports:** every run and plant set `PYTHONPATH` to the tree under test, so the `db migrate` console-script subprocess never used the shared venv's editable install.
- **Containers:** none of mine are left (`docker ps -a`).

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-285 XML upload | APP | W | r0 | PASS | Eleven fixtures, each uploaded by an admin `bsk_`: `xxe-file`, `xxe-url`, `parameter-entity`, `parameter-entity-internal`, `external-dtd-file`, `external-dtd-url`, `billion-laughs`, `quadratic-blowup`, `dtd-only`, `dtd-element-decl`, `undefined-entity`. Each gives 200 `rejected` with exactly `[BIT001]`. Nothing is stored (empty bits tree) and no policy of the fixture's name exists. A process-wide audit hook saw no `open` of the canary file, from any thread. A local TCP listener on the fixture's port saw no connection. The canary text is in neither the response, the stored `errors` nor any log record. Each finishes in under 10 s | 2026-10-28 |
| CHK-M7-285 oversize | APP | W | r0 | PASS | A 5,242,881-byte upload gives 413 `too_large` with no `bit_import` row and nothing on disk (#99 (b)). A 5,242,881-byte server-folder file is a `rejected` BIT001 row at start-up (`auto`) and again in a rebuild (`rebuild`), and its policy never exists | 2026-10-28 |
| CHK-M7-285 XML folder | APP | W | r0 | PASS | `xxe`, `laughs`, `blowup`, `dtd` and `big` placed in the server folder. The start-up reconcile and then `POST /policies/rebuild` each write one `rejected` row per file with exactly `[BIT001]`, and the task result lists all five as `rejected`. The canary is never opened and is in no stored finding | 2026-10-28 |
| CHK-M7-285 symlink/FIFO | APP | W | r0 | PASS | Symlinks `link.bit`, `uploaded/link.bit` and `uploaded/policy-999999.bit` point at valid policy files outside the folder; FIFOs `fifo.bit` and `uploaded/fifo.bit` sit in the folders. A restart finishes its start-up, so a FIFO never blocks it, and a rebuild ends `succeeded`. None of the target policies is imported, no `bit_import` row is written (not even a rejected one), and no skipped path is in the task's `files`. The links are unchanged, and the targets keep their bytes and mtime | 2026-10-28 |
| CHK-M7-285 upload paths | APP | W | r0 | PASS | A symlink at `uploaded/.tmp-<id>-<sha>` makes the upload 503 with no row; its target keeps `keep`, and the stored v1 is unchanged (REQ-163 (2)). A symlink at `uploaded/policy-<id>.bit` is replaced by a regular file holding v3; its target keeps `keep` | 2026-10-28 |
| CHK-M7-285 client path | APP | W | r0 | PASS | Nine client names: `../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, `../outside.bit`, `.tmp-1-<64 zeros>`, `policy-1.bit`, `uploaded/policy-1.bit`, `C:\Windows\x.bit`. A snapshot of the whole test directory before and after shows exactly one new file, `bits/uploaded/policy-<id>.bit` with the uploaded bytes, and no other file changed | 2026-10-28 |
| CHK-M7-285 route group | APP | W | r0 | PASS | The walk equals the OpenAPI document's eight M7 operations: `GET /policies`, `GET`, `PATCH` and `DELETE /policies/{id}`, `POST /policies/import`, `POST /policies/rebuild`, `GET /tasks/{id}`, `GET /imports`. On each of them, a random `bsa_`, the `bsa_` of an enrolled `online` agent (hash stored) and a `bse_` get 401 `unauthorized`. Catalog, `bit_import`, task, job, schedule and bits-tree state is unchanged, and the policy stays `enabled` | 2026-10-28 |
| CHK-M7-285 API tokens | APP | W | r0 | PASS | An admin `bsk_` gets 403 `totp_session_required` on `DELETE /policies/{id}` and on `POST /policies/rebuild`, with nothing changed. The same admin's TOTP session then gets 204 and 202 | 2026-10-28 |
| CHK-M7-285 non-admins | APP | W | r0 | PASS | Operator and viewer, with a session and with `bsk_`: upload gets 403 `forbidden`, and delete gets 403 (`forbidden` for sessions). Nothing changed | 2026-10-28 |
| CHK-M7-285 sink gate | APP | W | r0 | PASS | At 15:00 into a sink outage, delete and rebuild get 503 `audit_sink_unavailable` with nothing changed. After the queue drains, the delete gives 204 (#1) | 2026-10-28 |
| CHK-M7-285 logs | APP | W | r0 | PASS | Canaries placed in an `Execute`, a `PolicyDescription`, a `PluginDescription` and an `ExpectedResult`, plus a rejected `rm <canary>`. Then: upload, `GET /policies/{id}` (which does show the `Execute`, #98 (b)), PATCH disable and enable, rebuild, delete, and a failed check with a `bsa_`. None of the four canaries, the admin `bsk_`, the session token or the agent token appears in any log record (DEBUG) or on fd-level stdout/stderr. Log records exist, so the sweep has input | 2026-10-28 |
| CHK-M7-285 alerts | APP | W | r0 | PASS | The sequence upload, rejected upload, PATCH re-enable, rebuild, delete writes `policy_imported`, `policy_import_rejected`, `policy_reenabled`, `policy_rebuilt` and `policy_deleted` entries (`alert: true`). `bitscan_alerts_total{kind}` rises by exactly the number of entries of each kind. The `policy.import` entry has actor `user:<id>` and one `changed_executes` item with the full command, reason `new` and flags `[".ssh"]` (#100). Every kind reaches the sink (`RecordingSink` through the real shipper) | 2026-10-28 |
| CHK-M7-285 BIT102 | APP | W | r0 | PASS | `rm x` is rejected with BIT102 by upload (`manual`), at start-up (`auto`) and by rebuild (`rebuild`), and its policy never exists. Both `bits/samples/*.bit` upload as `success` with no BIT102 | 2026-10-28 |
| CHK-M7-285 BIT015 | APP | W | r0 | PASS | `db/bit015-owner.bit` succeeds. `db/bit015-claimer.bit` is rejected with BIT015, and the catalog, tasks, jobs, schedules and files are unchanged apart from its one `bit_import` row | 2026-10-28 |
| CHK-M7-320 | APP | W | plant: `parse.py` with every forbid off and an `ExternalEntityRefHandler` that reads `file://` paths (only the test's own temporary canary) | PASS (red) | 6 failed, among them `xxe-file`, `external-dtd-file`, `dtd-only`, `dtd-element-decl`. The other 5 (billion laughs, quadratic blow-up and others) stay refused by expat's own limits, a second layer | 2026-10-28 |
| CHK-M7-321 | APP | W | plant: `forbid_dtd=False` | PASS (red) | 5 failed: `external-dtd-file`, `external-dtd-url`, `dtd-only`, `dtd-element-decl`, the folder row | 2026-10-28 |
| CHK-M7-285-failopen | APP | W | plant: the DTD, entity and external-reference refusals return no finding | PASS (red) | 11 failed: ten XML upload cases and the folder row | 2026-10-28 |
| CHK-M7-323 | APP | W | plant: parser and folder read caps + 1 byte | PASS (red) | 1 failed: the folder row (`big.bit` not rejected) | 2026-10-28 |
| CHK-M7-324 | APP | W | plant: `bit` class 6 MiB and part cap + 1 | PASS (red) | 1 failed: `test_an_oversize_upload_is_413_with_no_row` | 2026-10-28 |
| CHK-M7-363 | APP | W | plant: discovery follows symlinks and `O_NOFOLLOW` dropped | PASS (red) | 1 failed: the symlink/FIFO row | 2026-10-28 |
| CHK-M7-285-fifo | APP | W | plant: discovery keeps any non-directory and the `S_ISREG` check dropped (O_NONBLOCK kept, so nothing hangs) | PASS (red) | 1 failed: the symlink/FIFO row | 2026-10-28 |
| CHK-M7-357 | APP | W | plant: the temp file opened `O_CREAT \| O_TRUNC`, no `O_EXCL` or `O_NOFOLLOW` | PASS (red) | 1 failed: the temp/final symlink row | 2026-10-28 |
| CHK-M7-358 | APP | W | plant: the stored file named after the client name (kept inside the folder) | PASS (red) | 8 failed: every client path except `..` | 2026-10-28 |
| CHK-M7-285-group | APP | W | plant: `current_principal` accepts a `bsa_` or `bse_` as an admin | PASS (red) | 1 failed: the route-group row | 2026-10-28 |
| CHK-M7-341, -342 | APP | W | plant: `_gate`'s TOTP-session check passes API tokens | PASS (red) | 1 failed: the API-token row (delete and rebuild) | 2026-10-28 |
| CHK-M7-343, -344 | APP | W | plant: the sink gate off in `_gate` | PASS (red) | 1 failed: the sink-gate row | 2026-10-28 |
| CHK-M7-345 | APP | W | plant: upload `require_role("operator")` | PASS (red) | 2 failed: operator session and `bsk_` | 2026-10-28 |
| CHK-M7-346 | APP | W | plant: delete `require_totp_session("operator")` | PASS (red) | 1 failed: operator session | 2026-10-28 |
| CHK-M7-285-logtext | APP | W | plant: the route logs the first 4 KiB of the file | PASS (red) | 1 failed: the log row | 2026-10-28 |
| CHK-M7-285-logtoken | APP | W | plant: a failed token check logs the raw token | PASS (red) | 1 failed: the log row | 2026-10-28 |
| CHK-M7-349 to -353 | APP | W | plants (one each): `policy_imported`, `policy_import_rejected`, `policy_deleted`, `policy_rebuilt`, `policy_reenabled` written as plain entries (`kind=None`) | PASS (red) | 1 failed each (5 plants): the alert row | 2026-10-28 |
| CHK-M7-354 | APP | W | plant: `flags` always `[]` | PASS (red) | 1 failed: the alert row | 2026-10-28 |
| CHK-M7-285-bit102 | APP | W | plant: `bit102.check_execute` returns no finding | PASS (red) | 1 failed: the `rm x` row. The samples rows stay green, as they should | 2026-10-28 |
| CHK-M7-335 | APP | W | plant: `check_ownership` returns no finding | PASS (red) | 1 failed: the BIT015 row | 2026-10-28 |

#### Acceptance

REQ-177 (1): `manager/tests/test_security_m7.py` covers each importer item of TS §8.3 Security L1283, and it runs in CI, which runs the whole pytest suite.
- Non-admins refused for upload and delete.
- API tokens refused on delete and rebuild.
- Tokens on the wrong route group, on every M7 operation.
- Hostile upload file names stored safely.
- BIT015 and BIT102 rejections.
- XXE, entity expansion and oversize rejected.
- Also covered: symlinks and FIFOs never followed, the sink gate, no plugin text or token in logs, and every catalog alert written and shipped.

REQ-177 (2): every security plant of the M7 mutation table aimed at this suite went red: 320, 321, 323, 324, 335, 341 to 346, 349 to 354, 357, 358 and 363, plus the fail-open, FIFO, route-group, log and BIT102 plants (24/24).

#### Notes (no defect)

- **The XXE-resolver plant shows defence in depth.** With defusedxml's guards off, billion laughs and quadratic blow-up are still refused by expat's own amplification limit. The fail-open plant, which takes away defusedxml's refusal outright, turns every XML case red.
- **An oversize upload is a 413 with no row (#99 (b)), not a BIT001 row.** The brief said BIT001 for oversize uploads; the suite asserts #99 (b) for uploads and BIT001 for folder files.
- **BIT102 coverage is deliberately narrow:** only `rm x` and the two samples. The TASK-146 r2 cases (su/runuser, time -o, flock, and the rest) belong to TASK-146 r2's own test and are not here.
- **The suite is Linux-only,** like every PostgreSQL suite (FIFOs and symlinks). `mkfifo` is guarded for the Windows type check, and nothing is skipped on Linux.

### M7-gate


Tester: tester-m7, 2026-10-28. Gate section "### M7 gate" and mutation table CHK-M7-320 to -371 of `work/tasks.md`; plan `tests/m7/test-plan.md`. Tree: the worktree `Bitscan-m7` (branch `m7-catalog`, HEAD `25d41ec` plus the uncommitted M7 work), every M7 task APPROVED; TASK-146 r2 was deferred by the user (decisions "TASK-146 r2 deferred", 2026-10-29) and `bit102.py` is back to r1.

W runs used fresh copies (`/root/bstest-m7-gate`) with `CI=true`, `PYTHONPATH` pinned to the copy's tree, and memory checked before each run. Runs were `-n 0` while tester-m7d ran PostgreSQL, and `-n 2` afterwards with at least 3,000 MB free. The web UI was built (`npm run build`, the gitignored `manager/bitscan_manager/webui/`) as CI does. No containers were left.

#### Verdict

**PASS.** Every gate below is green on the final tree, and every mutation row is red (from the per-task reports, or run here). Three test bugs found by G18 were fixed and re-run, and G54's timing rows got a measurement fix under the lead's ruling, with the bound unchanged. **TASK-146 r2 deferred:** its rows ran on the restored r1 tree (see "r1 re-run" below), all green. Also NOT RUN, per the gate section: the TS §8.3 Sandbox half (no runner until M10), the VM end-to-end import (M11 nightly) and the load tests (deferred by the user).

#### Gate rows

| Gate | Command | Result | Evidence | Plant (red) |
| --- | --- | --- | --- | --- |
| G1 | `ruff check manager` | PASS | All checks passed (312 files) | CHK-M7-336, -337 (TASK-148/150 reports), -347, -348 (TASK-141/144) |
| G2 | `ruff format --check manager` | PASS | 312 files already formatted | — |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | PASS | no issues in 312 source files | an untyped function appended to `store.py` (throwaway copy) → `no-untyped-def`, red |
| G4 | `pip install --dry-run --require-hashes --no-deps -r manager/requirements.txt` and `-dev.txt` | PASS | exit 0 for both (35 and 71 lines resolved). A dry run into the existing venv checks every pin and hash without changing the venv that the WSL runs and tester-m7d share; CI does the real `--require-hashes` install | — |
| G5 | `pytest --cov=bitscan_manager/services --cov-fail-under=85` (CI form, full suite, `-n 2`) | PASS | **95.34 %** (4,845 statements, 226 missed; `services/importer` included, every importer module ≥ 91.11 %) | an untested 600-statement function in `folders.py`, sized from the clean report (more than 589 needed): see "G5 plant" below |
| G6 | `tests/test_openapi.py` | PASS | 39/39 with G34; the export is byte-identical to `manager/openapi.json` | a route added in `policies.py` without re-export → 3 failed (committed file, module command, route walk), red |
| G12 | `npm run lint` (web) | PASS | exit 0, no warnings | CHK-M7-370 (`TASK-168-173-test.md`) |
| G13 | `npm run typecheck` | PASS | exit 0 | — |
| G14 | `npm run format:check` | PASS | All matched files use Prettier code style | — |
| G15 | `npm run test` (vitest) | PASS | 21 files, 516/516 passed | CHK-M7-370, -371 (`TASK-168-173-test.md`) |
| G16 | `npm run gen:api` | PASS | `src/api/schema.d.ts` byte-identical after regeneration (sha256 unchanged) | `openapi.json` changed (a planted property) without regeneration → the generated client differs, red |
| G18 | full manager suite (`-n 2`, with G5) | PASS | Run 1: **8,862 passed, 3 failed, 0 skipped**; the 3 were test bugs (below), fixed, then 14/14 by node id and 237/237 for the three files. Run 2 (the G5-planted copy, every fix in): **8,866 passed, 0 failed, 0 errors, 0 skipped**; see "G5 plant" | any of G54–G61 |
| G34 | `tests/test_invariants_m3.py` | PASS | in 39/39 above; the route walk has the eight M7 operations | CHK-M7-361 (TASK-161); the G6 plant's extra route → red |
| G54 | importer unit suite (`test_bit_model`, `_parse`, `_values`, `_structure`, `_validate`, `test_bit102_lexer`, `test_bit102`, `test_import_alerts`, `test_bit_fixtures`) | PASS (re-run) | 3,049/3,050; `test_pathological_inputs_bounded[seps]` failed the 100 ms bound at 0.103 s. Lead ruling (b): a measurement fix, below. Then `test_bit102_lexer.py` 173/173, and 237/237 with the G18 fixes | the G54 rows (TASK-140–146 reports); quadratic lexer → red under the new timing |
| G55 | `test_bit_fuzz.py`, `test_import_fuzz_pg.py` | PASS | 5/5 | CHK-M7-340 (TASK-154) |
| G56 | importer integration (13 files: lock, repos, store, delete, pipeline, uploads, folders, rebuild, start-up, `test_catalog_service_pg.py` (the table's `test_catalog_service.py`), import alerts) | PASS | 507/507 | the G56 rows (per-task reports) |
| G57 | catalog API and security (`test_policies_api_pg`, `_imports_api_`, `_policy_import_api_`, `_policy_delete_api_`, `_rebuild_api_`, `test_security_m7.py`) | PASS | 341/341, including TP-M7-30's 38 cases | the G57 rows (TASK-161–165, TP-M7-30: 24/24 red) |
| G58 | `test_cli_bits_pg.py` | PASS | 12/12 | CHK-M7-362 (TASK-166 c1) |
| G59 | `test_bits_samples_pg.py` | PASS | 50/50 on the current tree (TASK-146 r2 code included) | CHK-M7-366 (TASK-174/175) |
| G60 | `test_catalog_alerts_pg.py` (new, below) | PASS | 7/7 | CHK-M7-349–355 (below) |
| G61 | `test_watcher_linux_pg.py` (the table's `test_watcher_linux.py`), `test_serve_catalog_linux.py` | PASS | 22/22 | CHK-M7-367, -368 (below) |
| CHK-M7-305 | `test_readme_m7_walk_linux.py` (new, below) | PASS | 1/1, every row as the README says | — |

#### G5 plant

- **Plant.** A never-called function of 600 assignments appended to the end of `bm/services/importer/folders.py` (`_planted_untested`; 602 statements with its `def` and `return`). It was sized from the clean report: 4,845 statements and 226 missed, so more than 589 uncovered statements take the total under 85 %. It ran in a throwaway copy (`/root/bstest-m7-mut-g5`, removed afterwards).
- **Run.** The CI form, `pytest -n 2 --cov=bitscan_manager/services --cov-fail-under=85`, on the whole suite with every G18 fix in. This is G18 Run 2.
- **Result: red.** Coverage **84.84 %** (5,447 statements, 826 missed; `folders.py` 769 / 610 / 20.68 %) against the 85 % floor: "Coverage failure: total of 84.84 is less than fail-under=85.00", pytest exit 1, while all **8,866 tests passed** (0 failed, 0 errors, 0 skipped).
- **Clean.** 95.34 % (4,845 / 226) in Run 1.

#### G18 findings: three test bugs, no product defect

| Test | Expected vs actual | Diagnosis | Fix and re-run |
| --- | --- | --- | --- |
| `test_bit102_lexer.py::test_long_inputs_up_to_16384_chars` | < 0.1 s, got 2.78 s | Under the G5 coverage tracer the in-process timing measures the tracer. This is the same issue as the G54 row | The same ruling (b): the functional check in process, then the timing in a clean `python -I` subprocess when the in-process time exceeds 100 ms. 1/1, and 1/1 under `--cov` |
| `test_cli.py::test_refused_commands_touch_no_env_socket_or_db[bits rebuild]` | no `BITSCAN_*` read, got `['BITSCAN_BITS_DIR']` | Stale. `bits rebuild` was still listed as an unimplemented stub, but TASK-166 implemented it, and #107 (a) lets it read the non-secret `BITSCAN_BITS_DIR` | `["bits"]` stays a stub. New row `test_bits_rebuild_without_its_folder_reads_only_bits_dir`: exit 2, no database module loaded, only `BITSCAN_BITS_DIR` read. 1/1 |
| `test_login.py::test_documented_400_matches_what_the_app_returns` | 400, got 503 for `POST /policies/import` | Its `Runtime` has `catalog=None`, the state "in tests and the OpenAPI export", where the route answers 503 first. In `serve` the catalog is present, and a bad body is 400 even during start-up (the body is parsed before the catalog is called) | The test's `Runtime` gets a stub catalog that the bad body never reaches. 1/1 |

#### G54 measurement fix (lead ruling (b), 2026-10-28)

- **Cause.** In a pytest test, `sys.gettrace()` and `sys.getprofile()` are None, `sys.monitoring` has no tool, and the flags show no dev mode. The same `"a;" * 8192` lexing measured 55–59 ms in one pytest run and 103.5 ms in another, against 56 ms in a plain script. Thread CPU time still scales with core speed and contention on this shared WSL machine, so the in-process best of five had no headroom.
- **Change.** In `test_pathological_inputs_bounded` (all ten parameters), the functional assertions stay in process, and the timing runs in a clean `python -I` subprocess, best of 10, asserted < 100 ms. The bound is unchanged. `test_long_inputs_up_to_16384_chars` follows the same rule (see G18).
- **Plant.** A quadratic lexer (`len(list(src[:pos]))` per token) → 6 of 10 parameters red.
- Recorded in `work/reports/TASK-145-test.md`.

#### New gate files

- `manager/tests/test_catalog_alerts_pg.py` (G60). It raises each of the six M7 alert kinds through its real path:
  - `policy_imported` (pipeline; the changed Execute with its `shadow` flag);
  - `policy_import_rejected` (an auto import of `rm x`, with `fail:auto` +1);
  - `policy_deleted` (the delete service);
  - `policy_reenabled` (PATCH service and file);
  - `policy_rebuilt` (the rebuild);
  - `catalog_integrity_failed` (the start-up).

  Each test checks the one audit entry (action, target, actor, `alert` true, kind), the counter +1 exactly, and delivery of that entry to a recording sink through `Shipper.run_once`; a clean start-up raises none.
- `manager/tests/test_readme_m7_walk_linux.py` (CHK-M7-305). A real `serve` over HTTPS with a temporary bits folder, fake OpenBao and sink, an admin with a TOTP session and a `bsk_` token. One row per README "Policies" step:
  - start-up import; the watcher importing a copied file; ignored names;
  - rename in place; BIT007; the `auto` skip; version +1;
  - upload (keys, `policy-<id>.bit`, the client name only in the history, `bsk_` allowed, a rejection with every finding, 413 over 5 MiB, 409 for a server policy); the server file taking over an upload (move audited);
  - list and detail keys; PATCH (override, `?status`, clear + `policy_reenabled`);
  - DELETE (`bsk_` refused, 204, the alert, 409 `conflict`, 404, 409 `policy_managed_on_server`, PATCH of a deleted policy 409, revival with the same id); import history (keys, newest first, modes and outcomes);
  - rebuild (`bsk_` refused, 202, the task result shape, `policy_rebuilt`); `bits rebuild` (lines, summary, exit 0);
  - removing a file deletes it; `catalog_integrity_failed` at a restart with a damaged catalog; the 503 with `Retry-After: 10` while the start-up can't finish;
  - the hard-link warning and the 8 KiB sink note present.

  `sudo` and the fixed `/etc/bitscan/secrets/app.dsn` are replaced by `bits_main` with a temporary DSN file (the fixed path is TASK-166's row).

#### Mutation table CHK-M7-320 to -371

| Row | Plant | Result | Evidence |
| --- | --- | --- | --- |
| 320–323 | XXE, DTD, entities, oversize cap in the parser | red | `TASK-141-test.md`; TP-M7-30 (320, 321, 323) |
| 324 | import route cap removed or raised | red | `TASK-162-test.md`; TP-M7-30 |
| 325 | BIT013 with Python `re` | red | `TASK-142-test.md` |
| 326 | BIT013 skipped for `not_regex` | red | `TASK-144-test.md` |
| 327–331 | BIT102 substring, path names, nested scripts, wrappers, redirects | red | `TASK-146-test.md` (r1, the rules now in the tree; r2 deferred) |
| 332 | lexer errors pass (fail open) | red | `TASK-145-test.md`, `TASK-146-test.md` |
| 333 | BIT102 skipped in rebuild or upload | red | `TASK-154-test.md` (333a, 333b) |
| 334 | BIT001/BIT002 still run content rules | red | `TASK-143-test.md` |
| 335 | BIT015 removed | red | `TASK-151-test.md`; TP-M7-30 |
| 336, 337 | f-string SQL | red | `TASK-148-test.md`, `TASK-150-test.md` |
| 338 | a commit per plugin | red | `TASK-151-test.md` |
| 339 | `bit_import` in the catalog transaction | red | `TASK-149-test.md`, `TASK-154-test.md` |
| 340 | late exception swallowed and committed | red | `TASK-154-test.md` (340a, 340b; the fuzz) |
| 341–346 | API token on DELETE and rebuild; sink gate off; operator upload and delete | red | `TASK-162/163/164-test.md` (tester-m7d); TP-M7-30 (341, 343, 345, 346) |
| 347, 348 | `xml.etree` in `parse.py`, `re` in `validate.py` | red | `TASK-141-test.md`, `TASK-144-test.md` |
| 349 | no `policy_imported` | red | `TASK-154-test.md`; TP-M7-30 |
| 350 | no `policy_import_rejected` or failure count | red | `TASK-154-test.md` (350a, 350b) |
| 351 | no `policy_deleted` | red | `TASK-152-test.md` |
| 352 | no `policy_rebuilt` | red | `TASK-157-test.md` (plant b8: 6 failed) |
| 353 | no `policy_reenabled` on PATCH | red | `TASK-161-test.md` |
| 354 | import alert drops Executes or flags | red | `TASK-153-test.md`; TP-M7-30 |
| 355 | no `catalog_integrity_failed` | **red, run here** | the integrity alert's emit removed → 4 failed (`test_catalog_alerts_pg` integrity row and three start-up rows); also `TASK-158-test.md` s7, s8 |
| 356 | the catalog lock removed | red | `TASK-147-test.md`, `TASK-152-test.md` |
| 357 | `O_EXCL` or `O_NOFOLLOW` removed | red | `TASK-155-test.md` (u1–u4, u13+u4); TP-M7-30 |
| 358 | client name in the stored path | red | `TASK-155-test.md` (u11), `TASK-162-test.md`; TP-M7-30 |
| 359 | rejected upload replaces the file, or rollback leaves the temp | red | `TASK-155-test.md` (u5, u9, u12) |
| 360 | upload of a server-folder policy accepted | **red, run here** | the `PolicyManagedOnServer` decision removed → 2 failed (`test_uploads_pg` server-folder row, `test_policy_import_api_pg` 409 row) |
| 361 | PATCH accepts `execute` | red | `TASK-161-test.md` |
| 362 | CLI DSN from env or argv | red | `TASK-166-test.md` (c1) |
| 363 | symlinks in the server folder followed | red | `TASK-156-test.md` (f4, f5, f13); TP-M7-30 |
| 364 | rebuild changes `agent` (or `scan_result`, `audit_log`) | **red, run here** | `UPDATE agent SET hostname = hostname \|\| 'x'` inside the rebuild → 1 failed (`test_untouched_tables_stay_untouched`) |
| 365 | hard DELETE or no job cancel | red | `TASK-150-test.md`, `TASK-152-test.md` |
| 366 | sample with `rm`, or a shared id | red | `TASK-174-test.md`, `TASK-175-test.md` |
| 367 | watcher follows non-`.bit` files (or subfolders) | **red, run here** | the `.bit` name test removed → 1 failed (`test_ignored_names_and_kinds`); hidden names `TASK-159-test.md` w2. Subfolders give no inotify event in a non-recursive watch; the subfolder row stays green by construction |
| 368 | integrity check before the reconcile | red | `TASK-158-test.md` (s1: 5 failed) |
| 369 | override ignored; +1 on identical hash; auto/manual skip | red | `TASK-148/151/154-test.md` |
| 370, 371 | `dangerouslySetInnerHTML`; API token on the rebuild screen | red | `TASK-168-173-test.md` |

#### r1 re-run (TASK-146 r2 deferred, 2026-10-29)

The r2 rows that were NOT RUN are replaced by this run on the restored r1 tree:
- `bit102.py` is byte-identical to c6b7e13 (sha256 `279291cf…`);
- `bit102_wrappers.py` and `bit102_braces.py` are gone, and nothing in `manager/` imports them;
- the BIT102 tests and the `bits/tests` corpora are unchanged since r1.

The run used a fresh copy `/root/bstest-m7-r1`, `CI=true`, `PYTHONPATH` pinned and `-n 2` (5,135 MB free). The `R2_PENDING` exclusion was dropped from `test_import_pipeline_pg.py`.

| Row | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-191 (all fixtures) | `test_import_pipeline_pg.py::test_each_rejecting_fixture_writes_its_rejected_row_and_alert` | PASS | 150/150, including the six BIT102 fixtures `rm`, `redirect`, `systemctl-stop`, `sed-i`, `bash-c-subst` and `unlexable`: each gives a `rejected` row with exactly its manifest codes, one rejected alert, the failure count, and no catalog change |
| G59 re-run | `test_bits_samples_pg.py` | PASS | 50/50 on r1 |
| r1 BIT102 suites | `test_bit102.py`, `test_bit102_lexer.py`, `test_bit_validate.py`, `test_bit_fixtures.py` | PASS | 1,160/1,160 (as the r1 record), 173/173, 687/687, 227/227 |
| total | the six items above | PASS | **2,447/2,447 passed**, 0 failed, 0 errors, 0 skipped |
| gates | whole-tree `ruff check`, `ruff format --check`, `mypy --strict` (CI form) | PASS | clean, 310 files; no import of the removed modules |

#### NOT RUN

| Row | Reason |
| --- | --- |
| TS §8.3 Sandbox "full CIS plugin set under the sandbox" | no runner until M10 (gate section) |
| End-to-end import on VMs; load tests | M11 nightly; deferred by the user (gate section) |
