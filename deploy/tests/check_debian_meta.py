"""Static checks of the agent package metadata in deploy/debian/ (M4 TP-M4-07, REQ-106).

Usage: python deploy/tests/check_debian_meta.py [--root DIR]
Exit 0 when every check passes. Expected values come from TS §3.1 (L158-L159),
PD-26 (a) (debhelper compat 13, amd64 only), #90 (M6: the first supported
release is 0.1.0, package 0.1.0-1, so the first entry has no pre-release "~")
and the decisions of 2026-10-24 (arm64 dropped from v1), not from the files.

Checks:
- rules: dh_installsystemd is called so that bitscan-agent.service and
  bitscan-runner.socket are enabled, started and restarted on upgrade (no
  flags), bitscan-runner.service gets exactly --no-enable, and both capread
  units get exactly --no-enable --no-start; each of the five units is named
  exactly once and no call without unit names exists.
- rules: the five agent units are installed from debian/systemd/ with
  mode 0644, unchanged (install -m 0644, no sed or cat).
- control: source and package bitscan-agent, Architecture amd64 only,
  debhelper-compat (= 13), Rules-Requires-Root: no, Depends with adduser and
  ${misc:Depends}.
- changelog: first entry bitscan-agent (X.Y.Z-R), a release version with no
  "~" (#90), and a parseable RFC 2822 trailer date (the SOURCE_DATE_EPOCH
  source); every trailer's weekday matches its date, and the dates strictly
  decrease down the file (lintian's new-date rules).
- copyright: DEP-5 1.0; every Files stanza has Copyright and License; every
  short licence name has its text (inline or a standalone License stanza).
- bitscan-agent.install (TASK-096, CHK-M4-122): exactly the three binaries to
  /usr/sbin and the D-Bus policy (from the verbatim dbus/ copy) to
  /etc/dbus-1/system.d (TS §3.1 L158, L161); no globs.
- source/format: one line, 3.0 (native) or 3.0 (quilt) (PD-26).
- no "arm64" anywhere in deploy/debian or deploy/dbus.
"""

from __future__ import annotations

import argparse
# Only repository files are matched (trusted, not untrusted input), and the
# script must run on a bare CI Python without google-re2.
import re  # noqa: TID251
import shlex
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

UNITS = (
    "bitscan-agent.service",
    "bitscan-runner.socket",
    "bitscan-runner.service",
    "bitscan-capread.socket",
    "bitscan-capread.service",
)
# TS §3.1 L159: the flag set each unit must get from dh_installsystemd
EXPECTED_FLAGS: dict[str, frozenset[str]] = {
    "bitscan-agent.service": frozenset(),
    "bitscan-runner.socket": frozenset(),
    "bitscan-runner.service": frozenset({"--no-enable"}),
    "bitscan-capread.socket": frozenset({"--no-enable", "--no-start"}),
    "bitscan-capread.service": frozenset({"--no-enable", "--no-start"}),
}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+-[1-9]\d*$")


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.checks = 0

    def ok(self, cond: bool, what: str) -> None:
        self.checks += 1
        if cond:
            print(f"PASS {what}")
        else:
            self.failures += 1
            print(f"FAIL {what}")


def make_targets(text: str) -> dict[str, list[str]]:
    """Map each make target to its recipe lines (tab-prefixed, comments dropped)."""
    targets: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.split("\n"):
        if raw.startswith("\t"):
            if current is not None:
                line = raw[1:].strip()
                if line and not line.startswith("#"):
                    targets[current].append(line)
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_%.$@()-]+)\s*:(?!=)", raw)
        if m:
            current = m.group(1)
            targets.setdefault(current, [])
        else:
            current = None
    return targets


