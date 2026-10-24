"""TASK-060: property and fuzz tests for the inventory decoder (G32).

Check CHK-M3-136 of tests/m3/test-plan.md (TP-M3-14; TS §8.3 Property/fuzz
L1276: "no crash, no partial import"; REQ-074 (4)). Whatever the input, the
decoder either returns a complete DecodedInventory or raises InventoryRefused
with a 400, 413 or 422; nothing else escapes, and a refusal carries no data.
Hypothesis runs derandomized with a fixed example budget, so CI time is bounded
and a failure reproduces.
"""

import gzip
import json
import zlib
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bitscan_manager.services.inventory import (
    DecodedInventory,
    InventoryRefused,
    decode_inventory,
)
from tests.contract import loader

FUZZ = settings(
    max_examples=300,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
VALID = next(
    f for f in loader.select("inventory", "request") if f.id.endswith("multi_arch")
)
VALID_GZ = gzip.compress(VALID.body_bytes(), mtime=0)


def outcome(body: bytes) -> DecodedInventory | InventoryRefused:
    try:
        got = decode_inventory(body)
    except InventoryRefused as e:
        assert e.status in (400, 413, 422), e.status
        assert isinstance(e.reason, str) and e.reason.isascii()
        assert not hasattr(e, "packages")  # a refusal carries no data
        return e
    assert isinstance(got, DecodedInventory)
    assert got.list_sha256 == loader.list_sha256(
        [p.model_dump() for p in got.packages]
    )  # complete and consistent
    return got


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=40,
)


@FUZZ
@given(st.binary(max_size=4096))
def test_random_bytes(data: bytes) -> None:
    assert isinstance(outcome(data), InventoryRefused)


@FUZZ
@given(st.binary(max_size=4096))
def test_gzip_of_random_bytes(data: bytes) -> None:
    outcome(gzip.compress(data, mtime=0))


@FUZZ
@given(st.integers(min_value=0, max_value=len(VALID_GZ) - 1))
def test_truncated_valid_body(cut: int) -> None:
    got = outcome(VALID_GZ[:cut])
    assert isinstance(got, InventoryRefused) and got.status == 400


@FUZZ
@given(st.integers(min_value=0, max_value=len(VALID_GZ) * 8 - 1))
def test_bit_flip_in_the_gzip(bit: int) -> None:
    body = bytearray(VALID_GZ)
    body[bit // 8] ^= 1 << (bit % 8)
    outcome(bytes(body))


@FUZZ
@given(json_values)
def test_random_json_documents(doc: Any) -> None:
    outcome(gzip.compress(json.dumps(doc).encode(), mtime=0))


@FUZZ
@given(
    json_values, st.sampled_from(["os_info", "packages", "list_sha256", "raw", "extra"])
)
def test_random_values_in_a_valid_body(value: Any, where: str) -> None:
    doc = VALID.body()
    if where == "raw":
        doc["os_info"]["raw"] = {"v": value}
    elif where == "extra":
        doc["extra"] = value
    else:
        doc[where] = value
    outcome(gzip.compress(json.dumps(doc).encode(), mtime=0))


@FUZZ
@given(st.binary(min_size=1, max_size=64))
def test_invalid_utf8_inside_a_valid_body(junk: bytes) -> None:
    text = VALID.body_bytes()
    body = text.replace(b'"ubuntu"', b'"' + junk.replace(b'"', b"") + b'"', 1)
    outcome(gzip.compress(body, mtime=0))


@FUZZ
@given(st.integers(min_value=1, max_value=200_000), st.sampled_from(["[", '{"a":']))
def test_deep_nesting(depth: int, opener: str) -> None:
    closer = "]" if opener == "[" else "}"
    leaf = "1"
    text = opener * depth + leaf + closer * depth
    got = outcome(gzip.compress(text.encode(), mtime=0))
    assert isinstance(got, InventoryRefused)


@FUZZ
@given(st.binary(max_size=2048), st.integers(min_value=-1, max_value=9))
def test_raw_deflate_and_odd_wbits(data: bytes, level: int) -> None:
    """Not gzip: raw deflate and zlib streams are refused, never crash."""
    for wbits in (-15, 15):
        c = zlib.compressobj(level, zlib.DEFLATED, wbits)
        outcome(c.compress(data) + c.flush())
