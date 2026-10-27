"""TP-M7-06: the content validators (TASK-144; REQ-152 to REQ-155, REQ-180).

Expected values come from SR §2.1-§2.4 (limits, enums, operators), §3.3
(control_ref), §3.5 (finding shape), §4 (every failing rule reported, in
document order), §4.1 (codes and severities) and the approved answers #2, #13,
#16, #17, #105 (e), (g), #109, #110; fixtures and manifest from bits/tests
(tester-m7). The pipeline order is SR §4: parse, structure, then the content
rules (and BIT102, TASK-146) only on a ParsedPolicy. CHK-M7-065 to -077;
plants CHK-M7-326, -348. Owner: tester-m7b.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from bitscan_manager.services.importer import validate as validate_mod
from bitscan_manager.services.importer.bit102 import check_execute
from bitscan_manager.services.importer.model import (
    Code,
    Finding,
    ParsedPlugin,
    ParsedPolicy,
    RawValue,
    Severity,
)
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.store import RuleId
from bitscan_manager.services.importer.structure import check
from bitscan_manager.services.importer.validate import Validated, validate
from bitscan_manager.services.importer.values import trim_xml
from tests.bit_unit import FIXTURES, canonical, fixture, fixtures_in
from tests.test_bit_fixtures import sr_example

RETIRED = {"BIT006", "BIT009", "BIT018", "BIT019", "BIT020"}
P1 = "Policy/PluginsGroups/Plugin[1]"


def parsed_of(data: bytes) -> ParsedPolicy:
    result = parse_bit(data)
    assert result.root is not None, result.findings
    structure = check(result.root, result.pi_lines)
    assert structure.parsed is not None, structure.findings
    return structure.parsed


def content(data: bytes) -> tuple[list[Finding], Validated | None]:
    """Every finding the file-local rules give, in the SR §4 order: parser,
    structure (BIT002 stops; BIT016 does not), validators, BIT102 per plugin."""
    result = parse_bit(data)
    if result.root is None:
        return list(result.findings), None
    structure = check(result.root, result.pi_lines)
    if structure.parsed is None:
        return list(structure.findings), None
    validated = validate(structure.parsed)
    found = list(structure.findings) + list(validated.findings)
    for p in structure.parsed.plugins:
        found += check_execute(trim_xml(p.execute.text), line=p.execute.line,
                               element=p.execute.path)  # fmt: skip
    return found, validated


def run(data: bytes) -> Validated:
    return validate(parsed_of(data))


def codes(findings: list[Finding] | tuple[Finding, ...]) -> list[str]:
    return [f.code.value for f in findings]


def sr_text() -> str:
    return sr_example().decode("utf-8")


def sr_with(old: str, new: str) -> bytes:
    text = sr_text()
    assert old in text, old
    return text.replace(old, new, 1).encode("utf-8")


def sr_value(element: str, value: str) -> bytes:
    """The SR example with one element's whole content replaced."""
    text = sr_text()
    start = text.index(">", text.index(f"<{element}")) + 1
    end = text.index(f"</{element}>")
    return (text[:start] + value + text[end:]).encode("utf-8")


# CHK-M7-065: one fixture per content code, with its line and path -----------

CONTENT_FIXTURES = fixtures_in("content") + fixtures_in("valid")


@pytest.mark.parametrize("name", CONTENT_FIXTURES)
def test_fixture_codes_lines_and_paths(name: str) -> None:
    entry = FIXTURES[name]
    found, _ = content(fixture(name))
    assert sorted(set(codes(found))) == sorted(entry["codes"]), found
    if not entry["codes"]:
        return
    lines = entry.get("lines")
    expected_codes = entry["codes"]
    if lines and len(expected_codes) > 1 and len(lines) == len(expected_codes):
        for code, line in zip(expected_codes, lines, strict=True):
            first = next(f for f in found if f.code.value == code)
            assert first.line == line, (code, first)
    else:
        first = next(f for f in found if f.code.value == expected_codes[0])
        if lines:
            assert first.line in lines, (first, lines)
        if "element" in entry:
            assert first.element == entry["element"], first
        if "element_prefix" in entry:
            assert first.element is not None
            assert first.element.startswith(entry["element_prefix"]), first