def check_rules(debian: Path, r: Report) -> None:
    path = debian / "rules"
    text = path.read_text(encoding="utf-8")
    r.ok(text.startswith("#!/usr/bin/make -f\n"), "rules: #!/usr/bin/make -f shebang")
    r.ok("\r" not in text, "rules: LF line endings")
    targets = make_targets(text)

    calls: list[list[str]] = []
    for name, lines in targets.items():
        for line in lines:
            for part in re.split(r"\s*(?:&&|;)\s*", line):
                words = shlex.split(part)
                if words and words[0] == "dh_installsystemd":
                    calls.append(words[1:])
                    r.ok(
                        name == "override_dh_installsystemd",
                        f"rules: dh_installsystemd called only in override_dh_installsystemd (found in {name})",
                    )
    r.ok(
        "override_dh_installsystemd" in targets,
        "rules: override_dh_installsystemd target present",
    )
    r.ok(len(calls) > 0, "rules: at least one dh_installsystemd call")

    seen: dict[str, list[frozenset[str]]] = {}
    for args in calls:
        flags = frozenset(a for a in args if a.startswith("-"))
        names = [a for a in args if not a.startswith("-")]
        r.ok(
            bool(names),
            f"rules: dh_installsystemd call names its units ({' '.join(args) or 'no arguments'})",
        )
        for n in names:
            r.ok(n in UNITS, f"rules: dh_installsystemd unit {n} is an agent unit")
            seen.setdefault(n, []).append(flags)
    for unit in UNITS:
        got = seen.get(unit, [])
        r.ok(
            len(got) == 1,
            f"rules: {unit} named in exactly one dh_installsystemd call (got {len(got)})",
        )
        if len(got) == 1:
            want = EXPECTED_FLAGS[unit]
            r.ok(
                got[0] == want,
                f"rules: {unit} flags {sorted(got[0]) or '(none)'} == {sorted(want) or '(none)'}",
            )

    # units installed unchanged with mode 0644 from debian/systemd/
    recipe = "\n".join(line for lines in targets.values() for line in lines)
    for unit in UNITS:
        pat = re.compile(
            r"install\s+-m\s*0?644\s+debian/systemd/" + re.escape(unit) + r"\s"
        )
        r.ok(
            bool(pat.search(recipe + "\n")),
            f"rules: {unit} installed with install -m 0644 from debian/systemd/",
        )
    r.ok(
        not re.search(r"\b(sed|awk|perl|cat)\b[^\n]*debian/systemd", recipe),
        "rules: no tool rewrites the unit files",
    )
    r.ok(
        "--without systemd" not in text and "--without=systemd" not in text,
        "rules: dh keeps the systemd addon",
    )


def deb822(text: str) -> list[dict[str, str]]:
    paras: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    last: str | None = None
    for line in text.split("\n"):
        if not line.strip():
            if cur:
                paras.append(cur)
            cur, last = {}, None
            continue
        if line[0] in " \t":
            if last is None:
                raise ValueError(f"continuation without a field: {line!r}")
            cur[last] += "\n" + line
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"not a field: {line!r}")
        if key in cur:
            raise ValueError(f"duplicate field {key}")
        cur[key] = value.strip()
        last = key
    if cur:
        paras.append(cur)
    return paras


def check_control(debian: Path, r: Report) -> None:
    paras = deb822((debian / "control").read_text(encoding="utf-8"))
    r.ok(
        len(paras) == 2, f"control: one source and one binary stanza (got {len(paras)})"
    )
    if len(paras) < 2:
        return
    src, pkg = paras[0], paras[1]
    r.ok(src.get("Source") == "bitscan-agent", "control: Source: bitscan-agent")
    r.ok(bool(src.get("Maintainer")), "control: Maintainer set")
    bd = re.sub(r"\s+", " ", src.get("Build-Depends", ""))
    r.ok(
        "debhelper-compat (= 13)" in bd,
        "control: Build-Depends debhelper-compat (= 13)",
    )
    r.ok(src.get("Rules-Requires-Root") == "no", "control: Rules-Requires-Root: no")
    r.ok(bool(src.get("Standards-Version")), "control: Standards-Version set")
    r.ok(pkg.get("Package") == "bitscan-agent", "control: Package: bitscan-agent")
    r.ok(
        pkg.get("Architecture") == "amd64",
        f"control: Architecture: amd64 only (got {pkg.get('Architecture')!r})",
    )
    deps = [d.strip() for d in re.sub(r"\s+", " ", pkg.get("Depends", "")).split(",")]
    r.ok("${misc:Depends}" in deps, "control: Depends has ${misc:Depends}")
    r.ok(
        any(d.split(" ")[0] == "adduser" for d in deps),
        "control: Depends has adduser (postinst adduser)",
    )
    desc = pkg.get("Description", "")
    synopsis = desc.split("\n", 1)[0]
    r.ok(0 < len(synopsis) <= 80, "control: Description synopsis 1..80 characters")
    r.ok("\n" in desc, "control: Description has an extended part")


def check_changelog(debian: Path, r: Report) -> None:
    text = (debian / "changelog").read_text(encoding="utf-8")
    lines = text.split("\n")
    m = re.match(
        r"^bitscan-agent \(([^)]+)\) (\S+); urgency=(low|medium|high|emergency|critical)$",
        lines[0],
    )
    r.ok(m is not None, f"changelog: first line format ({lines[0]!r})")
    if m:
        r.ok(
            bool(VERSION_RE.match(m.group(1))),
            f"changelog: version {m.group(1)} is a release X.Y.Z-R (no ~)",
        )
    trailers = [ln for ln in lines if ln.startswith(" -- ")]
    r.ok(len(trailers) >= 1, "changelog: has a trailer line")
    if trailers:
        t = re.match(r"^ -- (.+ <[^>]+>)  (.+)$", trailers[0])
        r.ok(t is not None, "changelog: trailer ' -- Name <mail>  date' (two spaces)")
        if t:
            try:
                dt = parsedate_to_datetime(t.group(2))
                r.ok(
                    dt.tzinfo is not None,
                    f"changelog: trailer date parses (epoch {int(dt.timestamp())})",
                )
            except (TypeError, ValueError):
                r.ok(False, f"changelog: trailer date parses ({t.group(2)!r})")
    dates = []
    for ln in trailers:
        w = re.match(r"^ -- .+ <[^>]+>  (\w{3}), (.+)$", ln)
        if not w:
            r.ok(False, f"changelog: trailer has a weekday ({ln!r})")
            continue
        try:
            dt = parsedate_to_datetime(f"{w.group(1)}, {w.group(2)}")
        except (TypeError, ValueError):
            r.ok(False, f"changelog: trailer date parses ({ln!r})")
            continue
        r.ok(
            dt.strftime("%a") == w.group(1),
            f"changelog: weekday {w.group(1)} matches {dt.date().isoformat()}",
        )
        dates.append(dt)
    r.ok(
        all(a > b for a, b in zip(dates, dates[1:])),
        f"changelog: {len(dates)} trailer dates strictly decrease down the file",
    )
    r.ok(
        text.endswith("\n") and "\r" not in text,
        "changelog: LF endings and final newline",
    )


