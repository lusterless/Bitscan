"""Tokens (TS §6.2 L1083, §2.3): bsu_ sessions and bsk_ API tokens for users,
bsa_ agent tokens and bse_ enrolment tokens for agents.

A token is its prefix plus the unpadded base64url of 32 CSPRNG bytes (43
characters, #56 (a)). Only the lowercase SHA-256 hex of the whole token string
is stored. The user-route parser accepts only bsu_ and bsk_; the agent-route
check accepts only the one agent prefix it is asked for.
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


class AgentTokenKind(StrEnum):
    """bsa_ on the five agent routes, bse_ only on POST /agent/enroll."""

    AGENT = "agent"
    ENROLMENT = "enrolment"


PREFIXES: Final = {TokenKind.SESSION: "bsu_", TokenKind.API: "bsk_"}
_KIND_BY_PREFIX: Final = {prefix: kind for kind, prefix in PREFIXES.items()}
AGENT_PREFIXES: Final = {AgentTokenKind.AGENT: "bsa_", AgentTokenKind.ENROLMENT: "bse_"}


def _random_body() -> str:
    body = base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).rstrip(b"=")
    return body.decode("ascii")


def _well_formed(body: str) -> bool:
    return len(body) == BODY_LEN and _ALPHABET.issuperset(body)


def new_token(kind: TokenKind) -> str:
    return PREFIXES[kind] + _random_body()


def new_agent_token(kind: AgentTokenKind) -> str:
    return AGENT_PREFIXES[kind] + _random_body()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_user_token(raw: str) -> TokenKind | None:
    """The kind for a well-formed bsu_ or bsk_ token, else None (bsa_, bse_,
    unknown prefixes, wrong length or characters)."""
    kind = _KIND_BY_PREFIX.get(raw[:4])
    if kind is None or not _well_formed(raw[4:]):
        return None
    return kind


def is_agent_token(raw: str, kind: AgentTokenKind) -> bool:
    """True only for a well-formed token with kind's prefix: a bse_ is refused
    where a bsa_ is asked for and the other way round, and bsu_ and bsk_ always."""
    return raw[:4] == AGENT_PREFIXES[kind] and _well_formed(raw[4:])
