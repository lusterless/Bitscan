"""TP-M7-03: the safe `.bit` parser, BIT001 and the #105 (a) caps (TASK-141).

Expected values come from SR §4, §4.1 (BIT001), TS §4.1 L516-L517, §8.1 L1251
and the approved answers #57 (MiB) and #105 (a), (b), (c), (f), (g); fixtures
from ``bits/tests`` (tester-m7). CHK-M7-020 to -026 and -028; plants CHK-M7-320,
-321, -322, -323, -347 (tests/m7/test-plan.md). Owner: tester-m7b.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from defusedxml.ElementTree import DefusedXMLParser

from bitscan_manager.services.importer import parse as parse_mod
from bitscan_manager.services.importer.model import MAX_BIT_BYTES, Code, Node
from bitscan_manager.services.importer.parse import ParseResult, parse_bit
from tests.bit_unit import (
    FIXTURES,
    SAMPLES,
    canonical,
    connected,
    fixture,
    fixtures_in,
    listener,
    no_side_effects,
    start_tags,
)
from tests.test_bit_fixtures import sr_example

MIB = 1_048_576
PARSE_PY = Path(parse_mod.__file__)

DOCTYPE_FIXTURES = [
    f for f in fixtures_in("bit001") if b"<!DOCTYPE" in fixture(f)
]  # fmt: skip
ENTITY_FIXTURES = [
    "bit001/xxe-file.bit",
    "bit001/xxe-url.bit",
    "bit001/parameter-entity.bit",
    "bit001/parameter-entity-internal.bit",
    "bit001/billion-laughs.bit",
    "bit001/quadratic-blowup.bit",
]


def one(result: ParseResult) -> Any:
    assert result.root is None, "a finding must come without a tree"
    assert len(result.findings) == 1, result.findings
    return result.findings[0]


def doc(body: str, decl: str = '<?xml version="1.0" encoding="UTF-8"?>\n') -> bytes:
    return (decl + body).encode("utf-8")


@pytest.fixture(autouse=True, scope="module")
def _warm() -> None:
    # Lazy imports (codecs, error classes) happen here, outside any recorder,
    # on inputs that are not under test for side effects.
    parse_bit(sr_example())
    parse_bit(b"<a>")
    parse_bit(b"<!DOCTYPE a><a/>")
    parse_bit(b"\xff\xfe<\x00")
    parse_bit(b"<a>\xff</a>")


# CHK-M7-020: every BIT001 fixture is exactly one BIT001 ---------------------


@pytest.mark.parametrize("name", fixtures_in("bit001"))
def test_bit001_fixture_gives_exactly_one_bit001(name: str) -> None:
    entry = FIXTURES[name]
    assert entry["codes"] == ["BIT001"]
    f = one(parse_bit(fixture(name)))
    assert f.code is Code.BIT001
    assert f.element is None  # file-level (#105 (g))
    if "lines" in entry:
        assert f.line == entry["lines"][0]
    assert f.message and f.message.isprintable()
    # Fixed text per rule: nothing from the file (#105 (g), builder item 11).
    for token in ("Fixture", "@@", "nope", "lol", "xxe", "127.0.0.1", "ISO-8859"):
        assert token not in f.message, (name, f.message)


@pytest.mark.parametrize("name", DOCTYPE_FIXTURES)
def test_dtd_refused_at_the_doctype_line(name: str) -> None:
    # Red for CHK-M7-321 (forbid_dtd=False): these then fail later, with the
    # entity message, or pass.
    text = fixture(name).decode("utf-8")
    doctype_line = text.count("\n", 0, text.index("<!DOCTYPE")) + 1
    f = one(parse_bit(fixture(name)))
    assert f.code is Code.BIT001
    assert "DTD" in f.message, f.message
    assert f.line == doctype_line


def test_no_bit001_fixture_lacks_a_check() -> None:
    # Guard: the parametrised set above is the whole folder.
    assert len(fixtures_in("bit001")) >= 30
    assert set(ENTITY_FIXTURES) <= set(DOCTYPE_FIXTURES)


# CHK-M7-021: no file or network access ---------------------------------------


@pytest.mark.parametrize(
    "name",
    ["bit001/xxe-file.bit", "bit001/external-dtd-file.bit", "bit002/xinclude.bit"],
)
def test_file_references_never_opened(name: str, tmp_path: Path) -> None:
    canary = tmp_path / "canary.txt"
    marker = "CANARY-7b-e3f1c9"
    canary.write_text(marker, encoding="utf-8")
    data = fixture(name, canary=canary.resolve().as_posix())
    with no_side_effects() as events:
        result = parse_bit(data)
    assert events == []
    assert marker not in repr(result)
    assert result.root is None and len(result.findings) == 1


@pytest.mark.parametrize(
    "name",
    [
        "bit001/xxe-url.bit",
        "bit001/parameter-entity.bit",
        "bit001/external-dtd-url.bit",
    ],
)
def test_url_references_never_fetched(name: str) -> None:
    with listener() as (port, srv):
        data = fixture(name, port=port)
        with no_side_effects() as events:
            result = parse_bit(data)
        assert not connected(srv)
    assert events == []
    assert one(result).code is Code.BIT001


def test_recorder_sees_a_real_open(tmp_path: Path) -> None:
    # Guard on the oracle: the audit hook does record file access.
    with no_side_effects() as events:
        (tmp_path / "x").write_text("x", encoding="utf-8")
    assert any(e[0] == "open" for e in events)


# Defence in depth (CHK-M7-320 and -322): every defusedxml layer is on. ---------


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[DefusedXMLParser]:
    made: list[DefusedXMLParser] = []
    original = DefusedXMLParser.__init__

    def init(self: DefusedXMLParser, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(DefusedXMLParser, "__init__", init)
    return made


def test_parser_built_with_all_three_forbids(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _spy(monkeypatch)
    assert parse_bit(sr_example()).findings == ()
    assert len(made) == 1
    p: Any = made[0]
    assert (p.forbid_dtd, p.forbid_entities, p.forbid_external) == (True, True, True)


@pytest.mark.parametrize("name", ENTITY_FIXTURES)
def test_entity_layer_holds_when_dtd_layer_is_bypassed(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a DTD-layer failure; the entity layer must still refuse every
    # entity declaration without expanding it (red for CHK-M7-322).
    monkeypatch.setattr(DefusedXMLParser, "defused_start_doctype_decl", _noop)
    data = fixture(name)
    tracemalloc.start()
    try:
        with no_side_effects() as events:
            f = one(parse_bit(data))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert events == []
    assert f.code is Code.BIT001
    assert "ntit" in f.message, f.message  # Entity / entities
    assert peak < 64 * MIB


@pytest.mark.parametrize("name", ["bit001/xxe-file.bit", "bit001/xxe-url.bit"])
def test_external_layer_holds_when_dtd_and_entity_layers_are_bypassed(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Red for CHK-M7-320 (forbid_external=False).
    monkeypatch.setattr(DefusedXMLParser, "defused_start_doctype_decl", _noop)
    monkeypatch.setattr(DefusedXMLParser, "defused_entity_decl", _noop)
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY-ext-91ab", encoding="utf-8")
    with listener() as (port, srv):
        data = fixture(name, canary=canary.resolve().as_posix(), port=port)
        with no_side_effects() as events:
            result = parse_bit(data)
        assert not connected(srv)
    assert events == []
    assert "CANARY-ext-91ab" not in repr(result)
    f = one(result)
    assert f.code is Code.BIT001
    assert "xternal" in f.message, f.message


def _noop(*_args: Any) -> None:
    return None


# CHK-M7-022: memory and time on expansion bombs and the 5 MiB file ----------


def _measure(data: bytes) -> tuple[ParseResult, int, float]:
    tracemalloc.start()
    start = time.perf_counter()
    try:
        result = parse_bit(data)
        elapsed = time.perf_counter() - start
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return result, peak, elapsed


@pytest.mark.parametrize(
    "name", ["bit001/billion-laughs.bit", "bit001/quadratic-blowup.bit"]
)
def test_bombs_bounded(name: str) -> None:
    result, peak, elapsed = _measure(fixture(name))
    assert one(result).code is Code.BIT001
    assert peak < 64 * MIB
    assert elapsed < 2.0


def test_valid_5_mib_file_parses_bounded() -> None:
    data = canonical(pad_to=MAX_BIT_BYTES)
    result, peak, elapsed = _measure(data)
    assert result.findings == ()
    assert result.root is not None and result.root.name == "Policy"
    assert peak < 64 * MIB
    assert elapsed < 2.0


def test_5_mib_of_text_in_one_element_bounded() -> None:
    filler = "x" * (MAX_BIT_BYTES - 2_000)
    body = (
        canonical().decode().replace("Generated by the tester.", filler)
    )  # PolicyDescription; the parser does not check lengths
    data = body.encode()
    assert len(data) <= MAX_BIT_BYTES
    result, peak, elapsed = _measure(data)
    assert result.root is not None
    assert result.root.children[1].text == filler
    assert peak < 64 * MIB
    assert elapsed < 2.0


# CHK-M7-023: the size bound (#57: 5 MiB = 5,242,880 bytes) --------------------


def test_size_constant_is_5_mib() -> None:
    assert MAX_BIT_BYTES == 5_242_880


def test_exactly_5_mib_passes_bit001() -> None:
    result = parse_bit(canonical(pad_to=5_242_880))
    assert result.findings == ()
    assert result.root is not None


def test_one_byte_over_is_bit001_and_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red for CHK-M7-323 (cap raised): this file is otherwise valid.
    made = _spy(monkeypatch)
    f = one(parse_bit(canonical(pad_to=5_242_881)))
    assert f.code is Code.BIT001
    assert f.line is None and f.element is None
    assert made == []


def test_oversize_garbage_is_bit001_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = _spy(monkeypatch)
    f = one(parse_bit(b"\xff" * (MAX_BIT_BYTES + 1)))
    assert f.code is Code.BIT001 and f.line is None
    assert "UTF" not in f.message  # the size rule, not the encoding rule
    assert made == []


def test_empty_is_bit001_with_null_line() -> None:
    f = one(parse_bit(b""))
    assert (f.code, f.line, f.element) == (Code.BIT001, None, None)


# CHK-M7-024: the Node tree of the SR §1.1 example ----------------------------


def _preorder(node: Node) -> list[Node]:
    out = [node]
    for child in node.children:
        out.extend(_preorder(child))
    return out


def test_sr_example_tree_matches_the_file() -> None:
    data = sr_example()
    result = parse_bit(data)
    assert result.findings == () and result.pi_lines == ()
    root = result.root
    assert root is not None
    assert root.name == "Policy" and root.attributes == (("formatVersion", "1.0"),)
    assert [c.name for c in root.children] == [
        "PolicyName",
        "PolicyDescription",
        "PolicyStatus",
        "Family",
        "PluginsGroups",
    ]
    nodes = _preorder(root)
    assert [(n.name, n.line) for n in nodes] == start_tags(data.decode("utf-8"))
    plugin = root.children[4].children[0]
    assert [c.name for c in plugin.children] == [
        "PluginName",
        "PluginDescription",
        "PluginId",
        "Execute",
        "Operator",
        "ExpectedResult",
    ]
    execute = plugin.children[3]
    assert execute.attributes == (("timeout", "30"),)
    assert execute.text == (
        "\n        dpkg-query -W -f='${Status}' apparmor 2>/dev/null\n      "
    )
    assert root.children[0].text == "CIS Ubuntu 24.04 Level 1 - Server"
    assert plugin.children[2].text == "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"
    assert plugin.children[5].text == "install ok installed"


@pytest.mark.parametrize("name", fixtures_in("valid"))
def test_valid_fixture_lines_match_the_file(name: str) -> None:
    data = fixture(name)
    result = parse_bit(data)
    assert result.findings == ()
    assert result.root is not None
    text = data.decode("utf-8-sig")
    assert [(n.name, n.line) for n in _preorder(result.root)] == start_tags(text)


def test_sample_policies_parse() -> None:
    samples = sorted(SAMPLES.glob("*.bit"))
    assert len(samples) == 2
    for path in samples:
        data = path.read_bytes()
        result = parse_bit(data)
        assert result.findings == (), path.name
        assert result.root is not None
        assert [(n.name, n.line) for n in _preorder(result.root)] == start_tags(
            data.decode("utf-8")
        )


def test_result_and_nodes_are_frozen() -> None:
    result = parse_bit(sr_example())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.root = None  # type: ignore[misc]
    assert result.root is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.root.name = "x"  # type: ignore[misc]


# #105 (b): CDATA, text and comments ----------------------------------------


def test_cdata_text_and_comments_joined_in_order() -> None:
    data = doc(
        "<Policy><Execute>a<!-- rm -rf / -->b<![CDATA[<c>&amp;]]>d"
        "<!--x--></Execute><!-- top --></Policy>"
    )
    result = parse_bit(data)
    assert result.root is not None
    (execute,) = result.root.children
    assert execute.text == "ab<c>&amp;d"
    assert execute.children == ()


def test_predefined_entities_and_char_refs_decoded() -> None:
    body = "<Policy><X>&lt;&gt;&amp;&quot;&apos;&#x41;&#66;</X></Policy>"
    result = parse_bit(doc(body))
    assert result.root is not None
    assert result.root.children[0].text == "<>&\"'AB"


def test_undefined_entity_is_bit001_without_its_name() -> None:
    f = one(parse_bit(doc("<Policy>\n<X>&secretname;</X></Policy>")))
    assert f.code is Code.BIT001 and f.line == 3
    assert "secretname" not in f.message


def test_crlf_normalised_and_lines_counted() -> None:
    data = b'<?xml version="1.0"?>\r\n<Policy>\r\n<X>a\r\nb</X>\r<Y>c</Y></Policy>'
    result = parse_bit(data)
    assert result.root is not None
    x, y = result.root.children
    assert x.text == "a\nb" and "\r" not in y.text
    assert (result.root.line, x.line, y.line) == (2, 3, 5)


def test_attribute_order_kept() -> None:
    result = parse_bit(doc('<Policy b="2" a="1" c="3"/>'))
    assert result.root is not None
    assert result.root.attributes == (("b", "2"), ("a", "1"), ("c", "3"))


def test_multiline_start_tag_line_is_the_open_bracket() -> None:
    result = parse_bit(doc('<Policy>\n  <X\n   a="1"\n  >t</X></Policy>'))
    assert result.root is not None
    assert result.root.children[0].line == 3


# PIs (#105 (c)): recorded for TASK-143; the declaration is not one -----------


def test_pi_lines_recorded_declaration_not() -> None:
    result = parse_bit(doc("<Policy>\n<?foo bar?>\n<X/></Policy>\n<?tail x?>"))
    assert result.findings == ()
    assert result.pi_lines == (3, 5)


def test_fixture_pi_lines() -> None:
    assert parse_bit(fixture("bit002/processing-instruction.bit")).pi_lines == (7,)
    assert parse_bit(fixture("bit002/pi-before-root.bit")).pi_lines == (3,)


# CHK-M7-025: encodings (#105 (f), D1) ----------------------------------------


@pytest.mark.parametrize(
    "decl",
    [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<?xml version="1.0" encoding="utf-8"?>\n',
        '<?xml version="1.0" encoding="Utf-8"?>\n',
        "<?xml version='1.0' encoding='UTF-8'?>\n",
        '<?xml version="1.0"?>\n',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
        '<?xml  version = "1.0"\tencoding = "UTF-8" ?>\n',
        "",
    ],
)
def test_utf8_declarations_accepted(decl: str) -> None:
    result = parse_bit(doc("<Policy>é</Policy>", decl))
    assert result.findings == ()
    assert result.root is not None and result.root.text == "é"


def test_utf8_bom_accepted() -> None:
    result = parse_bit(b"\xef\xbb\xbf" + doc("<Policy>x</Policy>"))
    assert result.findings == () and result.root is not None


@pytest.mark.parametrize(
    "decl",
    [
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n',
        '<?xml version="1.0" encoding="iso-8859-1"?>\n',
        "<?xml version='1.0' encoding='latin1'?>\n",
        '<?xml version="1.0" encoding = "US-ASCII"?>\n',
        '<?xml version="1.0"\tencoding="utf8"?>\n',
        '<?xml version="1.0" encoding="UTF-16"?>\n',
        '<?xml version="1.0" encoding="windows-1252" standalone="no"?>\n',
    ],
)
def test_other_declared_encodings_are_bit001(decl: str) -> None:
    # ASCII-only body: plain expat would parse these, so only the D1 check
    # can catch them.
    f = one(parse_bit(doc("<Policy>x</Policy>", decl)))
    assert f.code is Code.BIT001 and f.line in (1, None)


def test_bom_then_foreign_declaration_is_bit001() -> None:
    data = b"\xef\xbb\xbf" + doc(
        "<Policy/>", '<?xml version="1.0" encoding="ISO-8859-1"?>'
    )
    assert one(parse_bit(data)).code is Code.BIT001


@pytest.mark.parametrize(
    "decl", ['<?xml version="1.1"?>', "<?xml version='2.0' encoding='UTF-8'?>"]
)
def test_xml_other_than_1_0_is_bit001(decl: str) -> None:
    assert one(parse_bit(doc("<Policy/>", decl))).code is Code.BIT001


@pytest.mark.parametrize(
    "prefix",
    [b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"],
)
def test_utf16_and_utf32_boms_are_bit001_line_1(prefix: bytes) -> None:
    f = one(parse_bit(prefix + b"<\x00P\x00/\x00>\x00"))
    assert f.code is Code.BIT001 and f.line == 1


@pytest.mark.parametrize(
    "bad",
    [b"\xff", b"\xc3\x28", b"\xc0\xaf", b"\xed\xa0\x80", b"\x80", b"\xe2\x82"],
)
@pytest.mark.parametrize("where", ["text", "comment", "cdata", "attribute"])
def test_invalid_utf8_line_of_first_bad_byte(bad: bytes, where: str) -> None:
    lines = [b'<?xml version="1.0"?>', b"<Policy>"] + [b"<X/>"] * 4
    hole = {
        "text": b"<X>" + bad + b"</X>",
        "comment": b"<!-- " + bad + b" -->",
        "cdata": b"<X><![CDATA[" + bad + b"]]></X>",
        "attribute": b'<X a="' + bad + b'"/>',
    }[where]
    data = b"\n".join(lines + [hole, b"</Policy>"])  # the hole is on line 7
    f = one(parse_bit(data))
    assert (f.code, f.line) == (Code.BIT001, 7)
    assert "UTF" in f.message


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("decl", ["", "UTF-8", "UTF-16"])
def test_utf16_without_bom_is_bit001(codec: str, decl: str) -> None:
    # REQ-150 / D1: UTF-8 only. expat auto-detects UTF-16 from a "<" byte next
    # to a NUL even when told UTF-8, so these bytes (valid UTF-8 holding NULs)
    # must be refused before XML parsing.
    text = sr_example().decode("utf-8").split("\n", 1)[1]
    if decl:
        text = f'<?xml version="1.0" encoding="{decl}"?>\n' + text
    f = one(parse_bit(text.encode(codec)))
    assert f.code is Code.BIT001


@pytest.mark.parametrize("where", [0, 1, 200, -1])
def test_nul_byte_anywhere_is_bit001(where: int) -> None:
    data = bytearray(sr_example())
    data[where] = 0
    assert one(parse_bit(bytes(data))).code is Code.BIT001


# CHK-M7-026: the #105 (a) caps ---------------------------------------------


def _nested(depth: int) -> bytes:
    inner = "".join("<d>\n" for _ in range(depth - 1)) + "x" + "</d>" * (depth - 1)
    return doc("<Policy>\n" + inner + "</Policy>")


def test_depth_16_accepted() -> None:
    result = parse_bit(_nested(16))
    assert result.findings == () and result.root is not None


def test_depth_17_is_bit002_at_the_17th_element() -> None:
    f = one(parse_bit(_nested(17)))
    # Policy on line 2, the n-th <d> on line n + 2: the 17th element is line 18.
    assert (f.code, f.line, f.element) == (Code.BIT002, 18, None)


def test_depth_17_fixture() -> None:
    f = one(parse_bit(fixture("bit002/depth-17.bit")))
    assert (f.code, f.line) == (Code.BIT002, 5)


def _flat(count: int, name: str = "x") -> bytes:
    # Root plus count - 1 children, one per line (child k on line k + 2).
    return doc("<Policy>\n" + f"<{name}/>\n" * (count - 1) + "</Policy>")


def test_35014_elements_accepted() -> None:
    result = parse_bit(_flat(35_014))
    assert result.findings == ()
    assert result.root is not None and len(result.root.children) == 35_013


def test_35015_elements_is_bit002_bounded() -> None:
    result, peak, elapsed = _measure(_flat(35_015))
    f = one(result)
    assert (f.code, f.line) == (Code.BIT002, 35_015 + 1)
    assert peak < 64 * MIB and elapsed < 2.0


def test_5000_plugins_accepted() -> None:
    result = parse_bit(_flat(5_001, "Plugin"))
    assert result.findings == ()
    result = parse_bit(canonical(5_000))
    assert result.findings == ()
    assert result.root is not None
    assert len(result.root.children[4].children) == 5_000


def test_5001_bare_plugins_is_bit017_at_the_5001st() -> None:
    f = one(parse_bit(_flat(5_002, "Plugin")))
    assert (f.code, f.line) == (Code.BIT017, 5_001 + 2)


def test_5001_canonical_plugins_is_bit017() -> None:
    f = one(parse_bit(canonical(5_001)))
    assert f.code is Code.BIT017


def test_over_35014_elements_with_5001_plugins_is_bit017() -> None:
    # #105 (a): BIT017 if more than 5,000 Plugin elements were seen.
    f = one(parse_bit(_flat(35_100, "Plugin")))
    assert f.code is Code.BIT017


def test_8_attributes_accepted_9_refused() -> None:
    eight = " ".join(f'a{i}="{i}"' for i in range(8))
    nine = eight + ' a8="8"'
    assert parse_bit(doc(f"<Policy>\n<X {eight}/></Policy>")).findings == ()
    f = one(parse_bit(doc(f"<Policy>\n<X {nine}/></Policy>")))
    assert (f.code, f.line) == (Code.BIT002, 3)
    f = one(parse_bit(fixture("bit002/nine-attributes.bit")))
    assert (f.code, f.line) == (Code.BIT002, 3)


# Namespaces (#105 (c)): exactly one BIT002 from the parser -------------------


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ('<Policy>\n<X xmlns="urn:x"/></Policy>', 3),
        ('<Policy xmlns="urn:x">\n<X/></Policy>', 2),
        ('<Policy>\n\n<p:X xmlns:p="urn:p"/></Policy>', 4),
        ('<Policy>\n<X xmlns=""/></Policy>', 3),
        ("<Policy>\n<p:X/></Policy>", 3),  # unbound prefix
        ('<Policy>\n<X p:a="1"/></Policy>', 3),  # unbound attribute prefix
    ],
)
def test_namespaces_are_one_bit002(body: str, line: int) -> None:
    f = one(parse_bit(doc(body)))
    assert (f.code, f.line, f.element) == (Code.BIT002, line, None)


@pytest.mark.parametrize(
    "name",
    [
        "bit002/namespace-default.bit",
        "bit002/namespace-prefixed.bit",
        "bit002/xinclude.bit",
    ],
)
def test_namespace_fixtures_are_bit002_at_manifest_line(name: str) -> None:
    f = one(parse_bit(fixture(name)))
    assert f.code is Code.BIT002
    assert f.line == FIXTURES[name]["lines"][0]


# Results are well-formed and side-effect free --------------------------------


@pytest.mark.parametrize(
    "name", fixtures_in("bit001") + fixtures_in("bit002") + fixtures_in("valid")
)
def test_no_log_and_no_output(
    name: str, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    result = parse_bit(fixture(name))
    assert (result.root is None) == bool(result.findings)
    assert len(result.findings) <= 1
    assert caplog.records == []
    out, err = capfd.readouterr()
    assert out == "" and err == ""


# CHK-M7-028 and CHK-M7-347: imports ----------------------------------------

BANNED_IMPORTS = (
    "xml", "lxml", "re", "subprocess", "socket", "urllib", "http", "ftplib",
    "logging", "time", "datetime", "os", "pathlib", "io", "shutil", "tempfile",
    "ctypes", "pickle", "marshal", "importlib",
)  # fmt: skip


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_parser_imports_only_safe_modules() -> None:
    for name in _imported_modules(PARSE_PY):
        top = name.split(".")[0]
        assert top not in BANNED_IMPORTS, name


def test_parser_calls_no_open_eval_or_exec() -> None:
    tree = ast.parse(PARSE_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("open", "eval", "exec", "compile", "__import__")


def test_no_importer_module_imports_xml_or_lxml() -> None:
    # CHK-M7-028: every module under services/importer/.
    for path in sorted(PARSE_PY.parent.glob("*.py")):
        for name in _imported_modules(path):
            top = name.split(".")[0]
            assert top not in ("xml", "lxml", "re"), (path.name, name)
