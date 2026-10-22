# TASK-034 TEST report: audit shipper and outage gate

Verdict: **PASS**. Tester, 2026-10-21. REQ-053, REQ-054; #50, #51; G26. Impl report: `work/reports/TASK-034-impl.md`. Second look recommended by the lead.

## Commands run
- L: `pytest tests/test_shipper.py` (27 tests: 25 run, 2 Linux-only skipped) and `tests/test_disk_queue.py`; 17 mutations plus control; ruff, ruff format, mypy --strict.
- W: `tester2_t034.sh`, alone: the shipper, the shipper PostgreSQL tests and the disk queue (196 passed with the other wave 4 files); full suite 1248 passed, 0 skipped; `shipper.py` 99 %.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-053 (1) order, at-least-once with identical ids and hashes | PASS | CHK-M2-120, -126, -130 |
| REQ-053 (2) rolled-back entries never sent | PASS | CHK-M2-127 |
| REQ-053 (5), (6) within 5 s; other-process entries | PASS (0.039 s max) | CHK-M2-128, -129 |
| REQ-054 (1) queued on disk, sent after restart | PASS | CHK-M2-121 |
| REQ-054 (2) one alert per outage | PASS | CHK-M2-122 |
| REQ-054 (3) refusing at 15 min until drained (G26) | PASS | CHK-M2-123, -124 |
| REQ-054 (5) outage clock survives restarts | PASS | CHK-M2-125 |
| edge cases (database down, disk full, back-off, deadline), logs | PASS | CHK-M2-131, -132 |
| TASK-033 hardening (stale 0644 files) | PASS | CHK-M2-133 |

Mutations: 17/17 red, including both G26 plants (15-minute check removed; acknowledging before the sink accepted). Control green. One test was weak in my first run (a deadline mutant survived); it now pre-fills the queue, and that mutant is red. Test files added: `test_shipper.py`, `test_shipper_pg.py`.

## Revision 1 (reviewer finding 1: the gate failed open)
- Round 1 tests passed on revision 0 because none of them made `_send` raise anything but `DeliveryError`. On revision 0 the reviewer's case (an `ack` raising `OSError`, or an unwrapped transport error) escaped `run_once`: there was no alert, and `refusing()` stayed false.
- Added 4 tests: unwrapped transport `RuntimeError`, `ack` `OSError`, `peek` `OSError`, and `save_state` `OSError` during an outage. Each must give one alert and refusing at 15 min. All pass on revision 1. With the old "only `DeliveryError` counts" behaviour planted, 3 of them fail.
- Full set re-run: 23/23 mutations red, control green. On Linux, alone: 96 passed. Rows: CHK-M2-131-r1, CHK-M2-120-r1.
- One correction to my earlier mutation evidence: the original "record content logged" plant was mis-built (a format-argument mismatch that logging swallows). The replanted pair is red.
