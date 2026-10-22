"""User tokens (TS §6.2 L1083, §2.3): bsu_ sessions and bsk_ API tokens.

A token is its prefix plus the unpadded base64url of 32 CSPRNG bytes (43
characters, #56 (a)). Only the lowercase SHA-256 hex of the whole token string
is stored. The user-route parser accepts only bsu_ and bsk_.
"""

import base64
import hashlib
import secrets
import string
from enum import StrEnum
from typing import Final

TOKEN_BYTES: Final = 32
BODY_LEN: Final = 43
_ALPHABET: Final = frozenset(string.ascii_letters + string.digits + "-_")


class TokenKind(StrEnum):
    """The user_token.kind value of each user token prefix."""

    SESSION = "session"
    API = "api"


PREFIXES: Final = {TokenKind.SESSION: "bsu_", TokenKind.API: "bsk_"}
_KIND_BY_PREFIX: Final = {prefix: kind for kind, prefix in PREFIXES.items()}


def new_token(kind: TokenKind) -> str:
    body = base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).rstrip(b"=")
    return PREFIXES[kind] + body.decode("ascii")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_user_token(raw: str) -> TokenKind | None:
    """The kind for a well-formed bsu_ or bsk_ token, else None (bsa_, bse_,
    unknown prefixes, wrong length or characters)."""
    kind = _KIND_BY_PREFIX.get(raw[:4])
    body = raw[4:]
    if kind is None or len(body) != BODY_LEN or not _ALPHABET.issuperset(body):
        return None
    return kind
