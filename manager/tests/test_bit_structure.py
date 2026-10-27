"""TP-M7-05: the structure check, BIT002 and BIT016 (TASK-143; REQ-151, REQ-176).

Expected values come from SR §2, §2.1-§2.3 (names, order, occurrence), §4
(BIT001/BIT002 first), §4.1 BIT002 and BIT016, TS §1.4 and the approved answers
#2 (missing Operator/ExpectedResult), #10 (one Family), #16 (empty
PluginsGroups) and #105 (c), (d), (g). Fixtures from ``bits/tests``
(tester-m7). CHK-M7-050 to -057; plant CHK-M7-334. Owner: tester-m7b.
"""

from __future__ import annotations

import dataclasses

import pytest

from bitscan_manager.services.importer.model import Code, Finding, ParsedPolicy
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.structure import StructureResult, check
from tests.bit_unit import FIXTURES, fixture, fixtures_in, start_tags
from tests.test_bit_fixtures import sr_example

POLICY = ["PolicyName", "PolicyDescription", "PolicyStatus", "Family", "PluginsGroups"]
PLUGIN = ["PluginName", "PluginDescription", "PluginId", "Execute", "Operator",
          "ExpectedResult"]  # fmt: skip
# Mis-cased names: "missing" at the container line, then "unknown" at its own
# line (the manifest rows were corrected by tester-m7 on 2026-10-27).
MISCASED = {
    "bit002/miscased-policyName.bit": [3, 4],
    "bit002/miscased-plugin.bit": [10, 11],
}


def run(data: bytes) -> tuple[ParsedPolicy | None, tuple[Finding, ...]]:
    """BIT001/BIT002 first (SR §4): the parser, then the structure check only
    on a tree."""
    parsed = parse_bit(data)
    if parsed.root is None:
        return None, parsed.findings
    result = check(parsed.root, parsed.pi_lines)
    assert isinstance(result, StructureResult)
    return result.parsed, result.findings


def codes(findings: tuple[Finding, ...]) -> list[str]:
    return [f.code.value for f in findings]


def sr_text() -> str:
    return sr_example().decode("utf-8")


def mutate(old: str, new: str, count: int = 1) -> bytes:
    text = sr_text()
    assert old in text, old
    return text.replace(old, new, count).encode("utf-8")


def line_of(text: str, needle: str, nth: int = 1) -> int:
    i = -1
    for _ in range(nth):
        i = text.index(needle, i + 1)
    return text.count("\n", 0, i) + 1


# CHK-M7-050: the SR §1.1 tree --------------------------------------------------


def test_sr_example_gives_raw_values_and_lines() -> None:
    text = sr_text()
    parsed, findings = run(sr_example())
    assert findings == ()
    assert parsed is not None
    lines = dict(start_tags(text))
    assert parsed.line == lines["Policy"] == 2
    assert parsed.format_version is not None
    assert (parsed.format_version.text, parsed.format_version.line) == ("1.0", 2)
    assert parsed.format_version.path == "Policy/@formatVersion"
    for field, name, value in [
        ("policy_name", "PolicyName", "CIS Ubuntu 24.04 Level 1 - Server"),
        ("policy_description", "PolicyDescription",
         "CIS Benchmark Level 1 controls for Ubuntu 24.04 servers."),
        ("policy_status", "PolicyStatus", "enabled"),
    ]:  # fmt: skip
        raw = getattr(parsed, field)
        assert (raw.text, raw.line, raw.path) == (value, lines[name], f"Policy/{name}")
    fam = parsed.family_name
    assert (fam.text, fam.line, fam.path) == (
        "CIS Ubuntu 24.04",
        lines["FamilyName"],
        "Policy/Family/FamilyName",
    )
    (plugin,) = parsed.plugins
    assert (plugin.index, plugin.line, plugin.path) == (
        1,
        lines["Plugin"],
        "Policy/PluginsGroups/Plugin[1]",
    )
    base = "Policy/PluginsGroups/Plugin[1]"
    expected = {
        "plugin_name": ("1.3.1.1 - Ensure AppArmor is installed", "PluginName"),
        "plugin_description": (
            "Checks that the AppArmor package is installed.",
            "PluginDescription",
        ),
        "plugin_id": ("3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48", "PluginId"),
        "execute": (
            "\n        dpkg-query -W -f='${Status}' apparmor 2>/dev/null\n      ",
            "Execute",
        ),
        "operator": ("equals", "Operator"),
        "expected_result": ("install ok installed", "ExpectedResult"),
    }
    for field, (value, name) in expected.items():
        raw = getattr(plugin, field)
        assert (raw.text, raw.line, raw.path) == (value, lines[name], f"{base}/{name}")
    assert plugin.timeout is not None
    assert (plugin.timeout.text, plugin.timeout.line, plugin.timeout.path) == (
        "30",
        lines["Execute"],
        f"{base}/Execute/@timeout",
    )


