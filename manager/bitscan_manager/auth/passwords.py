"""Argon2id passwords (TS §6.2 L1087, §5.2 app_user.password_hash; #56).

At least 12 and at most 1,024 characters, counted as Unicode code points, no
normalisation. Parameters: RFC 9106 low-memory profile (t=3, m=64 MiB, p=4),
recorded in each PHC string so they can be raised later. No message or error
here ever holds a password or a hash.
"""

from functools import cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

MIN_LEN: Final = 12
MAX_LEN: Final = 1024

_HASHER: Final = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)


class PasswordRejected(ValueError):
    """Names the rule that failed, never the value."""


def check_new_password(password: str) -> None:
    if len(password) < MIN_LEN:
        raise PasswordRejected(f"password must be at least {MIN_LEN} characters")
    if len(password) > MAX_LEN:
        raise PasswordRejected(f"password must be at most {MAX_LEN} characters")
    encodable = True
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        encodable = False
    # Raised outside the except block: the UnicodeEncodeError holds the whole
    # password as .object and must not become __context__.
    if not encodable:
        raise PasswordRejected("password must be valid Unicode text")


def _bytes(password: str) -> bytes:
    # Never raises: a lone surrogate cannot match a stored hash anyway, and the
    # verification still costs one Argon2id run.
    return password.encode("utf-8", "surrogatepass")


def hash_password(password: str) -> str:
    """Hash a password that passed check_new_password()."""
    check_new_password(password)
    return _HASHER.hash(_bytes(password))


def verify_password(stored: str, password: str) -> bool:
    """True only for the exact password; False for a mismatch or a malformed
    stored hash. Never raises on bad input."""
    try:
        return _HASHER.verify(stored, _bytes(password))
    except (VerificationError, InvalidHashError):
        return False


@cache
def _dummy_hash() -> str:
    return _HASHER.hash(b"bitscan dummy password for equal timing")


def dummy_verify(password: str) -> None:
    """One verification against a fixed hash with the same parameters, so an
    unknown user or a back-off costs as much as a wrong password."""
    verify_password(_dummy_hash(), password)