def test_every_content_code_has_a_fixture_here() -> None:
    have = {c for n in CONTENT_FIXTURES for c in FIXTURES[n]["codes"]}
    want = {"BIT003", "BIT004", "BIT005", "BIT008", "BIT010", "BIT011", "BIT012",
            "BIT013", "BIT014", "BIT016", "BIT017", "BIT101", "BIT102",
            "BIT103"}  # fmt: skip
    assert want <= have


# CHK-M7-066: the SR §1.1 example and its Candidate --------------------------


def test_sr_example_has_no_finding_and_the_expected_candidate() -> None:
    v = run(sr_example())
    assert v.findings == ()
    c = v.candidate
    assert c is not None
    assert (c.policy_name, c.policy_name_line) == (
        "CIS Ubuntu 24.04 Level 1 - Server",
        3,
    )
    assert c.policy_description == (
        "CIS Benchmark Level 1 controls for Ubuntu 24.04 servers."
    )
    assert (c.file_status, c.family_name, c.format_version) == (
        "enabled",
        "CIS Ubuntu 24.04",
        "1.0",
    )
    (p,) = c.plugins
    execute = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"
    assert p.plugin_uuid == UUID("3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48")
    assert p.line == 13
    assert p.plugin_name == "1.3.1.1 - Ensure AppArmor is installed"
    assert p.control_ref == "1.3.1.1"
    assert p.plugin_description == "Checks that the AppArmor package is installed."
    assert p.execute == execute
    assert p.execute_sha256 == hashlib.sha256(execute.encode("utf-8")).hexdigest()
    assert (p.operator, p.expected_result, p.timeout_s) == (
        "equals",
        "install ok installed",
        30,
    )
    assert v.rules.policy_name == "CIS Ubuntu 24.04 Level 1 - Server"
    assert v.rules.policy_name_line == 3
    assert v.rules.plugin_ids == (RuleId(p.plugin_uuid, 13, 1),)


def test_format_version_absent_is_stored_1_0() -> None:
    v = run(sr_with(' formatVersion="1.0"', ""))
    assert v.findings == () and v.candidate is not None
    assert v.candidate.format_version == "1.0"


def test_nbsp_kept_and_unicode_round_trips() -> None:
    v = run(fixture("valid/nbsp-name.bit"))
    assert v.candidate is not None
    assert v.candidate.policy_name.count(" ") == 2
    v = run(fixture("valid/unicode.bit"))
    assert v.findings == () and v.candidate is not None


# CHK-M7-067: the bound table (characters, not bytes; trimming first) --------

BOUNDS = [
    ("PolicyName", 1, 128, Code.BIT017),
    ("PolicyDescription", 0, 4_000, Code.BIT017),
    ("FamilyName", 1, 128, Code.BIT017),
    ("PluginName", 1, 255, Code.BIT017),
    ("PluginDescription", 0, 4_000, Code.BIT017),
    ("ExpectedResult", 0, 4_000, Code.BIT017),
]


def _value_for(element: str, length: int) -> str:
    if element == "PluginName":  # keep a control reference: no BIT101 noise
        return ("1 " + "é" * length)[:length] if length else ""
    return "é" * length


@pytest.mark.parametrize(("element", "low", "high", "code"), BOUNDS)
def test_length_at_limit_accepted_one_over_refused(
    element: str, low: int, high: int, code: Code
) -> None:
    if element == "ExpectedResult":

        def make(n: int) -> bytes:
            return sr_value("ExpectedResult", "é" * n).replace(
                b"<Operator>equals", b"<Operator>contains"
            )
    else:

        def make(n: int) -> bytes:
            return sr_value(element, _value_for(element, n))

    at = make(high)
    assert (
        len(at) - len(make(0)) == 2 * high or element == "PluginName"
    )  # bytes != chars
    found, _ = content(at)
    assert found == [], found
    found, _ = content(make(high + 1))
    assert [(f.code, f.element) for f in found if f.code is code] == [
        (code, _path(element))
    ]
    if low == 0 and element != "ExpectedResult":
        found, _ = content(make(0))
        assert found == []


