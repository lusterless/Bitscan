"""Structure check over the parser's Node tree: BIT002 and BIT016 (SR §2,
§4.1; REQ-151; open questions #2, #10, #16, #105).

Canonical, case-sensitive names; each element once and in the SR §2 order;
exactly one Family (#10); at least one Plugin (#16); no unknown elements or
attributes, no text in containers, no processing instructions (#105). A
missing Operator or ExpectedResult is left to BIT010 / BIT011 (#2). Any
BIT002 finding means no ParsedPolicy, and only BIT002 is reported (SR §4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from bitscan_manager.services.importer.model import (
    FORMAT_VERSIONS,
    Code,
    Finding,
    Node,
    ParsedPlugin,
    ParsedPolicy,
    RawValue,
    plugin_path,
    quote,
)

_POLICY: Final = (
    "PolicyName",
    "PolicyDescription",
    "PolicyStatus",
    "Family",
    "PluginsGroups",
)
_FAMILY: Final = ("FamilyName",)
_PLUGIN: Final = (
    "PluginName",
    "PluginDescription",
    "PluginId",
    "Execute",
    "Operator",
    "ExpectedResult",
)
_OPTIONAL: Final = frozenset({"Operator", "ExpectedResult"})  # #2
_ATTRIBUTES: Final = {"Policy": ("formatVersion",), "Execute": ("timeout",)}
_XML_SPACE: Final = " \t\r\n"


@dataclass(frozen=True, slots=True)
class StructureResult:
    parsed: ParsedPolicy | None  # None when any BIT002 finding was made
    findings: tuple[Finding, ...]  # BIT002 only, or BIT016 only


class _Check:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def fail(self, line: int | None, element: str | None, message: str) -> None:
        self.findings.append(Finding(line, element, Code.BIT002, message))

    def attributes(self, node: Node, path: str) -> None:
        allowed = _ATTRIBUTES.get(node.name, ())
        for name, _ in node.attributes:
            if name not in allowed:
                self.fail(node.line, path, f"Unknown attribute {quote(name)}.")

    def leaf(self, node: Node, path: str) -> None:
        self.attributes(node, path)
        for child in node.children:
            self.fail(child.line, path, f"{node.name} cannot hold elements.")

    def container(
        self, node: Node, path: str, expected: Sequence[str]
    ) -> dict[str, Node]:
        """Check one container whose children each occur at most once;
        returns the first occurrence of each canonical child."""
        self.attributes(node, path)
        if node.text.strip(_XML_SPACE):
            self.fail(node.line, path, f"Text is not allowed in {node.name}.")
        found: dict[str, Node] = {}
        last = -1
        for child in node.children:
            if child.name not in expected:
                self.fail(child.line, path, f"Unknown element {quote(child.name)}.")
            elif child.name in found:
                self.fail(
                    child.line,
                    f"{path}/{child.name}",
                    f"{child.name} appears more than once.",
                )
            else:
                found[child.name] = child
                index = expected.index(child.name)
                if index < last:
                    self.fail(
                        child.line,
                        f"{path}/{child.name}",
                        f"{child.name} is out of order.",
                    )
                last = max(last, index)
        for name in expected:
            if name not in found and name not in _OPTIONAL:
                self.fail(node.line, f"{path}/{name}", f"{name} is missing.")
        return found


def _value(node: Node, path: str) -> RawValue:
    return RawValue(node.text, node.line, path)


def _attribute(node: Node, name: str, path: str) -> RawValue | None:
    for key, value in node.attributes:
        if key == name:
            return RawValue(value, node.line, path)
    return None


def _plugin(check: _Check, node: Node, index: int) -> ParsedPlugin | None:
    path = plugin_path(index)
    found = check.container(node, path, _PLUGIN)
    for name, child in found.items():
        check.leaf(child, f"{path}/{name}")
    if any(name not in found for name in _PLUGIN if name not in _OPTIONAL):
        return None

    def opt(name: str) -> RawValue | None:
        child = found.get(name)
        return None if child is None else _value(child, f"{path}/{name}")

    execute = found["Execute"]
    return ParsedPlugin(
        index=index,
        line=node.line,
        plugin_name=_value(found["PluginName"], f"{path}/PluginName"),
        plugin_description=_value(
            found["PluginDescription"], f"{path}/PluginDescription"
        ),
        plugin_id=_value(found["PluginId"], f"{path}/PluginId"),
        execute=_value(execute, f"{path}/Execute"),
        timeout=_attribute(execute, "timeout", f"{path}/Execute/@timeout"),
        operator=opt("Operator"),
        expected_result=opt("ExpectedResult"),
    )


def check(root: Node, pi_lines: Sequence[int] = ()) -> StructureResult:
    """Check the tree from parse_bit (TASK-141) and build the ParsedPolicy."""
    chk = _Check()
    for line in pi_lines:
        chk.fail(line, None, "Processing instructions are not allowed.")
    if root.name != "Policy":
        chk.fail(root.line, None, "The root element must be Policy.")
        return StructureResult(None, tuple(chk.findings))
    top = chk.container(root, "Policy", _POLICY)
    for name in ("PolicyName", "PolicyDescription", "PolicyStatus"):
        if name in top:
            chk.leaf(top[name], f"Policy/{name}")
    family = top.get("Family")
    fam = chk.container(family, "Policy/Family", _FAMILY) if family else {}
    if "FamilyName" in fam:
        chk.leaf(fam["FamilyName"], "Policy/Family/FamilyName")
    plugins: list[ParsedPlugin | None] = []
    groups = top.get("PluginsGroups")
    if groups is not None:
        chk.attributes(groups, "Policy/PluginsGroups")
        if groups.text.strip(_XML_SPACE):
            chk.fail(
                groups.line,
                "Policy/PluginsGroups",
                "Text is not allowed in PluginsGroups.",
            )
        for child in groups.children:
            if child.name == "Plugin":
                plugins.append(_plugin(chk, child, len(plugins) + 1))
            else:
                chk.fail(
                    child.line,
                    "Policy/PluginsGroups",
                    f"Unknown element {quote(child.name)}.",
                )
        if not plugins:
            chk.fail(
                groups.line, "Policy/PluginsGroups", "PluginsGroups holds no Plugin."
            )
    if chk.findings:
        ordered = sorted(chk.findings, key=lambda f: f.line or 0)
        return StructureResult(None, tuple(ordered))
    version = _attribute(root, "formatVersion", "Policy/@formatVersion")
    parsed = ParsedPolicy(
        line=root.line,
        format_version=version,
        policy_name=_value(top["PolicyName"], "Policy/PolicyName"),
        policy_description=_value(top["PolicyDescription"], "Policy/PolicyDescription"),
        policy_status=_value(top["PolicyStatus"], "Policy/PolicyStatus"),
        family_name=_value(fam["FamilyName"], "Policy/Family/FamilyName"),
        plugins=tuple(p for p in plugins if p is not None),
    )
    findings: tuple[Finding, ...] = ()
    if version is not None and version.text not in FORMAT_VERSIONS:
        findings = (
            Finding(
                version.line,
                version.path,
                Code.BIT016,
                f"formatVersion {quote(version.text)} is not supported (only 1.0).",
            ),
        )
    return StructureResult(parsed, findings)
