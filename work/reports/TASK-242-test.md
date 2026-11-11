# TASK-242 TEST: PASS

Tester: tester-m11b, 2026-11-08. This is high risk and gets the user's second look, so it was tested to full rigor: a plant for every security row, boundary and race.

- **Scope:** REQ-274 to REQ-278 at service level, against TS §5.3 L1049, L1051, L1053 and L1054. Also #150 (a)–(k), plan TASK-242 §4, and the lead's corrections of 2026-11-08.
- **Lead's rows:** the TASK-237 review row (locked scans don't stall the step) and the points listed with this task.
- **Code under test:** `bm/services/retention/task.py` (sha256 `24568dc516e3111e…`), by impl-manager-b; see `work/reports/TASK-242-impl.md`.

Test files (new):
- `manager/tests/test_retention_pg.py`: 16 functions, 23 items. Rows CHK-M11-171, -175 to -192.
- `manager/tests/test_retention_race_pg.py`: 3 items. Rows CHK-M11-193 to -195.

I drafted the tests from the plan and the REQs before `task.py` existed, kept the draft outside the tree, and then matched it to the code's names. Each test starts from emptied retention tables, cleared as owner. The races are driven by held locks and bounded lock-wait probes, never by sleeps for ordering.

## Runs (WSL, `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 3 tests/test_retention_pg.py tests/test_retention_race_pg.py` | 25/25 passed, 0 failed, 0 errors, 0 skipped |
| 2 | `pytest -n 0 …::test_fault_in_the_second_inventory_chunk` (row added for a plant, see below) | 1/1 passed |
| 3 | both files, `-n 3`, on the final tree | 26/26 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on both files | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-171 | `test_retention_pg.py::test_locked_scans_at_the_head_do_not_stall_the_step` | PASS | **Lead's row.** 101 scans (`SCAN_CHUNK` + 1) are the oldest, and one session holds M8's re-evaluation lock on all of them; 50 deletable scans sit behind them. One run (a) ends inside the 120 s bound with `chunks` = 1, within ⌈151/100⌉ = 2; (b) deletes all 50; (c) leaves the 101 locked scans and the young scan. After release, the next run deletes the 101. Bound note: `chunks` counts committed transactions that deleted rows, so the bound is the number of chunks, with no extra probe chunk. |
| CHK-M11-175, -180, -192 | `::test_one_run_deletes_exactly_the_expired_rows` | PASS | One run over `aged_world` leaves exactly the spec's survivors for every rule. For the old and past scans, no rows remain anywhere (jobs, results in two partitions, re-evaluations). The 399-day scan and the scan at exactly 400 days are whole. The `NEVER_DELETED` checksums are unchanged (G2: `os_info`, `agent_package`). Per step, `(deleted, skipped)`: scans (2, None), inventory jobs (2, None), snapshots (2, None), requests (2, None), tokens (3, None), audit (0, None, no cursor), packages (2, None). |
| CHK-M11-176 | `::test_every_statement_as_bitscan_retention` | PASS | Every statement of a full run, more than 20 of them including the audit step, comes from login role `bitscan_retention`. The run is given only the retention pool. |
| CHK-M11-177 | `::test_fault_in_the_second_scans_chunk`, `::test_fault_in_the_second_inventory_chunk` | PASS | **Scans:** 150 expired scans, and the second chunk raises after its delete. The first chunk's 100 stay deleted; the step reports `(100, "failed")`; the snapshot step still runs. The log record is exactly `{step: scans, exc_type: RuntimeError}`, without the exception text. The next run deletes the remaining 50. **Inventory:** 2,500 jobs, and the second chunk raises. 1,000 stay deleted and 1,500 remain, so each dated step also uses one transaction per chunk. |
| CHK-M11-178 | `::test_one_run_deletes_exactly_the_expired_rows`, `::test_a_live_api_token_does_not_skip_the_tokens_step` | PASS | **Lead's row, service level.** With a live API token expiring in 300 days present, the tokens step runs and deletes 3: the token expired 91 days ago, a revoked one also 91 days ago, and the old one. The 89-day, revoked-not-expired and live tokens stay, as does the pending request. |
| CHK-M11-179 | `::test_unreferenced_package_pruned_and_stored_again` | PASS | The unreferenced package is pruned and the referenced one kept. An M3 `ingest` of the same name, version and architecture afterwards stores the package again with its `agent_package` row. |
| CHK-M11-181 | `::test_chunks` | PASS | 250 expired scans take 3 chunks, and 2,500 inventory jobs take 3 chunks |
| CHK-M11-182, -183, -187 | `::test_audit_prefix_checkpoint_and_chain` | PASS | Entries in order: 10 expired, 5 recent, 1 expired. The run deletes 10 in one chunk. One checkpoint: actor `system`, target null, detail exactly `{last_deleted_id: id 10, last_deleted_row_hash: its stored hash, deleted: 10}`. Its id is above every other id. The expired entry after the recent ones stays. `verify_chain()` is OK. The checkpoint INSERT comes before the DELETE (statement spy). Wake ran once, after commit: the checkpoint was visible from another session. A second run deletes nothing and writes no checkpoint. |
| CHK-M11-184 | `::test_fault_in_the_audit_delete_leaves_no_checkpoint[raise, count_mismatch]` | PASS | When the delete raises, or deletes one row more than the checkpoint counted, both the checkpoint and the delete roll back. Every entry stays, there is no checkpoint, the chain verifies, wake is never called, the step is `failed`, and packages still run. |
| CHK-M11-185 | `::test_audit_capped_at_the_shipper_cursor` | PASS | Nothing is deleted while `shipped_through()` is None. With the cursor on the third entry, exactly 3 are deleted. The chain verifies. |
| CHK-M11-186 | `::test_25000_entries_three_chunks_three_checkpoints` | PASS | 25,000 entries take 3 chunks with 3 checkpoints (10,000, 10,000 and 5,000). Each `last_deleted_id` is the last id of its chunk. Only the 3 checkpoints remain, and M1's verifier accepts the chain. |
| CHK-M11-188 | `::test_clock_doubt[1h-ahead, 1h-behind, 4min-ahead]`, `::test_a_failing_clock_check_propagates` | PASS | With the manager clock 1 h ahead or behind, nothing is deleted at all (audit included). Every step is `clock_doubt`, with exactly one WARNING "retention refused: clock_doubt" and no "step done" lines. At 4 min ahead the run goes ahead. If `db_now` raises, the error propagates and nothing is deleted. The 5 min 0 s and 5 min 1 s boundary is TASK-236's CHK-M11-046. |
| CHK-M11-189 | `::test_a_future_row_skips_only_its_step[scans, inventory_jobs, snapshots, requests, tokens]` | PASS | A row dated 2 days ahead in each probe column, including the **token created 2 days ahead** (lead's row), sets that step to `future_rows` with 0 deleted. Every other step runs and deletes exactly its expired rows. |
| CHK-M11-190, -191 | `::test_no_ddl_no_other_writes_counts_only_logs` | PASS | No DDL, no UPDATE, and the only INSERT is into `audit_log`. Afterwards the audit log holds only `audit.checkpoint` entries. There is one "retention step done" record per step, in order, with exactly `{step, deleted, chunks, skipped}`. No OUT, ERR, EXEC or EXP canary, and no deleted scan or job id, appears in any log record (message or attributes). |
| CHK-M11-193 | `test_retention_race_pg.py::test_a_scan_under_reevaluation_is_skipped_then_deleted` | PASS | While another session holds M8's lock on one expired scan, the run deletes the other expired scan and leaves this one whole. After release, the next run deletes it. A re-evaluation of it afterwards raises `ScanNotFound`. |
| CHK-M11-194 | `::test_app_writers_during_the_audit_step_never_fork_the_chain` | PASS | Two app writers start inside the audit transaction, after the delete; the probe sees both parked on the chain lock. After the commit both append after the checkpoint. No entry is lost, and `verify_chain()` is OK. |
| CHK-M11-195 | `::test_upload_racing_the_package_prune_loses_nothing` | PASS | An upload's uncommitted `agent_package` row references an unreferenced package. The prune waits on it, the upload commits, and the prune's chunk fails and rolls back: the step is logged `failed` (seen in the log). The package and its reference stay. The next run prunes only the package that is still unreferenced. |

## Plants (throwaway copies; log `/root/m11t/logs/plants-242.jsonl`; plants `/root/m11t/plants-242.json`)

15 plants, 15 red, 0 survived, and no copy left.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-172 | the scans loop stops on the first chunk that deletes nothing | locked-head row (b) |
| P242-skipped-not-carried | each chunk asks for `SCAN_CHUNK` rows only (the stranding bug) | locked-head row |
| CHK-M11-349 | the audit prefix is not capped at the shipper's cursor | cursor row |
| CHK-M11-343 | audit rows deleted without a checkpoint | checkpoint and 25,000 rows (5 failed) |
| CHK-M11-347 | checkpoint after the delete (delete moved first, hash read before it) | statement-order assertion |
| P242-count-check-removed | count mismatch not refused | `[count_mismatch]` |
| P242-wake-removed | no wake after commit | checkpoint row |
| CHK-M11-353 | no clock check | `[1h-ahead]`, `[1h-behind]` |
| P242-future-check-removed | future-row probe skipped | all 5 future rows |
| CHK-M11-394 (service) | tokens probe back on `expires_at` (in `retention.py`) | live-token row, one-run row (6 failed) |
| P242-failure-not-isolated | a step failure re-raised | fault rows (5 failed) |
| CHK-M11-357 | scan ids logged | counts-only row |
| P242-log-exception-text | exception text added to the failure log | scans fault row (exact log record) |
| CHK-M11-355 (service) | re-evaluation lock not tried | race -193 and the locked-head row |
| P242-one-tx-per-step | one transaction for a whole dated step | inventory fault row; added because chunk counts alone cannot show this |

## Acceptance (TASK-242: "Clock control on PostgreSQL with the retention pool: REQ-275 (1)–(6), REQ-276 (1)–(6) and REQ-278 (1), (2), (4) hold")

| Requirement | Parts | Rows |
| --- | --- | --- |
| REQ-275 | (1) | -175 |
| | (2) | -176 |
| | (3) | -177 |
| | (4) | -178 |
| | (5) | -179, -195 |
| | (6) | -180 |
| REQ-276 | (1) | -182 |
| | (2) | -183 |
| | (3) | -194 |
| | (4) | -184 |
| | (5) | -185 |
| | (6) | -186 |
| REQ-278 | (1) | -188, -189 |
| | (2) | -193, -171 |
| | (4) | -190 |

The lead's points:

| Point | Rows |
| --- | --- |
| Locked scans don't stall the step | -171 |
| No delete while the cursor is None | -185 |
| Count-mismatch rollback | -184 |
| 25,000 entries in 3 chunks, chain verifies | -186 |
| One clock-doubt warning; a failing clock check propagates | -188 |
| A failing step is logged by name and type, and the next step runs | -177 |

## Notes

- **Equivalent mutant, not planted:** removing `repo.lock_chain()` before `oldest()`. `append_entry` takes the same lock before the checkpoint insert, so a writer that commits between the read and the checkpoint appends only recent entries, which change neither the prefix nor the chain. The early lock is defence in depth. CHK-M11-194 shows the chain lock is held until commit.
- **Scope:** stopping the scheduler mid-run (CHK-M11-197) is tested with the wiring, in TASK-245. The #151 timing (CHK-M11-387) is for the gate.