def _path(element: str) -> str:
    if element.startswith("Plugin") or element == "ExpectedResult":
        return f"{P1}/{element}"
    if element == "FamilyName":
        return "Policy/Family/FamilyName"
    return f"Policy/{element}"


def test_trimmed_before_the_length_check() -> None:
    padded = " \t\r\n" + "x" * 128 + "\n\t "
    found, v = content(sr_value("PolicyName", padded))
    assert found == [] and v is not None and v.candidate is not None
    assert v.candidate.policy_name == "x" * 128
    # U+00A0 is not trimmed (#17), so it counts.
    found, _ = content(sr_value("PolicyName", " " + "x" * 128))
    assert codes(found) == ["BIT017"]


@pytest.mark.parametrize(
    ("element", "code"),
    [
        ("PolicyName", "BIT017"),
        ("FamilyName", "BIT017"),
        ("PluginName", "BIT017"),
        ("Execute", "BIT008"),
    ],
)
@pytest.mark.parametrize("blank", ["", " ", "\n\t \r\n"])
def test_whitespace_only_counts_as_empty(element: str, code: str, blank: str) -> None:
    data = sr_value(element, blank if element != "Execute" else blank)
    found, _ = content(data)
    assert code in codes(found)


def test_execute_bound_16384() -> None:
    at = "echo " + "é" * (16_384 - 5)
    found, v = content(sr_value("Execute", "<![CDATA[\n  " + at + "\n  ]]>"))
    assert found == [] and v is not None and v.candidate is not None
    assert v.candidate.plugins[0].execute == at
    found, _ = content(sr_value("Execute", "<![CDATA[" + at + "é]]>"))
    assert [(f.code, f.element) for f in found] == [(Code.BIT008, f"{P1}/Execute")]


# CHK-M7-068: enums --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "stored"),
    [("enabled", "enabled"), ("ENABLED", "enabled"), ("Disabled", "disabled"),
     (" disabled\n", "disabled"), ("eNaBlEd", "enabled")],
)  # fmt: skip
def test_policy_status_any_case_stored_lowercase(value: str, stored: str) -> None:
    v = run(sr_value("PolicyStatus", value))
    assert v.findings == () and v.candidate is not None
    assert v.candidate.file_status == stored


@pytest.mark.parametrize(
    "value", ["on", "", "true", "enable", "en abled", "ＥＮＡＢＬＥＤ", "enabled ",
              "enabledx", "disabled;"],
)  # fmt: skip
def test_bad_policy_status_is_bit003(value: str) -> None:
    v = run(sr_value("PolicyStatus", value))
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT003, 5, "Policy/PolicyStatus")
    ]
    assert v.candidate is None


@pytest.mark.parametrize(
    ("value", "stored"),
    [("EQUALS", "equals"), ("Equals", "equals"), (" not_equals ", "not_equals"),
     ("NOT_CONTAINS", "not_contains")],
)  # fmt: skip
def test_operator_any_case_stored_lowercase(value: str, stored: str) -> None:
    data = sr_value("Operator", value)
    if stored != "equals":
        data = data.replace(b"install ok installed", b"x")
    v = run(data)
    assert v.findings == () and v.candidate is not None
    assert v.candidate.plugins[0].operator == stored


@pytest.mark.parametrize(
    "value", ["equal", "", "not equals", "==", "regexp", "ＥＱＵＡＬＳ", "equals ",
              "is", "matches"],
)  # fmt: skip
def test_bad_operator_is_bit010(value: str) -> None:
    v = run(sr_value("Operator", value))
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT010, 17, f"{P1}/Operator")
    ]


