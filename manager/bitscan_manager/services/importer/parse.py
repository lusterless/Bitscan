"""Safe `.bit` parser: BIT001 and the #105 (a) caps (TS §4.1, §8.1; SR §4.1;
design note D1, work/plans/TASK-141.md).

Pure: no file, network, log or clock access. The caller has read and hashed
the buffer once; this parses that buffer once with defusedxml (DTDs, entity
declarations and external references forbidden) and returns either a Node
tree or exactly one finding.
"""

from dataclasses import dataclass
from typing import Final, Protocol

import defusedxml
from defusedxml.ElementTree import DefusedXMLParser, ParseError

from bitscan_manager.services.importer.model import (
    MAX_BIT_BYTES,
    PLUGINS_MAX,
    Code,
    Finding,
    Node,
)

MAX_ELEMENTS: Final = 35_014  # 7 + 7 * 5_001 (#105 (a))
MAX_DEPTH: Final = 16
MAX_ATTRIBUTES: Final = 8

_UTF16_32_BOMS: Final = (b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")
_UTF8_BOM: Final = b"\xef\xbb\xbf"
_XML_SPACE: Final = b" \t\r\n"
_EXPAT_UNDEFINED_ENTITY: Final = 11  # its text would name the entity
_EXPAT_UNBOUND_PREFIX: Final = 27
_NO_NAMESPACES: Final = "Namespaces are not allowed."


@dataclass(frozen=True, slots=True)
class ParseResult:
    root: Node | None  # None when there is a finding
    findings: tuple[Finding, ...]  # empty, or exactly one
    pi_lines: tuple[int, ...] = ()  # processing instructions (not the declaration)


class _Stop(Exception):
    def __init__(self, code: Code, message: str, line: int) -> None:
        super().__init__(message)
        self.finding = Finding(line, None, code, message)


class _Position(Protocol):
    @property
    def CurrentLineNumber(self) -> int: ...  # noqa: N802  (expat's name)


class _Frame:
    __slots__ = ("attributes", "children", "line", "name", "text")

    def __init__(self, name: str, line: int, attributes: tuple[tuple[str, str], ...]):
        self.name = name
        self.line = line
        self.attributes = attributes
        self.text: list[str] = []
        self.children: list[Node] = []


class _Collector:
    """The parser target. No comment method, so comments are dropped; no
    doctype method, since defusedxml refuses any DTD first."""

    def __init__(self) -> None:
        self.position: _Position | None = None
        self.pi_lines: list[int] = []
        self.root: Node | None = None
        self._stack: list[_Frame] = []
        self._elements = 0
        self._plugins = 0

    def line(self) -> int:
        return self.position.CurrentLineNumber if self.position is not None else 0

    def start(self, tag: str, attrib: dict[str, str]) -> None:
        line = self.line()
        self._elements += 1
        if tag == "Plugin":
            self._plugins += 1
            if self._plugins > PLUGINS_MAX:
                raise _Stop(Code.BIT017, "More than 5,000 plugins.", line)
        if self._elements > MAX_ELEMENTS:
            raise _Stop(
                Code.BIT002,
                "The file has more elements than a canonical .bit file can hold.",
                line,
            )
        if len(self._stack) >= MAX_DEPTH:
            raise _Stop(Code.BIT002, "Elements are nested too deeply.", line)
        if len(attrib) > MAX_ATTRIBUTES:
            raise _Stop(Code.BIT002, "An element has more than 8 attributes.", line)
        self._stack.append(_Frame(tag, line, tuple(attrib.items())))

    def end(self, tag: str) -> None:
        frame = self._stack.pop()
        node = Node(
            frame.name,
            frame.line,
            frame.attributes,
            "".join(frame.text),
            tuple(frame.children),
        )
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self.root = node

    def data(self, text: str) -> None:
        if self._stack:  # expat reports no text outside the root
            self._stack[-1].text.append(text)

    def pi(self, target: str, data: str) -> None:
        self.pi_lines.append(self.line())

    def start_ns(self, prefix: str, uri: str) -> None:
        # Namespace processing is on in the parser, so a declaration never
        # reaches start() as an attribute; any namespace is BIT002 (#105 (c)).
        raise _Stop(Code.BIT002, _NO_NAMESPACES, self.line())

    def close(self) -> Node | None:
        return self.root


def _fail(message: str, line: int | None) -> ParseResult:
    return ParseResult(None, (Finding(line, None, Code.BIT001, message),))


def _pseudo_attributes(decl: bytes) -> dict[bytes, bytes] | None:
    """`name = "value"` pairs of an XML declaration, or None if they do not
    scan (expat then rejects the declaration itself)."""
    out: dict[bytes, bytes] = {}
    i, n = 0, len(decl)
    while True:
        while i < n and decl[i] in _XML_SPACE:
            i += 1
        if i == n:
            return out
        eq = decl.find(b"=", i)
        if eq < 0:
            return None
        name = decl[i:eq].strip(_XML_SPACE)
        i = eq + 1
        while i < n and decl[i] in _XML_SPACE:
            i += 1
        if i == n or decl[i] not in b"'\"":
            return None
        close = decl.find(decl[i : i + 1], i + 1)
        if close < 0:
            return None
        out[name] = decl[i + 1 : close]
        i = close + 1


def _encoding_problem(buffer: bytes) -> ParseResult | None:
    if buffer.startswith(_UTF16_32_BOMS):
        return _fail("The file is not UTF-8.", 1)
    # U+0000 is never an XML 1.0 character. Refusing NUL bytes also stops
    # UTF-16/32 without a BOM: those bytes are valid UTF-8, and expat would
    # auto-detect the encoding from them despite encoding="utf-8".
    nul = buffer.find(b"\x00")
    if nul >= 0:
        return _fail("The file is not UTF-8 text.", buffer.count(b"\n", 0, nul) + 1)
    try:
        buffer.decode("utf-8")  # strict; the text is not kept
    except UnicodeDecodeError as exc:
        return _fail(
            "The file is not valid UTF-8.", buffer.count(b"\n", 0, exc.start) + 1
        )
    body = buffer[len(_UTF8_BOM) :] if buffer.startswith(_UTF8_BOM) else buffer
    if not (body.startswith(b"<?xml") and body[5:6] in (b" ", b"\t", b"\r", b"\n")):
        return None
    end = body.find(b"?>")
    attrs = _pseudo_attributes(body[5:end]) if end >= 0 else None
    if attrs is None:
        return None
    if attrs.get(b"version", b"1.0") != b"1.0":
        return _fail("Only XML 1.0 is supported.", 1)
    if attrs.get(b"encoding", b"utf-8").lower() != b"utf-8":
        return _fail("The file is not UTF-8.", 1)
    return None


def _not_well_formed(exc: ParseError) -> ParseResult:
    code = getattr(exc, "code", None)
    line = exc.position[0] if getattr(exc, "position", None) else None
    if code == _EXPAT_UNBOUND_PREFIX:
        return ParseResult(None, (Finding(line, None, Code.BIT002, _NO_NAMESPACES),))
    # expat's own text names the error kind, line and column only; the
    # undefined-entity text could name the entity, so it is replaced.
    kind = (
        "undefined entity"
        if code == _EXPAT_UNDEFINED_ENTITY
        else str(exc).partition(": line ")[0]
    )
    return _fail(f"The file is not well-formed XML: {kind}.", line)


def parse_bit(buffer: bytes) -> ParseResult:
    """Parse one `.bit` buffer. Never raises for bad input; a programming
    error propagates (TASK-154 treats it as an internal error, #98 (j))."""
    if not buffer:
        return _fail("The file is empty.", None)
    if len(buffer) > MAX_BIT_BYTES:
        return _fail("The file is larger than 5 MiB.", None)
    problem = _encoding_problem(buffer)
    if problem is not None:
        return problem
    collector = _Collector()
    parser = DefusedXMLParser(
        target=collector,
        encoding="utf-8",  # the declaration was checked; never decode otherwise
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    collector.position = parser.parser
    try:
        parser.feed(buffer)
        parser.close()
    except _Stop as stop:
        return ParseResult(None, (stop.finding,))
    except defusedxml.DTDForbidden:
        return _fail("A DTD is not allowed.", collector.line())
    except defusedxml.EntitiesForbidden:
        return _fail("Entity declarations are not allowed.", collector.line())
    except defusedxml.ExternalReferenceForbidden:
        return _fail("External references are not allowed.", collector.line())
    except ParseError as exc:
        return _not_well_formed(exc)
    if collector.root is None:  # cannot happen after a clean close
        return _fail("The file is not well-formed XML: no element found.", None)
    return ParseResult(collector.root, (), tuple(collector.pi_lines))
