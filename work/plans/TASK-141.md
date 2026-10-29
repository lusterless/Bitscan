# TASK-141 plan: safe `.bit` parser (BIT001)

Planner: planner-m7, 2026-10-27, from design note D1 (`work/tasks.md`, M7). Risk: high (importer; two approvals). File: `manager/bitscan_manager/services/importer/parse.py` only. Depends on TASK-140 (`Node`, `Finding`, codes, limits). Answers applied (user, 2026-10-27, all as recommended): #57 (MiB), #105 (caps, text, PIs, declaration, finding fields).

## 1. Spec

- TS §4.1 L516: "The importer reads the file into memory once; hashing and parsing use that buffer, and the file is never re-read."
- TS §4.1 L517: "`defusedxml` (no DTD, no external entities, max 5 MB, max 5,000 plugins)."
- TS §8.1 L1251: "XML attacks (XXE, billion laughs) | `defusedxml`, no DTD, size and node limits".
- SR §4.1 BIT001 (SR L256): "Well-formed XML, UTF-8, ≤ 5 MB, no DTD or external entities | Reject". SR §4 (SR L250): BIT001 and BIT002 run first; if either fails the content rules do not run.

## 2. Interface

```python
MAX_BIT_BYTES: Final = 5 * 1_048_576          # from model.py if TASK-140 defines it there
MAX_ELEMENTS: Final = 35_014                  # 7 + 7 * 5_001 (#105 (a))
MAX_DEPTH: Final = 16                         # #105 (a)

@dataclass(frozen=True)
class ParseResult:
    root: Node | None                         # None when any finding was made
    findings: tuple[Finding, ...]             # empty, or exactly one finding
    pi_lines: tuple[int, ...] = ()            # processing instructions other than the XML declaration

def parse_bit(buffer: bytes) -> ParseResult: ...
```

- `parse_bit` is pure: no file, network, log or clock access. It never raises; every failure is one finding. The caller (TASK-154) has already read and hashed the buffer.
- `Node` comes from TASK-140. The parser fills, per element: `name` (the raw tag, prefix included if any), `line` (start-tag line, 1-based), `attributes` (in document order, as `(name, value)` pairs), `text` (all character data directly inside the element, CDATA and plain text joined in document order; comments contribute nothing) and `children`. If TASK-140's `Node` lacks a field this needs, add it in this task's model change request to the lead, not by redefining `Node` here.
- The result has at most one finding. It is BIT001, except for the two cap cases in §3 step 5, which are BIT002 or BIT017.

## 3. Data flow