def test_all_14_operators_accepted() -> None:
    v = run(fixture("valid/all-operators.bit"))
    assert v.findings == () and v.candidate is not None
    assert sorted({p.operator for p in v.candidate.plugins}) == sorted(
        ["equals", "not_equals", "contains", "not_contains", "regex", "not_regex",
         "eq", "ne", "gt", "ge", "lt", "le", "empty", "not_empty"]
    )  # fmt: skip


# CHK-M7-069: BIT004 and BIT005 --------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["3F6C2A9E-8B1D-4E57-9A3C-2D7F0E6B1C48",
     "{3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48}",
     "urn:uuid:3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",
     "3f6c2a9e8b1d4e579a3c2d7f0e6b1c48",
     "", "x", "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4"],
)  # fmt: skip
def test_bad_plugin_id_is_bit004(value: str) -> None:
    v = run(sr_value("PluginId", value))
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT004, 13, f"{P1}/PluginId")
    ]
    assert v.rules.plugin_ids == ()


def test_padded_plugin_id_is_trimmed() -> None:
    v = run(sr_value("PluginId", "\n  3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48 \n"))
    assert v.findings == ()


def _same_id_three_times() -> bytes:
    body = canonical(3).decode()
    for i in (2, 3):
        body = body.replace(str(UUID(int=i + 1)), str(UUID(int=2)))
    return body.encode()


def test_duplicate_id_bit005_on_each_later_use() -> None:
    data = _same_id_three_times()
    text = data.decode()
    v = run(data)
    id_lines = [i + 1 for i, ln in enumerate(text.splitlines()) if "<PluginId>" in ln]
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT005, id_lines[1], "Policy/PluginsGroups/Plugin[2]/PluginId"),
        (Code.BIT005, id_lines[2], "Policy/PluginsGroups/Plugin[3]/PluginId"),
    ]
    assert [r.index for r in v.rules.plugin_ids] == [1]  # first use only
    assert v.candidate is None


# CHK-M7-070: the timeout table (#105 (e)) ----------------------------------


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("1", 1), ("600", 600), ("0600", 600), ("060", 60), ("00001", 1), ("30", 30),
     ("0" * 4_000 + "7", 7)],
)  # fmt: skip
def test_timeout_accepted(value: str, seconds: int) -> None:
    v = run(sr_with('timeout="30"', f'timeout="{value}"'))
    assert v.findings == () and v.candidate is not None
    assert v.candidate.plugins[0].timeout_s == seconds


def test_timeout_absent_is_60() -> None:
    v = run(sr_with(' timeout="30"', ""))
    assert v.findings == () and v.candidate is not None
    assert v.candidate.plugins[0].timeout_s == 60


@pytest.mark.parametrize(
    "value",
    ["0", "601", "30s", "1.5", "-1", "+5", " 30", "30 ", "", "٣٠", "３０", "0x1e",
     "1e2", "6000", "00", "9" * 5_000, "1_0", "&#x33;0x"],
)  # fmt: skip
def test_timeout_refused_is_bit017(value: str) -> None:
    v = run(sr_with('timeout="30"', f'timeout="{value}"'))
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT017, 14, f"{P1}/Execute/@timeout")
    ]


# CHK-M7-071: 5,000 plugins / 5,001 ----------------------------------------


def test_5000_plugins_accepted() -> None:
    v = run(canonical(5_000))
    assert v.findings == () and v.candidate is not None
    assert len(v.candidate.plugins) == 5_000
    assert len(v.rules.plugin_ids) == 5_000


