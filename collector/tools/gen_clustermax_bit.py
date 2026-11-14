#!/usr/bin/env python3
"""Generate bits/samples/clustermax-0.3.0.bit from the ClusterMAX check list.

Input:  clustermax-0.3.0-checks.txt, the output of `cmax audit --show -vvv`
        for ClusterMAX 0.3.0 (lusterless/clustermax f849f46).
Ids:    plugin-ids.json keeps every PluginId stable across regenerations;
        new entries get a fresh lowercase uuid4.
Output: ../../bits/samples/clustermax-0.3.0.bit

Each check plugin asks cmax-helper (TS §3.8) for one line of the report:
`<PASS|FAIL|WARNING|n/a> observed=<value>`. PASS and n/a (ClusterMAX SKIPPED)
pass; WARNING, FAIL and anything else fail (owner decisions).
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
CHECKS = HERE / "clustermax-0.3.0-checks.txt"
IDS = HERE / "plugin-ids.json"
OUT = HERE.parent.parent / "bits" / "samples" / "clustermax-0.3.0.bit"

GROUP = re.compile(r"^\[(\w+)\] (.+) \((\d+) checks\)$")
CHECK = re.compile(r"^  ([A-Za-z0-9_.-]+): (.+)$")
PASSING = r"^(PASS|n/a)( |$)"

POLICY_DESCRIPTION = (
    "The 81 checks of ClusterMAX 0.3.0 (lusterless/clustermax f849f46, cmax audit -vvv -y). "
    "Needs the clustermax-collector package on the host (Technical Specification 3.8); "
    "without it every plugin prints NOHELPER and fails. Every scan runs a fresh audit: the first "
    "plugin of the scan's job on a host starts one root ClusterMAX audit through cmax-helper, and "
    "every plugin of that job reads its own line from that audit's report, which is kept only in "
    "the helper's memory. ClusterMAX PASS and SKIPPED (printed as n/a) "
    "pass; WARNING and FAIL fail. With -y, ClusterMAX auto-detects standalone, Slurm or "
    "Kubernetes on each targeted host, so target only the hosts that should run it, for example "
    "with a dedicated tag."
)


def read_checks() -> list[tuple[str, int, str, str]]:
    """(group name, group number, check id, label) in `cmax audit --show` order."""
    out: list[tuple[str, int, str, str]] = []
    group, number = "", 0
    for line in CHECKS.read_text(encoding="utf-8").splitlines():
        if m := GROUP.match(line):
            group, number = m.group(2), number + 1
        elif m := CHECK.match(line):
            out.append((group, number, m.group(1), m.group(2)))
    return out


def plugin(
    name: str,
    description: str,
    pid: str,
    execute: str,
    timeout: int,
    operator: str,
    expected: str,
) -> str:
    return (
        "    <Plugin>\n"
        f"      <PluginName>{escape(name)}</PluginName>\n"
        f"      <PluginDescription>{escape(description)}</PluginDescription>\n"
        f"      <PluginId>{pid}</PluginId>\n"
        f'      <Execute timeout="{timeout}"><![CDATA[\n        {execute}\n      ]]></Execute>\n'
        f"      <Operator>{operator}</Operator>\n"
        f"      <ExpectedResult>{escape(expected)}</ExpectedResult>\n"
        "    </Plugin>\n"
    )


def main() -> int:
    checks = read_checks()
    if len(checks) != 81 or len({c[2] for c in checks}) != 81:
        print(f"expected 81 unique checks, found {len(checks)}", file=sys.stderr)
        return 1
    ids: dict[str, str] = json.loads(IDS.read_text()) if IDS.exists() else {}

    def pid(key: str) -> str:
        if key not in ids:
            ids[key] = str(uuid.uuid4())
        return ids[key]

    plugins = [
        plugin(
            "0.1 - collect - Run the ClusterMAX audit",
            "Asks cmax-helper to run cmax audit -vvv -y as root for this scan, unless an audit is "
            "already running, which this scan then shares. Prints started or running with the run "
            "id every plugin of this scan reads; NOHELPER when the collector package is not "
            "installed.",
            pid("collect"),
            "cmax-trigger collect",
            30,
            "regex",
            r"^(started|running) [0-9a-f]{32}$",
        ),
        plugin(
            "0.2 - header - ClusterMAX target",
            "Waits for the audit and prints the target block ClusterMAX reported: command, target, "
            "host, system, access and selection. Evidence of what ran on this host.",
            pid("header"),
            "cmax-trigger get header",
            600,
            "regex",
            r"^Command: cmax audit; ",
        ),
        plugin(
            "0.3 - status - ClusterMAX run status and version",
            "Waits for the audit, then prints ok <age-seconds> <cmax-version>. Passes only when the "
            "audit finished without error and the installed ClusterMAX is 0.3.0.",
            pid("status"),
            "cmax-trigger get header >/dev/null; cmax-trigger get status",
            600,
            "regex",
            r"^ok [0-9]+ 0\.3\.0$",
        ),
    ]
    index: dict[int, int] = {}
    for group, number, check_id, label in checks:
        index[number] = index.get(number, 0) + 1
        ref = f"{number}.{index[number]}"
        plugins.append(
            plugin(
                f"{ref} - {check_id} - {label}",
                f"ClusterMAX 0.3.0 check {check_id} ({group}). Prints the ClusterMAX verdict and its "
                "Observed value from this host's report. PASS and SKIPPED (n/a) pass; WARNING and "
                "FAIL fail; MISSING, ERROR, TIMEOUT or NOHELPER fail.",
                pid(check_id),
                f"cmax-trigger get {check_id}",
                600,
                "regex",
                PASSING,
            )
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Policy formatVersion="1.0">\n'
        "  <PolicyName>ClusterMAX 0.3.0 audit checks</PolicyName>\n"
        f"  <PolicyDescription>{escape(POLICY_DESCRIPTION)}</PolicyDescription>\n"
        "  <PolicyStatus>enabled</PolicyStatus>\n"
        "  <Family>\n    <FamilyName>Clustermax</FamilyName>\n  </Family>\n"
        "  <PluginsGroups>\n" + "".join(plugins) + "  </PluginsGroups>\n</Policy>\n"
    )
    OUT.write_text(xml, encoding="utf-8")
    IDS.write_text(json.dumps(ids, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({len(plugins)} plugins)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
