# TASK-034 REVIEW: audit shipper and outage gate

Reviewer: reviewer. Date: 2026-10-22. REQ-053, REQ-054. Spec: TS §5.3 L1051, TS §8.1 L1256, TS §8.4 L1289–L1290; #50, #51; decisions 2026-10-21 (TASK-033 `fchmod` folded in here; the per-attempt deadline; the alert counter after its own commit). Plan: `work/plans/TASK-034.md`. Inputs: `work/reports/TASK-034-impl.md` including revision 1; `work/reports/TASK-034-test.md`: PASS, plus a "Revision 1" re-test with rows CHK-M2-131-r1 and -120-r1, 23 of 23 mutations red, and 96 passed on Linux running alone.

Files reviewed:
- `manager/bitscan_manager/services/audit/shipper.py`;
- `manager/bitscan_manager/repositories/audit_log.py` (`entries_after`);
- `manager/bitscan_manager/services/audit/disk_queue.py` (`_owner_only`).

Verdict: APPROVED (round 2)

Not on the TS §8.2 two-approval list. The lead asked for a second look: this is the 15-minute refusal (TS §8.1 L1256), the control that the security invariants name for a sink outage. The user may want to read finding 1, which is fixed.

## Round 1 finding (fixed in revision 1)

1. **should-fix, fixed: the outage gate failed open.** `_send` caught only `DeliveryError`. Any of these escaped `run_once`, so no alert was written and `refusing()` stayed False forever:
   - a `queue.ack()` or `queue.peek()` that raised (`OSError` on a full or failing disk);
   - a transport error not wrapped in `DeliveryError`, such as `httpx.InvalidURL`, `StreamError` or any `RuntimeError`.

   Revision 1:
   - `_send` wraps the batch loop and treats any `Exception` as a failed attempt, logged by type, so `_outage()` runs. This covers the partial-delivery `ack` too.
   - `_save` updates the in-memory state first and logs an `OSError` from `save_state`, so a disk that refuses the state file cannot block the alert or the gate. A restart then re-reads from the older saved cursor, and the queue skips ids it already holds, so nothing is lost.

   I re-ran my repro on revision 1. A transport `OSError` and an `ack` `OSError` each now give no escaped exception, one alert, and `refusing()` true at 20 min. The tester committed 4 tests: transport `RuntimeError`, `ack` `OSError`, `peek` `OSError`, and `save_state` `OSError` during an outage. Three of them go red with the old behaviour planted.

## What was checked

- **Ordering and durability.** Committed rows are read in `audit_id` order after the cursor and fsynced to the queue before the cursor is saved. A record is acknowledged only after the sink accepted it, and after a partial `DeliveryError` only the first `delivered` records are. Delivery is at least once, with `audit_id` and `row_hash` kept. The G26 plant "acknowledging before the sink accepted" is red.
- **Gate (REQ-054 (3), (5)).** `refusing()` means 15 minutes or more since `outage_since`. That value is loaded from the queue folder, so a restart does not reset the 15-minute clock. It is cleared only when the queue is empty and the read has caught up (#51 (d)). The G26 plant "15-minute check removed" is red.
- **One alert per outage (REQ-054 (2)).** `alerted` is persisted, and an alert that fails to write is retried. The alert is written in its own `AppDatabase` transaction, so the counter rises only after commit. The recovery entry is not an alert.
- **Other.** `entries_after` is parameterised and returns the hashed text forms. `fchmod(0o600)` covers segment files and temp files on POSIX. Logs carry counts, id ranges and exception types only; the replanted "record content logged" mutant is red.
- **Gates (my run).** ruff and `mypy --strict` are clean on 100 files. `test_shipper.py` and `test_disk_queue.py` give 80 passed and 12 skipped (POSIX and pg, run in WSL).
- **Scope.** 3 files, about 210 lines in `shipper.py`. Accepted.

## Findings (round 2)

None block approval.

1. **note, the tester's point, accepted.** The `ATTEMPT_S` deadline is checked between batches, so a single batch can run past it by up to one transport timeout. With HTTPS sending one entry per POST, a 500-record batch to a sink that answers slowly but does answer could take up to 500 × 5 s. Consider slicing HTTPS batches, or passing the remaining deadline into `send`. This is a nit, because a slow sink that keeps answering is not an outage.
2. **nit.** `_save` swallows only `OSError`. Any other exception from `save_state` propagates. The tester's crash simulation relies on that, so it is intended.
3. **note, no change.** A database down while the sink is up is not an outage, as the plan says: entries already queued keep shipping.