def test_5001_plugins_is_bit017() -> None:
    # Through the pipeline the parser stops it (TASK-141; accepted by main).
    found, v = content(canonical(5_001))
    assert codes(found) == ["BIT017"] and v is None
    # validate's own rule, on a ParsedPolicy built directly.
    base = parsed_of(canonical(1))
    plugin = base.plugins[0]
    many = tuple(
        replace(
            plugin,
            index=i,
            line=plugin.line + 8 * (i - 1),
            plugin_id=RawValue(
                str(UUID(int=i)), plugin.plugin_id.line, plugin.plugin_id.path
            ),
        )
        for i in range(1, 5_002)
    )
    v2 = validate(replace(base, plugins=many))
    assert [(f.code, f.element) for f in v2.findings] == [
        (Code.BIT017, "Policy/PluginsGroups")
    ]
    assert v2.candidate is None


# CHK-M7-072: missing Operator / ExpectedResult (#2) ------------------------


def _drop(data: bytes, element: str, plugin: int) -> bytes:
    text = data.decode()
    starts = [i for i in range(len(text)) if text.startswith("<Plugin>", i)]
    head, tail = text[: starts[plugin - 1]], text[starts[plugin - 1] :]
    s = tail.index(f"<{element}>")
    e = tail.index(f"</{element}>") + len(f"</{element}>")
    return (head + tail[:s] + tail[e:]).encode()


def test_missing_operator_in_plugin_2_with_other_faults() -> None:
    data = _drop(fixture("valid/three-plugins.bit"), "Operator", 2)
    data = data.replace(b"<PolicyStatus>enabled", b"<PolicyStatus>on", 1)
    v = run(data)
    assert ("BIT010", "Policy/PluginsGroups/Plugin[2]/Operator") in [
        (f.code.value, f.element) for f in v.findings
    ]
    assert "BIT003" in codes(v.findings)
    plugin2_line = parsed_of(data).plugins[1].line
    bit010 = next(f for f in v.findings if f.code is Code.BIT010)
    assert bit010.line == plugin2_line
    assert v.candidate is None


def test_missing_expected_result_is_bit011() -> None:
    v = run(_drop(sr_example(), "ExpectedResult", 1))
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT011, 10, f"{P1}/ExpectedResult")
    ]


def test_missing_operator_with_expected_gives_no_bit014() -> None:
    v = run(_drop(sr_example(), "Operator", 1))
    assert codes(v.findings) == ["BIT010"]


# CHK-M7-073: BIT012, BIT013, BIT014 ---------------------------------------

NUMERIC = ["eq", "ne", "gt", "ge", "lt", "le"]


@pytest.mark.parametrize("op", NUMERIC)
@pytest.mark.parametrize("value", ["abc", "1e3", "nan", "inf", ".5", "5.", "0x10",
                                   "1_000", "١", "1 2", "--1"])  # fmt: skip
def test_numeric_operator_needs_a_number(op: str, value: str) -> None:
    v = run(sr_with("<Operator>equals", f"<Operator>{op}").replace(
        b"install ok installed", value.encode()))  # fmt: skip
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT012, 18, f"{P1}/ExpectedResult")
    ]


@pytest.mark.parametrize("op", NUMERIC)
@pytest.mark.parametrize("value", ["0", "-1", "+2.5", "14", " 14 ", "007"])
def test_numeric_operator_with_a_number_passes(op: str, value: str) -> None:
    v = run(sr_with("<Operator>equals", f"<Operator>{op}").replace(
        b"install ok installed", value.encode()))  # fmt: skip
    assert v.findings == ()
    assert v.candidate is not None
    assert v.candidate.plugins[0].expected_result == value.strip()


@pytest.mark.parametrize("op", ["regex", "not_regex"])
@pytest.mark.parametrize(
    "value", ["(?=x)", "(a)\\1", "[", "(?&lt;!a)b", "a{2,1}", "(?!x)y"]
)
def test_regex_operators_need_an_re2_pattern(op: str, value: str) -> None:
    # Red for CHK-M7-326 (BIT013 skipped for not_regex).
    v = run(sr_with("<Operator>equals", f"<Operator>{op}").replace(
        b"install ok installed", value.encode()))  # fmt: skip
    assert [(f.code, f.line, f.element) for f in v.findings] == [
        (Code.BIT013, 18, f"{P1}/ExpectedResult")
    ]


