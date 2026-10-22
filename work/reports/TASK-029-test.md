# TASK-029 TEST report: TOTP core (RFC 6238)

Verdict: **PASS**. Tester, 2026-10-21. REQ-042 (1), (4), (5) and the #49 (a) parameters. Impl report: `work/reports/TASK-029-impl.md`. Two-approval task (TS §8.2).

## Commands run (L)
- `cd manager && .venv/Scripts/python.exe -m pytest tests/test_totp.py` (new, 61 tests)
- Mutation harness on `bitscan_manager/auth/totp.py` (copies in `%TEMP%`, 9 mutations plus a control); ruff on a copy with `import re`.
- `ruff check manager`, `ruff format --check manager`, `mypy --strict … manager` (Success, 53 files), full suite 484 passed, 181 skipped (pg).

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-042 (1) RFC 6238 vectors for #49 (SHA1) | PASS | CHK-M2-070 |
| REQ-042 (2) window part (inside accepted, returns its step) | PASS | CHK-M2-071 |
| REQ-042 (2) single use and (3) concurrency | not in this task: TASK-031 (CHK-M2-092), TASK-038 (CHK-M2-175) | — |
| REQ-042 (4) outside window, wrong length, non-digits refused | PASS | CHK-M2-071, -072 |
| REQ-042 (5) constant-time comparison | PASS | CHK-M2-073 |
| #49 (a) seed 20 bytes, base32, URI | PASS | CHK-M2-074 |
| naive time refused, module pure, `re` banned | PASS | CHK-M2-075 |

Mutations: 8 of 9 red; the 9th (base32 padding) is equivalent for 20-byte seeds. Control green. Rows are in [tests/m2/report.md](../../tests/m2/report.md).

## Notes
- Expected codes are the published RFC 6238 and RFC 4226 vectors. The "newest step wins" case uses a brute-forced seed whose two adjacent steps share a code; the test re-checks the collision first.
- `match_step` refuses a malformed code before any HMAC work (a counting `code_at` shows 0 calls), and a 10,000-character string costs no hashing.
- Test file added by the tester: `manager/tests/test_totp.py`.