def check_copyright(debian: Path, r: Report) -> None:
    paras = deb822((debian / "copyright").read_text(encoding="utf-8"))
    head = paras[0] if paras else {}
    r.ok(
        head.get("Format")
        == "https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/",
        "copyright: DEP-5 1.0 Format line",
    )
    files = [p for p in paras if "Files" in p]
    r.ok(
        any(p["Files"].split()[0] == "*" for p in files), "copyright: a Files: * stanza"
    )
    standalone = {
        p["License"].split("\n", 1)[0].strip()
        for p in paras
        if "License" in p and "Files" not in p
    }
    for p in files:
        first = p["Files"].split()[0]
        r.ok(
            "Copyright" in p and "License" in p,
            f"copyright: Files {first} has Copyright and License",
        )
        lic = p.get("License", "")
        short = lic.split("\n", 1)[0].strip()
        has_text = "\n" in lic or short in standalone
        r.ok(has_text, f"copyright: licence {short!r} of Files {first} has its text")


# TS §3.1 L158, L161 (TASK-096, CHK-M4-122): what bitscan-agent.install must map
INSTALL_MAP = {
    "bitscan-agent": "usr/sbin",
    "bitscan-runner": "usr/sbin",
    "bitscan-capread": "usr/sbin",
    "bitscan-runner.conf": "etc/dbus-1/system.d",
}


def check_install(debian: Path, r: Report) -> None:
    text = (debian / "bitscan-agent.install").read_text(encoding="utf-8")
    r.ok(
        "\r" not in text and text.endswith("\n"),
        "install: LF endings and final newline",
    )
    entries: list[tuple[str, str]] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = line.split()
        r.ok(len(words) == 2, f"install: line {line!r} is 'source destination'")
        if len(words) != 2:
            continue
        r.ok(
            not any(c in words[0] for c in "*?[{"),
            f"install: source {words[0]} names one file (no glob)",
        )
        entries.append((words[0], words[1].strip("/")))
    names = sorted(src.rsplit("/", 1)[-1] for src, _ in entries)
    r.ok(
        names == sorted(INSTALL_MAP),
        f"install: exactly the three binaries and the D-Bus policy (got {names})",
    )
    for src, dest in entries:
        base = src.rsplit("/", 1)[-1]
        want = INSTALL_MAP.get(base)
        r.ok(dest == want, f"install: {base} -> /{dest} (want /{want})")
        if base == "bitscan-runner.conf":
            r.ok(
                src.endswith("dbus/bitscan-runner.conf"),
                f"install: policy taken from the verbatim dbus/ copy ({src})",
            )


def check_source_format(debian: Path, r: Report) -> None:
    text = (debian / "source" / "format").read_text(encoding="utf-8")
    r.ok(
        text in ("3.0 (native)\n", "3.0 (quilt)\n"),
        f"source/format: one line '3.0 (native)' or '3.0 (quilt)' (got {text!r})",
    )


def check_no_arm64(root: Path, r: Report) -> None:
    hits = []
    for folder in (root / "deploy" / "debian", root / "deploy" / "dbus"):
        for f in sorted(folder.rglob("*")):
            if f.is_file() and b"arm64" in f.read_bytes():
                hits.append(str(f.relative_to(root)))
    r.ok(not hits, f"no arm64 in deploy/debian or deploy/dbus {hits or ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root)
    debian = root / "deploy" / "debian"
    r = Report()
    for name, fn in (
        ("rules", check_rules),
        ("control", check_control),
        ("changelog", check_changelog),
        ("copyright", check_copyright),
        ("bitscan-agent.install", check_install),
        ("source/format", check_source_format),
    ):
        if not (debian / name).is_file():
            r.ok(False, f"{name}: file present")
            continue
        try:
            fn(debian, r)
        except ValueError as exc:
            r.ok(False, f"{name}: parses ({exc})")
    check_no_arm64(root, r)
    print(
        "FAIL" if r.failures else "OK",
        f"{r.checks - r.failures}/{r.checks} checks passed",
    )
    return 1 if r.failures else 0


if __name__ == "__main__":
    sys.exit(main())
