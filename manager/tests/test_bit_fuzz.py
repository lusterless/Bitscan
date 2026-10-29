"""TP-M7-03 property half (G55 unit half): the `.bit` parser never raises
(TASK-141; REQ-176, TS §8.3 "Property/fuzz ... no crash"). CHK-M7-027.

At least 10,000 inputs in total: random bytes, mutations of the SR §1.1 example
and the two samples, and XML-shaped token soup. Each call returns a
``ParseResult`` (a tree, or exactly one finding of BIT001, BIT002 or BIT017)
within 2 s. Owner: tester-m7b.
"""

from __future__ import annotations

import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bitscan_manager.services.importer.model import MAX_BIT_BYTES, Code
from bitscan_manager.services.importer.parse import ParseResult, parse_bit
from tests.bit_unit import SAMPLES
from tests.test_bit_fixtures import sr_example

SEEDS = [sr_example()] + [p.read_bytes() for p in sorted(SAMPLES.glob("*.bit"))]
PARSER_CODES = {Code.BIT001, Code.BIT002, Code.BIT017}

RANDOM, MUTATED, SOUP = 4_000, 4_000, 2_500
FUZZ = settings(
    deadline=2_000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def _check(data: bytes) -> None:
    start = time.perf_counter()
    result = parse_bit(data)
    assert time.perf_counter() - start < 2.0
    assert isinstance(result, ParseResult)
    assert len(result.findings) <= 1
    assert (result.root is None) == bool(result.findings)
    for f in result.findings:
        assert f.code in PARSER_CODES
        assert f.element is None
        # expat counts LF, CR LF and a lone CR as line ends (XML 1.0 §2.11).
        ends = data.count(b"\n") + data.count(b"\r")
        assert f.line is None or 1 <= f.line <= ends + 1
        assert f.message and len(f.message) < 200
    if result.root is not None:
        assert len(data) <= MAX_BIT_BYTES


@st.composite
def mutated(draw: st.DrawFn) -> bytes:
    data = bytearray(draw(st.sampled_from(SEEDS)))
    for _ in range(draw(st.integers(1, 8))):
        op = draw(st.integers(0, 3))
        pos = draw(st.integers(0, len(data)))
        if op == 0 and data:  # flip a byte
            data[min(pos, len(data) - 1)] = draw(st.integers(0, 255))
        elif op == 1:  # insert bytes
            data[pos:pos] = draw(st.binary(min_size=1, max_size=16))
        elif op == 2:  # delete a span
            del data[pos : pos + draw(st.integers(1, 64))]
        else:  # splice in XML syntax
            data[pos:pos] = draw(st.sampled_from(SYNTAX)).encode()
    return bytes(data)


SYNTAX = [
    "<", ">", "</", "/>", "&", ";", "&amp;", "&#0;", "&#x110000;", "&lol;",
    "<![CDATA[", "]]>", "<!--", "-->", "<?", "?>", "<?xml version='1.1'?>",
    '<!DOCTYPE Policy [<!ENTITY a "b">]>', "<!ENTITY % p 'x'>", "%p;",
    'xmlns="urn:x"', "xmlns:p='u'", "<p:x/>", "<Plugin>", "</Plugin>", '"', "'",
    "=", " ", "\r\n", "\r", "\x00", "\ufeff", "\u2028", "\U0001f600", "<Policy>",
    'timeout="30"', "<Execute>", "]]>]]>",
]  # fmt: skip


@st.composite
def token_soup(draw: st.DrawFn) -> bytes:
    parts = draw(st.lists(st.sampled_from(SYNTAX + ["a", "Policy", "\n"]),
                          max_size=200))  # fmt: skip
    prefix = draw(st.sampled_from(["", '<?xml version="1.0"?>', "\ufeff"]))
    return (prefix + "".join(parts)).encode("utf-8", "surrogatepass")


@settings(FUZZ, max_examples=RANDOM)
@given(st.binary(max_size=4_096))
def test_random_bytes_never_raise(data: bytes) -> None:
    _check(data)


@settings(FUZZ, max_examples=MUTATED)
@given(mutated())
def test_mutated_examples_never_raise(data: bytes) -> None:
    _check(data)


@settings(FUZZ, max_examples=SOUP)
@given(token_soup())
def test_xml_token_soup_never_raises(data: bytes) -> None:
    _check(data)


def test_total_inputs_at_least_10000() -> None:
    # Guard on the suite itself (CHK-M7-027).
    assert RANDOM + MUTATED + SOUP >= 10_000
