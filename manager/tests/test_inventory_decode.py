"""TASK-060: the inventory decoder, unit half (G32).

Checks CHK-M3-130 to CHK-M3-135, CHK-M3-137 and CHK-M3-138 of
tests/m3/test-plan.md (TP-M3-14); the property half is
tests/test_inventory_fuzz.py. Expected values: TS §3.4 L240 (64 MiB
decompressed as a stream, 50,000 rows, raw <= 256 KiB, field lengths), TS §6.5
L1186 and #33 (list_sha256 recomputed; lines sorted by bytes), #72 (b), (c), (f)
(413 for byte limits, 422 for rows, fields, duplicates and the hash, 400 for a
malformed stream or JSON), rulings 2026-10-23 (U+0000 and lone surrogates 400;
too-deep nesting a 400, never a 500), #57 (b) (MiB). Expected statuses come from
the manifest of the shared fixtures (TP-M3-01), not from the code.
"""

import gzip
import json
import logging
import time
import tracemalloc
import types
import zlib
from collections.abc import Iterator
from typing import Any

import pytest

from bitscan_manager.api.agent import AGENT_GENERIC_PROBLEM_TYPES, AGENT_PROBLEM_TYPES
from bitscan_manager.services.inventory import (
    DecodedInventory,
    InventoryRefused,
    decode_inventory,
    gunzip_capped,
)
from bitscan_manager.services.inventory import decode as decode_module
from tests.contract import loader

MIB = 1_048_576
CAP = 64 * MIB
RAW_CAP = 262_144
RESULTS_CAP = 3 * MIB // 2
ZERO_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
REASONS = {
    "decompressed_too_large",
    "bad_gzip",
    "truncated_gzip",
    "trailing_data",
    "bad_json",
    "nul_character",
    "lone_surrogate",
    "too_deep",
    "too_many_packages",
    "invalid_field",
    "raw_too_large",
    "duplicate_package",
    "hash_mismatch",
}
TYPES = {400: "invalid_request", 413: "too_large", 422: "about:blank"}
INVENTORY = list(loader.select("inventory", "request"))


def gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def refusal(body: bytes) -> InventoryRefused:
    with pytest.raises(InventoryRefused) as exc:
        decode_inventory(body)
    e = exc.value
    assert e.reason in REASONS, e.reason
    assert e.type == TYPES[e.status], (e.status, e.type)
    # the problem type a route answers with: only the agent-route values (#59)
    assert e.type in AGENT_PROBLEM_TYPES | AGENT_GENERIC_PROBLEM_TYPES, e.type
    return e


