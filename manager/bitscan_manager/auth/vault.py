"""TOTP seed cipher on OpenBao (Vault Transit API) (TS §8.6; #24, #58).

POST {BITSCAN_VAULT_ADDR}/v1/transit/encrypt/<BITSCAN_TOTP_KEY_REF> and
.../decrypt/<key> with the manager's token in X-Vault-Token, over HTTPS
verified against the system CA store (TLS 1.2+), ignoring proxy and netrc
settings. Any failure raises VaultUnavailable, which the routes answer with
503 (#58); its message never holds the seed, the token or the vault's reply.
"""

import base64
import binascii
import ssl
import string
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from bitscan_manager.config.startup import ConfigError

_KEY_CHARS: Final = frozenset(string.ascii_letters + string.digits + "_-.")


class VaultUnavailable(Exception):
    """The vault could not encrypt or decrypt; names the cause only."""


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class VaultCipher:
    """TotpCipher (runtime.py) backed by the Transit secrets engine."""

    def __init__(
        self,
        addr: str,
        key_ref: str,
        token: SecretStr,
        *,
        timeout_s: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parts = urlsplit(addr.strip())
        if parts.scheme != "https" or not parts.netloc or "@" in parts.netloc:
            raise ConfigError(
                "BITSCAN_VAULT_ADDR must be an https:// URL without credentials"
            )
        if parts.query or parts.fragment:
            raise ConfigError("BITSCAN_VAULT_ADDR must not have a query or fragment")
        if (
            not key_ref
            or len(key_ref) > 128
            or not _KEY_CHARS.issuperset(key_ref)
            or set(key_ref) == {"."}  # "." and ".." would be path segments
        ):
            raise ConfigError("BITSCAN_TOTP_KEY_REF must be a Transit key name")
        if not token.get_secret_value():
            raise ConfigError("BITSCAN_VAULT_TOKEN_FILE holds an empty token")
        base = addr.strip().rstrip("/")
        self._encrypt_url = f"{base}/v1/transit/encrypt/{key_ref}"
        self._decrypt_url = f"{base}/v1/transit/decrypt/{key_ref}"
        self._token = token
        self._client = httpx.Client(
            verify=ssl_context or _tls_context(),
            timeout=timeout_s,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return "VaultCipher()"

    def _call(self, url: str, body: dict[str, str], field: str) -> str:
        failure: str | None = None
        value: Any = None
        try:
            response = self._client.post(
                url,
                json=body,
                headers={"X-Vault-Token": self._token.get_secret_value()},
            )
            if response.status_code != 200:
                failure = f"vault answered HTTP {response.status_code}"
            else:
                value = response.json()["data"][field]
        except httpx.HTTPError as exc:
            failure = f"vault unreachable: {type(exc).__name__}"
        except (ValueError, KeyError, TypeError):
            failure = "vault reply is malformed"
        if failure is None and not isinstance(value, str):
            failure = "vault reply is malformed"
        # Raised outside the except blocks, so nothing from the request, the
        # reply or the driver is chained.
        if failure is not None:
            raise VaultUnavailable(failure)
        return str(value)

    def encrypt(self, seed: bytes) -> str:
        plaintext = base64.b64encode(seed).decode("ascii")
        ciphertext = self._call(
            self._encrypt_url, {"plaintext": plaintext}, "ciphertext"
        )
        if not ciphertext.startswith("vault:v"):
            raise VaultUnavailable("vault reply is malformed")
        return ciphertext

    def decrypt(self, ciphertext: str) -> bytes:
        plaintext = self._call(
            self._decrypt_url, {"ciphertext": ciphertext}, "plaintext"
        )
        seed: bytes | None = None
        try:
            seed = base64.b64decode(plaintext, validate=True)
        except (binascii.Error, ValueError):
            pass
        if not seed:
            raise VaultUnavailable("vault reply is malformed")
        return seed

    def close(self) -> None:
        self._client.close()
