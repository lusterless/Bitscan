"""REQ-053 (1), (3), (4): audit sink transports (TASK-032).

Checks CHK-M2-100 to CHK-M2-106 of tests/m2/test-plan.md. Expected values:
#24 and decisions 2026-10-21 (syslog+tls: RFC 5424 message, RFC 5425
octet-counted framing; https: one entry per POST, one JSON object, a 2xx
acknowledges exactly that entry; plain udp, tcp, http refused). The test CA is
trusted through SSL_CERT_FILE, so the production context (system store, TLS
1.2 minimum) is the one under test; ssl_context is not passed.
"""

import json
import logging
import socket
import ssl
import time
import traceback
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from bitscan_manager.config.startup import ConfigError
from bitscan_manager.services.audit.chain import (
    GENESIS_PREV_HASH,
    HashInput,
    compute_row_hash,
)
from bitscan_manager.services.audit.sink_transport import (
    DeliveryError,
    SinkRecord,
    transport_from_url,
)

from .certs import Leaf, Pki, make_pki
from .fake_sink import https_sink, server_context, syslog_sink, wait_for

CANARY = "CANARY-sink-6c2e9a1f0b4d8e37"
FIELDS = {
    "audit_id",
    "actor",
    "action",
    "target",
    "detail_text",
    "at_text",
    "prev_hash",
    "row_hash",
}
BOM = b"\xef\xbb\xbf"


def chain(n: int, detail_of: object = None) -> list[SinkRecord]:
    """n records whose row_hash is the real #38 hash, linked by prev_hash."""
    out: list[SinkRecord] = []
    prev = GENESIS_PREV_HASH
    for i in range(1, n + 1):
        target = None if i % 2 else f"user:{i}"
        detail = [None, '{"n": 1}', '{"note": "é ü 😀", "x": {"y": [1, 2]}}'][i % 3]
        if callable(detail_of):
            detail = detail_of(i)
        at = f"2026-10-21T10:00:{i % 60:02d}.{i:06d}Z"
        row = compute_row_hash(
            prev, HashInput(i, "user:1", "user.create", target, detail, at)
        )
        out.append(
            SinkRecord(i, "user:1", "user.create", target, detail, at, prev, row)
        )
        prev = row
    return out


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("pki"))


@pytest.fixture(scope="module")
def good(pki: Pki) -> Leaf:
    return pki.leaf("sink")


@pytest.fixture(scope="module")
def wrong_name(pki: Pki) -> Leaf:
    return pki.leaf("other", sans="DNS:other.example")


@pytest.fixture(scope="module")
def untrusted(tmp_path_factory: pytest.TempPathFactory) -> Leaf:
    return make_pki(tmp_path_factory.mktemp("pki2"), name="rogue").leaf("rogue")