def test_values_are_raw_not_trimmed_or_lowered() -> None:
    data = mutate("<PolicyStatus>enabled", "<PolicyStatus>  ENABLED\n")
    data = data.replace(b"<Operator>equals", b"<Operator> EQUALS ")
    parsed, findings = run(data)
    assert findings == () and parsed is not None
    assert parsed.policy_status.text == "  ENABLED\n"
    assert parsed.plugins[0].operator is not None
    assert parsed.plugins[0].operator.text == " EQUALS "


@pytest.mark.parametrize("name", fixtures_in("valid") + fixtures_in("content"))
def test_valid_and_content_fixtures_pass_the_structure(name: str) -> None:
    entry = FIXTURES[name]
    parsed, findings = run(fixture(name))
    if "BIT016" in entry["codes"]:
        assert codes(findings) == ["BIT016"]
    else:
        assert findings == (), name
    assert parsed is not None


def test_parsed_policy_is_frozen() -> None:
    parsed, _ = run(sr_example())
    assert parsed is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.line = 9  # type: ignore[misc]


def test_plugins_in_document_order_with_1_based_index() -> None:
    parsed, findings = run(fixture("valid/three-plugins.bit"))
    assert findings == () and parsed is not None
    assert [p.index for p in parsed.plugins] == [1, 2, 3]
    assert [p.path for p in parsed.plugins] == [
        f"Policy/PluginsGroups/Plugin[{i}]" for i in (1, 2, 3)
    ]
    assert [p.line for p in parsed.plugins] == sorted(p.line for p in parsed.plugins)


# CHK-M7-051 to -053: every BIT002 fixture ------------------------------------


@pytest.mark.parametrize("name", fixtures_in("bit002"))
def test_bit002_fixture_gives_only_bit002_and_no_parsed_policy(name: str) -> None:
    entry = FIXTURES[name]
    assert entry["codes"] == ["BIT002"]
    parsed, findings = run(fixture(name, canary="/nonexistent"))
    assert parsed is None
    assert findings and set(codes(findings)) == {"BIT002"}, findings
    lines = entry.get("lines")
    assert lines, name
    assert findings[0].line in lines, (findings, lines)
    assert [f.line for f in findings] == sorted(f.line or 0 for f in findings)
    for f in findings:
        assert f.message and len(f.message) <= 160


@pytest.mark.parametrize("name", sorted(MISCASED))
def test_miscased_names_are_missing_plus_unknown(name: str) -> None:
    assert FIXTURES[name]["lines"] == MISCASED[name]
    parsed, findings = run(fixture(name))
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [
        (Code.BIT002, MISCASED[name][0]),
        (Code.BIT002, MISCASED[name][1]),
    ]


# Missing, duplicated and out-of-order elements, built from the SR example ----


@pytest.mark.parametrize(
    "element",
    ["PolicyName", "PolicyDescription", "PolicyStatus", "FamilyName", "PluginName",
     "PluginDescription", "PluginId", "Execute"],
)  # fmt: skip
def test_missing_required_element_is_bit002_at_parent_line(element: str) -> None:
    text = sr_text()
    start = text.index(f"<{element}")
    end = text.index(f"</{element}>") + len(f"</{element}>")
    data = (text[:start] + text[end:]).encode()
    parsed, findings = run(data)
    assert parsed is None
    parent = {
        "FamilyName": "<Family>",
        "PluginName": "<Plugin>",
        "PluginDescription": "<Plugin>",
        "PluginId": "<Plugin>",
        "Execute": "<Plugin>",
    }.get(element, "<Policy")
    path = {
        "FamilyName": "Policy/Family/FamilyName",
    }.get(element, f"Policy/{element}")
    if parent == "<Plugin>":
        path = f"Policy/PluginsGroups/Plugin[1]/{element}"
    assert [(f.code, f.line, f.element) for f in findings] == [
        (Code.BIT002, line_of(text, parent), path)
    ]


