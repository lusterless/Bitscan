"""TOTP (RFC 6238 over RFC 4226 HOTP) with the #49 parameters.

Pure and standard library only (PD-19 (f)). Single use of a code is the
caller's job: it stores the returned step in app_user.totp_last_step.
"""

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from typing import Final
from urllib.parse import quote, urlencode

SEED_BYTES: Final = 20
DIGITS: Final = 6
PERIOD_S: Final = 30
WINDOW_STEPS: Final = 1
ISSUER: Final = "Bitscan"


def new_seed() -> bytes:
    return secrets.token_bytes(SEED_BYTES)


def seed_to_base32(seed: bytes) -> str:
    return base64.b32encode(seed).decode("ascii").rstrip("=")


def provisioning_uri(seed: bytes, username: str, issuer: str = ISSUER) -> str:
    label = quote(f"{issuer}:{username}", safe="")
    query = urlencode(
        {
            "secret": seed_to_base32(seed),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD_S,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{query}"


def step_at(now: datetime) -> int:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return int(now.timestamp()) // PERIOD_S


def code_at(seed: bytes, step: int, digits: int = DIGITS) -> str:
    mac = hmac.new(seed, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def match_step(seed: bytes, code: str, now: datetime) -> int | None:
    """Newest step within ±WINDOW_STEPS of now whose code equals code, else None."""
    current = step_at(now)
    if len(code) != DIGITS or not (code.isascii() and code.isdigit()):
        return None
    given = code.encode("ascii")
    matched: int | None = None
    for step in range(current - WINDOW_STEPS, current + WINDOW_STEPS + 1):
        if hmac.compare_digest(code_at(seed, step).encode("ascii"), given):
            matched = step
    return matched
