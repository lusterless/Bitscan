"""REQ-042 (1), (2), (4), (5): TOTP core with the #49 parameters (TASK-029).

Checks CHK-M2-070 to CHK-M2-075 of tests/m2/test-plan.md. Expected codes are the
published vectors of RFC 6238 Appendix B (SHA1) and RFC 4226 Appendix D, not
values computed by the implementation. Single use (REQ-042 (2) second half and
(3)) is the caller's job and is tested with TASK-031 and TASK-038.
"""

import base64
import hmac
import os
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from bitscan_manager.auth import totp

RFC_SEED = b"12345678901234567890"
# RFC 6238 Appendix B, SHA1 column: (T, 8-digit TOTP).
RFC6238_SHA1 = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]
# RFC 4226 Appendix D: HOTP values for counters 0..9 with the same secret.
RFC4226 = [
    "755224",
    "287082",
    "359152",
    "969429",
    "338314",
    "254676",
    "287922",
    "162583",
    "399871",
    "520489",
]
# A seed whose codes for steps COLLIDE_STEP and COLLIDE_STEP + 1 are equal
# (found by brute force with an independent HOTP; re-checked below).
COLLIDE_SEED = (263342).to_bytes(20, "big")
COLLIDE_STEP = 55_000_000
COLLIDE_CODE = "232630"