@pytest.mark.parametrize("element", ["Family", "PluginsGroups"])
def test_missing_container_is_bit002(element: str) -> None:
    text = sr_text()
    start = text.index(f"<{element}>")
    end = text.index(f"</{element}>") + len(f"</{element}>")
    parsed, findings = run((text[:start] + text[end:]).encode())
    assert parsed is None
    assert (findings[0].code, findings[0].line, findings[0].element) == (
        Code.BIT002,
        2,
        f"Policy/{element}",
    )


@pytest.mark.parametrize("element", POLICY[:3] + ["FamilyName"] + PLUGIN)
def test_duplicate_element_is_bit002_at_the_second(element: str) -> None:
    text = sr_text()
    start = text.index(f"<{element}")
    end = text.index(f"</{element}>") + len(f"</{element}>")
    copy = text[start:end]
    data = (text[:end] + "\n" + copy + text[end:]).encode()
    parsed, findings = run(data)
    assert parsed is None
    second = line_of(text, f"<{element}") + copy.count("\n") + 1
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, second)]


def test_second_family_is_bit002() -> None:
    # #10: exactly one Family.
    text = sr_text()
    fam = text[text.index("<Family>") : text.index("</Family>") + len("</Family>")]
    data = text.replace(fam, fam + "\n  " + fam).encode()
    parsed, findings = run(data)
    assert parsed is None
    assert codes(findings) == ["BIT002"]
    assert findings[0].line == line_of(text, "<Family>") + fam.count("\n") + 1


@pytest.mark.parametrize(
    ("first", "second"),
    [(POLICY[i], POLICY[i + 1]) for i in range(4)]
    + [(PLUGIN[i], PLUGIN[i + 1]) for i in range(5)],
)
def test_adjacent_swap_is_bit002(first: str, second: str) -> None:
    text = sr_text()

    def span(name: str) -> tuple[int, int]:
        s = text.index(f"<{name}")
        return s, text.index(f"</{name}>") + len(f"</{name}>")

    (a0, a1), (b0, b1) = span(first), span(second)
    swapped = text[:a0] + text[b0:b1] + text[a1:b0] + text[a0:a1] + text[b1:]
    parsed, findings = run(swapped.encode())
    assert parsed is None
    assert codes(findings) == ["BIT002"]
    moved_line = line_of(swapped, f"<{first}")
    assert findings[0].line in (line_of(swapped, f"<{second}"), moved_line)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<PolicyName>", "<policyName>"),
        ("<Plugin>", "<plugin>"),
        ("<Policy formatVersion", "<policy formatVersion"),
        ("<FamilyName>", "<Familyname>"),
        ("<ExpectedResult>", "<EXPECTEDRESULT>"),
    ],
)
def test_case_sensitive_names(old: str, new: str) -> None:
    closing_old = "</" + old[1:].split(" ")[0].rstrip(">") + ">"
    closing_new = "</" + new[1:].split(" ")[0].rstrip(">") + ">"
    text = sr_text().replace(old, new, 1).replace(closing_old, closing_new, 1)
    parsed, findings = run(text.encode())
    assert parsed is None
    assert codes(findings) and set(codes(findings)) == {"BIT002"}


def test_wrong_root_is_one_bit002() -> None:
    parsed, findings = run(b'<?xml version="1.0"?>\n<Policies><X/></Policies>')
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, 2)]