1. **Size.** `len(buffer) == 0` → BIT001 "The file is empty." `len(buffer) > MAX_BIT_BYTES` → BIT001 "The file is larger than 5 MiB." (`line` null).
2. **Encoding, before any XML parsing.**
   - A UTF-16 or UTF-32 byte-order mark (`FF FE`, `FE FF`, `FF FE 00 00`, `00 00 FE FF`) → BIT001 "The file is not UTF-8." (line 1).
   - `buffer.decode("utf-8")` in strict mode. A `UnicodeDecodeError` → BIT001 "The file is not valid UTF-8." with `line` = number of `b"\n"` before `exc.start`, plus 1. The decoded text is not kept: expat parses the bytes.
   - A UTF-8 BOM (`EF BB BF`) is allowed (#105 (f)).
   - XML declaration. Use plain byte operations, no regex. If the bytes after an optional BOM start with `<?xml` followed by whitespace, take the bytes up to the first `?>`. Read the pseudo-attributes `version` and `encoding`: a name, `=` with optional whitespace, then a `'` or `"` quoted value. `version` must be `1.0`, else BIT001 "Only XML 1.0 is supported." `encoding`, if present, must equal `utf-8` (ASCII case-insensitive), else BIT001 "The file is not UTF-8." A declaration without a closing `?>` is left for expat to reject.
3. **Parser.** One `defusedxml.ElementTree.DefusedXMLParser(target=collector, forbid_dtd=True, forbid_entities=True, forbid_external=True)`, then `parser.feed(buffer)` once and `parser.close()`. Import only from `defusedxml` and `defusedxml.ElementTree` (G1 bans `xml.*` and `lxml`; `ParseError` is re-exported by `defusedxml.ElementTree`, so `xml.etree` need not be imported).
4. **Collector** (a private class passed as `target`), with these methods:
   - `start(tag, attrib)`: count elements; check depth; create a `Node` with `line = self._expat.CurrentLineNumber`, where `_expat` is the parser's pure-Python `XMLParser.parser` attribute (defusedxml subclasses the pure-Python `XMLParser`, which exposes it). The implementer verifies this attribute exists on the pinned defusedxml 0.7.1 and Python 3.12. If it does not, stop and tell the lead; never fall back to a non-defused parser.
   - `end(tag)`: pop.
   - `data(text)`: append to the current element's text parts.
   - `pi(target, data)`: record the line.
   - No `comment` method (comments are dropped), and no `doctype` method (defusedxml refuses any DTD first).
   - `close()`: return the root.
   - `attrib` keeps document order (the pure-Python parser builds a dict in order). Element and attribute names are taken as given; namespaces are not processed, so `x:Name` and `xmlns` reach TASK-143 as plain names and become BIT002 there (#105 (c)).
5. **Caps** (#105 (a)). Raise a private `_CapExceeded` from `start` to stop at once:
   - element count `> MAX_ELEMENTS`: BIT017 "More than 5,000 plugins." if more than 5,000 elements named `Plugin` were seen, else BIT002 "The file has more elements than a canonical .bit file can hold.";
   - depth `> MAX_DEPTH`: BIT002 "Elements are nested too deeply."
   Exceptions raised in target callbacks propagate out of `feed`; catch `_CapExceeded` around `feed` and `close`.
6. **Errors to findings.** Every other failure becomes one BIT001 finding with `element` null:

   | Exception | `message` | `line` |
   | --- | --- | --- |
   | `defusedxml.DTDForbidden` | "A DTD is not allowed." | the parser's current line |
   | `defusedxml.EntitiesForbidden` | "Entity declarations are not allowed." | the parser's current line |
   | `defusedxml.ExternalReferenceForbidden` | "External references are not allowed." | the parser's current line |
   | `ParseError` | "The file is not well-formed XML: " plus expat's message, which names only the error kind, line and column, never input text | `exc.position[0]` |

   Any other exception is a programming error and propagates. TASK-154 maps it to an internal error (#98 (j)), never to a pass.
7. **Result.** On success, `root` is the `Policy` (or whatever the root element is; TASK-143 checks the name), `findings` is empty and `pi_lines` lists the processing-instruction lines. The XML declaration is not reported as a PI by expat.

## 4. Edge cases

- Text after the root element, or two root elements: expat raises `ParseError` ("junk after document element") → BIT001.
- `&lt;`, `&amp;` and the other predefined entities, and character references (`&#x41;`), are allowed and decoded by expat. Only declared entities are refused.
- An undeclared entity such as `&foo;` → `ParseError` → BIT001.
- CR LF inside text is normalised to LF by expat (XML end-of-line handling), including in CDATA. Tests must build CRLF input in code (`.gitattributes` makes text fixtures LF).
- U+0000 cannot appear in well-formed XML (expat refuses it) → BIT001.
- A 5,242,880-byte file of valid XML (large comments or a long `PluginDescription` padding) must parse within 2 s.
- Memory: the `Node` tree of a 5 MiB file stays under 64 MiB. Hold text parts as a list joined once at `end`; do not concatenate repeatedly.

### 4a. As built (impl-manager-m7, `work/reports/TASK-141-impl.md`; accepted by the planner, 2026-10-27)

These four points replace the matching text in §2 and §3:
1. **Namespaces.** defusedxml's pure-Python `XMLParser` always runs expat with namespace processing on, so `xmlns` declarations never reach `start()`, and an unbound prefix is an expat error. The parser itself therefore reports BIT002 "Namespaces are not allowed." for any namespace declaration (`start_ns`) and for an expat unbound-prefix error (code 27). This keeps #105 (c). TASK-143 never sees a namespaced name.
2. **Expat message text.** Expat's undefined-entity message quotes the entity name, which is input text. So the BIT001 message names only the error kind, plus the line from `position`. Expat's own message text is never copied.
3. **BIT017.** It fires when the 5,001st `Plugin` element starts. My §3 step 5 was wrong here: a canonical 5,001-plugin file has exactly 35,014 elements, so it would never cross the element cap. The 35,014-element cap remains as BIT002, for files of non-canonical elements.
4. **Attributes.** The #105 (a) limit of 8 attributes per element is BIT002, raised by the parser.

So a parser finding is either BIT001, or one of the BIT002 and BIT017 cases above. There is always exactly one finding.

## 5. Tests (TP-M7-03; tester files `manager/tests/test_bit_parse.py`, `manager/tests/test_bit_fuzz.py`)

Added by §4a: a declared namespace (`xmlns="x"`, `xmlns:a="x"`) and an unbound prefix (`<a:Policy>`) each give one BIT002 "Namespaces are not allowed."; an undefined entity `&secretname;` gives BIT001 whose message does not contain `secretname`; 5,000 canonical plugins parse and 5,001 give BIT017; 9 attributes on one element give BIT002.

1. Each BIT001 fixture in `bits/tests/bit001/` gives exactly one BIT001 finding and `root` None: an external entity by `file://` (pointing at a canary file) and by `http://` (pointing at a local listener), a parameter entity, billion laughs, quadratic blow-up, a DTD with no entity, a UTF-16 BOM, a UTF-32 BOM, `encoding="ISO-8859-1"`, `version="1.1"`, invalid UTF-8 at line 7 (`line` = 7), not well-formed (`line` from expat), an empty buffer, 5 MiB + 1 byte (generated). The canary's content appears nowhere in the result and the listener gets no connection.
2. Peak memory (`tracemalloc`) under 64 MiB for the billion-laughs and blow-up fixtures and for the valid 5 MiB file.
3. The SR §1.1 example: root `Policy`, children in order, the `Execute` node's line is the line of `<Execute timeout="30">`, its text is the CDATA content untrimmed, and `attributes` is `(("timeout", "30"),)`.
4. Text and CDATA mixed, and a comment inside `Execute`: text joined, comment absent.
5. A PI `<?foo bar?>` at line 3 gives `pi_lines == (3,)`; the XML declaration gives none.
6. Caps: 5,001 generated `Plugin` elements give one BIT017; 35,015 unknown elements give BIT002; nesting 17 deep gives BIT002.
7. A UTF-8 BOM with a valid file parses.
8. Fuzz: 10,000 Hypothesis-generated byte strings and mutations of the SR §1.1 example and the samples. Each call returns a `ParseResult` with no exception, within 2 s.
9. Source checks: the module imports nothing from `xml`, `lxml`, `re`, `subprocess`, `socket` or `urllib` (G1, plus a grep in the test).

Plants for the mutation table: CHK-M7-320 (`forbid_external=False`), -321 (`forbid_dtd=False`), -322 (`forbid_entities=False`), -323 (cap raised to 50 MiB), -347 (`import xml.etree.ElementTree`). Each must turn rows 1, 2 or 9 red.

## 6. Budget

About 170 lines in one file. If it grows past 200, move the declaration and encoding pre-check (§3 step 2) into a private helper module `services/importer/encoding.py`, as an extra file for this task, with the lead's agreement.