def at(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


# ------------------------------------------------------------ CHK-M2-070


@pytest.mark.parametrize(("t", "code8"), RFC6238_SHA1)
def test_rfc6238_appendix_b_sha1_eight_digits(t: int, code8: str) -> None:
    assert totp.step_at(at(t)) == t // 30
    assert totp.code_at(RFC_SEED, t // 30, digits=8) == code8


@pytest.mark.parametrize(("t", "code8"), RFC6238_SHA1)
def test_rfc6238_vectors_with_six_digits(t: int, code8: str) -> None:
    """#49 (a): 6 digits is the same truncation mod 10^6 (leading zeros kept)."""
    code6 = code8[-6:]
    assert totp.code_at(RFC_SEED, t // 30) == code6
    assert len(totp.code_at(RFC_SEED, t // 30)) == 6
    assert totp.match_step(RFC_SEED, code6, at(t)) == t // 30


@pytest.mark.parametrize(("counter", "code"), list(enumerate(RFC4226)))
def test_rfc4226_appendix_d_hotp(counter: int, code: str) -> None:
    assert totp.code_at(RFC_SEED, counter) == code


def test_parameters_are_the_49_defaults() -> None:
    assert (totp.SEED_BYTES, totp.DIGITS, totp.PERIOD_S, totp.WINDOW_STEPS) == (
        20,
        6,
        30,
        1,
    )


# ------------------------------------------------------------ CHK-M2-071

NOW = at(1_700_000_015)  # inside step 56,666,667
STEP = 1_700_000_015 // 30


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_codes_inside_the_window_return_their_step(delta: int) -> None:
    code = totp.code_at(RFC_SEED, STEP + delta)
    assert totp.match_step(RFC_SEED, code, NOW) == STEP + delta


@pytest.mark.parametrize("delta", [-3, -2, 2, 3])
def test_codes_outside_the_window_are_refused(delta: int) -> None:
    code = totp.code_at(RFC_SEED, STEP + delta)
    # Guard: the outside code must not equal one inside, or the case is moot.
    inside = {totp.code_at(RFC_SEED, STEP + d) for d in (-1, 0, 1)}
    assert code not in inside
    assert totp.match_step(RFC_SEED, code, NOW) is None


def test_step_boundaries() -> None:
    k = 56_666_667
    assert totp.step_at(at(k * 30 - 1)) == k - 1
    assert totp.step_at(at(k * 30)) == k
    assert totp.step_at(at(k * 30 + 29.999)) == k
    # A code for step k + 1 is refused in the last second of step k - 1 and
    # accepted from the first second of step k (window is current ± 1).
    code = totp.code_at(RFC_SEED, k + 1)
    assert totp.match_step(RFC_SEED, code, at(k * 30 - 1)) is None
    assert totp.match_step(RFC_SEED, code, at(k * 30)) == k + 1


def test_newest_matching_step_wins() -> None:
    oracle = [totp.code_at(COLLIDE_SEED, COLLIDE_STEP + d) for d in (0, 1)]
    assert oracle == [COLLIDE_CODE, COLLIDE_CODE]
    now = at((COLLIDE_STEP + 1) * 30 + 5)
    assert totp.match_step(COLLIDE_SEED, COLLIDE_CODE, now) == COLLIDE_STEP + 1


def test_non_utc_aware_time_is_the_same_instant() -> None:
    plus8 = NOW.astimezone(timezone(timedelta(hours=8)))
    code = totp.code_at(RFC_SEED, STEP)
    assert totp.match_step(RFC_SEED, code, plus8) == STEP


# ------------------------------------------------------------ CHK-M2-072


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "12345",
        "1234567",
        "12345a",
        " 123456",
        "123456 ",
        "123 456",
        "12345\n",
        "+12345",
        "-12345",
        "１２３４５６",  # noqa: RUF001  full-width digits (str.isdigit() is True)
        "١٢٣٤٥٦",  # Arabic-Indic digits
        "۱۲۳۴۵۶",  # Extended Arabic-Indic digits
        "1" * 10_000,
    ],
)
def test_malformed_codes_are_refused_without_hmac_work(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    calls: list[int] = []
    real = totp.code_at

    def counting(seed: bytes, step: int, digits: int = 6) -> str:
        calls.append(step)
        return real(seed, step, digits)

    monkeypatch.setattr(totp, "code_at", counting)
    assert totp.match_step(RFC_SEED, bad, NOW) is None
    assert calls == []


def test_a_correct_code_padded_to_seven_digits_is_refused() -> None:
    code = totp.code_at(RFC_SEED, STEP)
    assert totp.match_step(RFC_SEED, "0" + code, NOW) is None
    assert totp.match_step(RFC_SEED, code[1:], NOW) is None


# ------------------------------------------------------------ CHK-M2-073


class Spy:
    def __init__(self) -> None:
        self.calls = 0
        self.real = hmac.compare_digest

    def __call__(self, a: bytes, b: bytes) -> bool:
        self.calls += 1
        return self.real(a, b)


@pytest.mark.parametrize("delta", [-1, 0, 1, None])
def test_compare_digest_on_every_candidate_no_early_exit(
    monkeypatch: pytest.MonkeyPatch, delta: int | None
) -> None:
    """REQ-042 (5): 2 x window + 1 constant-time comparisons, match or not."""
    spy = Spy()
    monkeypatch.setattr("bitscan_manager.auth.totp.hmac.compare_digest", spy)
    if delta is None:
        inside = {totp.code_at(RFC_SEED, STEP + d) for d in (-1, 0, 1)}
        code = next(f"{n:06d}" for n in range(10**6) if f"{n:06d}" not in inside)
        expected: int | None = None
    else:
        code = totp.code_at(RFC_SEED, STEP + delta)
        expected = STEP + delta
    assert totp.match_step(RFC_SEED, code, NOW) == expected
    assert spy.calls == 3


def test_equality_operator_is_not_the_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With compare_digest forced to say "no", a right code must not match."""
    monkeypatch.setattr(
        "bitscan_manager.auth.totp.hmac.compare_digest", lambda a, b: False
    )
    assert totp.match_step(RFC_SEED, totp.code_at(RFC_SEED, STEP), NOW) is None


# ------------------------------------------------------------ CHK-M2-074


def test_new_seed_is_20_csprng_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = bytes(range(1, 21))
    asked: list[int | None] = []

    def token_bytes(n: int | None = None) -> bytes:
        asked.append(n)
        return fixed[: n or 32]

    # secrets.token_bytes is the OS CSPRNG (os.urandom via SystemRandom).
    monkeypatch.setattr("bitscan_manager.auth.totp.secrets.token_bytes", token_bytes)
    assert totp.new_seed() == fixed
    assert asked == [20]
    monkeypatch.undo()
    assert os.urandom is not None
    seeds = {totp.new_seed() for _ in range(1000)}
    assert len(seeds) == 1000
    assert all(len(s) == 20 for s in seeds)


def test_base32_has_no_padding_and_round_trips() -> None:
    seed = bytes(range(20))
    text = totp.seed_to_base32(seed)
    assert "=" not in text
    assert len(text) == 32
    assert base64.b32decode(text) == seed
    assert text == base64.b32encode(seed).decode()


@pytest.mark.parametrize("username", ["alice", "a b@x.example", "a&secret=AAAA#x", "é"])
def test_provisioning_uri(username: str) -> None:
    seed = bytes(range(20))
    uri = totp.provisioning_uri(seed, username)
    parts = urlsplit(uri)
    assert parts.scheme == "otpauth"
    assert parts.netloc == "totp"
    assert unquote(parts.path) == f"/Bitscan:{username}"
    assert parts.fragment == ""
    query = parse_qs(parts.query, strict_parsing=True)
    assert query["secret"] == [totp.seed_to_base32(seed)]
    assert query["issuer"] == ["Bitscan"]
    assert query.get("algorithm", ["SHA1"]) == ["SHA1"]
    assert query.get("digits", ["6"]) == ["6"]
    assert query.get("period", ["30"]) == ["30"]
    assert set(query) <= {"secret", "issuer", "algorithm", "digits", "period"}
    padded = query["secret"][0] + "=" * (-len(query["secret"][0]) % 8)
    assert base64.b32decode(padded) == seed


# ------------------------------------------------------------ CHK-M2-075


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError):
        totp.step_at(datetime(2026, 10, 21, 12, 0, 0))  # noqa: DTZ001
    with pytest.raises(ValueError):
        totp.match_step(RFC_SEED, "123456", datetime(2026, 10, 21))  # noqa: DTZ001


def test_module_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network, no logging: the module imports only the standard library."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(totp.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = {
        "base64",
        "hashlib",
        "hmac",
        "secrets",
        "struct",
        "datetime",
        "typing",
        "urllib",
    }
    assert imported <= allowed, imported - allowed
