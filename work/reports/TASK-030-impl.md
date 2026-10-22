# TASK-030 IMPL report: TOTP seed cipher on OpenBao (Vault Transit API)

REQ: REQ-043. Spec: TS §8.6 L1310–L1312 (`BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF`, `BITSCAN_VAULT_TOKEN_FILE`), TS §5.2 L957 (`totp_secret_enc`), TS §8.1 L1259. Decisions:
- #24, user's change 2026-10-21: OpenBao through the Vault-compatible Transit API (`/v1/transit/encrypt|decrypt/<key>`), token auth, TLS verified against the system CA store;
- #58: start-up does not fail; TOTP sign-in and enrolment answer 503; no fallback;
- lead 2026-10-21: `trust_env=False`; never log the token, the key or a plaintext seed.

**Two approvals (TS §8.2, auth).**

## Files (1)

- `manager/bitscan_manager/auth/vault.py`: new, 103 non-blank lines.

## Interface

```python
class VaultUnavailable(Exception)        # every encrypt/decrypt failure; routes answer 503 (#58)
class VaultCipher:                        # implements runtime.TotpCipher
    def __init__(self, addr: str, key_ref: str, token: SecretStr, *,
                 timeout_s: float = 5.0, ssl_context: ssl.SSLContext | None = None)
    def encrypt(self, seed: bytes) -> str         # "vault:v<n>:..." ciphertext
    def decrypt(self, ciphertext: str) -> bytes
    def close(self) -> None
```

`ssl_context` exists for tests only; `serve` (TASK-045) never passes it. `token` is the `SecretStr` that `config/startup.py` already reads from `BITSCAN_VAULT_TOKEN_FILE`.

## Behaviour

- **Construction checks** raise `ConfigError` naming the variable, never the value. This runs when `serve` builds the runtime and makes no network call, so #58 (a) holds: an unreachable vault does not stop start-up. It refuses:
  - a `BITSCAN_VAULT_ADDR` that is not `https://`, has no host, or has credentials, a query or a fragment;
  - a `BITSCAN_TOTP_KEY_REF` that is not 1–128 characters of `[A-Za-z0-9_.-]` (keeps it a single path segment);
  - an empty token.
- **encrypt:** `POST {addr}/v1/transit/encrypt/{key}` with JSON `{"plaintext": base64(seed)}` and header `X-Vault-Token`. The reply's `data.ciphertext` must be a string starting with `vault:v`.
- **decrypt:** `POST …/decrypt/{key}` with `{"ciphertext": …}`. The reply's `data.plaintext` must be strict base64 of a non-empty value.
- **HTTP client:** `httpx.Client` with these settings:
  - `verify` = `ssl.create_default_context()` (system CA store, host-name check) with a TLS 1.2 minimum;
  - `timeout = 5 s`;
  - `follow_redirects=False`;
  - `trust_env=False` (no proxy, `.netrc` or `SSL_CERT_*` from the environment).

  The token is sent only as a per-request header, never as a client default, so it is not in `repr(client)`.
- **Errors:** every failure raises `VaultUnavailable` with one of these messages:
  - `vault answered HTTP <code>`: any status other than 200;
  - `vault unreachable: <httpx exception type>`: TLS, connect or timeout errors;
  - `vault reply is malformed`: bad JSON, missing fields, wrong types.

  It is raised outside the `except` blocks, so `__context__` and `__cause__` are `None`. The vault's response body is never read into an error.
- **No logging and a fixed repr:** the module does not log, and `repr(VaultCipher)` is the fixed text `VaultCipher()`. httpx's own request-URL logging is capped at WARNING by TASK-027's `configure_logging`. The URL holds only the address and the key name, never key material, the token or the seed.
- **Not done here:** caching decrypted seeds, readiness probing (#58 (c): the vault is not part of `/readyz`), and token renewal (a vault token lifecycle is not in the spec).

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 76 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 781 passed, 229 skipped (pg), 97.73 % (`auth/` is outside G5) |
| Scratch script (deleted) against a local fake Transit server over HTTPS (self-signed `localhost` cert from Git Bash `openssl`), token = canary | Encrypt hit `/v1/transit/encrypt/totp` with `X-Vault-Token` = the token. Decrypt returned the seed. The ciphertext held neither the raw seed nor its base64. The canary was in neither `repr(cipher)` nor `repr(cipher._client)` |
| Scratch: error cases | 403 (with a body echoing the canary), 500 and a malformed reply gave `VaultUnavailable` with no canary and no chain. An untrusted certificate gave `vault unreachable: ConnectError`, with no context. A closed port with `timeout_s=1` gave `vault unreachable: ConnectTimeout`. No captured log line (root at DEBUG) held the token |
| Scratch: construction | `http://`, credentials, a query, key `a/b`, an empty key and an empty token were each refused with `ConfigError` naming the variable |

## For the tester (TP-M2-08)

- Trust your fake vault's CA with `VaultCipher(addr, key, SecretStr(token), ssl_context=ssl.create_default_context(cafile=...))`. Omit `ssl_context` for the untrusted-certificate case. `SSL_CERT_FILE` is ignored on purpose (`trust_env=False`).
- `VaultUnavailable` is the #58 error; TASK-038 and TASK-039 map it to 503.

## Revision 1 (found by running the tester's in-progress `tests/test_vault.py`)

`BITSCAN_TOTP_KEY_REF` values `.` and `..` were accepted. Every character is in the allowed set, but `.` and `..` would become the path segments `/v1/transit/encrypt/.` and `/v1/transit/encrypt/..`, so a request could reach a different Transit path. A key made only of dots is now refused with the same `ConfigError("BITSCAN_TOTP_KEY_REF must be a Transit key name")`.

Re-checked: ruff and mypy `--strict` are clean, and `pytest tests/test_vault.py` gives 55 passed.
