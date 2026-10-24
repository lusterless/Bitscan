# TASK-050 TEST report: `bsa_` and `bse_` token primitives

**Verdict: PASS** (2026-10-23, tester). REQ-063 (1), (2), (4) at the primitive level. Plan checks: CHK-M3-040 to -044 in `tests/m3/test-plan.md`, written before the code was read. Code tested: `manager/bitscan_manager/auth/tokens.py` (`work/reports/TASK-050-impl.md`). Two approvals are needed (TS §8.2).

## Tests added
- `manager/tests/test_tokens.py`: 13 new test functions (64 cases, file total 97). The oracles are `hashlib`, `base64` and TS §8.6 pattern 3 in RE2.

## Commands (L)
- `PY -m pytest tests/test_tokens.py`: 97 passed.
- ruff, ruff format and `mypy --strict` on the TASK-050 scope: clean. Full suite: 1136 passed, 451 skipped (no PostgreSQL part in this task).
- Mutation plants in throwaway copies (`$TEMP/m3-mut`, imports checked to come from the copy), run with `tests/test_tokens.py` and `tests/test_auth_dependencies.py`. Control: 102 passed. All 7 plants red:
  - CHK-M3-320 at unit level (either agent prefix accepted): 4 failed;
  - `bsa_` in the user prefix table: 4 failed;
  - padded body: 8 failed;
  - 31 bytes: 10 failed;
  - length `>=`: 8 failed;
  - alphabet not checked: 26 failed;
  - prefix compared case-insensitively: 2 failed.

## Acceptance criteria
- "10,000 tokens of each kind are distinct, 47 characters, prefixed and decode to 32 bytes": CHK-M3-040 PASS.
- "the agent parser accepts only a well-formed token of the asked prefix": CHK-M3-043 PASS.
- "the user parser still refuses both": CHK-M3-044 PASS.
- REQ-063 (2), the hash: CHK-M3-042 PASS. Storage at rest (REQ-063 (3)) is checked in TASK-066, TASK-067 and TP-M3-35 (CHK-M3-192, -206, -303).

## Note
- As for the M2 user tokens, a 43-character body whose last character has non-zero low bits is accepted, even though it is not the canonical base64url of 32 bytes. This is harmless (the hash lookup decides) and the same as M2. It is not a defect.
