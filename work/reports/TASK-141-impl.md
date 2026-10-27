# TASK-141 IMPL: safe `.bit` parser (BIT001)

Implementer: impl-manager-m7. REQ-150, REQ-176, REQ-180. Risk high (two approvals). Plan: `work/plans/TASK-141.md` (design note D1). Spec: TS §4.1 (L516-L517), §8.1 (L1251); SR §4 / §4.1 BIT001; #57, #105.

## File

`manager/bitscan_manager/services/importer/parse.py` (new, 231 lines with docstrings; about 175 hand-written). No other file changed.

## Interface (as plan §2)

```python
MAX_ELEMENTS: Final = 35_014;  MAX_DEPTH: Final = 16;  MAX_ATTRIBUTES: Final = 8
@dataclass(frozen=True, slots=True)
class ParseResult:
    root: Node | None; findings: tuple[Finding, ...]; pi_lines: tuple[int, ...] = ()
def parse_bit(buffer: bytes) -> ParseResult
```

`MAX_BIT_BYTES` comes from `model.py`. The module is pure: no file, network, log or clock access. It imports only `defusedxml`, `defusedxml.ElementTree`, `dataclasses`, `typing` and the model; no `xml`, `re`, `lxml`, `subprocess`, `socket` or `urllib`.

## Data flow (plan §3), with what was verified

1. Size: an empty buffer gets BIT001 "The file is empty."; more than 5,242,880 bytes gets "The file is larger than 5 MiB." (`line` null).
2. Encoding, before XML:
   - a UTF-16 or UTF-32 BOM gets BIT001 at line 1;
   - a strict `decode("utf-8")` failure gets BIT001 at the line of the first bad byte;
   - a UTF-8 BOM is allowed;
   - the XML declaration's `version` and `encoding` are read with byte operations (no regex): `version` other than `1.0` and `encoding` other than `utf-8` (ASCII case-insensitive) get BIT001; a declaration that does not scan is left to expat.
