# TASK-029 REVIEW: TOTP core (RFC 6238)

Reviewer: reviewer. Date: 2026-10-21. REQ-042 (1), (4), (5). Single use and concurrency are covered by TASK-031 and TASK-038. Spec: TS §6.2 L1087, TS §5.2 L957–L958; #49 (a) as approved 2026-10-21; PD-19 (f). Plan: `work/plans/TASK-038.md`, section TASK-029. Inputs: `work/reports/TASK-029-impl.md`; `work/reports/TASK-029-test.md` (PASS, CHK-M2-070 to -075 in `tests/m2/report.md`, `manager/tests/test_totp.py`; one equivalent mutant, base32 padding, which 20-byte seeds never have).

Files reviewed: `manager/bitscan_manager/auth/__init__.py` (empty), `manager/bitscan_manager/auth/totp.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **#49 parameters.** HMAC-SHA1, 6 digits, 30 s period, window current ± 1, seed 20 bytes from `secrets.token_bytes`, base32 without padding.
- **RFC conformance.** HOTP dynamic truncation (`totp.py:52-56`) is checked against the RFC 4226 Appendix D vectors and the RFC 6238 Appendix B SHA-1 vectors, at 8 digits and at 6.
- **Comparison (REQ-042 (5)).** `match_step` (`totp.py:59-69`) calls `hmac.compare_digest` on all three candidates and never exits early. It returns the newest matching step. A malformed code is refused before any HMAC work: wrong length, non-ASCII digits (for example Arabic-Indic), spaces or a sign. That leaks only the code's format, not the seed. The tests count `compare_digest` calls per candidate and guard against `==` being used instead.
- **Time.** A naive `datetime` is refused, and a non-UTC aware time gives the same step. The step boundaries are tested.
- **Provisioning URI.** The label and every query value are percent-encoded. The test with username `a&secret=AAAA#x` shows a username cannot inject a second `secret` parameter or a fragment.
- **Security invariants.** Standard library only: no stdlib `re`, no logging, no state, no database. Seed and codes never leave the function.
- **Gates (my run).** ruff and format clean, `mypy --strict` clean, `tests/test_totp.py` 61 passed.
- **Scope.** 2 files, about 60 lines.

## Findings

None block approval.

1. **note for TASK-039 and the user (carry-over accepted by the lead, decisions 2026-10-21).** `provisioning_uri()` and `seed_to_base32()` return the seed in clear text. TASK-039 must return them only in the enrolment response, and never log them or put them in an exception or an audit `detail`. The TASK-039 review will check this with the canary sweep.
2. **note for the user (second approval).** With ± 1 step, a code is accepted for up to 90 s: the #49 default the user approved. Single use rests entirely on the TASK-031 `claim_totp_step` UPDATE. That UPDATE stores the newest matching step, so after a code from step s + 1 (clock drift), the user's codes for steps up to s + 1 are refused until the next step. That is expected RFC 6238 behaviour.
