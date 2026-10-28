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

## W2 and W3 (folded 2026-10-27, cloud session)

Folded by the lead, unchanged except that headings are demoted two levels. Every task below also has REVIEW APPROVED and the user's second approval (decisions 2026-10-27).

| Task | Verdict | Source |
| --- | --- | --- |
| TASK-141 | PASS (revision 1) | `work/reports/TASK-141-test.md` |
| TASK-142 | PASS | `work/reports/TASK-142-test.md` |
| TASK-143 | PASS | `work/reports/TASK-143-test.md` |
| TASK-144 | PASS | `work/reports/TASK-144-test.md` |
| TASK-145 | PASS (r0; r1 + r1b in the revision sections) | `work/reports/TASK-145-test.md` |
| TASK-146 | PASS (r1; r2 final in the revision section) | `work/reports/TASK-146-test.md` |
| TASK-151 | PASS | `work/reports/TASK-151-test.md` |
| TASK-152 | PASS (round 2, on TASK-147 revision 2) | `work/reports/TASK-152-test.md` |
| TASK-153 | PASS | `work/reports/TASK-153-test.md` |
| TASK-161 | PASS | `work/reports/TASK-161-test.md` |
| TASK-147 (revision only) | PASS | `work/reports/TASK-147-test.md` (revision section) |
| TASK-148 (revision only) | PASS | `work/reports/TASK-148-test.md` (revision section) |

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

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost with the user's machine). REQ-152, REQ-153, REQ-154, REQ-155, REQ-180. Spec: SR §2.1–§2.4, §3.3, §3.5, §4, §4.1; answers #2, #13, #16, #17, #105 (e), (g), #109, #110. Checks CHK-M7-065 to -077 and mutation rows CHK-M7-326, -348 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_validate.py`. Implementation: `manager/bitscan_manager/services/importer/validate.py` (impl report `work/reports/TASK-144-impl.md`).

C = Linux cloud container, Ubuntu 24.04.5, 4 cores, CPython 3.12.3, venv `manager/.venv` (pytest 9.1.1, xdist 3.8.0, hypothesis 6.170.2, google-re2 1.1.20251105, defusedxml 0.7.1), `CI=true`. PostgreSQL is not needed for this task: it is unit-only, and no check here uses it. Plants in the scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/mut` (manager, bits, docs), imported first through `PYTHONPATH`, with a 2251/2251 control run; product files in the main checkout never edited.

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit_validate.py` | 687/687 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final, with the added test) | C | same | 689/689 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit_fixtures.py tests/test_bit_fuzz.py` | 231/231 passed, 0 skipped |
| importer unit neighbours | C | `pytest -q tests/test_bit_parse.py tests/test_bit_structure.py tests/test_bit_values.py tests/test_bit_model.py` | 744/744 passed, 0 skipped |
| load | C | full manager suite, `pytest -n 8` on 4 cores, 3 times (PostgreSQL tests not run: no Docker image, see TASK-145 report) | 8143/8143, 8145/8145, 8147/8147 passed, 0 failed |
| static | C | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` (repo root) | clean; 276 files formatted; mypy: no issues in 276 source files |

#### Test added (tester-owned; does not weaken anything)