3. One `DefusedXMLParser(target=collector, encoding="utf-8", forbid_dtd=True, forbid_entities=True, forbid_external=True)`, one `feed`, then `close`. **Verified:** `DefusedXMLParser` subclasses the pure-Python `XMLParser` on defusedxml 0.7.1 and Python 3.12, and `parser.parser` (expat) exposes `CurrentLineNumber`. `encoding="utf-8"` is passed as extra protection, but it does **not** stop expat's own UTF-16 detection (see Revision 1); the NUL-byte refusal does.
4. Collector: `start` (line = expat's `CurrentLineNumber`), `end` (builds the frozen `Node` with text parts joined once), `data`, `pi` (records the line), `close`. There is no `comment` method, so comments are dropped and text around them is joined.
5. Caps: a private `_Stop` is raised from the callbacks.
6. Exceptions become one finding: `DTDForbidden`, `EntitiesForbidden` and `ExternalReferenceForbidden` give BIT001 at the parser's current line; `ParseError` gives BIT001 at `exc.position[0]`. Any other exception propagates (#98 (j)).

## Revision 1 (TEST FAIL from tester-m7b: UTF-16 without a BOM)

- **Finding:** UTF-16 (LE or BE) without a BOM parsed with no finding. Its bytes are valid UTF-8 (NULs included), so the strict decode passed. Expat auto-detects UTF-16 from `3C 00` / `00 3C` even when `ParserCreate` is given `encoding="utf-8"`. The declaration pre-check never ran because the buffer does not start with the bytes `<?xml`.
- **Fix (cause, not symptom):** before the strict decode, any `0x00` byte gives BIT001 "The file is not UTF-8 text." at the line of the first NUL. U+0000 is never an XML 1.0 character, so no valid file is refused. Every UTF-16 or UTF-32 document has a NUL in its first bytes, because it must begin with `<` or whitespace. 5 lines.
- **Re-checked:** the SR §1.1 example as UTF-16-LE, UTF-16-BE, UTF-32-LE and UTF-32-BE, each with its declaration, without one, and with `encoding="UTF-16"`, gives exactly one BIT001 at line 1 with `root` None. The UTF-8 original still parses clean. All 180 fixtures still match (0 mismatches). The 5 MiB file still parses in 0.02 s at a 13 MiB peak. Ruff, format and mypy are clean.
- `raw-nul.bit` now gets this message instead of expat's "not well-formed"; it is still exactly one BIT001.

## Where this differs from the plan

These follow from how defusedxml really behaves, or tighten the plan. None changes an answered question; planner-m7 and main are told.

1. **Namespaces are BIT002 in the parser, not in TASK-143.** Plan §3 step 4 assumes namespaces are not processed. The pure-Python `XMLParser` always creates expat with namespace processing on (`ParserCreate(encoding, "}")`), so:
   - `xmlns` / `xmlns:p` declarations never reach `start()` as attributes;
   - an unbound prefix (`<x:Name>`) is an expat error (code 27), not a name.

   To keep #105 (c) ("any namespace is BIT002"), the collector has a `start_ns` method that stops with BIT002 "Namespaces are not allowed." at the declaring element's line. A ParseError with code 27 gives the same BIT002. The fixtures `bit002/namespace-default.bit`, `namespace-prefixed.bit` and `xinclude.bit` get BIT002 at their manifest lines.
2. **No expat message text is quoted verbatim.** The plan says expat's message holds no input text. The ElementTree undefined-entity path builds "undefined entity &name;", which quotes input. The message is therefore `"The file is not well-formed XML: <kind>."`, where `<kind>` is the text before `": line "` in expat's message. For code 11 (undefined entity) it is the fixed text "undefined entity".
3. **The plugin cap stops at the 5,001st `Plugin` element** with BIT017 "More than 5,000 plugins.", wherever it appears. In the plan, BIT017 came only with the 35,014-element cap. A canonical 5,001-plugin file has exactly 7 + 7 × 5,001 = 35,014 elements, so it would never hit that cap, and TS §4.1 L517 puts "max 5,000 plugins" on the parse. Exceeding 35,014 elements otherwise gives BIT002, as planned.
4. **The #105 (a) attribute cap** (at most 8 attributes per element) is enforced here as BIT002 "An element has more than 8 attributes." (`bit002/nine-attributes.bit`).

Finding `element` is null for every parser finding (file-level), as plan §3 step 6 says. The cap and namespace findings carry the start-tag line.

## Checks run (Windows, `manager/.venv`, scratch scripts outside the tree)

- **All 180 fixtures in `bits/tests/manifest.json`** (read only; `@@CANARY@@` and `@@PORT@@` replaced by dummies):
  - every fixture whose expected first code is BIT001 gets exactly one BIT001;
  - every other fixture gets either no parser finding or exactly its expected first code (the parser-level BIT002 and BIT017 cases), with the manifest line where one is given;
  - 0 mismatches.
- The XXE, parameter-entity, billion-laughs and quadratic fixtures all stop at the DTD (`DTDForbidden`, line 3) before any entity is declared or expanded.
- The SR §1.1 example: the root is `Policy` at line 2 with `(("formatVersion", "1.0"),)`, the children are in order, and each line matches the file (`Execute` at 14 with `(("timeout", "30"),)` and its CDATA untrimmed; `Operator` at 17).
- PIs: `bit002/processing-instruction.bit` gives no finding and `pi_lines == (7,)`; TASK-143 turns that into BIT002.
- Caps: 5,000 bare `<Plugin/>` give no finding; 5,001 give BIT017; 35,015 elements give BIT002; `depth-17.bit` gives BIT002 at line 5.
- A valid file of exactly 5,242,880 bytes (the SR example padded with a comment) parses in 0.03 s with a 13 MiB `tracemalloc` peak. One more byte gets BIT001 "larger than 5 MiB".
- Fuzz: 10,000 inputs (random bytes, and 1-8 byte mutations of the SR example). Nothing raised, there was never more than one finding, `root is None` exactly when there is a finding, and the slowest input took 1.3 ms.

## Static gates

- `ruff check manager`: All checks passed. `ruff format --check manager`: formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 249 source files.

## Builder checklist

- 11 and 12: messages are fixed text; no file content, entity name or expat input text is quoted. The parser logs nothing.
- 1 (values reaching the database): a U+0000 or lone surrogate cannot pass. Raw NUL and `&#0;` are refused by expat (BIT001, fixtures `raw-nul.bit` and `nul-char-ref.bit`), and surrogates encoded in UTF-8 fail the strict decode (`surrogate-utf8.bit`).
- 15 (CLI secrets) does not apply.

## For the tester (tester-m7b; TP-M7-03, `test_bit_parse.py`, `test_bit_fuzz.py`)

- Namespace fixtures are BIT002 **from the parser** (`start_ns`, or unbound prefix code 27), with `root` None.
- BIT017 for 5,001 `Plugin` elements comes from the parser at the 5,001st start tag, whatever their content.
- `pi_lines` is the hand-over for TASK-143; the parser itself makes no finding for a PI.
- Plants for CHK-M7-320/321/322: with `forbid_dtd=False` the external-entity fixtures are still stopped by `forbid_entities` or `forbid_external`, because declaring an entity fails first. A single plant may therefore leave a fixture BIT001 with a different message. Plant per flag and check the message: "A DTD is not allowed." becomes "Entity declarations are not allowed." or the canary or listener is reached.