@pytest.fixture
def trust(pki: Pki, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SSL_CERT_FILE", str(pki.ca))
    yield


def parse_5424(frame: bytes) -> dict[str, object]:
    """RFC 5424 §6: HEADER SP STRUCTURED-DATA [SP MSG]."""
    head, sep, msg = frame.partition(BOM)
    assert sep == BOM, "MSG must start with the UTF-8 BOM (RFC 5424 §6.4)"
    text = head.decode("ascii")
    assert text.endswith(" ")
    pri_version, timestamp, hostname, app, procid, msgid, sd = text[:-1].split(" ")
    assert pri_version.startswith("<") and ">" in pri_version
    pri_text, version = pri_version[1:].split(">")
    assert pri_text.isdigit() and 0 <= int(pri_text) <= 191
    assert version == "1"
    assert datetime.fromisoformat(timestamp).utcoffset() is not None
    for value, limit in ((hostname, 255), (app, 48), (procid, 128), (msgid, 32)):
        assert 1 <= len(value) <= limit
        assert all(33 <= ord(c) <= 126 for c in value), value
    assert sd == "-"
    return {
        "pri": int(pri_text),
        "timestamp": timestamp,
        "app": app,
        "msgid": msgid,
        "body": json.loads(msg.decode("utf-8")),
    }


# ------------------------------------------------- CHK-M2-100 syslog+tls


def test_syslog_frames_are_rfc5425_and_rfc5424(good: Leaf, trust: None) -> None:
    records = chain(5)
    with syslog_sink(server_context(good.cert, good.key)) as sink:
        transport = transport_from_url(f"syslog+tls://127.0.0.1:{sink.port}")
        transport.send(records)
        transport.close()
        assert wait_for(lambda: len(sink.raw) == 1)
    frames = sink.frames()
    assert len(frames) == 5
    for frame, record in zip(frames, records, strict=True):
        parsed = parse_5424(frame)
        body = parsed["body"]
        assert isinstance(body, dict)
        assert set(body) == FIELDS
        assert SinkRecord.from_wire(body) == record
        assert parsed["timestamp"] == record.at_text
        assert parsed["msgid"] == "user.create"
    assert [parse_5424(f)["body"]["audit_id"] for f in frames] == [1, 2, 3, 4, 5]  # type: ignore[index]


def test_syslog_frame_length_counts_bytes(good: Leaf, trust: None) -> None:
    records = chain(3, detail_of=lambda i: json.dumps({"t": "é" * 50 + "😀"}))
    with syslog_sink(server_context(good.cert, good.key)) as sink:
        t = transport_from_url(f"syslog+tls://127.0.0.1:{sink.port}")
        t.send(records)
        t.close()
        assert wait_for(lambda: len(sink.raw) == 1)
    frames = sink.frames()  # split_frames asserts MSG-LEN equals the byte length
    assert [SinkRecord.from_wire(parse_5424(f)["body"]) for f in frames] == records  # type: ignore[arg-type]


def test_syslog_keeps_one_connection_and_reconnects_after_an_error(
    good: Leaf, trust: None
) -> None:
    with syslog_sink(server_context(good.cert, good.key)) as sink:
        t = transport_from_url(f"syslog+tls://127.0.0.1:{sink.port}")
        t.send(chain(2))
        t.send(chain(4)[2:])
        assert sink.connections == 1
        t.close()
        t.send(chain(5)[4:])  # a new connection after close
        t.close()
        assert wait_for(lambda: len(sink.raw) == 2)
    assert len(sink.frames()) == 5


# ------------------------------------------------------ CHK-M2-101 https


def test_https_posts_one_json_object_per_entry(good: Leaf, trust: None) -> None:
    records = chain(4)
    with https_sink(server_context(good.cert, good.key)) as sink:
        t = transport_from_url(f"https://127.0.0.1:{sink.port}/audit")
        t.send(records)
        t.close()
    assert len(sink.posts) == 4
    for post, record in zip(sink.posts, records, strict=True):
        assert post.path == "/audit"
        assert post.headers["content-type"].split(";")[0] == "application/json"
        body = json.loads(post.body)
        assert isinstance(body, dict)  # one object, never an array
        assert set(body) == FIELDS
        assert SinkRecord.from_wire(body) == record
        assert "authorization" not in post.headers  # no credential (#24)


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_each_2xx_acknowledges_its_entry(good: Leaf, trust: None, status: int) -> None:
    with https_sink(server_context(good.cert, good.key), statuses=(status,)) as sink:
        t = transport_from_url(f"https://127.0.0.1:{sink.port}/a")
        t.send(chain(3))
        t.close()
    assert len(sink.posts) == 3


@pytest.mark.parametrize(
    ("statuses", "delivered"),
    [
        ((200, 204, 500), 2),
        ((500,), 0),
        ((200, 307, 200), 1),
        ((200, 308, 200), 1),
        ((200, 301, 200), 1),
        ((200, 400), 1),
        ((404,), 0),
    ],
)
def test_non_2xx_stops_and_reports_the_acknowledged_prefix(
    good: Leaf, trust: None, statuses: tuple[int, ...], delivered: int
) -> None:
    body = f"error page {CANARY}".encode()
    with https_sink(
        server_context(good.cert, good.key), statuses=statuses, response_body=body
    ) as sink:
        t = transport_from_url(f"https://127.0.0.1:{sink.port}/a")
        with pytest.raises(DeliveryError) as info:
            t.send(chain(5))
        t.close()
    assert info.value.delivered == delivered
    assert len(sink.posts) == delivered + 1  # stops at the failing entry
    assert_clean(info.value)
    assert all(p.path == "/a" for p in sink.posts)  # a 301 is not followed


# ------------------------------------------------------ CHK-M2-102 rehash


@pytest.mark.parametrize("scheme", ["syslog+tls", "https"])
def test_delivered_fields_rehash_to_row_hash_and_chain(
    good: Leaf, trust: None, scheme: str
) -> None:
    records = chain(9)
    if scheme == "https":
        with https_sink(server_context(good.cert, good.key)) as sink:
            t = transport_from_url(f"https://127.0.0.1:{sink.port}/a")
            t.send(records)
            t.close()
        delivered = [json.loads(p.body) for p in sink.posts]
    else:
        with syslog_sink(server_context(good.cert, good.key)) as ssink:
            t = transport_from_url(f"syslog+tls://127.0.0.1:{ssink.port}")
            t.send(records)
            t.close()
            assert wait_for(lambda: len(ssink.raw) == 1)
        delivered = [parse_5424(f)["body"] for f in ssink.frames()]
    prev = GENESIS_PREV_HASH
    for d in delivered:
        assert isinstance(d, dict)
        again = compute_row_hash(
            d["prev_hash"],
            HashInput(
                d["audit_id"],
                d["actor"],
                d["action"],
                d["target"],
                d["detail_text"],
                d["at_text"],
            ),
        )
        assert again == d["row_hash"]
        assert d["prev_hash"] == prev
        prev = d["row_hash"]


# ------------------------------------------------- CHK-M2-103 certificate


@pytest.mark.parametrize("scheme", ["syslog+tls", "https"])
@pytest.mark.parametrize("case", ["untrusted", "wrong-name", "no-trust"])
def test_bad_certificates_fail_the_send(
    pki: Pki,
    good: Leaf,
    untrusted: Leaf,
    wrong_name: Leaf,
    monkeypatch: pytest.MonkeyPatch,
    scheme: str,
    case: str,
) -> None:
    leaf = {"untrusted": untrusted, "wrong-name": wrong_name, "no-trust": good}[case]
    if case != "no-trust":
        monkeypatch.setenv("SSL_CERT_FILE", str(pki.ca))
    else:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    ctx = server_context(leaf.cert, leaf.key)
    if scheme == "https":
        with https_sink(ctx) as sink:
            t = transport_from_url(f"https://127.0.0.1:{sink.port}/a")
            with pytest.raises(DeliveryError) as info:
                t.send(chain(2))
            t.close()
        assert sink.posts == []
    else:
        with syslog_sink(ctx) as ssink:
            t = transport_from_url(f"syslog+tls://127.0.0.1:{ssink.port}")
            with pytest.raises(DeliveryError) as info:
                t.send(chain(2))
            t.close()
            time.sleep(0.3)
        assert ssink.frames() == []
    assert info.value.delivered == 0


@pytest.mark.parametrize("scheme", ["syslog+tls", "https"])
def test_tls_below_1_2_is_refused(good: Leaf, trust: None, scheme: str) -> None:
    ctx = server_context(good.cert, good.key, max_version=ssl.TLSVersion.TLSv1_1)
    control = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    control.check_hostname = False
    control.verify_mode = ssl.CERT_NONE
    control.minimum_version = ssl.TLSVersion.TLSv1
    control.maximum_version = ssl.TLSVersion.TLSv1_1
    control.set_ciphers("DEFAULT:@SECLEVEL=0")
    with syslog_sink(ctx) as probe:
        try:
            with socket.create_connection(("127.0.0.1", probe.port), timeout=5) as raw:
                with control.wrap_socket(raw) as tls:
                    negotiated = tls.version()
        except (OSError, ssl.SSLError) as exc:
            pytest.skip(f"not run: this OpenSSL cannot speak TLS 1.1 ({exc!r})")
    assert negotiated in ("TLSv1", "TLSv1.1")  # control: a TLS 1.1 sink exists
    if scheme == "https":
        with https_sink(ctx) as sink:
            t = transport_from_url(f"https://127.0.0.1:{sink.port}/a")
            with pytest.raises(DeliveryError):
                t.send(chain(1))
            t.close()
        assert sink.posts == []
    else:
        with syslog_sink(ctx) as ssink:
            t = transport_from_url(f"syslog+tls://127.0.0.1:{ssink.port}")
            with pytest.raises(DeliveryError):
                t.send(chain(1))
            t.close()
        assert ssink.frames() == []


# --------------------------------------------- CHK-M2-104 refused values

REFUSED = [
    "udp://sink.example:514",
    "tcp://sink.example:514",
    "syslog://sink.example:514",
    "syslog+tcp://sink.example:514",
    "syslog+udp://sink.example:514",
    "http://sink.example/x",
    "HTTP://sink.example/x",
    "ftp://sink.example",
    "file:///tmp/x",
    "sink.example:514",
    "",
    "   ",
    "syslog+tls://",
    "https://",
    "syslog+tls://sink.example:0",
    "https://sink.example:0/x",
    "syslog+tls://sink.example:65536",
    "syslog+tls://sink.example:abc",
    "syslog+tls://sink.example/path",
    "syslog+tls://sink.example?x=1",
    f"https://user:{CANARY}@sink.example/x",
    f"syslog+tls://{CANARY}@sink.example:6514",
    "https://[sink.example/x",
]


@pytest.mark.parametrize("value", REFUSED)
def test_refused_sink_values(value: str) -> None:
    with pytest.raises(ConfigError) as info:
        transport_from_url(value)
    exc = info.value
    assert "BITSCAN_AUDIT_SINK" in str(exc)
    assert exc.__cause__ is None and exc.__context__ is None
    text = "".join(traceback.format_exception(exc))
    assert CANARY not in text
    if value.strip():
        assert value.strip() not in str(exc)


@pytest.mark.parametrize(
    "value",
    [
        "syslog+tls://sink.example:6514",
        "syslog+tls://sink.example",
        "SYSLOG+TLS://sink.example:6514",
        "syslog+tls://[::1]:6514",
        "https://sink.example/audit",
        "HTTPS://sink.example/audit",
        "https://sink.example:8443/a/b?c=d",
    ],
)
def test_accepted_sink_values_open_no_connection(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*a: object, **k: object) -> None:
        raise AssertionError("connected while building the transport")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    transport_from_url(value).close()


# ------------------------------------------------- CHK-M2-105 timeouts


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.parametrize("scheme", ["syslog+tls", "https"])
def test_closed_port_fails_within_the_timeout(trust: None, scheme: str) -> None:
    port = free_port()
    url = f"{scheme}://127.0.0.1:{port}" + ("/a" if scheme == "https" else "")
    t = transport_from_url(url, timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(DeliveryError) as info:
        t.send(chain(2))
    assert time.monotonic() - started < 2.0
    assert info.value.delivered == 0
    assert_clean(info.value)
    t.close()


def test_syslog_sink_that_never_answers_fails_within_the_timeout(trust: None) -> None:
    with syslog_sink(None) as sink:  # TCP accepted, no TLS handshake ever
        t = transport_from_url(f"syslog+tls://127.0.0.1:{sink.port}", timeout_s=1.0)
        started = time.monotonic()
        with pytest.raises(DeliveryError):
            t.send(chain(1))
        assert time.monotonic() - started < 2.0
        t.close()


def test_https_sink_that_hangs_fails_within_the_timeout(
    good: Leaf, trust: None
) -> None:
    with https_sink(server_context(good.cert, good.key), delay_s=4) as sink:
        t = transport_from_url(f"https://127.0.0.1:{sink.port}/a", timeout_s=1.0)
        started = time.monotonic()
        with pytest.raises(DeliveryError) as info:
            t.send(chain(1))
        assert time.monotonic() - started < 2.0
        assert info.value.delivered == 0
        t.close()


# ------------------------------------------------- CHK-M2-106 no content


def assert_clean(exc: BaseException) -> None:
    text = "".join(traceback.format_exception(exc)) + repr(exc)
    for part in (CANARY, "user.create", "user:1", "row_hash"):
        assert part not in text, part


def test_record_content_never_reaches_logs_or_errors(
    good: Leaf, trust: None, caplog: pytest.LogCaptureFixture
) -> None:
    records = chain(3, detail_of=lambda i: json.dumps({"secret": CANARY}))
    with caplog.at_level(logging.DEBUG):
        with https_sink(server_context(good.cert, good.key), statuses=(200, 500)) as s:
            t = transport_from_url(f"https://127.0.0.1:{s.port}/a")
            with pytest.raises(DeliveryError) as info:
                t.send(records)
            t.close()
        with syslog_sink(server_context(good.cert, good.key)) as ss:
            t2 = transport_from_url(f"syslog+tls://127.0.0.1:{ss.port}")
            t2.send(records)
            t2.close()
    assert_clean(info.value)
    assert CANARY not in caplog.text


def test_no_path_hint_in_wire_format(tmp_path: Path) -> None:
    """to_wire/from_wire round trip keeps every field and nothing else."""
    rec = chain(1)[0]
    wire = rec.to_wire()
    assert set(wire) == FIELDS
    assert SinkRecord.from_wire({**wire, "extra": 1}) == rec
