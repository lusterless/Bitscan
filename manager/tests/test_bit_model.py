"""TP-M7-02: importer model and code table (TASK-140; REQ-152, REQ-155).

Expected values come from SR §2, §3.3, §3.5, §4, §4.1, TS §5.2 (the
``plugin_operator`` enum) and the approved answers #57 and #105 (g); the spec
text is read by the test where it can be, never copied from the code.
CHK-M7-010 to -013 (tests/m7/test-plan.md).
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from bitscan_manager.services import importer
from bitscan_manager.services.importer import model
from bitscan_manager.services.importer.model import (
    LENGTH_LIMITS,
    SEVERITY,
    Code,
    Finding,
    Node,
    ParsedPlugin,
    ParsedPolicy,
    RawValue,
    Severity,
    plugin_path,
    quote,
)

REPO = Path(__file__).resolve().parents[2]
SR = REPO / "docs" / "spec" / "bit_Schema_Reference.md"
TS = REPO / "docs" / "spec" / "Technical_Specification.md"


def _sr_rule_rows() -> dict[str, str]:
    """`| `BITnnn` | rule | Severity |` rows of SR §4.1, read from the spec."""
    text = SR.read_text(encoding="utf-8")
    section = text.split("### 4.1 Rules", 1)[1].split("### 4.2", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`BIT"):
            rows[cells[0].strip("`")] = cells[2]
    return rows


SR_RULES = _sr_rule_rows()
RETIRED = ("BIT006", "BIT009", "BIT018", "BIT019", "BIT020")


# CHK-M7-010 -----------------------------------------------------------------


def test_sr_table_read_from_spec_has_18_rules() -> None:
    # Guard on the oracle itself: SR §4.1 lists 18 codes.
    assert len(SR_RULES) == 18
    assert set(SR_RULES.values()) == {"Reject", "Warn"}


def test_code_table_is_exactly_the_sr_codes() -> None:
    assert {c.value for c in Code} == set(SR_RULES)
    assert set(SEVERITY) == set(Code)


@pytest.mark.parametrize("code", sorted(SR_RULES))
def test_each_code_has_its_sr_severity(code: str) -> None:
    expected = Severity.WARN if SR_RULES[code] == "Warn" else Severity.REJECT
    assert SEVERITY[Code(code)] is expected
    finding = Finding(None, None, Code(code), "m")
    assert finding.severity is expected
    assert finding.rejects is (expected is Severity.REJECT)


def test_only_bit101_and_bit103_warn_and_bit102_rejects() -> None:
    # SR §4: severity is per rule, not by number range.
    assert sorted(c.value for c in Code if SEVERITY[c] is Severity.WARN) == [
        "BIT101",
        "BIT103",
    ]
    assert SEVERITY[Code.BIT102] is Severity.REJECT


@pytest.mark.parametrize("code", RETIRED)
def test_retired_codes_are_absent(code: str) -> None:
    assert code not in {c.value for c in Code}
    assert not hasattr(Code, code)
    with pytest.raises(ValueError):
        Code(code)
    with pytest.raises(ValueError):
        Finding(1, None, code, "m")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad", ["bit001", "BIT1", "BIT000", "BIT021", "BIT104", "", "X"]
)
def test_unknown_codes_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        Finding(1, None, bad, "m")  # type: ignore[arg-type]


def test_severity_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        SEVERITY[Code.BIT101] = Severity.REJECT  # type: ignore[index]


def test_finding_severity_cannot_be_set() -> None:
    finding = Finding(1, None, Code.BIT101, "m")
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        finding.severity = Severity.REJECT  # type: ignore[misc]
    with pytest.raises(TypeError):
        Finding(1, None, Code.BIT101, "m", Severity.REJECT)  # type: ignore[call-arg]


# CHK-M7-011 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("element", "limits"),
    [
        # SR §2.1 to §2.3 constraint columns
        ("PolicyName", (1, 128)),
        ("PolicyDescription", (0, 4000)),
        ("FamilyName", (1, 128)),
        ("PluginName", (1, 255)),
        ("PluginDescription", (0, 4000)),
        ("Execute", (1, 16384)),
        ("ExpectedResult", (0, 4000)),
    ],
)
def test_length_limits_equal_sr_section_2(
    element: str, limits: tuple[int, int]
) -> None:
    assert LENGTH_LIMITS[element] == limits


def test_length_limits_cover_exactly_the_text_elements() -> None:
    assert set(LENGTH_LIMITS) == {
        "PolicyName",
        "PolicyDescription",
        "FamilyName",
        "PluginName",
        "PluginDescription",
        "Execute",
        "ExpectedResult",
    }
    with pytest.raises(TypeError):
        LENGTH_LIMITS["PolicyName"] = (1, 129)  # type: ignore[index]


def test_ddl_varchar_widths_agree_with_the_limits() -> None:
    # TS §5.2: family_name VARCHAR(128), policy_name VARCHAR(128),
    # plugin_name VARCHAR(255), control_ref VARCHAR(32).
    ddl = TS.read_text(encoding="utf-8")
    for column, width in [
        ("family_name  VARCHAR", LENGTH_LIMITS["FamilyName"][1]),
        ("policy_name        VARCHAR", LENGTH_LIMITS["PolicyName"][1]),
        ("plugin_name        VARCHAR", LENGTH_LIMITS["PluginName"][1]),
        ("control_ref        VARCHAR", model.CONTROL_REF_MAX),
    ]:
        assert f"{column}({width})" in ddl, column


def test_scalar_limits() -> None:
    assert model.MAX_BIT_BYTES == 5_242_880  # 5 MiB (#57)
    assert (model.PLUGINS_MIN, model.PLUGINS_MAX) == (1, 5000)
    assert (model.TIMEOUT_MIN, model.TIMEOUT_MAX, model.TIMEOUT_DEFAULT) == (1, 600, 60)
    assert model.CONTROL_REF_MAX == 32
    assert model.FORMAT_VERSIONS == ("1.0",)
    assert model.FORMAT_VERSION_DEFAULT == "1.0"
    assert set(model.POLICY_STATUSES) == {"enabled", "disabled"}
    assert model.QUOTE_MAX == 64


def _ddl_enum(name: str) -> tuple[str, ...]:
    ddl = TS.read_text(encoding="utf-8")
    body = ddl.split(f"CREATE TYPE {name} AS ENUM (", 1)[1].split(");", 1)[0]
    return tuple(v.strip().strip("'") for v in body.replace("\n", " ").split(","))


def test_operators_are_the_14_of_sr_2_4_in_ddl_enum_order() -> None:
    assert model.OPERATORS == _ddl_enum("plugin_operator")
    assert len(model.OPERATORS) == 14
    assert set(model.NUMERIC_OPERATORS) == {"eq", "ne", "gt", "ge", "lt", "le"}
    assert set(model.REGEX_OPERATORS) == {"regex", "not_regex"}
    assert set(model.PRESENCE_OPERATORS) == {"empty", "not_empty"}
    groups = model.NUMERIC_OPERATORS + model.REGEX_OPERATORS + model.PRESENCE_OPERATORS
    assert len(set(groups)) == len(groups)
    assert set(groups) < set(model.OPERATORS)


def test_policy_statuses_match_ddl_enum() -> None:
    assert set(model.POLICY_STATUSES) == set(_ddl_enum("policy_status"))


# CHK-M7-012 -----------------------------------------------------------------


def test_finding_serialises_to_exactly_four_keys() -> None:
    out = Finding(
        14, "Policy/PluginsGroups/Plugin[1]/Execute", Code.BIT102, "m"
    ).to_json()
    assert out == {
        "line": 14,
        "element": "Policy/PluginsGroups/Plugin[1]/Execute",
        "code": "BIT102",
        "message": "m",
    }
    assert type(out["code"]) is str
    assert list(json.loads(json.dumps(out))) == ["line", "element", "code", "message"]


def test_file_level_finding_serialises_nulls() -> None:
    out = Finding(None, None, "BIT001", "not UTF-8").to_json()  # type: ignore[arg-type]
    assert json.dumps(out) == (
        '{"line": null, "element": null, "code": "BIT001", "message": "not UTF-8"}'
    )


def test_finding_accepts_plain_string_codes_and_normalises() -> None:
    finding = Finding(3, None, "BIT003", "m")  # type: ignore[arg-type]
    assert finding.code is Code.BIT003


# quote() and plugin_path(): REQ-155 (2), (3), #105 (g) ------------------------


def test_quote_keeps_at_most_64_characters_of_content() -> None:
    value = "é" * 16384
    out = quote(value)
    assert out.count("é") == 64
    assert out.startswith('"') and "é" * 65 not in out
    assert len(out) < 80


def test_quote_short_value_whole() -> None:
    assert quote("rm") == '"rm"'
    assert quote("") == '""'
    assert quote("x" * 64).count("x") == 64
    assert "..." not in quote("x" * 64)
    assert quote("x" * 65).endswith("...")


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("a\nb", "a\\nb"),
        ("a\tb", "a\\tb"),
        ("a\rb", "a\\rb"),
        ("a\x00b", "a\\x00b"),
        ("a\x1bb", "a\\x1bb"),
        ("a\x7fb", "a\\x7fb"),
        ("a" + chr(92) + "b", "a" + chr(92) * 2 + "b"),
    ],
)
def test_quote_escapes_controls_del_and_backslash(raw: str, shown: str) -> None:
    out = quote(raw)
    assert out == '"' + shown + '"'
    assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in out)


def test_quote_escaping_counts_source_characters() -> None:
    # 64 characters of the value are quoted even when each is escaped.
    out = quote("\x00" * 100)
    assert out.count("\\x00") == 64


def test_plugin_path_form() -> None:
    assert plugin_path(1) == "Policy/PluginsGroups/Plugin[1]"
    assert plugin_path(12, "Operator") == "Policy/PluginsGroups/Plugin[12]/Operator"
    assert plugin_path(3, "Execute/@timeout") == (
        "Policy/PluginsGroups/Plugin[3]/Execute/@timeout"
    )


# CHK-M7-013 -----------------------------------------------------------------


def _raw(text: str = "x", line: int = 1, path: str = "Policy/PolicyName") -> RawValue:
    return RawValue(text, line, path)


def _plugin() -> ParsedPlugin:
    return ParsedPlugin(
        index=1,
        line=10,
        plugin_name=_raw(),
        plugin_description=_raw(),
        plugin_id=_raw(),
        execute=_raw(),
        timeout=None,
        operator=None,
        expected_result=None,
    )


@pytest.mark.parametrize(
    "obj",
    [
        Finding(1, None, Code.BIT001, "m"),
        Node("Policy", 2, (("formatVersion", "1.0"),), "", ()),
        _raw(),
        _plugin(),
        ParsedPolicy(2, None, _raw(), _raw(), _raw(), _raw(), (_plugin(),)),
    ],
    ids=["Finding", "Node", "RawValue", "ParsedPlugin", "ParsedPolicy"],
)
def test_model_types_are_frozen_dataclasses(obj: object) -> None:
    assert dataclasses.is_dataclass(obj)
    field = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, None)


def test_missing_operator_and_expected_are_representable() -> None:
    # #2: a missing Operator / ExpectedResult reaches the content rules.
    plugin = _plugin()
    assert plugin.operator is None and plugin.expected_result is None
    assert plugin.path == "Policy/PluginsGroups/Plugin[1]"


def test_node_children_and_attributes_are_tuples() -> None:
    names = {f.name: f.type for f in dataclasses.fields(Node)}
    assert "tuple" in str(names["children"]) and "tuple" in str(names["attributes"])


@pytest.mark.parametrize("path", ["__init__.py", "model.py"])
def test_model_imports_nothing_that_parses_or_matches(path: str) -> None:
    source = Path(importer.__file__).with_name(path).read_text(encoding="utf-8")
    banned = ("xml", "lxml", "re", "re2", "subprocess", "os", "psycopg", "logging")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] not in banned, name


def test_package_exports() -> None:
    for name in (
        "Code",
        "Finding",
        "Severity",
        "SEVERITY",
        "LENGTH_LIMITS",
        "MAX_BIT_BYTES",
    ):
        assert getattr(importer, name) is getattr(model, name)
