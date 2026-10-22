# TASK-030 TEST report: TOTP seed cipher (OpenBao, Vault Transit API)

Verdict: **PASS** (round 2). Tester, 2026-10-21. REQ-043 (1)–(4); decisions 2026-10-21 (1) (OpenBao Transit, token from `BITSCAN_VAULT_TOKEN_FILE`, TLS against the system CA store); #58. Impl report: `work/reports/TASK-030-impl.md` (revision 1). Two-approval task.

## Rounds
- Round 1: **FAIL** on `tests/test_vault.py::test_bad_configuration_is_refused_without_echoing_secrets[..]` and `[.]`. Expected `ConfigError`; actual: accepted. Diagnosis: `.` and `..` pass the character check, and httpx normalises the path, so the request goes to `/v1/transit` or `/v1/transit/encrypt` instead of a key.
- Round 2 (revision 1 refuses `.` and `..`): all pass.

## Commands run
- L: `pytest tests/test_vault.py` → 64 passed; 12 mutations plus control; ruff, ruff format, mypy --strict.
- W: `tester2_w3.sh`, alone: full suite 1131 passed, 0 skipped.

## Criteria
| REQ-043 | Result | Rows |
| --- | --- | --- |
| (1) only ciphertext stored; round trip | PASS | CHK-M2-080, -081 |
| (2) HTTPS with certificate verification | PASS | CHK-M2-082 |
| (3) vault token only in the vault request | PASS | CHK-M2-083 |
| (4) vault errors: one error (#58), no seed, token or reply | PASS | CHK-M2-084 |
| configuration refusals; no connection at construction | PASS (round 2) | CHK-M2-085 |

Mutations: 12/12 red, control green. Two mutants survived the first set (a chained transport error; non-200 statuses below 500 accepted). I added two tests, and both are now red. Test files added: `test_vault.py`, `fake_vault.py`.
