# TASK-032 TEST report: audit sink transports

Verdict: **PASS**. Tester, 2026-10-21. REQ-053 (1) send half, (3), (4); #24 and decisions 2026-10-21 (syslog+tls and https; one entry per POST). Impl report: `work/reports/TASK-032-impl.md` (revision 1).

## Commands run
- L: `pytest tests/test_sink_transport.py` → 61 passed against local fake sinks with a test CA made at test time by openssl (no key committed); 15 mutations plus control; ruff, format, mypy.
- W: full suite in the lead's clean run, 996 passed, 0 skipped; `sink_transport.py` 98 % covered.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-053 (1) every column delivered, in order, both transports | PASS | CHK-M2-100, -101 |
| REQ-053 (3) delivered fields re-hash to `row_hash` and chain | PASS | CHK-M2-102 |
| REQ-053 (4) certificate verified; plain transports refused | PASS | CHK-M2-103, -104 |
| delivery error within the timeout, no content | PASS | CHK-M2-105, -106 |

Mutations: 15/15 red, control green.

## Notes
- My tests found `syslog+tls://h:0` silently mapped to port 6514. Revision 1 (sent with the reviewer's nits) already refuses port 0; the round counted is revision 1.
- The test PKI helper (`tests/certs.py`) and the fake sinks (`tests/fake_sink.py`) are reused by TASK-030 and TASK-045.
- Test files added: `test_sink_transport.py`, `fake_sink.py`, `certs.py`.
