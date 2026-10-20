# TASK-012 TEST report: start-up configuration loader

Tester: tester. REQ-019. Date 2026-10-20. Impl report: `work/reports/TASK-012-impl.md` (revisions 1 and 2). Decisions: #45 (answered); main's ruling 2026-10-20 that REQ-019 (3) covers the TLS `*_FILE` variables.

## Verdict: PASS (revision 2)

- Round 1 FAILED on REQ-019 (3): empty BITSCAN_TLS_CERT_FILE and BITSCAN_TLS_KEY_FILE were accepted.
- Revision 1 (an oversized BITSCAN_LISTEN port crashed) and revision 2 (refuse an empty TLS file via stat) fix both. All 152 cases pass.

## Tests added

`manager/tests/test_config.py` (TP-M1-03, 152 cases). It was written from REQ-019 and the plan interface before `startup.py` was read. The fixtures:
- put a canary password in every DSN file and a canary in the vault-token file;
- use a key-recording mapping to prove which variables are looked up;
- sweep repr/str, the exception chain and traceback, captured output and DEBUG logs in every case.

## Commands and counts

- `cd manager && pytest tests/test_config.py`: 152 passed, 0 skipped.
- Gates: ruff, format and mypy clean; G1 and G3 plants red; G6 export unchanged.
- Mutation check: 15 mutations of `startup.py`, each turning at least 1 case red, and the control green:
  - prefer accepted;
  - retention or migrate DSN unchecked;
  - PGSSLMODE honoured;
  - port 0;
  - psycopg error chained;
  - serve reads the migrate variable;
  - plain look-alike fallback;
  - unstripped secret;
  - default listen changed;
  - uploads dir renamed;
  - message without the variable name;
  - DSN in the message;
  - vault address parsed;
  - unbracketed IPv6 accepted.
- The full suite on WSL with `CI=true` passed (274, 0 skipped).

## Acceptance criteria and rows in [tests/m1/report.md](../../tests/m1/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-019 (1) serve profile success, defaults | CHK-M1-010 | PASS |
| (2) each of the eight unset or empty | CHK-M1-011 | PASS |
| (3) missing, unreadable or empty `*_FILE` | CHK-M1-012 | PASS (revision 2) |
| (4) plain look-alikes never read | CHK-M1-013 | PASS |
| (5) TLS rule (#45, all three DSNs); unparsable DSN leaks nothing | CHK-M1-014, CHK-M1-015 | PASS |
| (6) serve never reads the migrate DSN | CHK-M1-016 | PASS |
| (7) db profile | CHK-M1-017 | PASS |
| (8) no secret leaks | CHK-M1-018 | PASS |
| (9), (10) opaque values, no connection | CHK-M1-019 | PASS |
| (11) BITSCAN_LISTEN | CHK-M1-025 | PASS |
| G1, G3, G6 | CHK-M1-020, -021, -023, -024 | PASS |

## Note

S608 does not flag SQL without a recognised shape, for example `SELECT 1 WHERE` with no FROM. Review stays the control for such shapes.
