# TASK-028 IMPL report: token and password primitives

REQ: REQ-040, REQ-041. Spec: TS §6.2 L1083 (256 random bits, base64url, prefix, SHA-256 only stored), L1087 (Argon2id, at least 12 characters), TS §2.3, TS §5.2 (`user_token.token_hash`, `app_user.password_hash`), TS §8.6 L1334 (redaction pattern); #56 as approved: (a) no padding (43 characters), (b) at most 1,024 characters with no normalisation, (c) the RFC 9106 low-memory profile. Plan: `work/plans/TASK-041.md`, section TASK-028. **Two approvals (TS §8.2, auth).**

## Files (2)

- `manager/bitscan_manager/auth/tokens.py`: new, 33 non-blank lines.
- `manager/bitscan_manager/auth/passwords.py`: new, 47 non-blank lines.

## `auth/tokens.py`

- `TokenKind(StrEnum)`: `SESSION = "session"`, `API = "api"`. These are the `user_token.kind` values. The plan put this enum in `principal.py` (TASK-037); it lives here because `parse_user_token` returns it, and TASK-037 imports it from here.
- `PREFIXES = {SESSION: "bsu_", API: "bsk_"}`. This module is the only place that defines user-token prefixes. M3 adds `bsa_`/`bse_` for the agent router; the user-route parser does not change.
- `new_token(kind)` returns the prefix plus `base64.urlsafe_b64encode(secrets.token_bytes(32))` with the `=` padding removed. That is 47 characters, and it matches `\bbs[aeku]_[A-Za-z0-9_-]{20,}` in full.
- `token_hash(token)` returns `hashlib.sha256(token.encode("utf-8")).hexdigest()`: 64 lowercase hex characters, the hash of the whole string including the prefix.
- `parse_user_token(raw)` returns a `TokenKind` only for `bsu_` or `bsk_` followed by exactly 43 characters of `[A-Za-z0-9_-]`. Otherwise it returns `None`: `bsa_`, `bse_`, unknown prefixes, other lengths, `=`, non-ASCII. It uses set membership, no regex.

## `auth/passwords.py`

- `MIN_LEN = 12` and `MAX_LEN = 1024`, counted with `len()` (code points). There is no normalisation.
- `PasswordRejected(ValueError)`. Its messages name only the rule: `password must be at least 12 characters`, `… at most 1024 characters`, `password must be valid Unicode text`.
- `check_new_password(pw)` checks both lengths and refuses strings that cannot be encoded as UTF-8 (lone surrogates). It raises `from None`, because the `UnicodeEncodeError` text would quote the offending character.
- `hash_password(pw)` runs `check_new_password`, then `PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)`. The PHC string is `$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>` with a random 16-byte salt.
- `verify_password(stored, pw)` returns `True` only for the exact password. It returns `False` on a mismatch or a malformed stored hash, and never raises. The password is encoded with `surrogatepass`, so even a lone surrogate costs one Argon2id run and returns `False`.
- `dummy_verify(pw)` runs one verification against a fixed hash with the same parameters. The hash is created lazily on first use and cached, so neither the import, the OpenAPI export nor the CLI pays for it. TASK-038 uses it for the unknown-user and back-off paths.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager` (stdlib `re` banned), `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 64 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 552 passed, 228 skipped (pg), 97.63 % |
| Scratch: 10,000 tokens of each kind (first 2,000 inspected in detail) | all distinct; each has the right prefix, 47 characters, a body that decodes to 32 bytes, an RE2 full match of the TS §8.6 pattern, and round-trips through `parse_user_token` |
| Scratch: `token_hash` | 64 lowercase hex characters |
| Scratch: `parse_user_token` on `bsa_`/`bse_`/`bsx_` with a valid body, one character too long or too short, a trailing `=`, a trailing `é`, `""`, `"bsk_"` | all `None` |
| Scratch: passwords | the hash begins `$argon2id$v=19$m=65536,t=3,p=4$` and two hashes of the same password differ; verify passes only for the exact password, and is `False` for a 13-character variant, a junk hash and a lone-surrogate password; 11 characters, 1,025 characters and a surrogate are refused; 12 × `é` and 1,024 characters are accepted |
| Scratch: timing | the first `dummy_verify` took 0.136 s (it also creates the cached hash), a wrong-password verify 0.068 s, a later `dummy_verify` 0.086 s |

## For the tester (TP-M2-06)

- To prove `dummy_verify` really verifies (REQ-048 (2)), monkeypatch `bitscan_manager.auth.passwords._HASHER` with a counting wrapper, or wrap `verify_password`.
- `auth/` is outside `services/`, so it does not count toward the G5 gate.

## Revision 1 (tester round 1, CHK-M2-068 / REQ-041 (5))

`check_new_password` used to refuse a non-UTF-8-encodable password with `raise PasswordRejected(...) from None` inside the `except UnicodeEncodeError` block. `from None` only suppresses the display: `__context__` still held the `UnicodeEncodeError`, whose `.object` is the whole password. The rejection is now raised after the `except` block, from a flag, so `__context__` and `__cause__` are both `None`. This is the same pattern `db/pool.py` and the M1 config loader use.

I checked the rest of `bitscan_manager/` for the same `from None` pattern:
- `api/pagination.py`: its context is a `binascii.Error` about the client's own cursor, which is not a secret, so I left it.
- `services/audit/sink_transport.py` (TASK-032): fixed in that task.

Re-checked:
- `pytest tests/test_passwords.py tests/test_tokens.py`: 61 passed.
- ruff and mypy `--strict` are clean on `bitscan_manager`.
