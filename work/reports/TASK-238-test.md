# TASK-238 TEST: PASS

Tester: tester-m11b, 2026-11-08. High risk, full rigor. REQ-276 at repository level; TS §5.3 L1049, L1051, L1053; TS §5.2 L983–L992 (`audit_log`), L1002–L1006 (grants); #39, #150 (d). Code under test: `bm/repositories/retention_audit.py` (sha256 `fe6ee3f1cb46d33f…`), impl-manager-b, `work/reports/TASK-238-impl.md`.

Test file: `manager/tests/test_retention_repo_pg.py`. It is shared with TASK-237 (see `TASK-237-test.md`); the audit rows are 3 functions, plus the `delete_through` row of the app-refusal test.

Each test starts from an emptied `audit_log` (owner `TRUNCATE`). It then writes a chain through `m.audit_chain`: M1's `compute_row_hash`, the chain lock, and chosen `at` values, deliberately not in time order.

## Runs (W, `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 0 tests/test_retention_repo_pg.py tests/test_retention_grants_pg.py` (with TASK-237) | 39/40 passed, 1 failed (a grant-probe test bug, TASK-237); every audit row passed |
| 2 | both files, `-n 2`, on the final tree | 41/41 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-141 | `test_retention_repo_pg.py::test_audit_oldest_row_hash_and_delete_through`, `::test_audit_delete_through_with_gaps`, `::test_audit_delete_through_refuses_autocommit` | PASS | `oldest(n)` gives `(audit_id, at)` in id order, at most `n`; the `at` values equal the chosen ones, out of time order (4 y, 4 y + 1 d, 1 d, 5 y …). `row_hash(id)` equals the stored hash for every entry; a missing id raises `LookupError`; `n = 0` raises `ValueError`. `delete_through(N)` removes exactly the ids ≤ N (3 of 6), including a recent entry inside the prefix: the repository deletes by id, and the prefix choice is TASK-236's. With a gap in ids, a non-stored N between two blocks removes the first block only, and N below the first id removes 0. On an autocommit connection `delete_through` raises `RuntimeError` and nothing is deleted. |
| CHK-M11-142 (TASK-238 part) | `::test_bitscan_app_is_refused_every_delete` | PASS | As `bitscan_app`, `delete_through` raises `InsufficientPrivilege` and `audit_log`'s checksum is unchanged; `oldest` works with SELECT |

## Plants (throwaway copies; log `/root/m11t/logs/plants-237.jsonl`)

7 plants, 7 red, 0 survived.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-403 | `delete_through` with `<` instead of `<=` | `test_audit_oldest_row_hash_and_delete_through` |
| CHK-M11-348 | audit delete by `at` (`at <=` the entry's time), a hole in the chain | the same test, plus the gaps test (2) |
| P238-oldest-by-at | `oldest` ordered by `at` instead of id | (1) |
| P238-row-hash-prev | `row_hash` returns `prev_hash` | (1) |
| P238-row-hash-missing | a missing id gives `""` instead of `LookupError` | (1) |
| P238-autocommit-allowed | autocommit guard removed | (1) |
| P238-n-zero | `n = 0` accepted | (1) |

## Acceptance (TASK-238: "PostgreSQL as bitscan_retention: the prefix read returns ids in order with their ages, the delete removes exactly ids ≤ N, and as bitscan_app the delete is refused")

- Prefix read: CHK-M11-141.
- Delete ≤ N: CHK-M11-141, plants -403 and -348.
- App refused: CHK-M11-142.

## Notes

- The checkpoint (written before the delete, in the same transaction, through `append_entry`) and `verify_chain()` after a run are TASK-242's: CHK-M11-182 to -187 and -194. This repository writes no checkpoint.
- The grant that lets `bitscan_retention` insert the checkpoint (INSERT on `audit_log`, USAGE on its sequence) is probed in TP-M11-22, CHK-M11-151 (`TASK-237-test.md`).