@pytest.mark.parametrize("root", ["policy", "POLICY", "PolicY"])
def test_miscased_root_without_attributes_is_bit002(root: str) -> None:
    # No formatVersion, so only the root-name rule can catch it.
    text = sr_text().replace('<Policy formatVersion="1.0">', f"<{root}>", 1)
    text = text.replace("</Policy>", f"</{root}>", 1)
    parsed, findings = run(text.encode())
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, 2)]


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ("<PluginsGroups>\n  </PluginsGroups>", 9),
        ("<PluginsGroups/>", 9),
        ("<PluginsGroups><!-- none --></PluginsGroups>", 9),
    ],
)
def test_empty_pluginsgroups_is_bit002(body: str, line: int) -> None:
    # #16: empty PluginsGroups is BIT002 (not BIT017).
    text = sr_text()
    start = text.index("<PluginsGroups>")
    end = text.index("</PluginsGroups>") + len("</PluginsGroups>")
    parsed, findings = run((text[:start] + body + text[end:]).encode())
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, line)]


@pytest.mark.parametrize(
    ("old", "new", "line"),
    [
        ("<Family>", "<Family>\n    <Author>x</Author>", 7),
        ("<PluginsGroups>", "<PluginsGroups>\n    <Group/>", 10),
        ("<Operator>", "<Severity>high</Severity><Operator>", 17),
        ("<PolicyStatus>", "<Version>1</Version><PolicyStatus>", 5),
    ],
)
def test_unknown_element_is_bit002_at_its_line(old: str, new: str, line: int) -> None:
    parsed, findings = run(mutate(old, new))
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, line)]


@pytest.mark.parametrize(
    ("old", "new", "line"),
    [
        ('<Policy formatVersion="1.0">', '<Policy formatVersion="1.0" id="x">', 2),
        ("<Plugin>", '<Plugin id="1">', 10),
        ('<Execute timeout="30">', '<Execute timeout="30" user="root">', 14),
        ("<Family>", '<Family lang="en">', 6),
        ("<PluginsGroups>", '<PluginsGroups n="1">', 9),
        ("<PolicyName>", '<PolicyName lang="en">', 3),
        ("<Operator>", '<Operator timeout="5">', 17),
        ("<ExpectedResult>", '<ExpectedResult formatVersion="1.0">', 18),
        ('<Execute timeout="30">', '<Execute Timeout="30">', 14),
        ('<Policy formatVersion="1.0">', '<Policy FormatVersion="1.0">', 2),
        ("<PolicyName>", '<PolicyName xml:lang="en">', 3),
    ],
)
def test_unknown_attribute_is_bit002(old: str, new: str, line: int) -> None:
    parsed, findings = run(mutate(old, new))
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, line)]


@pytest.mark.parametrize(
    ("old", "new", "line"),
    [
        ("<Family>", "<Family>stray", 6),
        ("<Plugin>", "<Plugin>stray", 10),
        ("</PluginsGroups>", "x</PluginsGroups>", 9),
        ("</Policy>", "x</Policy>", 2),
        ("<Family>", "<Family><![CDATA[x]]>", 6),
        ("<Family>", "<Family>&#160;", 6),  # U+00A0 is not XML whitespace
    ],
)
def test_non_whitespace_text_in_container_is_bit002(
    old: str, new: str, line: int
) -> None:
    parsed, findings = run(mutate(old, new))
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [(Code.BIT002, line)]


def test_whitespace_and_comments_between_elements_ignored() -> None:
    # #105 (b), (d): whitespace-only text and comments in containers are fine.
    data = mutate("<Family>", "<Family>\r\n\t <!-- c --> <![CDATA[ \t]]>")
    parsed, findings = run(data)
    assert findings == () and parsed is not None


@pytest.mark.parametrize(
    "element", ["PolicyName", "PolicyDescription", "PolicyStatus", "FamilyName",
                "PluginName", "PluginId", "Execute", "Operator", "ExpectedResult"],
)  # fmt: skip
def test_child_in_leaf_is_bit002(element: str) -> None:
    text = sr_text()
    tag_end = text.index(">", text.index(f"<{element}")) + 1
    data = (text[:tag_end] + "<b>x</b>" + text[tag_end:]).encode()
    parsed, findings = run(data)
    assert parsed is None
    assert [(f.code, f.line) for f in findings] == [
        (Code.BIT002, line_of(text, f"<{element}"))
    ]


