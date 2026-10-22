"""REQ-040 (1), (2), REQ-044 (1) parser part: user token primitives (TASK-028).

Checks CHK-M2-060 to CHK-M2-063 of tests/m2/test-plan.md. Oracles are written
here with hashlib and base64. TS §6.2 L1083 (256 random bits, base64url,
prefix, SHA-256 only), TS §8.6 L1334 (redaction pattern 3), #56 (a) (no
padding: 43 characters).
"""

import ast
import base64
import hashlib
from pathlib import Path

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.auth import tokens
from bitscan_manager.auth.tokens import (
    PREFIXES,
    TokenKind,
    new_token,
    parse_user_token,
    token_hash,
)

URLSAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
REDACT = re2.compile(r"\bbs[aeku]_[A-Za-z0-9_-]{20,}")  # TS §8.6 pattern 3, verbatim


# ------------------------------------------------------------ CHK-M2-060


def test_prefixes_and_kinds() -> None:
    assert dict(PREFIXES) == {TokenKind.SESSION: "bsu_", TokenKind.API: "bsk_"}
    assert TokenKind.SESSION.value == "session"  # user_token.kind (TS §5.2 L969)
    assert TokenKind.API.value == "api"


@pytest.mark.parametrize(
    ("kind", "prefix"), [(TokenKind.SESSION, "bsu_"), (TokenKind.API, "bsk_")]
)
def test_ten_thousand_tokens(kind: TokenKind, prefix: str) -> None:
    made = [new_token(kind) for _ in range(10_000)]
    assert len(set(made)) == 10_000
    bodies = set()
    for tok in made:
        assert tok.startswith(prefix)
        assert len(tok) == 47
        body = tok[4:]
        assert len(body) == 43 and "=" not in body
        assert set(body) <= URLSAFE
        assert len(base64.urlsafe_b64decode(body + "=")) == 32
        match = REDACT.search(tok)
        assert match is not None and match.group(0) == tok
        assert parse_user_token(tok) is kind
        bodies.add(body)
    assert len(bodies) == 10_000


def test_bodies_look_uniformly_random() -> None:
    """A weak or constant source would skew the byte distribution."""
    raw = b"".join(
        base64.urlsafe_b64decode(new_token(TokenKind.API)[4:] + "=")
        for _ in range(2000)
    )
    counts = [raw.count(bytes([b])) for b in range(256)]
    expected = len(raw) / 256  # 250
    assert min(counts) > expected * 0.6
    assert max(counts) < expected * 1.4


# ------------------------------------------------------------ CHK-M2-061


def test_body_is_the_csprng_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = bytes(range(32))
    asked: list[int | None] = []

    def token_bytes(n: int | None = None) -> bytes:
        asked.append(n)
        return fixed

    monkeypatch.setattr("bitscan_manager.auth.tokens.secrets.token_bytes", token_bytes)
    tok = new_token(TokenKind.SESSION)
    assert asked == [32]
    assert tok == "bsu_" + base64.urlsafe_b64encode(fixed).decode().rstrip("=")


def test_module_uses_no_non_cryptographic_random() -> None:
    tree = ast.parse(Path(tokens.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert "random" not in names and "numpy" not in names
    assert "secrets" in names


# ------------------------------------------------------------ CHK-M2-062

KNOWN = "bsu_" + "A" * 43


def test_hash_is_lowercase_sha256_of_the_whole_string() -> None:
    expected = hashlib.sha256(KNOWN.encode("ascii")).hexdigest()
    assert token_hash(KNOWN) == expected
    assert len(expected) == 64 and expected == expected.lower()
    assert token_hash(KNOWN) != hashlib.sha256(("A" * 43).encode()).hexdigest()
    assert token_hash(KNOWN) != hashlib.sha1(KNOWN.encode()).hexdigest()  # noqa: S324


def test_hash_known_answer() -> None:
    """Fixed vector computed independently: sha256("bsk_" + 43 x "0")."""
    tok = "bsk_" + "0" * 43
    assert token_hash(tok) == hashlib.sha256(b"bsk_" + b"0" * 43).hexdigest()
    a, b = new_token(TokenKind.API), new_token(TokenKind.API)
    assert token_hash(a) != token_hash(b)
    assert token_hash(a) == token_hash(a)


# ------------------------------------------------------------ CHK-M2-063

GOOD_BODY = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJ0123-_Z"


def test_good_body_is_43_chars() -> None:
    assert len(GOOD_BODY) == 43
    assert parse_user_token("bsu_" + GOOD_BODY) is TokenKind.SESSION
    assert parse_user_token("bsk_" + GOOD_BODY) is TokenKind.API


@pytest.mark.parametrize(
    "raw",
    [
        "bsa_" + GOOD_BODY,
        "bse_" + GOOD_BODY,
        "BSU_" + GOOD_BODY,
        "Bsk_" + GOOD_BODY,
        "bsx_" + GOOD_BODY,
        "bsu" + GOOD_BODY,
        "bsu-" + GOOD_BODY,
        GOOD_BODY,
        "",
        "bsu_",
        "bsk_",
        "bsu_" + GOOD_BODY[:-1],
        "bsu_" + GOOD_BODY + "A",
        "bsu_" + GOOD_BODY[:-1] + "=",
        "bsu_" + GOOD_BODY[:-1] + "+",
        "bsu_" + GOOD_BODY[:-1] + "/",
        "bsu_" + GOOD_BODY[:-1] + " ",
        "bsu_" + GOOD_BODY[:-1] + "é",
        "bsu_" + GOOD_BODY[:-1] + "\x00",
        "bsu_" + GOOD_BODY[:-1] + "\n",
        " bsu_" + GOOD_BODY[:-1],
        "bsu_" + "Ａ" * 43,  # noqa: RUF001  full-width letters
        "bsu_" + "A" * 10_000,
    ],
)
def test_parser_refuses(raw: str) -> None:
    assert parse_user_token(raw) is None


def test_long_garbage_is_refused_quickly() -> None:
    import time

    started = time.perf_counter()
    for _ in range(1000):
        assert parse_user_token("bsu_" + "A" * 100_000) is None
    assert time.perf_counter() - started < 2
