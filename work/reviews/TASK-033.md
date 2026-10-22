# TASK-033 REVIEW: audit disk queue

Reviewer: reviewer. Date: 2026-10-21. REQ-054 (1) (the queue part) and (6). Spec: TS §5.3 L1051, TS §8.7 L1344 (`/var/lib/bitscan/audit-queue/`, 0700), L1377; #51 (c); decisions 2026-10-21 ("M2 test-plan answers"). Plan: `work/plans/TASK-034.md`, section TASK-033. Inputs: `work/reports/TASK-033-impl.md`, including revision 1 (my pre-review) and revision 2 (tester round 1, `peek(0)`); `work/reports/TASK-033-test.md` (PASS in round 2, CHK-M2-110 to -115 in `tests/m2/report.md`, `manager/tests/test_disk_queue.py` with 61 tests on Linux).

File reviewed: `manager/bitscan_manager/services/audit/disk_queue.py`.

Verdict: APPROVED

This task is not on the TS §8.2 two-approval list. The lead recommends a second look, because the sink is the only control against a full rewrite of the chain (`work/m2-brief.md`).

## Pre-review findings (round 0), both fixed

1. **should-fix, fixed in revision 1.** A short `os.write` was ignored, so after a partial write on ENOSPC the queue counted the record as queued. `_write_all` now loops and raises on a 0-byte write, and `segment.end` does not advance after a failed write. Tested: `test_short_writes_are_retried`, `test_zero_byte_write_raises_and_queues_nothing`.
2. **should-fix, fixed in revision 1.** Damage in the middle of a file used to drop the valid records after it, and the next append then truncated them away for good. Only an incomplete last line of the newest segment now counts as a crash cut; anything else raises `QueueError` and touches no file. I re-ran my repro on revision 1. The damaged file raises and stays byte-identical, and a cut tail is still accepted and truncated. Tested: `test_newline_terminated_damage_raises_and_touches_nothing`, `test_incomplete_tail_in_an_older_segment_raises`, `test_cut_off_at_every_offset_of_the_last_record`.
3. The four pre-review nits are fixed: the folder must be exactly 0700, a naive `outage_since` is refused, `load_state` checks types exactly, and a segment is added only after its open succeeds (`unlink(missing_ok=True)`).

## What was checked

- **REQ-054 (1).** Order is kept across recreation and segment roll-over. Acknowledged records do not come back. The folder is created 0700 and an existing folder with any group or other bit is refused. Files are created `os.open(..., 0o600)`. The tester checked the modes on Linux under umask 000, 022 and 077.
- **REQ-054 (6).** A cut at every byte offset of the last record returns all the earlier records and never the cut one. The cut-off warning names only the file.
- **Durability.** Every append and state write is fsynced. `acked.json` and `state.json` are replaced atomically (temp file, fsync, `os.replace`, folder fsync on POSIX). The ack file is written before segments are deleted, and a crash between the two is cleaned up at the next start (tested).
- **#51 (c).** A damaged state file raises; it never resets the outage clock to "no outage".
- **Security invariants.** No record content is logged or put in an exception message. The line format is canonical JSON with ASCII escapes, so no raw newline or U+2028 appears inside a line.
- **Gates (my run, Windows).** ruff and format are clean and `mypy --strict` is clean. `test_disk_queue.py` gives 51 passed and 10 skipped; the skipped tests are POSIX-only and ran in WSL. With these tests G5 is green again at 97.63 %.
- **Scope.** 1 file, about 160 lines of code.

## Findings

None block approval.

1. **nit, moved to TASK-034 by the lead (decisions 2026-10-21).** `disk_queue.py:245` and `:145`: `os.open(..., O_CREAT, 0o600)` sets the mode only when it creates the file. A leftover `.state.json.tmp` or `.acked.json.tmp`, or an existing segment file, with mode 0644 keeps that mode, and `os.replace` passes it on to `state.json` (the tester's note). The 0700 folder still protects the contents. The `os.fchmod(fd, 0o600)` fix lands in TASK-034, and the TASK-034 review will check it there.
2. **note for TASK-034.** `peek` (`:162-:173`) re-reads and re-parses every segment from the start on each call. During a long outage that is O(queue size) per send attempt. It is bounded, and correct, but the shipper should not call `peek` in a tight loop. The TASK-034 back-off (1 to 30 s) is enough.
3. **note for TASK-034.** Records are plain `Mapping`s with an integer `audit_id`, not the plan's `SinkRecord`. TASK-034 must convert in both directions without dropping a field, because REQ-053 (3) requires every column so the sink can re-hash. With decisions 2026-10-21 (2), the HTTPS sink sends one entry per POST, so TASK-034 acknowledges entry by entry on that transport.