@pytest.mark.parametrize(
    ("where", "line"),
    [
        ('<?xml version="1.0" encoding="UTF-8"?>\n',
         '<?xml version="1.0" encoding="UTF-8"?>\n<?pi x?>\n'),
        ("<Family>", "<Family><?pi x?>"),
        ('<Execute timeout="30"><![CDATA[', '<Execute timeout="30"><?p?><![CDATA['),
        ("</Policy>", "</Policy>\n<?tail?>"),
    ],
)  # fmt: skip
def test_processing_instructions_are_bit002(where: str, line: str) -> None:
    parsed, findings = run(mutate(where, line))
    assert parsed is None
    assert codes(findings) == ["BIT002"]


def test_pi_findings_have_their_lines() -> None:
    data = mutate("</Policy>", "</Policy>\n<?a?>\n\n<?b?>")
    _, findings = run(data)
    text = data.decode()
    assert [f.line for f in findings] == [line_of(text, "<?a"), line_of(text, "<?b")]


def test_namespaced_documents_give_one_bit002_not_bit001() -> None:
    # Main's ask (TASK-141 change 1): the parser reports namespaces; the
    # structure check never runs on them, so there is no second report.
    for old, new in [
        ('<Policy formatVersion="1.0">',
         '<Policy formatVersion="1.0" xmlns="urn:bitscan">'),
        ("<PolicyName>", '<PolicyName xmlns:b="urn:b">'),
        ("<Family>", '<Family xmlns="">'),
    ]:  # fmt: skip
        parsed, findings = run(mutate(old, new))
        assert parsed is None
        assert [f.code for f in findings] == [Code.BIT002]


def test_xml_prefixed_element_is_bit002() -> None:
    data = mutate("<PolicyName>", "<xml:PolicyName>").replace(
        b"</PolicyName>", b"</xml:PolicyName>", 1
    )
    parsed, findings = run(data)
    assert parsed is None
    assert set(codes(findings)) == {"BIT002"}


# CHK-M7-054: missing Operator / ExpectedResult (#2) -------------------------


def _two_plugins(drop: str) -> bytes:
    text = fixture("valid/three-plugins.bit").decode()
    starts = [i for i in range(len(text)) if text.startswith("<Plugin>", i)]
    second = text[starts[1] :]
    s = second.index(f"<{drop}>")
    e = second.index(f"</{drop}>") + len(f"</{drop}>")
    return (text[: starts[1]] + second[:s] + second[e:]).encode()


@pytest.mark.parametrize("drop", ["Operator", "ExpectedResult"])
def test_missing_operator_or_expected_left_for_content_rules(drop: str) -> None:
    parsed, findings = run(_two_plugins(drop))
    assert findings == ()
    assert parsed is not None
    p1, p2, p3 = parsed.plugins
    field = "operator" if drop == "Operator" else "expected_result"
    assert getattr(p2, field) is None
    assert getattr(p1, field) is not None and getattr(p3, field) is not None


def test_missing_both_operator_and_expected() -> None:
    text = sr_text()
    for name in ("Operator", "ExpectedResult"):
        s = text.index(f"<{name}>")
        text = text[:s] + text[text.index(f"</{name}>") + len(f"</{name}>") :]
    parsed, findings = run(text.encode())
    assert findings == () and parsed is not None
    assert parsed.plugins[0].operator is None
    assert parsed.plugins[0].expected_result is None


@pytest.mark.parametrize(
    "name", ["content/bit010-missing.bit", "content/bit011-missing.bit"]
)
def test_missing_fixtures_are_not_bit002(name: str) -> None:
    parsed, findings = run(fixture(name))
    assert findings == () and parsed is not None


def test_expected_before_operator_still_bit002() -> None:
    # #2 exempts a missing element, not a misplaced one.
    text = sr_text()
    op = text[text.index("<Operator>") : text.index("</Operator>") + 11]
    data = text.replace(op + "\n      ", "").replace(
        "</ExpectedResult>", "</ExpectedResult>" + op
    )
    parsed, findings = run(data.encode())
    assert parsed is None and codes(findings) == ["BIT002"]


# CHK-M7-055: formatVersion (BIT016) ----------------------------------------