`test_missing_element_at_the_plugin_line_sorts_before_later_lines[Operator-BIT010, ExpectedResult-BIT011]` (REQ-155 (5)). Plant `V-unsorted` (findings not sorted by line) **survived** the 687 tests as found. Sorting only matters when a missing `Operator`/`ExpectedResult` (reported at the `<Plugin>` line, #2) follows a finding at a later line of the same plugin. No fixture or test built that case. The new test expects exactly `[(BIT010|BIT011, Plugin line), (BIT101, PluginName line), (BIT004, PluginId line)]`, and the plant is now red (2 failed).

#### Acceptance criteria (tasks.md TASK-144)

| Criterion | Check | Result |
| --- | --- | --- |
| One fixture per code gets exactly that code with its line and path | CHK-M7-065 | PASS: 90 content and valid fixtures; code set, first-finding line and element path equal the manifest for BIT003, 004, 005, 008, 010–014, 016, 017, 101, 102, 103 |
| SR §1.1 example: no finding, and a `Candidate` equal to the expected normalised values | CHK-M7-066 | PASS: name and line 3, description, `enabled`, family, `1.0`, uuid, line 13, plugin name, `control_ref` `1.3.1.1`, Execute exactly the SR text and its SHA-256, `equals`, `install ok installed`, 30 s; `RuleKeys` with `RuleId(uuid, 13, 1)` |
| REQ-152 (1) bound table | CHK-M7-067 | PASS: each length at its limit accepted and +1 refused (BIT017 with its path; BIT008 for `Execute` at 16,384/16,385), counted in characters with `é` (bytes ≠ characters); trimmed first (#17), U+00A0 not trimmed; whitespace-only names and `Execute` count as empty; descriptions may be empty |
| Enums | CHK-M7-068 | PASS: `ENABLED`, `Disabled` and ` disabled\n` stored lowercase; `on`, empty, fullwidth, `enabled ` (inner), `disabled;` → BIT003 at line 5; `EQUALS` → `equals`; `equal`, `==`, fullwidth → BIT010 at line 17; all 14 operators accepted |
| BIT004 / BIT005 | CHK-M7-069 | PASS: uppercase, braces, `urn:uuid:`, 32-hex, short, empty → BIT004 at line 13 with no `RuleId`; padded id trimmed; a third use of an id gives BIT005 on the 2nd and 3rd uses at their `PluginId` lines; `RuleKeys` holds the first use only |
| Timeout table (REQ-152 (5)) | CHK-M7-070 | PASS: `1`, `600`, `0600`, `00001`, 4,001-digit zero-padded `7` accepted; absent → 60; `0`, `601`, `30s`, `1.5`, `-1`, `+5`, ` 30`, `30 `, empty, Arabic-Indic, fullwidth, `0x1e`, `1e2`, `6000`, `00`, 5,000 nines, `1_0` → BIT017 at `Execute/@timeout` |
| 5,000 plugins pass, 5,001 BIT017 | CHK-M7-071 | PASS: 5,000 → candidate with 5,000 plugins and ids; 5,001 → BIT017 at `Policy/PluginsGroups` (pipeline stops it in the parser; `validate`'s own rule on a built `ParsedPolicy`) |
| Missing `Operator` / `ExpectedResult` (#2) | CHK-M7-072 | PASS: BIT010 for `Plugin[2]/Operator` at the plugin line plus the file's BIT003; BIT011 at line 10; a missing `Operator` gives no BIT014 |
| BIT012 / BIT013 / BIT014 | CHK-M7-073 | PASS: 11 non-numbers × 6 numeric operators → BIT012; 6 numbers pass; 6 non-RE2 patterns × `regex` and `not_regex` → BIT013 (RE2 helper, never `re`); a valid RE2 pattern passes; BIT014 in both directions (9 rows) |
| A file with three faults gets all three in line order and no `Candidate` | CHK-M7-074 | PASS: `three-faults.bit` → BIT003, BIT004, BIT012 at 6, 14, 25; every fixture sorted by line; same-line rule order kept; new missing-element ordering test |
| Warnings have Warn severity and never reject | CHK-M7-075 | PASS: warnings-only file has a candidate, BIT101 and BIT103 both `Severity.WARN`, `rejects` false; listed next to an error |
| Messages (#105 (g)) | CHK-M7-076 | PASS: ≤ 64 characters of value, a 16,384-char value never whole, control characters escaped; exactly the four JSON keys for every fixture |
| No retired code | CHK-M7-077 | PASS: across every fixture |
| `RuleKeys` always built; `Candidate` only without Reject | CHK-M7-066, -074 | PASS: rule keys built on a rejected file, `policy_name` None when it fails BIT017; `Validated` frozen; input not mutated |
| No `import re` | CHK-M7-348 | PASS: AST test and ruff TID251 |

CHK-M7-334 (BIT001/BIT002 failure still runs the content rules) is shared with TASK-143: `validate()` only accepts a `ParsedPolicy`, so TASK-144 has no code path to plant. The stop is in `structure.check` (TASK-143, its plant red there) and in `import_one` (TASK-154). **NOT RUN here** for that reason.

#### Plants (scratch copy; each anchor asserted to occur once, file restored after)

Tests run per plant: `tests/test_bit_validate.py tests/test_bit_fixtures.py` (916 tests), `-n 4`.

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-326 | BIT013 only for `regex` (skipped for `not_regex`) | red, 8 failed |
| CHK-M7-348 (G1) | `import re` in `validate.py` | red: `ruff check` TID251 "`re` is banned" (still red with `# noqa: F401`) |
| CHK-M7-348 (AST) | same, ruff silenced with `# noqa: F401, TID251` | red, 1 failed (`test_validate_module_imports_no_re`) |
| V-len-off1 | length limit +1 | red, 14 |
| V-len-bytes | length counted in UTF-8 bytes | red, 12 |
| V-notrim | values not trimmed before the length check | red, 20 |
| V-bit003-case | `PolicyStatus` case-sensitive | red, 5 |
| V-bit003-off | BIT003 removed | red, 19 |
| V-bit004-off | UUID form not checked | red, 32 |
| V-bit005-off | duplicate ids allowed | red, 2 |
| V-bit008-empty | empty `Execute` allowed | red, 5 |
| V-bit008-max | `Execute` limit 16,385 | red, 2 |
| V-timeout-max | timeout up to 6,000 | red, 2 |
| V-timeout-min0 | timeout 0 allowed | red, 7 |
| V-timeout-trim | `@timeout` trimmed | red, 3 |
| V-timeout-default | absent timeout → 30 | red, 1 |
| V-bit010-case | `Operator` case-sensitive | red, 4 |
| V-bit010-missing | missing `Operator` not reported | red, 5 |
| V-bit011-missing | missing `ExpectedResult` not reported | red, 3 |
| V-bit012-off | BIT012 removed | red, 74 |
| V-bit013-off | BIT013 removed | red, 16 |
| V-bit014-oneway | BIT014 only for empty/not_empty with a value | red, 6 |
| V-5001 | plugin cap 5,001 | red, 1 |
| V-unsorted | findings not sorted by line | red, 2 (survived before the added test) |
| V-first-only | only the first finding kept | red, 12 |
| V-bit101-off | BIT101 never raised | red, 12 |
| V-bit103-off | BIT103 never raised | red, 4 |
| V-candidate-on-reject | `Candidate` built despite a Reject | red, 15 |
| V-exec-untrimmed | `Execute` stored and hashed untrimmed | red, 6 |
| V-msg-unquoted | values put in messages raw (no `quote`) | red, 2 |
| V-rulekeys-dup | duplicate id kept in `RuleKeys` | red, 1 |
| V-rulekeys-name | invalid `PolicyName` kept in `RuleKeys` | red, 1 |

**32/32 red** (one after the added test).

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-065 | CODE | C | `pytest -q tests/test_bit_validate.py -k "fixture_codes or every_content_code"` | PASS | 90 fixtures match the manifest | 2026-10-27 |
| CHK-M7-066 | CODE | C | `pytest -q tests/test_bit_validate.py -k "sr_example or format_version or nbsp"` | PASS | no finding; candidate fields and `RuleId` exact | 2026-10-27 |
| CHK-M7-067 | CODE | C | `pytest -q tests/test_bit_validate.py -k "length or trimmed or whitespace or execute_bound"` | PASS | 6 bounds at/over in characters; BIT008 at 16,385 | 2026-10-27 |
| CHK-M7-068 | CODE | C | `pytest -q tests/test_bit_validate.py -k "policy_status or operator"` | PASS | lowercase storage; BIT003 line 5, BIT010 line 17 | 2026-10-27 |
| CHK-M7-069 | CODE | C | `pytest -q tests/test_bit_validate.py -k "plugin_id or duplicate"` | PASS | 7 BIT004 forms; BIT005 on each later use | 2026-10-27 |
| CHK-M7-070 | CODE | C | `pytest -q tests/test_bit_validate.py -k timeout` | PASS | 7 accepted, 18 refused, absent 60 | 2026-10-27 |
| CHK-M7-071 | CODE | C | `pytest -q tests/test_bit_validate.py -k "5000 or 5001"` | PASS | 5,000 pass; 5,001 BIT017 | 2026-10-27 |
| CHK-M7-072 | CODE | C | `pytest -q tests/test_bit_validate.py -k missing` | PASS | BIT010/BIT011 at the plugin line | 2026-10-27 |
| CHK-M7-073 | CODE | C | `pytest -q tests/test_bit_validate.py -k "numeric or regex or re2 or bit014"` | PASS | 66 + 36 + 12 + 2 + 9 rows | 2026-10-27 |
| CHK-M7-074 | CODE | C | `pytest -q tests/test_bit_validate.py -k "faults or sorted or rule_order or plugin_line"` | PASS | 3 faults in line order; new ordering test | 2026-10-27 |
| CHK-M7-075 | CODE | C | `pytest -q tests/test_bit_validate.py -k "warning or control_ref"` | PASS | Warn severity, never rejects | 2026-10-27 |
| CHK-M7-076 | CODE | C | `pytest -q tests/test_bit_validate.py -k "messages or control_characters or long_execute or four_keys"` | PASS | ≤ 64 chars, escaped, four keys | 2026-10-27 |
| CHK-M7-077 | CODE | C | `pytest -q tests/test_bit_validate.py -k retired` | PASS | no retired code in any fixture | 2026-10-27 |
| CHK-M7-334 | CODE | — | — | NOT RUN | no TASK-144 code path: `validate()` takes only a `ParsedPolicy`; the stop is planted at TASK-143 (red) and at TASK-154 | 2026-10-27 |
| CHK-M7-326 | CODE | C | plant: BIT013 skipped for `not_regex` | PASS (red) | 8 failed | 2026-10-27 |
| CHK-M7-348 | CODE | C | plant: `import re` in `validate.py`; `ruff check` | PASS (red) | TID251; AST test 1 failed with ruff silenced | 2026-10-27 |
| CHK-M7-144-extra | CODE | C | 30 further plants (table above) | PASS (red) | 30/30 red | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 689/689 passed, 0 failed, 0 errors, 0 skipped. Plants: 32/32 red.

### TASK-145

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost). REQ-156; #108 (c), (h), (j). Spec: SR §4.2 (SR L277, L285, L287); POSIX XCU §2.3, §2.6.3, §2.7, §2.10; design note D2 and `work/plans/TASK-145.md` §5. Checks CHK-M7-100 to -102 and -112; mutation rows CHK-M7-332 (lexer half) and -387. Test file: `manager/tests/test_bit102_lexer.py`. Implementation: `shlex_model.py`, `shlex_grammar.py`, `shlex_posix.py` under `manager/bitscan_manager/services/importer/` (impl report `work/reports/TASK-145-impl.md`).

C is as in `work/reports/TASK-144-test.md` (Ubuntu 24.04.5 container, 4 cores, CPython 3.12.3, `manager/.venv`, `CI=true`). Unit-only; no PostgreSQL needed. Plants are in the same scratch copy, imported first through `PYTHONPATH`.

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit102_lexer.py` | 173/173 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final) | C | same | 175/175 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit102.py` (BIT102 runs on the lexer) | 1177/1177 passed |
| load | C | full manager suite `pytest -n 8` on 4 cores, 3 times | 8143/8143, 8145/8145, 8147/8147 passed, 0 failed |
| load + 12 CPU burners | C | `pytest -n 8 tests/test_bit_parse.py tests/test_bit102_lexer.py tests/test_bit102.py tests/test_bit_validate.py`, 3 rounds | 2317/2317 passed each round |
| static | C | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean; 276 files |

The load runs used no `CI=true`. With `CI=true` the PostgreSQL fixtures error, because the Docker image build cannot reach the Debian apt hosts (`docker.errors.BuildError` on `apt-get install postgresql-16-debversion`): 6491 passed, 1652 errors, all of them PostgreSQL setup. None of this task's tests use PostgreSQL.

#### Test added (tester-owned)

`test_param_and_arith_count_toward_depth_8[param, arith]` (REQ-156 "nesting deeper than 8"). As built, `${…}` and `$((…))` count toward `MAX_DEPTH` like `$( )` (impl report, accepted by the lead), so no form nests without a bound. Plant `L-scan-depth` (that count removed) **survived** the 173 tests as found. The new test checks that 7 wrappers plus a `$( )` lex with `rm` found, and that 8 wrappers plus the `$( )` raise. It also checks 8 plain wrappers pass and 9 raise. The plant is now red (2 failed).

#### Acceptance criteria (tasks.md TASK-145, REQ-156)

| Criterion | Check | Result |
| --- | --- | --- |
| A table of at least 60 inputs gives the expected tokens | CHK-M7-100 | PASS: 85-row table (command words and nested scripts at each depth), plus quoting (`echo "rm -rf /"` one `dq` argument; `r''m`, `\rm`, `"r"m` → `rm`), word boundaries, assignments, 15 redirection rows (fd, op, target), the SR §1.1 command, quoted here-document body as data and unquoted body scanned, CRLF `\r` literal, line counts, `for`/`case`/function names as data words, reserved words only in command position |
| Unterminated quotes or substitutions and 9-deep nesting raise the fail-closed error | CHK-M7-101 | PASS: 34 fail-closed inputs (incl. `'`, `"`, `$(`, backtick, `${`, here-document, `)`, `fi`, `if x; then y`, `; rm`, NUL, `$((1)`) raise `ShellSyntaxError` with a line and quote no input; 8 nested `$(`, `<(`, `>(`, backticks accepted, 9 refused; mixed nesting; `depth=` argument; new param/arith depth test |
| Random strings up to 16,384 characters raise nothing else, within 100 ms each | CHK-M7-112 | PASS: 3,000 shell-soup and 1,000 random-text Hypothesis examples, 60 inputs repeated to 16,384 chars, 10 pathological 16,384-char inputs; each under 100 ms of thread CPU time (best of 5 only when the first try is over) |
| The module imports nothing that executes | CHK-M7-102 | PASS: AST of all three files: no `subprocess`, `os`, `shlex`, `re`, `regex`, `pty`, `ctypes`, `multiprocessing`, `importlib`, `runpy`, `code`, `socket`; no `eval`/`exec`/`compile`/`__import__`/`open` calls; no `system`/`popen`/`exec*`/`spawn`; `test_lexer_runs_nothing` with those patched to raise |

#### Plants (scratch copy; tests run: `tests/test_bit102_lexer.py tests/test_bit102.py`, 1352 tests, `-n 4`)

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-332 (lexer half) | `lex` returns an empty `Script` on `ShellSyntaxError` and on NUL (fail open) | red, 58 failed (TASK-146's corpus included, as the plan requires) |
| CHK-M7-387 | `$( )`, `<( )`, `>( )` keep no nested script | red, 192 |
| L-backtick | backticks keep no nested script | red, 35 |
| L-heredoc-unscanned | unquoted here-document bodies not scanned | red, 34 |
| L-heredoc-quoted-scanned | quoted bodies scanned as code (over-detection) | red, 6 |
| L-maxdepth9 | `MAX_DEPTH` 9 | red, 10 |
| L-scan-depth | `${…}`/`$((…))` not counted toward depth | red, 2 (survived before the added test) |
| L-scan-noscripts | `${…}`/`$((…))` drop their substitutions' scripts | red, 32 |
| L-sq-unterminated | an unterminated `'` runs to the end | red, 4 |
| L-dq-unterminated | an unterminated `"` accepted | red, 3 |
| L-reserved-anywhere | reserved words recognised outside command position | red, 1 |
| L-forlist-dropped | `for`/`case` list words dropped (substitutions hidden) | red, 6 |
| L-escape-lit | `\x` kept as a literal part (so `\if` is a keyword) | red, 1 |
| L-lines | line numbers off by one | red, 2 |
| L-unbalanced-paren | a stray `)` ignored | red, 3 |
| L-assign-not-kept | assignments treated as command words | red, 11 |
| L-quadratic | `line()` rescans the source in Python per token (super-linear) | red, 8 (best of 5 ≈ 1.95 s against 100 ms). A first form using C-speed `str.count` stayed under the bound; it is not a realistic regression, so the plant was made genuinely super-linear |

**17/17 red** (one after the added test).

#### Load-sensitive time bounds (main's known item)

In the user's full `pytest -n 8` run, `test_bit_parse.py::test_35015_elements_is_bit002_bounded` (TASK-141) and `test_bit102_lexer.py::test_pathological_inputs_bounded[seps]` each failed once, and passed alone.

Measurements (C, 4 cores):

| Test | Bound and measure | Idle | 3× oversubscribed (12 burners on 4 cores) |
| --- | --- | --- | --- |
| `test_35015_elements_is_bit002_bounded` | 2.0 s, **wall clock** (`perf_counter`), tracemalloc on | 0.20–0.26 s (15 samples) | 0.20–**1.50 s** (15 samples) |
| `test_pathological_inputs_bounded[seps]` | 100 ms, thread CPU time, best of 5 when the first try is over | 39–56 ms (30 samples) | 39–63 ms (30 samples, 0 over 100 ms) |

Repeated runs: neither test failed in 3 full-suite `-n 8` runs, nor in 3 rounds of the four importer test files under `-n 8` with 12 burners.

Diagnosis:
- **The parse bound is load-sensitive.** It measures wall time, so time spent waiting for a core counts. Under 3× oversubscription one run took 1.5 s, 7.5× its idle time. On a slower machine shared with other agents, more than 2 s is plausible, which explains the failure.
- **The lexer bound is not scheduler-sensitive.** It measures the thread's CPU time and takes the best of 5. Here it never exceeded 63 ms, even single-shot under load. The bound is the REQ-156 (4) acceptance figure (100 ms), so I did not raise it.
- The margin on `seps` is still about 2× (impl report: 52 ms worst on the user's Windows box). The one failure there was likely CPU contention: an SMT sibling or frequency drop lowers per-thread throughput, which CPU time does not hide.

Changes (tester-owned test files; nothing weakened):
1. `manager/tests/test_bit_parse.py` `_measure` (TASK-141's test): the elapsed time is now `time.thread_time()` (this thread's CPU time) instead of `time.perf_counter()`, with the same 2.0 s bound and the same tracemalloc peak. It applies to every `_measure` user (bombs, 5 MiB file, 5 MiB element, 35,015 elements).
   - The parser is single-threaded, so expat and the collector are all counted; only waiting for a core is not.
   - Proof it still catches a slow parser: plant `P-quadratic-collector` (per start tag, Python work proportional to the elements seen so far) is red, `test_35015_elements_is_bit002_bounded` 1 failed.
2. `manager/tests/test_bit102_lexer.py` `_bounded`: diagnostics only. The assertion now reports the five measured times in ms. The bound, the measure and the best-of-5 rule are unchanged. Plant `L-quadratic` is still red.

Recommendation: keep both bounds as they now are. If `seps` fails again on the user's machine, the message now gives the five times. If they are all just over 100 ms with no super-linear growth, the fix is a decision on the REQ-156 (4) figure for loaded developer machines, which is for main and the user. It is not a test change: retrying until green is not allowed. Note for TASK-141: its report should cite this change to `_measure`.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "table or command_words or quoted or escaped or boundaries or assignments or redirections or digits or sr_example or heredoc or crlf or lines or function or reserved"` | PASS | 85-row table and the plan §5 row 1 shapes | 2026-10-27 |
| CHK-M7-101 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "fail_closed or unlexable or depth or nested or mixed"` | PASS | 34 inputs raise with a line; 8 accepted, 9 refused for `$(`, `<(`, `>(`, backticks, `${`, `$((` | 2026-10-27 |
| CHK-M7-102 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "imports_nothing or runs_nothing"` | PASS | AST clean in 3 files | 2026-10-27 |
| CHK-M7-112 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "random or long_inputs or pathological"` | PASS | 4,060 generated + 10 pathological inputs, each < 100 ms CPU | 2026-10-27 |
| CHK-M7-332 | CODE | C | plant: lexer errors swallowed (empty `Script`) | PASS (red) | 58 failed incl. the TASK-146 corpus | 2026-10-27 |
| CHK-M7-387 | CODE | C | plant: `$( )` recursion dropped | PASS (red) | 192 failed | 2026-10-27 |
| CHK-M7-145-extra | CODE | C | 15 further plants (table above) | PASS (red) | 15/15 red | 2026-10-27 |
| CHK-M7-112-load | CODE | C | 3 × full suite `-n 8`; 3 × importer files `-n 8` + 12 burners | PASS | both named tests green every time; measurements above | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 175/175 passed, 0 failed, 0 errors, 0 skipped. Plants: 17/17 red. Changed: `test_bit102_lexer.py` (added test; bound message) and `test_bit_parse.py` (`_measure` uses CPU time).

---

### TASK-145 TEST (revision 1 and 1b): PASS

Tester: tester-m7d, 2026-10-27. Code under test: `0529083` (r1 at `8173527`, plus r1b, which makes the function-definition removal linear). Impl report: `work/reports/TASK-145-impl.md` "Revision 1" and "Revision 1b". Review being answered: `work/reviews/TASK-145.md` findings 1 (blocking), 2 (should-fix) and 3 (nit). Spec: SR §4.2 L277 and L287; TS §3.3 L249 (`/bin/sh -c` is dash); POSIX XCU §2.7.4; REQ-156 (4).

Environment C: cloud container, Ubuntu 24.04, 4 cores, `manager/.venv`, dash 0.5.12-6ubuntu5, bash 5.2.21. Unit-only; no PostgreSQL. Plants were made in the scratch copy `scratchpad/mut`, which was refreshed from the working tree. A control run first proved that the copy is the code imported: a marker planted in the copy raised on import through `PYTHONPATH`.

#### Runs

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| as found (r1, before my rows) | `pytest -q -p no:cacheprovider -n 4` on the six files | 2548/2548 passed |
| r1 + my rows | `pytest -q tests/test_bit102_lexer.py -k pathological` | 10/14 passed, **4 failed** (`fndefs*`, see the finding below) |
| re-run, failing rows only, after r1b | the 4 node ids `test_pathological_inputs_bounded[fndefs]`, `[fndefs-nl]`, `[fndefs-true]` and `[fndefs-hypothesis]` | 4/4 passed |
| final (`0529083`) | `pytest -q -p no:cacheprovider tests/test_bit102_lexer.py` | 230/230 passed, 0 failed, 0 errors, 0 skipped |
| final, six files, 3 runs | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` | 2981/2981 passed, 3 times |
| static (repo root) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 278 files |

#### Finding (product, fixed in r1b): the lexer was quadratic on function definitions (REQ-156 (4))

- **How it was found.** Hypothesis found it in `test_long_inputs_up_to_16384_chars`, with `unit='{{\nrm()'` repeated to 16 KB. The example was stored in the scratch copy's `.hypothesis` database, and from then on the test failed every run there.
- **Cause.** `cmds.remove(cur)` in the `NAME ( )` branch of `shlex_grammar.py` ran the dataclass `__eq__` against every earlier command. cProfile: 2.74 M `__eq__` calls, 0.58 s of 0.68 s.
- **Timings before the fix**, `lex()`, best-of-3 thread CPU time, at 4 K / 8 K / 16 K chars:
  - `x;f(){ :;};`: 53 / 200 / **774 ms**;
  - `a\nf()\n:\n`: 37 / 134 / 533 ms;
  - `true\nf() { :; }\n`: 13 / 41 / 140 ms;
  - `{{\nrm()`: 24 / 87 / 326 ms.

  `150bcd3` timed the same, so this predates r1. The r0 PASS was a test gap: no fixed input had many function definitions.
- **After r1b**, `cmds.pop()` behind an identity check that raises (fail closed): 34 ms and 26 ms at 16 K for the first and last forms.
- **Pins.** Four fixed rows were added to `test_pathological_inputs_bounded`. They make the bound deterministic, without relying on Hypothesis finding the input again.

#### Tests added (tester-owned; nothing weakened)

- `bits/tests/bit102/must_reject.json` gets 38 TASK-145 rows, `rule` starting `145r1`:
  - the 10 review here-document forms, each with `rm -rf /x` and with `rm x`;
  - two levels (`$(echo $(⏎…))`), a backtick inside `$( )`, two here-documents, `<<-`, and a flock `-c` script;
  - a substitution on the here-document line with no newline inside it;
  - `coproc rm x` and 9 `bash -c 'coproc …'` forms;
  - the nit `>/etc/x f() { :; }`, and `f() { :; } >/etc/x; f`.
- `must_pass.json` gets the 6 forms the shells read normally: `cat <<E $(date)` (the old false positive), `x=$(cat <<E⏎body⏎E⏎)`, `cat <<E⏎$(⏎date⏎)⏎E`, backticks in a body, `( cat <<E )`, and a quoted body inside `{ }`. It also gets `bash -c 'coproc cat /etc/x'`, `coproc NAME { … }` and `f() { cat /x; }; f`.
- `manager/tests/test_bit102_lexer.py`:
  - `test_heredoc_pending_across_a_substitution_newline_fails_closed` (13), which asserts the exact reason;
  - `test_heredoc_forms_the_shells_read_normally` (7);
  - `test_coproc_command_words` (10) and `test_coproc_name_is_a_data_word_and_assignment_kept`;
  - `test_redirection_before_a_function_definition_fails_closed`;
  - the 4 `fndefs` rows in `test_pathological_inputs_bounded`;
  - `test_time_keyword_or_command` (6) and `test_prompt_and_escape_transforms_fail_closed` / `test_quoted_or_other_transforms_lex`, which are for TASK-146 r2 but live in the lexer file.

#### Real-shell confirmation (scratch `sh146/shellprobe.py`; `rm` replaced by `echo RAN`, run in a fresh temp dir under the scratchpad)

| Rows | Result |
| --- | --- |
| Here-document forms (`$( )`, `<<E`, `"$( )"`, `; echo $( )`, `${x:-$( )}`, backticks, two levels, backtick in `$( )`, two here-documents, `<<-`, flock `-c`) | dash runs the inner line (prints RAN, then `E: not found`) in every form |
| `<( )`, `>( )` | bash runs it; dash has no process substitution |
| `$(($( ⏎…)))` | dash runs it; RAN shown on stderr (stdout is used up by the arithmetic) |
| `x=$(cat <<'E' $(⏎…⏎E⏎)⏎)` | dash and bash give a syntax error and nothing runs; the refusal is fail closed |
| coproc: 9 `bash -c` forms, and `coproc rm x` under bash | bash runs the command (RAN on stderr). dash has no coproc keyword, so the top-level row is over-detection, which is allowed |
| `>/etc/x f() { :; }` | dash: `Syntax error: "(" unexpected`; nothing runs |
| `f() { :; } >FILE; f` | dash creates FILE |

#### Plants (scratch copy; tests `tests/test_bit102.py tests/test_bit102_lexer.py`, `-n 4`)

| Plant | Change | Result |
| --- | --- | --- |
| L1-heredoc-depth | the depth test removed from the newline check (`if self.outer:`) | red, 34 |
| L1-backtick-outer | backticks no longer get `outer=` | red, 6 |
| L1-coproc-reserved | `coproc` not reserved | red, 21 |
| L1-coproc-name-dropped | `coproc NAME` not kept as a data word | red, 1 |
| L1-fn-redirect-dropped | the raise for a redirection before `NAME ( )` removed | red, 2 |
| L1-close-paren-any-pending | the r0 `)` rule (any pending here-document) | red, 4 (incl. must-pass `cat <<E $(date)`) |
| L1b-fndef-remove-by-eq | `cmds.remove(cur)` back (quadratic) | red, 5 (the 4 `fndefs` rows and `test_long_inputs`) |

**7/7 red.**
- The grammar plants were re-run on `0529083`.
- The two shlex_posix plants were run on `8173527`; r1b does not touch that file.
- In the first plant pass, `test_long_inputs_up_to_16384_chars` also failed, because of the stored quadratic example described above. Every plant also had a red test of its own, and the counts above leave that extra failure out.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "heredoc_forms or coproc or time_keyword or transforms_lex"` | PASS | 7 + 11 + 6 + 5 rows | 2026-10-27 |
| CHK-M7-101 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "across_a_substitution or redirection_before or transforms_fail_closed"` | PASS | 13 + 1 + 8 raise the fail-closed error | 2026-10-27 |
| CHK-M7-112 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "pathological or long_inputs or random"` | PASS after r1b (FAIL at r1) | 4 `fndefs` rows: 774/533/140/326 ms → < 50 ms | 2026-10-27 |
| CHK-M7-115 (145 rows) | CODE | C | `pytest -q tests/test_bit102.py -k must_reject` | PASS | 38 rows `145r1`, each with its token; real-shell: dash/bash run each hidden command (table above) | 2026-10-27 |
| CHK-M7-145-r1-plants | CODE | C | `python plant2.py plants_r2_grammar.json` and the full `plants_r2.json` | PASS (red) | 7/7 | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 278 files | 2026-10-27 |

Verdict: **PASS** (r1b). 230/230 passed in the lexer file; 2981/2981 passed across the six files, 3 times; 0 failed, 0 errors, 0 skipped. Plants: 7/7 red. Revision 1 alone was **FAIL** on REQ-156 (4); r1b fixes it.

### TASK-146

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost). REQ-157, REQ-177, REQ-180; #108 (a)–(k). Spec: SR §4.2 (SR L277–L287), §4.1 BIT102, §1.1; TS §3.7, §8.1. Rulings tested as written:
- User, 2026-10-27: a non-literal command word passes, and only its nested scripts are checked.
- Lead, 2026-10-27: apt, apt-get and systemctl verbs are refused anywhere among the literal arguments; `<>` is an output redirection; `env -S` is lexed.
- The `stdbuf -io L` dispute is closed (`work/status.md`: the builder was right). The test uses `stdbuf -i0 -oL rm x`.

Checks CHK-M7-115 to -121; mutation rows CHK-M7-327 to -332. Test file: `manager/tests/test_bit102.py`. Corpora: `bits/tests/bit102/must_reject.json` (149) and `must_pass.json` (96). Implementation: `manager/bitscan_manager/services/importer/bit102.py` (impl report `work/reports/TASK-146-impl.md`, revision 1).

C is as in `work/reports/TASK-144-test.md`. Unit-only; no PostgreSQL needed. Plants are in the same scratch copy.

#### Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit102.py` | 1160/1160 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final, with added tests) | C | same | 1177/1177 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit_validate.py` (runs `check_execute` on every fixture); `tests/test_bit_fixtures.py tests/test_bit_fuzz.py` | 689/689; 231/231 passed |
| load | C | full suite `pytest -n 8`, 3 times | 8143/8143, 8145/8145, 8147/8147 passed |
| static | C | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean; 276 files |

#### Tests added (tester-owned; 17 cases, nothing weakened)

- `test_wrapper_long_option_values_do_not_hide_the_command` (13). #108 (d) says "skipping its options". A long option with its value as the next word must not hide the command: `sudo --user root rm x`, `sudo --group adm`, `env --unset HOME`, `env --chdir /`, `nice --adjustment 5`, `ionice --class 3`, `stdbuf --output L`, `timeout --signal KILL 5`, `timeout --kill-after 1 5`, `chroot --userspec a:b /`, and `env --split-string 'rm x'`, `env -iS 'rm x'`, `env -iS'rm x'`.
  - Plant `B-long-opt-value` (a long option's separate value not skipped) **survived** the 1160 tests as found. That is a #108 (d) bypass (`root` would be taken as the command, hiding `rm`).
  - Now red (10 failed). The `-iS` rows also make the new plant `B-envS-cluster` red.
- `test_sed_in_place_abbreviations` (4): `sed --in`, `--in-pl`, `--in-pl=.bak`, `-n --i`. SR §4.2 refuses `--in-place`, and GNU getopt accepts any unique prefix of it. Plant `B-sed-long-abbrev` (only the full `--in-place` matched) **survived**; it is now red (4 failed).

The code already handled every added case (the impl report's r1 probes list them). The gap was in the tests only. No product bug.

#### Acceptance criteria (tasks.md TASK-146)

| Criterion | Check | Result |
| --- | --- | --- |
| Every must-reject case gets BIT102 with the offending token in its message | CHK-M7-115 | PASS: 149/149, each finding BIT102, Reject, at the caller's line and element, and the corpus token in a message |
| Every simple command anywhere (pipelines, lists, subshells, substitutions, `-c` scripts) | CHK-M7-116 | PASS: 24 corpus cases × 27 contexts = 646 rows: `|`, `;`, `&&`, `||`, `&`, `( )`, `{ ; }`, `if`, `while`, `until`, `for`, `case`, function, `$( )`, backticks, `<( )`, `>( )`, `!`, assignment, `"$( )"`, `${x:-$( )}`, here-document, `bash -c`, `sh -c`, `dash -c`, `sudo`, `env`. Plus 10 substitutions in data words and input-redirection targets |
| #108 matching (paths, `mkfs.*`, wrappers, assignments) | CHK-M7-117 | PASS: 66 forms (`/bin/rm`, `../../bin/rm`, `mkfs.ext4`, 13 wrappers with options, `FOO=1 rm`, `sed` clusters and `--in-place`, apt and systemctl verbs after option values, `dpkg --purge=x`); 11 short-cluster rows (r1 fix, incl. `stdbuf -i0 -oL rm x`); 13 + 4 added rows |
| Redirections | CHK-M7-118 | PASS: 25 refused (incl. `/tmp/../etc/x`, `"$F"`, `$HOME/x`, `/tmpx`, `/tmp`, `&>`, `>&`, `<>`, `/dev/sda`, `/tmp/$(id -u)`); 18 pass (`/dev/null`, `/dev/stdout`, `/dev/stderr`, `/tmp/…`, `2>&1`, `>&2`, `>&-`, input forms, `<>/tmp/x`) |
| Code-running forms | CHK-M7-119 | PASS: 36 rows: `.`, `source`, `eval`, `exec`, `xargs`, the 4 `find` actions, shells without `-c` (file, `-s`, stdin, `<`), `-c` with `$( )`, backticks, `<( )`, `${…$( )}`, here-document substitution, `-c` scripts checked (also through `-o pipefail`, `-ec`, `--`, nested `sh -c`), `env -S` forms, `sudo sh -c`, `busybox sh -c` |
| No case of the must-pass corpus (the SR §1.1 `Execute` included) gets BIT102 | CHK-M7-120 | PASS: 96/96 corpus (first entry = the SR §1.1 `Execute`, extracted from the spec); all 32 `Execute`s in `bits/samples/` read through the real parser; 47 ruled and read-only forms (the lead's false-positive guards, the user's 6 non-literal forms, `command -v`/`-V`, here-document with a quoted delimiter, `sed -ei`, `sed -- -i`) |
| Unlexable `Execute` is BIT102 (fail closed) | CHK-M7-121 | PASS: 13 unlexable inputs give exactly one "cannot be checked" BIT102; 10 nested `sh -c` levels fail closed |
| Messages | — | PASS: the token as written (`r''m`, `"rm" (via "sudo")`); a 16,000-char target never whole, under 300 chars; `\x01` escaped; one finding per distinct offence, in order; 3,000-example fuzz never raises, each under 1 s CPU |

Accepted residual risk (user decision 2026-10-27, `work/decisions.md`): `c=rm; "$c" -rf /` passes BIT102 and is tested as must-pass. The runner sandbox (TS §3.7, M10) is the control. This report notes it, as the decision asks.

#### Plants (scratch copy; tests run: `tests/test_bit102.py tests/test_bit_validate.py`, 1866 tests, `-n 4`)

Security rows (tasks.md mutation table):

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-327 | substring search over `Execute` for the listed words instead of the lexer | red, 473 failed (incl. `test_not_a_substring_search`: `echo "rm"` rejected, `r''m` accepted) |
| CHK-M7-328 | path-qualified names not reduced (`name = value`) | red, 14 |
| CHK-M7-329 (a) | nested scripts (`$( )`, backticks, `<( )`, here-documents) not walked (`_nested` empty) | red, 188 |
| CHK-M7-329 (b) | `-c` scripts not checked | red, 88 |
| CHK-M7-329 (c) | data words (`for` lists, `case` words) not walked | red, 5 |
| CHK-M7-329 (d) | redirect-target substitutions not walked | red, 5 |
| CHK-M7-330 (a) | `WRAPPERS` empty | red, 127 |
| CHK-M7-330 (b) | `busybox` dropped from `WRAPPERS` | red, 3 |
| CHK-M7-331 (a) | any redirect target accepted | red, 69 |
| CHK-M7-331 (b) | `..` component allowed under `/tmp/` | red, 3 |
| CHK-M7-331 (c) | non-literal target (`"$F"`) accepted | red, 7 |
| CHK-M7-331 (d) | `/tmp` prefix without the slash | red, 4 |
| CHK-M7-332 (a) | `check_execute` returns `[]` on `ShellSyntaxError` (fail open) | red, 13 |
| CHK-M7-332 (b) | an unlexable `-c` script passes | red, 2 |

Revision 1 and further rule plants:

| Plant | Change | Result |
| --- | --- | --- |
| B-r1-cluster | the r1 bug back: a short cluster whose letter takes a value (`-iu root`) skipped as one word | red, 8 |
| B-r1-next-word | a value-taking short option never takes the next word | red, 17 |
| B-long-opt-value | a long option's separate value not skipped | red, 10 (after the added test) |
| B-envS-cluster | `env -S` found only as the first letter of a cluster | red, 2 (added test) |
| B-envS-unchecked | `env -S` strings not checked | red, 6 |
| B-sed-cluster | `sed -i` only as the whole word | red, 5 |
| B-sed-long-abbrev | `--in-place` only in full | red, 4 (after the added test) |
| B-verb-first-only | apt/systemctl/dpkg/find only the first argument checked | red, 44 |
| B-dpkg-eq | `dpkg --opt=value` forms not matched | red, 5 |
| B-mkfs-dot | `mkfs.*` not matched | red, 6 |
| B-find-okdir | `-okdir` dropped | red, 2 |
| B-write-word-tee | `tee` dropped | red, 27 |
| B-code-xargs | `xargs` dropped | red, 30 |
| B-apt-autoremove | `autoremove` dropped | red, 2 |
| B-systemctl-setprop | `set-property` dropped | red, 1 |
| B-sh-c-subst | `-c` word holding a substitution allowed | red, 3 |
| B-sh-c-literal-subst | a literal `-c` script holding a substitution allowed | red, 7 |
| B-sh-no-c | a shell without `-c` allowed | red, 43 |
| B-ltgt-input | `<>` treated as input | red, 1 |
| B-nonliteral-reject | a non-literal command word rejected (against the user's ruling) | red, 9 |
| B-command-v-runs | `command -v`/`-V` treated as running the command | red, 1 |
| B-assignments-unchecked | substitutions in assignments not walked | red, 25 |
| B-msg-unquoted | token not quoted in messages | red, 2 |
| B-sed-skip-value | `-e`/`-f`/`-l` no longer take the next word | **survived** (see below) |

**38/39 red; all 14 security rows red.** The survivor, `B-sed-skip-value`, errs toward rejecting. Without the skip, an `-e`/`-f`/`-l` value that starts with `-` and holds an `i` (for example `sed -f -i.sed f`, where GNU sed reads `-i.sed` as a script file) would be refused as in-place. No realistic CIS command has such a value, and the change can only add rejections, never hide one. So it is not a security row, and I added no contrived must-pass case. Reviewer: please confirm, or ask for a must-pass row.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 | CODE | C | `pytest -q tests/test_bit102.py -k "must_reject and not context or corpora"` | PASS | 149/149 with token | 2026-10-27 |
| CHK-M7-116 | CODE | C | `pytest -q tests/test_bit102.py -k "every_context or context_count or data_words"` | PASS | 646 + 10 rows | 2026-10-27 |
| CHK-M7-117 | CODE | C | `pytest -q tests/test_bit102.py -k "108_matching or wrapper or abbreviations"` | PASS | 66 + 11 + 13 + 4 rows | 2026-10-27 |
| CHK-M7-118 | CODE | C | `pytest -q tests/test_bit102.py -k "redirections"` | PASS | 25 refused, 18 pass | 2026-10-27 |
| CHK-M7-119 | CODE | C | `pytest -q tests/test_bit102.py -k code_running` | PASS | 36 rows | 2026-10-27 |
| CHK-M7-120 | CODE | C | `pytest -q tests/test_bit102.py -k "must_pass or sample or sr_example or ruled or substring"` | PASS | 96 + 32 + 1 + 47 rows | 2026-10-27 |
| CHK-M7-121 | CODE | C | `pytest -q tests/test_bit102.py -k "unlexable or depth_8"` | PASS | 13 + 1 rows, one "cannot be checked" finding | 2026-10-27 |
| CHK-M7-327 | CODE | C | plant: substring search | PASS (red) | 473 failed | 2026-10-27 |
| CHK-M7-328 | CODE | C | plant: `/bin/rm` not reduced | PASS (red) | 14 failed | 2026-10-27 |
| CHK-M7-329 | CODE | C | plants (a)–(d): nested, `-c`, data words, redirect targets not walked | PASS (red) | 188, 88, 5, 5 failed | 2026-10-27 |
| CHK-M7-330 | CODE | C | plants: `WRAPPERS` empty; `busybox` dropped | PASS (red) | 127, 3 failed | 2026-10-27 |
| CHK-M7-331 | CODE | C | plants (a)–(d): any target, `..`, `"$F"`, `/tmp` without slash | PASS (red) | 69, 3, 7, 4 failed | 2026-10-27 |
| CHK-M7-332 | CODE | C | plants: fail open in `check_execute` and in `-c` scripts (lexer half in TASK-145) | PASS (red) | 13, 2 failed | 2026-10-27 |
| CHK-M7-146-extra | CODE | C | 24 rule plants (table above) | PASS (23 red, 1 survivor that errs toward rejecting) | see table | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 1177/1177 passed, 0 failed, 0 errors, 0 skipped. Plants: 38/39 red, with every security row red.

---

### TASK-146 TEST (revision 2 final): PASS

Tester: tester-m7d, 2026-10-27. Code under test: `0529083`. The r2 final code is `8173527`; it includes the three fixes in (6) for this tester's findings, and TASK-145 r1b is on top. Impl report: `work/reports/TASK-146-impl.md` "Revision 2", items (1) to (6). Review being answered: `work/reviews/TASK-146.md` findings 1 and 2 (blocking) and 3 (should-fix, tester-owned).

Rulings tested as written (`work/decisions.md`):
- the r2 order: the wrappers time, nsenter, unshare, flock, setpriv, taskset, chrt, `su -c` and runuser, plus brace expansion in bash mode;
- trap is refused whenever it sets an action;
- alias with a definition, `hash -p`, let, and `${…@P}` / `${…@E}` are refused;
- the readings the lead accepted (`trap SIG` passes; `sudo VAR=value cmd`);
- "three more fail-open forms" (the env `--` and nsenter `-S`/`-G` fixes, and `sudo -s`/`-i` and `doas -s` with no command are BIT102);
- the `sudo -e` residual, which has no test.

Spec: SR §4.2 L277–L287, §4.1 BIT102, §1.1; TS §3.3 L249.

Environment C and the scratch copy are as in `TASK-145-test.md` "revision 1 and 1b". GNU `time` 1.9 was installed in the container for the real-shell checks. `doas` is not installed, so its rows follow the ruling without a shell run.

#### Runs

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| as found (r2 snapshot, before my rows) | six files, `-n 4` | 2548/2548 passed |
| r2 + my rows, before (6) | `pytest -q tests/test_bit102.py` (scratch probe) | the 4 `env --` rows and the 4 `nsenter -S +0` rows not refused (bugs 1 and 2 below) |
| r2 final (`8173527`) + all rows | `pytest -q -p no:cacheprovider -n 4` on the six files | 2977/2977 passed |
| final (`0529083`) | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py` | 1555/1555 passed, 0 failed, 0 errors, 0 skipped |
| final, six files, 3 runs | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` | 2981/2981 passed, 3 times |
| static (repo root) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 278 files |

The existing corpus still passes:
- the 96 old must-pass rows;
- the SR §1.1 `Execute` (`test_sr_example_execute_passes`);
- every `Execute` in `bits/samples/*.bit`, read through the real parser (`test_every_sample_execute_passes`);
- the 149 old must-reject rows and their 646 context rows.

#### Findings (product; all three fixed in r2 (6), real-shell checked)

1. **env reads `-` and `NAME=value` after `--`** (#108 (d)). `env -- FOO=1 rm x`, `env -- - rm x`, `env -i -- FOO=1 rm x` and `env -u HOME -- FOO=1 rm x` all passed BIT102. Under dash, coreutils 9.4 runs the command in each (`dash -c 'env -- FOO=1 echo RAN'` prints RAN). sudo is not affected (`sudo -- FOO=1 echo RAN`: command not found). The implementer widened the fix to any operand holding `=` (`env a-b=1`, `env 1=2`, `env "$x"=1`, `sudo a-b=1`); all four run under dash, checked here.
2. **nsenter `-S`/`-G`/`--setuid`/`--setgid` take the next word as a required argument in util-linux 2.39.3**, even though `--help` prints `[=<uid>]`. `nsenter -S echo RAN` gives "failed to parse uid: 'echo'". `+0` and `' 0'` parse as uid 0, so `nsenter -S +0 rm x`, `-S ' 0'`, `--setuid +0` and `-G +0` passed BIT102 while nsenter runs the command. Now a non-decimal value is "cannot be checked".
3. **`sudo -s` / `sudo -i` / `doas -s` with no command start a root shell that reads stdin.** `echo 'echo RAN' | sudo -s` prints RAN, and the same holds for `-i`. The lead ruled them BIT102. With a command, the words are checked as a script. sudo really escapes the words (`sudo -s 'echo RAN; echo TWO'` runs one command named `echo RAN; echo TWO`), so refusing `sudo -s 'ls; rm x'` is stricter than sudo. The ruling allows that.

#### Tests added (tester-owned; nothing weakened, corpus size guards raised to 386 / 190)

- `bits/tests/bit102/must_reject.json` gets 199 TASK-146 rows (`rule` starting `146`), each with the token its message must hold:
  - 39 wrappers naming `rm`, plus 14 wrapper rows that fail closed;
  - 20 brace expansions, plus 4 brace rows that fail closed (unmatched, nested, 257 words, 65 levels), plus 1 brace inside a trap action;
  - 19 trap/alias/hash/let rows and 7 `@P`/`@E` rows;
  - 12 shell-option rows, plus 6 that fail closed;
  - 20 old-wrapper abbreviation and unknown-option rows (`option "--un"` …), plus 10 rows that still name `rm`;
  - 4 `env --` rows and 7 sed attached-value rows (review finding 3: `sed -es/a/b/ -i f`, `sed -l5 -i f`, `sed -nfx -i f`, `-l5 -i p f`, `-fx -i f`, `--line-length=5 -i p f`, `--expression=p -i f`);
  - 36 rows for (6).
- `must_pass.json` gets 94 rows in all, including the TASK-145 ones:
  - every must-pass list in the impl report, and the (6) list;
  - `trap -p 'rm x' EXIT` and `trap -l 'rm x' EXIT`: neither shell sets an action (dash: "Illegal option -p"; bash: invalid signal spec);
  - `sudo -l`, `sudo -v`, `sudo -k`;
  - `sed -es/a/b/ f`, `sed -l5 p f`, `sed -nfx f`.
- `manager/tests/test_bit102.py`:
  - `test_sed_attached_value_does_not_take_the_next_word` (7), and `test_sed_separate_value_is_taken` (2; `sed -e -i f`, `sed -l 5 p f`). The second is the opposite pin that the r1 survivor `B-sed-skip-value` lacked;
  - `test_brace_expansion_word_limit_256` (256 words pass, 257 refused), `test_brace_nesting_limit_64` (64 pass, 65 refused) and `test_brace_expansion_only_in_bash_mode`;
  - `test_shell_option_values_are_not_the_script` (7; the script is found, not "without -c") and `test_shell_option_values_with_read_only_script_pass` (3);
  - `test_code_defining_builtins_use_the_eval_message` (8), `test_listing_and_reset_forms_pass` (16) and `test_at_p_message_is_the_fail_closed_one`.

#### Real-shell confirmation (scratch `sh146/shellprobe.py` with `shellprobe.json`; `rm` replaced by `echo RAN`; sed rows edit a scratch file `f`)

- **The hidden command really runs: 150 rows.** Each is the Execute run by `dash -c` (bash for the `<(`/`>(`, `@P` and `let` rows); the `echo RAN` stand-in prints RAN, or sed edits `f` in place:
  - every wrapper row except the 5 below;
  - every brace row (bash expands `{echo,RAN}`, `ech{o..o}`, `"e"{cho,}`, `{sh,-c,'echo RAN'}` …);
  - every shell-option row (`-co`, `-oc`, `-Oc`, `+oc`, `-c -`, `-c -o`, `--rcfile`, `+c`);
  - the abbreviations that real getopt accepts (`env --un`/`--ch`/`--sp`, `nice --adj`, `timeout --sig`/`--pres`, `stdbuf --out`, `sudo --us`/`--gr`, `chroot --sk`, `setsid --fo`, `nsenter --targ`, `setpriv --reu`);
  - `echo 'rm x' | su root` and `su root -- -c 'rm x'`;
  - the trap, alias, hash, let and `@P` rows;
  - the `env --` and `nsenter -S +0` rows;
  - 6 of the 7 sed rows.

  The (6) rows were run by hand: `env a-b=1`, `env 1=2`, `sudo a-b=1`, `env "$x"=1`, `env -- - FOO=1 a-b=2`, `nsenter -S0`, `nsenter -S 0 -t $$`, `sudo -iu root CMD`, `sudo -s FOO=1 CMD`, `sudo --shell CMD`, `sudo --login` (stdin), `sudo -s -- CMD` and `sudo -sk CMD` each print their RAN.
- **The shell itself refuses or runs nothing: 52 rows.** These are fail-closed or ruling rows, where refusing is the safe side:
  - unknown options, `--flag=x`, `chrt -o`, `bash --rcf`, `sh -q`;
  - the brace fail-closed rows (bash's reading differs, or the expansion is too large);
  - `trap ''`, `trap "$a"`, `trap 0 'ls' EXIT`, `hash -p` under dash (bash only), `let x=1`, `${x@E}` (expands escapes only);
  - `x=$(cat <<'E' $(⏎…)⏎)` (syntax error in both shells);
  - `nsenter -S rm x` (uid parse error);
  - `flock -c 'rm x' /tmp/l`: flock 2.39 says "invalid option -- 'c'", because `-c` is only valid after the file;
  - `chrt -T 1 -P 2 -D 3 -d 0` (EINVAL here);
  - `runuser -l nobody -c` (nologin; with root it runs);
  - `sudo -h host` (sudo refuses a remote host);
  - `sed -l5 -i f`, which has no script (the `-l5 -i p f` variant edits `f`).
- **Skipped: 5 rows.**
  - `bash -c 'systemctl {stop,status} ssh'`, which would stop ssh;
  - `su root /tmp/script` (no script);
  - `alias r=rm`, `alias -p r=rm` and `builtin alias r=rm`, which define an alias and run nothing (the `alias r=echo⏎r RAN` row runs).

#### Plants (scratch copy; `tests/test_bit102.py tests/test_bit102_lexer.py`, `-n 4`; `scratchpad/plants_r2.json`, runner `plant2.py`)

| Plant | Change | Red |
| --- | --- | --- |
| W-SPECS-empty | no r2 wrappers | 67 |
| W-WRAPPERS-empty | no #108 (d) wrappers | 196 |
| W-unknown-option-taken-1 | an unknown option (incl. abbreviations) takes 1 word | 23 |
| W-flag-eq-accepted | `--flag=x` accepted | 3 |
| W-optional-as-value | optional letters take the next word | 4 |
| W-numeric-else-1 | nsenter `-S` non-decimal value read as the command (the bug-2 code) | 8 |
| W-time-dropped | external `time` not a wrapper | 9 |
| W-chrt-priority-unchecked | chrt non-decimal priority not refused | 3 |
| W-flock-file-c-unchecked | `flock FILE -c CMD` not checked | 4 |
| W-su-no-permute | su/runuser do not permute | 6 |
| W-su-without-c-allowed | su without `-c` allowed | 7 |
| W-su-script-unchecked | su/runuser/flock `-c` scripts not checked | 18 |
| W-env-after-dashdash | env stops at `--` (the bug-1 code) | 5 |
| W-sets-var-is-assignment | `_sets_var` back to `is_assignment` | 6 |
| W-sudo-assignment-skip-dropped | `sudo FOO=1` not skipped | 5 |
| W-sudo-shell-no-command-allowed | `sudo -s` with no command allowed | 12 |
| W-sudo-shell-command-unchecked | `sudo -s CMD` not checked | 10 |
| W-sudo-shell-rule-dropped | the sudo/doas shell rule removed | 14 |
| S-oO-take-no-word | `o`/`O` take no word (r1 blocking 1) | 16 |
| S-O-not-value | only `o` takes a word | 7 |
| S-lone-dash-not-consumed | a lone `-` not consumed | 6 |
| S-unknown-letter-accepted | an unknown shell letter accepted | 1 |
| S-long-prefix-accepted | any shell long option accepted | 4 |
| S-rcfile-takes-no-word | `--rcfile` takes no word | 1 |
| B-bash-false | no brace expansion | 29 |
| B-dash-is-bash | brace expansion for sh/dash too | 3 |
| B-su-script-dash-mode | su `-c` scripts not in bash mode | 3 |
| B-cap-unbounded | the 256-word cap removed | 3 |
| B-depth-unbounded | the 64-level cap removed | 3 |
| B-no-sequences | `{x..y}` not expanded | 3 |
| B-empty-word-kept | a word that expands to nothing kept | 1 |
| R-defines-code-false | trap/alias/hash/let never refused | 28 |
| R-let-dropped | let allowed | 5 |
| R-alias-dropped | alias definitions allowed | 8 |
| R-hash-dropped | `hash -p` allowed | 5 |
| R-trap-dropped | trap actions allowed | 12 |
| R-trap-reset-refused | `trap - SIG` refused (false positive) | 5 |
| R-trap-listing-ignored | `trap -p/-l …` refused (false positive) | 4 |
| R-trap-one-operand-refused | `trap SIG` refused (false positive) | 2 |
| R-atP-atE-dropped | `${…@P}`/`${…@E}` not refused | 17 |
| R-atE-dropped | only `@P` refused | 3 |
| T-time-always-keyword | `Grammar.time()` always `[]` | 6 |
| D-sed-attached-skips-next | an attached `-e`/`-f`/`-l` value also skips the next word (review finding 3) | 11 |
| D-sed-long-eq-skips-next | `--expression=…` also skips the next word | 5 |
| D-sed-skip-value (r1 survivor) | `-e`/`-f`/`-l` never take the next word | 1 (`sed -e -i f`) |

**45/45 red**, the r1 survivor included.
- Every security row (W-*, S-*, B-bash-false, B-cap/B-depth, R-*-dropped, R-defines-code-false, R-atP-atE-dropped, D-sed-*) is red.
- The `shlex_grammar.py` plant (T-time) was re-run on `0529083`.
- Red counts leave out the extra `test_long_inputs` failure explained in the TASK-145 section (a stored quadratic example). Each plant above has a red test of its own.

#### For the reviewer

- **Stricter than the shell, which is the safe side:**
  - `flock -c CMD FILE`, because flock 2.39 rejects `-c` before the file;
  - `sudo -s 'a; b'`, because sudo escapes it;
  - `coproc` at the top level under dash.
- **Brace sequences.** `bit102_brace._sequence` accepts any single character, while bash expands only letters (`{....}` stays literal). The impl over-expands, which is the safe direction: a literal bash word is never hidden.
- **Possibly in the open "arithmetic subscript" class (decisions 2026-10-27, open for the user).** bash `${!x}` indirection with `x='a[$(cmd)]'` runs `cmd` (checked: `a=(1); x="a[\$(echo RAN >&2)0]"; echo ${!x}` prints RAN). It is not in the rulings, so I added no test; main may add it to the open item.
- **Hypothesis database.** Once a slow example was stored, `test_long_inputs_up_to_16384_chars` failed on every run in that checkout, but a fresh database would not find it again. The deterministic `fndefs` rows now pin the case.

#### Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k must_reject` | PASS | 386/386 rows with token (199 new for TASK-146 r2); 150 real-shell RUNS | 2026-10-27 |
| CHK-M7-117 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "must_reject or sed_attached or sed_separate"` | PASS | 39 + 14 wrapper rows, 30 old-wrapper rows, 36 (6) rows, 7 + 2 sed rows | 2026-10-27 |
| CHK-M7-119 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "shell_option or code_defining or listing_and_reset or at_p"` | PASS | 7 + 3 + 8 + 16 + 1 | 2026-10-27 |
| CHK-M7-120 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "must_pass or sample or sr_example or ruled"` | PASS | 190 corpus (SR §1.1 first) + every `bits/samples` Execute | 2026-10-27 |
| CHK-M7-121 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "brace_expansion or brace_nesting"` and the fail-closed corpus rows | PASS | 256/257 and 64/65 bounds; 24 fail-closed corpus rows | 2026-10-27 |
| CHK-M7-330 (r2) | CODE | C | plants W-* (18) | PASS (red) | 18/18 | 2026-10-27 |
| CHK-M7-146-r2-plants | CODE | C | `python plant2.py plants_r2.json` | PASS (red) | 45/45 | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 278 files | 2026-10-27 |

Verdict: **PASS** (r2 final). 1555/1555 passed in `test_bit102.py`; 2981/2981 passed across the six files, 3 times; 0 failed, 0 errors, 0 skipped. Plants: 45/45 red. Three fail-open forms were found by this round and fixed in r2 (6) before the verdict.

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

### TASK-147 (revision)

#### Revision 2 (session transactions run with autocommit off; found through TASK-152)

New rows in `test_catalog_lock_pg.py` (20 tests now):
- `test_audit_append_inside_a_session_transaction`: an audit append inside `session.transaction()` under `catalog_lock` succeeds; the entry is invisible before COMMIT and visible after; a rolled-back session transaction leaves no entry.
- `test_between_transactions_the_session_is_autocommit_and_idle` (reviewer rows 1 and 2): after a commit and after a rollback, `autocommit` is True and the status IDLE; `catalog_lock` then takes the lock while idle, session-level.
- `test_commit_failure_closes_the_connection_and_the_pool_replaces_it` (reviewer row 4): the backend is terminated inside the transaction, so COMMIT fails with `DatabaseUnavailable`; the session's connection is closed or broken; the next pooled connection (`max_size=1`) is a new backend with autocommit False and 0 advisory locks.
- Reviewer row 3 is the existing `test_connection_goes_back_clean`, which still passes.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-140..145-r2 | APP | W | `pytest -q -n 2 tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py tests/test_policy_delete_pg.py tests/test_audit_append_pg.py` (m7t-t147r2) | PASS | 77/77 passed, 0 failed, 0 skipped (20 lock + 30 pool/runtime + 11 delete + the M2 audit append tests) | 2026-10-27 |
| CHK-M7-147-ac | APP | W | plant: `autocommit = False` removed in `transaction()` | PASS (red) | 8 failed (`AuditError` in the audit row and in the delete tests) | 2026-10-27 |
| CHK-M7-147-rs | APP | W | plant: `_restore_autocommit()` removed | PASS (red) | 2 failed (`test_between_transactions…`: autocommit False; `test_released_when_a_transaction_inside_raises`: ProgrammingError) | 2026-10-27 |

Verdict after revision 2: **PASS**.

### TASK-148 (revision)

#### Revision 1 (`retired_among`, for the #100 (a) widening)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-153-r1 | APP | W | `pytest -n 2 tests/test_catalog_repo_pg.py` (m7t-t161) | PASS | 52/52 passed. New: `test_retired_among_returns_only_the_retired_ids` (retired, active and unknown ids mixed: only the retired come back; none for active and unknown); `test_retired_among_empty_input_runs_no_statement` (a connection that refuses any statement: empty set, no query) | 2026-10-27 |
| CHK-M7-148-ra | APP | W | plant: state filter dropped | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-148-rb | APP | W | plant: state filter inverted (`active`) | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-336-r1 | CODE | L | plant: f-string query in `retired_among` | PASS (red) | S608 at catalog_plugins.py:53 | 2026-10-27 |

Verdict after revision 1: **PASS**.

## W4 (folded 2026-10-27, cloud session)

Folded by the lead, unchanged except that headings are demoted two levels. Every task below also has REVIEW APPROVED; TASK-154 has the user's second approval (decisions 2026-10-27).

| Task | Verdict | Source |
| --- | --- | --- |
| TASK-154 | PASS | `work/reports/TASK-154-test.md` |
| TASK-165 | PASS | `work/reports/TASK-165-test.md` |
| TASK-174, 175 | PASS (G59: CHK-M7-300, -301, in the TASK-154 report) | `work/reports/TASK-154-test.md` |

### TASK-154

Tester: tester-m7-154, 2026-10-27. Covers REQ-150, REQ-155, REQ-157, REQ-160, REQ-162 and REQ-176 (2). Spec: TS §4.1 L516–L532, §5.2 (`bit_import`; the app only inserts it and never deletes `policy`), §8.4 L1290–L1291; SR §1.1, §3.6, L250. Open-question answers used: #23, #98 (j), #99 (b) and (e), #100 (a) as widened, #101, #110. Design: D4 and `work/plans/TASK-154.md` §10, plus deviations (1)–(5) (`work/decisions.md`, last TASK-154 row).

Files under test: `bm/services/importer/pipeline.py` and `bm/services/importer/pipeline_record.py`. Checks: CHK-M7-190 to -197 (TP-M7-14), mutation rows CHK-M7-333, -339, -340, -349, -350 and -369, plus extra plants CHK-M7-154-*. Also, because G59 was waiting on this task, CHK-M7-300 and -301 (G59, the TASK-174/175 samples).

New tester files (no product file changed):
- `manager/tests/pipeline_rows.py`: helpers. It generates files with fresh names and plugin ids, takes a snapshot of the catalog checksums, the `bit_import` and `audit_log` high-water marks and every M7 counter, and reads the results as owner.
- `manager/tests/test_import_pipeline_pg.py`: 199 tests, with its own migrated server per module.
- `manager/tests/test_import_fuzz_pg.py`: 1 test, 500 files.
- `manager/tests/test_samples_import_pg.py`: 2 tests, each in its own fresh catalog.

The tests were written from the spec, the acceptance row and plan §10 before reading `pipeline*.py`. The code was read afterwards, only to find the branches to plant and the hook names to patch for fault injection.

#### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 | `pytest -n 0 tests/test_import_pipeline_pg.py` | 199/199 passed, 0 failed, 0 errors, 0 skipped |
| r1 | `pytest -n 2 tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | 3/3 passed, 0 failed, 0 errors, 0 skipped. Fuzz tally: success 140, rejected 234, skipped 15, refused 78, injected fault 33 (total 500) |
| r2 (affected set) | `pytest -n 4` the 3 new files plus `test_import_store_pg.py test_import_alerts.py test_import_alerts_pg.py test_imports_repo_pg.py test_catalog_lock_pg.py test_policy_delete_pg.py test_bit_validate.py test_bit102.py test_bit_fixtures.py` | **2829/2829 passed**, 0 failed, 0 errors, 0 skipped |
| r3 (coverage) | `pytest -n 2 --cov=bitscan_manager.services.importer` the 3 new files | 202/202 passed; `pipeline.py` 113/113 lines (100 %), `pipeline_record.py` 62/62 (100 %) |
| static | `ruff check manager`, `ruff format --check` (tests), `mypy --strict --config-file manager/pyproject.toml manager` | clean (286 files) |
| plants control | copy `scratchpad/t154/base` (manager, bits and docs, no venv), run from the copy's `manager/` with `PYTHONPATH` set to it. The import path printed was the copy's `pipeline.py`. Same 3 files, `-n 4` | 202/202 passed |

Two first-draft test bugs, both mine and both fixed before r1: (a) `test_samples_import_pg.py` did not create its credentials folder; (b) the first fuzz mix gave too few successes and faults (the 27 >= 50 assertion caught it), so the generator was re-weighted. Neither was a product failure.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-190 | APP | Linux/PG | r0 `test_sr_example_imports_with_one_success_row_and_one_alert_then_auto_skips` | PASS | The byte-identical SR §1.1 example (manifest sha matches), `manual`. Exactly 1 `bit_import` row, every column: `sr.bit`, sha, v1, `manual`, `success`, 1/0/0, `[]`, `imported_by` 7, `imported_at` = clock. Exactly 1 audit entry: `policy.import`, actor `user:7`, target `policy:<id>`, `alert` true, kind `policy_imported`, `changed_executes` = [the SR plugin, full Execute, its sha, reason `new`, flags `[]`]. Counter delta exactly `{policy_imported: +1}`. The alert's `xmin` equals the policy row's `xmin` (same transaction) and the record's `xmin` differs (its own transaction) | 2026-10-27 |
| CHK-M7-191 | APP | Linux/PG | r0 `test_each_rejecting_fixture_…` (150 fixtures, all `rejected` non-`db/` manifest entries; modes cycle auto, manual, rebuild) | PASS | Each fixture gives 1 `rejected` row: codes = the manifest codes, `errors` = the outcome's findings, keys exactly `{line, element, code, message}`, sorted by line, manifest line and element checked. 1 `policy.import_rejected` alert in the record transaction (same `xmin`): `import_id`, mode, file name, distinct codes; target is the file name, or `policy:<id>` when a policy matched. Counter delta exactly `{policy_import_rejected: +1, import_failures{mode}: +1}`. Catalog checksums unchanged. The XXE canary file was never created | 2026-10-27 |
| CHK-M7-191 db rules | APP | Linux/PG | r0 `test_bit007_…`, `test_bit015_…`, `test_bit016_…[2.0, 1.1]`, `test_bit002_stops_the_content_rules`, `test_rejecting_an_update_…` | PASS | BIT007 at line 4 `Policy/PolicyName`, target `policy:<a>`; BIT007 + BIT003 → `[(BIT007,4),(BIT003,6)]`. BIT015 at `Plugin[2]/PluginId`; BIT003 + BIT015 sorted by line; after the owner drops the id the claimer succeeds and owns its plugins. formatVersion 2.0 or 1.1 with a bad status → {BIT003, BIT016} (SR L250). BIT002 + bad status → only BIT002. Rejecting an update to a live policy leaves it unchanged, target `policy:<id>` | 2026-10-27 |
| CHK-M7-191 bounds | APP | Linux/PG | r0 `test_oversize_…`, `test_5_mib_…`, `test_5000_plugins_…`, `test_long_client_name_…` | PASS | `data=None` → exactly `[{null, null, BIT001, "The file is larger than 5 MiB."}]`, the streamed hash stored, metric `auto` +1. 5,242,880 bytes → `success`; 5,242,881 → BIT001. 5,000 plugins → `success` with 5,000 added, order kept and 5,000 changed Executes; 5,001 → BIT017. A 304-character client name is kept whole in `file_name`, and the target is its first 255 characters | 2026-10-27 |
| CHK-M7-192 | APP | Linux/PG | r0 (SR test second half), `test_auto_skip_only_for_an_unchanged_last_success`, `test_auto_skips_an_unchanged_live_upload_…` | PASS | `auto` on an unchanged file → exactly 1 `skipped` row (v1, 0/0/0, `[]`), no audit entry, no counter, catalog unchanged. The plain string `"auto"` works the same. `manual` and `rebuild` → `success`, v1 kept for the identical hash, 0/0/0, one `policy.import` with `changed_executes` `[]`. Changed bytes in `auto` → v2. A retire reaches the row (0/0/1, v3). A file rejected earlier is retried (2 `rejected` rows, `fail:auto` +2). An unchanged live upload in `auto` → skipped | 2026-10-27 |
| CHK-M7-193 | APP | Linux/PG | r0 `test_warnings_only_…`, `test_a_rejected_file_lists_its_warnings_too` | PASS | `valid/warnings-only.bit` → `success` with BIT101 and BIT103 stored in `errors` (#110). BIT102 + BIT101 → `rejected` with both listed | 2026-10-27 |
| CHK-M7-194 | APP | Linux/PG | r0 `test_before_commit_…`, `test_record_failure_after_a_committed_success_…`, `test_after_commit_…` (2) | PASS | `before_commit` gets an int id (the existing id on an update). If it raises: catalog unchanged, no row, no audit entry, no counter (REQ-162 (4)). If transaction 2 fails after a success: the catalog is committed, `import_id` None, the alert stands, and one log line `bit_import record failed: DivisionByZero` (REQ-160 (4)). `after_commit` sees the policy committed (visible from another connection) and no row yet; if it raises, the `success` row is still written and the error propagates (deviation (5)). It is not called for a rejection or a skip | 2026-10-27 |
| CHK-M7-195 | APP | Linux/PG | r0 `test_the_buffer_is_hashed_and_parsed_once_and_never_reread`, `test_prepare_is_pure_…` | PASS | The file on disk is rewritten after the one read. An audit hook sees no `open` of it during `import_one`. The stored `source_sha256`, the row's `file_sha256` and the plugin Execute all come from the buffer. `prepare` takes only `data`, with no file, socket or process events. A given `prepared` is not redone (spy: 0 calls; without it, 1) | 2026-10-27 |
| CHK-M7-196 | APP | Linux/PG | r0 `test_database_error_in_the_catalog_transaction_is_not_a_rejection` (3 places × 3 modes), `test_record_failure_with_nothing_committed_propagates[rejected, skipped]` | PASS | A real PostgreSQL error (`SELECT 1/0`) before the membership write, after the store, or after the audit entries → `DivisionByZero` propagates. Catalog unchanged, no `bit_import` row, no entry, no counter (#98 (j)). If transaction 2 fails for a rejected or skipped file: the error propagates, with no row, no alert and no count | 2026-10-27 |
| CHK-M7-197 | APP | Linux/PG | r1 `test_500_generated_files_leave_the_catalog_complete_or_unchanged` | PASS | 500 seeded files (structured mutations; 20 % also byte-mutated). About 10 % had a database fault mid-store and about 10 % a `before_commit` `OSError`. After every rejection, skip, refusal or fault, all 4 catalog checksums equal the ones before, with no row on a fault. After every success the policy is exactly the file (name, status, hash, not deleted, plugins in order with Execute and timeout, active, owned by it). Tally asserted (≥ 50 success, ≥ 100 rejected, ≥ 25 faults, ≥ 1 skip) | 2026-10-27 |
| CHK-M7-154-refused | APP | Linux/PG | r0 `test_upload_of_a_server_folder_policy_is_refused_…` | PASS | `PolicyManagedOnServer` is re-raised with the server policy's id. No row, 1 `policy.import_refused` entry (target `policy:<id>`, actor kept, no `alert`, the client-name canary absent), no counter, catalog unchanged (#99 (e)) | 2026-10-27 |
| CHK-M7-154-entries | APP | Linux/PG | r0 `test_reenable_…`, `test_move_from_upload_…`, `test_a_file_renamed_onto_an_uploaded_name_…` | PASS | Re-enable by file → `policy.import` then `policy.status_change` (`policy_reenabled`, `by: file`, `status_overridden: false`). With the admin override → only `policy.import`, and the status stays disabled. Upload to server folder → `policy.move` `{from: uploaded/policy-<id>.bit, to: mv.bit}`, no alert, the copy removed after commit. A file renamed onto an uploaded name → import, move, then `policy.delete` of X (`policy_deleted`, "file now holds another policy"), X `deleted_at` set | 2026-10-27 |
| CHK-M7-154-rebuild | APP | Linux/PG | r0 `test_rebuild_savepoints_…` | PASS | 4 files in one transaction: ok, BIT102, ok, BIT015-against-the-first. Results: success, rejected, success, rejected. No counter moves before the commit; `policy_imported` +2 after it. `record` writes 4 `rebuild` rows (ids returned in order) and 2 rejected alerts; `fail:rebuild` +2; the rejected files leave no entries | 2026-10-27 |
| CHK-M7-154-bit102 | APP | Linux/PG | r0 `test_bit102_rejects_in_every_mode_and_target` (3 modes × 2 target kinds × 6 fixtures × with or without `prepared`) | PASS | Every combination is `rejected` with BIT102 and leaves the catalog unchanged (REQ-157 (3), pipeline half) | 2026-10-27 |
| CHK-M7-154-metric | APP | Linux/PG | r0 `test_failure_metric_counts_once_per_rejection_with_its_mode[auto, manual, rebuild]` | PASS | After 1 and 2 rejections the delta is exactly that number for that mode only, with the rejected alert equal to it | 2026-10-27 |
| CHK-M7-154-logs | APP | Linux/PG | r0 `test_execute_text_names_and_tokens_never_reach_application_logs` | PASS | DEBUG capture across a success, a skip, a BIT102 rejection, a BIT003 rejection and a transaction-2 failure. The Execute canary, a `bsa_` token, the policy-name canary and the client-file-name canary appear in no record (message, args or `__dict__`). The pipeline's own `bit import success` / `rejected` / `skipped` lines are present | 2026-10-27 |
| CHK-M7-154-lock | APP | Linux/PG | r0 `test_import_one_never_takes_the_catalog_lock_itself`, `test_the_callers_lock_spans_the_rename_and_the_record` | PASS | While a probe holds `hashtext('catalog')`, `import_one` on another session still finishes, so it never takes the lock (the contract is in its docstring). With the caller's lock: during `after_commit` the probe's `pg_try_advisory_lock` fails; after `import_one` returns it still fails; after the caller's `catalog_lock` exits it succeeds | 2026-10-27 |
| CHK-M7-300 | APP | Linux/PG | r1 `test_all_samples_import_together_with_no_reject_and_no_bit102` | PASS | Both `bits/samples/*.bit` in one fresh catalog (own container), `auto`, every file present: each `success`, no Reject finding, no BIT102, distinct names, plugin count = sum of added (distinct ids) | 2026-10-27 |
| CHK-M7-301 | APP | Linux/PG | r1 `test_the_sr_example_alone_imports_in_a_fresh_catalog` | PASS | Another fresh catalog: `success`, v1, 1 added; `CIS Ubuntu 24.04 Level 1 - Server` with 1 plugin | 2026-10-27 |
| CHK-M7-154 static | CODE | Linux | ruff, format, mypy (CI form) | PASS | clean, 286 files | 2026-10-27 |

##### Plants (copy `scratchpad/t154/<id>`; control `base` 202/202 green; each run is the 3 new files, `-n 4`)

| Check | Plant | Result | Red tests (reason) |
| --- | --- | --- | --- |
| CHK-M7-154-P01 | Success alert committed before the commit point (`COMMIT; BEGIN` after `audit_success`) | PASS (red) | 3 failed: the before-commit rollback test (catalog checksum changed), the rebuild test, fuzz |
| CHK-M7-154-P02 | Alert counters run at once, not on commit | PASS (red) | 5 failed (`{policy_imported: 1}` != `{}`): rollback, 3 × DB error after audit, rebuild |
| CHK-M7-154-P03 | Rejected path changes the catalog (a DB-rule rejection still applied and committed) | PASS (red) | 2 failed: BIT015 (checksum changed), fuzz |
| CHK-M7-369 (a) | `manual` skips too | PASS (red) | 2 failed (`skipped` != `success`) |
| CHK-M7-369 (b) | `auto` never skips | PASS (red) | 6 failed, incl. the SR test and fuzz |
| CHK-M7-154-P06 | A `rejected` record written for an internal error | PASS (red) | 11 failed: 9 DB-error cases, rollback, fuzz (row exists) |
| CHK-M7-350 (count) | `count_failure` removed | PASS (red) | 156 failed |
| CHK-M7-154-P07b | Failure counted under `auto` whatever the mode | PASS (red) | 103 failed (the manual and rebuild rows) |
| CHK-M7-154-P08 | BIT102 step skipped in `prepare` | PASS (red) | 15 failed |
| CHK-M7-333 | BIT102 skipped in `rebuild` mode (import_one and `store_in_savepoint`) | PASS (red) | 8 failed: rebuild sweep rows, the BIT102 matrix, the rebuild savepoint test, fuzz |
| CHK-M7-339 | `bit_import` written in transaction 1 (lost on reject) | PASS (red) | 177 failed |
| CHK-M7-340 | Late exception swallowed (`before_commit` error ignored, transaction 1 committed) | PASS (red) | 2 failed: rollback (DID NOT RAISE), fuzz |
| CHK-M7-349 | No `policy_imported` entry | PASS (red) | 8 failed |
| CHK-M7-350 (alert) | No `policy_import_rejected` entry | PASS (red) | 158 failed |
| CHK-M7-154-P14 | `import_one` takes the catalog lock itself | PASS (red) | 1 failed ("import_one waited on the catalog lock") |
| CHK-M7-154-P15 | Lock released before the rename | PASS (red) | 1 failed (probe got the lock) |
| CHK-M7-154-P16 | File read again from disk | PASS (red) | 1 failed (`open` of `once.bit` recorded) |
| CHK-M7-154-P17 | `Pending` logged | PASS (red) | 1 failed (Execute canary in the log) |
| CHK-M7-154-P18 | Transaction-2 failure after a success propagates | PASS (red) | 2 failed (`DivisionByZero` raised) |

Plants: **19/19 red.**

#### Acceptance coverage

- SR §1.1 example: one `success` row and one `policy_imported` alert. CHK-M7-190 PASS.
- Each BIT fixture rejected, with its row and alert and no catalog change. CHK-M7-191 (150 fixtures plus the db, bounds and BIT016 rows) PASS.
- Unchanged file in `auto` → only `skipped`. CHK-M7-192 PASS.
- 500 generated files: complete or unchanged. CHK-M7-197 PASS.
- A rolled-back import writes no success alert. CHK-M7-194 and CHK-M7-196, P01, P02, CHK-M7-340: PASS.
- Also checked: the lock contract, read once, the log canary, audit entries in the same transaction (`xmin`), and the metric once per rejection with its mode. All PASS.

#### Findings for the reviewer (none blocking)

1. **The lock contract is documented, not enforced.** `import_one` runs to completion on a session that does not hold `catalog_lock` (shown by `test_import_one_never_takes_the_catalog_lock_itself`). Every current caller is a future task (155 to 158), so a missed lock there would go unnoticed. One option is a cheap guard: a flag set by `catalog_lock` on the session, checked at entry. Reviewer or lead to decide.
2. **`FileInput.sha256` is trusted, not checked against `data`.** `import_one` stores whatever hash the caller passes. The read-once and hash-of-the-same-bytes property therefore belongs to the callers (TASK-155 uploads, TASK-156 folders), and their tests must check it there. A one-line check (`sha256(data) == sha256` when `data` is not None) would make the pipeline self-checking.
3. Deviation (5) behaves as accepted: after a failed `after_commit` there is still one `success` row, and the error is re-raised.
4. `policy.import_refused` detail `{policy_id, mode, file_sha256}`: no client text reaches the entry (canary checked).

### TASK-165

Tester: tester-m7-165, 2026-10-27. REQ-173 (1) to (4), REQ-174 (2); TS §6.2 L1107 (`GET /imports`, admin), §6 L1056 (user routes take only `bsu_`/`bsk_`), §6.3 L1133 to L1141 (problem+json, cursor paging, max 500, catalog keys as integers, RFC 3339 UTC, stored text untrusted), §5.2 L694 to L707 (`bit_import`); #98 (h), (i), #110, #53 (i), #48. Files under test: `bm/api/user/imports.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (plus TASK-149's `repositories/imports.py` through the route). New test file `manager/tests/test_imports_api_pg.py` (79 tests) on the M2 users-API environment (real auth, sink gate, rate limiter), with a module-owned PostgreSQL (`own_migrated_server`) and `bit_import` truncated as owner before each test, so page contents are asserted exactly. Tests were derived from the spec and the answers first; the code was read only for the cursor-key branch.

#### Runs (Linux container, `CI=true`, Ryuk pinned)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 | `pytest -n 2 tests/test_imports_api_pg.py` | 77/78 passed, 1 failed, 0 errors, 0 skipped: `test_bad_limit_is_400[50 ]` (test bug: the shared `page_params` accepts `"50 "` as 50 on every list; not this task; case removed) |
| r1 | `pytest -n 0 tests/test_imports_api_pg.py::test_bad_limit_is_400` | 7/7 passed |
| r2 | `pytest -n 4 tests/test_imports_api_pg.py tests/test_imports_repo_pg.py tests/test_policies_api_pg.py tests/test_audit_log_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py tests/test_auth_dependencies.py tests/test_app.py` | 258/258 passed, 0 failed, 0 errors, 0 skipped |
| r3 | `pytest -n 4 tests/test_imports_api_pg.py` (after adding the 2 prefix-vs-hash tests) | 79/79 passed |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (283 files) |

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-258 (1) | APP | W | r2, r3 | PASS | N + 1 rows with `limit=N` (N = 1, 2, 3, 7, 500): pages `[N newest], [oldest]`, each once, strictly by `import_id` desc, `next_cursor` null on the last page; exactly N rows → one page, cursor null; empty → `{"items": [], "next_cursor": null}`; default limit 50 (51 rows); order is `import_id`, not `imported_at` (clock stepped back); rows added between pages do not appear on page 2; limit `0`, `501`, `-1`, `a`, `1.5`, ``, `1e2` → 400 `invalid_request`; unknown parameters (`outcome`, `mode`, `file_name`, `status`, `order`, `sort`, `before`) are ignored and never filter (#98 (h), as `test_package_query.py`) | 2026-10-27 |
| CHK-M7-258 cursor | APP | W | r2, r3 | PASS | tampered cursors (MAC byte, payload byte, truncated, appended, padding, space, `x`, `W10`, `!!!!`, `%00`, 512 × `A`) → 400; 513 chars → 400; real `/users` and `/api-tokens` cursors → 400; validly signed integer cursors of scopes `audit_log`, `policies`, `users`, `agents`, `api_tokens`, `Imports`, `` → 400; signed `imports` keys `True`, `False`, 0, -1, -2^63, 2^63, 2^64, 10^30, `"5"`, `""`, `[5]`, `[]`, null, 1.5, `{}` → 400, never 500; keys 1 (empty page) and 2^63-1 (all rows) → 200 | 2026-10-27 |
| CHK-M7-258 (2) | APP | W | r2, r3 | PASS | every item has exactly the 12 `bit_import` columns; `import_id`, `policy_version`, the three counts and `imported_by` are JSON integers, nulls for a system/skipped row; `imported_at` ends `Z` and equals the stored instant; every mode × outcome round-trips; `errors` equals the stored `jsonb` and the inserted list (BIT003, BIT101, BIT103, BIT001 with null line/element), warnings kept on a success (#110), 2,000 findings returned whole | 2026-10-27 |
| CHK-M7-258 (3) | APP | W | r2, r3 | PASS | admin `bsu_` and admin `bsk_` → 200; operator and viewer (session and API) → 403 `forbidden` with no item in the body; admin without TOTP (session and API) → 403 `totp_enrolment_required` (#53 (i)) | 2026-10-27 |
| CHK-M7-258 (4) | APP | W | r2, r3 | PASS | a hostile `file_name` (HTML/JS, `../`, formula prefixes, CR LF tab, bidi, ESC, DEL, C0, `%00`) and hostile `element`/`message` come back byte-identical as JSON; `application/json` with `nosniff` | 2026-10-27 |
| CHK-M7-282 | APP | W | r2, r3 | PASS | `bsa_`, `bse_`, no token, garbage `bsu_`/`bsk_`, a revoked admin token → 401 problem+json with no data; a `bsa_`/`bse_` string whose hash is stored as an admin API token is still 401 (prefix decides the group); 600 requests in a minute pass and the 601st is 429 `rate_limited`, and the next window passes; POST/PUT/PATCH/DELETE on `/imports` and `/imports/{id}` → 404/405 with nothing changed; GETs write no `bit_import` or `audit_log` row | 2026-10-27 |
| CHK-M7-281 | APP | W | r2 (`test_invariants_m3.py`) | PASS | the route walk passes with `GET /imports` (already in the spec allow-list); no query parameter can switch inventory off | 2026-10-27 |
| G6 | CODE | W | r2 (`test_openapi.py`) and `test_openapi_documents_the_route_…` | PASS | export byte-identical to `manager/openapi.json`; the path has only `get`, parameters exactly `limit` (1..500, default 50) and `cursor`; 400/401/403/429 are problem+json; `ImportItem` has the 12 columns, all required, `import_id` integer, `mode`/`outcome` enums as the DDL CHECKs | 2026-10-27 |

#### Plants (scratch copies under `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/t165/`, `bitscan_manager` plus `tests` copied, run from the copy with `PYTHONPATH` set)

Control: a probe test printed `bitscan_manager.__file__` inside the copy, and the unchanged copy ran 79/79 passed.

| Plant | Result | Failing tests |
| --- | --- | --- |
| p1 RBAC loosened: `require_role("operator")` | red | 2 failed (operator session and API get 200) |
| p2 cursor scope check removed in `decode_cursor` | red | 8 failed (real `/users` cursor, 7 foreign-scope cursors) |
| p3 `bsa_`/`bse_` parsed as `bsk_` in `parse_user_token` | red | 2 failed (prefix-vs-hash tests) |
| p4 order flipped (`ORDER BY import_id ASC`) | red | 14 failed |
| p5 cursor key bounds/type check removed in `_before` | red | 15 failed (500 instead of 400) |
| p6 order by `imported_at DESC, import_id DESC` | red | 1 failed |
| p7 warnings (BIT101/BIT103) dropped from `errors` | red | 2 failed |
| p8 no look-ahead row (`limit` instead of `limit + 1`) | red | 9 failed |

8/8 plants red.

#### Findings for the reviewer

- None against TASK-165. The route matches #98 (h), (i) and REQ-173.
- Note (not this task): the shared `page_params` accepts `limit=50 ` (trailing space) as 50 on every list (pydantic lax int). The spec does not forbid it; recorded, not tested.
- In p3, an unknown `bsa_` token is 401 even with the prefix check removed, because the hash lookup fails. Only the hash-present test shows the prefix check, so it is kept as a security row.

## W5 and the first web wave (folded 2026-10-28, cloud session)

Folded by the lead, unchanged except that headings are demoted two levels. Every task below has REVIEW APPROVED; TASK-168 is its first pass (the second follows TASK-162 to 164).

| Task | Verdict | Source |
| --- | --- | --- |
| TASK-155 | PASS (r0, r1, r2 and r3) | `work/reports/TASK-155-test.md` |
| TASK-156 | PASS (revisions 1 to 4 included) | `work/reports/TASK-156-test.md` |
| TASK-168 | PASS | `work/reports/TASK-168-test.md` |
| TASK-169 | PASS | `work/reports/TASK-169-test.md` |

### TASK-155

Tester: tester-m7-155b, 2026-10-27. This continues the files that tester-m7-155 left when the container restarted (snapshot d6e60d6). Covers REQ-163 (1)–(6) and REQ-165 (1). Spec: TS §4.1 L516–L532 (L522, L526, L528), §4.6, §8.7 (L1344, L1377). Answers and rulings used: #99 (d) and (e), #101, #98 (j). Decisions (2026-10-27): "Crash window ruling", "Rebuild finishes interrupted uploads first", "TASK-154 REVIEW APPROVED … Carried" (a) and (b), and "TASK-155 built … lead rulings" (1)–(3). Checks: TP-M7-15, CHK-M7-200 to -204, the REQ-165 (1) half of CHK-M7-230, and mutation rows CHK-M7-357 to -359.

Files under test: `manager/bitscan_manager/services/importer/uploads.py` and `FileInput.__post_init__` in `pipeline_record.py`. No product file was changed.

Tester files:
- `manager/tests/test_uploads.py`: 74 tests, no database. They cover the #99 (d) name form (bytes and `str`), the 255-character cut, lone surrogates, the `FileInput` mismatches, the rename guard and the discard log.
- `manager/tests/test_uploads_pg.py`: 63 tests, on PostgreSQL with a temporary bits folder per test.

Changes this session to the snapshot:
- (1) The hostile-name test no longer assumes `/abs.bit` is absent. It compares the state (inode, mtime, hash) of `/abs.bit`, `/x.bit` and `/a/b.bit` before and after the upload. The predecessor's plant run of "client name as path" had left a root-owned `/abs.bit` (a generated "Hostile …" policy, 19:29:56). That file failed 21 rows of the control run and made its plant log worthless, so every plant was redone.
- (2) New: `test_two_concurrent_uploads_of_one_policy_serialise`.

#### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, Ryuk pinned, nothing skipped; from `manager/`)

| Run | Command | Count |
| --- | --- | --- |
| r0 (snapshot as found) | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | 115/136 passed, 21 failed: all `hostile…[i]`, `assert not Path("/abs.bit").exists()`. This was a test bug from the leaked file, not a product failure |
| r1 | same, after (1) and (2) | **137/137 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (TASK-154 suites) | `pytest -n 4 tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | **202/202 passed** |
| r3 (affected set) | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py tests/test_import_store_pg.py tests/test_catalog_lock_pg.py tests/test_policy_delete_pg.py tests/test_bit_fixtures.py tests/test_import_alerts_pg.py` | **439/439 passed** |
| r4 (coverage) | `pytest -n 2 --cov=bitscan_manager.services.importer` on the 2 files | 137/137 passed. `uploads.py` 122/122 lines (100 %), `pipeline_record.py` 68/68 (100 %) |
| static | `ruff check` and `ruff format --check` on the 2 files; `mypy --strict --config-file manager/pyproject.toml manager` | ruff clean. mypy: no error in the TASK-155 files; 17 errors, all in `test_folders_pg.py` (another tester's, in progress against TASK-156 r1) |
| plants control | copy `scratchpad/t155/r2/base`, `PYTHONPATH` = the copy (the printed `uploads.__file__` is the copy's) | 137/137 passed |

#### Report rows (tests/m7/report.md format, to be folded by the lead)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-200 | APP | Linux/PG | r1 `test_a_hostile_client_name_lands_only_as_policy_id_bit[0..20]`, `test_a_client_name_naming_another_policy_never_touches_its_file`, `test_uploads.py` name rows | PASS | 21 names, as bytes and as `str`. They include every REQ-163 (1) name (`../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, 5,000 chars, NUL, CR, LF, `<script>`, RLO, invalid UTF-8), plus `uploaded/../../x.bit`, `policy-1.bit`, `.tmp-1-<hex>`, a lone surrogate and 5,000 × `é`. The tree diff of the whole tmp root is exactly `{bits/uploaded/policy-<id>.bit: (file, 0600, sha(data))}`. `/`-level targets and `/etc/passwd` are unchanged. `file_name` equals `client_file_name(raw)` and the literal #99 (d) values; it is ≤ 255 characters with no C0 or DEL. A name equal to another policy's stored file leaves that file byte-identical | 2026-10-27 |
| CHK-M7-201 | APP | Linux/PG | r1 `test_a_symlink_at_the_temp_path_…`, `test_a_dangling_symlink_…`, `test_a_regular_file_at_the_temp_path_…`, `test_a_directory_at_the_temp_path_…`, `test_a_symlink_at_the_final_path_…` | PASS | A planted symlink, dangling link, regular file or directory at `.tmp-<id>-<sha>` → `OSError` (EEXIST or ELOOP). There is no `bit_import` row and no audit entry, the catalog checksums and counters are unchanged, and the tree under the tmp root is identical: the link, its target's bytes and mode, the planted file and the old `policy-<id>.bit` are all kept. A dangling link's target is never created. A symlink at the final path is replaced by a regular file, and the victim is unchanged | 2026-10-27 |
| CHK-M7-202 (3) | APP | Linux/PG | r1 `test_a_rejected_reupload_…`, `test_a_rejected_new_upload_writes_nothing`, `test_a_reupload_replaces_only_that_policys_file` | PASS | A BIT003 re-upload → `rejected` with an identical file (inode, mtime_ns, mode) and an unchanged catalog, one `rejected` row with `bad.bit`. A rejected new upload or non-XML writes nothing. A re-upload replaces only that policy's file | 2026-10-27 |
| CHK-M7-202 (4) before commit | APP | Linux/PG | r1 `test_a_fault_after_the_temp_open_and_before_commit_leaves_no_temp[write, fsync, dirsync × new, update]` | PASS | A partial `os.write` (ENOSPC), an `fsync` EIO or a directory-fsync EIO → `OSError`. The tree is identical (no temp, old file kept), with no catalog change, no row, no entry and no counter | 2026-10-27 |
| CHK-M7-202 (4) at commit | APP | Linux/PG | r1 `test_a_failed_commit_keeps_the_temp_and_finish_deletes_it_when_not_committed`, `test_a_commit_that_happened_but_reported_unavailable_is_renamed_by_finish` | PASS | Lead ruling (2). Backend killed before COMMIT → `DatabaseUnavailable`, the temp is kept, the catalog is unchanged; `finish` → (0 renamed, 1 deleted), old file kept. COMMIT done but `DatabaseUnavailable` reported → the temp is kept and the row has the new hash; the same bytes uploaded again → `OSError` and the temp is untouched (the accepted 500); `finish` → (1, 0), the new file has mode 0600 | 2026-10-27 |
| CHK-M7-202 (4) after commit | APP | Linux/PG | r1 `test_a_fault_between_commit_and_rename_is_finished_at_the_next_start`, `test_a_new_policy_whose_rename_failed_gets_its_file_from_finish` | PASS | `os.replace` EIO → `OSError`. There is one `success` row (`v2.bit`, TASK-154 deviation (5)) and the row has the new hash; `uploaded/` holds the old file and the temp. `finish` → (1, 0), and the file is the new bytes. A new policy gets its first file from `finish` | 2026-10-27 |
| CHK-M7-203 | APP | Linux/PG | r1 `test_an_upload_of_a_server_folder_policy_is_409_with_nothing_written` | PASS | `PolicyManagedOnServer` with the server policy's id; the tree is identical and `uploaded/` is empty. No `bit_import` row; exactly 1 entry `policy.import_refused`, `policy:<id>`, `user:7`, with no `alert`. No counter and no catalog change | 2026-10-27 |
| CHK-M7-204 | APP | Linux/PG | r1 `test_the_stored_file_is_0600_and_the_service_users[umask 000, 022, 077]`, `test_temp_open_flags_…` | PASS | A regular file with mode 0600 and uid/gid = the process's, under every umask. A re-upload over a file chmodded 0644 gives 0600 again. The open mode argument is 0600 | 2026-10-27 |
| CHK-M7-155-flags | APP | Linux/PG | r1 `test_temp_open_flags_flush_then_commit_then_rename` | PASS | One open with `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW`, no `O_TRUNC` or `O_APPEND`. Order: fsync(temp) < COMMIT, fsync(dir) < COMMIT, COMMIT < `replace(.tmp-<id>-<sha>, policy-<id>.bit)` | 2026-10-27 |
| CHK-M7-230 (1) | APP | Linux/PG | r1 `test_finish_renames_only_full_matches_…` and 9 `test_finish_*` rows | PASS | Renamed only when the name, content hash, live row, `source_file = uploaded/policy-<id>.bit` and `source_sha256` all match (ruling (1)). Deleted: an uncommitted temp, content not matching the name, a symlink temp (the target is not followed, even when its bytes match; the target is kept), `.tmp-x`, `.tmp-`, uppercase hex, a leading zero, extra suffix, negative, id > 2^63−1, a 30-digit id (no DB error), a short hash, a deleted policy (by `source_file` and, as owner, `deleted_at` alone), a policy moved to the server folder, and a FIFO (no hang). Non-temp files are kept. A `.tmp-dir` directory is left and the rest still finish. Empty folder → (0, 0). Missing folder → nothing created, no change. No row, no entry and no catalog change. The log holds no name or content | 2026-10-27 |
| CHK-M7-155-lock | APP | Linux/PG | r1 `test_import_upload_and_finish_never_take_the_catalog_lock_themselves`, `test_the_callers_lock_is_held_at_the_temp_write_and_the_rename`, `test_a_concurrent_upload_and_delete_serialise_…`, `test_a_concurrent_upload_and_server_import_serialise`, `test_two_concurrent_uploads_of_one_policy_serialise` | PASS | Carry (a). Both functions finish while a probe holds the lock, so they take no lock themselves (the contract is documented). The probe cannot take the lock at the write or at the rename. A delete, a server-folder import and a second upload each wait (`pg_locks`, not granted) while the first upload holds the lock after the write or the commit, and run after its rename. The final disk state matches the catalog (deleted → no file; server wins → no copy; the last upload's bytes) | 2026-10-27 |
| CHK-M7-155-fileinput | CODE | Linux | r1 `test_fileinput_raises_on_each_mismatch[6]`, `test_fileinput_accepts_agreeing_hashes[2]` | PASS | Carry (b). `ValueError` when the target hash differs, when both hashes agree but not with the data, for uppercase hex, for empty data, for no data with differing hashes, and for one extra byte. Agreeing inputs and `data=None` with equal hashes are accepted | 2026-10-27 |
| CHK-M7-155 static | CODE | Linux | ruff, format, mypy | PASS | clean for the TASK-155 files | 2026-10-27 |

##### Plants (copies `scratchpad/t155/r2/<id>`, control 137/137 green; each run is the 2 files, `-n 4`)

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-357 (a) | `O_NOFOLLOW` removed | PASS (red) | 1: the flags spy. The symlink rows stay green because `O_CREAT \| O_EXCL` alone already refuses an existing link (kernel behaviour) |
| CHK-M7-357 (b) | `O_EXCL` removed | PASS (red) | 3: the flags spy, the planted regular file (overwritten), and the kept-temp re-upload |
| CHK-M7-357 (c) | both removed | PASS (red) | 5: symlink at temp (victim written), dangling symlink (target created), regular file, flags, kept temp |
| CHK-M7-358 | client name used as the stored path | PASS (red) | 48 (`hostile[1]` `/abs.bit` deselected, so the plant cannot write at `/`): 18 hostile rows, the name-of-another-policy row, the 0600 rows and every flow that stores a file |
| CHK-M7-359 (a) | temp kept on rollback (`discard` does nothing) | PASS (red) | 7: 6 before-commit fault rows and the discard log row |
| CHK-M7-359 (b) | rename before commit (in `write`) | PASS (red) | 11: the order spy, both COMMIT-failure rows, both post-commit-fault rows, the rename-guard rows |
| CHK-M7-359 (c) | `discard` deletes a planted entry (`temp` set before the open) | PASS (red) | 4: symlink, dangling, regular file, kept temp |
| CHK-M7-155-P06 | finish: `deleted_at` check removed | PASS (red) | 1: the owner-built deleted row (the app's own delete is also refused by `source_file`) |
| CHK-M7-155-P06b | finish: `source_file` check removed | PASS (red) | 1: the policy moved to the server folder |
| CHK-M7-155-P07 | `FileInput` check removed | PASS (red) | 6: every mismatch row |
| CHK-M7-155-P08 | finish follows links (`O_NOFOLLOW` dropped on read) | PASS (red) | 2: a symlink temp renamed into place |
| CHK-M7-155-P09 | temp not kept on `DatabaseUnavailable` | PASS (red) | 2: both COMMIT-failure rows |
| CHK-M7-155-P10 | mode 0644 | PASS (red) | 25 |
| CHK-M7-155-P11 | controls not replaced | PASS (red) | 20 |
| CHK-M7-155-P12 | no 255 cut | PASS (red) | 7 |
| CHK-M7-155-P14 | finish: content hash not checked | PASS (red) | 3: content ≠ name, symlink, FIFO |
| CHK-M7-155-P15 | `import_upload` takes the catalog lock itself | PASS (red) | 1 |
| CHK-M7-155-P16 | temp not fsynced | PASS (red) | 1: the order spy |

Plants: **18/18 red.** The security plants the lead named (O_NOFOLLOW, O_EXCL, client name as path, temp kept on rollback, rename before commit, finish renaming a deleted policy's file, FileInput check removed) are all red.

#### Acceptance coverage

- REQ-163 (1): CHK-M7-200 PASS. (2): CHK-M7-201 PASS. (3) and (4): CHK-M7-202 (all four rows) PASS. (5): CHK-M7-203 PASS. (6): CHK-M7-204 PASS.
- REQ-165 (1): CHK-M7-230 (1) PASS.
- The symlink at the temp path, a fault before commit, and a fault between commit and rename: CHK-M7-201 and CHK-M7-202 PASS. The COMMIT fault: ruling (2) PASS.
- Carry (a): CHK-M7-155-lock PASS. Carry (b): CHK-M7-155-fileinput PASS.

#### Findings for the reviewer (none blocking)

1. **A missing `uploaded/` folder.** Resolved by the lead ruling "A missing `bits/uploaded/` folder" and implemented in r1; see "Revision 1" below.
2. **The flags are defence in depth.** With only one of `O_EXCL` / `O_NOFOLLOW` removed, a planted symlink is still refused. Only the flags spy guards each flag on its own, so keep that test.
3. **The deleted-policy guard is two checks.** For an app-deleted policy, `source_file = deleted/<id>` already refuses the rename. `deleted_at IS NULL` matters only for an owner-built inconsistent row, and is tested that way.
4. **Environment:** `/abs.bit` (root-owned, 675 bytes, a generated test policy) was left at the file-system root by the previous tester's plant run. The safety check blocked my removal and I did not work around it. **The user should delete `/abs.bit`.** The tests no longer depend on it.

#### Revision 1 (lead ruling "A missing `bits/uploaded/` folder", `work/decisions.md`; commit c26e046)

The change: if `uploaded/` is missing, `finish_interrupted_uploads` logs one fixed warning, returns `(0, 0)` and creates nothing. `import_upload` is unchanged.

Test changes:
- The missing-folder test now asserts the ruling exactly: `(0, 0)`, the folder not created, no row, no entry, no catalog change, and exactly one warning from the `uploads` logger with no path in it.
- New `test_an_upload_with_no_uploaded_folder_fails_closed_with_no_row`: `FileNotFoundError`; nothing is created anywhere under the tmp root; no `bit_import` row, no entry, no counter and no catalog change (#98 (j)). A rejected upload still gets its normal `rejected` row.

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r1-1 | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | **138/138 passed**, 0 failed, 0 errors, 0 skipped |
| r1-2 | `pytest -n 4 tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | **202/202 passed** |
| r1-3 | `--cov=bitscan_manager.services.importer` on the 2 files | 138/138 passed; `uploads.py` 127/127 (100 %), `pipeline_record.py` 68/68 (100 %) |
| r1-static | ruff, ruff format (2 files); `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy "no issues found in 291 source files" |
| r1-plants | copies `scratchpad/t155/r3/<id>`. Control 138/138; the import path is the copy's | all 18 r0 plants re-applied: each red again, same counts. Plus 4 new plants below |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-230 (1) missing folder | APP | Linux/PG | r1-1 `test_finish_on_a_missing_folder_is_empty_logs_one_line_and_creates_nothing` | PASS | `(0, 0)`, `uploaded/` not created, one warning without a path, no row, entry or catalog change | 2026-10-27 |
| CHK-M7-155-nofolder | APP | Linux/PG | r1-1 `test_an_upload_with_no_uploaded_folder_fails_closed_with_no_row` | PASS | `FileNotFoundError`; the tmp root still holds only `bits/` (empty); no row, entry, counter or catalog change. A rejected upload gets 1 `rejected` row | 2026-10-27 |

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-155-R1a | the missing-folder branch removed (raises again) | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1b | finish creates `uploaded/` | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1c | the log line removed | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1d | `import_upload` creates `uploaded/` | PASS (red) | 1: the no-folder upload test |

Plants on r1: **22/22 red** (the 18 r0 plants plus R1a to R1d). Verdict for r1: **PASS**.

#### Revision 2 (lead ruling "Folder guard applied to the upload path", user ruling "Folder guard"; working tree after 09fcf66)

The change: `uploaded/` is opened with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` (`open_uploaded_dir`). The temp open, the fsync, the rename, the listing and the unlinks are all relative to that fd. The same applies to `delete.remove_after_commit`. If the folder is missing, a symlink or not a directory:
- the upload fails as an internal error (#98 (j)) and writes nothing through the link;
- the finish step returns `(0, 0)` with one fixed log line;
- the post-commit removal leaves the copy and logs one line.

The rows were drafted from the ruling before r2 landed. The previous run showed that r1 wrote through a symlinked `uploaded/`.

Test changes in `manager/tests/test_uploads_pg.py`:
- **Spies updated for the `dir_fd` call shapes** (the impl's 4 "spy" failures, all test-side):
  - The flags/order test now also asserts the ruling: the folder is opened with `O_DIRECTORY` and `O_NOFOLLOW`, the temp open is relative to that fd, and so are both sides of the rename.
  - The `broken` replace spies accept `**kw`.
  - `test_uploads.py`: the discard-log test patches `os.unlink` as well.
- **New tests:**
  - `test_finish_touches_nothing_when_uploaded_is_not_a_real_directory[file, dir-link, file-link, dangling-link]`;
  - `test_an_upload_writes_nothing_when_uploaded_is_not_a_real_directory[4 kinds × new, update]`;
  - `test_a_rejected_upload_still_gets_its_row_with_a_broken_folder[4]`;
  - `test_the_folder_is_checked_at_each_call_not_cached`;
  - `test_a_server_file_taking_an_uploaded_name_through_a_linked_folder_leaves_the_copy` (`move_upload`);
  - `test_a_delete_through_a_linked_folder_commits_and_leaves_the_copy`, `test_a_delete_with_a_real_folder_still_removes_the_copy`;
  - `test_a_failed_copy_removal_is_logged_by_type_and_never_raises`;
  - `test_a_folder_swapped_for_a_link_after_the_write_renames_in_the_original`.

In every broken-folder case the link target holds a committed temp (it would be renamed if the link were followed), a junk `.tmp-x` (it would be deleted) and the live `policy-<id>.bit`. The tree under the tmp root is compared before and after.

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r2-1 | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | **160/160 passed**, 0 failed, 0 errors, 0 skipped (74 + 86) |
| r2-2 (TASK-154 suites + affected) | `pytest -n 4` the 2 files + `test_import_pipeline_pg.py test_import_fuzz_pg.py test_samples_import_pg.py test_policy_delete_pg.py test_folders_pg.py test_import_store_pg.py test_catalog_lock_pg.py` | **522/522 passed** (run before the last new row; that row passed in r2-1) |
| r2-3 (coverage) | `--cov=bitscan_manager.services.importer`, the 2 files | `uploads.py` 136/136 (100 %), `pipeline_record.py` 68/68 (100 %). `delete.py`: with the delete, folder and pipeline suites, every r2 line is covered (152–153 by the new removal-error row) |
| r2-static | ruff, ruff format (2 files); `mypy --strict --config-file manager/pyproject.toml manager` | clean; "no issues found in 291 source files" |
| r2-plants | copies `scratchpad/t155/r4/<id>` (`plant_r2.py`); control 160/160, the import paths of `uploads.py` and `delete.py` are the copy's | **27/27 red** |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-155-guard-finish | APP | Linux/PG | r2-1 `test_finish_touches_nothing_…[file, dir-link, file-link, dangling-link]` | PASS | `(0, 0)`; the tree is identical (the committed temp in the link target is not renamed and `.tmp-x` is not deleted); the dangling target is not created; no row, entry or catalog change; exactly 1 warning, with no path, entry name or folder name | 2026-10-27 |
| CHK-M7-155-guard-upload | APP | Linux/PG | r2-1 `test_an_upload_writes_nothing_…[8]`, `…_rejected_upload_still_gets_its_row_…[4]`, `…_not_cached` | PASS | `OSError` for new and update; the tree is identical (nothing written, renamed or deleted in the target); no row, entry, counter or catalog change (#98 (j)); the client-name canary is not logged. A rejection still gets its `rejected` row. Swapped to a link after a good upload → refused; restored → success | 2026-10-27 |
| CHK-M7-155-guard-removal | APP | Linux/PG | r2-1 `test_a_server_file_taking_…`, `test_a_delete_through_a_linked_folder_…`, `test_a_delete_with_a_real_folder_…`, `test_a_failed_copy_removal_…` | PASS | Through a linked folder: the catalog move or delete commits, nothing raises, the copy behind the link is byte-identical, and "upload removal skipped" is logged with no path. With a real folder the copy is removed. An `EACCES` on the unlink → `upload removal failed: PermissionError`, the copy is left, the delete commits | 2026-10-27 |
| CHK-M7-155-guard-fd | APP | Linux/PG | r2-1 `test_temp_open_flags_…`, `test_a_folder_swapped_for_a_link_after_the_write_…` | PASS | The folder is opened `O_DIRECTORY \| O_NOFOLLOW`; the temp open and both rename sides use that fd. `uploaded/` swapped for a link to a decoy between commit and rename → the file lands in the original directory, and the decoy holds only `keep` | 2026-10-27 |
| CHK-M7-200 to -204, -230 (1) | APP | Linux/PG | r2-1 | PASS | every r0 and r1 row passes unchanged on r2 | 2026-10-27 |

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-155-G1 | `dir_fd` removed: the folder opened by path, following links; the temp open and the rename by path | PASS (red) | 5: the flags/fd spy, the dir-link upload (new, update), not-cached, the swap |
| CHK-M7-155-G2 | `O_DIRECTORY` dropped from the folder open | PASS (red) | 2: the flags spy, finish with a regular file (raised `NotADirectoryError` instead of `(0, 0)`) |
| CHK-M7-155-G3 | `O_NOFOLLOW` dropped from the folder open | PASS (red) | 7: the flags spy, dir-link finish, the dir-link upload (2), not-cached, both linked-folder removals |
| CHK-M7-155-G4 | finish raises instead of returning `(0, 0)` | PASS (red) | 5: missing plus the 4 kinds |
| CHK-M7-155-G5 | `remove_after_commit` opens the folder following links | PASS (red) | 2: the `move_upload` and delete rows |
| CHK-M7-155-G6 | rename by path instead of by fd | PASS (red) | 2: the fd spy, the swap |
| CHK-M7-155-R1b, R1c, R1d (on r2) | finish creates the folder; no log line; the upload creates the folder | PASS (red) | 1, 5, 4 |
| r0 plants re-applied on r2 (P01–P17, adapted to the fd call shapes) | as in r0 | PASS (red) | same counts as r0, except P03 at 58 (more flows store a file) |

Plants on r2: **27/27 red.** Verdict for r2: **PASS**. One note: under P03 the rename is relative to the fd, but an absolute client name still escapes the fd. That is why the `/abs.bit` row stays deselected in plant runs (see the `/abs.bit` note above).

#### Revision 3 (security: a symlinked bits folder was followed; lead routing of the TASK-156 r4 FAIL, option (a); commit 1be4769)

The change: `open_uploaded_dir(bits_dir)` opens the bits folder `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`, then `uploaded` relative to that fd with the same flags. Every caller uses it: the upload, the finish step and `delete.remove_after_commit`. `_Upload`'s first field is now `bits_dir`.

Test changes:
- **Changed private interface (test-side):**
  - `test_uploads.py`: the rename-guard and discard rows build `_Upload(_bits(tmp_path), …)` and look in `tmp_path/uploaded`.
  - The flags spy now requires exactly two folder opens, in order: the bits folder by path, then `"uploaded"` relative to the bits fd, both `O_DIRECTORY | O_NOFOLLOW`. It records the opens in a list, because a closed fd's number is reused (my first draft keyed them by fd and failed on that reuse; it was a test bug).
- **New tests in `test_uploads_pg.py`:**
  - `test_finish_touches_nothing_when_the_bits_folder_is_not_a_real_directory[dir-link, file, dangling-link]`;
  - `test_an_upload_writes_nothing_when_the_bits_folder_is_not_a_real_directory[3 kinds × new, update]`;
  - `test_a_delete_through_a_linked_bits_folder_commits_and_leaves_the_copy`;
  - `test_a_server_file_taking_an_uploaded_name_through_a_linked_bits_folder` (`move_upload`);
  - `test_a_bits_folder_swapped_for_a_link_after_the_write_renames_in_the_original`.

  In each case the real folder holds a live `policy-<id>.bit`, a committed temp and a junk `.tmp-x`, and the whole tree is compared before and after.

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r3-1 | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | **172/172 passed**, 0 failed, 0 errors, 0 skipped (74 + 98); re-run after the Docker restart: 172/172 |
| r3-2 (TASK-154 suites + affected) | `pytest -n 4 tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py tests/test_policy_delete_pg.py tests/test_folders_pg.py tests/test_import_store_pg.py tests/test_catalog_lock_pg.py` | **419/419 passed** (after the Docker restart). Before it, the same set plus the 2 files: 591/591 |
| r3-3 (coverage) | `--cov=bitscan_manager.services.importer`, the 2 files plus the delete, folders and pipeline suites | `uploads.py` 139/139 (100 %; also 100 % from the 2 files alone), `pipeline_record.py` 100 %, `delete.py` 71/72 (line 77 predates r3; every r3 line is covered) |
| r3-static | ruff, ruff format (2 files); `mypy --strict --config-file manager/pyproject.toml manager` | ruff clean. mypy: no error in the TASK-155 files; 1 error in `test_folders_pg.py:2507` (another tester's file, `pipeline.remove_after_commit` not re-exported) |
| r3-plants | copies `scratchpad/t155/r5/<id>` (`plant_r3.py`). Control 172/172; the import paths of `uploads.py` and `delete.py` are the copy's; `cmp` shows the copy's product and test files are identical to the committed r3 | **30/30 red** |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-155-bits-finish | APP | Linux/PG | r3-1 `test_finish_touches_nothing_when_the_bits_folder_…[3]` | PASS | `(0, 0)`; the tree is identical (the committed temp behind the link is not renamed and `.tmp-x` is not deleted); the dangling target is not created; no row, entry or catalog change; exactly 1 warning, with no path | 2026-10-28 |
| CHK-M7-155-bits-upload | APP | Linux/PG | r3-1 `test_an_upload_writes_nothing_when_the_bits_folder_…[6]` | PASS | `OSError` for new and update; the tree is identical; no row, entry, counter or catalog change (#98 (j)) | 2026-10-28 |
| CHK-M7-155-bits-removal | APP | Linux/PG | r3-1 `test_a_delete_through_a_linked_bits_folder_…`, `test_a_server_file_taking_…_linked_bits_folder` | PASS | The delete or move commits and nothing raises; `real/uploaded/` is unchanged (the copy is left); "upload removal skipped" is logged | 2026-10-28 |
| CHK-M7-155-bits-swap | APP | Linux/PG | r3-1 `test_a_bits_folder_swapped_for_a_link_after_the_write_…` | PASS | Bits swapped for a link to a decoy between commit and rename: the file lands in the original `uploaded/` through the fd, and the decoy's `uploaded/` stays empty | 2026-10-28 |
| CHK-M7-155-guard-fd (r3) | APP | Linux/PG | r3-1 `test_temp_open_flags_…` | PASS | The opens are exactly [bits by path, `uploaded` relative to the bits fd], each `O_DIRECTORY \| O_NOFOLLOW`; the temp open and both rename sides are relative to the `uploaded` fd | 2026-10-28 |
| r0 to r2 rows | APP | Linux/PG | r3-1 | PASS | every earlier row passes unchanged on r3 | 2026-10-28 |

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-155-H1 | bits folder opened without `O_NOFOLLOW` (follows a link) | PASS (red) | 6: the flags spy, bits dir-link finish, the upload (new, update), delete, `move_upload` |
| CHK-M7-155-H2 | `uploaded` opened by path (`bits_dir / "uploaded"`, the r2 shape) after the bits check | PASS (red) | 1: the flags spy (see note) |
| CHK-M7-155-H3 | `uploaded` relative open without `O_NOFOLLOW` | PASS (red) | 7: the flags spy, `uploaded/` dir-link finish, the upload (2), not-cached, delete, `move_upload` |
| CHK-M7-155-G1 to G6 (r3 shapes) | as in r2 | PASS (red) | 8, 2, 12, 8, 4, 3 (they now also turn the bits-folder rows red) |
| R1b, R1c, R1d and P01 to P17 (r3 shapes) | as before | PASS (red) | the same counts as r2, except R1c 8, P03 59 |

Plants on r3: **30/30 red.** Verdict for r3: **PASS**.

Note on H2: with the bits folder checked `O_NOFOLLOW` first, a path-based `uploaded` open is only exposed to a swap of the bits folder between the two opens, a race the tests do not force. Only the flags spy catches this plant, so it must stay.

### TASK-156

Tester: tester-m7-156, 2026-10-27. Covers REQ-159 (1), (2), (3), (6), REQ-164 (2), REQ-165 (3), and #15, #102 (b) and #103 (the folder side). Spec: TS §4.1 L515, L524, L526, L528, L532; §4.2; §4.3 L550; §4.6; SR §3.6. Rulings applied (`work/decisions.md`, 2026-10-27):
- "Crash window": a deleted policy's leftover upload is removed and reported.
- "Stray `uploaded/` files are skipped and reported": this amends case (c) and sets the lead's accepted order (server files first, then `uploaded/`, then the removed-file deletes).
- "A live upload file with a hand-edited `<PolicyName>` is skipped and reported like a stray": this ruling came from this test round. Revision 1 implements it.

File under test: `manager/bitscan_manager/services/importer/folders.py` (r1). Checks: CHK-M7-208, -209, -210 (TP-M7-16) and mutation row CHK-M7-363, plus extra plants CHK-M7-156-P*.

Tester file (no product file changed): `manager/tests/test_folders_pg.py`. It has 37 test functions (88 cases) and its own migrated server per module. An autouse fixture soft-deletes, as owner, every policy still live, because the reconcile works on the whole catalog. I wrote the tests from the spec, the TASK-156 row and the rulings first. I read the code afterwards, to find branches and plant targets.

#### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 (pre-r1 code, 85db3c9) | `pytest -n 0 tests/test_folders_pg.py` | 82/82 passed. A probe then found the edited-name churn (Findings 1), which I sent to main |
| r1 (r1 code) | `pytest -n 4 tests/test_folders_pg.py` | **88/88 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (affected set) | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py` | **360/360 passed**, 0 failed, 0 errors, 0 skipped |
| r3 (coverage) | `pytest -n 2 tests/test_folders_pg.py --cov=bitscan_manager.services.importer.folders` | 88/88 passed. `folders.py` 165/166 lines (99.4 %). Only line 233 is not covered: a file that vanishes between `discover` and `read_input` |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |
| plants control | copy at `scratchpad/t156/base` (manager, bits, docs, deploy; no venv), run from the copy's `manager/` with `PYTHONPATH` set to it. The import path printed was the copy's `folders.py` | 88/88 passed |

There were two test bugs, both mine and both fixed. (a) A first draft compared a symlink target with a newly generated file whose UUIDs differed. (b) The parse-count spy patched only `folders.prepare`, so plant P24 (a re-parse inside `import_one`) survived. The spy now patches `pipeline.prepare` too, and P24 goes red. Neither was a product failure.

#### Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-208 | APP | Linux/PG | r1 `test_discover_…`, `test_present_matches_discover`, `test_a_symlinked_uploaded_folder_…`, `test_a_missing_uploaded_folder_…`, `test_read_input_never_follows_…`, `test_hostile_entries_are_never_imported` | PASS | The folder holds `n.txt`, `.n.bit`, `A.BIT`, `a.Bit`, `a.bit.txt`, `a.bit~`, `sub/n.bit`, a directory `d.bit/`, FIFO `f.bit`, char device `c.bit`, symlinks `l.bit` (to a.bit), `passwd.bit` (to /etc/passwd), `etc.bit` (to /etc), a dangling link, `o.bit` (to a file outside), `uploaded/.tmp-…`, `uploaded/.policy-2.bit`, `uploaded/sub/…`, an `uploaded/` FIFO and an `uploaded/` symlink. `discover` returns exactly `["a.bit", "uploaded/policy-1.bit"]`. `present` agrees, including `../` and `deleted/1`. A symlinked `uploaded/` folder is not followed. `read_input` returns None for a symlink, FIFO (no block), device, directory or missing file. On PG only `a.bit` is imported, none of the 9 hostile policy names exists, and the file tree (lstat) is identical before and after | 2026-10-27 |
| CHK-M7-208 (#102 b) | APP | Linux/PG | r1 `test_unstorable_names_…`, `test_wanted_name_rules` (17), `test_upload_policy_id` (20) | PASS | The test creates files whose names are `bad\xff.bit`, `a\x01.bit`, `del\x7f.bit` and `uploaded/policy-1\xfe.bit`. Each gives exactly one warning per reconcile and no row. No log record holds the name. The next reconcile does the same. A 255-byte name imports, and a 256-byte one is refused. That limit is in bytes: 125×`é`+`a.bit` passes and 126×`é`+`.bit` fails. Cc controls (TAB, LF, DEL, C1 U+0085) are refused, and U+202E (Cf) is allowed. Ids: no leading zeros, ASCII digits only, ≤ 2^63−1 | 2026-10-27 |
| CHK-M7-208 (oversize) | APP | Linux/PG | r1 `test_read_input_oversize_…`, `test_oversize_server_file_…` | PASS | Exactly 5 MiB is read as data. MAX+1 bytes and MAX+3 MiB give `data=None`, with the hash taken over the whole file. On PG this is one `rejected` `auto` row: BIT001 only, `file_sha256` = the whole-file hash, `imported_by` NULL, catalog unchanged | 2026-10-27 |
| CHK-M7-209 (REQ-159 1) | APP | Linux/PG | r1 `test_req159_1_…` | PASS | `b.bit` edited to `a.bit`'s name gives rows `[a.bit skipped, b.bit rejected]`, with BIT007 naming `a.bit`. Both policies and the catalog checksums are unchanged | 2026-10-27 |
| CHK-M7-209 (REQ-159 2) | APP | Linux/PG | r1 `test_req159_2_…` | PASS | `a.bit` renamed to `c.bit` gives one `success` row for `c.bit` with the same id. `source_file` is `c.bit`, the version is the same, and the members are the same. The audit entries are `policy.import` then `policy.move {from a.bit, to c.bit}`. There is no delete (`deleted == ()`), and the only alert is `policy_imported` +1 | 2026-10-27 |
| CHK-M7-209 (REQ-159 3) | APP | Linux/PG | r1 `test_req159_3_…`, `test_server_files_are_reconciled_before_uploaded_files` | PASS | A server file named like an uploaded policy gives one row (`x.bit success`) and the copy never reaches the pipeline. The policy moves to `x.bit` and `uploaded/policy-<id>.bit` is removed. The audit entries are `policy.import` and `policy.move`. `strays`, `renamed` and `deleted` are all empty. A later upload of that name raises `PolicyManagedOnServer`, and the next reconcile is one `skipped`. Server files always come before `uploaded/` | 2026-10-27 |
| CHK-M7-209 (REQ-159 6, #15) | APP | Linux/PG | r1 `test_req159_6_…` (4 pairs), `test_15_a_live_policys_file_goes_before_a_new_file` | PASS | Of two new files with one name, the byte-order winner imports and the other gets BIT007 naming the winner. Pairs: `a`/`b`, `B`/`a` (raw bytes, not casefold), `a`/`a0`, `z`/`é`. When live `z.bit` renames X to Y in place and new `a.bit` takes X, `z.bit` goes first: rows `[z.bit success, a.bit success]`, Y keeps the old id, and X is new at `a.bit` | 2026-10-27 |
| CHK-M7-210 | APP | Linux/PG | r1 `test_an_unchanged_folder_…`, `test_three_reconciles_and_a_restart_cause_no_churn` | PASS | For 3 server files and 1 live upload, the rows are exactly 4 `skipped` `auto` rows (0/0/0). There is no audit entry and no counter change, the catalog checksums and the file tree are the same, and every result list is empty. Mixed folder (adds a BIT007 loser, a stray and a leftover): after run 1, three runs and a restart (new pool) are identical. The catalog is the same, the rows are `skipped` plus the loser's `rejected` (retried per TS §4.1 L532), and the only entry is `policy.import_rejected` | 2026-10-27 |
| REQ-165 (3) | APP | Linux/PG | r1 `test_new_server_files_…`, `test_a_removed_server_file_…`, `test_a_removed_upload_…`, `test_a_server_file_replaced_by_a_symlink_…`, `test_a_changed_server_file_…` | PASS | New files give `success` `auto` rows with `imported_by` NULL, actor `system` and v1. A removed `a.bit` gives `deleted_at` = clock and `source_file` `deleted/<id>`, keeps the row and the name, and retires both plugins. The audit entry is `policy.delete` (actor `system`, reason `file removed`, `source_file a.bit`), with `policy_deleted` +1. An added `c.bit` imports in the same run. A removed upload is deleted the same way. A server file replaced by a symlink counts as removed, and its target is untouched. A changed file gives v2 with 1 updated | 2026-10-27 |
| (i) | APP | Linux/PG | r1 `test_i_…` | PASS | An unchanged live upload gives one `skipped` row with no audit entry and no alert. Changed, it gives `success` v2, with `source_sha256` = the new hash, the file kept and one `policy.import` | 2026-10-27 |
| (ii) leftover | APP | Linux/PG | r1 `test_ii_…[same, other, names-live, garbage]` | PASS | The test deletes through `delete_policy` and then restores the file (the crash window). Then the file is removed and never read (read spy). There is no row, no entry and no counter change, the catalog is unchanged and the policy row is identical (still deleted). `leftovers == (Difference(path, "leftover of an interrupted delete"),)` with one log line. The next run reports nothing | 2026-10-27 |
| (iii) | APP | Linux/PG | r1 `test_iii_…`, `test_classify_upload_cases` | PASS | A live policy's file with another hash gives `success`, the file stays and `deleted_at` stays NULL. `classify_upload` returns `live`, `leftover`, `stray` (a server policy's copy), `stray` (leading zero, no policy, 2^63−1, 2^63, `x.bit`) | 2026-10-27 |
| (iv) | APP | Linux/PG | r1 `test_iv_…`, `test_spy_contract` | PASS | Spies on `folders.import_one` and `store_decide.decide` over a mixed folder show that no target is `Target("server", "uploaded/…")`. Exactly the 2 live uploads (as `Target("upload", None, sha)`) and the 2 server files reach the pipeline. The 4 strays are reported and the leftover is reported | 2026-10-27 |
| (c) strays | APP | Linux/PG | r1 `test_c_…[new-name, no-policy, leading-zero, over-bigserial, server-copy, live-name]` | PASS | Over 2 runs: `strays == (path,)`, the file is never read, there is no row for it, no audit entry and no counter change. The catalog checksums are the same, the tree is byte-identical and there is one log line without the name. The server policy and the live policy keep their `source_file` | 2026-10-27 |
| r1 edited name | APP | Linux/PG | r1 `test_a_live_upload_with_an_edited_name_…[new-name, other-upload, server-name, new-name-with-bit102]` | PASS | Over 3 runs: `renamed == (path,)`, there is no row, entry or alert for it, and the file is byte-identical. There is one fixed-words log line (no name, no path), and each file is parsed once (3 parses). The policy row is identical (not deleted). The new name never exists, the server policy is unchanged and there is no `policy.import_refused`. The changed later upload still imports (`success`, then `skipped`) | 2026-10-27 |
| r1 no valid name | APP | Linux/PG | r1 `test_a_live_upload_with_no_valid_name_…[unparsable, oversize, bad-name]` | PASS | Over 3 runs: one `rejected` row with the file's hash and one `policy.import_rejected`. `renamed`, `strays` and `deleted` are empty, the catalog and the policy row are unchanged, and the file is kept | 2026-10-27 |
| carry (a) lock | APP | Linux/PG | r1 `test_the_lock_spans_every_import_…` | PASS | The lock is held at each of the 3 imports and still held when `reconcile` returns. A concurrent `delete_policy` waits (still alive after 1 s) and completes after the reconcile's block ends. Then the lock is free | 2026-10-27 |
| carry (c) temp | APP | Linux/PG | r1 `test_reconcile_leaves_temp_files_and_writes_no_file` | PASS | Does not apply (no temp file is written, as the impl report says). A `.tmp-<id>-<sha>` is left byte-identical, and an unchanged reconcile leaves the tree identical | 2026-10-27 |
| logs | APP | Linux/PG | r1 `test_reconcile_never_logs_file_content_or_names` | PASS | A canary in file names, a policy name, an Execute, a malformed file and a symlink appears in no log record (message, args or `__dict__`) over 2 runs | 2026-10-27 |

##### Plants (copy `scratchpad/t156/<id>` of the r1 base; control 88/88 green; each run is `test_folders_pg.py`, `-n 4`): 32/32 red

| Check | Plant | Red |
| --- | --- | --- |
| CHK-M7-363 / P01 | `entry.is_file(follow_symlinks=True)` | 1 (discover) |
| P01b | `present` uses `os.stat` | 2 (present, symlink-replaced file) |
| P01c | O_NOFOLLOW dropped | 1 (read_input) |
| P01d | `_real_dir` follows a symlinked `uploaded/` | 1 |
| P02 | stray falls through to import | 9 |
| P03 | leftover imported (revived) | 6 |
| P03b | leftover removed but not reported | 6 |
| P03c | leftover not removed | 5 |
| P04 | deletes before imports | 2 (REQ-159 (2) and the removed file) |
| P05 | `Mode.MANUAL` (skips become `success`) | 24 |
| P06a | #15 byte order reversed | 10 |
| P06b | existing-file-first dropped | 1 (`test_15_…`) |
| P06c | casefold order | 1 (`B.bit`/`a.bit`) |
| P07 | uploads before server files | 7 |
| P08 | Cc check dropped | 6 |
| P08b | length in characters, not bytes | 1 |
| P09 | leading zeros accepted | 2 |
| P10 | BIGSERIAL cap dropped | 2 (unit only; see Findings 3) |
| P11 | hidden files kept | 5 |
| P12 | case-insensitive `.bit` | 4 |
| P14 | a server policy's copy treated as a leftover (removed) | 5 |
| P14b | live treated as leftover | 27 |
| P15 | uploads read as server targets | 23 |
| P16 | reconcile releases the catalog lock | 1 |
| P17 | unstorable name written to the log | 1 |
| P18 | stray removed | 8 |
| P19 | O_NONBLOCK dropped | red by hang: the FIFO test is killed at 30 s (exit 124) |
| P20 | fstat regular-file check dropped | 1 (char device read) |
| P21 | stray not reported | 9 |
| P22 (r1) | edited-name check disabled | 4 |
| P23 (r1) | edited name not listed in `renamed` | 4 |
| P24 (r1) | `prepared` not passed (parsed twice) | 4 |

The pre-r1 plant P13 (refused aborts the reconcile) is retired, because `refused` no longer exists. The 13 plants P01 to P06c were also red on the pre-r1 code.

#### Findings for the reviewer (none blocking)

1. Fixed in r1. The pre-r1 code sent a live upload with an edited `<PolicyName>` through the pipeline. With a new name, each reconcile inserted or revived that policy and then deleted it: versions 1, 2, 3, with an import and a delete alert every time. With another uploaded policy's name, each reconcile flip-flopped that policy (versions 3, 5, 7). Main got the user's ruling. Those cases are now PASS criteria over 3 runs.
2. A missing or symlinked `uploaded/` folder makes `discover` find no uploads, so `delete_removed` soft-deletes every live uploaded policy. This follows from the spec ("policies whose files disappeared are deleted"; symlinks are never followed), but a mis-mounted folder would delete them all, with an alert for each. It is not asserted here. The reviewer or TASK-158 may want a guard or an explicit ruling.
3. P10: without the BIGSERIAL cap, PostgreSQL compares the out-of-range id as numeric and finds no row, so the PG path still gives `stray`. Only the unit test catches it. That is harmless.
4. A BIT007 loser, or any rejected folder file, writes a `rejected` row and a `policy.import_rejected` alert at every reconcile. TS §4.1 L532 says to retry, and #103 counts the rejected row. Expected, but noisy at every start-up.
5. `folders.import_one`, `folders.prepare` and `pipeline.store_decide` are re-exports that the spies patch. The tests use `pipeline.import_one` and `pipeline.prepare` for the real calls, so mypy is clean.

#### Revision 2 (tester-m7-156r2, 2026-10-27): folder guard: PASS

Ruling: `work/decisions.md`, 2026-10-27, user "Folder guard" and lead "Folder guard details" (1). The code under test is `folders.py` at HEAD 09fcf66 (r2: `unreadable`, `BITS_ROOT`, `ReconcileResult.unreadable_folders`, the guard in `reconcile` and `delete_removed`, and `discover` returning `[]` for a bits folder that is not a real directory). This revision closes r1 Finding 2. I wrote the expected values from the two rulings first. I read the code afterwards, only to choose plant targets. No product file changed.

File changed: `manager/tests/test_folders_pg.py`. It gains 7 test functions (23 cases), so it now has 44 functions (111 cases).

##### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| baseline (HEAD, before the new tests) | `pytest -n 4 tests/test_folders_pg.py` | 88/88 passed |
| r2 file | `pytest -n 4 tests/test_folders_pg.py` | **111/111 passed**, 0 failed, 0 errors, 0 skipped (r1's 88 are among them) |
| r2 affected set | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py` | **383/383 passed**, 0 failed, 0 errors, 0 skipped |
| coverage | `pytest -n 2 tests/test_folders_pg.py --cov=bitscan_manager.services.importer.folders` | 111/111 passed. `folders.py` 179/180 lines (99.4 %). Only line 256 is missed: a file that vanishes between `discover` and `read_input`, the same branch as in r1 |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |
| plants control | copy at `scratchpad/t156r2/base` (rebuilt from the current tree). The import path printed was the copy's `folders.py` | 111/111 passed |

`test_uploads*.py` were not run. They belong to TASK-155 r2, which is in progress, and `folders.py` does not import `uploads.py`. The `upload()` helper here goes through `uploads.import_upload` and works at HEAD.

##### Report rows

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| r2 labels (no DB) | CODE | Linux | `test_unreadable_labels` (10) | PASS | `unreadable()` returns `()` for real folders and for real empty ones. It returns `("uploaded/",)` when `uploaded/` is missing, a symlink to a real folder, a dangling symlink or a regular file. It returns `("./", "uploaded/")` when the bits folder is missing, a symlink to a real folder, a file, or a symlink to a folder with no `uploaded/`. In every case `discover` returns only the files of readable folders (`[]` through a symlinked bits folder), and the whole tmp tree (lstat) is unchanged | 2026-10-27 |
| r2 `uploaded/` unreadable | APP | Linux/PG | `test_an_unreadable_uploaded_folder_is_left_alone_and_the_server_folder_reconciled[missing, symlink, file]` | PASS | Setup: server S and R, live upload U, deleted upload D. Then `uploaded/` is broken. Its real folder (the symlink target) holds U's file changed, D's leftover and a stray. `r.bit` is removed and `n.bit` added. Over 3 reconciles: `unreadable_folders == ("uploaded/",)`; there is no `bit_import` row for any `uploaded/` path, and `read_input` is never called for one (spy). Leftovers, strays and renamed are empty. U's and D's rows (incl. xmin) and member states are identical, and the real folder's tree is byte-identical. There is exactly one guard log line per run, ending in the label, identical across runs, with no tmp path, `/bits` or `policy-` in any record. Run 1 reconciles the server folder normally: `n.bit success`, `s.bit skipped`, R deleted (`deleted_at` = clock), `policy.import` and `policy.delete`, +1/+1 alerts. Runs 2 and 3 give only skips, no audit entries, no counter change and the same catalog. Recovery: `()`, U `success` with the new hash, D reported as a leftover, the stray reported, no delete | 2026-10-27 |
| r2 bits folder unreadable | APP | Linux/PG | `test_an_unreadable_bits_folder_makes_both_folders_unreadable[missing, symlink, file]` | PASS | The real folder (the symlink target) holds `s.bit` changed, `r.bit` removed, a new `n.bit`, U's file changed, D's leftover and a stray. Over 3 reconciles: `("./", "uploaded/")`, two guard lines per run, no rows, no audit entries, no counter change, same catalog, and empty outcomes, deleted, leftovers, strays and renamed. S, R, U and D are identical, the target tree is byte-identical, `read_input` is never called, and `discover(bits) == []`. Recovery: `()`, R deleted, `n.bit` and `s.bit` `success`, U's new hash, D reported as a leftover | 2026-10-27 |
| r2 both together | APP | Linux/PG | `test_both_folders_unreadable_together[missing, symlink, file]` | PASS | A symlinked bits folder whose own `uploaded/` is missing, a symlink or a file, with `s.bit` also removed in the target. Over 2 runs: `("./", "uploaded/")`, two lines, no rows or entries, no deletes, same catalog, the policies identical and the whole tmp tree unchanged | 2026-10-27 |
| r2 real empty folder | APP | Linux/PG | `test_a_real_empty_folder_still_deletes_its_policies[uploaded, server, both]` | PASS | Empty real `uploaded/` (`listdir == []`), a bits folder holding only `uploaded/`, or both. Run 1: `()`, no guard line, exactly the folder's policies soft-deleted (`deleted_at` = clock, `deleted/<id>`, members retired, `policy.delete` with reason `file removed`, `policy_deleted` +n), the other folder's policies kept. Runs 2 and 3: nothing deleted, no entries, no counter change, same catalog | 2026-10-27 |
| r2 `delete_removed` direct | APP | Linux/PG | `test_delete_removed_skips_an_unreadable_folder_but_not_an_empty_one` | PASS | With `uploaded/` missing it returns only R (the server folder still works) and U stays live. With `uploaded/` real and empty it returns U. With the bits folder a symlink and `s.bit` gone in the target it returns `()` and S stays live | 2026-10-27 |

##### Plants (copy `scratchpad/t156r2/<id>` of the r2 base; control 111/111 green; each run is `test_folders_pg.py`, `-n 4`): 10/10 red

| Plant | Change | Red |
| --- | --- | --- |
| R1 | guard skipped in `reconcile` (`blind = ()`) | 9 |
| R2 | guard skipped in `delete_removed` (`blind = ()`) | 10 |
| R3 | a symlinked bits folder lists only `"./"` | 6 |
| R3b | any unreadable bits folder lists only `"./"` | 10 |
| R4 | label missing from the result (last field `()`) | 9 |
| R5 | `_real_dir` uses `stat` (follows links) | 10 |
| R6 | a real empty folder treated as unreadable | 5 (labels `both-empty`, empty `[uploaded]` and `[both]`, the `delete_removed` test, r1's removed-upload test) |
| R7 | `discover`'s bits-folder check dropped (reads `uploaded/` through a symlinked bits folder) | 2 |
| R8 | guard log line also carries `bits_dir` | 9 |
| R9 | guard log line dropped | 9 |

##### Findings for the reviewer (none blocking)

1. r1 Finding 2 (a mis-mounted `uploaded/` deletes every uploaded policy) is fixed and is now a PASS criterion.
2. Plant R6 does not turn `test_a_real_empty_folder_still_deletes_its_policies[server]` red. A bits folder always holds `uploaded/`, so it is never literally empty. The case still covers "a bits folder with no `.bit` file is readable".
3. On recovery, a folder that comes back with changed content is imported normally (a `success` row and an alert), and a leftover inside it is removed then. That is the expected behaviour, not churn: the guard only defers the reconcile.
4. Through a symlinked bits folder, `present(bits, "s.bit")` still resolves the link, because `lstat` does not follow only the last path component. This is harmless, because `delete_removed` checks `unreadable` first (plant R2 shows the guard is what protects), but TASK-157 should keep that order.
5. The guard log words are not pinned. The tests check one line per folder, ending in its label, identical across runs, with no path.

#### Revision 3 (tester-m7-156r2, 2026-10-27): per-row folder check and no-follow reads: PASS

Source: review `work/reviews/TASK-156.md` (finding 1 should-fix, nit 2), routed as r3 by `work/decisions.md` ("Joint review ... routed as TASK-156 revision 3", "TASK-156 r3 built ... size accepted"). Code under test: `folders.py` at HEAD 22e4fda; impl report "Revision 3". No product file changed. Folders are swapped at fixed points by wrapping the module's own calls (`folders.delete_in_tx`, `folders.discover`, `folders._open_folder` and `folders.read_input`). There are no sleeps. The file passed 3 runs in a row with no flakes.

File changed: `manager/tests/test_folders_pg.py`, with 10 new test functions (19 cases). It now has 54 functions and 130 cases.

##### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r2 tests on r3 code | `pytest -n 4 tests/test_folders_pg.py` | 111/111 passed |
| r3 file | `pytest -n 4 tests/test_folders_pg.py` | **130/130 passed**, 0 failed, 0 errors, 0 skipped (3 runs in a row while I wrote the tests) |
| r3 affected set | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py tests/test_uploads.py tests/test_uploads_pg.py` | **562/562 passed**, 0 failed, 0 errors, 0 skipped |
| coverage | `pytest -n 2 tests/test_folders_pg.py --cov=bitscan_manager.services.importer.folders` | 130/130 passed. `folders.py` **219/219 lines (100 %)** |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |
| plants control | copy at `scratchpad/t156r3/base` (from 22e4fda, with the final test file). The import path printed was the copy's `folders.py` | 130/130 passed |

There were two test bugs, both mine and both fixed:
- A draft forgot that `r.bit` still existed in one setup.
- My log counter matched every message containing "unreadable". It now counts only the guard line. See Finding 1.

##### Report rows

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| r3 mid-loop, `uploaded/` | APP | Linux/PG | `test_uploaded_folder_broken_after_the_first_delete_deletes_no_more[missing, symlink]` | PASS | Setup: 3 live uploads and 3 server policies. Every upload file is removed, plus `k0.bit`. A wrapped `delete_in_tx` breaks `uploaded/` right after the first upload's delete. For "symlink", the link points to an empty real folder. Exactly 2 deletes happen: `k0` and that one upload, matching the wrapper's calls. The other 2 uploads keep `deleted_at` NULL and get no `policy.delete`. The other server policies stay live. The result is `("uploaded/",)` with one guard line and no path. The link target is untouched. The next reconcile deletes nothing more and still reports `("uploaded/",)` | 2026-10-27 |
| r3 mid-loop, bits folder | APP | Linux/PG | `test_bits_folder_broken_after_the_first_delete_deletes_no_more[missing, symlink]` | PASS | Setup: 2 server and 2 uploaded policies, with every file removed. The bits folder is broken after the first delete. "symlink" points to a real folder with an empty `uploaded/`. Exactly 1 delete happens, the first call. The 3 others stay live, with one `policy.delete` entry in total. The result is `("./", "uploaded/")` with two guard lines. The target is unchanged | 2026-10-27 |
| r3 swap after `discover`, `uploaded/` | APP | Linux/PG | `test_uploaded_folder_swapped_after_discover_is_not_read_or_deleted[missing, symlink]` | PASS | A wrapped `discover` returns its list, then `uploaded/` is removed or swapped for a link to a folder holding a changed copy of U. There is no `uploaded/` row, and U's row (including xmin) is identical, so nothing was read through the link. The server folder is still reconciled: `n.bit success`, `r.bit` and `s.bit skipped`. The result is `("uploaded/",)` with one guard line. Nothing is deleted, and the link target is unchanged | 2026-10-27 |
| r3 swap after `discover`, bits folder | APP | Linux/PG | `test_bits_folder_swapped_after_discover_is_not_read_or_deleted[missing, symlink]`, `test_a_folder_swapped_after_discover_is_reported_by_the_read[missing, symlink]` | PASS | A changed `s.bit` (it would become v2) is discovered, then the bits folder goes or turns into a link. The result has no rows, no audit entries, no counter change, the same catalog, and is `("./", "uploaded/")`. Outcomes, deletes, strays and renamed are empty. S, R, U and D are identical, and the target is unchanged. With no live policy anywhere, the failed read alone reports both labels | 2026-10-27 |
| r3 read through the folder handle | APP | Linux/PG | `test_a_file_is_read_through_its_folder_handle_not_its_path` | PASS | The bits folder is swapped for a link to a changed `s.bit` right after `read_input` opens the folder handle, using a wrapped `_open_folder` armed only for `s.bit`. The file comes from the real folder: `s.bit skipped`, no `success` row, the same version and hash. The result is `("./", "uploaded/")`. Nothing is deleted (the removed `r.bit` keeps its policy), and the link target is unchanged | 2026-10-27 |
| r3 finding 4 | CODE | Linux | `test_present_and_read_input_never_resolve_a_symlinked_bits_folder` | PASS | Through a symlinked bits folder, `present` is False and `read_input` is None for both `a.bit` and `uploaded/policy-1.bit`. Through the real folder both are found with their data. A symlinked `uploaded/` inside a real bits folder gives the same | 2026-10-27 |
| r3 other stat errors | APP | Linux/PG | `test_a_stat_error_other_than_not_found_is_unreadable_not_absent` | PASS | U's file is removed and `os.stat` raises `PermissionError` for that name. Running as root, EACCES can only be injected. `present` is False, but nothing is deleted. The result is `("uploaded/",)` with one guard line | 2026-10-27 |
| r3 report without policies | APP | Linux/PG | `test_an_unreadable_folder_with_no_policy_in_it_is_still_reported[uploaded, bits × missing, symlink, file]` | PASS | With an empty catalog, the unreadable folder is still listed over 2 runs, with one guard line per label. `n.bit` is imported only when the bits folder is readable | 2026-10-27 |
| r2 regression | APP | Linux/PG | the 23 r2 cases | PASS | All unchanged on r3 | 2026-10-27 |

##### Plants (copy `scratchpad/t156r3/<id>` of the r3 base; control 130/130; `-n 4`): 20/20 red

| Plant | Change | Red |
| --- | --- | --- |
| R1 | start-of-reconcile guard skipped | 6 (only the new "no policy in it" cases; the delete loop's own marking masked it until they were added) |
| R2 | an unreadable row is deleted (`state == "present"` skip only) | 20 |
| R3 | a symlinked bits folder lists only "./" | 4 |
| R3b | an unreadable bits folder lists only "./" | 9 |
| R4 | label missing from the result | 27 |
| R5 | `_real_dir` uses `stat` | 6 |
| R6 | a real empty `uploaded/` treated as unreadable | 7 |
| R7 | `discover`'s bits-folder check dropped | 2 |
| R8 | guard line carries `bits_dir` | 25 |
| R9 | guard line dropped | 26 |
| S1 | per-row check replaced by a snapshot before the loop | 4 (the mid-loop tests) |
| S2 | "absent" decided by path `lstat`, without the no-follow fd | 18 |
| S2b | a missing folder treated as "absent" | 7 |
| S3 | `read_input` opens by path after the folder check | 1 (the folder-handle test) |
| S3b | `read_input` by path with no folder check | 4 |
| S4 | `_open_folder` follows a link at the bits folder | 13 |
| S4b | `_open_folder` follows a link at `uploaded/` | 7 |
| S5 | any stat error counts as "absent" | 1 |
| S6 | a folder swapped after `discover` not marked by the read path | 2 (only once the "reported by the read" test was added) |
| S7 | an unreadable row not marked in the delete loop | 5 |

##### Findings for the reviewer (none blocking)

1. **Extra log lines.** When a folder is swapped after `discover`, there is still exactly one guard line ("folder unreadable, not reconciled: <label>") per folder. On top of it, `read_input` adds one fixed-words line per discovered file in that folder: "folder file not read: its folder is unreadable" (3 files gave 3 lines). These lines hold no path. The ruling says "one log line" per folder; main or the reviewer should decide whether the per-file lines are acceptable. The tests count only the guard line.
2. **Leftover misreport.** A leftover discovered before `uploaded/` is swapped for a link is classified from the database alone. `remove_leftover` then calls `remove_after_commit`, which refuses through the unreadable folder (TASK-155 r2 handle, log "upload removal skipped: uploaded folder unreadable"). Nothing in the link target or the real folder was touched (throwaway probe in `scratchpad/t156r3/probe`). But the reconcile still logs "removed a leftover of an interrupted delete: uploaded/policy-<id>.bit" and lists it in `leftovers`, though the file was not removed. Listing it for #103 is fine, because the file really is still there; the "removed" log is not true. This is a narrow race window, and nothing is followed or deleted. It is not asserted.
3. Plants R1 and S6 first survived because the delete loop marks a folder whenever it still holds a live policy, so the start check and the read check overlap. The two new empty-catalog tests now pin each one separately.
4. `_state`'s "unreadable on any stat error except ENOENT" path can only be reached by injection here, because the tests run as root.

#### Revision 4 (tester-m7-156r2, 2026-10-27): r3 findings fixed; a follow-through-link removal found and fixed in TASK-155 r3: PASS

Source: `work/decisions.md`, "TASK-156 r3 TEST PASS ... revision 4" (my r3 findings 1 and 2) and the row routing TASK-155 r3. Code under test: `folders.py` at 1b0aff3 (r4). The final verdict is on HEAD 1be4769 (TASK-155 r3: `open_uploaded_dir` opens the bits folder no-follow, then `uploaded` relative to it). No product file changed.

File changed: `manager/tests/test_folders_pg.py`. It gains 7 test functions (14 cases), for 61 functions and 144 cases. Folders are swapped at fixed points by wrapping `folders.discover`, `folders.delete_in_tx`, `pipeline.remove_after_commit` and `os.open` / `os.unlink` for one name. There are no sleeps.

##### Round 1 (1b0aff3): FAIL, a security defect outside `folders.py`

| Test | Expected | Actual at 1b0aff3 |
| --- | --- | --- |
| `test_a_leftover_whose_folder_is_swapped_after_discover_is_not_reported_removed[bits-symlink-with-copy]` | After `discover`, the bits folder becomes a link to `evil/`, which holds `uploaded/policy-<D>.bit`. That file stays | It is deleted. `remove_leftover` → `remove_after_commit` → `open_uploaded_dir(bits_dir / "uploaded")`, and `O_NOFOLLOW` covers only the last component |
| `test_a_bits_folder_swapped_before_an_upload_copy_is_removed_is_not_followed` | U's file is removed by hand, so U is deleted. The bits folder becomes a link right after U's `delete_in_tx`, and `evil/uploaded/policy-<U>.bit` stays | It is deleted (the same helper, called from `_delete_removed`) |
| `test_req159_3_move_does_not_remove_the_copy_through_a_swapped_bits_folder` (added at main's request) | In a REQ-159 (3) server-wins move, the bits folder becomes a link just before the pipeline removes the uploaded copy. The link target's file stays, and the real copy is left in place | It is deleted (the same helper, called from `pipeline`) |

Diagnosis: "Folder guard details" (1) says a symlinked bits folder makes `uploaded/` unreadable, because it would be reached through the link. The helper (TASK-155 code) followed it. r4's own `_state` check in `remove_leftover` runs only after the removal, so it reports the leftover correctly (`leftovers == ()`, both folders marked) but cannot prevent the removal. My r3 tests had no case that swaps the bits folder before a removal, so r3 missed this. main routed it as TASK-155 r3, option (a). The failing evidence came from a clean `git archive 1b0aff3` copy (`scratchpad/t156r4/base`): 3 failed, 141 passed.

##### Round 2 (HEAD 1be4769, TASK-155 r3 landed)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| file | `pytest -n 4 tests/test_folders_pg.py` (twice) | **144/144 passed** both times, 0 failed, 0 errors, 0 skipped |
| affected set | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py tests/test_uploads.py tests/test_uploads_pg.py` | **588/588 passed**, 0 failed, 0 errors, 0 skipped |
| coverage | `--cov=bitscan_manager.services.importer.folders` | 144/144 passed. `folders.py` **223/223 lines (100 %)** |
| re-run after a test fix | `pytest tests/test_folders_pg.py::test_req159_3_move_does_not_remove_the_copy_through_a_swapped_bits_folder` | 1/1 passed. mypy had flagged `pipeline.remove_after_commit` as not re-exported; the test now takes the real function from `delete` (the same object) |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |

##### Report rows

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| r4 (1) no per-file line | APP | Linux/PG | `test_a_folder_swapped_after_discover_logs_only_the_guard_line[uploaded, bits × missing, symlink]` | PASS | Setup: 3 changed server files and 3 changed live uploads, all discovered, then one folder goes. The module's only WARNING lines are the guard lines, one per label, and none says "not read". Nothing is deleted. With `uploaded/` gone the 3 server files are imported and the uploads are unchanged; with the bits folder gone there are no rows and all 6 policies are identical | 2026-10-27 |
| r4 (1) a readable folder still logs | APP | Linux/PG | `test_a_read_error_inside_a_readable_folder_still_logs_its_type` | PASS | `os.open` of `s.bit` raises `PermissionError`. The module's warnings are exactly `["folder file not read: PermissionError"]`. The result is `()`, there is no `s.bit` row, and S is identical | 2026-10-27 |
| r4 (2) leftover, folder swapped | APP | Linux/PG | `test_a_leftover_whose_folder_is_swapped_after_discover_is_not_reported_removed[missing, symlink-with-copy, symlink-empty, bits-symlink-with-copy]` | PASS (the bits case only after TASK-155 r3) | `leftovers == ()` and the folder is marked, with one guard line per label and no "removed a leftover" line. S, R, U and D are identical, with no audit entry and no delete. The link target is byte-identical, and the real leftover is still there | 2026-10-27 |
| r4 (2) leftover removal refused | APP | Linux/PG | `test_a_leftover_that_cannot_be_removed_is_retried_and_reported_once_gone[no-op, unlink-raises]` | PASS | Over 2 runs: `leftovers == ()`, `("uploaded/",)`, one guard line, no "removed" line, the file kept, D identical and no row. U's hand-removed file still deletes U, because the folder is real and the mark only reports. Once removal works: the leftover is listed once with one "removed" line and the file is gone; the next run lists nothing | 2026-10-27 |
| r4 (2) direct call | CODE | Linux | `test_remove_leftover_returns_a_difference_only_when_the_file_is_gone` | PASS | It returns a `Difference` once the file is gone. It returns None when the removal is a no-op (file kept), when `uploaded/` is a symlink (target kept), and when `uploaded/` is missing | 2026-10-27 |
| no removal through a symlinked bits folder | APP | Linux/PG | `test_a_bits_folder_swapped_before_an_upload_copy_is_removed_is_not_followed`, `test_req159_3_move_does_not_remove_the_copy_through_a_swapped_bits_folder`, leftover `[bits-symlink-with-copy]` | FAIL at 1b0aff3, PASS at 1be4769 | See Round 1. At 1be4769 every link target is byte-identical. The move still commits (`x.bit`, `policy.import` + `policy.move`), the real copy is left for #103, and the result is `("./", "uploaded/")` | 2026-10-27 |
| regression | APP | Linux/PG | r1 to r3 cases (130) | PASS | unchanged | 2026-10-27 |

##### Plants (copy `scratchpad/t156r4/<id>` of `git archive 1b0aff3` plus the final tests; the 3 TASK-155-dependent cases deselected; control 141/141): 27/27 red

The r2 and r3 plants, re-anchored to r4 (S3b's anchor changed with the dropped log line), are all red: R1 6, R2 27, R3 4, R3b 9, R4 36, R5 6, R6 14, R7 2, R8 34, R9 35, S1 4, S2 25, S2b 11, S3 2, S3b 10, S4 14, S4b 10, S5 1, S6 2, S7 5. The new r4 plants:

| Plant | Change | Red |
| --- | --- | --- |
| T1 | `remove_leftover`'s `_state` check dropped | 6 |
| T2 | check by path (`os.path.lexists`) instead of the no-follow handle | 3 |
| T3 | a refused leftover not marked | 2 |
| T4 | a refused leftover still listed | 5 |
| T5 | the per-file "its folder is unreadable" line restored | 4 |
| T6 | the per-file read-error line in a readable folder dropped | 1 |
| T7 | "removed a leftover" logged before the check | 9 |

##### Findings for the reviewer (none blocking)

1. A real `uploaded/` whose leftover could not be removed is listed in `unreadable_folders`, yet its absent files still delete their policies (the impl report's intent: the mark only reports). This fits the ruling, which defines "unreadable" as missing, a symlink or not a directory. TASK-158's alert text should not suggest the folder is missing.
2. A regular file replaced by a FIFO or a directory counts as "absent" in `_state`, so after a refused removal of such an entry the leftover would still be reported as removed. Not reachable through the manager. Not tested.

### TASK-168

Tester: tester-m7-web, 2026-10-27. REQ-183 (1), (2) and the problem-mapping half; #98 (e), TS §4.1 L522 (`policy_managed_on_server`); #102 (d) and the lead's 503 rule (`work/decisions.md` 2026-10-27, "Web: how the UI shows the #102 start-up 503"); TS §6.3 L1133. Files under test: `web/src/api/schema.d.ts` (generated), `web/src/app/problems.ts`. Tests were written from the decision row, the task row and REQ-183 first. The code was read afterwards only to find the Retry-After parse bounds. **First pass only:** the TASK-162 to TASK-164 routes are not in `manager/openapi.json` yet, so G16 and the path checks must run again at the second pass.

#### Tests added

- `web/src/app/problems.test.ts`: 28 new cases in two `CHK-M7-310 (TASK-168)` blocks.
  - `policy_managed_on_server` gives the server-folder text with action `null` for statuses 409, 400, 403, 404, 500 and 503. The text holds no detail and does not mention a token. A 409 without the type keeps the generic text.
  - 503 start-up answer:
    - Retry-After 10, 1 ("1 second", singular), 2, 0 and 999999999 give the not-ready text with action `wait`.
    - No Retry-After gives the generic text (CHK-M5-185).
    - The same through `toProblem` with real headers: `10`, `1` and `999999999` give not-ready; an HTTP date, `-1`, `1.5`, `abc`, an empty value and `1e3` give the generic text. A missing header and a non-problem body are covered too.
    - The detail is never read: five detail texts (one says "Retry-After: 99", one says "starting") do not change the result.
    - `audit_sink_unavailable` with Retry-After keeps the PAUSED text.
    - An unknown type on 503 is decided by the header. On 400, 404, 409, 500 and 502 it gets the generic text even with Retry-After. Retry-After does not change 500, 502 or 401.
- `web/src/api/client.test.ts`: 3 new cases ("M7 generated paths, first pass").
  - `/api/v1/policies`, `/api/v1/policies/{id}` and `/api/v1/imports` are paths; `/policies` and `/imports` are not.
  - The only paths outside `/api/v1` are still `/healthz` and `/readyz`.
  - The list `status` query type is exactly `"enabled" | "disabled"` (#9).
  - A GET goes out as `/api/v1/policies?limit=50&status=disabled`.

#### Runs (Linux container, Node 22, from `web/`)

| Run | Command | Count |
| --- | --- | --- |
| r1 | `npx vitest run src/app/problems.test.ts` | 74/74 passed, 0 failed, 0 skipped |
| r2 | `npx vitest run src/api/client.test.ts` | 16/16 passed, 0 failed, 0 skipped |
| G16 | `npm run gen:api` twice in a scratch copy (`tweb/web` with `tweb/manager/openapi.json` = HEAD), `cmp` against `web/src/api/schema.d.ts` | byte-identical both times; `manager/openapi.json` is unchanged from HEAD |
| paths | `git diff b2e1351 HEAD -- web/src/api/schema.d.ts` | new paths are exactly `/api/v1/imports`, `/api/v1/policies` and `/api/v1/policies/{id}` |
| gates | `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm test` | clean; full suite 401/401 passed, 0 failed, 0 skipped (16 files) |

#### Report rows (for `tests/m7/report.md`)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-317 (G16, web half) | CODE | L | G16 | PASS (first pass) | regeneration byte-identical twice; a hand edit in the copy is undone by regeneration (the plant shows a diff) | 2026-10-27 |
| CHK-M7-310 (REQ-183 (2), first pass) | CODE | L | r2, typecheck | PASS | the three new paths are under `/api/v1/`; `UserPathsArePrefixed` holds; the plant of an unprefixed `/imports` gives 6 `tsc` errors | 2026-10-27 |
| CHK-M7-310 (problem mapping) | CODE | L | r1 | PASS | the cases listed above | 2026-10-27 |
| CHK-M5-185 (regression) | CODE | L | r1 | PASS | every row in the existing table is unchanged, including 503 `about:blank` with no header giving the generic text | 2026-10-27 |

#### Plants (scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/tweb/web`): 8/8 red

The unchanged copy passed 115/115 first, as a control.

| Plant | Result |
| --- | --- |
| The 503 not-ready text is also chosen when the detail contains "start" (the detail is read) | red, 1 failed |
| The 503 branch ignores Retry-After | red, 12 failed |
| The singular is dropped ("1 seconds") | red, 2 failed |
| The `policy_managed_on_server` case is missing | red, 6 failed |
| The detail is appended to the not-ready text | red, 12 failed |
| Retry-After also changes the 401 text | red, 1 failed |
| An unprefixed path in `schema.d.ts` | red in `npm run typecheck` (6 errors) |
| `schema.d.ts` is hand-edited | red in G16 (regeneration differs) |

#### Findings

None blocking.
- The singular "1 second" is in place and tested, as the lead allowed.
- `0` gives "Try again in 0 seconds." with `wait`, which matches the 429 behaviour. Retry-After values over 9 digits are treated as invalid and give the generic text.
- An unknown type on 503 with Retry-After gets the not-ready text. This follows from the ruling (the header decides) and is tested as such.

### TASK-169

Tester: tester-m7-web, 2026-10-27. REQ-181 (1) and (4) for the list; #9; PD-34 (a); TS §4.3 L546-L548, §6.2 (`GET /policies`, every role), §6.3 L1134 (cursor pages) and L1141 (plain text); REQ-126 with the 503 rule. File under test: `web/src/screens/Profiles.tsx`. New test file: `web/src/screens/Profiles.test.tsx`, 25 tests, using the M5 harness (every request is recorded and none leaves the test).

#### Coverage

- **REQ-181 (1), columns.** The headers are exactly Name, Description, Status, Family, Version, Plugins and Updated. Each cell matches the fixture, and the time shows as `YYYY-MM-DD HH:MM:SS UTC`. "(set by an admin)" follows `status_overridden` only, not `file_status`. The empty state says "No profiles." and Next is disabled. "Loading." shows until the answer arrives.
- **Hostile text.** These values render literally, with and without `onOpen`:
  - name `<script>alert(1)</script>`, description `<img src=x onerror=alert(1)>`, family `<b>x</b>`;
  - an RTL override (U+202E) in the name and family;
  - a 16,384-character name and description.

  The container has no `script`, `img`, `b`, `iframe`, `[onerror]` or `[dir]` element. The HTML holds `&lt;script&gt;`. A hostile problem `detail` shows as text in the banner.
- **REQ-181 (4), paging.**
  - With 51 policies: page 1 is one GET with `{limit: 50}`, and Next sends `cursor` from `next_cursor`. Each policy shows once (51 distinct). Next is disabled on the last page. Previous sends a request with no cursor and shows page 1 again.
  - With a server page size of 2: three pages, the cursors are null, `p-2` and `p-4`, and there are exactly 3 requests.
  - A stale answer that arrives after the filter changed is dropped.
- **#9 filter.**
  - The options are exactly `all`, `enabled` and `disabled`.
  - From page 2, `disabled` sends `{limit: 50, status: disabled}` with no cursor and shows "Page 1". Paging inside the filter keeps the status.
  - `enabled` resets paging the same way. `all` sends no `status`.
  - `deleted` is never sent, even when a forged `<option value="deleted">` is injected and chosen (it maps to `all`).
  - Only `GET /api/v1/policies` is ever called.
- **Every role.** Viewer, operator and admin each send exactly one request, `GET /api/v1/policies?limit=50`, with `Bearer <their bsu_>`, and see the list.
- **Errors through `problems.ts`.**
  - The banner shows the fixed text for a 401, a 403 `forbidden`, a 503 with `Retry-After: 10` ("not ready ... 10 seconds"), a 503 without the header (the generic text) and a 500. No table is shown.
  - A rejected fetch shows the "unavailable" callout.
  - A later success clears the banner.
- **`onOpen`.** Without it, the name is plain text in a `TD` and there is no button. With it, a click calls `onOpen(102)` once and sends no request.

#### Runs (Linux container, Node 22, from `web/`)

| Run | Command | Count |
| --- | --- | --- |
| r1 | `npx vitest run src/screens/Profiles.test.tsx` | 25/25 passed, 0 failed, 0 skipped |
| r2 | `npx vitest run src/app/problems.test.ts src/api/client.test.ts src/screens/Profiles.test.tsx` (scratch copy, control) | 115/115 passed |
| gates | `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm test` | clean; full suite 401/401 passed, 0 failed, 0 skipped |

#### Report rows (for `tests/m7/report.md`)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-310 (REQ-181 (1) list) | CODE | L | r1 | PASS | columns, labels, override note, empty and loading states, hostile text (see Coverage) | 2026-10-27 |
| CHK-M7-310 (REQ-181 (4) list) | CODE | L | r1 | PASS | 51 at 50 and 5 at 2 each show every policy once; one GET per page; stale answer dropped | 2026-10-27 |
| CHK-M7-310 (#9, PD-34 (a)) | CODE | L | r1 | PASS | the filter resets to page 1 and never sends `deleted`; three roles each send one identical request | 2026-10-27 |
| CHK-M7-319 (G12-G15) | CODE | L | gates | PASS | lint, typecheck, Prettier and vitest are clean; 401/401 | 2026-10-27 |

#### Plants (scratch copy `/tmp/claude-0/-home-user-Bitscan/b599402a-f9ea-53d5-b7c7-db1b3aca2d92/scratchpad/tweb/web`): 11/11 red

| Plant in `Profiles.tsx` | Result |
| --- | --- |
| The description is rendered with `dangerouslySetInnerHTML` | red, 2 failed |
| The filter passes any value through (a forged `deleted` is sent) | red, 1 failed |
| `pages.reset()` is removed from the filter change | red, 1 failed |
| `all` sends `status=all` | red, 13 failed |
| The stale-answer `active` guard is removed | red, 1 failed |
| The override label is removed | red, 2 failed |
| The family is shown in the description column | red, 3 failed |
| The cursor is never sent | red, 3 failed |
| The network-failure callout is removed | red, 1 failed |
| `ProblemBanner` is removed | red, 7 failed |
| The problem is not cleared after a later success | red, 1 failed |

#### Findings

None.
- The *Deleted* state, the plugin order and the admin actions (REQ-181 (1) detail half, (2) and (3)) belong to TASK-170 and are not tested here.
- I did not edit `tests/m7/report.md`, because it is owned by tester-m7. The rows above are ready to paste.
