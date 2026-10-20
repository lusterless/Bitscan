# TASK-021 TEST report: audit chain verifier

Tester: tester. REQ-031. Date 2026-10-20. Impl report: `work/reports/TASK-021-impl.md` (step 1, revision 1, step 2). Decisions #38 and #39. TP-M1-15.

## Verdict: PASS

## Tests

- `manager/tests/test_audit_verify.py`. The unit part builds chains with the independent #38 reference from test_audit_chain, so a verifier that agrees with a wrong hash would fail.
  - Unit cases: intact and empty chains; id gaps; each hashed field tampered, prev_hash included; inserted and deleted rows; genesis; checkpoint pass and failure cases; 9 malformed checkpoints; a forged mid-chain checkpoint.
  - Revision 1 (the reviewer's should-fix): a failure before the vouching checkpoint is reported at the failing row. The reviewer's repro, checkpoint for 4 with ids 1–4 deleted and the actor of 8 changed, gives (8, `row_hash mismatch`).
  - PostgreSQL part (step 2): `verify_chain`, read as bitscan_app; tampering as bitscan_owner; checkpoint and delete as bitscan_retention; the snapshot read; the open-transaction refusal; the connection left idle.
- Expected ids are taken from REQ-031 (2) and (3) and #39, not from the code. Two cases:
  - a checkpoint edited in place reports itself (its own hash fails);
  - a checkpoint rehashed by a forger reports the oldest row, because nothing vouches for it any more.

## Commands and counts

- Windows: ruff, format and mypy --strict are clean. pytest: 366 passed, pg skipped.
- WSL, clean run: 547 passed, 0 skipped, coverage 100 %, 0 leftover containers.
- Mutations (WSL copy), each red:
  - link check removed: 7 unit and 2 pg red;
  - checkpoint id rule removed: 1 red;
  - REPEATABLE READ removed from the read: 1 red.

## Acceptance criteria → [tests/m1/report.md](../../tests/m1/report.md)

| REQ-031 | Check | Result |
| --- | --- | --- |
| (1) intact chain verifies with a count; empty log verifies | CHK-M1-220, CHK-M1-230 | PASS |
| (2) any hashed field changed (as owner): that audit_id | CHK-M1-221, CHK-M1-229, CHK-M1-230 | PASS |
| (3) deleted middle entry: the next one; inserted wrong-prev entry: itself | CHK-M1-221, CHK-M1-230 | PASS |
| (4) rolled-back id gaps pass | CHK-M1-222, CHK-M1-230 | PASS |
| (5) checkpoint (retention) then delete verifies; one more delete or a changed hash fails | CHK-M1-223, CHK-M1-230 | PASS |
| (6) pure logic, unit-tested without PostgreSQL | CHK-M1-220, CHK-M1-226 | PASS |
| one snapshot (plan) | CHK-M1-224 | PASS |
| mutations | CHK-M1-228, CHK-M1-224 | PASS |

## Accepted residual risk (TS §8.1, impl report)

Anyone who can write audit_log with correct hashes can rebuild a whole valid chain. That cannot be detected without the external sink (M2).
