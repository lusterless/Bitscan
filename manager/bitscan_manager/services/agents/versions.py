"""Debian version ordering for agent versions (TS §3.3, §6.5; owner decision
2026-11-14): the heartbeat sends max_parallel_jobs only to agents 0.5.0 or
later, because older agents refuse an unknown key.

`compare` is dpkg's algorithm (deb-version(7)): epoch numerically, then the
upstream version and the revision, each compared in alternating non-digit
and digit runs, where `~` sorts before everything, even the end of the
string, and letters sort before other characters. Pure; no I/O.
"""

from __future__ import annotations

from typing import Final

PARALLEL_JOBS_SINCE: Final = "0.5.0"


def _order(c: str) -> int:
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isascii() and c.isalpha():
        return ord(c)
    return ord(c) + 256


def _part(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) or j < len(b):
        diff = 0
        while (i < len(a) and not a[i].isdigit()) or (
            j < len(b) and not b[j].isdigit()
        ):
            ac = _order(a[i]) if i < len(a) and not a[i].isdigit() else 0
            bc = _order(b[j]) if j < len(b) and not b[j].isdigit() else 0
            if ac != bc:
                return -1 if ac < bc else 1
            if i < len(a) and not a[i].isdigit():
                i += 1
            if j < len(b) and not b[j].isdigit():
                j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not diff:
                diff = (a[i] > b[j]) - (a[i] < b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if diff:
            return diff
    return 0


def _split(v: str) -> tuple[int, str, str]:
    epoch, sep, rest = v.partition(":")
    if not sep:
        epoch, rest = "0", v
    upstream, dash, revision = rest.rpartition("-")
    if not dash:
        upstream, revision = rest, ""
    return int(epoch) if epoch.isdigit() else 0, upstream, revision


def compare(a: str, b: str) -> int:
    """-1, 0 or 1 as dpkg --compare-versions orders a and b."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    return _part(ua, ub) or _part(ra, rb)


def sends_parallel_jobs(agent_version: str) -> bool:
    """True when the agent understands max_parallel_jobs (0.5.0 or later). A
    version that does not start with a digit (a development build) is
    treated as older: an unknown key would make an old agent refuse the
    whole answer, while a missing key costs a new agent nothing."""
    if not agent_version[:1].isdigit():
        return False
    return compare(agent_version, PARALLEL_JOBS_SINCE) >= 0
