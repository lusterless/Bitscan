"""REQ-043 (1)-(4): TOTP seeds through OpenBao (Vault Transit API) (TASK-030).

Checks CHK-M2-080 to CHK-M2-085 of tests/m2/test-plan.md. Expected values:
decisions 2026-10-21 (OpenBao, POST /v1/transit/encrypt|decrypt/<key>, token
from BITSCAN_VAULT_TOKEN_FILE, TLS verified against the system CA store), #58
(any vault failure is one error the routes answer with 503; no seed, token or
vault reply in it). The fake vault is tests/fake_vault.py.
"""

import base64
import gc
import logging
import socket
import ssl
import time
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from bitscan_manager.auth.totp import new_seed, seed_to_base32
from bitscan_manager.auth.vault import VaultCipher, VaultUnavailable
from bitscan_manager.config.startup import ConfigError
from bitscan_manager.runtime import TotpCipher

from .canary import new_canary, sweep
from .certs import Leaf, Pki, make_pki
from .fake_sink import https_sink, server_context
from .fake_vault import FakeVault, fake_vault

TOKEN = new_canary("vaulttoken")
KEY = "bitscan-totp"


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("vpki"))


@pytest.fixture(scope="module")
def leaf(pki: Pki) -> Leaf:
    return pki.leaf("vault")


@pytest.fixture(scope="module")
def rogue(tmp_path_factory: pytest.TempPathFactory) -> Leaf:
    return make_pki(tmp_path_factory.mktemp("vpki2"), name="rogue").leaf("rogue")


@pytest.fixture
def trusted(pki: Pki) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(pki.ca))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


@pytest.fixture
def vault(leaf: Leaf) -> Iterator[FakeVault]:
    with fake_vault(server_context(leaf.cert, leaf.key), TOKEN) as v:
        yield v


def cipher(
    v: FakeVault, ctx: ssl.SSLContext | None, timeout_s: float = 5.0
) -> VaultCipher:
    return VaultCipher(
        f"https://127.0.0.1:{v.port}",
        KEY,
        SecretStr(TOKEN),
        timeout_s=timeout_s,
        ssl_context=ctx,
    )


def seed_forms(seed: bytes) -> list[str]:
    b32 = base64.b32encode(seed).decode()
    b64 = base64.b64encode(seed).decode()
    return [
        seed.decode("latin-1"),
        seed.hex(),
        seed.hex().upper(),
        b32,
        b32.rstrip("="),
        seed_to_base32(seed),
        b64,
        b64.rstrip("="),
        base64.urlsafe_b64encode(seed).decode(),
        base64.urlsafe_b64encode(seed).decode().rstrip("="),
    ]


# ------------------------------------------------------------ CHK-M2-080


def test_round_trip_and_the_transit_requests(
    vault: FakeVault, trusted: ssl.SSLContext
) -> None:
    c = cipher(vault, trusted)
    seeds = [new_seed() for _ in range(20)]
    texts = [c.encrypt(s) for s in seeds]
    assert [c.decrypt(t) for t in texts] == seeds
    c.close()
    enc = vault.requests[:20]
    dec = vault.requests[20:]
    assert all(r.path == f"/v1/transit/encrypt/{KEY}" for r in enc)
    assert all(r.path == f"/v1/transit/decrypt/{KEY}" for r in dec)
    for r, s in zip(enc, seeds, strict=True):
        assert r.headers["x-vault-token"] == TOKEN
        body = __import__("json").loads(r.body)
        assert body == {"plaintext": base64.b64encode(s).decode()}
    for r, t in zip(dec, texts, strict=True):
        assert __import__("json").loads(r.body) == {"ciphertext": t}
        assert r.headers["x-vault-token"] == TOKEN


def test_cipher_implements_the_runtime_protocol(
    vault: FakeVault, trusted: ssl.SSLContext
) -> None:
    proto: TotpCipher = cipher(vault, trusted)
    assert isinstance(proto.encrypt(b"x" * 20), str)


# ------------------------------------------------------------ CHK-M2-081


def test_ciphertext_holds_no_form_of_the_seed(
    vault: FakeVault, trusted: ssl.SSLContext
) -> None:
    c = cipher(vault, trusted)
    for _ in range(50):
        seed = new_seed()
        text = c.encrypt(seed)
        assert text.startswith("vault:v1:")
        assert text in vault.stored  # passed through unchanged, nothing appended
        for form in seed_forms(seed):
            assert form not in text


# ------------------------------------------------------------ CHK-M2-082


def test_untrusted_certificate_is_refused_and_nothing_reaches_the_vault(
    rogue: Leaf, trusted: ssl.SSLContext
) -> None:
    with fake_vault(server_context(rogue.cert, rogue.key), TOKEN) as v:
        for ctx in (trusted, None):  # our CA only; the system store only
            c = cipher(v, ctx)
            with pytest.raises(VaultUnavailable):
                c.encrypt(new_seed())
            c.close()
        assert v.requests == []


