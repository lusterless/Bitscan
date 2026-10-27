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

