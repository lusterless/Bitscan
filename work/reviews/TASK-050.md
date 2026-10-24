# TASK-050 REVIEW: `bsa_` and `bse_` token generation and parsing

Reviewer: reviewer. Date: 2026-10-23. REQ-063. Spec: TS §6.2 L1083 (256 random bits, base64url, prefix, SHA-256 stored), §2.3 (token table), §3.2 L183 (agent token shown once, hash stored); #56 (a) (unpadded, 43 characters). Inputs:
- `work/reports/TASK-050-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-040 to -044, rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/auth/tokens.py` (the only impl file; 33 added, 6 removed);
- the tester's M3 section of `manager/tests/test_tokens.py`.

Verdict: APPROVED

**Two approvals required** (TS §8.2 L1268; agent token primitives, decisions 2026-10-20). This is the first one; the user's second approval is still needed.

## What was checked

- **Spec conformance.** `new_agent_token` uses the same generator as the user tokens: `secrets.token_bytes(32)`, unpadded base64url, 43 characters plus the prefix, so 47 characters in all. `token_hash` is unchanged: lowercase SHA-256 hex of the whole token string. `is_agent_token(raw, kind)` accepts only the asked kind's exact prefix with a well-formed body. It therefore refuses the other agent prefix, `bsu_`, `bsk_`, upper-case prefixes, wrong lengths, padding, `+`, `/` and non-ASCII. The user parser and `PREFIXES` are untouched, so `bsa_` and `bse_` are still refused on user routes (REQ-040 (4), REQ-063 (4)).
- **Security invariants.** Only hashes are meant to be stored, and this module neither stores nor logs anything. No `random` module is used. The generator and the check have separate per-kind entry points, so a route dependency asks for exactly one prefix. That is the unit-level guard for CHK-M3-320 and CHK-M3-321.
- **Scope.** One file, small, no unrelated change. `_random_body` and `_well_formed` are shared by the user and agent paths, with no new abstraction beyond that.
- **Tests (my run, Windows).** `tests/test_tokens.py` passes within the 206-test run listed in the TASK-049 review. `ruff`, `ruff format --check` and `mypy --strict` are clean on both files. The tests can fail:
  - 10,000 tokens per kind are checked for distinctness, length, alphabet, 32-byte decode and a full RE2 match of TS §8.6 pattern 3;
  - a fixed `secrets.token_bytes` value must appear as the body;
  - the `random` functions are patched to raise;
  - a known-answer hash over the whole token rules out a body-only hash;
  - there are 25 malformed variants per kind, plus the cross-kind refusals in both directions.

## Findings

None.

Note (no action): the 43rd character of a 32-byte body carries only 4 bits, so the check also accepts some bodies the generator never produces. Such a token can only fail the hash lookup, the same as for user tokens in M2.