@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_valid_re2_pattern_passes(op: str) -> None:
    v = run(sr_with("<Operator>equals", f"<Operator>{op}").replace(
        b"install ok installed", rb"^MaxAuthTries\s+[1-4]$"))  # fmt: skip
    assert v.findings == ()


@pytest.mark.parametrize(
    ("op", "value", "code"),
    [("empty", "x", "BIT014"), ("not_empty", "x", "BIT014"), ("equals", "", "BIT014"),
     ("contains", " \n ", "BIT014"), ("regex", "", "BIT014"), ("eq", "", "BIT014"),
     ("empty", "", None), ("not_empty", "\n  \t", None), ("empty", " ", "BIT014")],
)  # fmt: skip
def test_bit014_both_directions(op: str, value: str, code: str | None) -> None:
    data = sr_with("<Operator>equals", f"<Operator>{op}").replace(
        b"install ok installed", value.encode()
    )
    v = run(data)
    assert codes(v.findings) == ([code] if code else [])
    if code:  # BIT014 alone: no BIT012/BIT013 on top
        assert v.findings[0].element == f"{P1}/ExpectedResult"


# CHK-M7-074: all faults reported, in line order ---------------------------


def test_three_faults_on_three_lines_in_order() -> None:
    found, v = content(fixture("content/three-faults.bit"))
    assert codes(found) == ["BIT003", "BIT004", "BIT012"]
    assert [f.line for f in found] == [6, 14, 25]
    assert v is not None and v.candidate is None


def test_many_faults_across_plugins_sorted_by_line() -> None:
    data = canonical(4).decode()
    data = data.replace("<PolicyStatus>enabled", "<PolicyStatus>x")
    data = data.replace(str(UUID(int=3)), "BAD")
    data = data.replace('timeout="30"', 'timeout="0"', 1)
    data = data.replace("<Operator>not_empty", "<Operator>nope", 4)
    v = run(data.encode())
    lines = [f.line or 0 for f in v.findings]
    assert lines == sorted(lines)
    assert codes(v.findings).count("BIT010") == 4
    assert {"BIT003", "BIT004", "BIT017"} <= set(codes(v.findings))


@pytest.mark.parametrize("name", CONTENT_FIXTURES)
def test_findings_sorted_by_line_for_every_fixture(name: str) -> None:
    v = run(fixture(name)) if parse_bit(fixture(name)).root is not None else None
    if v is None:
        return
    lines = [-1 if f.line is None else f.line for f in v.findings]
    assert lines == sorted(lines)


def test_same_line_findings_keep_rule_order() -> None:
    # PluginName: BIT017 (length) then BIT101 (warning), both at its line.
    found, _ = content(fixture("content/bit017-pluginname-whitespace.bit"))
    assert codes(found) == ["BIT017", "BIT101"]
    assert found[0].line == found[1].line


# CHK-M7-075: warnings (#110) ----------------------------------------------


def test_warnings_only_file_has_a_candidate() -> None:
    v = run(fixture("valid/warnings-only.bit"))
    assert set(codes(v.findings)) == {"BIT101", "BIT103"}
    assert all(f.severity is Severity.WARN and not f.rejects for f in v.findings)
    assert v.candidate is not None
    refs = [p.control_ref for p in v.candidate.plugins]
    assert None in refs
    assert any(r is not None and len(r) == 31 for r in refs)


def test_warning_listed_with_an_error() -> None:
    found, v = content(fixture("content/warning-with-error.bit"))
    assert set(codes(found)) == {"BIT101", "BIT010"}
    assert v is not None and v.candidate is None


