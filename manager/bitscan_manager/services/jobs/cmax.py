"""ClusterMAX scans (TS §3.8, §4.4; owner decision 2026-11-23).

A policy whose Family is `Clustermax` is a ClusterMAX profile. Its plugins
name the checks (`cmax-check <check-id>`; the 0.5.x form `cmax-trigger get
<check-id>` is read too, so an old import still names its checks) and are
never run as commands. A scan of it builds one fixed `cluster_audit` job per
scanner; the only inputs are a target mode, a kubeconfig reference and the
allow-listed variables below, each checked against its RE2 pattern. Pure; no
I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

import re2  # type: ignore[import-untyped]

FAMILY: Final = "Clustermax"
TARGETS: Final = ("auto", "standalone", "slurm", "k8s")
SCANNER_HELPER: Final = "scanner"
SCANNER_SINCE: Final = "0.6.0"
MAX_SCANNERS: Final = 50
RESERVED: Final = frozenset({"header", "status"})
_SKIPPED: Final = frozenset({"collect", "wait"})

_DNS: Final = r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?"
_NAMESPACE: Final = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
# TS §3.8: changing this list is a spec change. Image, command, file and URL
# variables are never allowed.
ALLOWED_VARS: Final[Mapping[str, str]] = {
    "CLUSTERMAX_K8S_GPU_DRA": r"[01]",
    "CLUSTERMAX_K8S_GPU_DRA_DEVICE_CLASS": _DNS,
    "CLUSTERMAX_K8S_GPU_DRA_DRIVER": _DNS,
    "CLUSTERMAX_AUDIT_K8S_NAMESPACE": _NAMESPACE,
    "CLUSTERMAX_AUDIT_TENANT_NAMESPACE": _NAMESPACE,
}
_COMPILED: Final = {
    name: re2.compile(pattern) for name, pattern in ALLOWED_VARS.items()
}
_CHECK: Final = re2.compile(r"(?:cmax-check|cmax-trigger get) ([A-Za-z0-9_.-]{1,128})")


class InvalidOptions(Exception):
    """The ClusterMAX options are refused (400); the message names the field."""


@dataclass(frozen=True)
class Options:
    target: str = "auto"
    kubeconfig_id: int | None = None
    vars: Mapping[str, str] = field(default_factory=dict)

    def stored(self) -> dict[str, object]:
        """scan.clustermax: the choices, never a kubeconfig."""
        return {
            "target": self.target,
            "kubeconfig_id": self.kubeconfig_id,
            "vars": dict(self.vars),
        }


def parse_options(
    target: str | None, kubeconfig_id: int | None, variables: Mapping[str, str] | None
) -> Options:
    chosen = target or ("k8s" if kubeconfig_id is not None else "auto")
    if chosen not in TARGETS:
        raise InvalidOptions("cmax.target")
    if kubeconfig_id is not None and chosen != "k8s":
        raise InvalidOptions("cmax.target")
    checked: dict[str, str] = {}
    for name, value in (variables or {}).items():
        pattern = _COMPILED.get(name)
        if (
            pattern is None
            or not isinstance(value, str)
            or pattern.fullmatch(value) is None
        ):
            raise InvalidOptions(f"cmax.vars.{name}" if pattern else "cmax.vars")
        checked[name] = value
    return Options(chosen, kubeconfig_id, checked)


def check_id(execute: str) -> str | None:
    """The check a ClusterMAX plugin names, or None for a 0.5.x helper plugin
    (collect, wait) that has no check of its own."""
    match = _CHECK.fullmatch(execute.strip())
    if match is None or match.group(1) in _SKIPPED:
        return None
    return str(match.group(1))


@dataclass(frozen=True)
class Check:
    plugin_uuid: UUID
    check_id: str


def checks(plugins: Sequence[tuple[UUID, str]]) -> list[Check]:
    """One Check per plugin that names one, in policy order."""
    out: list[Check] = []
    for plugin_uuid, execute in plugins:
        cid = check_id(execute)
        if cid is not None:
            out.append(Check(plugin_uuid, cid))
    return out
