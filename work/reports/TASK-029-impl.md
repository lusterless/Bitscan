# TASK-029 IMPL report: TOTP core (RFC 6238)

REQ: REQ-042 (parts 1, 4, 5; single use and concurrency are TASK-031/TASK-038). Spec: TS §6.2 L1087 ("each code is accepted once (`totp_last_step`)"), TS §5.2 L957–L958; #49 (a) as approved 2026-10-21: HMAC-SHA1, 6 digits, 30 s, current step ± 1, seed 20 random bytes, base32; PD-19 (f) standard library only. Plan: `work/plans/TASK-038.md`, section TASK-029. **Two approvals (TS §8.2, auth).**

## Files (2)

- `manager/bitscan_manager/auth/__init__.py`: new, empty package marker.
- `manager/bitscan_manager/auth/totp.py`: new, about 60 lines, imports only `base64`, `hashlib`, `hmac`, `secrets`, `struct`, `datetime`, `urllib.parse`.

## API

| Name | Behaviour |
| --- | --- |
| `SEED_BYTES = 20`, `DIGITS = 6`, `PERIOD_S = 30`, `WINDOW_STEPS = 1`, `ISSUER = "Bitscan"` | #49 parameters |
| `new_seed() -> bytes` | `secrets.token_bytes(20)` |
| `seed_to_base32(seed) -> str` | RFC 4648 base32, `=` padding removed (32 characters for 20 bytes) |
| `provisioning_uri(seed, username, issuer="Bitscan") -> str` | `otpauth://totp/Bitscan%3A<user>?secret=…&issuer=Bitscan&algorithm=SHA1&digits=6&period=30`; label and values percent-encoded |
| `step_at(now) -> int` | `int(now.timestamp()) // 30`; `ValueError` for a naive datetime (a naive value would silently use local time) |
| `code_at(seed, step, digits=DIGITS) -> str` | RFC 4226 HOTP, HMAC-SHA1, dynamic truncation, zero-padded. The `digits` keyword exists so the RFC 6238 Appendix B 8-digit vectors can be checked directly |
| `match_step(seed, code, now) -> int \| None` | Returns `None` unless `code` is exactly 6 ASCII digits (so Unicode digits such as Arabic-Indic are refused). Otherwise compares the code with the codes for steps `current-1 … current+1` using `hmac.compare_digest` on every candidate, with no early exit, and returns the newest matching step or `None` |

The module is pure. It does not log or keep state, and it never sees the database. Single use is the caller's job: it stores the returned step atomically with `totp_last_step < step` (TASK-031 repository, TASK-038).

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager` (stdlib `re` banned; none used), `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 48 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 366 passed, 181 skipped (pg), 98.15 % |
| Scratch check (not a test file): RFC 6238 Appendix B SHA1 vectors (seed `12345678901234567890`, T = 59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000) | the 8-digit codes match with `digits=8`; the default 6-digit code is the last 6 digits of each and `match_step` returns `step_at(T)` |
| Scratch: window | codes for steps ±1 return that step; ±2 return `None`; `""`, 5 and 7 digits, `12345a`, Arabic-Indic digits and a leading space return `None`; a naive `now` raises `ValueError` |

## For the tester

- `auth/totp.py` is outside `services/`, so it does not count toward the G5 coverage gate. TP-M2-07 covers it directly.
- To prove the comparison is constant-time, monkeypatch `bitscan_manager.auth.totp.hmac.compare_digest` with a counting wrapper. A well-formed code should cause exactly 3 calls, whether it matches or not.
