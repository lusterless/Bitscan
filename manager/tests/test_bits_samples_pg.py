"""TP-M7-27 (TASK-174, TASK-175): gate G59 and the sample script rules.

CHK-M7-300 to -303 (tests/m7/test-plan.md). Expected values come from the
spec and the approved answers, not from the samples: REQ-179 (1) to (4);
#111 (two samples; the 24.04 one starts with the SR §1.1 plugin byte for
byte; each PolicyDescription ends with the fixed note; PolicyStatus enabled);
SR §1.1 (the canonical example), §2.4 (script rules), §4.2 (BIT102); TS §3.7
L500-L502 (the runner has only CAP_DAC_READ_SEARCH: commands that need uid 0
fail, files are read instead), §8.6 L1329-L1337 (the default redaction
patterns, read from the spec text here); G59 in work/tasks.md (all samples
together in one fresh catalog, the SR §1.1 example alone in another, each
`success`, no Reject finding, no BIT102).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import re2  # type: ignore[import-untyped]
from defusedxml import ElementTree

from .bit_unit import REPO, SAMPLES, fixture
from .catalog_rows import app
from .conftest import own_migrated_server
from .test_import_pipeline_pg import Env, make_env

pytestmark = pytest.mark.pg

SPEC_SR = REPO / "docs" / "spec" / "bit_Schema_Reference.md"
SPEC_TS = REPO / "docs" / "spec" / "Technical_Specification.md"
NOTE = "Control numbers are not yet confirmed against the CIS benchmark copy (TS §8.5)."
WS = " \t\r\n"
SAMPLE_FILES = sorted(SAMPLES.glob("*.bit"))


def fenced_after(path: Path, heading: str, lang: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    open_ = text.index(f"```{lang}\n", start) + len(f"```{lang}\n")
    return text[open_ : text.index("```", open_)]


SR_EXAMPLE = fenced_after(SPEC_SR, "### 1.1 Canonical example", "xml")
REDACTION = [
    re2.compile(line)
    for line in fenced_after(SPEC_TS, "**Default redaction patterns**", "text")
    .strip("\n")
    .split("\n")
]


def plugin_block(text: str, n: int = 1) -> str:
    """The n-th `<Plugin>…</Plugin>` source text (string search, not XML)."""
    i = -1
    for _ in range(n):
        i = text.index("<Plugin>", i + 1)
    return text[i : text.index("</Plugin>", i) + len("</Plugin>")]


def parsed(path: Path) -> Any:
    return ElementTree.fromstring(path.read_bytes(), forbid_dtd=True)


def value(el: Any, tag: str) -> str:
    node = el.find(tag)
    assert node is not None, tag
    return str(node.text or "").strip(WS)


def plugins(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    out = []
    for n, p in enumerate(parsed(path).findall("PluginsGroups/Plugin"), 1):
        block = plugin_block(text, n)
        raw = block[block.index("<Execute") : block.index("</Execute>")]
        out.append(
            {
                "sample": path.name,
                "name": value(p, "PluginName"),
                "uuid": value(p, "PluginId"),
                "execute": value(p, "Execute"),
                "raw_execute": raw[raw.index(">") + 1 :],
                "timeout": p.find("Execute").get("timeout", "60"),
                "operator": value(p, "Operator").lower(),
                "expected": value(p, "ExpectedResult"),
            }
        )
    return out


ALL_PLUGINS = [p for f in SAMPLE_FILES for p in plugins(f)]


def fresh_env(tmp_path: Path) -> Iterator[Env]:
    (tmp_path / "creds").mkdir()
    with own_migrated_server(tmp_path / "creds") as s:
        yield from make_env(s, tmp_path)


@pytest.fixture
def fresh(tmp_path: Path) -> Iterator[Env]:
    yield from fresh_env(tmp_path)


# CHK-M7-300 / REQ-179 (1): G59 -----------------------------------------------------


def test_g59_all_samples_together_in_one_fresh_catalog(fresh: Env) -> None:
    assert len(SAMPLE_FILES) == 2  # #111: exactly the two samples
    outcomes = {}
    for path in SAMPLE_FILES:
        out = fresh.imp(path.read_bytes(), path.name, mode="manual")
        assert out.outcome == "success", (path.name, out.findings)
        assert [f for f in out.findings if f.rejects] == [], path.name
        assert [f for f in out.findings if f.code.value == "BIT102"] == []
        outcomes[path.name] = out
    with app(fresh.server) as c:
        for path in SAMPLE_FILES:
            out = outcomes[path.name]
            ids = [p["uuid"] for p in plugins(path)]
            rows = c.execute(
                "SELECT pp.plugin_uuid::text, pp.sort_order, p.owner_policy_id,"
                " p.state::text FROM policy_plugin pp JOIN plugin p USING"
                " (plugin_uuid) WHERE pp.policy_id = %s ORDER BY pp.sort_order",
                (out.policy_id,),
            ).fetchall()
            assert [r[0] for r in rows] == ids  # every plugin, in file order
            assert {(r[2], r[3]) for r in rows} == {(out.policy_id, "active")}
            assert out.plugins_added == len(ids)  # nothing claimed from the other
        live = c.execute(
            "SELECT count(*) FROM policy WHERE deleted_at IS NULL"
        ).fetchone()
    assert live == (len(SAMPLE_FILES),)


def test_g59_the_sr_example_alone_in_another_fresh_catalog(fresh: Env) -> None:
    out = fresh.imp(fixture("valid/sr-1.1-example.bit"), "sr.bit")
    assert out.outcome == "success" and out.findings == ()


def test_the_fixture_is_the_spec_example() -> None:
    assert fixture("valid/sr-1.1-example.bit").decode("utf-8") == SR_EXAMPLE


# CHK-M7-300 / REQ-179 (1): distinct names and ids -----------------------------------


def test_policy_names_and_plugin_ids_are_distinct_across_the_samples() -> None:
    names = [value(parsed(f), "PolicyName") for f in SAMPLE_FILES]
    assert len(set(names)) == len(names), names
    ids = [p["uuid"] for p in ALL_PLUGINS]
    assert len(set(ids)) == len(ids), sorted(i for i in ids if ids.count(i) > 1)
    assert all(
        re2.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", i) for i in ids
    )
    by_sample = {f.name: {p["uuid"] for p in plugins(f)} for f in SAMPLE_FILES}
    a, b = by_sample.values()
    assert a.isdisjoint(b)


# CHK-M7-302 / REQ-179 (3), (4) ------------------------------------------------


def test_the_2404_sample_starts_with_the_sr_plugin_byte_for_byte() -> None:
    text = (SAMPLES / "cis-ubuntu-24.04-l1-server.bit").read_text(encoding="utf-8")
    assert plugin_block(text) == plugin_block(SR_EXAMPLE)
    root = parsed(SAMPLES / "cis-ubuntu-24.04-l1-server.bit")
    assert value(root, "PolicyName") == "CIS Ubuntu 24.04 Level 1 - Server"


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.name)
def test_description_note_and_status(path: Path) -> None:
    root = parsed(path)
    assert value(root, "PolicyDescription").endswith(NOTE)
    assert value(root, "PolicyStatus") == "enabled"
    assert root.get("formatVersion") == "1.0"
    assert 10 <= len(root.findall("PluginsGroups/Plugin")) <= 20  # about 15


# CHK-M7-303 / REQ-179 (2): the SR §2.4 script rules, one row per plugin --------------

# Words that start a command (after a separator, `$(`, `then`, `do` …).
CMD = r"(?:^|[;&|(`\n]|\$\(|\bthen\b|\bdo\b|\belse\b)\s*"
NEVER = {
    "xargs": CMD + r"xargs\b",
    "find -exec": r"\bfind\b[^\n|;]*\s-(?:exec|execdir|ok|okdir)\b",
    "eval": CMD + r"eval\b",
    "source": CMD + r"(?:source|\.)\s",
    "exec": CMD + r"exec\b",
    "cd": CMD + r"cd\b",
    "sudo": CMD + r"(?:sudo|doas|su)\b",
    "shell script": CMD + r"(?:sh|bash|dash)\b",
    "user-writable path run": CMD
    + r"(?:/tmp/|/var/tmp/|/dev/shm/|/home/|~|\./|\$HOME)",
    "plain mount table": r"/proc/(?:self/)?mounts\b|/etc/mtab\b|/proc/self/mountinfo",
    "mount command": CMD + r"mount\b",
    # TS §3.7 L502: these need uid 0 (or a capability the runner lacks)
    "needs uid 0": CMD + r"(?:nft|auditctl|iptables|ip6tables|aa-status|"
    r"apparmor_status|sshd\s+-T|ufw\s+status|sysctl\s+-w)\b",
    "prompt": CMD + r"read\s+-p\b|\bselect\b",
}


@pytest.mark.parametrize(
    "plugin", ALL_PLUGINS, ids=[f"{p['sample']}:{p['name'][:40]}" for p in ALL_PLUGINS]
)
def test_script_rules(plugin: dict[str, Any]) -> None:
    raw = plugin["raw_execute"].strip(WS)
    assert raw.startswith("<![CDATA[") and raw.endswith("]]>")  # Execute in CDATA
    ex = plugin["execute"]
    hits = [rule for rule, pat in NEVER.items() if re2.search(pat, ex)]
    assert hits == []
    if "findmnt" in ex:  # the host's view, never the runner's private mounts
        assert all("--task 1" in line for line in ex.split("\n") if "findmnt" in line)
    if "mountinfo" in ex:
        assert "/proc/1/mountinfo" in ex
    assert 1 <= int(plugin["timeout"]) <= 600
    # The compared value is never something a default redaction pattern hides.
    exp = plugin["expected"]
    assert [p.pattern for p in REDACTION if p.search(exp)] == []
    # Only the observed value is printed: a short value, not a sentence.
    if plugin["operator"] in ("equals", "not_equals", "contains", "not_contains"):
        assert len(exp.split()) <= 4 and not exp.endswith(".")


def test_the_redaction_patterns_were_read_from_the_spec() -> None:
    assert len(REDACTION) == 5
    assert REDACTION[0].search("root:$6$abc$def:19000")  # a shadow hash field
    assert not any(p.search("install ok installed") for p in REDACTION)


@pytest.mark.parametrize(
    ("rule", "text"),
    [
        ("xargs", "find /etc -print | xargs cat"),
        ("find -exec", "find /etc -name x -exec cat {} +"),
        ("cd", "cd /tmp && cat x"),
        ("source", ". /etc/default/x"),
        ("user-writable path run", "/tmp/x.sh"),  # noqa: S108 - scanned text
        ("plain mount table", "grep nodev /proc/mounts"),
        ("needs uid 0", "nft list ruleset"),
        ("needs uid 0", "x=$(auditctl -l)"),
        ("shell script", "sh /usr/local/x"),
    ],
)
def test_the_script_rule_scan_can_fail(rule: str, text: str) -> None:
    assert re2.search(NEVER[rule], text)


def test_the_script_rule_scan_passes_the_spec_example() -> None:
    ex = plugins(SAMPLES / "cis-ubuntu-24.04-l1-server.bit")[0]["execute"]
    assert [r for r, pat in NEVER.items() if re2.search(pat, ex)] == []
    assert not re2.search(NEVER["cd"], "findmnt --task 1 -n -o OPTIONS /tmp")