def test_wrong_host_name_is_refused(pki: Pki, trusted: ssl.SSLContext) -> None:
    wrong = pki.leaf("wrongname", sans="DNS:other.example")
    with fake_vault(server_context(wrong.cert, wrong.key), TOKEN) as v:
        c = cipher(v, trusted)
        with pytest.raises(VaultUnavailable):
            c.encrypt(new_seed())
        assert v.requests == []


def test_tls_below_1_2_is_refused(leaf: Leaf, trusted: ssl.SSLContext) -> None:
    ctx = server_context(leaf.cert, leaf.key, max_version=ssl.TLSVersion.TLSv1_1)
    with fake_vault(ctx, TOKEN) as v:
        c = VaultCipher(f"https://127.0.0.1:{v.port}", KEY, SecretStr(TOKEN))
        with pytest.raises(VaultUnavailable):
            c.encrypt(new_seed())
        assert v.requests == []


def test_default_context_is_the_system_store_with_tls_1_2(
    pki: Pki, leaf: Leaf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ssl_context the production context is used; the test CA is put
    in the store OpenSSL reads (SSL_CERT_FILE), so this exercises it."""
    monkeypatch.setenv("SSL_CERT_FILE", str(pki.ca))
    with fake_vault(server_context(leaf.cert, leaf.key), TOKEN) as v:
        c = VaultCipher(f"https://127.0.0.1:{v.port}", KEY, SecretStr(TOKEN))
        seed = new_seed()
        assert c.decrypt(c.encrypt(seed)) == seed


def test_redirect_is_not_followed_and_the_token_goes_nowhere_else(
    leaf: Leaf, trusted: ssl.SSLContext
) -> None:
    with https_sink(server_context(leaf.cert, leaf.key)) as other:
        with fake_vault(server_context(leaf.cert, leaf.key), TOKEN) as v:
            v.mode = "redirect"
            v.redirect_to = f"https://127.0.0.1:{other.port}/steal"
            c = cipher(v, trusted)
            with pytest.raises(VaultUnavailable):
                c.encrypt(new_seed())
    assert other.posts == []


def test_proxy_environment_is_ignored(
    vault: FakeVault, trusted: ssl.SSLContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    c = cipher(vault, trusted)
    seed = new_seed()
    assert c.decrypt(c.encrypt(seed)) == seed


# ------------------------------------------------------- CHK-M2-083, -084

FAILURES = [
    ("status", 403, b'{"errors":["permission denied CANARY"]}'),
    ("status", 500, b"internal CANARY"),
    ("status", 503, b'{"errors":["sealed CANARY"]}'),
    ("status", 307, b""),
    ("status", 204, b""),
    ("raw", 200, b"<html>CANARY</html>"),
    ("raw", 200, b'{"data": null}'),
    ("raw", 200, b'{"nodata": {"ciphertext": "vault:v1:CANARY"}}'),
    ("raw", 200, b'{"data": {"ciphertext": 5, "plaintext": 5}}'),
    ("raw", 200, b'{"data": {"ciphertext": "CANARY-not-vault", "plaintext": "!!!"}}'),
    ("raw", 200, b'{"data": {"ciphertext": "", "plaintext": ""}}'),
    ("raw", 200, b'{"data": ["CANARY"]}'),
    ("raw", 200, b"[]"),
]


@pytest.mark.parametrize(("mode", "status", "raw"), FAILURES)
@pytest.mark.parametrize("op", ["encrypt", "decrypt"])
def test_vault_failures_raise_one_clean_error(
    vault: FakeVault,
    trusted: ssl.SSLContext,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    status: int,
    raw: bytes,
    op: str,
) -> None:
    reply_canary = new_canary("reply")
    vault.mode, vault.status = mode, status
    vault.raw = raw.replace(b"CANARY", reply_canary.encode())
    c = cipher(vault, trusted)
    seed = new_seed()
    caplog.set_level(logging.DEBUG)
    with pytest.raises(VaultUnavailable) as info:
        if op == "encrypt":
            c.encrypt(seed)
        else:
            c.decrypt("vault:v1:" + base64.b64encode(seed).decode())
    exc = info.value
    assert exc.__cause__ is None and exc.__context__ is None
    out = capsys.readouterr()
    places = [exc, caplog.text, out.out, out.err, repr(c)]
    assert sweep([TOKEN, reply_canary, *seed_forms(seed)[1:]], *places) == []


def test_wrong_token_is_403_and_clean(
    vault: FakeVault, trusted: ssl.SSLContext
) -> None:
    other = new_canary("othertoken")
    c = VaultCipher(
        f"https://127.0.0.1:{vault.port}", KEY, SecretStr(other), ssl_context=trusted
    )
    with pytest.raises(VaultUnavailable) as info:
        c.encrypt(new_seed())
    assert sweep([other, TOKEN], info.value) == []


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


def test_closed_port_fails_within_the_timeout(trusted: ssl.SSLContext) -> None:
    c = VaultCipher(
        f"https://127.0.0.1:{free_port()}",
        KEY,
        SecretStr(TOKEN),
        timeout_s=1.0,
        ssl_context=trusted,
    )
    started = time.monotonic()
    with pytest.raises(VaultUnavailable) as info:
        c.encrypt(new_seed())
    assert time.monotonic() - started < 2.5
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert sweep([TOKEN], info.value) == []


def test_untrusted_certificate_error_is_not_chained(
    rogue: Leaf, trusted: ssl.SSLContext
) -> None:
    with fake_vault(server_context(rogue.cert, rogue.key), TOKEN) as v:
        c = cipher(v, trusted)
        with pytest.raises(VaultUnavailable) as info:
            c.encrypt(new_seed())
    assert info.value.__cause__ is None and info.value.__context__ is None


@pytest.mark.parametrize("status", [201, 202, 204, 400, 403, 404, 409, 429])
def test_any_status_but_200_fails_even_with_a_valid_looking_body(
    vault: FakeVault, trusted: ssl.SSLContext, status: int
) -> None:
    """A non-200 reply never yields a ciphertext or a seed, whatever its body."""
    vault.mode, vault.status = "status", status
    vault.raw = (
        b'{"data": {"ciphertext": "vault:v1:QUJDREVGR0hJSktM",'
        b' "plaintext": "QUJDREVGR0hJSktMTU5PUFFSU1Q="}}'
    )
    c = cipher(vault, trusted)
    with pytest.raises(VaultUnavailable):
        c.encrypt(new_seed())
    with pytest.raises(VaultUnavailable):
        c.decrypt("vault:v1:QUJDREVGR0hJSktM")


def test_hanging_vault_fails_within_the_timeout(
    vault: FakeVault, trusted: ssl.SSLContext
) -> None:
    vault.mode, vault.delay_s = "delay", 4.0
    c = cipher(vault, trusted, timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(VaultUnavailable):
        c.encrypt(new_seed())
    assert time.monotonic() - started < 2.5


def test_token_appears_only_in_the_vault_request(
    vault: FakeVault,
    trusted: ssl.SSLContext,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-043 (3): canary sweep over logs, repr of the cipher and its client."""
    caplog.set_level(logging.DEBUG)
    c = cipher(vault, trusted)
    seed = new_seed()
    c.decrypt(c.encrypt(seed))
    reprs = [repr(c), str(c)]
    reprs += [repr(v) for v in vars(c).values()]
    client = next(v for v in vars(c).values() if type(v).__name__ == "Client")
    reprs += [repr(client.headers), repr(dict(client.headers))]
    out = capsys.readouterr()
    assert (
        sweep([TOKEN, *seed_forms(seed)[1:]], caplog.text, out.out, out.err, *reprs)
        == []
    )
    assert all(r.headers.get("x-vault-token") == TOKEN for r in vault.requests)
    del c
    gc.collect()


# ------------------------------------------------------------ CHK-M2-085


@pytest.mark.parametrize(
    ("addr", "key", "token"),
    [
        ("http://vault.example", KEY, TOKEN),
        ("HTTP://vault.example", KEY, TOKEN),
        ("vault.example:8200", KEY, TOKEN),
        ("https://", KEY, TOKEN),
        (f"https://user:{TOKEN}@vault.example", KEY, TOKEN),
        ("https://vault.example?x=1", KEY, TOKEN),
        ("https://vault.example#f", KEY, TOKEN),
        ("https://vault.example", "", TOKEN),
        ("https://vault.example", "a/b", TOKEN),
        ("https://vault.example", "a b", TOKEN),
        ("https://vault.example", "a?b", TOKEN),
        ("https://vault.example", "..", TOKEN),
        ("https://vault.example", ".", TOKEN),
        ("https://vault.example", "k" * 129, TOKEN),
        ("https://vault.example", KEY, ""),
    ],
    # fixed ids: TOKEN is a fresh canary per process, so ids built from it
    # would differ between pytest-xdist workers and break the collection
    ids=[
        "http",
        "http-upper",
        "no-scheme",
        "no-host",
        "userinfo-token",
        "query",
        "fragment",
        "key-empty",
        "key-slash",
        "key-space",
        "key-query",
        "key-dotdot",
        "key-dot",
        "key-129",
        "token-empty",
    ],
)
def test_bad_configuration_is_refused_without_echoing_secrets(
    addr: str, key: str, token: str
) -> None:
    with pytest.raises(ConfigError) as info:
        VaultCipher(addr, key, SecretStr(token))
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert sweep([TOKEN], info.value) == []
    assert "BITSCAN_" in str(info.value)


def test_construction_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*a: object, **k: object) -> None:
        raise AssertionError("connected at construction")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    VaultCipher("https://vault.example:8200/", KEY, SecretStr(TOKEN)).close()