def zero_body(
    raw: Any = None, packages: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    pk = packages or []
    os_info: dict[str, Any] = {
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "os_pretty_name": "Ubuntu",
        "kernel_release": "6.8",
        "architecture": "x86_64",
        "cpu_count": 1,
        "memory_mb": 1,
        "ip_addresses": [],
        "uptime_s": 1,
        "raw": {} if raw is None else raw,
    }
    return {"os_info": os_info, "packages": pk, "list_sha256": loader.list_sha256(pk)}


def encode(doc: Any) -> bytes:
    return gz(json.dumps(doc, ensure_ascii=False).encode())


def expected_status(fx: loader.Fixture) -> int:
    """From the manifest and the rulings: decoder entries say it; unstorable is
    400; NaN/Infinity tokens are not JSON (400); everything else the model
    refuses is 422 (#72 (b), plan TASK-060 step 3)."""
    if fx.decoder is not None:
        return int(fx.decoder["status"])
    if fx.cls == "unstorable":
        return 400
    if fx.schema_gap == "nan_inf" and "overflow_1e400" not in fx.id:
        return 400
    return 422


# ------------------------------------------------------------ CHK-M3-130


@pytest.mark.parametrize(
    "fx", [f for f in INVENTORY if f.valid and f.decoder is None], ids=lambda f: f.id
)
def test_valid_fixtures_decode_exactly(fx: loader.Fixture) -> None:
    body = fx.body()
    got = decode_inventory(gz(fx.body_bytes()))
    assert isinstance(got, DecodedInventory)
    assert got.os_info.model_dump(mode="json") == body["os_info"]
    assert [p.model_dump(mode="json") for p in got.packages] == body["packages"]
    assert isinstance(got.packages, tuple)
    assert (
        got.list_sha256 == body["list_sha256"] == loader.list_sha256(body["packages"])
    )
    assert got.raw_json == json.dumps(
        body["os_info"]["raw"], ensure_ascii=False, separators=(",", ":")
    )


# ------------------------------------------------------------ fixture refusals


@pytest.mark.parametrize(
    "fx",
    [f for f in INVENTORY if not f.valid or f.decoder is not None],
    ids=lambda f: f.id,
)
def test_refused_fixtures_get_their_status(fx: loader.Fixture) -> None:
    e = refusal(gz(fx.body_bytes()))
    assert e.status == expected_status(fx), (e.status, e.reason, fx.reason)


def test_specific_reasons_for_the_decoder_fixtures() -> None:
    by_id = {f.id: f for f in INVENTORY}
    cases = {
        "inventory/request_valid_hash_mismatch": (422, "hash_mismatch"),
        "inventory/request_valid_duplicate_package": (422, "duplicate_package"),
        "inventory/request_valid_raw_256k_plus_1": (413, "raw_too_large"),
        "inventory/request_invalid_packages_50001": (422, "too_many_packages"),
        "inventory/request_invalid_nul_raw_nested_key": (400, "nul_character"),
        "inventory/request_invalid_lone_surrogate_package_name": (
            400,
            "lone_surrogate",
        ),
        "inventory/request_invalid_raw_nan_top": (400, "bad_json"),
        "inventory/request_invalid_raw_overflow_1e400_nested": (422, "invalid_field"),
    }
    for fid, (status, reason) in cases.items():
        e = refusal(gz(by_id[fid].body_bytes()))
        assert (e.status, e.reason) == (status, reason), fid


# ------------------------------------------------------------ CHK-M3-131


def test_hash_is_recomputed_and_order_free() -> None:
    fx = next(f for f in INVENTORY if f.id.endswith("multi_arch"))
    body = fx.body()
    body["packages"] = list(reversed(body["packages"]))
    got = decode_inventory(encode(body))
    assert got.list_sha256 == loader.list_sha256(body["packages"])
    assert [p.name for p in got.packages] == [p["name"] for p in body["packages"]]
    # the agent's value is never trusted: one changed character is refused
    bad = dict(
        body,
        list_sha256=("0" if body["list_sha256"][0] != "0" else "1")
        + body["list_sha256"][1:],
    )
    assert refusal(encode(bad)).reason == "hash_mismatch"
    # a hash over a different status for one line is refused too
    flipped = json.loads(json.dumps(body))
    flipped["packages"][0]["status"] = "half-installed"  # a status no line has
    assert refusal(encode(flipped)).reason == "hash_mismatch"


def test_hash_ignores_source_and_size() -> None:
    """#33: only name, version, architecture and status are hashed."""
    pk = [
        {
            "name": "a",
            "version": "1",
            "architecture": "all",
            "status": "s",
            "source": "x",
            "installed_size_kb": 1,
        }
    ]
    body = zero_body(packages=pk)
    pk2 = [dict(pk[0], source=None, installed_size_kb=None)]
    body2 = dict(zero_body(packages=pk2), list_sha256=body["list_sha256"])
    assert decode_inventory(encode(body2)).list_sha256 == body["list_sha256"]


# ------------------------------------------------------------ CHK-M3-132


class CountingInflater:
    """Wraps zlib's decompress object and counts the bytes it produced."""

    produced = 0

    def __init__(self, wbits: int) -> None:
        self._z = zlib.decompressobj(wbits)

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        assert max_length > 0, "an unlimited decompress call"
        out = self._z.decompress(data, max_length)
        CountingInflater.produced += len(out)
        return out

    def __getattr__(self, name: str) -> Any:
        return getattr(self._z, name)


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[CountingInflater]]:
    CountingInflater.produced = 0
    # only the decoder's zlib reference changes; the real module is untouched
    fake = types.SimpleNamespace(decompressobj=CountingInflater, error=zlib.error)
    monkeypatch.setattr(decode_module, "zlib", fake)
    yield CountingInflater


