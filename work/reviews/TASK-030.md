# TASK-030 REVIEW: TOTP seed cipher on OpenBao (Vault Transit API)

Reviewer: reviewer. Date: 2026-10-21. REQ-043. Spec: TS §8.6 L1310–L1312 (`BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF`, `BITSCAN_VAULT_TOKEN_FILE`), TS §5.2 L957 (`totp_secret_enc`), TS §8.1 L1259; #24 as changed by the user on 2026-10-21 (OpenBao via `/v1/transit/encrypt|decrypt/<key>`, token auth, system CA store); #58. Inputs: `work/reports/TASK-030-impl.md` (revision 1: key refs `.` and `..`); `work/reports/TASK-030-test.md` (PASS in round 2, CHK-M2-080 to -085, 64 tests, 12 of 12 mutations red).

File reviewed: `manager/bitscan_manager/auth/vault.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **API (#24).** Encrypt is `POST {addr}/v1/transit/encrypt/{key}` with `{"plaintext": base64(seed)}`. Decrypt is `POST …/decrypt/{key}` with `{"ciphertext": …}`. The token goes in `X-Vault-Token`. The ciphertext must start with `vault:v`, and the plaintext must be strict base64 of a non-empty value. `totp_secret_enc` therefore holds only Transit ciphertext. The tester checked that it contains no form of the seed (REQ-043 (1)).
- **TLS (REQ-043 (2)).** `ssl.create_default_context()` (system CA store, host-name check) with a TLS 1.2 minimum. Redirects are not followed. `trust_env=False`, so proxy, netrc and `SSL_CERT_*` from the environment are ignored (my TASK-032 nit, applied here too). `ssl_context` is a test hook only. An untrusted certificate is refused.
- **Token secrecy (REQ-043 (3)).** The token stays a `SecretStr` and is sent as a per-request header, never as a client default, so it is in no `repr`. `repr(VaultCipher)` is fixed text. The module does not log, and httpx's URL logging is capped by TASK-027; the URL holds only the address and the key name.
- **Errors (REQ-043 (4), #58).** Every failure is `VaultUnavailable` with fixed text: an HTTP status, a transport exception type, or "malformed". It is raised outside the `except` blocks, so nothing is chained, and the response body is never read into an error. The tester's two added tests cover a chained transport error and non-200 statuses below 500. Construction makes no network call, so an unreachable vault does not stop start-up (#58 (a)).
- **Path tricks, as the tester asked me to check.** The key ref allows `[A-Za-z0-9_.-]`, 1–128 characters. The only segments a URL parser rewrites are the dot segments `.` and `..`, and revision 1 refuses any all-dot value. I ran mixed values through httpx's URL handling: `.a`, `a.`, `a..b`, `..a` and `.-.` all stay one literal segment under `/v1/transit/encrypt/`. With no `/`, `%`, `?` or `#` allowed, the key cannot leave the Transit path.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 86 files, and `test_vault.py` passes.
- **Scope.** 1 file, about 105 lines.

## Findings

None block approval.

1. **nit.** `vault.py:47-65`: `BITSCAN_VAULT_ADDR` is checked for scheme, host, credentials, query and fragment, but its path is kept. An address such as `https://h/x/..` is normalised by httpx to `https://h/v1/transit/…`. This value is set by root in the unit's environment, not by users, so it is not a trust boundary. Refusing any non-empty path other than `/` would still make a mistyped address fail at start-up rather than at the first sign-in.
2. **note for TASK-045.** `close()` exists, but no owner calls it yet. `serve`'s lifecycle should close the client on shutdown.
3. **note for TASK-038 and TASK-039.** `VaultUnavailable` must map to 503 (#58 (b)) and must not count as a failed sign-in; the TASK-038 plan already says this. The TASK-038 review will check it.

## For the user (second approval)

There is no vault token renewal: the impl report notes that a token lifecycle is not in the spec. An OpenBao token with a TTL will expire, and from then on every TOTP sign-in and enrolment answers 503 until the token file is replaced and the manager restarted. Choose a token without expiry for the Transit policy, or plan renewal as an operational step. This is not a code defect.
