# TASK-050 IMPL report: `bsa_` and `bse_` token generation and parsing

REQ: REQ-063. Spec: TS §6.2 L1083, §2.3 (L124–L125), §3.2 L183; #56 (a). This task needs **two approvals** (TS §8.2; agent token primitives).

## Files (1)

- `manager/bitscan_manager/auth/tokens.py`: 33 lines added, 6 removed.

## What changed

- `AgentTokenKind` (`StrEnum`) has two members: `AGENT` (prefix `bsa_`) and `ENROLMENT` (prefix `bse_`). The prefixes are in `AGENT_PREFIXES`. The user `TokenKind` and `PREFIXES` are unchanged, so `parse_user_token` still accepts only `bsu_` and `bsk_`, and refuses `bsa_` and `bse_` as before (REQ-040 (4)).
- `new_agent_token(kind) -> str` returns the prefix plus the unpadded base64url of 32 bytes from `secrets.token_bytes` (43 characters, 47 in total). This is the same generator as the user tokens; both now share `_random_body()`.
- `is_agent_token(raw, kind) -> bool` is True only when `raw` starts with **that** kind's prefix and its body has exactly 43 base64url characters (`A–Z a–z 0–9 - _`). It refuses:
  - the other agent prefix (`bse_` where `bsa_` is asked for, and the other way round);
  - `bsu_`, `bsk_`, unknown prefixes and an upper-case `BSA_`;
  - wrong lengths, padding `=`, `+` and `/`, and non-ASCII characters.

  User and agent parsing share `_well_formed()`.
- Hashing is unchanged: `token_hash(token)` is the lowercase SHA-256 hex of the whole token string, and the agent tokens use it too. Nothing here logs or stores a token.

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: pass (126 files).
- `cd manager && .venv/Scripts/python -m pytest -q`: 1098 passed, 451 skipped (the PostgreSQL tests; Docker unavailable on Windows).
- Scratch probe outside the tree: 10,000 tokens of each kind were distinct, 47 characters long, prefixed, and decoded to 32 bytes. Each passed `is_agent_token` for its own kind only, and `parse_user_token` returned `None` for every one. User tokens failed `is_agent_token` for both kinds, and every malformed variant listed above was refused.

## For the tester

- Call `is_agent_token(raw, AgentTokenKind.AGENT)` for the five `bsa_` routes and `is_agent_token(raw, AgentTokenKind.ENROLMENT)` for enrol. The route dependencies that use it come in TASK-063 and TASK-067.

## Deviations

None.