@pytest.mark.parametrize(
    ("name", "warning"),
    [("1.3.1.1 - x", None), ("Ensure x", "BIT101"), ("١.٢ x", "BIT101"),
     ("1" * 32 + " x", None), ("1" * 33 + " x", "BIT103")],
)  # fmt: skip
def test_control_ref_warnings(name: str, warning: str | None) -> None:
    v = run(sr_value("PluginName", name))
    assert codes(v.findings) == ([warning] if warning else [])
    assert v.candidate is not None
    ref = v.candidate.plugins[0].control_ref
    assert (ref is None) == (warning is not None)


# CHK-M7-076: messages and the finding shape -------------------------------


def test_messages_quote_at_most_64_characters() -> None:
    long = "Z" * 5_000
    v = run(sr_value("PolicyStatus", long))
    (f,) = v.findings
    assert long not in f.message and "Z" * 64 in f.message and "Z" * 65 not in f.message
    v = run(sr_value("Operator", "op" + "\x7f" + "\\" + "Y" * 300))
    (f,) = v.findings
    assert "\x7f" not in f.message and "\\x7f" in f.message and "\\\\" in f.message


def test_control_characters_escaped() -> None:
    v = run(sr_value("PolicyStatus", "a&#9;b&#10;c"))  # tab and LF via char refs
    (f,) = v.findings
    assert "\t" not in f.message and "\n" not in f.message


def test_long_execute_never_quoted_whole() -> None:
    execute = "rm -rf /etc/" + "x" * 16_000
    found, _ = content(sr_value("Execute", "<![CDATA[" + execute + "]]>"))
    assert found and all(execute not in f.message for f in found)
    assert all(len(f.message) < 400 for f in found)


@pytest.mark.parametrize("name", CONTENT_FIXTURES)
def test_finding_json_has_exactly_four_keys(name: str) -> None:
    found, _ = content(fixture(name))
    for f in found:
        item = f.to_json()
        assert set(item) == {"line", "element", "code", "message"}
        assert item["line"] is None or isinstance(item["line"], int)
        assert item["element"] is None or isinstance(item["element"], str)
        assert json.loads(json.dumps(item)) == item


# CHK-M7-077: retired codes never appear -----------------------------------


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_no_retired_code_across_fixtures(name: str) -> None:
    found, _ = content(fixture(name))
    assert not RETIRED & set(codes(found))


# RuleKeys and Candidate gating --------------------------------------------


def test_rule_keys_built_even_when_rejected() -> None:
    v = run(sr_value("PolicyStatus", "on"))
    assert v.candidate is None
    assert v.rules.policy_name == "CIS Ubuntu 24.04 Level 1 - Server"
    assert len(v.rules.plugin_ids) == 1


def test_rule_keys_policy_name_none_when_invalid() -> None:
    v = run(sr_value("PolicyName", "x" * 129))
    assert v.rules.policy_name is None and v.rules.policy_name_line == 3


def test_candidate_execute_and_sha_are_trimmed() -> None:
    v = run(sr_value("Execute", "\n\t  cat /etc/hostname \r\n  "))
    assert v.candidate is not None
    p = v.candidate.plugins[0]
    assert p.execute == "cat /etc/hostname"
    assert p.execute_sha256 == hashlib.sha256(b"cat /etc/hostname").hexdigest()


def test_validated_is_frozen() -> None:
    v = run(sr_example())
    with pytest.raises(AttributeError):
        v.candidate = None  # type: ignore[misc]


def test_validate_does_not_mutate_its_input() -> None:
    parsed = parsed_of(fixture("content/three-faults.bit"))
    before = repr(parsed)
    validate(parsed)
    assert repr(parsed) == before


def test_parsed_plugin_type_guard() -> None:
    # Guard: the direct-construction test above builds real ParsedPlugins.
    assert isinstance(parsed_of(canonical(1)).plugins[0], ParsedPlugin)


# CHK-M7-348: no `re` in validate.py ---------------------------------------


def test_validate_module_imports_no_re() -> None:
    tree = ast.parse(Path(str(validate_mod.__file__)).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"re", "regex", "xml", "lxml", "logging", "os", "socket"}