@pytest.mark.parametrize("value", ["1.1", "1.00", "", "2.0", " 1.0", "1.0 ", "1"])
def test_unsupported_format_version_is_bit016(value: str) -> None:
    data = mutate('formatVersion="1.0"', f'formatVersion="{value}"')
    parsed, findings = run(data)
    assert [(f.code, f.line, f.element) for f in findings] == [
        (Code.BIT016, 2, "Policy/@formatVersion")
    ]
    # SR §4: only BIT001 and BIT002 stop the content rules.
    assert parsed is not None


def test_format_version_absent_or_1_0() -> None:
    parsed, findings = run(mutate(' formatVersion="1.0"', ""))
    assert findings == () and parsed is not None
    assert parsed.format_version is None  # stored as 1.0 by the store (SR §3.2)
    parsed, findings = run(sr_example())
    assert findings == () and parsed is not None
    assert parsed.format_version is not None
    assert parsed.format_version.text == "1.0"


@pytest.mark.parametrize(
    "name", [f for f in FIXTURES if f.startswith("content/bit016")]
)
def test_bit016_fixtures(name: str) -> None:
    entry = FIXTURES[name]
    parsed, findings = run(fixture(name))
    assert codes(findings) == ["BIT016"]
    assert findings[0].line == entry["lines"][0]
    assert findings[0].element == entry["element"]
    assert parsed is not None


# CHK-M7-056: BIT002 masks the content codes and BIT016 ---------------------


@pytest.mark.parametrize(
    "name",
    ["bit002/plus-bit003.bit", "bit002/plus-bit016.bit", "bit002/plus-bit102.bit"],
)
def test_bit002_masks_other_codes(name: str) -> None:
    parsed, findings = run(fixture(name))
    assert parsed is None
    assert set(codes(findings)) == {"BIT002"}


def test_bit002_and_bad_format_version_reports_only_bit002() -> None:
    data = mutate('formatVersion="1.0"', 'formatVersion="9"').replace(
        b"<Family>", b"<Family>stray", 1
    )
    parsed, findings = run(data)
    assert parsed is None
    assert codes(findings) == ["BIT002"]


def test_bit001_stops_before_structure() -> None:
    parsed, findings = run(mutate("</Policy>", "</Polic>"))
    assert parsed is None and codes(findings) == ["BIT001"]


# CHK-M7-057: comments are never part of a value ----------------------------


def test_comments_inside_values_ignored() -> None:
    data = mutate("<PolicyName>CIS", "<PolicyName><!-- hidden -->CIS")
    data = data.replace(b"<![CDATA[", b"<!-- x --><![CDATA[", 1)
    data = data.replace(
        b"]]></Execute>", b"]]><!-- rm -rf / --><![CDATA[ ]]></Execute>"
    )
    parsed, findings = run(data)
    assert findings == () and parsed is not None
    assert parsed.policy_name.text == "CIS Ubuntu 24.04 Level 1 - Server"
    assert "hidden" not in repr(parsed) and "rm -rf" not in repr(parsed)
    assert parsed.plugins[0].execute.text.endswith("2>/dev/null\n       ")


def test_comments_fixture() -> None:
    parsed, findings = run(fixture("valid/comments.bit"))
    assert findings == () and parsed is not None
    assert parsed.plugins[0].expected_result is not None
    assert parsed.plugins[0].expected_result.text.strip() == "install ok installed"


# Messages: fixed text, names quoted at most 64 chars (#105 (g)) ------------


def test_unknown_names_quoted_and_bounded() -> None:
    long_name = "A" * 300
    parsed, findings = run(mutate("<Family>", f"<Family><{long_name}/>"))
    assert parsed is None
    (f,) = findings
    assert long_name not in f.message
    assert "A" * 64 in f.message and len(f.message) < 160
    assert f.element == "Policy/Family"


def test_element_paths_follow_105g() -> None:
    text = fixture("valid/three-plugins.bit").decode()
    starts = [i for i in range(len(text)) if text.startswith("<Execute", i)]
    assert len(starts) == 3
    i = starts[2] + len("<Execute")
    data = (text[:i] + ' bad="1"' + text[i:]).encode()
    _, findings = run(data)
    (f,) = findings
    assert f.code is Code.BIT002
    assert f.element is not None
    assert f.element.startswith("Policy/PluginsGroups/Plugin[3]/Execute")
    assert f.line == line_of(text, "<Execute", 3)
