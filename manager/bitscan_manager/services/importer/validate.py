"""Content rules over a structurally valid file (SR §2, §4.1; REQ-152 to
REQ-155; open questions #2, #13, #16, #17, #105, #109, #110).

BIT003, BIT004, BIT005, BIT008, BIT010 to BIT014 and BIT017, plus the BIT101
and BIT103 warnings. Every failing rule is reported (SR L250), ordered by line
and then by rule. BIT007 and BIT015 need the database and run in the store;
this module gives them their inputs as `RuleKeys`. BIT016 comes from the
structure check and does not stop these rules. Pure: no I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Literal, cast
from uuid import UUID

from bitscan_manager.services.importer.model import (
    LENGTH_LIMITS,
    NUMERIC_OPERATORS,
    OPERATORS,
    PLUGINS_MAX,
    POLICY_STATUSES,
    PRESENCE_OPERATORS,
    REGEX_OPERATORS,
    TIMEOUT_DEFAULT,
    TIMEOUT_MAX,
    TIMEOUT_MIN,
    Code,
    Finding,
    ParsedPlugin,
    ParsedPolicy,
    RawValue,
    plugin_path,
    quote,
)
from bitscan_manager.services.importer.store import (
    Candidate,
    CandidatePlugin,
    RuleId,
    RuleKeys,
)
from bitscan_manager.services.importer.values import (
    control_ref,
    is_number,
    is_plugin_uuid,
    is_valid_pattern,
    trim_xml,
)

FORMAT_VERSION: Final = "1.0"  # stored either way: BIT016 rejects any other (#16)


@dataclass(frozen=True, slots=True)
class Validated:
    findings: tuple[Finding, ...]  # warnings included (#110)
    rules: RuleKeys  # always built: the structure passed
    candidate: Candidate | None  # None when any finding here rejects


class _Rules:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, value: RawValue, code: Code, message: str) -> None:
        self.findings.append(Finding(value.line, value.path, code, message))

    def text(self, value: RawValue, name: str) -> str | None:
        """The trimmed value (#17), or None after BIT017 for its length;
        lengths count characters, as VARCHAR(n) does."""
        text = trim_xml(value.text)
        low, high = LENGTH_LIMITS[name]
        if not low <= len(text) <= high:
            span = f"{low:,}" if low == high else f"{low:,} to {high:,}"
            self.add(value, Code.BIT017, f"{name} must be {span} characters long.")
            return None
        return text


def validate(parsed: ParsedPolicy) -> Validated:
    rules = _Rules()
    name = rules.text(parsed.policy_name, "PolicyName")
    description = rules.text(parsed.policy_description, "PolicyDescription")
    status = trim_xml(parsed.policy_status.text)
    if not (status.isascii() and status.lower() in POLICY_STATUSES):
        rules.add(
            parsed.policy_status,
            Code.BIT003,
            f"PolicyStatus must be enabled or disabled, not {quote(status)}.",
        )
    family = rules.text(parsed.family_name, "FamilyName")
    plugins: list[CandidatePlugin] = []
    ids: list[RuleId] = []
    seen: set[str] = set()
    for plugin in parsed.plugins:
        built = _plugin(rules, plugin, seen, ids)
        if built is not None:
            plugins.append(built)
    if len(parsed.plugins) > PLUGINS_MAX:
        extra = parsed.plugins[PLUGINS_MAX]
        rules.findings.append(
            Finding(
                extra.line,
                "Policy/PluginsGroups",
                Code.BIT017,
                f"A policy may hold at most {PLUGINS_MAX:,} plugins.",
            )
        )
    findings = tuple(
        sorted(rules.findings, key=lambda f: -1 if f.line is None else f.line)
    )  # stable: rule order within a line
    keys = RuleKeys(name, parsed.policy_name.line, tuple(ids))
    candidate = None
    if not any(f.rejects for f in findings):
        candidate = Candidate(
            policy_name=cast(str, name),
            policy_name_line=parsed.policy_name.line,
            policy_description=cast(str, description),
            file_status=cast(Literal["enabled", "disabled"], status.lower()),
            family_name=cast(str, family),
            format_version=FORMAT_VERSION,
            plugins=tuple(plugins),
        )
    return Validated(findings, keys, candidate)


def _plugin(
    rules: _Rules, plugin: ParsedPlugin, seen: set[str], ids: list[RuleId]
) -> CandidatePlugin | None:
    """One plugin's rules in element order; the CandidatePlugin when every
    value it needs passed, else None (the file is then rejected anyway)."""
    name = rules.text(plugin.plugin_name, "PluginName")
    # The warnings read the trimmed name whatever its length, so an empty
    # name gets BIT101 next to its BIT017 (fixture bit017-pluginname-whitespace).
    found = control_ref(trim_xml(plugin.plugin_name.text))
    ref = found.value
    if found.warning is Code.BIT101:
        rules.add(
            plugin.plugin_name,
            Code.BIT101,
            "PluginName has no leading control reference.",
        )
    elif found.warning is Code.BIT103:
        rules.add(
            plugin.plugin_name,
            Code.BIT103,
            "The control reference is longer than 32 characters; it is not stored.",
        )
    description = rules.text(plugin.plugin_description, "PluginDescription")
    plugin_id = _plugin_id(rules, plugin.plugin_id, seen)
    if plugin_id is not None:
        ids.append(RuleId(plugin_id, plugin.plugin_id.line, plugin.index))
    execute = trim_xml(plugin.execute.text)
    if not 1 <= len(execute) <= LENGTH_LIMITS["Execute"][1]:
        rules.add(
            plugin.execute, Code.BIT008, "Execute must be 1 to 16,384 characters long."
        )
    timeout = _timeout(rules, plugin.timeout)
    operator = _operator(rules, plugin)
    expected = _expected(rules, plugin, operator)
    if None in (name, description, plugin_id, timeout, operator, expected) or not (
        1 <= len(execute) <= LENGTH_LIMITS["Execute"][1]
    ):
        return None
    return CandidatePlugin(
        plugin_uuid=cast(UUID, plugin_id),
        line=plugin.plugin_id.line,
        plugin_name=cast(str, name),
        control_ref=ref,
        plugin_description=cast(str, description),
        execute=execute,
        execute_sha256=hashlib.sha256(execute.encode("utf-8")).hexdigest(),
        operator=cast(str, operator),
        expected_result=cast(str, expected),
        timeout_s=cast(int, timeout),
    )


def _plugin_id(rules: _Rules, value: RawValue, seen: set[str]) -> UUID | None:
    """BIT004 for the #109 form, BIT005 on the second use of an id."""
    text = trim_xml(value.text)
    if not is_plugin_uuid(text):
        rules.add(
            value, Code.BIT004, f"PluginId {quote(text)} is not a lowercase UUID."
        )
        return None
    if text in seen:
        rules.add(
            value, Code.BIT005, f"PluginId {quote(text)} is used twice in this file."
        )
        return None
    seen.add(text)
    return UUID(text)


def _timeout(rules: _Rules, value: RawValue | None) -> int | None:
    """#105 (e): ASCII digits only (leading zeros allowed), 1 to 600; absent
    means 60. The attribute is not trimmed: " 30" is BIT017."""
    if value is None:
        return TIMEOUT_DEFAULT
    digits = value.text.lstrip("0")
    if (
        value.text.isascii()
        and value.text.isdigit()
        and len(digits) <= 3  # bounded before int(), whatever the input length
        and TIMEOUT_MIN <= int(digits or "0") <= TIMEOUT_MAX
    ):
        return int(digits)
    rules.add(
        value,
        Code.BIT017,
        f"Execute/@timeout must be a whole number of seconds from {TIMEOUT_MIN} to "
        f"{TIMEOUT_MAX}, not {quote(value.text)}.",
    )
    return None


def _operator(rules: _Rules, plugin: ParsedPlugin) -> str | None:
    """BIT010 when Operator is missing (#2) or not one of the 14; stored
    lowercase."""
    if plugin.operator is None:
        rules.findings.append(
            Finding(
                plugin.line,
                plugin_path(plugin.index, "Operator"),
                Code.BIT010,
                "Operator is missing.",
            )
        )
        return None
    text = trim_xml(plugin.operator.text)
    if text.isascii() and text.lower() in OPERATORS:
        return text.lower()
    rules.add(
        plugin.operator,
        Code.BIT010,
        f"Operator {quote(text)} is not one of the 14 operators.",
    )
    return None


def _expected(rules: _Rules, plugin: ParsedPlugin, operator: str | None) -> str | None:
    """BIT011 when ExpectedResult is missing (#2), BIT017 for its length, and
    BIT014, BIT012 and BIT013 against a valid Operator (SR §2.4)."""
    value = plugin.expected_result
    if value is None:
        rules.findings.append(
            Finding(
                plugin.line,
                plugin_path(plugin.index, "ExpectedResult"),
                Code.BIT011,
                "ExpectedResult is missing.",
            )
        )
        return None
    text = rules.text(value, "ExpectedResult")
    if text is None or operator is None:  # too long: not compiled or parsed
        return text
    if (operator in PRESENCE_OPERATORS) != (text == ""):
        rules.add(
            value,
            Code.BIT014,
            f"ExpectedResult must be empty with {operator} and with no other operator."
            if operator in PRESENCE_OPERATORS
            else f"ExpectedResult must not be empty with {operator}.",
        )
        return None
    if operator in NUMERIC_OPERATORS and not is_number(text):
        rules.add(value, Code.BIT012, f"ExpectedResult {quote(text)} is not a number.")
        return None
    if operator in REGEX_OPERATORS and not is_valid_pattern(text):
        rules.add(
            value,
            Code.BIT013,
            f"ExpectedResult {quote(text)} is not a valid RE2 pattern.",
        )
        return None
    return text
