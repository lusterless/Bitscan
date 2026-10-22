# TASK-028 TEST report: token and password primitives

Verdict: **PASS** (round 2). Tester, 2026-10-21. REQ-040 (1), (2), REQ-041, REQ-044 (1) parser part, REQ-048 (2) dummy verify; #56. Impl report: `work/reports/TASK-028-impl.md` (revision 1). Two-approval task.

## Rounds
- Round 1: **FAIL** on `tests/test_passwords.py::test_rejection_message_names_the_rule_not_the_value`. Expected `__context__` None (REQ-041 (5) canary sweep includes the exception chain); actual the `UnicodeEncodeError` whose `.object` was the whole password, kept because `raise … from None` only hides the context.
- Round 2 (revision 1, raised outside the except block): all pass.

## Commands run
- L: `pytest tests/test_tokens.py tests/test_passwords.py` → 61 passed; 16 mutations plus control; ruff, format, mypy.
- W: full suite in the lead's clean run, 996 passed, 0 skipped.

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-040 (1) 10,000 tokens, prefix, 32 bytes, no padding | PASS | CHK-M2-060, -061 |
| REQ-040 (2) lowercase SHA-256 of the whole string | PASS | CHK-M2-062 |
| prefix parsing refuses `bsa_`, `bse_`, unknown, malformed | PASS | CHK-M2-063 |
| REQ-041 (1) Argon2id m=65536 t=3 p=4 | PASS | CHK-M2-064 |
| REQ-041 (2) 12–1,024 code points | PASS | CHK-M2-066 |
| REQ-041 (3), (4) exact verify, random salt | PASS | CHK-M2-065 |
| REQ-041 (5) no password or hash in logs or chains | PASS (round 2) | CHK-M2-066, -068 |
| REQ-048 (2) dummy verify is one real verification | PASS | CHK-M2-067 |

Mutations: 16/16 red, control green. Test files added: `test_tokens.py`, `test_passwords.py`.
