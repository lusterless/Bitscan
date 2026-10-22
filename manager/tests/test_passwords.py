"""REQ-041 (1)-(5), REQ-048 (2): Argon2id passwords (TASK-028).

Checks CHK-M2-064 to CHK-M2-068 of tests/m2/test-plan.md. TS §6.2 L1087
(Argon2id, at least 12 characters), #56 (b) (at most 1,024 code points, no
normalisation), #56 (c) (RFC 9106 low-memory profile: t=3, m=65536 KiB, p=4).
The hash is recomputed with argon2.low_level, independent of the module.
"""

import base64
import logging
import statistics
import time
import unicodedata
from typing import Any

import pytest
from argon2.low_level import Type, hash_secret_raw

from bitscan_manager.auth import passwords
from bitscan_manager.auth.passwords import (
    PasswordRejected,
    check_new_password,
    dummy_verify,
    hash_password,
    verify_password,
)

CANARY = "CANARY-pw-0f1e2d3c4b5a6978"


def b64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4))


def phc(stored: str) -> tuple[str, str, dict[str, int], bytes, bytes]:
    empty, alg, version, params, salt, digest = stored.split("$")
    assert empty == ""
    values = {k: int(v) for k, v in (p.split("=") for p in params.split(","))}
    return alg, version, values, b64(salt), b64(digest)


# ------------------------------------------------------------ CHK-M2-064


@pytest.mark.parametrize("password", ["correct horse battery", "é" * 12, "😀" * 12])
def test_hash_is_argon2id_with_the_56_parameters(password: str) -> None:
    stored = hash_password(password)
    alg, version, params, salt, digest = phc(stored)
    assert stored.startswith("$argon2id$")
    assert (alg, version) == ("argon2id", "v=19")
    assert params == {"m": 65536, "t": 3, "p": 4}
    assert len(salt) >= 16
    recomputed = hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=len(digest),
        type=Type.ID,
    )
    assert recomputed == digest


def test_dummy_hash_uses_the_same_parameters() -> None:
    _, _, params, _, _ = phc(passwords._dummy_hash())  # noqa: SLF001
    assert params == {"m": 65536, "t": 3, "p": 4}


# ------------------------------------------------------------ CHK-M2-065


def test_verify_only_the_exact_password() -> None:
    pw = "Exact Password 1"
    stored = hash_password(pw)
    assert verify_password(stored, pw) is True
    for wrong in (
        pw + " ",
        " " + pw,
        pw.lower(),
        pw.upper(),
        pw[:-1],
        pw + "1",
        "",
        "x" * 12,
    ):
        assert verify_password(stored, wrong) is False, wrong


def test_no_normalisation() -> None:
    nfc = unicodedata.normalize("NFC", "café-passwörd-ü")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    stored = hash_password(nfc)
    assert verify_password(stored, nfc) is True
    assert verify_password(stored, nfd) is False


def test_two_hashes_differ_by_salt() -> None:
    a, b = hash_password("same password!"), hash_password("same password!")
    assert a != b
    assert phc(a)[3] != phc(b)[3]
    assert verify_password(a, "same password!") and verify_password(b, "same password!")


@pytest.mark.parametrize(
    "stored", ["", "not a hash", "$argon2id$v=19$m=65536,t=3,p=4$", "$2b$12$abc"]
)
def test_malformed_stored_hash_is_false_not_an_error(stored: str) -> None:
    assert verify_password(stored, "whatever password") is False


def test_lone_surrogate_password_verifies_false() -> None:
    stored = hash_password("a normal password")
    assert verify_password(stored, "\ud800" * 12) is False


# ------------------------------------------------------------ CHK-M2-066


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("a" * 11, False),
        ("a" * 12, True),
        ("😀" * 11, False),  # 44 UTF-8 bytes, 11 code points
        ("😀" * 12, True),
        ("é" * 5 + "a", False),  # 11 code points
        ("é" * 6, True),  # 12 code points
        ("x" * 1024, True),
        ("x" * 1025, False),
        ("😀" * 1024, True),
        ("😀" * 1025, False),
        ("", False),
        ("\ud800" * 12, False),
    ],
)
def test_length_rule_counts_code_points(password: str, ok: bool) -> None:
    if ok:
        check_new_password(password)
        if len(password) <= 1024:
            assert hash_password(password).startswith("$argon2id$")
    else:
        with pytest.raises(PasswordRejected):
            check_new_password(password)
        with pytest.raises(PasswordRejected):
            hash_password(password)


def test_rejection_message_names_the_rule_not_the_value() -> None:
    for bad in (CANARY[:11], CANARY * 100, "\ud800" * 12 + CANARY):
        with pytest.raises(PasswordRejected) as info:
            check_new_password(bad)
        assert CANARY[:11] not in str(info.value)
        assert info.value.__cause__ is None and info.value.__context__ is None
        assert "password" in str(info.value)


# ------------------------------------------------------------ CHK-M2-067


class CountingHasher:
    def __init__(self, real: Any) -> None:
        self.real = real
        self.verifies = 0

    def hash(self, password: bytes) -> str:
        return str(self.real.hash(password))

    def verify(self, stored: str, password: bytes) -> bool:
        self.verifies += 1
        return bool(self.real.verify(stored, password))


def test_dummy_verify_runs_exactly_one_argon2_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = CountingHasher(passwords._HASHER)  # noqa: SLF001
    monkeypatch.setattr(passwords, "_HASHER", counter)
    passwords._dummy_hash()  # noqa: SLF001  warm the cache
    counter.verifies = 0
    dummy_verify("any password at all")
    assert counter.verifies == 1
    dummy_verify("bitscan dummy password for equal timing")
    assert counter.verifies == 2


def test_dummy_verify_costs_about_a_wrong_password() -> None:
    """Reported, not gated tightly: median times within 0.33x-3x."""
    stored = hash_password("the real password")
    dummy_verify("warm up")

    def median(fn: Any) -> float:
        times = []
        for _ in range(5):
            t = time.perf_counter()
            fn()
            times.append(time.perf_counter() - t)
        return statistics.median(times)

    wrong = median(lambda: verify_password(stored, "a wrong password"))
    dummy = median(lambda: dummy_verify("a wrong password"))
    print(f"wrong={wrong:.3f}s dummy={dummy:.3f}s")
    assert wrong / 3 < dummy < wrong * 3
    assert dummy > 0.01  # a real Argon2id run, not a shortcut


# ------------------------------------------------------------ CHK-M2-068


def test_no_password_or_hash_is_logged(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    with caplog.at_level(logging.DEBUG):
        stored = hash_password(CANARY)
        verify_password(stored, CANARY)
        verify_password(stored, CANARY + "x")
        dummy_verify(CANARY)
        with pytest.raises(PasswordRejected):
            hash_password(CANARY[:5])
    out = capsys.readouterr()
    for text in (caplog.text, out.out, out.err):
        assert CANARY not in text
        assert CANARY[:5] not in text
        assert stored not in text