def padded(total: int) -> bytes:
    """A valid zero-package body padded with JSON whitespace to `total` bytes."""
    text = json.dumps(zero_body()).encode()
    return text + b" " * (total - len(text))


def test_exactly_64_mib_decompressed_is_accepted() -> None:
    got = decode_inventory(gz(padded(CAP)))
    assert got.packages == () and got.list_sha256 == ZERO_SHA


def test_64_mib_plus_one_is_413_after_at_most_cap_plus_one(
    counting: type[CountingInflater],
) -> None:
    e = refusal(gz(padded(CAP + 1)))
    assert (e.status, e.type, e.reason) == (413, "too_large", "decompressed_too_large")
    assert counting.produced <= CAP + 1


def test_gunzip_cap_on_chunked_input(counting: type[CountingInflater]) -> None:
    data = gz(b"z" * 10_000)
    chunks = [data[i : i + 7] for i in range(0, len(data), 7)]
    assert gunzip_capped(chunks, 10_000) == b"z" * 10_000
    counting.produced = 0
    with pytest.raises(InventoryRefused) as exc:
        gunzip_capped(chunks, 9_999)
    assert exc.value.status == 413
    assert counting.produced <= 9_999 + 1


# ------------------------------------------------------------ CHK-M3-133


def _bomb(size: int) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"\0" * MIB
    parts = [c.compress(block) for _ in range(size // MIB)]
    parts.append(c.flush())
    return b"".join(parts)


@pytest.fixture(scope="module")
def bomb() -> bytes:
    return _bomb(1024 * MIB)


def test_gzip_bomb_is_refused_within_the_bounds(bomb: bytes) -> None:
    """REQ-074 (1): about 1 MiB expanding to 1 GiB; 413, peak memory < 256 MiB."""
    assert len(bomb) < 2 * MIB
    tracemalloc.start()
    started = time.perf_counter()
    try:
        e = refusal(bomb)
    finally:
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert (e.status, e.reason) == (413, "decompressed_too_large")
    assert peak < 256 * MIB, peak
    print(
        f"gzip bomb: {len(bomb)} bytes, refused in {elapsed:.2f} s,"
        f" peak {peak / MIB:.0f} MiB"
    )


# ------------------------------------------------------------ CHK-M3-134


def _packages(n: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"p{i}",
            "version": "1",
            "architecture": "all",
            "status": "install ok installed",
            "source": None,
            "installed_size_kb": None,
        }
        for i in range(n)
    ]


def test_rows_checked_before_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """50,001 rows: 422 without validating them (no partial work)."""
    body = encode(zero_body(packages=_packages(50_001)))

    class NoValidate:
        @staticmethod
        def model_validate(_: object) -> None:
            raise AssertionError("50,001 rows reached the model")

    monkeypatch.setattr(decode_module, "InventoryBody", NoValidate)
    e = refusal(body)
    assert (e.status, e.reason) == (422, "too_many_packages")


def test_fifty_thousand_rows_decode() -> None:
    got = decode_inventory(encode(zero_body(packages=_packages(50_000))))
    assert len(got.packages) == 50_000


def _raw_of_utf8_bytes(total: int) -> dict[str, str]:
    """raw = {"pad": "é…"} whose compact UTF-8 JSON is exactly `total` bytes."""
    overhead = len(b'{"pad":""}')
    body_bytes = total - overhead
    pad = "é" * (body_bytes // 2) + "a" * (body_bytes % 2)
    raw = {"pad": pad}
    assert (
        len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode())
        == total
    )
    return raw


def test_raw_cap_counts_utf8_bytes_of_compact_json() -> None:
    ok = decode_inventory(encode(zero_body(raw=_raw_of_utf8_bytes(RAW_CAP))))
    assert len(ok.raw_json.encode()) == RAW_CAP
    e = refusal(encode(zero_body(raw=_raw_of_utf8_bytes(RAW_CAP + 1))))
    assert (e.status, e.type, e.reason) == (413, "too_large", "raw_too_large")


def test_raw_whitespace_does_not_count() -> None:
    """The limit is on the compact form, so indentation as sent is free."""
    raw = _raw_of_utf8_bytes(RAW_CAP)
    text = json.dumps(zero_body(raw=raw), ensure_ascii=False, indent=8).encode()
    assert (
        decode_inventory(gz(text)).raw_json.encode()
        == json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
    )


def test_duplicate_package_line() -> None:
    pk = _packages(2)
    pk[1] = dict(pk[0], status="deinstall ok config-files")
    e = refusal(encode(zero_body(packages=pk)))
    assert (e.status, e.reason) == (422, "duplicate_package")
    # same name and version, another architecture: not a duplicate
    pk[1] = dict(pk[0], architecture="amd64")
    assert len(decode_inventory(encode(zero_body(packages=pk))).packages) == 2


# ------------------------------------------------------------ CHK-M3-135


@pytest.mark.parametrize(
    ("name", "body", "reason"),
    [
        ("plain-json", json.dumps(zero_body()).encode(), "bad_gzip"),
        ("empty", b"", "truncated_gzip"),
        ("random", b"\x00\x01garbage" * 10, "bad_gzip"),
        ("header-only", gz(b"{}")[:10], "truncated_gzip"),
        (
            "trailing-byte",
            gz(json.dumps(zero_body()).encode()) + b"\x00",
            "trailing_data",
        ),
        (
            "two-members",
            gz(b"{}") + gz(json.dumps(zero_body()).encode()),
            "trailing_data",
        ),
        ("bad-crc", None, "bad_gzip"),
        ("invalid-utf8", gz(b'{"os_info": "\xff\xfe"}'), "bad_json"),
        ("invalid-json", gz(b'{"os_info": '), "bad_json"),
        ("nan-token", gz(b'{"a": NaN}'), "bad_json"),
        ("huge-int", gz(b'{"a": ' + b"9" * 5000 + b"}"), "bad_json"),
        ("deep-100k", gz(b"[" * 100_000 + b"]" * 100_000), None),
        ("nul-in-key", gz(json.dumps({"os_info\u0000": 1}).encode()), "nul_character"),
        ("lone-surrogate", gz(b'{"a": "\\ud800"}'), "lone_surrogate"),
    ],
)
def test_malformed_input_is_400(
    name: str, body: bytes | None, reason: str | None
) -> None:
    if name == "bad-crc":
        good = bytearray(gz(json.dumps(zero_body()).encode()))
        good[-6] ^= 0xFF  # inside the CRC32 trailer
        body = bytes(good)
    assert body is not None
    e = refusal(body)
    assert e.status == 400 and e.type == "invalid_request", (name, e.status, e.reason)
    if reason is not None:
        assert e.reason == reason, (name, e.reason)


def test_every_truncation_of_a_valid_body_is_400() -> None:
    whole = encode(zero_body(packages=_packages(3)))
    assert decode_inventory(whole)
    for cut in range(len(whole)):
        e = refusal(whole[:cut])
        assert e.status == 400, (cut, e.reason)


def test_non_object_documents_are_refused() -> None:
    for doc in ([], "x", 1, None, [zero_body()]):
        e = refusal(encode(doc))
        assert e.status in (400, 422), (doc, e.status)


def _nested_raw(levels: int) -> Any:
    node: Any = "leaf"
    for _ in range(levels - 1):
        node = {"k": node}
    return node


def test_depth_limit_is_a_400_never_a_crash() -> None:
    """Ruling 2026-10-23 and the impl report (MAX_DEPTH 32 anywhere in the body):
    a shallow raw decodes, a deep one is a fixed 400, an extreme one too."""
    assert decode_inventory(encode(zero_body(raw=_nested_raw(20))))
    for levels in (40, 99, 101, 5000):
        text = '{"k": ' * (levels - 1) + '"leaf"' + "}" * (levels - 1)
        doc_text = json.dumps(zero_body()).replace('"raw": {}', '"raw": ' + text)
        e = refusal(gz(doc_text.encode()))
        # beyond the decoder's scan, Python's own json recursion limit answers
        # first (bad_json); either way it is a 400, which is what is pinned
        assert e.status == 400, levels
        assert e.reason == ("too_deep" if levels < 1000 else e.reason), levels
        assert e.reason in {"too_deep", "bad_json"}, levels
    # the observed boundary (recorded, not pinned): the deepest raw that passes
    ok = max(n for n in range(20, 40) if _decodes(_nested_raw(n)))
    print(f"deepest accepted raw: {ok} object levels")


def _dicts(k: int) -> Any:
    """raw as exactly k nested objects (raw itself is the outermost)."""
    node: Any = "leaf"
    for _ in range(k):
        node = {"k": node}
    return node


def test_nesting_boundary_32_accepted_33_refused() -> None:
    """Main's ruling: the body nested 32 containers deep (body, os_info and 30
    levels of raw) is accepted; 33 or more is 400 invalid_request, never 500."""
    got = decode_inventory(encode(zero_body(raw=_dicts(30))))
    assert got.raw_json.count("{") == 30
    for k in (31, 32, 60):
        e = refusal(encode(zero_body(raw=_dicts(k))))
        assert (e.status, e.type) == (400, "invalid_request"), k
    # the same bound through lists, and through packages, not only raw
    deep_list: Any = "x"
    for _ in range(29):
        deep_list = [deep_list]
    assert decode_inventory(encode(zero_body(raw={"a": deep_list})))  # 2 + 1 + 29 = 32
    e = refusal(encode(zero_body(raw={"a": [deep_list]})))
    assert (e.status, e.type) == (400, "invalid_request")
    doc = zero_body()
    nested: Any = 1
    for _ in range(32):
        nested = [nested]
    doc["packages"] = nested  # body + 32 lists = 33 levels: too deep
    e = refusal(encode(doc))
    assert (e.status, e.type) == (400, "invalid_request")


def _decodes(raw: Any) -> bool:
    try:
        decode_inventory(encode(zero_body(raw=raw)))
    except InventoryRefused:
        return False
    return True


# ------------------------------------------------------------ CHK-M3-137 (REQ-087)


def test_reasons_and_logs_hold_no_input(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    canary = "CANARY-60a1b2c3d4e5f6a7"
    pk = [
        {
            "name": canary,
            "version": canary + "v",
            "architecture": "all",
            "status": "s",
            "source": canary,
            "installed_size_kb": 1,
        }
    ]
    bodies = [
        dict(zero_body(raw={canary: canary}, packages=pk), list_sha256="0" * 64),
        zero_body(raw={canary: canary * 30_000}, packages=pk),
        dict(zero_body(packages=pk + pk)),
        {"os_info": {canary: 1}},
    ]
    errors: list[InventoryRefused] = []
    for doc in bodies:
        with pytest.raises(InventoryRefused) as exc:
            decode_inventory(encode(doc))
        errors.append(exc.value)
    blob = " ".join(
        [str(e) + repr(e) + repr(e.args) + repr(vars(e)) for e in errors]
        + [r.getMessage() + repr(r.args) for r in caplog.records]
    )
    assert canary not in blob
    assert {e.reason for e in errors} <= REASONS
    assert not [r for r in caplog.records if r.name.startswith("bitscan")]


# ------------------------------------------------------------ CHK-M3-138


def test_results_cap_through_the_same_gunzip(counting: type[CountingInflater]) -> None:
    assert len(gunzip_capped([gz(b"r" * RESULTS_CAP)], RESULTS_CAP)) == RESULTS_CAP
    counting.produced = 0
    with pytest.raises(InventoryRefused) as exc:
        gunzip_capped([gz(b"r" * (RESULTS_CAP + 1))], RESULTS_CAP)
    assert (exc.value.status, exc.value.reason) == (413, "decompressed_too_large")
    assert counting.produced <= RESULTS_CAP + 1
